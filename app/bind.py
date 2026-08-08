# -*- coding: utf-8 -*-
"""fields 바인딩 — 정본 content → 템플릿 required_fields 채우기.

원칙(안전기본): **텍스트형 필드는 content에서 결정적 매핑, 구조형은 지어내지 않고 review_needed로 비워둔다.**
(환각·유출 차단 = make_pptx의 '검토요망' 철학 일관.)

- 이미 AI가 fields를 준 슬라이드는 건드리지 않는다(우선).
- 바인더가 있는 텍스트형 템플릿만 자동 채움.
- 채운 뒤에도 비어있는 required_field → "[필수입력 미확보] <field>" 검토요망.
"""
from __future__ import annotations

from typing import Callable


# W9 예시 데이터 정책(안전장치 ②): slide.example=True인 슬라이드에 "실데이터로 교체 필요"를
# review_needed로 자동 태그한다. 태그 문자열은 review_resolve가 접두로 인식해(EXAMPLE_TAG_PREFIX)
# fact_supplied 해소 시 예시 마크까지 제거한다 — 접두 `[예시 데이터]`는 그 계약이므로 바꾸지 말 것.
# (bind._missing_flag ↔ review_resolve._FIELD_TAG_RES와 같은 문자열 결합 관례.)
EXAMPLE_REVIEW_TAG = "[예시 데이터] 실데이터로 교체 필요"


def _title(s): return s.get("title", "")
def _msg(s): return s.get("key_message", "")
def _body(s): return list(s.get("body") or [])


# template_id/role → (정본 slide → fields).
# 텍스트형: 완전 바인딩. 구조형: **텍스트 파생 가능한 부분만** 채우고 숫자/축 등은 비워둠(→ 검토요망 플래그).
# ⚠️ 동어반복 주의: core_question/main_claim/concept_message는 의도적으로 message(_msg)를 미러링한다
#   (문제 슬라이드의 "핵심 질문"=핵심 메시지 by-design). 이 hero 필드를 승격 렌더링하는 렌더러
#   (htmlgen r_problem/r_summary/r_cover)는 message와 동일하면 부제(slide__msg)를 생략해 중복을 막는다
#   → _head(slide, claim) 참조. 여기서 별도 문구를 만들 소스는 없으므로 미러링을 유지한다.
BINDERS: dict[str, Callable[[dict], dict]] = {
    # --- 텍스트형 (완전) ---
    "cover_cinematic": lambda s: {"project_title": _title(s), "concept_message": _msg(s)},
    "problem_questions": lambda s: {"core_question": _msg(s), "sub_questions": _body(s)},
    "executive_summary": lambda s: {"main_claim": _msg(s), "supporting_points": _body(s)},
    "strategy_pillars": lambda s: {"pillars": _body(s)},
    "closing_matrix": lambda s: {"commitments": _body(s)},
    # --- 구조형 (부분: 텍스트 파생만, 나머지 required는 플래그됨) ---
    "data_interpretation": lambda s: {"metric": _msg(s), "interpretation": _body(s)},   # comparison(수치)→플래그
    "comparison_table": lambda s: {"options": _body(s), "recommendation": _msg(s)},      # criteria→플래그
    "org_roles": lambda s: {"roles": _body(s)},                                          # teams/lead→플래그
    "process_steps": lambda s: {"steps": _body(s)},                                      # outputs→플래그
    "roadmap_gantt": lambda s: {"workstreams": _body(s)},                                # time_units/milestones→플래그
    "risk_dashboard": lambda s: {"risks": _body(s)},                                     # severity/mitigations→플래그
    "portfolio_cases": lambda s: {"cases": _body(s)},                                    # metrics/client_safe_names→플래그
    # matrix_priority: x_axis/y_axis/items 전부 구조형 → 부분 바인딩 불가, 전부 플래그
    # --- role 별칭(팩 무관) ---
    "cover": lambda s: {"project_title": _title(s), "concept_message": _msg(s)},
    "problem_intro": lambda s: {"core_question": _msg(s), "sub_questions": _body(s)},
    "summary": lambda s: {"main_claim": _msg(s), "supporting_points": _body(s)},
    "closing": lambda s: {"commitments": _body(s)},
    "data": lambda s: {"metric": _msg(s), "interpretation": _body(s)},
    "comparison": lambda s: {"options": _body(s), "recommendation": _msg(s)},
    "process": lambda s: {"steps": _body(s)},
}


