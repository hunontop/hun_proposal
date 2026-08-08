# -*- coding: utf-8 -*-
"""골격(frame) × 조각(piece) 조합 렌더러 — W21-0 2단계 (결정 12, 설계 CONTEXT/W21_CATALOG_REBUILD.md).

슬라이드에 `frame`이 선언되면 htmlgen이 template_id 대신 이 모듈로 디스패치한다.

슬라이드 스키마(v2):
    {"frame": "row_n", "layout_group": "axis1-evidence", "variation_reason": null,
     "slots": [{"piece": "stat_card", "size": "third", "data": {...}},
               {"piece": "big_number", "binds": "hero"}]}          # binds = fields[key]

계약:
- frame/piece 어휘 정본 = packs/core/frames.json·pieces.json (원전 출처 앵커).
- R2: 데이터 없는 슬롯은 배치하지 않는다(억지 채움 금지) — 유효 슬롯 수로 그리드 축소.
- R4: 출처 없는 수치는 감추거나 강등하지 않고 '출처요망' 딱지를 붙인다(표면화).
- R6: 동류 슬롯 공통 베이스라인 — 그리드 stretch + 조각 내부 footer(margin-top:auto)로 구조 강제.
- 미지원 frame/piece = 조용한 폴백 금지, 경고 표면화(catalog_gap의 런타임 짝).
"""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
_CONTRACT_DIR = ROOT / "packs" / "core"
_contracts_cache: "dict | None" = None


# W32 마찰28: 조각(piece)도 문자열 기대 자리에 객체가 들어올 수 있다(htmlgen과 동일 원인).
# 관용 코어스 + 기록 → render_slide가 warnings로 수거한다. 규약은 htmlgen._as_text와 동일.
try:
    from .text_coerce import as_text as _as_text, records as _coerced   # 패키지 컨텍스트
except ImportError:
    from text_coerce import as_text as _as_text, records as _coerced    # top-level

_notes: list[str] = []   # 검수 채널(청중 장표에 그리지 않고 warnings로만 보내는 신호 · 마찰31)


def _esc(x: Any) -> str:
    return html.escape(_as_text(x))


def _contracts() -> dict:
    global _contracts_cache
    if _contracts_cache is None:
        frames = json.loads((_CONTRACT_DIR / "frames.json").read_text(encoding="utf-8"))
        pieces = json.loads((_CONTRACT_DIR / "pieces.json").read_text(encoding="utf-8"))
        presets = json.loads((_CONTRACT_DIR / "presets.json").read_text(encoding="utf-8"))
        _contracts_cache = {
            "frames": {f["id"]: f for f in frames.get("frames", [])},
            "pieces": {p["id"]: p for p in pieces.get("pieces", [])},
            "presets": {p["id"]: p for p in presets.get("presets", [])},
        }
    return _contracts_cache


def _head(slide: dict) -> str:
    role = _esc(slide.get("role", ""))
    title = _esc(slide.get("title", ""))
    message = _esc(slide.get("key_message", ""))
    return (
        f'<div class="slide__eyebrow">{role}</div>'
        f'<h2 class="slide__title">{title}</h2>'
        + (f'<div class="slide__msg">{message}</div>' if message else "")
    )


def _review(msg: str) -> str:
    return f'<div class="review">🔴 <b>검토요망:</b> {_esc(msg)}</div>'


def _source_tag(data: dict) -> str:
    """R4: 출처 병기 또는 '출처요망' 딱지(강등 아님 — 정직성 표면화)."""
    note = data.get("source_note")
    if note:
        return f'<div class="cp-source">{_esc(note)}</div>'
    return '<div class="cp-source cp-source--missing">출처요망</div>'


def _items(value: Any) -> list:
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value] if value not in (None, "", {}, []) else []


# --- 조각 렌더러 (2a 최소 세트 10종) -----------------------------------------

def p_text_block(d: dict) -> str:
    body = _items(d.get("body"))
    if len(body) == 1 and not isinstance(body[0], (list, dict)):
        return f'<p class="cp-text">{_esc(body[0])}</p>'
    return '<ul class="cp-text">' + "".join(f"<li>{_esc(b)}</li>" for b in body) + "</ul>"


def p_big_number(d: dict) -> str:
    return (
        '<div class="cp-bignum">'
        f'<div class="cp-bignum__value">{_esc(d.get("value"))}<span class="cp-bignum__unit">{_esc(d.get("unit", ""))}</span></div>'
        f'<div class="cp-bignum__label">{_esc(d.get("label", ""))}</div>'
        + _source_tag(d) + "</div>"
    )


def p_stat_card(d: dict) -> str:
    icon = f'<div class="cp-stat__icon">{_esc(d["icon"])}</div>' if d.get("icon") else ""
    note = f'<div class="cp-stat__note">{_esc(d["note"])}</div>' if d.get("note") else ""
    return (
        '<div class="cp-stat">'
        + icon
        + f'<div class="cp-stat__label">{_esc(d.get("label"))}</div>'
        + f'<div class="cp-stat__value">{_esc(d.get("value"))}</div>'
        + note + _source_tag(d) + "</div>"
    )


def p_calc_arrow(d: dict) -> str:
    foot = f'<div class="cp-calc__formula">{_esc(d["formula_footnote"])}</div>' if d.get("formula_footnote") else ""
    return (
        '<div class="cp-calcwrap"><div class="cp-calc">'
        f'<div class="cp-calc__narrative">{_esc(d.get("narrative"))}</div>'
        '<div class="cp-calc__arrow" aria-hidden="true">→</div>'
        f'<div class="cp-calc__result">{_esc(d.get("result_value"))}</div>'
        "</div>" + foot + "</div>"
    )


def p_contrast_pair(d: dict) -> str:
    return (
        '<div class="cp-contrast">'
        f'<div class="cp-contrast__reject">{_esc(d.get("reject"))}</div>'
        f'<div class="cp-contrast__adopt">{_esc(d.get("adopt"))}</div>'
        "</div>"
    )


def p_compare_table(d: dict) -> str:
    axes = _items(d.get("axes"))[:3]  # 축 최대 3행(2-3)
    columns = _items(d.get("columns"))
    cells = d.get("cells") or []
    crits = _items(d.get("selection_criteria"))
    heads = ""
    for i, col in enumerate(columns):
        crit = f'<sup class="cp-cmp__crit">*{_esc(crits[i])}</sup>' if i < len(crits) and crits[i] else ""
        heads += f'<th scope="col">{_esc(col)}{crit}</th>'
    rows = ""
    for ri, ax in enumerate(axes):
        label = ax.get("label") if isinstance(ax, dict) else ax
        voice = ax.get("voice") if isinstance(ax, dict) else None
        voice_html = f'<div class="cp-cmp__voice">{_esc(voice)}</div>' if voice else ""
        row_cells = cells[ri] if ri < len(cells) else []
        tds = "".join(f"<td>{_esc(c)}</td>" for c in row_cells)
        rows += f'<tr><th scope="row">{_esc(label)}{voice_html}</th>{tds}</tr>'
    return (
        '<div class="cp-cmp"><table class="core-table">'
        f'<thead><tr><th scope="col"></th>{heads}</tr></thead><tbody>{rows}</tbody></table>'
        + _source_tag(d) + "</div>"
    )


