# -*- coding: utf-8 -*-
"""W3c 덱 평가 — 승인 전 LLM 비전 게이트 (`run/deck_review.md`).

NORTHSTAR_REDESIGN §N6-1 + §6 결정 3: `stage9 → LLM 평가 → 디자인 게이트 → approve`.
평가는 사람이 디자인 게이트에서 읽는 **판단 자료**다(차단자가 아니다).

**이 모듈의 결정론 몫**(§N1-D4 "go는 LLM을 호출하지 않는다"):
  1. 프롬프트 번들 조립 — 입력 4원천 = deck.json + deck.html **슬라이드 실측** +
     gating_report(design_checks·applied_axes) + design_brief + 규칙층 가이드.
  2. 산출물 계약 검증 — `deck_review.md`의 필수 섹션·verdict 토큰을 확인하고 수거한다.

LLM 호출은 go/ship이 하지 않는다 — secure=복붙 왕복, direct=세션 지시(핸드오프 문구만 다르다).

**실측의 출처는 deck.html 마크업**이지 `fill_images()`·디렉터의 자기보고가 아니다.
gating_report의 기록과 지금 잰 값이 어긋나면 그 사실 자체를 프롬프트에 싣는다(정합 신호).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

REVIEW_NAME = "deck_review.md"
BUNDLE_DIR = "deck_review"
PROMPT_NAME = "deck_review_prompt.md"

# 출력 계약(prompts/deck_review.md와 같은 문자열 — 계약의 단일 소재지는 이 상수다).
REQUIRED_SECTIONS = ("## 총평", "## 슬라이드별", "## 승인 권고")
VERDICTS = ("approve", "revise")
MIN_CHARS = 300

_VERDICT_RE = re.compile(r"^[ \t]*-[ \t]*verdict:[ \t]*([A-Za-z]+)", re.M)


def review_path(run: Path) -> Path:
    return Path(run) / REVIEW_NAME


def prompt_path(run: Path) -> Path:
    return Path(run) / BUNDLE_DIR / PROMPT_NAME


def exists(run: Path) -> bool:
    return review_path(run).is_file()


# ── 실측 ────────────────────────────────────────────────────────────────────

def measure(html: str) -> dict[str, Any]:
    """deck.html → design_checks 계열 실측(같은 모듈을 재사용 — 두 번째 구현 금지)."""
    import design_checks  # type: ignore  # sys.path는 호출부(proposal_pipeline)가 세운다
    return design_checks.compute_design_checks(html)


def _fmt_slot(im: dict[str, Any]) -> str:
    f = im.get("fulfillment")
    return (f"total={im.get('total')} filled={im.get('filled')} "
            f"placeholder={im.get('placeholder')} fulfillment={'미정의(슬롯 0)' if f is None else f}")


def _render_browser_layer(browser: dict[str, Any] | None) -> list[str]:
    """W6-A1: 브라우저 실측 계층(있으면). 미측정은 미측정이라고 적는다 — 침묵은 가짜 pass다."""
    if not browser:
        return ["- 브라우저 실측(browser): **없음** — 정적 파싱만으로 판단 중이다(절대배치·겹침은 못 본다).", ""]
    if browser.get("status") == "unmeasured":
        return [f"- 브라우저 실측(browser): **미측정** — {browser.get('reason', '(사유 미기록)')}. "
                "겹침·오버플로는 확인되지 않았다(결함 없음이 아니다).", ""]
    s = browser.get("summary") or {}
    lines = [
        f"- 브라우저 실측(browser): **{browser['status']}** "
        f"(뷰포트 {browser['viewport']['width']}×{browser['viewport']['height']} — PNG와 같은 좌표계) "
        f"overflow={s.get('overflow')} occlusion={s.get('occlusion')} "
        f"content_overlap={s.get('content_overlap')} void={s.get('void')}",
        f"  - 방법: {browser.get('method', '(미기록)')}",
    ]
    # W12: 실결함 계열 flag를 조용한 warn이 아니라 1급 "수리 대상"으로 앞세운다(승격).
    try:
        import layout_probe  # type: ignore  # app/render는 호출부(bundle_deck_review)가 세운다
        targets = layout_probe.repair_targets(browser)
    except Exception:
        targets = []
    if targets:
        tag = "; ".join(f"slide {t['slide_id']} {'/'.join(t['flags'])}" for t in targets)
        lines.append(f"  - **수리 대상 {len(targets)}건**(실결함 계열 — 반드시 지적): {tag}")
    for row in browser.get("slides") or []:
        if not row.get("flags"):
            continue
        det = [f"{b['selector']} height={b['height_px']}px void_ratio={b['void_ratio']}"
               for b in row.get("void_blocks") or []]
        det += [f"{o['box']} {o['overlap_px']}px²" for o in row.get("content_overlaps") or []]
        det += [f"{o['target']} {int(o['ratio'] * 100)}% 가림" for o in row.get("occlusions") or []]
        lines.append(f"  - slide {row['slide_id']}: {', '.join(row['flags'])} "
                     f"(overflow {row['overflow_px']}px; {'; '.join(det[:4]) or '-'})")
    lines.append("")
    return lines


def render_measurements(measured: dict[str, Any], recorded: dict[str, Any] | None) -> str:
    """슬라이드 실측 표 + 기록본(gating_report.design_checks)과의 정합 신호."""
    s = measured["summary"]
    lines = [
        f"- 측정 출처: {measured['measured_from']}",
        f"- 방법 한계: {measured['method']}",
        f"- 상태: **{measured['status']}** (fail 없음 — 게이트는 차단하지 않는다. "
        f"pass = \"기존 덱들의 범위 안\"이지 \"잘 디자인됨\"이 아니다)",
        f"- 슬라이드 {s['slides']}장 · density_over={s['density_over']} density_under={s['density_under']} "
        f"bullets_over={s['bullets_over']} overflow_risk={s['overflow_risk']} "
        # W31 γ패킷(마찰25): 기존 gating_report(이 키 도입 전)와의 호환을 위해 .get 기본값 0.
        f"title_overflow_risk={s.get('title_overflow_risk', 0)}",
        f"- 이미지 슬롯: {_fmt_slot(s['image_slots'])}",
        "",
        "| slide | text_chars | bullets | long_lines | slots | placeholder | flags |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in measured["slides"]:
        lines.append(
            f"| {row['slide_id']} | {row['text_chars']} | {row['bullets']} | {row['long_lines']} | "
            f"{row['image_slots']} | {row['image_slots_placeholder']} | {', '.join(row['flags']) or '-'} |"
        )
    lines.append("")
    lines.extend(_render_browser_layer(measured.get("browser")))
    if recorded:
        rs = recorded.get("summary") or {}
        same = rs == s
        lines.append(
            f"- gating_report.design_checks와의 정합: **{'일치' if same else '불일치'}** "
            f"(기록본 status={recorded.get('status')}, updated_by={recorded.get('updated_by', '-')})"
        )
        if not same:
            lines.append(
                "  - 불일치는 신호다: 기록 이후 deck.html이 다시 렌더됐거나(override 소실) "
                "기록이 낡았다. 지금 잰 값이 마크업의 사실이다."
            )
    else:
        lines.append("- gating_report.design_checks 없음 — 기록본과 대조하지 못했다(미측정).")
    return "\n".join(lines)


def render_applied_axes(axes: dict[str, Any] | None) -> str:
    if not isinstance(axes, dict):
        return "- applied_axes.html 없음 — 렌더 축(pack/skins/override 적용 여부)을 모른다(지어내지 않음)."
    return (
        f"- pack={axes.get('pack')} skins={axes.get('skins')} overrides={axes.get('overrides')} "
        f"image_slots={axes.get('image_slots')} (placeholder={axes.get('image_slots_placeholder')})\n"
        f"- 출처: {axes.get('measured_from', '(미기록)')} / updated_by={axes.get('updated_by', '(미기록)')}"
    )


# ── 번들 ────────────────────────────────────────────────────────────────────

def build_prompt(
    *,
    run: Path,
    header: str,
    contract: str,
    deck_json_text: str,
    measured: dict[str, Any],
    recorded_checks: dict[str, Any] | None,
    applied_axes: dict[str, Any] | None,
    brief_block: str | None,
    guide_blocks: list[tuple[str, str, int]],
) -> str:
    """평가 프롬프트 조립. 결정론·0토큰(텍스트만 붙인다)."""
    run = Path(run)
    parts = [header, contract, f"\n\n# 대상 run: {run.name}\n"]

    parts.append("\n# 입력 ①: deck.json (내용 SSOT — 참조만, 변경 금지)\n")
    parts.append(deck_json_text)

    parts.append("\n\n# 입력 ②: deck.html 슬라이드 실측 (마크업 파싱 — 자기보고 아님)\n")
    parts.append(render_measurements(measured, recorded_checks))

    parts.append("\n\n# 입력 ③: 렌더 축 (gating_report.applied_axes.html)\n")
    parts.append(render_applied_axes(applied_axes))

    if brief_block:
        parts.append("\n\n# 입력 ④: 디자인 브리핑 (design_brief.json — 이 덱의 결정. 평가 기준)\n")
        parts.append(brief_block)
        parts.append("\n\n브리핑의 리듬·슬롯 계획이 실측과 어긋나는 지점을 반드시 지적하라.\n")
    else:
        parts.append("\n\n# 입력 ④: 디자인 브리핑 — **없음**. 리듬·슬롯 계획 대조는 생략한다(미측정).\n")

    parts.append("\n\n# 입력 ⑤: 규칙층 디자인 가이드 (무엇이 좋은 디자인인가 — SSOT)\n")
    if not guide_blocks:
        parts.append("(등록된 가이드 없음 — 위계·그리드 판단은 일반 원칙으로.)\n")
    for gid, text, n_examples in guide_blocks:
        parts.append(f"\n## [{gid}]\n")
        parts.append(text)
        if n_examples:
            parts.append(f"\n(시각 예시 {n_examples}장 — 비전 입력으로 사용)\n")

    parts.append(
        "\n\n# 렌더 산출물\n"
        f"- HTML: {run / 'deck.html'}\n"
        "- 슬라이드 PNG가 있으면 `assets/slides/slide_NN.png`를 비전 입력으로 사용.\n"
        f"\n# 출력\n- `{review_path(run)}` 하나만 쓴다(위 출력 계약 형식 그대로).\n"
        f"- 저장 후 `python proposal_system/scripts/proposal_pipeline.py go --run {run.name}` 가 "
        "결정론 검증기로 수거한다.\n"
    )
    return "".join(parts)


# ── 수거·검증 ────────────────────────────────────────────────────────────────

def validate(text: str) -> list[str]:
    """산출물 계약 검증. 반환 = 위반 목록(빈 리스트 = 통과)."""
    errs: list[str] = []
    body = text or ""
    for sec in REQUIRED_SECTIONS:
        if sec not in body:
            errs.append(f"필수 섹션 누락: `{sec}`")
    m = _VERDICT_RE.search(body)
    if not m:
        errs.append("`- verdict: approve|revise` 줄 없음")
    elif m.group(1).lower() not in VERDICTS:
        errs.append(f"verdict 값이 계약 밖: {m.group(1)!r} (허용: {'/'.join(VERDICTS)})")
    if len(body.strip()) < MIN_CHARS:
        errs.append(f"본문이 너무 짧다({len(body.strip())}자 < {MIN_CHARS}) — 평가로 보기 어렵다")
    return errs


def verdict_of(text: str) -> str | None:
    m = _VERDICT_RE.search(text or "")
    if not m:
        return None
    v = m.group(1).lower()
    return v if v in VERDICTS else None


def collect(run: Path) -> dict[str, Any]:
    """`deck_review.md` 수거. 계약 위반이면 errors를 담아 돌려준다(호출부가 판단)."""
    p = review_path(run)
    if not p.is_file():
        return {"path": str(p), "found": False, "errors": ["deck_review.md 없음"], "verdict": None}
    text = p.read_text(encoding="utf-8", errors="replace")
    errs = validate(text)
    return {
        "path": str(p),
        "found": True,
        "chars": len(text.strip()),
        "verdict": verdict_of(text),
        "errors": errs,
    }