def bind_slide(slide: dict, required_fields: list[str]) -> list[str]:
    """슬라이드 fields를 채우고, 못 채운 required_field 목록을 반환(검토요망용)."""
    fields = slide.setdefault("fields", {})
    tid = slide.get("template_id")
    role = slide.get("role")
    binder = BINDERS.get(tid or "") or BINDERS.get(role or "")
    if binder:
        for k, v in binder(slide).items():
            if v and not fields.get(k):   # AI가 준 값 우선, 빈 값은 덮지 않음
                fields[k] = v
    # required 중 여전히 빈 것 = 구조형 데이터 미확보
    missing = [rf for rf in (required_fields or []) if not fields.get(rf)]
    return missing


# W7-C1: 자동배정 폴백 — 코드가 추측한 template_id가 **필수필드를 하나도** 못 채우면
# 그 템플릿은 거짓말이다(deck.json은 roadmap_gantt라 하고 렌더러는 generic 본문을 그린다
# — layouts_house_a.timeline_matrix가 units 없으면 _fallback()으로 빠지는 것이 근거).
# 강제 배정을 유지하면 근거 없는 슬라이드가 태그 N건을 낳고, 사람 서명 N건을 소모한다.
#
# 폴백 조건(보수적 — 검사를 없애는 게 아니라 **거짓 배정**만 없앤다):
#   ① template_id를 코드가 추측했다(meta.template_auto). 명시 지정은 면제 — 사람/스토리라인의 의도.
#   ② 템플릿에 required_fields가 있는데 바인딩 후 **전부** 비었다(부분이라도 채워지면 유지).
# 폴백 결과 template_id=None → 스키마의 "null=미정"이고, htmlgen은 role 별칭 → generic 본문으로
# 우아하게 렌더한다(신규 어휘 0). 폴백 사실은 report["template_fallback"]로 가시화(조용한 폴백 금지).
AUTO_TEMPLATE_META_KEY = "template_auto"   # adapt_storyline이 심는다(자동배정 슬라이드 id 목록)


def _missing_flag(field: str) -> str:
    return f"[필수입력 미확보] {field} — 구조 데이터 필요(지어내지 않음)"


def _fallback_warning(sid, template_id: str, missing: list[str]) -> str:
    return (
        f"slide {sid}: 자동배정 '{template_id}' → generic 폴백 "
        f"(필수필드 {', '.join(missing)} 전부 미확보 — 근거 없는 템플릿을 강제하지 않는다)"
    )


def _strip_field_flags(slide: dict, template_id: str, fields: list[str]) -> None:
    """폴백으로 사라진 템플릿의 필수필드 태그만 제거. **다른 태그는 절대 건드리지 않는다**(W5 불변식).

    지우는 대상은 두 생산자뿐: bind(_missing_flag)와 enrich("required field '<f>' unresolved
    for template '<tid>'"). 근사 매칭 없음 — 정확 문자열/명시 템플릿명 일치만.
    """
    tags = slide.get("review_needed") or []
    if not tags:
        return
    doomed = {_missing_flag(f) for f in fields}
    enrich_marks = {f"required field '{f}' unresolved for template '{template_id}'." for f in fields}
    slide["review_needed"] = [
        t for t in tags
        if t not in doomed and not any(t.endswith(mark) for mark in enrich_marks)
    ]


