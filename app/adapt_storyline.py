# -*- coding: utf-8 -*-
"""Vendor stage5 storyline JSON → canonical SlideModel deck.

Only source-backed values are copied. Layout fields and template choices remain
empty until a later stage supplies them.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


APP = Path(__file__).resolve().parent


class StorylineAdapterError(ValueError):
    """Raised when a storyline cannot provide stable canonical slide IDs."""


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return str(value)
    return ""


def _slide_id(value: Any, index: int) -> int:
    if isinstance(value, bool):
        raise StorylineAdapterError(f"slide {index}: n must be an integer, got boolean")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value.strip()):
        return int(value.strip())
    raise StorylineAdapterError(f"slide {index}: stable integer n is required")


def _body(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [text for item in value if (text := _text(item))]
    text = _text(value)
    return [text] if text else []


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (str, int, float)):
        return value
    return None


def _fields(value: Any) -> dict:
    """Pass through LLM-supplied structured render fields (JSON-safe dict).

    Storyline may carry a per-slide ``fields`` object holding the structured
    payload its template renderer expects (options/criteria, risks/severity,
    time_units/milestones, teams/lead, ...). Only JSON-safe content is copied;
    enrichment still validates/normalises and fills any gaps downstream.
    """
    if not isinstance(value, dict):
        return {}
    cleaned = _json_safe(value)
    return cleaned if isinstance(cleaned, dict) else {}


def _example_flag(value: Any) -> bool:
    """W9: storyline 슬라이드의 예시/데모 데이터 표식. 명시 true만 인정한다.

    문자열 "true"/"1"/"yes"도 관대하게 받되(외부 LLM이 종종 문자열로 준다),
    그 외는 False. False는 슬라이드에 아예 심지 않는다(호출부에서 조건부 추가) —
    예시 없는 기존 덱의 바이트 동일성을 지키기 위함.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "예시", "example"}
    return False


def _carry_optional(record: dict) -> dict:
    """W16(+W31 R9): supports_axis·length_band·separate_budget·emphasis를 조건부로 운반
    (값 없으면 키 미추가).

    - supports_axis: 축 id 문자열(장표→메시지 추적성, 결정 9①).
    - length_band: [min, max] 어절 밴드(분량 리듬 실측 기준, 결정 9⑤).
    - separate_budget: G5 별도예산 표기(스키마 슬롯 — 사람/참조가 채움, 자동 생성 금지).
    - emphasis: W31 리허설 마찰17(2026-07-21 확정) — A5 회의에서 사람이 확정한 디자인 강조
      (hero) 표식. 구조 결정이라 A5에서만 채워지고 하류(뼈대·이미지)는 소비만 한다.
    존재하지 않는 키는 심지 않아 기존 덱의 바이트 동일성을 지킨다(example과 같은 규칙).
    """
    out: dict = {}
    axis = record.get("supports_axis")
    if isinstance(axis, str) and axis.strip():
        out["supports_axis"] = axis.strip()
    band = record.get("length_band")
    if (isinstance(band, (list, tuple)) and len(band) == 2
            and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in band)):
        out["length_band"] = [int(band[0]), int(band[1])]
    budget = record.get("separate_budget")
    if isinstance(budget, bool):
        out["separate_budget"] = budget
    elif isinstance(budget, str) and budget.strip():
        out["separate_budget"] = budget.strip()
    emphasis = record.get("emphasis")
    if isinstance(emphasis, str) and emphasis.strip():
        out["emphasis"] = emphasis.strip()
    # W32 마찰36: 형태 의도(form_intent)는 뼈대 결정기의 권장 입력이다 — 결정기는 deck.json을
    # 읽으므로 여기서 운반하지 않으면 storyline에 적혀도 조용히 끊긴다(이 함수의 allowlist가
    # 마찰36 통로의 병목). art_note는 운반하지 않는다 — 소비자(imagedeck)가 storyline.json을
    # 직접 읽어 deck 운반이 불필요하고, 안 쓰는 키를 deck에 심는 것은 중복이다.
    form_intent = record.get("form_intent")
    if isinstance(form_intent, str) and form_intent.strip():
        out["form_intent"] = form_intent.strip()
    return out


