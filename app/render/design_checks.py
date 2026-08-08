# -*- coding: utf-8 -*-
"""W3b 결정론 디자인 게이트 — `gating_report.design_checks` (LLM 0토큰).

NORTHSTAR_REDESIGN §N3-5 "품질 게이트 이원화"의 **결정론 게이트** 쪽.
`review_badges`와 같은 계열이다: 렌더 산출물을 파싱해 신호를 세고, 판단은 사람/디렉터에게 넘긴다.

**정직성 계약(S6-1 계열 — 리포트가 자기 한계를 말한다)**
- 입력은 **병합된 `deck.html` 마크업뿐**. 브라우저 레이아웃(실제 픽셀·폰트 메트릭)은 측정하지 않는다.
  그래서 오버플로는 확정이 아니라 **위험 신호**(`overflow_risk`)로만 표기한다 — 이름이 곧 한계 고지.
- 임계값은 **잠정(미교정)**. N3-5 완료 정의 = "게이트 점수가 사람 평가와 방향 일치".
  그 검증 전까지 `thresholds.calibration = "잠정(사람 평가와 대조 전)"`이고 status는 pass/warn뿐 —
  **fail(차단)이 없다.** 숫자가 좋아졌는데 덱이 나빠지면 게이트가 틀린 것(불변 원칙).
- 이미지 슬롯 충족률의 출처는 `fill_images()` 리포트(자기보고)가 **아니라** html 마크업이다.
"""
from __future__ import annotations

import re

SCHEMA_VERSION = 1

# 임계값 = **실 코퍼스 분포의 바깥 경계**(이 저장소의 렌더된 deck.html 13개 / 166 슬라이드 / 424 텍스트
# 노드 실측: chars p99=553·max=554, node p99=73·max=98, bullets max=7, chars min=93).
# 그래서 **지금까지 만든 어떤 덱도 이 게이트에 걸리지 않는다 — 설계상 그렇다.**
#   ⇒ `status="pass"`의 뜻은 "잘 디자인됐다"가 아니라 **"기존 덱들의 범위 안"**이다.
#      이 게이트는 품질 판정기가 아니라 **이상치(out-of-distribution) 탐지기**다.
# 임계값을 관측 분포 안쪽으로 당기면 정상 덱이 걸리고, 밖으로 밀면 아무것도 못 잡는다.
# 재교정의 근거는 사람 평가여야 한다(N3-5 완료 정의) — 숫자가 좋아지면 의심하라.
MAX_TEXT_CHARS = 600     # 본문 가시 텍스트 상한(관측 max 554)
MIN_TEXT_CHARS = 90      # 하한(관측 min 93) — 미만 = 마크업이 사실상 빈 슬라이드
MAX_BULLETS = 8          # 렌더된 <li> 상한(관측 max 7). deck.json 불릿이 아니라 **마크업** 기준 —
                         # 템플릿이 불릿을 카드/도형으로 렌더하면 여기 안 세진다(review_badges와 다른 축).
MAX_LINE_CHARS = 110     # 단일 텍스트 노드 길이 상한(관측 max 98) — 초과 = 줄바꿈 폭주 → 오버플로 위험

# W31 γ패킷(리허설 마찰25): 크롬 헤더(제목) 전용 결정론 경고 — app/render/htmlgen.py의
# TITLE_LEN_SM(40자, auto-fit 2단계 축소 발동점)과 **같은 값**을 독립적으로 든다(정적 파싱
# 모듈은 렌더 모듈을 import하지 않는 이 저장소 관례 — 값만 복제, gates.py가
# dashboard.server.SKIPPABLE_ACK_GATES를 복제하는 것과 동일한 관례). 기존 overflow_risk
# (줄길이 110자, 본문 전반)보다 훨씬 낮은 문턱 — "htmlgen의 auto-fit이 이미 축소했어야 할 만큼
# 길다"는 신호이지 "실제로 넘쳤다"의 확정은 아니다(정적 파싱의 한계 — 위 정직성 계약과 동일).
TITLE_OVERFLOW_CHARS = 40

