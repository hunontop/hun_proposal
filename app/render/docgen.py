# -*- coding: utf-8 -*-
"""정본 SlideModel(deck) → 문서형 파생 뷰(deck.doc.html) — 검토·회의 정독용.

W31 리허설 마찰 3호(CONTEXT/REHEARSAL_FRICTIONS_W31.md 3행): 스켈레톤 기반 deck.html은
장(페이지) 단위로 끊긴 덱 형태라 정독·회의에 가독성이 나쁘다. 이 모듈은 **같은 SlideModel**을
페이지 프레임·고정 px 캔버스 없는 연속 스크롤 문서로 재조판한다.

⚠️ 이 모듈은 render_html(정본, htmlgen.py)의 출력 바이트에 관여하지 않는다 — deck.html은
승인·pptx·이미지 트랙이 계약한 정본 구조라 여기서 절대 건드리지 않는다(호출부에서 별도 호출).
이 모듈은 오직 deck.doc.html(제출물 아님, 참고용 문서 뷰)만 생성한다.

원칙(htmlgen.py와 동형):
  - 노하우 0 — 특정 팩/스킨 색을 모른다(중립 타이포 CSS만).
  - 자기완결 단일 HTML — 외부 의존 0.
  - 조판 실패 필드는 크래시 대신 **우아하게 생략**(개별 필드/슬라이드 단위 try/except).

사용: python app/render/docgen.py <deck.json> <out.doc.html>
"""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


# W32 마찰28: deck.doc.html은 정독용 검토 표면이다(마찰3 산출) — 여기서도 원시 dict가 보이면
# 검토가 헛돈다. 렌더 경로 4개 공통 코어스를 태운다(str/숫자 입력은 종전과 바이트 동일).
try:
    from .text_coerce import as_text as _as_text   # 패키지 컨텍스트
except ImportError:
    from text_coerce import as_text as _as_text    # top-level


def _esc(x: Any) -> str:
    return html.escape(_as_text(x))


# 템플릿마다 다른 fields 키를 사람이 읽기 좋은 한글 라벨로. 매핑 없는 키는 키 원문을 그대로 쓴다
# (라벨 사전에 없다고 내용을 숨기지 않는다 — "최대한 살리되"의 기본 원칙).
FIELD_LABELS: dict[str, str] = {
    "project_title": "프로젝트명",
    "concept_message": "컨셉 메시지",
    "items": "목록",
    "main_claim": "핵심 주장",
    "supporting_points": "근거",
    "core_question": "핵심 질문",
    "sub_questions": "세부 질문",
    "pillars": "전략 축",
    "one_line_per_pillar": "축별 한줄",
    "comparison": "비교 데이터",
    "interpretation": "해석",
    "metric": "지표",
    "x_axis": "X축",
    "y_axis": "Y축",
    "as_is": "AS-IS",
    "to_be": "TO-BE",
    "transition_message": "전환 메시지",
    "stages": "단계",
    "loop": "순환 고리",
    "roles": "역할",
    "cases": "사례",
    "metrics": "정량 지표",
    "client_safe_names": "고객명(비식별)",
    "commitments": "다짐",
    "proof_points": "근거 포인트",
}

# section(=role) 표시 라벨. adapt_storyline._role()이 표지만 "cover"로 정규화하므로 되돌린다.
_SECTION_LABELS = {"cover": "표지"}


def _render_dict(d: dict) -> str:
    """평면 dict → key: value 정의 목록(중첩 list/dict는 재귀적으로 렌더)."""
    rows = []
    for k, v in d.items():
        try:
            if isinstance(v, (list, dict)):
                inner = _render_value(k, v)
            else:
                inner = _esc(v)
        except Exception:
            continue  # 개별 값 조판 실패 — 그 값만 생략(우아한 생략)
        if inner == "":
            continue
        rows.append(f'<div class="doc-kv"><b>{_esc(k)}</b><span>{inner}</span></div>')
    return f'<div class="doc-dict">{"".join(rows)}</div>' if rows else ""