def _review_needed(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [text for item in value if (text := _text(item))]
    text = _text(value)
    return [text] if text else []


def _role(section: Any) -> str:
    source_role = _text(section).strip()
    return "cover" if source_role.lower() in {"표지", "cover"} else source_role


def _load_template_catalog(pack: str) -> dict[str, dict]:
    path = APP.parent / "packs" / pack / "templates.json"
    if not path.exists():
        # 격리 하우스 팩 폴백 — --pack 명시 시만(결정 11·12). W31 E3: 실물은 <개발 원본 전용 경로> 격리, 이 경로는 상시 부재
        path = APP.parent / "packs_excluded" / pack / "templates.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("templates", data) if isinstance(data, dict) else data
    if not isinstance(items, list):
        return {}
    return {item["id"]: item for item in items if isinstance(item, dict) and item.get("id")}


def _contains_any(haystack: str, needles: tuple[str, ...]) -> bool:
    return any(needle and needle in haystack for needle in needles)


def _renderable(catalog: dict[str, dict], template_id: str) -> bool:
    template = catalog.get(template_id)
    return bool(template and template.get("renderer"))


def _pick_existing_template(catalog: dict[str, dict], candidates: tuple[str, ...]) -> str | None:
    for template_id in candidates:
        if _renderable(catalog, template_id):
            return template_id
    return None


_TEMPLATE_RULES = (
    {
        "candidates": ("cover_cinematic", "cover_slide"),
        "roles": ("cover", "표지"),
        "keywords": ("표지", "cover", "제안서", "proposal"),
    },
    {
        "candidates": ("agenda",),
        "roles": ("agenda", "목차"),
        "keywords": ("목차", "agenda", "contents", "차례"),
    },
    {
        "candidates": ("problem_questions", "issue_tree"),
        "roles": ("problem_intro", "problem", "challenge", "고민", "문제"),
        "keywords": ("고민", "문제", "질문", "과제", "이슈", "challenge", "problem", "question", "issue"),
    },
    {
        "candidates": ("executive_summary", "executive_summary_takeaways", "dark_navy_summary"),
        "roles": ("summary", "executive_summary", "요약"),
        "keywords": ("요약", "핵심", "결론", "시사점", "takeaway", "summary", "executive"),
    },
    {
        "candidates": ("roadmap_gantt", "gantt_timeline", "phases_table_4", "waves_timeline_4", "phases_chevron_3"),
        "roles": ("roadmap", "timeline", "일정"),
        "keywords": ("일정", "로드맵", "기간", "주차", "timeline", "gantt", "schedule", "roadmap", "phase"),
    },
    {
        "candidates": ("process_steps", "process_flow_horizontal", "process_activities"),
        "roles": ("process", "프로세스", "절차"),
        "keywords": ("프로세스", "절차", "단계", "흐름", "process", "step", "workflow"),
    },
    {
        "candidates": ("comparison_table", "two_column_compare", "pros_cons"),
        "roles": ("comparison", "contrast", "assessment", "비교"),
        "keywords": ("비교", "as-is", "to-be", "asis", "tobe", "장단점", "평가", "compare", "comparison", "option"),
    },
    {
        "candidates": ("contrast_as_is_to_be", "two_column_compare"),
        "roles": ("contrast",),
        "keywords": ("as-is", "to-be", "현재", "목표", "전환", "before", "after"),
    },
    {
        "candidates": ("org_roles", "team_chart", "project_team_circles", "org_chart"),
        "roles": ("organization", "org", "hierarchy", "조직", "인력"),
        "keywords": ("조직", "인력", "역할", "r&r", "rnr", "팀", "참여", "staff", "team", "role", "organization"),
    },
    {
        "candidates": ("risk_dashboard", "assessment_table"),
        "roles": ("risk", "리스크"),
        "keywords": ("리스크", "위험", "대응", "risk", "mitigation"),
    },
    {
        "candidates": ("strategy_pillars", "three_trends_table", "three_trends_numbered", "five_key_areas", "overview_areas"),
        "roles": ("strategy", "areas", "trends", "전략"),
        "keywords": ("전략", "추진전략", "체계", "축", "방향", "핵심영역", "pillar", "strategy", "trend", "area"),
    },
    {
        "candidates": ("data_interpretation", "kpi_dashboard", "assessment_table", "stat_hero", "column_comparison"),
        "roles": ("data", "chart", "kpi", "stat", "예산"),
        "keywords": ("data", "chart", "kpi", "성과", "지표", "수치", "예산", "금액", "비용", "효과", "측정", "dashboard", "metric", "budget", "cost"),
    },
    {
        "candidates": ("portfolio_cases", "overview_areas"),
        "roles": ("portfolio", "case", "실적"),
        "keywords": ("실적", "사례", "경험", "이력", "증빙", "portfolio", "case", "reference", "track record"),
    },
    {
        "candidates": ("closing_matrix", "dark_navy_summary"),
        "roles": ("closing", "마무리"),
        "keywords": ("마무리", "감사", "약속", "closing", "thank", "commitment"),
    },
)


def _catalog_hint_score(template: dict, keywords: tuple[str, ...]) -> int:
    hint_text = " ".join(
        _text(part)
        for part in (
            template.get("id"),
            template.get("role"),
            " ".join(template.get("use_when") or []),
        )
    ).lower()
    return 1 if _contains_any(hint_text, keywords) else 0


def _infer_template_id(
    *,
    role: str,
    title: str,
    key_message: str,
    body: list[str],
    catalog: dict[str, dict],
) -> str | None:
    if not catalog:
        return None
    role_text = role.lower()
    header_text = " ".join([role, title, key_message]).lower()
    body_text = " ".join(body).lower()
    if _contains_any(header_text, ("목차", "agenda", "contents", "차례")) and not _pick_existing_template(catalog, ("agenda",)):
        return None
    best: tuple[int, int, str] | None = None
    for priority, rule in enumerate(_TEMPLATE_RULES):
        template_id = _pick_existing_template(catalog, rule["candidates"])
        if not template_id:
            continue
        roles = rule["roles"]
        keywords = rule["keywords"]
        score = 0
        if role_text in roles or _contains_any(role_text, roles):
            score += 3
        if _contains_any(header_text, keywords):
            score += 2
        elif _contains_any(body_text, keywords):
            score += 1
        score += _catalog_hint_score(catalog[template_id], keywords)
        if score < 3:
            continue
        candidate = (score, -priority, template_id)
        if best is None or candidate > best:
            best = candidate
    return best[2] if best else None


def _existing_template_id(record: dict) -> str | None:
    existing = _text(record.get("template_id") or record.get("selected_template_id")).strip()
    return existing or None


# W7-C1: 자동배정과 명시배정의 구분은 **여기서만** 알 수 있다(스토리라인 레코드를 보는 유일한 지점).
# 뒤 단계(bind)가 "이 template_id는 코드가 추측한 것"임을 알아야 폴백 여부를 판단할 수 있으므로,
# 추측한 슬라이드 id를 meta에 남긴다. 명시 template_id는 이 목록에 들어가지 않는다 → 폴백 면제.
AUTO_TEMPLATE_META_KEY = "template_auto"


def adapt_storyline(
    document: dict | list,
    *,
    project: str | None = None,
    pack: str = "core",
    source_file: str | Path | None = None,
) -> dict:
    """Adapt vendor ``n/section/title/message/bullets`` records to a deck."""
    if isinstance(document, dict):
        records = document.get("slides")
        source_meta = document.get("meta") if isinstance(document.get("meta"), dict) else {}
    elif isinstance(document, list):
        records = document
        source_meta = {}
    else:
        raise StorylineAdapterError("storyline root must be an object or slide array")
    if not isinstance(records, list) or not records:
        raise StorylineAdapterError("storyline must contain a non-empty slides array")

    catalog = _load_template_catalog(pack)
    slides: list[dict] = []
    seen: set[int] = set()
    auto_assigned: list[int] = []
    for index, record in enumerate(records, 1):
        if not isinstance(record, dict):
            raise StorylineAdapterError(f"slide {index}: record must be an object")
        sid = _slide_id(record.get("n"), index)
        if sid in seen:
            raise StorylineAdapterError(f"slide {index}: duplicate n={sid}")
        seen.add(sid)
        role = _role(record.get("section"))
        title = _text(record.get("title"))
        key_message = _text(record.get("message"))
        body = _body(record.get("bullets"))
        template_id = _existing_template_id(record)
        if template_id is None:
            template_id = _infer_template_id(
                role=role,
                title=title,
                key_message=key_message,
                body=body,
                catalog=catalog,
            )
            if template_id:
                auto_assigned.append(sid)
        slides.append(
            {
                "slide_id": sid,
                "role": role,
                "template_id": template_id,
                "title": title,
                "key_message": key_message,
                "body": body,
                "fields": _fields(record.get("fields")),
                "evidence": [],
                "review_needed": _review_needed(record.get("flag")),
                "open_questions": [],
                "style": {},
                # W9: 예시/데모 데이터 표식. False면 키 자체를 심지 않는다(기존 덱 바이트 동일 보존).
                **({"example": True} if _example_flag(record.get("example")) else {}),
                # W16(결정 9①⑤): 장표→메시지 추적성(supports_axis)·분량 리듬(length_band)·
                # G5 별도예산(separate_budget)을 deck.json까지 운반한다. 값이 없으면 키를 심지
                # 않는다(기존 덱 바이트 동일 보존 — example과 같은 conditional 규칙).
                **_carry_optional(record),
            }
        )

    project_name = _text(project) if project is not None else _text(source_meta.get("project"))
    source_files = [str(source_file)] if source_file is not None else []
    return {
        "meta": {
            "project": project_name,
            "pack": pack,
            "source_files": source_files,
            AUTO_TEMPLATE_META_KEY: sorted(auto_assigned),
        },
        "slides": sorted(slides, key=lambda slide: slide["slide_id"]),
    }
