"""P3-1 review badges — deterministic per-slide divergence triage (0 tokens).

Classifies every slide of a canonical deck into one review-gate verdict so the
dashboard can propose which slides deserve Phase 3 brainstorming (발산):

  - ``발산추천`` (divergence-recommended): a *divergent-type* section (전략/차별화/
    접근방법/핵심메시지/창의제안) that is also **thin** — the analysis card holds
    no ready answer, so idea generation + human review is warranted.
  - ``밋밋`` (bland): thin, but a *deterministic-type* section (표지/목차/개요/일정/
    자격/리스크/조직/사례). Its gap is a fields/enrich shortfall (backlog A),
    NOT a divergence candidate — filling it is deterministic, not creative.
  - ``충실`` (substantial): filled enough; no action needed.

Pure string/shape heuristics over the canonical deck. No LLM, no I/O — the two
signals of QUALITY_PLAN §9.2 combined:
  · Signal A — section classification (the tables below = the "config").
  · Signal B — thinness (content units = bullets + filled field leaves, review flags).

Design: QUALITY_PLAN §9.6 P3-1.
"""

from __future__ import annotations

from typing import Any

# ── Signal A: section classification table (§9.4) ──────────────────────────
# Matched (case-insensitive substring) against a slide's role + title.
# Deterministic keywords take precedence on conflict — conservative, so we do
# not over-recommend divergence for e.g. a "전략 추진 일정" (really a schedule).
DIVERGENT_KEYWORDS: tuple[str, ...] = (
    "전략", "strategy",
    "차별", "차별화", "차별점", "differentiat",
    "접근방법", "접근 방법", "접근법", "방법론", "approach", "methodology",
    "핵심메시지", "핵심 메시지", "가치제안", "value proposition",
    "창의", "아이디어", "창의제안", "idea", "creative",
)

DETERMINISTIC_KEYWORDS: tuple[str, ...] = (
    "표지", "cover",
    "목차", "agenda", "contents", "차례",
    "개요", "배경", "overview", "background",
    "문제", "이슈", "과제", "고민", "problem", "issue", "challenge",
    "요약", "핵심요약", "시사점", "summary", "takeaway",
    "프로세스", "절차", "단계", "process", "step", "workflow",
    "일정", "로드맵", "기간", "주차", "schedule", "roadmap", "timeline", "gantt",
    "비교", "평가", "장단점", "compare", "comparison", "assessment",
    "데이터", "지표", "성과", "예산", "정량", "data", "metric", "kpi", "budget",
    "자격", "요건", "요구사항", "qualification", "requirement",
    "리스크", "위험", "risk",
    "조직", "인력", "역할", "team", "organization", "org",
    "사례", "실적", "경험", "포트폴리오", "case", "portfolio", "reference",
    "결론", "기대효과", "마무리", "감사", "약속", "closing", "conclusion",
)

# Deterministic section keywords that must win even when a divergent keyword is
# also present in the haystack (e.g. "전략 추진 일정" → schedule, not strategy).
_DETERMINISTIC_PRECEDENCE = True

# ── Signal B: thinness thresholds ──────────────────────────────────────────
# W31 리허설 마찰 16(2026-07-21): 구 기준은 불릿(body) 수만 내용으로 세어, 내용이
# 템플릿 필드(fields)에 담기는 현행 덱에서는 전 장이 자동으로 "얇음" 판정됐다
# (22/22 thin 실측). 내용 단위 = 불릿 + 채워진 필드 리프 값(예시 딱지 제외)으로 현대화.
_CONTENT_TARGET = 3         # content units below this count contribute to thinness
_THIN_THRESHOLD = 3         # thin_score >= this → the slide is "thin"
_SHORT_MESSAGE_CHARS = 20   # key_message shorter than this adds a thinness point

_EXAMPLE_MARKERS = ("[예시]", "예시 데이터")   # 예시 표기가 든 문자열 리프는 내용으로 안 센다


def _filled_leaves(value: Any) -> int:
    """fields 안의 '채워진 내용 리프 값' 수 — 결정론.

    센다: 비어 있지 않은 문자열(예시 표기 제외)·숫자. 안 센다: bool·None·빈 값,
    `is_example`/밑줄 시작 키, `is_example: true`가 붙은 dict 전체(예시 데이터 블록).
    """
    if isinstance(value, dict):
        if value.get("is_example") is True:
            return 0
        return sum(
            _filled_leaves(v) for k, v in value.items()
            if not (isinstance(k, str) and (k.startswith("_") or k == "is_example"))
        )
    if isinstance(value, (list, tuple)):
        return sum(_filled_leaves(v) for v in value)
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, (int, float)):
        return 1
    text = str(value).strip()
    if not text or any(m in text for m in _EXAMPLE_MARKERS):
        return 0
    return 1