def apply_template_fallback(deck: dict, templates_by_id: dict[str, dict]) -> list[dict]:
    """자동배정 폴백을 덱에 적용(in-place). 반환 = 폴백 기록 목록(warning 포함).

    **enrich 이후에 불러도 안전하도록 별도 함수다** — enrich가 분석카드에서 time_units/milestones를
    실제로 채울 수 있으므로, enrich가 도는 run에서는 그 뒤에 판정해야 근거 있는 간트를 잃지 않는다.
    멱등: 이미 폴백된 슬라이드는 template_id가 없어 두 번 걸리지 않는다.
    """
    auto = set((deck.get("meta") or {}).get(AUTO_TEMPLATE_META_KEY) or [])
    if not auto:
        return []
    out: list[dict] = []
    for s in deck.get("slides", []):
        tid = s.get("template_id")
        if not tid or s.get("slide_id") not in auto:
            continue                                   # 명시 배정·이미 폴백됨 → 대상 아님
        req = list((templates_by_id.get(tid) or {}).get("required_fields") or [])
        if not req:
            continue
        fields = s.get("fields") or {}
        missing = [rf for rf in req if not fields.get(rf)]
        if len(missing) != len(req):
            continue                                   # 하나라도 채워졌으면 템플릿을 유지한다
        s["template_id"] = None                        # 스키마의 "null=미정" → htmlgen generic 본문
        _strip_field_flags(s, tid, req)
        bind_slide(s, [])                              # role 별칭 바인더에게 한 번 더 기회(cover 등)
        out.append({
            "slide_id": s.get("slide_id"),
            "from": tid,
            "missing": missing,
            "warning": _fallback_warning(s.get("slide_id"), tid, missing),
        })
    return out


def tag_example_slides(deck: dict) -> int:
    """W9 안전장치 ②: 예시 데이터 슬라이드에 '교체 필요' 태그를 붙인다(멱등). 반환 = 신규 태그 수.

    태그 생산일 뿐 제거는 하지 않는다(창작금지의 대칭 = 근거 없음 표식은 사람 서명 없이 안 사라진다).
    이미 붙어 있으면 다시 붙이지 않는다 → 매 렌더 재실행에도 태그가 중복되지 않는다.
    """
    added = 0
    for s in deck.get("slides", []):
        if not isinstance(s, dict) or not s.get("example"):
            continue
        tags = s.setdefault("review_needed", [])
        if EXAMPLE_REVIEW_TAG not in tags:
            tags.append(EXAMPLE_REVIEW_TAG)
            added += 1
    return added


def bind_deck(deck: dict, templates_by_id: dict[str, dict], *, allow_fallback: bool = True) -> dict:
    """deck 전체 바인딩. 미확보 구조필드는 review_needed에 플래그. 리포트 반환.

    `allow_fallback=False`면 자동배정 폴백을 **미루기만** 한다(enrich가 필드를 채울 기회를 준 뒤
    호출부가 `apply_template_fallback()`을 직접 부른다). 폴백 판정 자체는 한 곳에만 산다.
    """
    report: dict = {"bound": 0, "flagged": {}, "template_fallback": []}
    pending: list[tuple[dict, list[str]]] = []
    for s in deck.get("slides", []):
        tdef = templates_by_id.get(s.get("template_id") or "", {})
        req = tdef.get("required_fields", [])
        pending.append((s, bind_slide(s, req)))

    if allow_fallback:
        report["template_fallback"] = apply_template_fallback(deck, templates_by_id)
        fell_back = {f["slide_id"] for f in report["template_fallback"]}
        pending = [(s, [] if s.get("slide_id") in fell_back else m) for s, m in pending]

    for s, missing in pending:
        if s.get("fields"):
            report["bound"] += 1
        if missing:
            s.setdefault("review_needed", [])
            for m in missing:
                flag = _missing_flag(m)
                if flag not in s["review_needed"]:
                    s["review_needed"].append(flag)
            report["flagged"][s["slide_id"]] = missing
    # W9: 예시 데이터 자동 태그(안전장치 ②). 필드 미확보 태그와 별개 축이라 마지막에 얹는다.
    report["example_tagged"] = tag_example_slides(deck)
    return report
