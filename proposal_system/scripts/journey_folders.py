"""W31 R-A(R7) — 단계 폴더 여정(`run/journey/<NN_한글이름>/`).

CONTEXT/JOURNEY.md R7 정본. 핵심 원칙:

  - **기계 정본은 flat 유지.** 이 모듈은 `run/*.json` 정본을 절대 옮기거나 복제하지 않는다.
    journey 폴더에는 세 종류 파일만 둔다(이중화 금지 규칙, R7 하위 불릿①):
      ①**파생 뷰** — 정본 JSON의 읽기 전용 md 렌더. 머리에 자동생성 고지(`AUTO_GEN_HEADER`).
        정본이 뷰보다 새로우면(mtime) `sync()`가 재생성한다(별도 상태 파일 없이 파일끼리 대조 —
        `pipeline_state.is_stale`과 같은 "감시 산출물이 더 새로우면 재무장" 문법의 단순판).
      ②**사람 편집물** — 이번 패킷은 자리만(R6 오버레이 등은 후속). 정본은 폴더 쪽이 될 예정.
      ③**포인터** — `_여기서-할-일.md`. 매 `go`(=매 `sync()` 호출)마다 통째로 재작성한다
        (사람이 이 파일을 고쳐도 다음 go에서 덮인다 — 그래서 편집하지 말라고 명시한다).
  - **결정론·0토큰.** LLM을 호출하지 않는다. 파일 존재·내용만 읽는다.
  - **수납처 선개방.** 폴더는 "그 단계에 도달했을 때"가 아니라 "그 폴더에 넣을 산출물이 실제로
    생겼을 때" 연다(R7 하위 불릿③) — 예: institution_research.json이 생기면 07_테마확정/도
    즉시 열린다(아직 B1 게이트 전이어도).

`sync(run)`은 `proposal_pipeline.go_cmd`가 매번 호출한다(단일 호출점 — 트리거 배선은 go 쪽 몫,
이 모듈은 "무엇을 어떻게 채울지"만 안다).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

SCHEMA_VERSION = 1
JOURNEY_DIRNAME = "journey"
MANUAL_NAME = "_여기서-할-일.md"

AUTO_GEN_HEADER = (
    "<!-- 자동 생성 — 편집 금지. 수정은 오버레이/정본 공정으로. -->\n"
    "> ⚠️ 자동 생성 — 편집 금지. 수정은 오버레이/정본 공정으로(이 파일은 다음 `go`에서 통째로 다시 만들어진다).\n\n"
)

DASHBOARD_URL = "http://127.0.0.1:8754"

# R7 하위 불릿④: 폴더명 = 숫자 접두 + 한글(탐색기 정렬 = 여정 순서). A2(시동)는 run 생성 그
# 자체라 폴더가 없다 — 그래서 14개다(A0~B8에서 A2 하나 뺀 수).
FOLDERS: dict[str, str] = {
    "01": "01_공고찾기",
    "02": "02_착수판단",
    "03": "03_발주처조사",
    "04": "04_내용만들기",
    "05": "05_내용동결",
    "06": "06_뼈대확정",
    "07": "07_테마확정",
    "08": "08_프롬프트확인",
    "09": "09_이미지생산",
    "10": "10_수거검증",
    "11": "11_장표정독",
    "12": "12_합성검토",
    "13": "13_승인출하",
    "14": "14_마무리",
}


def journey_root(run: Path) -> Path:
    return Path(run) / JOURNEY_DIRNAME


def folder_path(run: Path, key: str) -> Path:
    return journey_root(run) / FOLDERS[key]


# ---------------------------------------------------------------------------
# 공용 유틸 — 읽기·쓰기
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> Any | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write(path: Path, text: str) -> bool:
    """내용이 실제로 달라질 때만 쓴다(불필요한 mtime 갱신 방지 — 파생 뷰 재무장 오탐 예방)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        try:
            if path.read_text(encoding="utf-8") == text:
                return False
        except OSError:
            pass
    path.write_text(text, encoding="utf-8")
    return True


def _refresh_view(source: Path, view: Path, render: Callable[[Any], str]) -> bool:
    """파생 뷰 재생성. 정본이 없으면 아무것도 안 한다(모르는 걸 아는 척 안 함).

    stale 판정 = 정본 mtime > 뷰 mtime(뷰 없으면 무조건 생성). `pipeline_state.is_stale`이
    쓰는 "감시 파일이 clearance보다 새로우면 재무장"과 동형 — 여기선 clearance 대신 뷰
    파일 자체의 mtime을 기준선으로 쓴다(이 뷰는 사람이 승인하는 게이트가 아니라 항상-최신
    렌더이므로 더 단순한 형태로 충분하다).
    """
    if not source.is_file():
        return False
    if view.is_file() and view.stat().st_mtime >= source.stat().st_mtime:
        return False
    doc = _load_json(source)
    if doc is None:
        return False
    if view.suffix == ".html":
        header = (
            "<!-- 자동 생성 — 편집 금지. 수정은 정본 공정으로. -->\n"
            "<div style='background:#fef3cd;border:1px solid #d4a72c;padding:6px 10px;"
            "font:13px sans-serif'>⚠️ 자동 생성 — 편집 금지(다음 go에서 다시 만들어진다)</div>\n"
        )
    else:
        header = AUTO_GEN_HEADER
    text = header + render(doc)
    return _write(view, text)


def _fmt_flag(flag: Any) -> str:
    if not flag:
        return ""
    if isinstance(flag, str):
        flags = [flag]
    else:
        flags = list(flag)
    tags = []
    for f in flags:
        s = str(f)
        tags.append(s if s.startswith("[") else f"[{s}]")
    return " ".join(tags)


# ---------------------------------------------------------------------------
# R1 — 파생 뷰 렌더러 (storyline / wireframe 가독 md)
# ---------------------------------------------------------------------------

STORYLINE_VIEW_NAME = "storyline_읽기.md"
WIREFRAME_VIEW_NAME = "wireframe_읽기.html"   # 마찰13: md→html 도식(구 md는 _populate_06이 정리)
INSTITUTION_VIEW_NAME = "기관조사_읽기.md"
BRAND_VIEW_NAME = "브랜드_요약_읽기.md"
DESIGN_CONTRACT_VIEW_NAME = "design_contract_읽기.md"
DESIGN_METRICS_VIEW_NAME = "디자인지표_읽기.md"

# imagedeck.PROMPTS_LOCAL_DIR과 같은 값의 리터럴 — journey_folders는 다른 imagedeck 상수도
# (MANIFEST_NAME 등) import 없이 문자열로 참조하는 기존 관례를 그대로 따른다.
PROMPTS_LOCAL_DIRNAME = "imagedeck_prompts_local"

# R9: review_badges 저점수 판정(둘 다 thin_score>=임계치) — app/review_badges.py의
# VERDICT_DIVERGE/VERDICT_BLAND 문자열과 동일(값만 참조, import는 하지 않는다 - 소비만).
_LOW_SCORE_VERDICTS = ("밋밋", "발산추천")


# W31 R9(리허설 마찰17, 2026-07-21 확정): hero(디자인 강조) 후보 결정론 유도.
# 강조는 구조 결정이라 A5(내용 동결)에서 확정한다 — 여기서는 "후보"만 계산해 표시한다(강제 아님,
# storyline은 건드리지 않는다). 후보 = ①문서 프레임(표지·간지·결론) 슬라이드 + ②핵심 전략 축
# (supports_axis)을 대표하는 축별 첫 등장 장. 축 자체도 상위 _HERO_AXIS_CAP개까지만 후보에 넣는다
# (전부 강조=아무것도 강조 안 됨 — 사용자 확정 근거). role/section 어느 쪽에 있든 인식한다
# (storyline 원본은 section만 갖고, adapt 이후 deck은 role도 갖는다 — 이 함수는 둘 다 받을 수 있다).
_HERO_FRAME_KEYWORDS = (
    "표지", "cover", "간지", "divider", "section_divider",
    "결론", "마무리", "closing", "끝인사", "감사", "thanks",
)
_HERO_AXIS_CAP = 3


def compute_hero_candidates(doc: dict[str, Any]) -> set:
    """W31 R9: storyline(또는 deck) 문서에서 hero(강조) 후보 슬라이드 식별자 집합을 계산한다.

    반환값은 표시(딱지)용 제안일 뿐이다 — 실제 확정은 사람이 slide.emphasis="hero"로 기록한다.
    """
    slides = doc.get("slides") or []
    candidates: set = set()
    axis_order: list[str] = []
    axis_first: dict[str, Any] = {}
    for s in slides:
        if not isinstance(s, dict):
            continue
        ident = s.get("n") if s.get("n") is not None else s.get("slide_id")
        if ident is None:
            continue
        text = " ".join(str(s.get(k) or "") for k in ("role", "section")).lower()
        if any(k.lower() in text for k in _HERO_FRAME_KEYWORDS):
            candidates.add(ident)
            continue
        axis = s.get("supports_axis")
        if isinstance(axis, str) and axis.strip():
            axis = axis.strip()
            if axis not in axis_first:
                axis_first[axis] = ident
                axis_order.append(axis)
    for axis in axis_order[:_HERO_AXIS_CAP]:
        candidates.add(axis_first[axis])
    return candidates


def render_storyline_view(doc: dict[str, Any]) -> str:
    """R1: 회의(A5)에서 훑기 좋은 장표별 요약 — 섹션(장)·제목·핵심 메시지·불릿·flag.

    W31 R9(마찰17): 이 단계가 디자인 강조(hero) 장을 확정하는 자리임을 머리에 고지하고,
    hero 후보(⭐, 시스템 유도) / 확정(⭐ 강조 확정, emphasis="hero")을 장 제목에 표시한다."""
    meta = doc.get("meta") or {}
    slides = doc.get("slides") or []
    candidates = compute_hero_candidates(doc)
    lines = ["# 스토리라인 가독 뷰", ""]
    lines.append(
        "> 이 단계에서 디자인 강조(hero) 장을 확정한다 — ⭐ 강조 후보(시스템이 표지·간지·결론·"
        "핵심 전략 축 지지 장에서 유도) 중 실제로 강조할 장을 골라 `emphasis: \"hero\"`로 "
        "storyline에 기록하고 함께 동결한다(강조 장은 메시지를 한 줄로 줄이거나 장을 분리·간지 "
        "신설 후 확정 — 05 매뉴얼 참고)."
    )
    lines.append(f"- 프로젝트: {meta.get('project') or '(없음)'}")
    if meta.get("governing_message"):
        lines.append(f"- 핵심 메시지(governing): {meta['governing_message']}")
    lines.append(f"- 장표 수: {len(slides)}")
    lines.append("")
    current_section: str | None = None
    for s in slides:
        section = s.get("section")
        if section != current_section:
            lines.append(f"## {section or '(섹션 없음)'}")
            current_section = section
        n = s.get("n")
        title = s.get("title") or "(제목 없음)"
        example_tag = "  [예시]" if s.get("example") else ""
        flag_tag = _fmt_flag(s.get("flag"))
        if s.get("emphasis") == "hero":
            hero_tag = "  ⭐ 강조 확정"
        elif n in candidates:
            hero_tag = "  ⭐ 강조 후보"
        else:
            hero_tag = ""
        head = f"### {n}. {title}{example_tag}{hero_tag}"
        if flag_tag:
            head += f"  {flag_tag}"
        lines.append(head)
        if s.get("message"):
            lines.append(f"- 메시지: {s['message']}")
        # W32 마찰36(시험 적용): 형태·분위기 의도는 이 회의(A5)에서 함께 동결된다 — 사람이 여기서
        # 봐야 뼈대 단계 전에 거부·수정할 수 있다(뷰에 없으면 wireframe에서야 발견 = 뒤늦음).
        if s.get("form_intent"):
            lines.append(f"- 형태 의도: {s['form_intent']}")
        if s.get("art_note"):
            lines.append(f"- 분위기 메모: {s['art_note']}")
        bullets = s.get("bullets") or []
        for b in bullets:
            lines.append(f"  - {b}")
        lines.append("")
    return "\n".join(lines)