VERDICT_DIVERGE = "발산추천"
VERDICT_BLAND = "밋밋"
VERDICT_SUBSTANTIAL = "충실"


def _haystack(slide: dict) -> str:
    parts = (slide.get("role"), slide.get("title"))
    return " ".join(str(p) for p in parts if p).lower()


def _classify_section(slide: dict) -> str:
    """Return 'divergent' | 'deterministic' | 'other' for the slide's section."""
    text = _haystack(slide)
    hit_det = any(k in text for k in DETERMINISTIC_KEYWORDS)
    hit_div = any(k in text for k in DIVERGENT_KEYWORDS)
    if hit_det and (_DETERMINISTIC_PRECEDENCE or not hit_div):
        return "deterministic"
    if hit_div:
        return "divergent"
    return "deterministic" if hit_det else "other"


def _thinness(slide: dict) -> tuple[int, dict]:
    """Deterministic thinness score (higher = thinner) plus its raw signals."""
    body = slide.get("body") or []
    fields = slide.get("fields") or {}
    review = slide.get("review_needed") or []
    key_message = slide.get("key_message") or ""

    bullets = len(body) if isinstance(body, (list, tuple)) else 0
    has_fields = bool(fields) if isinstance(fields, dict) else False
    field_values = _filled_leaves(fields) if isinstance(fields, dict) else 0
    has_flag = bool(review) if isinstance(review, (list, tuple)) else bool(review)
    msg_len = len(str(key_message))

    # 마찰 16: 내용 단위 = 불릿 + 채워진 필드 리프 값. 불릿 0이어도 필드가 알차면
    # 얇음이 아니다(필드형 덱). 빈 장(둘 다 0)은 종전과 동일하게 즉시 얇음.
    content_units = bullets + field_values
    score = max(0, _CONTENT_TARGET - content_units)
    if has_flag:
        score += 1
    if msg_len < _SHORT_MESSAGE_CHARS:
        score += 1

    signals = {
        "bullets": bullets,
        "has_fields": has_fields,
        "field_values": field_values,
        "content_units": content_units,
        "has_flag": has_flag,
        "message_chars": msg_len,
    }
    return score, signals


def _verdict(section_type: str, thin_score: int) -> str:
    thin = thin_score >= _THIN_THRESHOLD
    if not thin:
        return VERDICT_SUBSTANTIAL
    return VERDICT_DIVERGE if section_type == "divergent" else VERDICT_BLAND


def compute_review_badges(deck: dict) -> dict:
    """Attach a deterministic review verdict to every slide of ``deck``.

    Returns a report dict (does not mutate ``deck``):
      {
        "badges": [{slide_id, section_type, verdict, thin_score, signals}, ...],
        "divergence_candidates": [slide_id, ...],   # verdict==발산추천, thinnest first
        "counts": {"발산추천": n, "충실": n, "밋밋": n},
      }

    W31 R9(리허설 마찰17, 2026-07-21 확정): a slide with ``emphasis == "hero"`` was deliberately
    thinned at A5 (내용 동결) — it is a structural decision, not a content gap. Such slides are
    always classified 충실 (never 밋밋/발산추천) so gates' low-score ratio does not count them,
    and ``signals["emphasis"] = True`` is recorded (omitted entirely otherwise — no key added,
    matching the conditional-carry convention used elsewhere in this codebase).
    """
    slides = deck.get("slides") or []
    badges: list[dict] = []
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        section_type = _classify_section(slide)
        thin_score, signals = _thinness(slide)
        if slide.get("emphasis") == "hero":
            verdict = VERDICT_SUBSTANTIAL
            signals["emphasis"] = True
        else:
            verdict = _verdict(section_type, thin_score)
        badges.append(
            {
                "slide_id": slide.get("slide_id"),
                "section_type": section_type,
                "verdict": verdict,
                "thin_score": thin_score,
                "signals": signals,
            }
        )

    candidates = sorted(
        (b for b in badges if b["verdict"] == VERDICT_DIVERGE),
        key=lambda b: (-b["thin_score"], b["slide_id"] if b["slide_id"] is not None else 0),
    )
    counts = {VERDICT_DIVERGE: 0, VERDICT_SUBSTANTIAL: 0, VERDICT_BLAND: 0}
    for b in badges:
        counts[b["verdict"]] = counts.get(b["verdict"], 0) + 1

    return {
        "badges": badges,
        "divergence_candidates": [b["slide_id"] for b in candidates],
        "counts": counts,
    }