def p_before_after(d: dict) -> str:
    metrics = _items(d.get("metrics"))
    before = _items(d.get("before"))
    after = _items(d.get("after"))
    rows = ""
    for i, m in enumerate(metrics):
        b = before[i] if i < len(before) else ""
        a = after[i] if i < len(after) else ""
        rows += (f'<tr><th scope="row">{_esc(m)}</th>'
                 f'<td class="cp-ba__before">{_esc(b)}</td><td class="cp-ba__after">{_esc(a)}</td></tr>')
    return (
        '<div class="cp-ba"><table class="core-table">'
        '<thead><tr><th scope="col">지표</th><th scope="col">전</th><th scope="col">후</th></tr></thead>'
        f"<tbody>{rows}</tbody></table></div>"
    )


def p_flow_arrow(d: dict) -> str:
    stages = _items(d.get("stages"))
    parts = []
    for s in stages:
        label = s.get("label") if isinstance(s, dict) else s
        desc = s.get("description") if isinstance(s, dict) else None
        desc_html = f'<div class="cp-flow__desc">{_esc(desc)}</div>' if desc else ""
        parts.append(f'<div class="cp-flow__stage"><div class="cp-flow__label">{_esc(label)}</div>{desc_html}</div>')
    return '<div class="cp-flow">' + '<div class="cp-flow__arrow" aria-hidden="true">→</div>'.join(parts) + "</div>"


def p_group_naming(d: dict) -> str:
    collected = _items(d.get("collected"))
    groups = _items(d.get("groups"))
    col_html = "".join(f'<div class="cp-grp__item">{_esc(c)}</div>' for c in collected)
    grp_html = ""
    for g in groups:
        name = g.get("name") if isinstance(g, dict) else g
        items = _items(g.get("items")) if isinstance(g, dict) else []
        inner = "".join(f'<div class="cp-grp__item">{_esc(i)}</div>' for i in items)
        grp_html += f'<div class="cp-grp__group"><div class="cp-grp__name">{_esc(name)}</div>{inner}</div>'
    return (
        '<div class="cp-grp">'
        f'<div class="cp-grp__stage">{col_html}</div>'
        '<div class="cp-flow__arrow" aria-hidden="true">→</div>'
        f'<div class="cp-grp__stage cp-grp__stage--named">{grp_html}</div>'
        "</div>"
    )


def p_match_pairs(d: dict) -> str:
    pairs = _items(d.get("pairs"))
    rows = ""
    for p in pairs:
        if not isinstance(p, dict):
            continue
        rows += (
            '<div class="cp-match__row">'
            f'<div class="cp-match__complaint">"{_esc(p.get("complaint"))}"</div>'
            '<div class="cp-match__link" aria-hidden="true">—</div>'
            f'<div class="cp-match__proposal">{_esc(p.get("proposal"))}</div>'
            "</div>"
        )
    return f'<div class="cp-match">{rows}</div>'


def p_matrix_2x2(d: dict) -> str:
    quads = (_items(d.get("quadrants")) + ["", "", "", ""])[:4]
    current = d.get("current")
    target = d.get("target")
    cells = ""
    for i, q in enumerate(quads, 1):
        marker = '<span class="cp-mx__marker" title="현위치">●</span>' if current == i else ""
        goal = '<span class="cp-mx__goal" title="목표">★</span>' if target == i else ""
        cells += f'<div class="cp-mx__q">{marker}{goal}<div>{_esc(q)}</div></div>'
    move = ""
    if current and target and current != target:
        move = f'<div class="cp-mx__move">현위치 → 목표: {_esc(quads[current - 1])} → {_esc(quads[target - 1])}</div>'
    return (
        '<div class="cp-mx">'
        f'<div class="cp-mx__ylab">{_esc(d.get("axis_y"))}</div>'
        f'<div class="cp-mx__grid">{cells}</div>'
        f'<div class="cp-mx__xlab">{_esc(d.get("axis_x"))}</div>'
        + move + "</div>"
    )


def p_connect_diagram(d: dict) -> str:
    relation = d.get("relation")
    groups = _items(d.get("groups"))
    rel_html = f'<div class="cp-conn__rel">{_esc(relation)}</div>' if relation else ""
    if groups:
        boxes = ""
        for g in groups:
            name = g.get("name") if isinstance(g, dict) else g
            items = _items(g.get("items")) if isinstance(g, dict) else []
            inner = "".join(f'<div class="cp-grp__item">{_esc(i)}</div>' for i in items)
            boxes += f'<div class="cp-conn__box"><div class="cp-conn__name">{_esc(name)}</div>{inner}</div>'
        return f'<div class="cp-conn">{rel_html}<div class="cp-conn__boxes">{boxes}</div></div>'
    items = _items(d.get("items"))
    nodes = '<div class="cp-conn__link" aria-hidden="true">—</div>'.join(
        f'<div class="cp-conn__node">{_esc(i)}</div>' for i in items)
    return f'<div class="cp-conn">{rel_html}<div class="cp-conn__row">{nodes}</div></div>'


def _loop_html(steps: list, cls: str, label: str) -> str:
    chain = ' <span aria-hidden="true">→</span> '.join(_esc(s) for s in steps)
    return (f'<div class="cp-loop__panel {cls}"><div class="cp-loop__label">{_esc(label)} '
            f'<span class="cp-loop__cycle" aria-hidden="true">↻</span></div>'
            f'<div class="cp-loop__chain">{chain}</div></div>')


def p_loop_pair(d: dict) -> str:
    return ('<div class="cp-loop">'
            + _loop_html(_items(d.get("vicious_loop")), "cp-loop__panel--vicious", "악순환")
            + _loop_html(_items(d.get("virtuous_loop")), "cp-loop__panel--virtuous", "선순환")
            + "</div>")


def _ratio(d: dict) -> float:
    try:
        r = float(str(d.get("ratio", "")).rstrip("%"))
        return max(0.0, min(100.0, r))
    except (TypeError, ValueError):
        return 33.0