def _render_dict_list(items: list) -> str:
    """dict 리스트 → 공통 키가 적으면 표, 아니면 카드(각 dict를 key:value로) 리스트."""
    dicts = [it for it in items if isinstance(it, dict)]
    if not dicts:
        return ""
    keys: list[str] = []
    for it in dicts:
        for k in it.keys():
            if k not in keys:
                keys.append(k)
    try:
        if 1 <= len(keys) <= 6 and all(len(it) <= 6 for it in dicts):
            head = "".join(f"<th>{_esc(k)}</th>" for k in keys)
            body_rows = []
            for it in dicts:
                cells = "".join(f"<td>{_esc(it.get(k, ''))}</td>" for k in keys)
                body_rows.append(f"<tr>{cells}</tr>")
            return (f'<table class="doc-table"><thead><tr>{head}</tr></thead>'
                    f'<tbody>{"".join(body_rows)}</tbody></table>')
    except Exception:
        pass  # 표 조립 실패 — 카드 폴백으로 이어감(생략하지 않고 대체 표현 시도)
    parts = []
    for it in dicts:
        try:
            rendered = _render_dict(it)
        except Exception:
            continue
        if rendered:
            parts.append(rendered)
    return "".join(parts)


def _render_value(key: str, value: Any) -> str:
    """제네릭 필드 값 -> HTML. 실패해도 예외를 던지지 않는다(빈 문자열 = 그 필드만 생략)."""
    try:
        if value is None or value == "":
            return ""
        if isinstance(value, bool):
            return f'<p>{"예" if value else "아니오"}</p>'
        if isinstance(value, (int, float)):
            return f'<p>{_esc(value)}</p>'
        if isinstance(value, str):
            return f'<p>{_esc(value)}</p>'
        if isinstance(value, list):
            if not value:
                return ""
            if all(isinstance(v, str) for v in value):
                items = "".join(f"<li>{_esc(v)}</li>" for v in value)
                return f'<ul class="doc-list">{items}</ul>'
            if all(isinstance(v, dict) for v in value):
                return _render_dict_list(value)
            # 혼합 리스트(문자열+dict 등) — 원소별로 최선을 다해 렌더, 실패 원소만 생략.
            parts = []
            for v in value:
                try:
                    rendered = _render_value(key, v)
                except Exception:
                    continue
                if rendered:
                    parts.append(rendered)
                elif v is not None and v != "":
                    parts.append(f"<p>{_esc(v)}</p>")
            return "".join(parts)
        if isinstance(value, dict):
            return _render_dict(value)
        return f"<p>{_esc(value)}</p>"
    except Exception:
        return ""  # 조판 실패 필드 우아 생략 — 크래시 금지


def _slide_html(slide: dict, n: int, total: int) -> str:
    try:
        return _slide_html_inner(slide, n, total)
    except Exception as exc:
        # 슬라이드 전체가 실패해도 문서 전체는 죽지 않는다 — 최소 정보(제목)만 남긴다.
        sid = slide.get("slide_id", n) if isinstance(slide, dict) else n
        title = _esc((slide or {}).get("title", "")) if isinstance(slide, dict) else ""
        return (f'<section class="doc-slide" id="doc-slide-{_esc(sid)}">'
                f'<h2 class="doc-slide__title">{n}. {title}</h2>'
                f'<p class="doc-warn">⚠ 이 장은 문서 뷰 조판에 실패해 본문이 생략됐습니다 '
                f'({_esc(type(exc).__name__)}). 정본 deck.html·deck.json을 참조하세요.</p></section>')


