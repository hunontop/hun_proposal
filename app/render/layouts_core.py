# -*- coding: utf-8 -*-
"""중립 코어 레이아웃 — core 카탈로그가 요구하는 렌더러 3종의 엔진 소유 구현.

이식 절차(W21-0 §7 공급 매핑): 원출처 = layouts_house_a.py의 렌더러 함수
(하우스 무관 구현력 — 결정 11③·12). 마크업 클래스·CSS를 중립화(core-*)해
하우스 스코프(body.pack-house_a) 의존을 제거했다. 수요 근거:
  - process_steps → 표현원칙 3-3(수집·묶기·이름)·2-2 흐름
  - table_block   → 표현원칙 2-3(상대의 축 비교표)
  - timeline_matrix → RFP 작성요령 서식(추진일정 의무)
2b 조각화(flow_seq·compare_table·timeline_gantt) 완료 시 이 모듈은 조각 구현으로 흡수된다.
"""
from __future__ import annotations

import html
from typing import Any


def _present(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {} and value != ()


# W32 마찰28: 이 모듈이 agenda·process_steps·table_block·timeline_matrix·endcard를 렌더한다
# (htmlgen REGISTRY에 없는 이름 = 마찰28⒞가 지목한 shape 미문서 template들). 문자열 기대 자리에
# 객체가 들어오면 원시 dict가 장표에 노출되므로 htmlgen·compose와 같은 관용 코어스를 태운다.
try:
    from .text_coerce import as_text as _as_text   # 패키지 컨텍스트
except ImportError:
    from text_coerce import as_text as _as_text    # top-level(sys.path에 app/render)


def _esc(value: Any) -> str:
    return html.escape(_as_text(value), quote=True)


def _sequence(value: Any) -> list:
    return list(value) if isinstance(value, (list, tuple)) else []


def _pick(mapping: Any, *keys: str) -> Any:
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        value = mapping.get(key)
        if _present(value):
            return value
    return None


def _display(value: Any) -> str:
    if isinstance(value, dict):
        preferred = _pick(value, "label", "name", "title", "text", "value", "description")
        if _present(preferred):
            return _display(preferred)
        return "<br>".join(f"{_esc(k)}: {_display(v)}" for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return "<br>".join(_display(item) for item in value)
    return _esc(value)


def _body_items(slide: dict) -> list:
    body = slide.get("body")
    if isinstance(body, (list, tuple)):
        return list(body)
    return [body] if _present(body) else []


def _head(slide: dict) -> str:
    role = _esc(slide.get("role", ""))
    title = _esc(slide.get("title", ""))
    message = _esc(slide.get("key_message", ""))
    return (
        f'<div class="slide__eyebrow">{role}</div>'
        f'<h2 class="slide__title">{title}</h2>'
        + (f'<div class="slide__msg">{message}</div>' if message else "")
    )


def _fallback(slide: dict) -> str:
    items = "".join(f"<li>{_display(item)}</li>" for item in _body_items(slide))
    body = f'<div class="slide__body"><ul>{items}</ul></div>' if items else ""
    return _head(slide) + body


def _aligned(source: Any, index: int, key: Any, count: int) -> Any:
    if isinstance(source, dict):
        candidates = (key, str(key), index, str(index), index + 1, str(index + 1))
        for candidate in candidates:
            if candidate in source and _present(source[candidate]):
                return source[candidate]
        return None
    values = _sequence(source)
    if index < len(values) and _present(values[index]):
        return values[index]
    if count == 1 and _present(source) and not values:
        return source
    return None


# --- timeline_matrix (RFP 일정 의무) ---------------------------------------

def _timeline_streams(source: Any, units: list) -> list[tuple[Any, list]]:
    if isinstance(source, dict):
        streams = [{"label": label, "cells": cells} for label, cells in source.items()]
    else:
        streams = _sequence(source)
    rows: list[tuple[Any, list]] = []
    for stream in streams:
        if not isinstance(stream, dict):
            continue
        label = _pick(stream, "label", "name", "title", "workstream")
        raw_cells = _pick(stream, "cells", "schedule", "periods", "time_units")
        if isinstance(raw_cells, dict):
            cells = [_aligned(raw_cells, i, unit, len(units)) for i, unit in enumerate(units)]
        else:
            values = _sequence(raw_cells)
            cells = [values[i] if i < len(values) else None for i in range(len(units))]
        if _present(label) and any(_present(cell) for cell in cells):
            rows.append((label, cells))
    return rows


def _timeline_milestones(source: Any, units: list) -> tuple[list[list[str]], bool]:
    cells: list[list[str]] = [[] for _ in units]
    if isinstance(source, dict):
        for i, unit in enumerate(units):
            value = _aligned(source, i, unit, len(units))
            if _present(value):
                cells[i].append(_display(value))
    else:
        for milestone in _sequence(source):
            if not isinstance(milestone, dict):
                continue
            period = _pick(milestone, "time_unit", "period", "unit", "phase")
            label = _pick(milestone, "label", "name", "title", "milestone")
            if not (_present(period) and _present(label)):
                continue
            for i, unit in enumerate(units):
                if str(period) == str(unit):
                    cells[i].append(_display(label))
                    break
    return cells, any(cells)


def _timeline_cell(value: Any) -> str:
    if value is True:
        return "●"
    if value is False or value is None:
        return ""
    return _display(value)


def timeline_matrix(slide: dict, f: dict) -> str:
    units = _sequence(f.get("time_units"))
    rows = _timeline_streams(f.get("workstreams"), units) if units else []
    milestones, has_milestones = _timeline_milestones(f.get("milestones"), units) if units else ([], False)
    if not units or not rows or not has_milestones:
        return _fallback(slide)
    headers = "".join(f'<th scope="col">{_display(unit)}</th>' for unit in units)
    body_rows = ""
    for label, cells in rows:
        rendered = "".join(f"<td>{_timeline_cell(cell)}</td>" for cell in cells)
        body_rows += f'<tr><th scope="row">{_display(label)}</th>{rendered}</tr>'
    milestone_cells = "".join(f'<td class="is-strong">{"<br>".join(cell)}</td>' for cell in milestones)
    table = (
        '<div class="slide__body core-timeline">'
        '<table class="core-table">'
        f'<thead><tr><th scope="col">업무</th>{headers}</tr></thead>'
        f'<tbody>{body_rows}<tr class="core-timeline__milestones">'
        f'<th scope="row">마일스톤</th>{milestone_cells}</tr></tbody>'
        "</table></div>"
    )
    return _head(slide) + table


# --- process_steps (3-3 수집·묶기·이름 / 2-2 흐름) ---------------------------

def process_steps(slide: dict, f: dict) -> str:
    raw_steps = f.get("steps")
    outputs = f.get("outputs")
    if isinstance(raw_steps, dict):
        steps = [{"label": label, "description": description} for label, description in raw_steps.items()]
    else:
        steps = _sequence(raw_steps)
    if not steps or not _present(outputs):
        return _fallback(slide)
    cards = []
    for i, step in enumerate(steps):
        if isinstance(step, dict):
            label = _pick(step, "label", "name", "title", "step")
            detail = _pick(step, "description", "body", "detail")
            embedded_output = _pick(step, "output", "deliverable")
        else:
            label, detail, embedded_output = step, None, None
        output = _aligned(outputs, i, label, len(steps))
        if not _present(output):
            output = embedded_output
        if not _present(label):
            continue
        detail_html = f'<div class="core-step__detail">{_display(detail)}</div>' if _present(detail) else ""
        output_html = f'<div class="core-step__output"><b>산출물</b><br>{_display(output)}</div>' if _present(output) else ""
        cards.append(
            '<div class="card core-step">'
            f'<div class="core-step__number">STEP {i + 1}</div>'
            f"<h4>{_display(label)}</h4>{detail_html}{output_html}</div>"
        )
    if not cards:
        return _fallback(slide)
    return _head(slide) + f'<div class="cards core-process">{"".join(cards)}</div>'


# --- table_block (2-3 비교표 / 리스크 표) ------------------------------------

def _normalise_options(source: Any) -> list:
    if isinstance(source, dict):
        return [{"name": name, "values": values} for name, values in source.items()]
    return _sequence(source)


def _normalise_criteria(source: Any) -> list:
    if isinstance(source, dict):
        return [{"label": label, "values": values} for label, values in source.items()]
    return _sequence(source)


def _option_label(option: Any) -> Any:
    return _pick(option, "name", "label", "title", "option") if isinstance(option, dict) else option


def _criterion_label(criterion: Any) -> Any:
    return _pick(criterion, "name", "label", "title", "criterion") if isinstance(criterion, dict) else criterion


def _comparison_value(option, option_index, option_label, criterion, criterion_index,
                      criterion_label, option_count, criterion_count) -> Any:
    if isinstance(criterion, dict):
        criterion_values = _pick(criterion, "values", "options", "scores")
        value = _aligned(criterion_values, option_index, option_label, option_count)
        if _present(value):
            return value
    if isinstance(option, dict):
        option_values = _pick(option, "criteria", "values", "scores", "details")
        value = _aligned(option_values, criterion_index, criterion_label, criterion_count)
        if _present(value):
            return value
        if criterion_label in option and _present(option[criterion_label]):
            return option[criterion_label]
    return None


def _comparison_table(slide: dict, f: dict) -> str:
    options = _normalise_options(f.get("options"))
    criteria = _normalise_criteria(f.get("criteria"))
    recommendation = f.get("recommendation")
    if not options or not criteria or not _present(recommendation):
        return _fallback(slide)
    option_labels = [_option_label(option) for option in options]
    if not all(_present(label) for label in option_labels):
        return _fallback(slide)
    headers = "".join(f'<th scope="col">{_display(label)}</th>' for label in option_labels)
    rows = []
    has_values = False
    for ci, criterion in enumerate(criteria):
        criterion_label = _criterion_label(criterion)
        if not _present(criterion_label):
            continue
        cells = []
        for oi, option in enumerate(options):
            value = _comparison_value(option, oi, option_labels[oi], criterion, ci,
                                      criterion_label, len(options), len(criteria))
            has_values = has_values or _present(value)
            cells.append(f"<td>{_display(value)}</td>")
        rows.append(f'<tr><th scope="row">{_display(criterion_label)}</th>{"".join(cells)}</tr>')
    if not rows or not has_values:
        return _fallback(slide)
    return _head(slide) + (
        '<div class="slide__body core-table-wrap"><table class="core-table">'
        f'<thead><tr><th scope="col">기준</th>{headers}</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
        f'<div class="core-recommendation"><b>추천</b><br>{_display(recommendation)}</div></div>'
    )


def _risk_table(slide: dict, f: dict) -> str:
    raw_risks = f.get("risks")
    severities = f.get("severity")
    mitigations = f.get("mitigations")
    if isinstance(raw_risks, dict):
        risks = [{"name": name, "detail": detail} for name, detail in raw_risks.items()]
    else:
        risks = _sequence(raw_risks)
    if not risks or not _present(severities) or not _present(mitigations):
        return _fallback(slide)
    rows = []
    has_details = False
    for i, risk in enumerate(risks):
        if isinstance(risk, dict):
            label = _pick(risk, "name", "label", "title", "risk")
            detail = _pick(risk, "description", "detail", "body")
            embedded_severity = _pick(risk, "severity")
            embedded_mitigation = _pick(risk, "mitigation", "response")
        else:
            label, detail, embedded_severity, embedded_mitigation = risk, None, None, None
        if not _present(label):
            continue
        severity = _aligned(severities, i, label, len(risks))
        mitigation = _aligned(mitigations, i, label, len(risks))
        if not _present(severity):
            severity = embedded_severity
        if not _present(mitigation):
            mitigation = embedded_mitigation
        has_details = has_details or (_present(severity) and _present(mitigation))
        risk_text = _display(label)
        if _present(detail):
            risk_text += f"<br>{_display(detail)}"
        rows.append(
            f'<tr><th scope="row">{risk_text}</th>'
            f'<td class="is-strong">{_display(severity)}</td><td>{_display(mitigation)}</td></tr>'
        )
    if not rows or not has_details:
        return _fallback(slide)
    return _head(slide) + (
        '<div class="slide__body core-table-wrap"><table class="core-table">'
        '<thead><tr><th scope="col">리스크</th><th scope="col">심각도</th><th scope="col">대응</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>'
    )


def table_block(slide: dict, f: dict) -> str:
    role = slide.get("role")
    if role == "risk" or all(_present(f.get(key)) for key in ("risks", "severity", "mitigations")):
        return _risk_table(slide, f)
    if all(_present(f.get(key)) for key in ("options", "criteria", "recommendation")):
        return _comparison_table(slide, f)
    return _fallback(slide)


# --- agenda (문서 프레임 목차, D23) -----------------------------------------

def agenda(slide: dict, f: dict) -> str:
    """대목차 목차 — items(섹션 제목 리스트)를 번호 매긴 행으로. 지어내기 0(골격 조립)."""
    items = f.get("items") or _body_items(slide)
    rows = []
    for item in _sequence(items):
        if isinstance(item, dict):
            label = _pick(item, "title", "label", "name", "text", "section")
        else:
            label = item
        if not _present(label):
            continue
        num = len(rows) + 1
        rows.append(
            f'<li class="core-agenda__row"><span class="core-agenda__num">{num:02d}</span>'
            f'<span class="core-agenda__text">{_display(label)}</span></li>'
        )
    if not rows:
        return _fallback(slide)
    return _head(slide) + f'<ol class="slide__body core-agenda">{"".join(rows)}</ol>'


# --- endcard (문서 프레임 끝인사, D23) --------------------------------------

def endcard(slide: dict, f: dict) -> str:
    """명시 끝인사 — 정적 문구(감사합니다 / End of document). 마무리(closing)와 다른 경로."""
    thanks = _esc(slide.get("title") or "감사합니다")
    return (
        '<div class="slide__body core-endcard">'
        f'<div class="core-endcard__thanks">{thanks}</div>'
        '<div class="core-endcard__end">End of document</div>'
        "</div>"
    )


LAYOUTS = {
    "timeline_matrix": timeline_matrix,
    "process_steps": process_steps,
    "table_block": table_block,
    "agenda": agenda,
    "endcard": endcard,
}


# 중립 CSS — 무채, 팩 스코프 없음(core-* 클래스 네임스페이스). 대비는 명도로.
CSS = """
.core-table-wrap, .core-timeline { display: flex; flex: 1; flex-direction: column; margin-top: .4em; min-height: 0; }
.core-table { background: var(--paper, #fff); border-collapse: collapse; font-size: var(--type-body, 16px); table-layout: fixed; width: 100%; }
.core-table th, .core-table td { border: 1px solid var(--line, #cfcfcf); padding: .35em .6em; text-align: left; vertical-align: middle; }
.core-table thead th { background: var(--c-section-default, #404040); color: #fff; font-size: var(--type-small, 12px); font-weight: 700; }
.core-table tbody th { background: var(--c-gray-bg, #f2f2f2); font-weight: 700; }
.core-table .is-strong { font-weight: 700; }
.core-timeline .core-table th:not(:first-child), .core-timeline .core-table td { text-align: center; }
.core-timeline .core-table th:first-child { width: 22%; }
.core-timeline__milestones th, .core-timeline__milestones td { border-top: 3px solid var(--ink, #1a1a1a); }
.core-process { align-items: stretch; flex: 1; margin-top: .5em; }
.core-step { border-top: 3px solid var(--ink, #1a1a1a); display: flex; flex-direction: column; }
.core-step__number { color: var(--muted, #595959); font-size: var(--type-small, 12px); font-weight: 700; letter-spacing: .04em; }
.core-step__detail { color: var(--muted, #595959); margin-top: .35em; }
.core-step__output { border-top: 1px solid var(--line, #cfcfcf); color: var(--muted, #595959); font-size: var(--type-small, 12px); margin-top: auto; padding-top: .5em; }
.core-recommendation { border-left: 3px solid var(--ink, #1a1a1a); margin-top: .5em; padding: .35em .6em; }
.core-agenda { display: flex; flex: 1; flex-direction: column; gap: .5em; justify-content: center; list-style: none; margin-top: .4em; }
.core-agenda__row { align-items: baseline; border-bottom: 1px solid var(--line, #cfcfcf); display: flex; gap: 1em; padding-bottom: .45em; }
.core-agenda__num { color: var(--muted, #595959); font-size: var(--type-small, 12px); font-weight: 700; letter-spacing: .04em; min-width: 2.2em; }
.core-agenda__text { color: var(--ink, #1a1a1a); font-size: var(--type-body, 16px); font-weight: 700; }
.core-endcard { align-items: center; display: flex; flex: 1; flex-direction: column; gap: .4em; justify-content: center; text-align: center; }
.core-endcard__thanks { color: var(--ink, #1a1a1a); font-size: var(--type-title, 40px); font-weight: 700; }
.core-endcard__end { color: var(--muted, #595959); font-size: var(--type-small, 12px); letter-spacing: .08em; text-transform: uppercase; }
"""