def p_part_of_whole(d: dict) -> str:
    r = _ratio(d)
    return (
        '<div class="cp-pow">'
        f'<div class="cp-pow__donut" style="background: conic-gradient(var(--ink, #1a1a1a) 0 {r}%, var(--c-gray-bg, #f2f2f2) {r}% 100%);">'
        f'<div class="cp-pow__hole">{_esc(d.get("part"))}</div></div>'
        f'<div class="cp-pow__legend"><b>{_esc(d.get("part_label"))}</b><div>{_esc(d.get("whole"))}</div></div>'
        + _source_tag(d) + "</div>"
    )


def p_analogy_hero(d: dict) -> str:
    return (
        '<div class="cp-analogy">'
        f'<div class="cp-analogy__line">{_esc(d.get("analogy"))}</div>'
        f'<div class="cp-analogy__proof">{_esc(d.get("proof"))}</div>'
        "</div>"
    )


def p_journey_flow(d: dict) -> str:
    nodes = _items(d.get("nodes"))
    parts = []
    for nd in nodes:
        label = nd.get("label") if isinstance(nd, dict) else nd
        content = nd.get("content") if isinstance(nd, dict) else None
        if content:
            body = f'<div class="cp-flow__desc">{_esc(content)}</div>'
            cls = ""
        else:
            body = '<div class="cp-jf__gap">빈틈 — 대응 콘텐츠 없음(경쟁 대비 취약)</div>'
            cls = " cp-jf__node--gap"
        parts.append(f'<div class="cp-flow__stage{cls}"><div class="cp-flow__label">{_esc(label)}</div>{body}</div>')
    return '<div class="cp-flow">' + '<div class="cp-flow__arrow" aria-hidden="true">→</div>'.join(parts) + "</div>"


def p_claim_proof_split(d: dict) -> str:
    comps = _items(d.get("components"))
    proofs = _items(d.get("proofs"))
    cols = ""
    for i, c in enumerate(comps):
        proof = proofs[i] if i < len(proofs) else None
        if proof:
            p_html = f'<div class="cp-cps__proof">{_esc(proof)}</div>'
        else:
            p_html = '<div class="cp-source cp-source--missing">출처요망</div>'
        cols += f'<div class="cp-cps__comp"><div>{_esc(c)}</div>{p_html}</div>'
    return (
        '<div class="cp-cps">'
        f'<div class="cp-cps__claim">{_esc(d.get("claim"))}</div>'
        '<div class="cp-flow__arrow" aria-hidden="true">↓</div>'
        f'<div class="cp-cps__comps">{cols}</div></div>'
    )


def _funnel_layer(d: dict, key: str, width: int) -> str:
    layer = d.get(key)
    if isinstance(layer, dict):
        value, note = layer.get("value"), layer.get("source_note")
    else:
        value, note = layer, None
    src = (f'<span class="cp-source">{_esc(note)}</span>' if note
           else '<span class="cp-source cp-source--missing">출처요망</span>')
    return (f'<div class="cp-fun__layer" style="width:{width}%">'
            f'<b>{key.upper()}</b> {_esc(value)} {src}</div>')


def p_funnel_3layer(d: dict) -> str:
    return ('<div class="cp-fun">'
            + _funnel_layer(d, "tam", 100) + _funnel_layer(d, "sam", 72) + _funnel_layer(d, "som", 44)
            + "</div>")


def p_chart(d: dict) -> str:
    ctype = d.get("chart_type") or "bar"
    series = [s for s in _items(d.get("series")) if isinstance(s, dict)]
    vals = [float(s.get("value") or 0) for s in series]
    vmax = max(vals) if vals else 1.0
    if ctype == "donut" and series:
        r = (vals[0] / (sum(vals) or 1)) * 100
        body = p_part_of_whole({"ratio": r, "part": series[0].get("label"),
                                "part_label": series[0].get("value"),
                                "whole": " / ".join(str(s.get("label")) for s in series[1:]),
                                "source_note": d.get("source_note")})
        return f'<div class="cp-chart">{body}</div>'
    if ctype == "line" and series:
        pts = []
        n = max(len(vals) - 1, 1)
        for i, v in enumerate(vals):
            pts.append(f"{(i / n) * 100:.1f},{40 - (v / (vmax or 1)) * 36:.1f}")
        labels = "".join(f'<span class="cp-chart__ll">{_esc(s.get("label"))}</span>' for s in series)
        return (
            '<div class="cp-chart">'
            f'<svg class="cp-chart__line" viewBox="0 0 100 42" preserveAspectRatio="none" aria-hidden="true">'
            f'<polyline points="{" ".join(pts)}" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>'
            f'<div class="cp-chart__labels">{labels}</div>' + _source_tag(d) + "</div>"
        )
    bars = ""
    for s in series:
        h = (float(s.get("value") or 0) / (vmax or 1)) * 100
        bars += (f'<div class="cp-chart__bar"><div class="cp-chart__val">{_esc(s.get("value"))}</div>'
                 f'<div class="cp-chart__fill" style="height:{h:.0f}%"></div>'
                 f'<div class="cp-chart__lab">{_esc(s.get("label"))}</div></div>')
    return f'<div class="cp-chart"><div class="cp-chart__bars">{bars}</div>{_source_tag(d)}</div>'


def p_quote(d: dict) -> str:
    ex = '<span class="cp-quote__example">[예시]</span> ' if d.get("is_example") else ""
    return (
        '<figure class="cp-quote">'
        f'<blockquote>{ex}{_esc(d.get("text"))}</blockquote>'
        f'<figcaption>— {_esc(d.get("attribution"))}</figcaption></figure>'
    )


def p_image_evidence(d: dict) -> str:
    return (
        '<figure class="cp-img">'
        f'<img src="{_esc(d.get("asset_path"))}" alt="{_esc(d.get("caption"))}">'
        f'<figcaption>{_esc(d.get("caption"))}</figcaption></figure>'
    )


def _gantt_cells(ws: dict) -> "list | None":
    for key in ("cells", "schedule", "periods"):
        val = ws.get(key)
        if isinstance(val, list):
            return val
    return None


def _gantt_adapt(d: dict) -> "tuple[list, list]":
    """병렬 리스트 어댑터: time_units+workstreams(단순 케이스 — cells가 리스트) → period_labels/tasks.
    workstreams 항목별로 cells에서 truthy 값의 첫/끝 1-기반 인덱스를 start/end로 잡는다.
    milestones는 이 어댑터 범위 밖(무시 — layouts_core._timeline_streams처럼 별도 마일스톤 행을 만들지 않는다)."""
    time_units = _items(d.get("time_units"))
    workstreams = [w for w in _items(d.get("workstreams")) if isinstance(w, dict)]
    if not time_units or not workstreams:
        return [], []
    tasks: list = []
    for ws in workstreams:
        cells = _gantt_cells(ws)
        label = ws.get("label")
        if cells is None or not label:
            continue
        idxs = [i + 1 for i, c in enumerate(cells) if c]
        if idxs:
            tasks.append({"label": label, "start": idxs[0], "end": idxs[-1]})
    return time_units, tasks