def _slide_html_inner(slide: dict, n: int, total: int) -> str:
    sid = slide.get("slide_id", n)
    title = _esc(slide.get("title") or f"(제목 없음 {n})")
    role = _esc(slide.get("role") or "")

    badges = []
    if slide.get("example"):
        badges.append('<span class="doc-badge doc-badge--example">⚠ 예시 데이터</span>')
    rn = slide.get("review_needed") or []
    oq = slide.get("open_questions") or []
    if rn or oq:
        badges.append(f'<span class="doc-badge doc-badge--review">🔴 검토요망 {len(rn) + len(oq)}건</span>')
    badge_html = ("" if not badges else f' <span class="doc-badges">{"".join(badges)}</span>')

    eyebrow_html = f'<div class="doc-slide__eyebrow">{role} · {n:02d}/{total:02d}</div>' if role else ""
    header_html = f'<h2 class="doc-slide__title">{title}{badge_html}</h2>'

    msg = slide.get("key_message") or ""
    msg_html = f'<p class="doc-slide__lead">{_esc(msg)}</p>' if msg else ""

    body_html = ""
    body = slide.get("body") or []
    if body:
        items = "".join(f"<li>{_esc(b)}</li>" for b in body)
        body_html = f'<ul class="doc-list">{items}</ul>'

    field_parts = []
    fields = slide.get("fields") or {}
    if isinstance(fields, dict):
        for k, v in fields.items():
            try:
                rendered = _render_value(k, v)
            except Exception:
                rendered = ""
            if not rendered:
                continue  # 조판 실패/빈 값 필드 — 우아하게 생략
            label = FIELD_LABELS.get(k, k)
            field_parts.append(f'<div class="doc-field"><h4>{_esc(label)}</h4>{rendered}</div>')
    fields_html = "".join(field_parts)

    review_html = ""
    if rn or oq:
        items = "".join(f'<li>🔴 <b>검토요망:</b> {_esc(x)}</li>' for x in rn)
        items += "".join(f'<li>🔴 <b>미결:</b> {_esc(x)}</li>' for x in oq)
        review_html = f'<ul class="doc-review">{items}</ul>'

    return (f'<section class="doc-slide" id="doc-slide-{_esc(sid)}">'
            f'{eyebrow_html}{header_html}{msg_html}{body_html}{fields_html}{review_html}'
            f'</section>')


_HEAD_BADGE = (
    '<div class="doc-notice">📖 검토·회의용 문서 뷰 — 제출물 아님(정본 덱은 '
    '<code>deck.html</code>)</div>'
)

_CSS = """
    :root { color-scheme: light dark; }
    * { box-sizing: border-box; }
    body {
      margin: 0; padding: 0 1.2rem 6rem;
      font-family: "Pretendard", "Noto Sans KR", "Apple SD Gothic Neo", "Malgun Gothic", system-ui, sans-serif;
      line-height: 1.7; color: #1a1a1a; background: #fff;
    }
    @media (prefers-color-scheme: dark) {
      body { color: #e6e6e6; background: #16181c; }
    }
    .doc-wrap { max-width: 46rem; margin: 0 auto; }
    .doc-notice {
      position: sticky; top: 0; z-index: 10; margin: 0 -1.2rem 2rem; padding: .7em 1.2rem;
      background: #fff3cd; color: #7a5b00; border-bottom: 1px solid #e0b400;
      font-weight: 700; font-size: .95rem;
    }
    @media (prefers-color-scheme: dark) {
      .doc-notice { background: #4a3b00; color: #ffe08a; border-bottom-color: #7a5b00; }
    }
    .doc-notice code { background: rgba(0,0,0,.08); padding: .1em .35em; border-radius: 3px; }
    .doc-title { font-size: 1.5rem; font-weight: 800; margin: .2em 0 1.2em; }
    .doc-section {
      margin: 2.6em 0 1em; padding-top: .3em; border-top: 3px solid #1f3864;
      font-size: 1.3rem; font-weight: 800; color: #1f3864;
    }
    @media (prefers-color-scheme: dark) { .doc-section { color: #8fb4ff; border-top-color: #8fb4ff; } }
    .doc-section:first-of-type { margin-top: 0; }
    .doc-slide { margin: 1.6em 0 2.2em; padding-bottom: 1.6em; border-bottom: 1px solid #e2e2e2; }
    @media (prefers-color-scheme: dark) { .doc-slide { border-bottom-color: #333; } }
    .doc-slide:last-child { border-bottom: none; }
    .doc-slide__eyebrow { font-size: .82rem; letter-spacing: .04em; color: #888; margin-bottom: .2em; }
    .doc-slide__title { font-size: 1.15rem; font-weight: 700; margin: .1em 0 .3em; }
    .doc-slide__lead { font-size: 1.02rem; color: #444; font-style: italic; margin: 0 0 .8em; }
    @media (prefers-color-scheme: dark) { .doc-slide__lead { color: #bbb; } }
    .doc-badges { margin-left: .4em; }
    .doc-badge {
      display: inline-block; font-size: .72rem; font-weight: 700; border-radius: 4px;
      padding: .15em .5em; margin-left: .3em; vertical-align: middle;
    }
    .doc-badge--example { background: #fff3cd; color: #7a5b00; border: 1px solid #e0b400; }
    .doc-badge--review { background: #fde8e8; color: #a00; border: 1px solid #e0a0a0; }
    .doc-field { margin: .8em 0; }
    .doc-field h4 { margin: 0 0 .3em; font-size: .85rem; color: #1f3864; letter-spacing: .02em; }
    @media (prefers-color-scheme: dark) { .doc-field h4 { color: #8fb4ff; } }
    .doc-list { margin: .2em 0; padding-left: 1.3em; }
    .doc-list li { margin: .25em 0; }
    .doc-table { border-collapse: collapse; width: 100%; margin: .3em 0; font-size: .92rem; }
    .doc-table th, .doc-table td { border: 1px solid #ddd; padding: .4em .6em; text-align: left; }
    @media (prefers-color-scheme: dark) { .doc-table th, .doc-table td { border-color: #444; } }
    .doc-table th { background: #f4f6f9; }
    @media (prefers-color-scheme: dark) { .doc-table th { background: #22262e; } }
    .doc-dict { display: grid; gap: .2em; margin: .2em 0; }
    .doc-kv { display: flex; gap: .5em; }
    .doc-kv b { flex: 0 0 auto; color: #555; }
    @media (prefers-color-scheme: dark) { .doc-kv b { color: #aaa; } }
    .doc-review { margin: .6em 0 0; padding: .6em .9em; background: #fff4f4; border-left: 4px solid #c00;
                  border-radius: 4px; list-style: none; font-size: .92rem; color: #a00; }
    @media (prefers-color-scheme: dark) { .doc-review { background: #3a1f1f; color: #ff9a9a; } }
    .doc-warn { color: #a00; font-size: .9rem; }
    """