# 마찰 13(2026-07-21 사용자: html 도식): 골격별 슬롯 배치를 16:9 미니 캔버스에 상자로 그린다.
# 기하는 packs/core/frames.json의 의미(size·slot 수)를 상수 지도로 옮긴 것 — 미지 골격은 적층 폴백.
_FRAME_LAYOUT_CSS: dict[str, str] = {
    "full": "grid-template:1fr / 1fr",
    "split_v": "grid-template:1fr / 1fr 1fr",
    "split_h": "grid-template:1fr 1fr / 1fr",
    "grid_2x2": "grid-template:1fr 1fr / 1fr 1fr",
    "hero_body": "grid-template:11fr 9fr / 1fr",
}


def _slot_box(slot: dict[str, Any]) -> str:
    piece = str(slot.get("piece") or "?")
    size = str(slot.get("size") or "")
    binds = str(slot.get("binds") or "")
    return (
        "<div class='slot'><b>" + piece + "</b>"
        + ("<span class='sz'>" + size + "</span>" if size else "")
        + ("<span class='bd'>← " + binds + "</span>" if binds else "")
        + "</div>"
    )


def render_wireframe_view(doc: dict[str, Any]) -> str:
    """R1+마찰13: wireframe.json의 장별 배치를 도식 상자(16:9 미니 캔버스)로 렌더한 HTML."""
    slides = doc.get("slides") or []
    parts = [
        "<meta charset='utf-8'><title>뼈대(wireframe) 가독 뷰</title>",
        "<style>",
        "body{font:14px/1.5 'Malgun Gothic',sans-serif;max-width:960px;margin:16px auto;padding:0 12px}",
        ".canvas{aspect-ratio:16/9;border:2px solid #333;display:grid;gap:6px;padding:6px;",
        " background:#fafafa;margin:6px 0 4px}",
        ".slot{border:1.5px dashed #666;background:#fff;display:flex;flex-direction:column;",
        " align-items:center;justify-content:center;text-align:center;padding:4px;font-size:12px}",
        ".slot .sz{color:#888;font-size:11px}.slot .bd{color:#2563a8;font-size:11px}",
        ".gap{color:#b00;font-weight:bold}.meta{color:#555;font-size:12px}",
        "h2{margin:20px 0 2px;border-bottom:1px solid #ddd}",
        "</style>",
        "<h1>뼈대(wireframe) 가독 뷰</h1>",
        f"<p class='meta'>schema_version={doc.get('schema_version')} · "
        f"결정 주체={doc.get('selected_by') or '(미기록)'} · 장표 수={len(slides)}</p>",
    ]
    for s in slides:
        sid = s.get("slide_id")
        frame = str(s.get("frame") or "?")
        slots = s.get("slots") or []
        parts.append(f"<h2>장 {sid} — {s.get('message_type') or '?'}</h2>")
        parts.append(
            f"<p class='meta'>frame={frame} · rendition={s.get('rendition')} "
            f"· layout_group={s.get('layout_group') or '(없음)'}</p>"
        )
        # 골격 기하: 알려진 frame은 지도대로, 미지/가변(row_n·flow_seq 등)은 슬롯 수만큼 가로 등분.
        css = _FRAME_LAYOUT_CSS.get(frame)
        if css is None:
            n = max(1, len(slots))
            css = f"grid-template:1fr / repeat({n}, 1fr)"
        boxes = "".join(_slot_box(slot) for slot in slots) or "<div class='slot'>(슬롯 없음)</div>"
        parts.append(f"<div class='canvas' style='{css}'>{boxes}</div>")
        principles = s.get("principles") or []
        if principles:
            parts.append("<p class='meta'>원칙: " + ", ".join(str(p) for p in principles) + "</p>")
        gaps = s.get("catalog_gap") or []
        if gaps:
            parts.append("<p class='gap'>[!] 어휘 갭: " + ", ".join(str(g) for g in gaps) + "</p>")
    return "\n".join(parts) + "\n"


def render_institution_view(doc: dict[str, Any]) -> str:
    lines = ["# 발주처 조사 가독 뷰", ""]
    lines.append(f"- 기관: {doc.get('institution') or '(없음)'}")
    lines.append(f"- 조사자: {doc.get('researched_by') or '(미기록)'}")
    identity = doc.get("identity") or {}
    if identity:
        lines.append("")
        lines.append("## 정체성")
        if identity.get("mission"):
            lines.append(f"- 미션: {identity['mission']}")
        if identity.get("founding_philosophy"):
            lines.append(f"- 건학이념: {identity['founding_philosophy']}")
        for sp in identity.get("specialization") or []:
            lines.append(f"- 특성화: {sp}")
        for rc in identity.get("recent_context") or []:
            lines.append(f"- 최근 맥락: {rc}")
    hooks = doc.get("content_hooks") or []
    if hooks:
        lines.append("")
        lines.append("## 문서 밖 근거(도입 직인용 후보)")
        for h in hooks:
            lines.append(f"- \"{h.get('claim')}\" — {h.get('use_in')}")
    sources = doc.get("sources") or []
    if sources:
        lines.append("")
        lines.append("## 출처")
        for src in sources:
            lines.append(f"- {src}")
    return "\n".join(lines)


def render_brand_view(doc: dict[str, Any]) -> str:
    """07_테마확정 전용 — institution_research의 디자인 계열 부분만 발췌(R7 선개방)."""
    lines = ["# 브랜드 요약 (발주처 조사에서 선개방)", ""]
    lines.append(f"- 기관: {doc.get('institution') or '(없음)'}")
    tokens = (doc.get("brand_tokens") or {})
    colors = tokens.get("colors") or {}
    fonts = tokens.get("fonts") or {}
    logo = tokens.get("logo") or {}
    lines.append(f"- 대표색(primary): {colors.get('primary') or '(없음)'}")
    lines.append(f"- 보조색(accent): {colors.get('accent') or '(없음)'}")
    lines.append(f"- 폰트: {fonts.get('family') or '(없음)'}")
    lines.append(f"- 로고: {logo.get('path') or '(없음 — 실자산 필수, 자동 생성 금지)'}")
    if logo.get("note"):
        lines.append(f"  - 비고: {logo['note']}")
    lines.append("")
    lines.append("> 전체 조사 내용은 03_발주처조사/기관조사_읽기.md 참조.")
    lines.append("> B1 테마 확정에서 이 색·자산을 반영할지 결정한다(기본값=inkline 유지도 가능).")
    return "\n".join(lines)


def render_design_contract_view(doc: dict[str, Any]) -> str:
    """W31 R2·R3·R5: run/design_contract.json(정본) 파생 뷰 — 회의 없이도 계약 내용을 훑는 자리.

    용어 정의(JOURNEY.md): design_contract=run별 1회성 정본, 스킨=졸업본(창고, 미자동적용),
    차용=design_brief.skin.value가 초안 소스. 여기서는 그 결과(출처·색·폰트)와, R5가 분리한
    chrome_contract(조립 전용)/image_contract(이미지 프롬프트 전용) 키 목록을 요약한다."""
    meta = doc.get("meta") or {}
    chrome = doc.get("chrome_contract") or {}
    image = doc.get("image_contract") or {}
    colors = chrome.get("colors") or {}
    ch = chrome.get("chrome") or {}
    typo = chrome.get("typography") or {}
    lines = ["# 디자인 계약 가독 뷰 (design_contract.json)", ""]
    source = meta.get("source") or "(미기록)"
    origin = "차용" if source not in (None, "neutral") else "중립 템플릿"
    lines.append(f"- 출처: **{source}** ({origin})")
    spec_mode = "완전 스킨 — 세부 스펙 그대로 이미지 프롬프트에 주입" if meta.get("full_skin") \
        else "중립/부분 — 이미지 프롬프트는 축소판(크롬 이웃 브리핑 + 자유, R9 마찰19)"
    lines.append(f"- 이미지 프롬프트 스펙 수준: {spec_mode}")
    lines.append(f"- 동결 시각: {meta.get('frozen_at') or '(없음)'}")
    lines.append(f"- run 조정 반영: {'예' if meta.get('run_overrides_applied') else '아니오'}")
    # W31 R10(β2): 마스터 시안(imagedeck --master-apply)이 기록한 확정 룩·밀도 — 있을 때만 표시.
    art = doc.get("art_direction") or {}
    if art.get("look"):
        lines.append(f"- 확정 룩(마스터 시안, R10): {art['look']}")
        if art.get("chosen_axis"):
            lines.append(f"  - 확정 축: {art['chosen_axis']}")
    density = doc.get("density")
    if density:
        note = "" if density == "standard" else "  ⚠️ 비표준 — 분량 밴드 재조정 → A5 부분 재생성 권장"
        lines.append(f"- 밀도 등급: {density}{note}")
    lines.append("")
    lines.append("## 색·폰트 (chrome_contract에서 발췌)")
    lines.append(f"- 대표색(ink): {colors.get('ink') or '(없음)'}")
    lines.append(f"- 강조색(accent): {colors.get('accent') or '(없음)'}")
    lines.append(f"- 배경(bg): {colors.get('bg') or '(없음)'}")
    lines.append(f"- 폰트: {typo.get('family') or '(없음)'}")
    lines.append(f"- 헤더/푸터 높이: {ch.get('header_h')}px / {ch.get('footer_h')}px")
    lines.append("")
    lines.append("## R5 분리 — chrome_contract vs image_contract")
    lines.append(
        f"- chrome_contract(HTML/pptx 조립 전용, compose가 소비): {', '.join(chrome.keys()) or '(없음)'}"
    )
    lines.append(
        f"- image_contract(이미지 생성 프롬프트 주입 전용, imagedeck bundle이 소비): "
        f"{', '.join(image.keys()) or '(없음)'}"
    )
    lines.append("> canvas/chrome은 image_contract에 없다 — 이미지 프롬프트에 크롬(헤더/푸터) 구조가 더 이상 섞이지 않는다.")
    return "\n".join(lines)