def p_timeline_gantt(d: dict) -> str:
    periods = _items(d.get("period_labels")) or _items(d.get("period"))
    tasks = [t for t in _items(d.get("tasks")) if isinstance(t, dict)]
    if not periods and not tasks:
        adapted_periods, adapted_tasks = _gantt_adapt(d)
        if adapted_periods and adapted_tasks:
            periods, tasks = adapted_periods, adapted_tasks
    if not periods or not tasks:
        # 입력 2형태(tasks+period_labels / time_units+workstreams) 모두 불충족 —
        # 빈 표를 조용히 그리지 않고 표면화(requires [] 이관에 따른 조각 내부 정직성 검사).
        return _review("timeline_gantt 입력 없음 — tasks/period_labels 또는 time_units/workstreams 필요")
    heads = "".join(f'<th scope="col">{_esc(p)}</th>' for p in periods)
    rows = ""
    for t in tasks:
        try:
            start, end = int(t.get("start") or 1), int(t.get("end") or 1)
        except (TypeError, ValueError):
            start, end = 1, 1
        tds = "".join(
            f'<td class="{"cp-gantt__on" if start <= i <= end else ""}"></td>'
            for i in range(1, len(periods) + 1))
        rows += f'<tr><th scope="row">{_esc(t.get("label"))}</th>{tds}</tr>'
    return (f'<div class="cp-gantt"><table class="core-table"><thead><tr><th scope="col">과업</th>{heads}</tr></thead>'
            f"<tbody>{rows}</tbody></table></div>")


def _org_rows(d: dict) -> list:
    roles = _items(d.get("roles"))
    if roles and all(isinstance(r, dict) for r in roles):
        return roles
    # 병렬 리스트 어댑터: teams + roles(설명 문자열) 병렬 결합. teams가 남으면 role 빈칸으로
    # 전부 표시한다 — min() 절단은 조용한 표시 소실(정본에 있는 팀이 그림에서 사라짐)이라 금지.
    teams = _items(d.get("teams"))
    if teams and (roles or any(isinstance(t, dict) for t in teams)):
        return [{"team": t, "role": roles[i] if i < len(roles) else ""}
                for i, t in enumerate(teams)]
    return []


def _org_person_text(v: "dict | str | None") -> str:
    """lead/team 항목이 dict({name, description|roles})로 오는 정본 형상 지원 —
    dict를 그대로 문자열화(repr 노출)하는 것은 표시 결함이다."""
    if isinstance(v, dict):
        txt = _esc(v.get("name") or v.get("team"))
        if v.get("description"):
            txt += f' — {_esc(v.get("description"))}'
        return txt
    return _esc(v)


def _org_team_cell(t: "dict | str | None") -> str:
    if isinstance(t, dict):
        name = f'<b>{_esc(t.get("name") or t.get("team"))}</b>'
        subs = "".join(f'<div class="cp-org__sub">{_esc(s)}</div>' for s in _items(t.get("roles")))
        return name + subs
    return _esc(t)


def p_org_table(d: dict) -> str:
    lead = f'<div class="cp-org__lead"><b>책임자</b> {_org_person_text(d.get("lead"))}</div>' if d.get("lead") else ""
    rows = ""
    for r in _org_rows(d):
        rows += f'<tr><th scope="row">{_org_team_cell(r.get("team"))}</th><td>{_esc(r.get("role"))}</td></tr>'
    return (f'<div class="cp-org">{lead}<table class="core-table">'
            '<thead><tr><th scope="col">팀</th><th scope="col">R&amp;R</th></tr></thead>'
            f"<tbody>{rows}</tbody></table></div>")


def _case_rows(d: dict) -> list:
    cases = _items(d.get("cases"))
    if cases and all(isinstance(c, dict) for c in cases):
        return cases
    # 병렬 리스트 어댑터: cases(문자열) + metrics·client_safe_names 병렬 결합. cases가 남으면
    # 빈칸으로 전부 표시한다 — min() 절단은 조용한 표시 소실(정본에 있는 사례가 그림에서
    # 사라짐)이라 금지(org_table과 동일 원칙, 5차 run slide 2 실측 결함).
    if cases and all(isinstance(c, str) for c in cases):
        metrics = _items(d.get("metrics"))
        names = _items(d.get("client_safe_names"))
        if metrics and names:
            return [{"client": names[i] if i < len(names) else "",
                     "description": c,
                     "metric": metrics[i] if i < len(metrics) else ""}
                    for i, c in enumerate(cases)]
    return []


def p_case_card(d: dict) -> str:
    cards = ""
    for c in _case_rows(d):
        ex = '<span class="cp-quote__example">[예시]</span> ' if c.get("is_example") else ""
        cards += (
            '<div class="cp-case">'
            f'<div class="cp-case__client">{ex}{_esc(c.get("client"))}</div>'
            f'<div>{_esc(c.get("description"))}</div>'
            f'<div class="cp-case__metric">{_esc(c.get("metric"))}</div></div>'
        )
    return f'<div class="cp-cases">{cards}</div>'


_RELIEF_KINDS = ("원인", "숫자", "비교", "계획")


def p_agenda(d: dict) -> str:
    """목차 = 상대의 두려움 목록 [[목차는-상대의-두려움-목록이다]].

    W32 마찰31: 원전의 조작적 정의는 ①목차=두려움 순서 구성 ②각 두려움의 해소 근거를 **본문에**
    배정하고 **체크리스트로 검수**(자매 카드 [[기획서는-두려움을-안심으로-바꾼다]])다 — 해소수단의
    목차 장표 위 표기가 아니다. 종전에는 relief 미신고 시 "해소수단 미배정" 배지를 장표에 그려
    ⓐ'본문에 해소 있음·매핑만 미신고'(원전상 무결)와 '해소 근거 없음'(취약점)을 구분 못 하고
    ⓑ내부 검수 어휘가 심사위원이 보는 장표에 노출됐다(이미지까지 가면 그림에 구워진다).
    → 장표에는 relief가 **있을 때만** 표기하고, 미신고는 _notes(검수 채널)로만 보낸다.
    """
    rows = ""
    unassigned: list[str] = []
    for i, item in enumerate(_items(d.get("items")), 1):
        if isinstance(item, dict):
            title, relief = item.get("title"), item.get("relief")
        else:
            title, relief = item, None
        badge = f'<span class="cp-agenda__badge">{_esc(relief)}</span>' if relief else ""
        if not relief:
            unassigned.append(f"{i:02d} {_as_text(title)}")
        rows += f'<div class="cp-agenda__row"><span class="cp-agenda__n">{i:02d}</span><span class="cp-agenda__t">{_esc(title)}</span>{badge}</div>'
    if unassigned:
        _notes.append("agenda 해소수단 미신고 — " + " · ".join(unassigned)
                      + " (원전 검수: 각 항목의 해소 근거가 본문 장에 있는지 확인. 장표 표기 아님)")
    return f'<div class="cp-agenda">{rows}</div>'