# 구 렌더본은 `<section class="slide …">`(id 없음)라 id 매칭만 하면 **조용히 0 슬라이드**가 된다.
# 그건 pass 가 아니라 미측정이다(아래 status="unmeasured").
_SECTION_RE = re.compile(
    r'<section\b(?P<attrs>[^>]*class="[^"]*\bslide\b[^"]*"[^>]*)>(?P<rest>.*?)</section>', re.S)
_SECTION_ID_RE = re.compile(r'id="slide-([^"]+)"')
_SLOT_RE = re.compile(r'class="dov-slot[ "]')
_SLOT_PH_RE = re.compile(r'class="dov-slot dov-slot--ph')
_TEXT_NODE_RE = re.compile(r'<(li|p|h1|h2|h3)\b[^>]*>(.*?)</\1>', re.S | re.I)
_TITLE_TEXT_RE = re.compile(r'<h[12] class="slide__title[^"]*">(.*?)</h[12]>', re.S)
_LI_RE = re.compile(r"<li\b", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_DROP_RE = re.compile(r"<(script|style|svg)\b.*?</\1>", re.S | re.I)
# 슬롯은 append-only 장식이다 — 텍스트 밀도 측정에서 제외(태그·캡션이 본문으로 세지 않도록).
# 슬롯 마크업에 중첩 <div>가 없다는 것이 non-greedy 매칭의 근거(image_slots.render_slot_html).
_SLOT_BLOCK_RE = re.compile(r'<div class="dov-slot[ "].*?</div>', re.S)


def _plain(html: str) -> str:
    """마크업 → 가시 텍스트. svg/style/script 는 통째로 제거(도형·CSS는 텍스트가 아니다)."""
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", _DROP_RE.sub(" ", html))).strip()


def _long_lines(section_html: str) -> int:
    """단일 텍스트 노드가 MAX_LINE_CHARS 를 넘는 개수(오버플로 위험 신호)."""
    n = 0
    for _, inner in _TEXT_NODE_RE.findall(_DROP_RE.sub(" ", section_html)):
        if len(_plain(inner)) > MAX_LINE_CHARS:
            n += 1
    return n


def measure_slide(section_html: str) -> dict:
    """슬라이드 1장의 결정론 측정치(순수 함수). 판정은 flags 로만, 차단하지 않는다."""
    content = _SLOT_BLOCK_RE.sub(" ", section_html)  # 본문 = 슬롯(장식) 제외
    chars = len(_plain(content))
    bullets = len(_LI_RE.findall(content))
    long_lines = _long_lines(content)
    slots = len(_SLOT_RE.findall(section_html))
    placeholder = len(_SLOT_PH_RE.findall(section_html))
    # W31 γ패킷(마찰25): 크롬 헤더(제목) 전용 글자수 — htmlgen auto-fit 발동점(TITLE_OVERFLOW_CHARS)
    # 을 넘었는지 별도로 본다(본문 전체 chars/long_lines와는 다른 축 — 제목 하나만).
    title_m = _TITLE_TEXT_RE.search(section_html)
    title_chars = len(_plain(title_m.group(1))) if title_m else 0

    flags: list[str] = []
    if chars > MAX_TEXT_CHARS:
        flags.append("density_over")
    elif chars < MIN_TEXT_CHARS:
        flags.append("density_under")
    if bullets > MAX_BULLETS:
        flags.append("bullets_over")
    if long_lines:
        flags.append("overflow_risk")
    if title_chars > TITLE_OVERFLOW_CHARS:
        flags.append("title_overflow_risk")
    if placeholder:
        flags.append("slot_placeholder")

    return {
        "text_chars": chars,
        "title_chars": title_chars,
        "bullets": bullets,
        "long_lines": long_lines,
        "image_slots": slots,
        "image_slots_placeholder": placeholder,
        "flags": flags,
    }


def compute_design_checks(html: str) -> dict:
    """병합된 deck.html → design_checks 블록. 결정론·0토큰·순수(파일 IO 없음)."""
    slides: list[dict] = []
    for i, m in enumerate(_SECTION_RE.finditer(html or ""), 1):
        sid = _SECTION_ID_RE.search(m.group("attrs"))
        row = {"slide_id": sid.group(1) if sid else str(i)}  # id 없는 구 렌더본 → 1-기반 인덱스
        row.update(measure_slide(m.group("rest")))
        slides.append(row)

    total_slots = sum(s["image_slots"] for s in slides)
    placeholder = sum(s["image_slots_placeholder"] for s in slides)
    filled = total_slots - placeholder

    def _count(flag: str) -> int:
        return sum(1 for s in slides if flag in s["flags"])

    summary = {
        "slides": len(slides),
        "density_over": _count("density_over"),
        "density_under": _count("density_under"),
        "bullets_over": _count("bullets_over"),
        "overflow_risk": _count("overflow_risk"),
        "title_overflow_risk": _count("title_overflow_risk"),
        "image_slots": {
            "total": total_slots,
            "filled": filled,
            "placeholder": placeholder,
            # 충족률: 슬롯이 없으면 비율이 정의되지 않는다 → null(0.0 으로 지어내지 않는다).
            "fulfillment": round(filled / total_slots, 3) if total_slots else None,
        },
    }
    flagged = summary["density_over"] + summary["density_under"] + \
        summary["bullets_over"] + summary["overflow_risk"] + summary["title_overflow_risk"] + placeholder

    # 슬라이드를 하나도 못 읽었으면 그건 "통과"가 아니라 **미측정**이다(조용한 0 = 가짜 pass).
    if not slides:
        status = "unmeasured"
    elif flagged:
        status = "warn"
    else:
        status = "pass"

    return {
        "schema_version": SCHEMA_VERSION,
        "measured_from": "deck.html (마크업 실측 — 자기보고 아님)",
        "method": ("정적 파싱 휴리스틱. 브라우저 레이아웃(픽셀·폰트 메트릭) 미측정 → "
                   "overflow 는 확정이 아니라 위험 신호다. title_overflow_risk(W31 마찰25)는 "
                   "크롬 헤더(제목) 글자수만 별도로 보는 신호 — htmlgen auto-fit 발동점과 같은 값."),
        "thresholds": {
            "max_text_chars": MAX_TEXT_CHARS,
            "min_text_chars": MIN_TEXT_CHARS,
            "max_bullets": MAX_BULLETS,
            "max_line_chars": MAX_LINE_CHARS,
            "title_overflow_chars": TITLE_OVERFLOW_CHARS,
            "calibration": ("기존 덱 코퍼스(166 슬라이드) 분포의 바깥 경계 — 정상 덱은 걸리지 않는다. "
                            "이상치 탐지기이지 품질 판정기가 아니며, 사람 평가와 대조 전이다(N3-5). "
                            "title_overflow_chars는 코퍼스 교정치가 아니라 htmlgen auto-fit 임계 복제다."),
        },
        "summary": summary,
        "slides": slides,
        # fail 없음 — 게이트는 차단하지 않는다. pass = "기존 덱들의 범위 안"(잘 디자인됨 아님).
        "status": status,
    }


def attach_browser_layer(checks: dict, probe: dict) -> dict:
    """W6-A1: 정적 계층(`checks`) 위에 브라우저 실측 계층(`layout_probe.probe_html`)을 얹는다.

    - 기존 키(summary/slides/status/method/thresholds)는 **보존**한다. 소비자(deck_review·
      대시보드)가 읽는 표면을 깨지 않기 위해서다 — 브라우저 결과는 `browser` 하위에 산다.
    - `summary.browser`는 probe 요약 카운터(void 포함)를 통째로 복사한다(중첩 요약 — 기존
      카운터와 이름이 겹치지 않는다).
    - **status 승격만 한다**: 정적이 pass인데 브라우저가 결함을 봤으면 warn. 반대로 브라우저가
      pass여도 정적 warn을 낮추지 않는다. 미측정(unmeasured)은 status를 건드리지 않는다 —
      "안 봤음"이 "괜찮음"이 되면 안 된다.
    """
    checks = dict(checks)
    checks["browser"] = probe
    b_status = probe.get("status")
    b_summary = dict(probe.get("summary") or {})
    b_summary["status"] = b_status
    summary = dict(checks.get("summary") or {})
    summary["browser"] = b_summary
    checks["summary"] = summary
    checks["method"] = (
        checks.get("method", "")
        + " | 브라우저 계층(browser): " + str(probe.get("method", "(없음)"))
    )
    if b_status == "warn" and checks.get("status") == "pass":
        checks["status"] = "warn"
    return checks