def render_design_metrics_view(doc: dict[str, Any], band_violations: "list[dict] | None" = None) -> str:
    """W31 R9: review_badges 장별 채점 → 이미지 단계 디자인 지표 파생 뷰(imagedeck_manifest.json에서).

    정본은 imagedeck_manifest.json(bundle이 매번 다시 쓴다) — 여기 담긴 slide별
    design_verdict/design_signal_injected/overlay_merged를 표로 훑는다. 채점 자체가 없던
    run(design_brief.json 없음)은 모든 행이 '채점 미실시'로 나오고 조용히 그렇다고 표기한다
    (강제 아님 — B2는 그대로 진행 가능).

    W31 마찰17(R9 2축화): 밋밋 보완(축A)과 디자인 강조(축B, emphasis="hero")는 서로 다른
    신호다 — 장별로 [보완 축A/강조 축B/그대로]를 표기한다(imagedeck_manifest.json의
    design_signal_injected=축A, emphasis_signal_injected=축B).

    W31 γ패킷(마찰22·23): `band_violations`(gating_report.json.length_rhythm — 별도 소스 파일,
    render_design_metrics_view 호출부가 함께 읽어 넘긴다)가 있으면 위반 장을 전면(표 위)에
    표시하고, manifest slide의 content_split/overflow_split_skipped(마찰23 사전 분할 결과)를
    표의 '분할' 열로 보여준다."""
    slides = doc.get("slides") or []
    lines = ["# 디자인 지표 읽기 (review_badges 채점 → 이미지 단계, R9)", ""]
    lines.append(
        "> 저점수(밋밋·발산추천) 장은 bundle 때 '배경이미지 생성 권장·디자인지식 적극 적용' "
        "신호(축A — 보완)가 프롬프트 말미에 자동 주입된다. 충실 장은 과잉 장식 방지를 위해 "
        "주입하지 않는다. 반대로 디자인 강조(축B, `emphasis: \"hero\"` 확정 장)는 채점과 무관하게 "
        "의도적 저밀도·무드 배경 신호가 주입된다 — 축A(밋밋 보완)와 축B(강조)는 문구·목적이 다르다."
    )
    lines.append("")
    band_violations = band_violations or []
    if band_violations:
        ids = ", ".join(str(v.get("slide_id")) for v in band_violations)
        lines.append(f"## ⚠️ 분량 밴드 위반 {len(band_violations)}장 (마찰22 — 이미지 단계 오버플로 전조)")
        lines.append(f"- 위반 장: {ids}.")
        lines.append(
            "- 3장 이상이면 `imagedeck_prompt_ack` 관문이 자동 재정지된다(gates.py — 신호 나쁘면 "
            "재정지, W31 마찰2 다이얼과 별개로 항상 적용)."
        )
        lines.append(
            "- 1차 탈출구: 하한(`minimum_body_size`) 내 폰트 축소로 흡수 시도(가이드, 강제 아님). "
            "2차: 하한으로도 수용 불가가 확정된 장은 `imagedeck --bundle`이 결정론 사전 분할(A/B) "
            "한다(마찰23) — 아래 표의 '분할' 열 참고."
        )
        lines.append("")
    lines.append("| 장 | 프롬프트/파일 | 채점 | 축 | 권장 조치 | 오버레이 | 분할 | 지식운반 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    any_scored = False
    for s in slides:
        n = s.get("n")
        target = s.get("out_name") or s.get("prompt_file") or "(html 전용 — 프롬프트 없음)"
        verdict = s.get("design_verdict")
        if verdict:
            any_scored = True
        if s.get("emphasis_signal_injected"):
            axis = "강조 축B"
            action = "의도적 저밀도 유지 · 무드/풀블리드 배경 권장(A5 확정 — hero)"
        elif verdict in _LOW_SCORE_VERDICTS:
            axis = "보완 축A"
            action = "배경이미지 생성 권장 · 디자인지식(무드/배경) 적극 적용"
        elif verdict:
            axis = "그대로"
            action = "주입 없음(충실 — 과잉 장식 방지)"
        else:
            axis = "그대로"
            action = "채점 미실시"
        overlay = "병합됨" if s.get("overlay_merged") else "-"
        if s.get("content_split"):
            split_col = f"A/B 분할({s.get('split_reason') or ''})"
        elif s.get("overflow_split_skipped"):
            split_col = f"⚠️ 분할 포기({s.get('overflow_split_skip_reason') or ''})"
        else:
            split_col = "-"
        # δ패킷: A6가 이 장에 고른 디자인지식 카드 운반 요약(§5) — imagedeck_manifest.json
        # slides[].knowledge_carried(cards/images/missing). html 전용 장은 None(프롬프트 자체가
        # 없어 운반 대상 없음), 카드 미인용 장은 {"cards":0,...}(0건과 미측정을 구분).
        kc = s.get("knowledge_carried")
        if kc is None:
            knowledge_col = "-"
        elif not kc.get("cards") and not kc.get("missing"):
            knowledge_col = "미인용"
        else:
            knowledge_col = f"카드{kc.get('cards', 0)}·이미지{kc.get('images', 0)}"
            if kc.get("missing"):
                knowledge_col += f" · 미발견 {', '.join(kc['missing'])}"
        lines.append(
            f"| {n} | {target} | {verdict or '(없음)'} | {axis} | {action} | {overlay} | "
            f"{split_col} | {knowledge_col} |"
        )
    lines.append("")
    if not any_scored:
        lines.append(
            "> 채점 데이터 없음 — design_brief.json이 아직 없거나(파일럿·직접 imagedeck 호출) 이 "
            "run에서 review_badges 채점이 실행되지 않았다. 강제 아님 — B2는 그대로 진행할 수 있다."
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# W31 리허설 마찰5(REHEARSAL_FRICTIONS_W31.md #5) — 산출물.html(클릭 링크 + 계보) + _전체여정.html
#
# 산출물이 flat run 루트에만 있어 journey 폴더에서 바로 못 열고, 어떤 단계를 거쳐 나왔는지도
# 안 보인다는 마찰(사용자 확정 2026-07-21)의 해소. 이중화 금지 규칙은 그대로다 — 여기서 만드는
# 건 "정본으로 가는 클릭 링크"(상대 file 링크)와 "계보 텍스트"뿐, 정본 JSON의 사본이 아니다.
#
# 계보 사슬(ARTIFACT_STAGE/STAGE_PARENT)은 **추측 생성이 아니라 실제 공정 순서**를 코드로 명시한
# 상수다(pipeline_state.STAGE_ORDER·message_map 우선 설계 W16 결정 9①에 근거) — message_map이
# skeleton보다 앞선다(핵심 주장을 먼저 확정하고 그것에 종속해 장표 구조를 잡는다).
# ---------------------------------------------------------------------------

OUTPUT_VIEW_NAME = "산출물.html"
OVERVIEW_NAME = "_전체여정.html"

# 산출물 파일(run 루트 기준 상대경로) -> 이 파일을 만든 pipeline_state 단계 키. 단계 키가 있어야
# 완료 시각(view["stages"][key]["at"])과 계보 사슬(STAGE_PARENT)을 붙일 수 있다 — 단계 키가 없는
# 산출물(예: 사람 편집물)은 완료 시각/계보 없이 링크만 나열한다.
ARTIFACT_STAGE: dict[str, str] = {
    "institution_research.json": "research_apply",
    "message_map.json": "message_map",
    "skeleton.json": "skeleton",
    "storyline.json": "storyline_bundle",
    "deck.html": "render",
    "deck.doc.html": "render",
    "review_resolutions.json": "review_resolve",
    "wireframe.json": "wireframe_apply",
    "design_brief.json": "design_brief",
    "design_contract.json": "design_contract",
    "master_design_prompt.md": "imagedeck_master_bundle",
    "master_design.json": "imagedeck_master_apply",
    "design_overrides.json": "stage9_apply",
    "design_spec.json": "refine_collect",
    "imagedeck_manifest.json": "imagedeck_bundle",
    "imagedeck_collect.json": "imagedeck_collect",
    os.path.join("imagedeck", "collect_report.md"): "imagedeck_collect",
    "deck.images.html": "imagedeck_compose",
    "deck_review.md": "deck_review",
    "approval.json": "approve",
    "deck.pptx": "approve",
}

# 단계 -> 직전 단계(내용을 물려받은 곳). 단일 부모 체인 — 표시용 계보이지 의존성 그래프 전체가
# 아니다. 실제 순서 근거: message_map(핵심 주장)이 skeleton(장표 구조)보다 앞선다(W16 결정 9① —
# "스켈레톤 역제안은 message_map 종속"), skeleton이 storyline(채움)보다 앞선다(W10→W16).
STAGE_PARENT: dict[str, str] = {
    "message_map": "message_map_bundle",
    "skeleton": "message_map",
    "storyline_bundle": "skeleton",
    "render": "storyline_bundle",
    "review_resolve": "render",
    "wireframe_bundle": "review_resolve",
    "wireframe_apply": "wireframe_bundle",
    "design_brief": "wireframe_apply",
    "design_contract": "design_brief",
    "stage9_bundle": "design_contract",
    "stage9_apply": "stage9_bundle",
    "refine_bundle": "stage9_apply",
    "refine_collect": "refine_bundle",
    "refine_handoff": "refine_collect",
    "imagedeck_bundle": "design_contract",
    "imagedeck_collect": "imagedeck_bundle",
    "imagedeck_compose": "imagedeck_collect",
    "deck_review_bundle": "stage9_apply",
    "deck_review": "deck_review_bundle",
    "approve": "deck_review",
}
_ROOT_LABEL = "분석카드(02_착수판단 초안)"

# 단계 -> journey 폴더 키(계보 사슬 표시에 붙이는 (NN) 태그). CHECKPOINT_FOLDER(관문용)와 짝을 이룬다.
STAGE_FOLDER: dict[str, str] = {
    "message_map_bundle": "04", "message_map": "04", "skeleton": "04",
    "storyline_bundle": "04", "render": "04",
    "research_bundle": "03", "research_apply": "03",
    "review_resolve": "05",
    "wireframe_bundle": "06", "wireframe_apply": "06",
    "design_brief": "07", "design_contract": "07",
    "imagedeck_master_bundle": "07", "imagedeck_master_apply": "07",
    "stage9_bundle": "07", "stage9_fill_images": "07", "stage9_apply": "07",
    "refine_bundle": "07", "refine_collect": "07", "refine_handoff": "07",
    "imagedeck_bundle": "08", "imagedeck_collect": "10", "imagedeck_compose": "12",
    "deck_review_bundle": "12", "deck_review": "12", "approve": "13",
}

# 관문 -> journey 폴더 키(_전체여정.html의 "현재 위치" 표시용). journey_check.GATE_FOLDER_KEY와
# 동형이나 여기는 선택 관문(start·research)까지 포함한 전체 지도용이라 별도로 둔다.
CHECKPOINT_FOLDER: dict[str, str] = {
    "start": "02", "research": "03", "decision": "05", "design": "12",
    "skeleton_review": "04", "wireframe_review": "06", "theme_confirm": "07",
    "imagedeck_prompt_ack": "08", "imagedeck_ack": "11",
    # design_refs: 전용 폴더 없음(기존 갭 — 대시보드 채널만).
}

# 폴더 키 -> [(run 루트 상대경로, 표시 라벨), ...]. 그 폴더의 "핵심 산출물"만 큐레이션한다
# (모든 산출물을 나열하지 않는다 — 대량 파일 디렉터리는 개수만 안내).
ARTIFACT_CATALOG: dict[str, list[tuple[str, str]]] = {
    "03": [("institution_research.json", "기관 조사 결과(정본 JSON)")],
    "04": [("message_map.json", "메시지맵(핵심 주장·전략 축)"),
           ("skeleton.json", "스켈레톤 역제안(표준 시나리오 더미)"),
           ("storyline.json", "스토리라인(장표 채움)")],
    "05": [("storyline.json", "스토리라인(회의 확정본)"),
           ("review_resolutions.json", "검토요망 해소지"),
           ("deck.doc.html", "본문 정독용 문서형 뷰"),
           ("deck.html", "덱 미리보기")],
    "06": [("wireframe.json", "뼈대(frame×piece 결정)")],
    "07": [("design_brief.json", "디자인 브리핑"),
           ("design_contract.json", "디자인 계약(run별 정본)"),
           ("master_design_prompt.md", "마스터 시안 제작 프롬프트(R10)"),
           ("master_design.json", "마스터 시안 확정본(R10, 사람 편집물)"),
           ("design_overrides.json", "정련 override(코드명 stage9)")],
    "08": [("imagedeck_manifest.json", "장별 프롬프트 매니페스트")],
    "10": [("imagedeck_collect.json", "수거 검증 결과(JSON)"),
           (os.path.join("imagedeck", "collect_report.md"), "수거 검증 리포트")],
    "11": [(os.path.join("imagedeck", "collect_report.md"), "수거 검증 리포트"),
           ("deck_review.md", "LLM 덱 평가")],
    "12": [("deck.images.html", "완성 이미지 덱"), ("deck.html", "완성 덱(html_editable)")],
    "13": [("approval.json", "승인 기록"), ("deck.pptx", "하이브리드 pptx")],
    "14": [("deck.pptx", "최종 제안서(pptx)")],
}


def _html_escape(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _lineage_text(stages: dict[str, dict[str, Any]], label: str, stage_key: str | None) -> str:
    """"산출물 ← 직전내용(폴더, 완료시각) ← ... ← 분석카드(02)" 사슬 텍스트. 완료 시각 기록이
    없으면 "미기록"(모르는 걸 아는 척하지 않는다 — pipeline_state의 기존 정직화 관례와 동형)."""
    if stage_key is None:
        return label
    import pipeline_state  # sibling, 지연 임포트(순환 방지 — 이 리포 전역 관례)

    parts = [label]
    cur = STAGE_PARENT.get(stage_key)
    seen = {stage_key}
    while cur:
        at = (stages.get(cur) or {}).get("at") or "미기록"
        folder = STAGE_FOLDER.get(cur, "?")
        stage_label = pipeline_state.STAGE_LABEL.get(cur, cur)
        parts.append(f"{stage_label}({folder}, {at})")
        if cur in seen:
            break
        seen.add(cur)
        cur = STAGE_PARENT.get(cur)
    parts.append(_ROOT_LABEL)
    return " ← ".join(parts)


def render_output_view(run: Path, key: str, stages: dict[str, dict[str, Any]]) -> str | None:
    """이 폴더 키의 핵심 산출물을 클릭 링크(상대경로) + 계보로 나열한 자기완결 HTML.

    산출물이 하나도 없으면 None(정본이 없으면 아무것도 안 만든다 — 이 모듈의 기존 관례).
    """
    run = Path(run)
    folder = folder_path(run, key)
    entries = ARTIFACT_CATALOG.get(key, [])
    rows: list[str] = []
    for rel, label in entries:
        p = run / rel
        if not p.is_file():
            continue
        stage_key = ARTIFACT_STAGE.get(rel)
        at = ((stages.get(stage_key) or {}).get("at") if stage_key else None) or "미기록"
        href = os.path.relpath(p, folder).replace(os.sep, "/")
        lineage = _lineage_text(stages, label, stage_key)
        rows.append(
            "<li><a href=\"" + _html_escape(href) + "\">" + _html_escape(label) + "</a>"
            " — 완료: " + _html_escape(at)
            + "<div class=\"lineage\">계보: " + _html_escape(lineage) + "</div></li>"
        )
    if not rows:
        return None
    title = f"{FOLDERS[key]} — 산출물"
    return (
        "<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
        f"<title>{_html_escape(title)}</title><style>"
        "body{font-family:-apple-system,'Malgun Gothic',sans-serif;max-width:760px;margin:2rem auto;"
        "padding:0 1rem;color:#222}h1{font-size:1.2rem}"
        "ul{list-style:none;padding:0}li{padding:.6rem 0;border-bottom:1px solid #ddd}"
        "a{font-weight:600;color:#0b5cad;text-decoration:none}a:hover{text-decoration:underline}"
        ".lineage{font-size:.85rem;color:#555;margin-top:.2rem}"
        ".note{font-size:.8rem;color:#a00;margin-bottom:1rem}"
        "</style></head><body>"
        f"<p class=\"note\">자동 생성 — 편집 금지. 매 go에서 다시 만들어진다. 링크는 이 폴더 밖 "
        "run 루트의 정본 파일을 가리킨다(사본 아님).</p>"
        f"<h1>{_html_escape(title)}</h1><ul>" + "".join(rows) + "</ul></body></html>\n"
    )


def render_overview(run: Path, stages: dict[str, dict[str, Any]], current_key: str | None) -> str:
    """journey 루트 지도 — 14단계 × 핵심 산출물 + 현재 위치(다음 관문이 속한 폴더)."""
    run = Path(run)
    root = journey_root(run)
    sections: list[str] = []
    for key, name in FOLDERS.items():
        is_current = key == current_key
        marker = " <span class=\"here\">◀ 현재 위치</span>" if is_current else ""
        links: list[str] = []
        for rel, label in ARTIFACT_CATALOG.get(key, []):
            p = run / rel
            if not p.is_file():
                continue
            href = os.path.relpath(p, root).replace(os.sep, "/")
            links.append(f"<li><a href=\"{_html_escape(href)}\">{_html_escape(label)}</a></li>")
        body = f"<ul>{''.join(links)}</ul>" if links else "<p class=\"empty\">(아직 산출물 없음)</p>"
        cls = "step current" if is_current else "step"
        sections.append(f"<section class=\"{cls}\"><h2>{_html_escape(name)}{marker}</h2>{body}</section>")
    return (
        "<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
        "<title>전체 여정 지도</title><style>"
        "body{font-family:-apple-system,'Malgun Gothic',sans-serif;max-width:900px;margin:2rem auto;"
        "padding:0 1rem;color:#222}h1{font-size:1.3rem}"
        ".step{border:1px solid #ddd;border-radius:8px;padding:.7rem 1rem;margin:.5rem 0}"
        ".step.current{border-color:#0b5cad;background:#eef5ff}"
        ".step h2{font-size:1rem;margin:.2rem 0}.here{color:#0b5cad;font-weight:700}"
        "ul{list-style:none;padding:0;margin:.3rem 0 0}li{padding:.15rem 0}"
        "a{color:#0b5cad;text-decoration:none}a:hover{text-decoration:underline}"
        ".empty{color:#888;font-size:.85rem;margin:.2rem 0 0}"
        ".note{font-size:.8rem;color:#a00}"
        "</style></head><body>"
        "<p class=\"note\">자동 생성 — 편집 금지. 매 go에서 다시 만들어진다.</p>"
        "<h1>전체 여정 지도 (14단계)</h1>" + "".join(sections) + "</body></html>\n"
    )


def _current_folder_key(view: dict[str, Any] | None) -> str | None:
    step = (view or {}).get("next") or {}
    cp = step.get("checkpoint")
    if cp and cp in CHECKPOINT_FOLDER:
        return CHECKPOINT_FOLDER[cp]
    stage = step.get("stage")
    if stage and stage in STAGE_FOLDER:
        return STAGE_FOLDER[stage]
    if step.get("kind") == "done":
        return "14"
    return None


# ---------------------------------------------------------------------------
# 매뉴얼(_여기서-할-일.md) — 처음 정주행자 기준, 동사형 단계명, R4 자리 포인터 포함
# ---------------------------------------------------------------------------

# R4(회의체 이름/참석/판단 기준)는 **사람 편집물**이다(이중화 금지 규칙 ②) — 정본은 폴더
# 쪽이라 시스템이 절대 덮어쓰지 않는다. `_여기서-할-일.md`는 매 sync에서 통째로 재작성되므로
# (③ 포인터) R4 값을 그 안에 두면 다음 go에서 사람이 적은 내용이 사라진다(2026-07-21 발견·수정).
# 그래서 R4는 별도 파일 `회의록_메모.md`로 분리하고, 매뉴얼에는 그곳을 가리키는 한 줄만 남긴다.
# (구명 `회의체_메모.md` — "회의체"가 모호하다는 사용자 판정으로 개명, 리허설 마찰 10 · 2026-07-21.
#  기존 발급분은 _ensure_meeting_note가 내용 보존한 채 새 이름으로 이관한다.)
MEETING_NOTE_NAME = "회의록_메모.md"
_MEETING_NOTE_LEGACY_NAME = "회의체_메모.md"

HUMAN_EDIT_HEADER = (
    "> ✍️ 사람 편집물 — 자유롭게 수정, 시스템이 덮어쓰지 않음(이 폴더에서는 이 파일이 정본이다).\n\n"
)

_MEETING_NOTE_TEMPLATE = (
    HUMAN_EDIT_HEADER
    + "# 회의록 메모 (R4)\n\n"
    "이 단계의 결정을 **누가·어떤 기준으로** 내리는지, 그리고 **회의에서 나온 내용**을\n"
    "**사람이** 적는 곳이다(시스템·Claude는 이 파일을 건드리지 않는다).\n\n"
    "- 회의 이름: [사용자 기입]\n"
    "- 참석자: [사용자 기입]\n"
    "- 판단 기준: [사용자 기입]\n"
    "- 회의 메모(피드백·결정 사항):\n"
)

_MEETING_POINTER = (
    f"\n## 회의록 (R4)\n"
    f"- 이 단계의 결정 주체·판단 기준·회의 내용은 `{MEETING_NOTE_NAME}`에 적는다"
    f"(이 파일과 달리 매 go에서 재작성되지 않는다 — 자유롭게 채워도 유실되지 않는다).\n"
)


def _ensure_meeting_note(folder: Path) -> bool:
    """R4 자리 — 사람 편집물. **없을 때만 최초 1회** 템플릿을 만든다. 이후 sync는 절대 건드리지
    않는다(내용이 뭐든 — 빈 칸이든 사람이 채운 값이든 — 그대로 둔다).
    개명 이관(마찰 10): 구명 파일만 있으면 내용 그대로 새 이름으로 rename."""
    path = folder / MEETING_NOTE_NAME
    if path.is_file():
        return False
    legacy = folder / _MEETING_NOTE_LEGACY_NAME
    if legacy.is_file():
        legacy.rename(path)
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_MEETING_NOTE_TEMPLATE, encoding="utf-8")
    return True


def _gate_profile_note(run: Path, gate_id: str) -> str:
    """W31 리허설 마찰2: 관문 프로파일 1줄 안내. 실패는 침묵(안내 층 — 파이프라인 계약 아님,
    review_badges 소비와 같은 관례: 값만 쓰고 모듈 부재/오류는 그냥 빈 문자열)."""
    try:
        import gates  # sibling — proposal_pipeline/test_smoke가 이미 scripts/를 sys.path에 얹는다
        return gates.gate_note(run, gate_id)
    except Exception:
        return ""


def _company_note(run: Path) -> str:
    """W31 리허설 마찰6: 선택된 제안사 프로필 1줄 안내(없으면 선택 방법 안내). 실패는 침묵
    (안내 층 — `_gate_profile_note`와 같은 관례)."""
    try:
        import company  # sibling — proposal_pipeline/test_smoke가 이미 scripts/를 sys.path에 얹는다
        sel = company.load_selection(run)
        if not sel or not sel.get("company_id"):
            return "선택된 제안사 프로필 없음 — `start --company <id>`로 연결하거나 `company --list`로 창고를 확인하라."
        cid = sel["company_id"]
        profile = company.load(cid)
        if profile is None:
            return f"제안사 프로필 선택됨: {cid} (profile.json 아직 없음 — `company --bundle --id {cid}`로 인테이크)"
        name = ((profile.get("overview") or {}).get("name") or {}).get("value") or cid
        tag = " [가상]" if profile.get("fictional") and "가상" not in name else ""
        return f"제안사 프로필: {name}{tag} (`proposal_system/companies/{cid}/profile.json`)"
    except Exception:
        return ""


def _master_route_note(run: Path) -> str:
    """W31 R10(β2): 마스터 시안 공정 안내 — 완전 스킨 차용·express 프로파일이면 축약(과제 지시 2).

    실패는 침묵(안내 층 — `_gate_profile_note`·`_company_note`와 같은 관례)."""
    try:
        contract = _load_json(run / "design_contract.json")
        if contract and ((contract.get("meta") or {}).get("full_skin")):
            return "차용 스킨이 이미 완전 스펙(full_skin)이다 — 차용본이 곧 마스터이므로 시안 생성을 생략해도 된다."
        import gates  # sibling
        profile = gates.load_config(run).get("profile")
        if profile == "express":
            return "관문 프로파일=express — 마스터 시안 공정은 권장(생략 가능)만 안내한다."
        return (
            f"`imagedeck --master-bundle --run {run.name}` 로 마스터 시안 프롬프트를 만들고, "
            "직결 세션이 시안을 생성한 뒤 "
            f"`imagedeck --master-apply --file <master_design.json> --run {run.name}` 로 확정한다."
        )
    except Exception:
        return ""


def _exists_line(run: Path, rel: str, label: str) -> str:
    path = run / rel
    mark = "x" if path.exists() else " "
    return f"- [{mark}] {label} — `{rel}`"


def _manual(*, title: str, intro: str, artifacts: list[str], decisions: list[str],
            next_steps: list[str]) -> str:
    lines = [AUTO_GEN_HEADER, f"# {title}", "", intro, ""]
    lines.append("## 이 단계에서 보는 산출물")
    lines.extend(artifacts or ["- (아직 없음)"])
    lines.append("")
    lines.append("## 여기서 하는 의사결정")
    lines.extend(f"- {d}" for d in decisions)
    lines.append("")
    lines.append("## 다음 명령")
    lines.extend(f"- {c}" for c in next_steps)
    lines.append(_MEETING_POINTER)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 폴더별 populate — probe(열림 조건) + 채우기
# ---------------------------------------------------------------------------

def _populate_01(run: Path, folder: Path, report: dict) -> None:
    analysis_dir = run / "analysis"
    cards = sorted(analysis_dir.glob("*_분석카드.md")) if analysis_dir.is_dir() else []
    artifacts = [f"- 대시보드 공고 카드: {DASHBOARD_URL} (Go/Hold/Skip = 메모, 관문 아님)"]
    if cards:
        artifacts.append(f"- 분석카드(이 run에 복제됨): {', '.join(str(c) for c in cards)}")
    else:
        artifacts.append("- 분석카드: run/analysis/*_분석카드.md (bid로 시작한 run이면 여기 복제됨)")
    text = _manual(
        title="01. 공고 찾기 — 모니터링 요원의 메모",
        intro=(
            "나라장터에서 공고를 훑고 관심 있는 것을 메모하는 단계다. **관문이 아니다** — "
            "Go/Hold/Skip은 실행을 트리거하지 않는, 단지 다음에 볼 때 기억하기 위한 메모다."
        ),
        artifacts=artifacts,
        decisions=["이 공고를 계속 지켜볼지(메모만, 착수 결정은 다음 단계 02에서)."],
        next_steps=[f"대시보드({DASHBOARD_URL})에서 공고를 훑고 메모한다.",
                     "착수를 결정하면 02_착수판단/ 로."],
    )
    _write(folder / MANUAL_NAME, text)


def _populate_02(run: Path, folder: Path, report: dict) -> None:
    analysis_dir = run / "analysis"
    cards = sorted(analysis_dir.glob("*_분석카드.md")) if analysis_dir.is_dir() else []
    artifacts = ["- 초안 pptx: `<proposal_core>/draft/*_초안.pptx` (dashboard/proposal_pipeline.py status로 위치 확인)"]
    if cards:
        artifacts.append(f"- 분석카드(이 run에 복제됨): {', '.join(str(c) for c in cards)}")
    artifacts.append(f"- {_company_note(run)}")
    text = _manual(
        title="02. 착수 판단 — 팀장급 의사결정",
        intro=(
            "A0과는 별개인 실제 착수 회의다. 분석→전략→storyline을 거쳐 만든 **초안 pptx**를 "
            "보고 이 공고에 착수할지 결정한다."
        ),
        artifacts=artifacts,
        decisions=["착수 여부(✋ 착수 결정).",
                   "제안사 프로필 선택 여부(선택 — `start --company <id>`는 착수 시에만 지정 가능).",
                   "**내용 먼저 vs 덱 디자인 먼저**(R10 v2) — 발주 내용 기반 디자인(행사 브랜딩 헤더 "
                   "등)이 필요하면 디자인 선행이 맞다: `start` → 03_발주처조사 → 07_테마확정(마스터 "
                   "시안) → 04_내용만들기 순서. 보통은 내용 먼저(기본, 04→05→07 순)가 더 간단하다."],
        next_steps=["착수하면 대시보드에서 공고 고유번호를 복사해 채팅창에 붙여넣는다 "
                    "(클릭 실행이 아니라 이 붙여넣기 자체가 실행 통로다 — R8)."],
    )
    _write(folder / MANUAL_NAME, text)


def _populate_03(run: Path, folder: Path, report: dict) -> None:
    research = run / "institution_research.json"
    artifacts = [_exists_line(run, "institution_research.json", "기관 조사 결과(JSON, 정본)")]
    if research.is_file():
        artifacts.append(f"- 가독 뷰: `{JOURNEY_DIRNAME}/{FOLDERS['03']}/{INSTITUTION_VIEW_NAME}`")
        if _refresh_view(research, folder / INSTITUTION_VIEW_NAME, render_institution_view):
            report["views_rendered"].append(f"03/{INSTITUTION_VIEW_NAME}")
    text = _manual(
        title="03. 발주처 조사 — 문서 밖 근거·브랜드 색 (선택)",
        intro=(
            "RFP 문서만으로는 부족한 '문서 밖 근거'(발주기관 미션·건학이념 → 도입부 직인용)와 "
            "브랜드 색(대표색 → 스킨)을 조사할지 판단하는 선택 단계다. 안 해도 다음으로 진행된다. "
            "⚠️ 기관 사이트의 봇 차단은 기본 환경 — 조사는 소스 계단으로 간다: ①브라우저 열람(기본, "
            "실제 브라우저라 대부분 열림) ②검색 스니펫·보도자료 ③공공 공시 ④RFP 첨부 안의 기관 CI "
            "⑤캡차 화면만 사용자에게 클릭 요청(자동 우회 금지). 못 구한 항목은 공란이 정상이다(중립 진행)."
        ),
        artifacts=artifacts,
        decisions=["문서 밖 근거·브랜드 색을 이 제안에 반영할지(선택 관문 — 건너뛰기 가능)."],
        next_steps=["조사하려면 `python proposal_system/scripts/proposal_pipeline.py research --run "
                    f"{run.name} --bundle` → 결과 저장 후 `--apply`.",
                    "건너뛰려면 `go --run " + run.name + " --confirm`."],
    )
    _write(folder / MANUAL_NAME, text)


def _populate_04(run: Path, folder: Path, report: dict) -> None:
    artifacts = [
        _exists_line(run, "message_map.json", "메시지맵(핵심 주장·전략 축)"),
        _exists_line(run, "skeleton.json", "스켈레톤 역제안(표준 시나리오 더미)"),
        _exists_line(run, "storyline.json", "스토리라인(장표 채움)"),
    ]
    if (run / "storyline.json").is_file():
        artifacts.append(
            f"- 스토리라인 정독 가독 뷰는 여기가 아니라 `{JOURNEY_DIRNAME}/{FOLDERS['05']}/"
            f"{STORYLINE_VIEW_NAME}` 에 있다(회의 산출물이라 05에서 관리)."
        )
    if (run / "deck.doc.html").is_file():
        artifacts.append(
            "- 본문 정독은 `deck.doc.html`(문서형 파생 뷰 — 연속 스크롤, 제출물 아님). "
            "`storyline_읽기.md`는 목차 훑기용, `deck.doc.html`은 장표 본문까지 읽는 용도(W31 리허설 마찰3)."
        )
    artifacts.append(f"- {_company_note(run)}")
    text = _manual(
        title="04. 내용 만들기 — 스켈레톤부터 스토리라인까지",
        intro="RFP 분석 후 핵심 주장·전략 축(메시지맵)을 먼저 확정하고, 그것에 종속해 장표(스켈레톤→스토리라인)를 채운다. 멈추는 곳만 개입한다.",
        artifacts=artifacts,
        decisions=["스켈레톤 역제안 구조를 그대로 쓸지 조정할지(선택 관문, 스토리라인 채움 전).",
                   f"관문 다이얼(W31 리허설 마찰2, `run/gates.json`): {_gate_profile_note(run, 'skeleton_review')}"],
        next_steps=[f"`python proposal_system/scripts/proposal_pipeline.py go --run {run.name}`"],
    )
    _write(folder / MANUAL_NAME, text)


def _populate_05(run: Path, folder: Path, report: dict) -> None:
    storyline = run / "storyline.json"
    artifacts = [
        _exists_line(run, "storyline.json", "스토리라인(장·제목·메시지·불릿·flag) — 회의 핵심 산출물"),
        _exists_line(run, "wireframe.json", "뼈대(참고 — 상세 뷰는 06)"),
        _exists_line(run, "message_map.json", "메시지맵"),
        _exists_line(run, "review_resolutions.json", "검토요망 해소지"),
    ]
    if storyline.is_file():
        artifacts.append(f"- 가독 뷰: `{JOURNEY_DIRNAME}/{FOLDERS['05']}/{STORYLINE_VIEW_NAME}`(회의에서 훑기용)")
        if _refresh_view(storyline, folder / STORYLINE_VIEW_NAME, render_storyline_view):
            report["views_rendered"].append(f"05/{STORYLINE_VIEW_NAME}")
    if (run / "deck.doc.html").is_file():
        artifacts.append(
            "- 본문 정독: run 루트의 `deck.doc.html`(문서형 파생 뷰 — 연속 스크롤, "
            "제출물 아님·정본은 `deck.html`). storyline_읽기.md=목차 훑기, deck.doc.html=본문 정독(W31 리허설 마찰3)."
        )
    text = _manual(
        title="05. 내용 동결 — 회의 라운드 (✋② 의사결정 게이트)",
        intro=(
            "실제 회의체다. storyline_읽기.md(가독 뷰)로 장·제목·핵심 메시지·불릿·[예시]/검토요망 "
            "딱지를 훑으며 피드백을 반복하고 방향을 확정한다. 본문까지 정독하려면 run 루트의 "
            "deck.doc.html(문서형 뷰)을 본다. message_map·storyline·wireframe 전부 중요 산출물이다."
        ),
        artifacts=artifacts,
        decisions=["방향·메시지 확정(동결) — 이후 디자인은 계속 좋아지지만 내용 골격은 여기서 잠근다.",
                   "잔존 검토요망(review_resolutions.json)을 해소할지 보류할지.",
                   "**디자인 강조 장 확정**(이 단계가 그 자리다 — 사용자 고지, W31 R9 마찰17): "
                   "storyline_읽기.md의 ⭐ 강조 후보(표지·간지·결론·핵심 전략 축 지지 장)를 보고 "
                   "실제로 강조할 장을 고른다. 강조 장은 메시지를 한 줄로 줄이거나 장을 분리(주장 "
                   "히어로+상세)하거나 간지를 신설한 뒤 storyline에 `emphasis: \"hero\"` 표식으로 "
                   "기록하고 함께 동결한다(하류 뼈대·이미지는 이 확정을 소비만 한다)."],
        next_steps=["대시보드에서 확정(ack) — 실행 명령이 아니다.",
                    f"확정 후 `go --run {run.name}` 이 design_brief.json을 기본값으로 만든다."],
    )
    _write(folder / MANUAL_NAME, text)


def _populate_06(run: Path, folder: Path, report: dict) -> None:
    wireframe = run / "wireframe.json"
    artifacts = [_exists_line(run, "wireframe.json", "뼈대(frame×piece 결정, 정본)")]
    if wireframe.is_file():
        artifacts.append(f"- 가독 뷰: `{JOURNEY_DIRNAME}/{FOLDERS['06']}/{WIREFRAME_VIEW_NAME}`")
        if _refresh_view(wireframe, folder / WIREFRAME_VIEW_NAME, render_wireframe_view):
            report["views_rendered"].append(f"06/{WIREFRAME_VIEW_NAME}")
        legacy_md = folder / "wireframe_읽기.md"   # 마찰13: 구 md 뷰 잔재 정리(정본 아님 — 파생 뷰)
        if legacy_md.is_file():
            legacy_md.unlink()
    else:
        artifacts.append(_exists_line(run, "wireframe_prompt/prompt.md", "뼈대 결정 프롬프트(핸드오프 전)"))
    text = _manual(
        title="06. 뼈대 확정 — 재조판 확인",
        intro=(
            "내용 동결 후 무채(색 없는) 형태로 재조판된 결과를 확인한다. 테마(B1)는 이 뼈대 "
            "위에 입혀진다. wireframe은 항상 생성된다(스킵 없음 — 2026-07-21 확정)."
        ),
        artifacts=artifacts,
        decisions=["재조판된 frame×piece 배치가 맞는지(선택 관문 — 건너뛰기 가능).",
                   f"관문 다이얼(W31 리허설 마찰2, `run/gates.json`): {_gate_profile_note(run, 'wireframe_review')}"],
        next_steps=["대시보드에서 확인 또는 건너뛰기(실행 명령 아님).",
                    f"통과 후 `go --run {run.name}` 로 디자인 브리핑 단계."],
    )
    _write(folder / MANUAL_NAME, text)


def _imagedeck_refs_note(run: Path) -> str:
    """W31 마찰20(β): run/imagedeck_refs/ 투입 현황(전체·장별) — 폴더=범위 선언 안내."""
    global_dir = run / "imagedeck_refs" / "global"
    slides_dir = run / "imagedeck_refs" / "slides"
    global_n = len(list(global_dir.glob("*.png"))) + len(list(global_dir.glob("*.jpg"))) \
        if global_dir.is_dir() else 0
    slide_dirs = sorted(p.name for p in slides_dir.iterdir() if p.is_dir()) if slides_dir.is_dir() else []
    if global_n or slide_dirs:
        parts = []
        if global_n:
            parts.append(f"전체 {global_n}장(imagedeck_refs/global/)")
        if slide_dirs:
            parts.append(f"장별 {', '.join(slide_dirs)}(imagedeck_refs/slides/<NN>/)")
        return "- 레퍼런스 투입 현황: " + " · ".join(parts)
    return ("- 레퍼런스 투입 현황: 아직 없음 — 비워두면 시드 기본값"
            "(design-assets/references/seed/, 사용자 취향 기준)이 자동 적용된다.")


def _populate_07(run: Path, folder: Path, report: dict) -> None:
    research = run / "institution_research.json"
    contract = run / "design_contract.json"
    artifacts = [
        _exists_line(run, "design_brief.json", "디자인 브리핑(skin.value = 차용 신호)"),
        _exists_line(run, "design_contract.json", "디자인 계약(run별 정본 — R2. chrome/image 2계약 분리, R5)"),
        _exists_line(run, "master_design_prompt.md", "마스터 시안 제작 프롬프트(R10 v2)"),
        _exists_line(run, "master_design.json", "마스터 시안 확정본(R10 v2, 사람 편집물)"),
        _exists_line(run, "design_overrides.json", "정련 override(코드명 stage9, html 라우트)"),
    ]
    if contract.is_file():
        artifacts.append(f"- 계약 가독 뷰: `{JOURNEY_DIRNAME}/{FOLDERS['07']}/{DESIGN_CONTRACT_VIEW_NAME}`")
        if _refresh_view(contract, folder / DESIGN_CONTRACT_VIEW_NAME, render_design_contract_view):
            report["views_rendered"].append(f"07/{DESIGN_CONTRACT_VIEW_NAME}")
    if research.is_file():
        artifacts.append(
            f"- 발주처 브랜드 색(선개방 — A3에서 즉시 적재): "
            f"`{JOURNEY_DIRNAME}/{FOLDERS['07']}/{BRAND_VIEW_NAME}`"
        )
        if _refresh_view(research, folder / BRAND_VIEW_NAME, render_brand_view):
            report["views_rendered"].append(f"07/{BRAND_VIEW_NAME}")
    else:
        artifacts.append("- 발주처 브랜드 색: 아직 없음(03_발주처조사에서 조사하면 여기로 자동 적재)")
    artifacts.append(_imagedeck_refs_note(run))
    route_note = _master_route_note(run)
    if route_note:
        artifacts.append(f"- 마스터 시안 공정(R10 v2): {route_note}")
    text = _manual(
        title="07. 테마 확정 — 마스터 시안 공정 (design_contract 동결 · R2·R3·R5·R10 v2)",
        intro=(
            "B1은 이제 값 동결뿐 아니라 **실물 룩을 보고 확정하는 공정**이다(R10 v2). "
            "`imagedeck --master-bundle`이 복합 입력함(발주처 브랜드·자사 아이덴티티·주제·레퍼런스·"
            "디자인지식 pull)을 자기완결 프롬프트로 만들고, 직결 세션이 마스터 시안(공통 배경·크롬 "
            "조합·대표 장 1~2개 실물)을 생성한다 — 축이 갈리면(발주처축/자사축/주제축) 복수 후보안을 "
            "제시하고 회의에서 하나를 고른다. **내용(storyline) 유무와 무관하게 동작한다** — 디자인을 "
            "먼저 하고 싶으면 내용 없이 지금 바로 돌려도 된다(디자인 선행 루트, 02_착수판단 안내 참고).\n\n"
            "확정된 시안(`imagedeck --master-apply --file <master_design.json>`)은 ①design_contract에 "
            "art_direction(룩 서술)·density(표준/여백형/밀집형)를 기록(재동결 문법 — 기존 계약은 "
            "design_contract.prev.json으로 보존)하고 ②확정 시안 이미지를 `imagedeck_refs/global/`에 "
            "시리즈 레퍼런스로 등록한다(이후 `imagedeck --bundle`이 3계층 조회로 자동 동봉 — 마찰20이 "
            "이미 소비하는 채널이라 별도 배선이 필요 없다).\n\n"
            "design_brief.json의 skin.value에 스킨 이름을 적으면 그 창고 스킨을 **차용**(초안으로 "
            "가져와 이 run에서 다시 수정)하고, 비워두면 하우스 취향 없는 **중립 템플릿**"
            "(skins/_neutral.json)에서 시작한다. inkline도 이제 자동 기본값이 아니라 차용 대상 스킨 "
            "중 하나일 뿐이다. **차용 스킨이 이미 완전 스펙(full_skin)이면 그 자체가 마스터이므로 "
            "시안 생성을 생략해도 된다.** `go`가 이 결정을 병합해 run/design_contract.json(정본)을 "
            "동결하면 theme_confirm 관문(선택 — 회의 없이 기본값 진행 가능, 대시보드에서 ack 가능)이 "
            "뜬다.\n\n"
            "**레퍼런스 투입 자리도 여기다**(마찰20) — `run/imagedeck_refs/global/`에 넣으면 이 run "
            "전체 장에, `run/imagedeck_refs/slides/<NN>/`에 넣으면 그 장에만 적용된다(**폴더 = 범위 "
            "선언**). imagedeck bundle은 장별>전체>시드 순으로 조회하고, 아무것도 없으면 "
            "`design-assets/references/seed/`의 기본 레퍼런스(사용자 취향 기준)를 쓴다. direct 세션 "
            "중 새 레퍼런스(레퍼런스가 될 만한 이미지)를 발견하면, 임의로 넣지 말고 **전체 적용인지 "
            "특정 장 적용인지 사용자에게 확인한 뒤** 해당 폴더에 배치한다. 뒤늦게 넣었다면 "
            "`imagedeck --bundle`로 재번들해야 프롬프트에 반영된다."
        ),
        artifacts=artifacts,
        decisions=["마스터 시안 공정을 돌릴지(내용 선행/디자인 선행 무관 — R10 v2, express 프로파일은 "
                   "권장만·차용 완전 스킨은 생략 가능).",
                   "어떤 스킨을 차용할지(design_brief.skin.value) 또는 중립 템플릿 그대로 둘지.",
                   "동결된 design_contract.json을 확정할지(theme_confirm — 건너뛰어도 진행된다).",
                   "레퍼런스를 전체 적용할지 특정 장만 적용할지(폴더 위치 = 범위 선언).",
                   f"관문 다이얼(W31 리허설 마찰2, `run/gates.json`): {_gate_profile_note(run, 'theme_confirm')}"],
        next_steps=[f"`imagedeck --master-bundle --run {run.name}` → 시안 생성 → "
                    f"`imagedeck --master-apply --file <경로> --run {run.name}`(R10 v2, 선택).",
                    "차용하려면 design_brief.json의 skin.value에 스킨 이름을 적는다(예: \"inkline\").",
                    f"그대로 `go --run {run.name}` — design_contract.json을 생성하고 theme_confirm 관문을 연다.",
                    "대시보드에서 확인(ack) 또는 건너뛰기 — 둘 다 대시보드의 사람 결정만 허용한다.",
                    "브리핑을 고친 뒤라면 `go --refreeze-contract`로 재동결 — 이미 이미지 단계를 지난 "
                    "run은 재동결 직후 `imagedeck --bundle` 재실행이 필요하다는 안내가 뜬다(마찰18)."],
    )
    _write(folder / MANUAL_NAME, text)


def _populate_08(run: Path, folder: Path, report: dict) -> None:
    manifest_path = run / "imagedeck_manifest.json"
    local_dir = run / PROMPTS_LOCAL_DIRNAME
    artifacts = [
        _exists_line(run, "imagedeck_manifest.json", "장별 프롬프트 매니페스트"),
        _exists_line(run, "imagedeck_prompts", "장별 프롬프트(NN.md)"),
    ]
    if local_dir.is_dir():
        overlays = sorted(p.name for p in local_dir.glob("*.md") if p.name.lower() != "readme.md")
        if overlays:
            artifacts.append(
                f"- 오버레이 존재 현황(R6, 재번들에도 살아남음): {', '.join(overlays)}"
            )
        else:
            artifacts.append(
                f"- 오버레이 존재 현황(R6): 아직 없음 — `{PROMPTS_LOCAL_DIRNAME}/NN.md`"
                "(예: 05.md)를 만들면 다음 재번들에서 병합된다. 안내: "
                f"`{PROMPTS_LOCAL_DIRNAME}/README.md`."
            )
    else:
        artifacts.append(
            f"- 사람 편집물(R6 오버레이): `{PROMPTS_LOCAL_DIRNAME}/`는 첫 `imagedeck --bundle`"
            " 때 열린다(빈 폴더+안내 README)."
        )
    gating_path = run / "gating_report.json"
    band_violations = (((_load_json(gating_path) or {}).get("length_rhythm") or {}).get("band_violations") or [])
    if manifest_path.is_file():
        artifacts.append(
            f"- 디자인 지표 뷰(review_badges 채점 → 저점수 장 보강 권고, R9 · 마찰22 밴드 위반 전면 표시): "
            f"`{JOURNEY_DIRNAME}/{FOLDERS['08']}/{DESIGN_METRICS_VIEW_NAME}`"
        )
        # W31 γ패킷(마찰22): 이 뷰는 imagedeck_manifest.json 뿐 아니라 gating_report.json(밴드
        # 위반)도 소스로 삼는다 — _refresh_view의 단일 소스 mtime 비교로는 부족해 여기서 직접
        # 두 파일 중 더 새것을 뷰 mtime과 비교한다(둘 중 하나만 바뀌어도 재생성).
        view_path = folder / DESIGN_METRICS_VIEW_NAME
        newest = manifest_path.stat().st_mtime
        if gating_path.is_file():
            newest = max(newest, gating_path.stat().st_mtime)
        stale = (not view_path.is_file()) or view_path.stat().st_mtime < newest
        if stale:
            manifest_doc = _load_json(manifest_path)
            if manifest_doc is not None:
                text = AUTO_GEN_HEADER + render_design_metrics_view(manifest_doc, band_violations=band_violations)
                if _write(view_path, text):
                    report["views_rendered"].append(f"08/{DESIGN_METRICS_VIEW_NAME}")
        manifest = _load_json(manifest_path) or {}
        full_skin = manifest.get("full_skin")
        artifacts.append(
            "- 프롬프트 스펙 수준: "
            + ("완전 스킨 — 그 스킨의 세부 스펙 그대로 주입" if full_skin
               else "중립/부분 — 축소판(크롬 이웃 브리핑 + 자유, R9 마찰19)")
        )
        tiers = [s.get("references_source") for s in (manifest.get("slides") or [])
                 if s.get("render") != "html"]
        if tiers:
            seed_n, slide_n, global_n, none_n, cli_n = (
                tiers.count(t) for t in ("seed", "slide", "global", "none", "cli"))
            bits = [f"{t}={c}" for t, c in
                    (("장별", slide_n), ("전체", global_n), ("시드", seed_n), ("명시", cli_n), ("없음", none_n))
                    if c]
            artifacts.append(f"- 레퍼런스 조회 결과(장 단위): {' · '.join(bits) if bits else '(없음)'}")
    # W31 γ패킷(마찰22): 밴드 위반은 경고에 묻히지 않게 이 매뉴얼 전면에도 낸다(디자인지표 뷰와 중복
    # 표시 — 관문 직전 눈에 띄어야 한다는 게 마찰22의 요지, "경고와 파손 사이 거리" 단축).
    if band_violations:
        ids = ", ".join(str(v.get("slide_id")) for v in band_violations)
        artifacts.append(
            f"- ⚠️ 분량 밴드 위반 {len(band_violations)}장(slide {ids}) — 3장 이상이면 이 관문이 "
            "자동 재정지된다(gates.py). 하한 내 축소로도 안 되면 다음 `imagedeck --bundle`이 "
            "결정론 사전 분할(A/B)한다(마찰23). 디자인지표 뷰 상단 참고."
        )
    artifacts.append(_imagedeck_refs_note(run))
    text = _manual(
        title="08. 프롬프트·레퍼런스 확인 — 생산 전 마지막 확인",
        intro=(
            "장별 프롬프트와 레퍼런스로 '이렇게 그려질 것'을 사전 확인한다. 기대와 다르면 "
            f"프롬프트 파일을 직접 고치지 말고 `{PROMPTS_LOCAL_DIRNAME}/NN.md`(파일명은 "
            "imagedeck_prompts/의 것과 동일하게 — 예: 05.md, A/B 실험 장은 05A.md/05B.md)에 추가 "
            "지시를 적는다(R6 오버레이 — 비스킵 관문의 유일한 수정 통로). 정본은 이 폴더 쪽이라 "
            "`imagedeck --bundle`을 몇 번을 다시 돌려도 사라지지 않고 매번 프롬프트 말미에 다시 "
            "병합된다. 저점수(밋밋·발산추천) 장은 배경이미지 생성·디자인지식 적용을 권장하는 신호가 "
            "프롬프트에 자동 주입된다(R9 — 채점 데이터가 없으면 조용히 생략, 강제 아님). 장별 "
            "wireframe 적용(on/off) 여부도 여기서 결정한다.\n\n"
            "**레퍼런스 범위 규칙(마찰20, 07_테마확정에서 투입)**: `imagedeck_refs/slides/<NN>/`"
            "(그 장만) > `imagedeck_refs/global/`(전체) > `design-assets/references/seed/`(둘 다 "
            "비었을 때의 기본값) 순으로 조회한다 — **폴더 = 범위 선언**이라 배치한 위치가 곧 적용 "
            "범위다. direct 세션 중 새 레퍼런스를 발견했다면 임의로 넣지 말고 전체/장별 적용 여부를 "
            "사용자에게 확인한 뒤 배치하라. 여기서 뒤늦게 추가·교체했다면 `imagedeck --bundle`로 "
            "재번들해야 프롬프트에 반영된다(재번들 전까지는 낡은 참조가 남는다)."
        ),
        artifacts=artifacts,
        decisions=["프롬프트 문구·레퍼런스가 의도와 맞는지.", "장별 wireframe 적용 여부(on/off).",
                   f"오버레이(`{PROMPTS_LOCAL_DIRNAME}/NN.md`)로 추가 지시를 얹을지.",
                   f"관문 다이얼(W31 리허설 마찰2, `run/gates.json`, 비스킵 - 신호 나쁘면 항상 정지): "
                   f"{_gate_profile_note(run, 'imagedeck_prompt_ack')}"],
        next_steps=["대시보드에서 확인 후 승인(실행 명령 아님).",
                    "고쳤으면(오버레이·레퍼런스 포함) `imagedeck --bundle --run " + run.name
                    + "` 로 재번들 후 다시 확인."],
    )
    _write(folder / MANUAL_NAME, text)


# imagedeck.MANUAL_GUIDE_NAME과 같은 값의 리터럴 — 이 모듈의 기존 문자열 참조 관례
# (PROMPTS_LOCAL_DIRNAME 주석 참고). W32 수동 생산 루트 가이드(같은 09 폴더에 생성된다).
MANUAL_GUIDE_NAME_09 = "이미지_수동생산_가이드.md"


def _populate_09(run: Path, folder: Path, report: dict) -> None:
    slides_dir = run / "imagedeck" / "slides"
    # W32 마찰34: `*.rejected.png`(px 불일치 반려 증거본)은 생산물이 아니다 — 집계에서 뺀다.
    # imagedeck.is_rejected와 같은 규약이지만 여기서 import하지 않는다(순환 임포트 회피 — 이 모듈은
    # 안내 층이고 imagedeck이 journey_folders를 부른다).
    all_png = sorted(slides_dir.glob("*.png")) if slides_dir.is_dir() else []
    rejected = [p for p in all_png if ".rejected" in p.stem]
    n = len(all_png) - len(rejected)
    rejected_n = len(rejected)
    artifacts = [f"- 생산된 이미지: {n}장 — `imagedeck/slides/`"]
    if rejected_n:
        artifacts.append(f"- 반려(px 불일치) 증거본: {rejected_n}장 — `*.rejected.png` "
                         "(재실행하면 해당 장을 다시 위임한다)")
    manual_route = (folder / MANUAL_GUIDE_NAME_09).is_file()
    if manual_route:
        # W32: codex CLI 미감지로 수동 생산 루트가 열린 run — 사람이 직접 생산한다(대기 아님).
        artifacts.append(f"- 수동 생산 가이드 — `journey/{FOLDERS['09']}/{MANUAL_GUIDE_NAME_09}`")
        intro = ("장별 프롬프트로 이미지를 만드는 단계다. 이 run은 **수동 생산 루트**(codex CLI 없음)로 "
                 "열렸다 — 이 폴더의 가이드를 따라 사람이 직접 생성·수거한다.")
        decisions = ["(없음 — 가이드의 절차 수행)"]
        next_steps = [
            f"1) 가이드를 따라 프롬프트 복붙 생성 → 이미지를 한 폴더에 다운로드(파일명=장 번호 시작).",
            f"2) `imagedeck --adopt <폴더> --run {run.name}` (PNG 변환·px 리사이즈·개명·배치 자동).",
            f"3) `imagedeck --collect --run {run.name}` (검증).",
        ]
    else:
        intro = ("Codex가 장별 프롬프트로 이미지를 그리는 단계다. 사람은 대기한다(자동 생산). "
                 "codex CLI가 없는 환경이면 `--produce`가 수동 생산 가이드를 이 폴더에 만들고 "
                 "복붙→adopt 절차로 자동 전환한다(W32).")
        decisions = ["(없음 — 대기)"]
        next_steps = [f"`imagedeck --produce --run {run.name}`(자동 실행, 대개 go가 안내)."]
    text = _manual(
        title="09. 이미지 생산" + (" — 수동 루트" if manual_route else " — 대기"),
        intro=intro,
        artifacts=artifacts,
        decisions=decisions,
        next_steps=next_steps,
    )
    _write(folder / MANUAL_NAME, text)


def _populate_10(run: Path, folder: Path, report: dict) -> None:
    artifacts = [_exists_line(run, "imagedeck_collect.json", "수거 검증 결과(px·커버리지)"),
                 _exists_line(run, "imagedeck/collect_report.md", "수거 검증 리포트(사람이 읽는 판)")]
    text = _manual(
        title="10. 수거 검증 — 결과 훑기",
        intro="생산된 이미지의 px·커버리지·파일명을 결정론으로 검증한 결과를 훑는다.",
        artifacts=artifacts,
        decisions=["결과가 FAIL이면 무엇을 다시 그릴지."],
        next_steps=[f"`imagedeck --collect --run {run.name}`(불합격 시 재생성 지시를 따른다)."],
    )
    _write(folder / MANUAL_NAME, text)


def _populate_11(run: Path, folder: Path, report: dict) -> None:
    artifacts = [
        _exists_line(run, "imagedeck/collect_report.md", "수거 검증 리포트"),
        _exists_line(run, "imagedeck_review.md", "Claude 검수 scaffold(선택)"),
        _exists_line(run, "deck_review.md", "LLM 덱 평가(html_editable 라우트)"),
    ]
    text = _manual(
        title="11. 장표 정독·채택",
        intro="오탈자·고스팅·정본 대조를 정독한다(선택: Claude 검수 scaffold 활용). 결함 장만 국소 재생성한다.",
        artifacts=artifacts,
        decisions=["장표를 채택할지, 어떤 장을 국소 재생성할지.",
                   f"관문 다이얼(W31 리허설 마찰2, `run/gates.json`, 비스킵 - 신호 나쁘면 항상 정지): "
                   f"{_gate_profile_note(run, 'imagedeck_ack')}"],
        next_steps=["대시보드에서 이미지 장표 승인(imagedeck_ack, 실행 명령 아님).",
                    f"국소 재생성: `imagedeck --produce --only <N> --run {run.name}`."],
    )
    _write(folder / MANUAL_NAME, text)


def _populate_12(run: Path, folder: Path, report: dict) -> None:
    artifacts = [_exists_line(run, "deck.images.html", "완성 이미지 덱(크롬+본문 합성)"),
                 _exists_line(run, "deck.html", "완성 덱(html_editable 라우트)")]
    text = _manual(
        title="12. 합성·완성 검토 — 디자인 게이트",
        intro="크롬(제목·로고)과 본문을 합성한 완성 덱을 검토한다(✋ 디자인 게이트).",
        artifacts=artifacts,
        decisions=["완성 덱을 승인할지, 편집할지, 반려할지."],
        next_steps=["`deck.images.html`을 그냥 더블클릭해서 연다(서버 불필요). 화면에 맞춰 자동 축소되고 "
                    "화살표 키로 한 장씩 넘어간다 — 좌측 썸네일을 눌러 바로 이동해도 된다.",
                    "발표·리허설로 쓰려면 창을 두 개 열고 주소 뒤에 각각 `?present`(발표자 창)와 "
                    "`?clean`(전면 창)을 붙인다 — 한쪽에서 넘기면 다른 쪽이 따라온다(같은 브라우저 안에서만).",
                    "대시보드에서 검토 완료(실행 명령 아님).",
                    f"완료 후 `go --run {run.name}` 또는 바로 `ship --run {run.name}`."],
    )
    _write(folder / MANUAL_NAME, text)


def _populate_13(run: Path, folder: Path, report: dict) -> None:
    artifacts = [_exists_line(run, "approval.json", "승인 기록"),
                 _exists_line(run, "deck.pptx", "하이브리드 pptx(크롬 수정 가능)")]
    text = _manual(
        title="13. 승인·출하",
        intro="제출본을 확정한다. 하이브리드 pptx는 크롬(제목·로고)만 네이티브 수정 가능하고 본문은 이미지다.",
        artifacts=artifacts,
        decisions=["제출본 확정."],
        next_steps=[f"`python proposal_system/scripts/proposal_pipeline.py ship --run {run.name} --pptx`"],
    )
    _write(folder / MANUAL_NAME, text)


def _populate_14(run: Path, folder: Path, report: dict) -> None:
    artifacts = [_exists_line(run, "deck.pptx", "최종 제안서(pptx)"),
                 _exists_line(run, "_archive_meta.json", "보관 완료 표식(이 run이 보관소로 이관된 경우)")]
    text = _manual(
        title="14. 마무리 — 실데이터 교체·제출·보관",
        intro="[예시]·검토요망 딱지가 남은 실데이터를 교체하고 제출한다(딱지 제거 = 네이티브 pptx에서 직접 수정, 이미지 재생성 불필요). "
              "제출까지 끝났으면 창고에 남겨둘 자산을 졸업(등록)시키고, run 자체는 보관소로 정리한다(리허설 마찰9).",
        artifacts=artifacts,
        decisions=[
            "잔존 [예시]/검토요망을 전부 실데이터로 교체했는지 확인.",
            "재사용할 스킨·레퍼런스가 있으면 창고로 졸업시킬지(선택).",
        ],
        next_steps=[
            "1) 실데이터 교체 확인 (위 결정 체크).",
            "2) (선택) 졸업 — 재사용 가치 있는 스킨·가이드를 창고에 등록: "
            "`python proposal_system/scripts/proposal_pipeline.py curate --register <id>`"
            "(창고 후보 확인 = `curate --list`).",
            f"3) 보관 — 활성 run 목록 정리: "
            f"`python proposal_system/scripts/proposal_pipeline.py archive --run {run.name}` "
            "(한글명 미지정 시 자동 유도 후 확정값을 보여준다 — `--name`으로 직접 지정도 가능).",
        ],
    )
    _write(folder / MANUAL_NAME, text)


# key -> (probe, populate)
_STEPS: dict[str, tuple[Callable[[Path], bool], Callable[[Path, Path, dict], None]]] = {
    "01": (lambda run: True, _populate_01),  # run 존재=A0/A1 이미 지남 — 포인터만, 항상 연다.
    "02": (lambda run: True, _populate_02),
    "03": (lambda run: (run / "institution_research.json").is_file()
                        or (run / "research_prompt").is_dir(),
           _populate_03),
    "04": (lambda run: (run / "skeleton.json").is_file()
                        or (run / "message_map.json").is_file()
                        or (run / "storyline.json").is_file(),
           _populate_04),
    "05": (lambda run: (run / "storyline.json").is_file(), _populate_05),
    "06": (lambda run: (run / "wireframe.json").is_file()
                        or (run / "wireframe_prompt" / "prompt.md").is_file(),
           _populate_06),
    "07": (lambda run: (run / "institution_research.json").is_file()
                        or (run / "design_brief.json").is_file()
                        or (run / "design_overrides.json").is_file()
                        or (run / "design_contract.json").is_file()
                        # W31 R10(β2): 디자인 선행 루트 — 내용(storyline) 없이 마스터 시안부터
                        # 시작해도 07_테마확정이 즉시 열린다(R7 수납처 선개방과 동형).
                        or (run / "master_design_prompt.md").is_file()
                        or (run / "master_design.json").is_file(),
           _populate_07),
    "08": (lambda run: (run / "imagedeck_manifest.json").is_file()
                        or (run / "imagedeck_prompts").is_dir(),
           _populate_08),
    "09": (lambda run: (run / "imagedeck" / "slides").is_dir()
                        and any((run / "imagedeck" / "slides").iterdir()),
           _populate_09),
    "10": (lambda run: (run / "imagedeck_collect.json").is_file(), _populate_10),
    "11": (lambda run: (run / "imagedeck" / "collect_report.md").is_file()
                        or (run / "deck_review.md").is_file(),
           _populate_11),
    "12": (lambda run: (run / "deck.images.html").is_file()
                        or (run / "deck_review.md").is_file(),
           _populate_12),
    "13": (lambda run: (run / "approval.json").is_file(), _populate_13),
    "14": (lambda run: (run / "deck.pptx").is_file(), _populate_14),
}


def sync(run: Path) -> dict[str, Any]:
    """journey/ 폴더 트리를 현재 run 상태에 맞춰 연다·갱신한다.

    `go`가 매 호출마다 부른다(단일 호출점). 결정론·0토큰·멱등 — 이미 열린 폴더를 다시
    닫지 않는다(폴더는 한 번 열리면 계속 남는다, "뒤로 가기에도 헷갈리지 않는 구조" R7).

    반환값(데모/로그용 리포트):
      - `newly_opened`: 이번 호출에서 처음 생긴 폴더 키(수납처 선개방 확인용).
      - `active`: 이번 호출에서 매뉴얼을 재작성한 폴더 키 전부(새로 열렸든 이미 있었든).
      - `views_rendered`: 이번 호출에서 실제로 다시 쓴 파생 뷰 경로(정본 mtime이 더 새로울 때만).
      - `meeting_notes_created`: 이번 호출에서 **처음** 생긴 `회의체_메모.md` 경로(사람 편집물 —
        이미 있으면 절대 건드리지 않는다, R4 유실 방지 수정 2026-07-21).
    """
    run = Path(run)
    report: dict[str, Any] = {
        "newly_opened": [], "active": [], "views_rendered": [], "meeting_notes_created": [],
    }
    if not run.is_dir():
        return report
    for key, (probe, populate) in _STEPS.items():
        try:
            should_open = bool(probe(run))
        except OSError:
            should_open = False
        folder = folder_path(run, key)
        already = folder.is_dir()
        if not should_open and not already:
            continue
        if not already:
            report["newly_opened"].append(key)
        populate(run, folder, report)
        # 사람 편집물(R4): 매뉴얼(파생/포인터)과 별도로, 없을 때만 만들고 이후엔 건드리지 않는다.
        if _ensure_meeting_note(folder):
            report["meeting_notes_created"].append(f"{key}/{MEETING_NOTE_NAME}")
        report["active"].append(key)

    # W31 리허설 마찰5: 산출물.html(클릭 링크 + 계보) — 활성 폴더마다 매 sync에서 다시 만든다.
    # 완료 시각·계보는 pipeline_state의 기록에서 결정론으로 뽑는다(추측 없음). 실패해도(파이프라인
    # state 판독 오류 등) 폴더/매뉴얼 갱신 자체를 막지 않는다 — 이 뷰는 안내 층이다.
    stages: dict[str, dict[str, Any]] = {}
    view_for_overview: dict[str, Any] | None = None
    try:
        import pipeline_state  # sibling, 지연 임포트(순환 방지)
        view_for_overview = pipeline_state.resolve(run)
        stages = view_for_overview.get("stages") or {}
    except Exception:
        pass
    for key in report["active"]:
        html = render_output_view(run, key, stages)
        folder = folder_path(run, key)
        if html is None:
            continue
        if _write(folder / OUTPUT_VIEW_NAME, html):
            report["views_rendered"].append(f"{key}/{OUTPUT_VIEW_NAME}")

    # journey 루트 지도(_전체여정.html) — 산출물이 하나라도 있으면(=폴더가 하나라도 열렸으면) 만든다.
    if report["active"]:
        current_key = _current_folder_key(view_for_overview)
        overview_html = render_overview(run, stages, current_key)
        if _write(journey_root(run) / OVERVIEW_NAME, overview_html):
            report["views_rendered"].append(OVERVIEW_NAME)
    return report