def p_pillar_card(d: dict) -> str:
    """병렬 하위 주장/근거를 라벨+한 줄 요지 기둥 2~4개(기본 3)로 나란히 놓는다(원전 P2.3).

    형태(색 제외) = peedori 와이어프레임 pull:
    - 면(카드)으로 구획, 선+면 중복 없음 [[선보다-면으로-구분]]
    - 라벨 굵게 / 한 줄 요지 muted — 위계는 크기·굵기 [[위계-크기-투명도-굵기]]
    - 한 줄 요지 margin-top:auto → 동류 하단선 정렬(R6 베이스라인) [[픽토그램-작게-정렬-통일]]
    - 좌측 정렬축·동일 폭·간격 [[정렬축-통일]] [[여백-통일과-균형]]
    - 모서리 번호 배지 [[번호-배지-분할-구성]] [[n열-아이콘-카드-그리드]]
    색은 skin 토큰(var(--*))에서만 — 조각에 굽지 않는다(MANUAL §3.5).
    """
    pillars = _items(d.get("pillars"))
    claim = d.get("claim")
    claim_html = f'<div class="cp-pillar__claim">{_esc(claim)}</div>' if claim else ""
    # 원전 P2.3 상한 2~4(기본 3) 강제: 벗어나면 조용히 자르지 않고 표면화(정직성).
    n = len(pillars)
    review = _review(f"pillar_card 기둥 {n}개 — 원전 P2.3 상한 2~4(기본 3) 벗어남") if n and (n < 2 or n > 4) else ""
    cols = ""
    for i, p in enumerate(pillars, 1):
        label = p.get("label") if isinstance(p, dict) else p
        line = p.get("line") if isinstance(p, dict) else None
        line_html = f'<div class="cp-pillar__line">{_esc(line)}</div>' if line else ""
        cols += (
            '<div class="cp-pillar__col">'
            f'<div class="cp-pillar__n" aria-hidden="true">{i:02d}</div>'
            f'<div class="cp-pillar__label">{_esc(label)}</div>'
            + line_html + "</div>"
        )
    return review + f'<div class="cp-pillar">{claim_html}<div class="cp-pillar__row">{cols}</div></div>'


PIECES: dict[str, Callable[[dict], str]] = {
    "text_block": p_text_block,
    "big_number": p_big_number,
    "stat_card": p_stat_card,
    "calc_arrow": p_calc_arrow,
    "contrast_pair": p_contrast_pair,
    "compare_table": p_compare_table,
    "before_after": p_before_after,
    "flow_arrow": p_flow_arrow,
    "group_naming": p_group_naming,
    "match_pairs": p_match_pairs,
    "matrix_2x2": p_matrix_2x2,
    "connect_diagram": p_connect_diagram,
    "loop_pair": p_loop_pair,
    "part_of_whole": p_part_of_whole,
    "analogy_hero": p_analogy_hero,
    "journey_flow": p_journey_flow,
    "claim_proof_split": p_claim_proof_split,
    "funnel_3layer": p_funnel_3layer,
    "chart": p_chart,
    "quote": p_quote,
    "image_evidence": p_image_evidence,
    "timeline_gantt": p_timeline_gantt,
    "org_table": p_org_table,
    "case_card": p_case_card,
    "agenda": p_agenda,
    "pillar_card": p_pillar_card,
}


# --- 슬롯·프레임 -------------------------------------------------------------

def _slot_data(slot: dict, slide: dict) -> "dict | None":
    if isinstance(slot.get("data"), dict) and slot["data"]:
        return slot["data"]
    binds = slot.get("binds")
    if binds == "*":
        # 프리셋 의무 조각(org_table·case_card·timeline_gantt) — slide.fields 전체를 그대로 넘긴다.
        # wireframe._slot_resolves와 동일 규칙(결정기 검증·런타임 렌더 정합).
        fields = slide.get("fields") or {}
        return fields if fields else None
    if binds:
        fields = slide.get("fields") or {}
        val = fields.get(binds)
        if isinstance(val, dict) and val:
            return val
        if val not in (None, "", [], {}):
            return {"body": val}
    return None


def _render_slot(slot: dict, data: dict, warnings: list, sid: Any) -> str:
    pid = slot.get("piece") or ""
    pdef = _contracts()["pieces"].get(pid)
    fn = PIECES.get(pid)
    review = ""
    if fn is None:
        warnings.append(f"slide {sid}: piece '{pid}' 미구현 → 표면화")
        return _review(f"piece '{pid}' 미구현(catalog_gap)") + f'<pre class="cp-dump">{_esc(json.dumps(data, ensure_ascii=False)[:300])}</pre>'
    missing = [k for k in (pdef or {}).get("requires", []) if data.get(k) in (None, "", [], {})]
    if missing:
        review = _review(f"piece '{pid}' 필수 필드 누락: {', '.join(missing)}")
    try:
        body = fn(data)
    except Exception as exc:
        warnings.append(f"slide {sid}: piece '{pid}' 렌더 실패({type(exc).__name__}) → 표면화")
        return _review(f"piece '{pid}' 렌더 실패: {exc}")
    return review + body