def render_doc(deck: dict, out_path: "str | Path") -> dict:
    """SlideModel(deck) -> 문서형 파생 뷰(deck.doc.html). render_html()과 독립적으로 호출한다.

    반환: {"out", "slides", "warnings", "bytes"} — render_html()과 유사한 리포트 모양(호출부
    로깅 재사용 용이).
    """
    slides = deck.get("slides", []) if isinstance(deck, dict) else []
    total = len(slides)
    meta = deck.get("meta") or {} if isinstance(deck, dict) else {}
    project = _esc(meta.get("project") or "제안 문서")

    warnings: list[str] = []
    parts: list[str] = []
    current_role: "str | None" = None
    for n, s in enumerate(slides, 1):
        if not isinstance(s, dict):
            warnings.append(f"slide index {n}: dict 아님 — 생략")
            continue
        try:
            role = s.get("role") or ""
        except Exception:
            role = ""
        if role != current_role:
            label = _SECTION_LABELS.get(role, role) or "(섹션 없음)"
            parts.append(f'<h1 class="doc-section">{_esc(label)}</h1>')
            current_role = role
        try:
            parts.append(_slide_html(s, n, total))
        except Exception as exc:  # 이중 방어 — _slide_html 내부가 이미 감싸지만 만일을 위해.
            sid = s.get("slide_id", n)
            warnings.append(f"slide {sid}: 문서 뷰 조판 실패({type(exc).__name__}) — 생략")

    body_html = "".join(parts)
    doc = (
        f'<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{project} — 문서 뷰</title><style>{_CSS}</style></head>'
        f'<body>{_HEAD_BADGE}<div class="doc-wrap">'
        f'<div class="doc-title">{project}</div>{body_html}</div></body></html>'
    )
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    return {"out": str(out), "slides": total, "warnings": warnings, "bytes": len(doc.encode("utf-8"))}


def _load(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("사용: python app/render/docgen.py <deck.json> <out.doc.html>")
        raise SystemExit(1)
    rep = render_doc(_load(Path(sys.argv[1])), sys.argv[2])
    print(json.dumps(rep, ensure_ascii=False, indent=2))