def render_slide(slide: dict, warnings: list) -> str:
    """frame 선언 슬라이드 → 콘텐츠 HTML. htmlgen의 슬라이드 루프에서 디스패치된다."""
    sid = slide.get("slide_id")
    _coerced.clear()
    _notes.clear()
    if not slide.get("frame") and slide.get("preset"):
        # preset 확장(결정 12 후속·§6): 이름 붙은 frame×piece 조합일 뿐 특권 없음 —
        # 슬라이드에 이미 있는 키(frame/rendition/slots)는 슬라이드 우선, 없는 것만 채운다.
        pdef = _contracts()["presets"].get(slide["preset"])
        if pdef is None:
            warnings.append(f"slide {sid}: preset '{slide['preset']}' 미정의 → 표면화")
            return _head(slide) + _review(f"preset '{slide['preset']}' 미정의(presets.json에 없음)")
        merged = dict(slide)
        for key in ("frame", "rendition", "slots"):
            if not merged.get(key) and pdef.get(key) is not None:
                merged[key] = pdef[key]
        slide = merged
    frame_id = slide.get("frame") or ""
    fdef = _contracts()["frames"].get(frame_id)
    if fdef is None:
        warnings.append(f"slide {sid}: frame '{frame_id}' 미정의 → 표면화")
        return _head(slide) + _review(f"frame '{frame_id}' 미정의(frames.json에 없음)")

    slots_in = [s for s in (slide.get("slots") or []) if isinstance(s, dict)]
    rendered: list[str] = []
    footers: list[str] = []  # flow_seq 산출물(footer) — 단계 열 흐름에서 분리(아래 밴드)
    for slot in slots_in:
        data = _slot_data(slot, slide)
        if data is None:
            continue  # R2: 빈 슬롯은 배치하지 않는다
        size = slot.get("size") or "auto"
        inner = _render_slot(slot, data, warnings, sid)
        cell = f'<div class="cslot cslot--{_esc(size)}">{inner}</div>'
        # flow_seq의 footer(=산출물)는 단계로 오인되지 않게 열 흐름에서 빼 별도 밴드로 낸다
        # (deck_review 착시: 산출물이 화살표 뒤 4번째 단계처럼 보임).
        if size == "footer" and frame_id == "flow_seq":
            footers.append(cell)
        else:
            rendered.append(cell)

    n = len(rendered)
    if n == 0 and not footers:
        warnings.append(f"slide {sid}: frame '{frame_id}' 유효 슬롯 0 → 표면화")
        return _head(slide) + _review("모든 슬롯이 비어 있음(R2) — 내용 배정 필요")

    variation = slide.get("variation_reason")
    var_attr = f' data-variation-reason="{_esc(variation)}"' if variation else ""
    group_attr = f' data-layout-group="{_esc(slide.get("layout_group"))}"' if slide.get("layout_group") else ""
    # rendition = 시각 은유 계층(결정 12 후속 — 사용자 우려 "CSS가 레이아웃을 고착").
    # frame은 논리 구조(순서 연결·병렬·대비)만 동결하고, 같은 논리를 어떤 은유로 그릴지는
    # rendition이 정한다: boxed(기본·와이어프레임 최소 은유) | spine(화살표 등뼈 위 아이템) | …
    # [3]는 항상 boxed로 내고, [4] 테마 공정이 T2 조정권으로 갈아끼운다(논리 diff 0).
    rendition = slide.get("rendition") or "boxed"
    if frame_id == "flow_seq" and footers:
        # 단계 = 열 흐름(.flow-steps), 산출물 = 그 아래 전폭 분리 밴드(has-outputs).
        inner = f'<div class="flow-steps cols-{n}">{"".join(rendered)}</div>' + "".join(footers)
        body = (
            f'<div class="compose compose--flow_seq cols-{n} rend-{_esc(rendition)} has-outputs"{group_attr}{var_attr}>'
            + inner + "</div>"
        )
    else:
        body = (
            f'<div class="compose compose--{_esc(frame_id)} cols-{n} rend-{_esc(rendition)}"{group_attr}{var_attr}>'
            + "".join(rendered) + "".join(footers) + "</div>"
        )
    out = _head(slide) + body
    # W32 마찰28: shape 불일치는 **결함**이므로 warnings(상류 storyline을 고쳐야 한다).
    for msg in dict.fromkeys(_coerced):
        warnings.append(f"slide {sid}: fields shape 불일치 — {msg}")
    _coerced.clear()
    # W32 마찰31: 검수 노트는 warnings가 아니다 — relief는 **선택** 필드라 미신고 자체는 결함이 아니고
    # ("본문에 해소 있음·매핑만 미신고" = 원전상 무결), warnings에 섞으면 "warnings=0 = 무결" 계약이
    # 깨진다. 별도 채널로 내보내 호출자가 검수 자료로만 쓴다(drain_notes).
    _notes[:] = [f"slide {sid}: {m}" for m in dict.fromkeys(_notes)]
    return out


def drain_notes() -> list[str]:
    """검수 노트 수거 + 비우기(마찰31). 장표에 그리지 않는 신호 — 호출자가 리포트로 낸다."""
    out = list(_notes)
    _notes.clear()
    return out


# --- CSS (무채 — 토큰 변수 상속, 명도 대비) -----------------------------------

CSS = """
.compose { display: grid; gap: 16px; flex: 1; min-height: 0; margin-top: .5em; align-items: stretch; }
.compose--full { grid-template-columns: 1fr; }
.compose--split_v { grid-template-columns: 1fr 1fr; }
.compose--split_h { grid-template-columns: 1fr; grid-template-rows: auto 1fr; }
.compose--hero_body { grid-template-columns: 1fr; grid-template-rows: minmax(30%, auto) 1fr; }
.compose--grid_2x2 { grid-template-columns: 1fr 1fr; }
.compose--grid_2x2.cols-1, .compose--grid_2x2.cols-2 { grid-template-columns: repeat(2, 1fr); }
.compose--row_n.cols-2 { grid-template-columns: repeat(2, 1fr); }
.compose--row_n.cols-3 { grid-template-columns: repeat(3, 1fr); }
.compose--row_n.cols-4 { grid-template-columns: repeat(4, 1fr); }
.compose--flow_seq { grid-auto-flow: column; grid-auto-columns: 1fr; position: relative; }
.compose--flow_seq .cslot { position: relative; }
.cslot { display: flex; flex-direction: column; min-width: 0; padding: 14px 16px; }
/* --- rendition 계층: 시각 은유(슬롯 크롬 포함)는 여기서만 정한다 — frame=논리, rendition=은유 --- */
/* boxed(기본): 박스 + 사이 화살표 — 와이어프레임의 최소 은유 */
.rend-boxed .cslot { border: 1px solid var(--line, #cfcfcf); background: var(--paper, #fff); }
.compose--flow_seq.rend-boxed .cslot + .cslot::before { content: "→"; position: absolute; left: -14px; top: 42%; color: var(--muted, #595959); font-weight: 700; }
/* flow_seq 산출물(footer) 분리 — 단계로 오인 방지(deck_review 착시 수리) */
.compose--flow_seq.has-outputs { grid-auto-flow: row; grid-auto-columns: auto; grid-template-rows: 1fr auto; }
.compose--flow_seq .flow-steps { display: grid; grid-auto-flow: column; grid-auto-columns: 1fr; gap: 16px; position: relative; align-items: stretch; }
.compose--flow_seq .cslot--footer { border: none; border-top: 2px solid var(--muted, #999); background: transparent; padding: 8px 4px 0; margin-top: 2px; }
.compose--flow_seq .cslot--footer::before { content: "산출물"; display: block; font-size: .72em; font-weight: 700; letter-spacing: .04em; color: var(--muted, #6b6b6b); margin-bottom: 3px; }
.compose--flow_seq .cslot--footer::after { content: none; }
/* spine: 화살표 등뼈 하나 위에 아이템들 — 같은 순서 논리의 다른 은유([4] T2 선택지) */
.compose--flow_seq.rend-spine { padding-bottom: 34px; }
.compose--flow_seq.rend-spine .cslot { border: none; background: transparent; padding: 8px 12px; }
.compose--flow_seq.rend-spine::after { content: ""; position: absolute; left: 1%; right: 1.5%; bottom: 16px; border-top: 2px solid var(--ink, #1a1a1a); }
.compose--flow_seq.rend-spine::before { content: ""; position: absolute; right: 0; bottom: 10.5px; border: 7px solid transparent; border-left: 12px solid var(--ink, #1a1a1a); }
.compose--flow_seq.rend-spine .cslot::after { content: ""; position: absolute; left: 50%; bottom: -22px; width: 10px; height: 10px; border-radius: 50%; background: var(--paper, #fff); border: 2px solid var(--ink, #1a1a1a); transform: translateX(-50%); }
/* R6: 조각 루트가 슬롯을 채우고, 내부 푸터(cp-source·각주)가 margin-top:auto로 바닥 정렬
   → 동류 슬롯의 푸터가 공통 베이스라인에 선다. 본문은 상단부터 흐른다. */
.cslot > .cp-stat, .cslot > .cp-bignum, .cslot > .cp-cmp, .cslot > .cp-calcwrap { flex: 1; display: flex; flex-direction: column; }
.cp-source { border-top: 1px solid var(--line, #cfcfcf); color: var(--muted, #595959); font-size: var(--type-caption, 10px); margin-top: auto; padding-top: .4em; }
.cp-source--missing { font-weight: 700; }
.cp-source--missing::before { content: "⚠ "; }
.cp-text { margin: 0; }
.cp-text li { margin-bottom: .35em; }
.cp-bignum__value { font-size: calc(var(--type-title, 54px) * .8); font-weight: 800; line-height: 1.1; }
.cp-bignum__unit { font-size: .45em; font-weight: 600; margin-left: .1em; }
.cp-bignum__label { color: var(--muted, #595959); margin-top: .3em; }
.cp-stat__icon { font-size: 1.4em; }
.cp-stat__label { color: var(--muted, #595959); font-size: var(--type-small, 12px); font-weight: 700; }
.cp-stat__value { font-size: calc(var(--type-body, 16px) * 1.9); font-weight: 800; line-height: 1.15; }
.cp-stat__note { color: var(--muted, #595959); font-size: var(--type-small, 12px); margin-top: .3em; }
.cp-calc { display: grid; grid-template-columns: 1fr auto auto; gap: 12px; align-items: center; }
.cp-calc__arrow { font-size: 1.6em; font-weight: 800; }
.cp-calc__result { font-size: calc(var(--type-body, 16px) * 2); font-weight: 800; }
.cp-calc__formula { color: var(--muted, #595959); font-size: var(--type-caption, 10px); margin-top: auto; padding-top: .5em; border-top: 1px solid var(--line, #cfcfcf); }
.cp-contrast__reject { color: var(--muted, #595959); text-decoration: line-through; }
.cp-contrast__adopt { font-size: calc(var(--type-body, 16px) * 1.25); font-weight: 800; margin-top: .3em; }
.cp-cmp__voice { color: var(--muted, #595959); font-size: var(--type-caption, 10px); font-weight: 400; }
.cp-cmp__crit { color: var(--muted, #595959); font-weight: 400; }
.cp-ba__after { font-weight: 700; }
.cp-flow { display: flex; align-items: stretch; gap: 8px; }
.cp-flow__stage { border: 1px solid var(--line, #cfcfcf); flex: 1; padding: 10px 12px; }
.cp-flow__label { font-weight: 700; }
.cp-flow__desc { color: var(--muted, #595959); font-size: var(--type-small, 12px); margin-top: .3em; }
.cp-flow__arrow { align-self: center; color: var(--muted, #595959); font-weight: 800; }
.cp-grp { display: grid; grid-template-columns: 1fr auto 1.2fr; gap: 10px; align-items: stretch; }
.cp-grp__stage { display: flex; flex-direction: column; gap: 6px; }
.cp-grp__item { border: 1px dashed var(--line, #cfcfcf); font-size: var(--type-small, 12px); padding: 6px 8px; }
.cp-grp__group { border: 1px solid var(--ink, #1a1a1a); padding: 8px; }
.cp-grp__name { font-size: calc(var(--type-body, 16px) * 1.3); font-weight: 800; margin-bottom: .3em; }
.cp-match__row { display: grid; grid-template-columns: 1fr auto 1fr; gap: 10px; align-items: center; margin-bottom: 10px; }
.cp-match__complaint { color: var(--muted, #595959); }
.cp-match__link { font-weight: 800; }
.cp-match__proposal { font-weight: 700; }
.cp-dump { color: var(--muted, #595959); font-size: var(--type-caption, 10px); overflow: hidden; }
/* --- 2b 조각 --- */
.cp-mx { display: grid; grid-template-columns: auto 1fr; grid-template-areas: "y grid" ". x" ". move"; gap: 6px; flex: 1; }
.cp-mx__ylab { grid-area: y; writing-mode: vertical-rl; transform: rotate(180deg); color: var(--muted, #595959); font-size: var(--type-small, 12px); align-self: center; }
.cp-mx__xlab { grid-area: x; color: var(--muted, #595959); font-size: var(--type-small, 12px); text-align: center; }
.cp-mx__grid { grid-area: grid; display: grid; grid-template-columns: 1fr 1fr; min-height: 0; }
.cp-mx__q { border: 1px solid var(--line, #cfcfcf); margin: -.5px; padding: 10px; position: relative; font-weight: 600; }
.cp-mx__marker { font-size: 1.1em; margin-right: .3em; }
.cp-mx__goal { margin-right: .3em; }
.cp-mx__move { grid-area: move; color: var(--muted, #595959); font-size: var(--type-small, 12px); }
.cp-conn__rel { font-weight: 800; margin-bottom: .4em; }
.cp-conn__boxes { display: flex; gap: 10px; align-items: stretch; }
.cp-conn__box { border: 1px solid var(--ink, #1a1a1a); flex: 1; padding: 8px; }
.cp-conn__name { font-weight: 800; margin-bottom: .3em; }
.cp-conn__row { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.cp-conn__node { border: 1px solid var(--line, #cfcfcf); padding: 6px 10px; }
.cp-conn__link { color: var(--muted, #595959); font-weight: 800; }
.cp-loop { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; flex: 1; }
.cp-loop__panel { border: 1px solid var(--line, #cfcfcf); padding: 10px 12px; }
.cp-loop__panel--vicious { border-style: dashed; color: var(--muted, #595959); }
.cp-loop__panel--virtuous { border-width: 2px; border-color: var(--ink, #1a1a1a); }
.cp-loop__label { font-weight: 800; margin-bottom: .4em; }
.cp-loop__cycle { font-size: 1.2em; }
.cp-pow { display: grid; grid-template-columns: auto 1fr; gap: 14px; align-items: center; flex: 1; }
.cp-pow__donut { width: 120px; height: 120px; border-radius: 50%; display: flex; align-items: center; justify-content: center; }
.cp-pow__hole { width: 72px; height: 72px; border-radius: 50%; background: var(--paper, #fff); display: flex; align-items: center; justify-content: center; font-weight: 800; text-align: center; font-size: var(--type-small, 12px); }
.cp-analogy__line { font-size: calc(var(--type-body, 16px) * 1.7); font-weight: 800; line-height: 1.3; }
.cp-analogy__proof { border-top: 1px solid var(--line, #cfcfcf); color: var(--muted, #595959); margin-top: .6em; padding-top: .5em; font-size: var(--type-small, 12px); }
.cp-jf__node--gap { border-style: dashed; }
.cp-jf__gap { color: var(--muted, #595959); font-size: var(--type-small, 12px); font-style: italic; margin-top: .3em; }
.cp-jf__gap::before { content: "⚠ "; }
.cp-cps__claim { font-size: calc(var(--type-body, 16px) * 1.3); font-weight: 800; text-align: center; }
.cp-cps .cp-flow__arrow { text-align: center; }
.cp-cps__comps { display: grid; grid-auto-flow: column; grid-auto-columns: 1fr; gap: 10px; }
.cp-cps__comp { border: 1px solid var(--line, #cfcfcf); display: flex; flex-direction: column; padding: 8px 10px; }
.cp-cps__proof { font-weight: 800; margin-top: auto; padding-top: .4em; border-top: 1px solid var(--line, #cfcfcf); }
.cp-fun { display: flex; flex-direction: column; align-items: center; gap: 4px; flex: 1; justify-content: center; }
.cp-fun__layer { border: 1px solid var(--ink, #1a1a1a); background: var(--c-gray-bg, #f2f2f2); padding: 8px 12px; text-align: center; }
.cp-chart { display: flex; flex-direction: column; flex: 1; min-height: 0; }
.cp-chart__bars { display: flex; align-items: flex-end; gap: 8%; flex: 1; padding: 0 4%; border-bottom: 2px solid var(--line, #cfcfcf); min-height: 90px; }
.cp-chart__bar { flex: 1; display: flex; flex-direction: column; justify-content: flex-end; text-align: center; height: 100%; }
.cp-chart__val { font-weight: 800; margin-bottom: .15em; }
.cp-chart__fill { background: var(--ink, #1a1a1a); min-height: 4px; }
.cp-chart__bar:first-child .cp-chart__fill { background: var(--c-gray-line, #cfcfcf); }
.cp-chart__lab { margin-top: .4em; font-size: var(--type-small, 12px); }
.cp-chart__line { width: 100%; height: 100px; color: var(--ink, #1a1a1a); }
.cp-chart__labels { display: flex; justify-content: space-between; font-size: var(--type-small, 12px); color: var(--muted, #595959); }
.cp-quote { margin: 0; display: flex; flex-direction: column; }
.cp-quote blockquote { margin: 0; font-size: calc(var(--type-body, 16px) * 1.15); font-weight: 600; border-left: 3px solid var(--ink, #1a1a1a); padding-left: .7em; }
.cp-quote figcaption { color: var(--muted, #595959); font-size: var(--type-small, 12px); margin-top: .5em; }
.cp-quote__example { color: var(--muted, #595959); font-weight: 800; }
.cp-img { margin: 0; display: flex; flex-direction: column; min-height: 0; }
.cp-img img { max-width: 100%; min-height: 0; object-fit: contain; border: 1px solid var(--line, #cfcfcf); }
.cp-img figcaption { color: var(--muted, #595959); font-size: var(--type-caption, 10px); margin-top: .4em; }
.cp-gantt .cp-gantt__on { background: var(--ink, #1a1a1a); }
.cp-org__lead { border: 1px solid var(--ink, #1a1a1a); display: inline-block; margin-bottom: .5em; padding: 6px 12px; }
.cp-org__sub { color: var(--muted, #595959); font-size: var(--type-small, 12px); font-weight: 400; margin-top: .25em; }
.cp-cases { display: grid; grid-auto-flow: column; grid-auto-columns: 1fr; gap: 10px; flex: 1; }
.cp-case { border: 1px solid var(--line, #cfcfcf); display: flex; flex-direction: column; padding: 10px 12px; }
.cp-case__client { font-weight: 800; margin-bottom: .3em; }
.cp-case__metric { border-top: 1px solid var(--line, #cfcfcf); font-weight: 800; margin-top: auto; padding-top: .4em; }
.cp-agenda { display: flex; flex-direction: column; gap: 8px; }
.cp-agenda__row { display: grid; grid-template-columns: auto 1fr auto; gap: 12px; align-items: baseline; border-bottom: 1px solid var(--line, #cfcfcf); padding-bottom: 8px; }
.cp-agenda__n { font-weight: 800; color: var(--muted, #595959); }
.cp-agenda__t { font-weight: 600; }
.cp-agenda__badge { border: 1px solid var(--ink, #1a1a1a); font-size: var(--type-caption, 10px); font-weight: 700; padding: 2px 8px; }
.cp-agenda__badge--none { border-style: dashed; color: var(--muted, #595959); }
.cp-agenda__badge--none::before { content: "⚠ "; }
/* pillar_card: 병렬 하위 주장 라벨+한 줄 기둥 2~4(원전 P2.3). 면(카드)으로 구획(선+면 중복 없음),
   좌측 정렬축·동일 폭·간격, 한 줄 요지 margin-top:auto로 동류 하단선 정렬(R6). 색=토큰만. */
.cp-pillar { display: flex; flex-direction: column; flex: 1; min-height: 0; }
.cp-pillar__claim { font-weight: 800; font-size: calc(var(--type-body, 16px) * 1.2); margin-bottom: .5em; }
.cp-pillar__row { display: grid; grid-auto-flow: column; grid-auto-columns: 1fr; gap: 14px; flex: 1; align-items: stretch; }
.cp-pillar__col { background: var(--c-gray-bg, #f2f2f2); display: flex; flex-direction: column; padding: 12px 14px; }
.cp-pillar__n { color: var(--muted, #595959); font-size: var(--type-small, 12px); font-weight: 800; letter-spacing: .05em; }
.cp-pillar__label { font-weight: 800; font-size: calc(var(--type-body, 16px) * 1.1); line-height: 1.25; margin-top: .2em; }
.cp-pillar__line { color: var(--muted, #595959); font-size: var(--type-small, 12px); line-height: 1.4; margin-top: auto; padding-top: .5em; }
"""
