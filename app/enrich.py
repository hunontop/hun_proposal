# -*- coding: utf-8 -*-
"""Stage7 enrichment for canonical SlideModel decks.

This module fills template ``required_fields`` from already-grounded slide
content, an analysis JSON card, and optional RFP text. It deliberately stays
conservative: existing ``fields`` win, low-interpretation title/message/body
fields are copied directly, and structured values are only populated when they
can be found or shaped from explicit source text.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import bind  # sibling module (app/) — W31 리허설 마찰6: EXAMPLE_REVIEW_TAG 계약 공유(review_resolve 대칭)


APP = Path(__file__).resolve().parent
ROOT = APP.parent

NULL_RENDERER_TEMPLATES = {"matrix_priority", "image_board"}

TEXT_FIELDS = {
    "author",
    "as_is",
    "body",
    "concept_message",
    "core_question",
    "date",
    "historic_growth",
    "forecast_growth",
    "growth_pct",
    "growth_pct_first",
    "growth_pct_second",
    "interpretation",
    "lead",
    "main_claim",
    "metric",
    "project_name",
    "project_title",
    "quote",
    "recommendation",
    "root",
    "section_number",
    "section_title",
    "stat",
    "stat_label",
    "title",
    "to_be",
    "transition_message",
    "visual_subject",
    "x_axis",
    "y_axis",
}

LIST_TEXT_FIELDS = {
    "as_is",
    "captions",
    "client_safe_names",
    "commitments",
    "images",
    "left_items",
    "mitigations",
    "outputs",
    "paragraphs",
    "proof_points",
    "pros",
    "cons",
    "right_items",
    "risks",
    "roles",
    "severity",
    "sub_questions",
    "supporting_points",
    "takeaways",
    "time_units",
    "weeks",
}

FIELD_ALIASES = {
    "author": ("speaker", "source_person", "quote_author"),
    "body": ("message", "claim", "summary", "takeaway"),
    "captions": ("caption", "image_captions"),
    "categories": ("labels", "periods", "groups"),
    "client_safe_names": ("client_names", "safe_client_names", "references"),
    "comparison": ("comparisons", "benchmarks"),
    "criteria": ("criterion", "evaluation_criteria"),
    "interpretation": ("insight", "implication", "meaning"),
    "main_claim": ("claim", "conclusion", "summary_claim"),
    "metric": ("measure", "kpi", "indicator"),
    "milestones": ("milestone", "key_milestones"),
    "mitigations": ("responses", "countermeasures", "mitigation"),
    "options": ("alternatives", "choices"),
    "project_title": ("project", "project_name", "proposal_title"),
    "proof_points": ("evidence", "proof", "supporting_evidence"),
    "recommendation": ("recommended_option", "recommended", "decision"),
    "risks": ("risk", "risk_factors"),
    "sections": ("takeaways", "summary_sections"),
    "series": ("datasets", "data_series"),
    "stat": ("number", "figure", "value"),
    "stat_label": ("label", "number_label", "figure_label"),
    "supporting_points": ("support", "grounds", "evidence_points"),
    "time_units": ("timeline", "periods", "weeks", "months"),
    "values": ("data", "numbers", "figures"),
    "visual_subject": ("image_subject", "visual", "visual_prompt", "image_prompt"),
    "workstreams": ("streams", "tracks", "tasks"),
}


def _load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_text(path: str | Path | None) -> str:
    if not path:
        return ""
    return Path(path).read_text(encoding="utf-8", errors="replace")


def _present(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {} and value != ()


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return ""
    if isinstance(value, (str, int, float)):
        return str(value).strip()
    return ""


def _as_text_list(value: Any) -> list[str]:
    if not _present(value):
        return []
    if isinstance(value, str):
        lines = [part.strip(" -\t") for part in re.split(r"[\r\n]+", value)]
        return [line for line in lines if line]
    if isinstance(value, dict):
        out = []
        for key, item in value.items():
            if isinstance(item, (list, tuple)):
                detail = "; ".join(_text(part) for part in item if _text(part))
            else:
                detail = _text(item)
            label = _text(key)
            out.append(f"{label}: {detail}" if label and detail else label or detail)
        return [item for item in out if item]
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            if isinstance(item, dict):
                label = _first_present(item, ("name", "label", "title", "key", "role"))
                desc = _first_present(item, ("description", "detail", "value", "fact", "summary"))
                text = f"{label}: {desc}" if label and desc else label or desc
            else:
                text = _text(item)
            if text:
                out.append(text)
        return out
    text = _text(value)
    return [text] if text else []


def _first_present(mapping: Any, keys: tuple[str, ...]) -> str:
    if not isinstance(mapping, dict):
        return ""
    for key in keys:
        value = mapping.get(key)
        text = _text(value)
        if text:
            return text
    return ""


def _norm_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk_dicts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_dicts(item)


def _find_key(value: Any, field: str) -> Any:
    names = {_norm_key(field)}
    names.update(_norm_key(alias) for alias in FIELD_ALIASES.get(field, ()))
    for mapping in _walk_dicts(value):
        for key, item in mapping.items():
            if _norm_key(str(key)) in names and _present(item):
                return item
    return None


def _slide_analysis(analysis: Any, slide: dict) -> dict:
    sid = slide.get("slide_id")
    title = _text(slide.get("title")).lower()
    template_id = _text(slide.get("template_id"))
    matches: list[dict] = []
    for mapping in _walk_dicts(analysis):
        if not isinstance(mapping, dict):
            continue
        candidate_id = mapping.get("slide_id", mapping.get("n"))
        if sid is not None and str(candidate_id) == str(sid):
            matches.append(mapping)
            continue
        if template_id and mapping.get("template_id") == template_id:
            matches.append(mapping)
            continue
        cand_title = _text(mapping.get("title") or mapping.get("slide_title")).lower()
        if title and cand_title and cand_title == title:
            matches.append(mapping)
    merged: dict[str, Any] = {}
    for match in matches:
        merged.update(match)
    return merged


def _catalog_items(pack: str) -> dict[str, dict]:
    path = ROOT / "packs" / pack / "templates.json"
    if not path.exists():
        # 격리 하우스 팩 폴백 — --pack 명시 시만(결정 11·12). W31 E3: 실물은 <개발 원본 전용 경로> 격리, 이 경로는 상시 부재
        path = ROOT / "packs_excluded" / pack / "templates.json"
    if not path.exists():
        return {}
    data = _load_json(path)
    items = data.get("templates", data) if isinstance(data, dict) else data
    if not isinstance(items, list):
        return {}
    return {item["id"]: item for item in items if isinstance(item, dict) and item.get("id")}


def _load_catalogs(pack_hint: str | None) -> dict[str, dict[str, dict]]:
    packs = []
    if pack_hint:
        packs.append(pack_hint)
    packs.extend(pack for pack in ("house_a", "house_b") if pack not in packs)
    return {pack: _catalog_items(pack) for pack in packs}


def _template_def(
    slide: dict,
    catalogs: dict[str, dict[str, dict]],
    pack_hint: str | None,
) -> tuple[str | None, dict]:
    template_id = slide.get("template_id")
    if not template_id:
        return pack_hint, {}
    if pack_hint and template_id in catalogs.get(pack_hint, {}):
        return pack_hint, catalogs[pack_hint][template_id]
    for pack, catalog in catalogs.items():
        if template_id in catalog:
            return pack, catalog[template_id]
    return pack_hint, {}


def _add_review(slide: dict, note: str) -> None:
    review = slide.setdefault("review_needed", [])
    if note not in review:
        review.append(note)


def _slide_body(slide: dict) -> list[str]:
    body = slide.get("body") or []
    return _as_text_list(body)


def _source_blob(slide: dict, slide_analysis: dict, rfp_text: str) -> str:
    parts = [
        _text(slide.get("title")),
        _text(slide.get("key_message")),
        "\n".join(_slide_body(slide)),
    ]
    for evidence in slide.get("evidence") or []:
        if isinstance(evidence, dict):
            parts.extend([_text(evidence.get("fact")), _text(evidence.get("source"))])
    for key in ("summary", "analysis", "recommendation", "requirements", "findings"):
        value = slide_analysis.get(key) if isinstance(slide_analysis, dict) else None
        if _present(value):
            parts.append(json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value)
    if rfp_text:
        parts.append(rfp_text)
    return "\n".join(part for part in parts if part)


def _labeled_numbers(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    pattern = re.compile(
        r"(?P<label>[^\n\r:;,.]{1,40}?)[\s:：-]+(?P<num>[+-]?\d+(?:\.\d+)?)\s*(?P<unit>%|percent|억원|원|명|건|개|주|개월|월|년|days?|weeks?|months?)?",
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        label = match.group("label").strip(" -:：,.;")
        if not label:
            continue
        raw = match.group("num")
        number = float(raw) if "." in raw else int(raw)
        unit = match.group("unit") or ""
        out.append({"label": label[-40:], "value": number, "unit": unit})
    return out[:12]


def _first_number(text: str) -> tuple[str, str] | None:
    match = re.search(r"[+-]?\d+(?:\.\d+)?\s*(?:%|percent|억원|원|명|건|개|주|개월|월|년)?", text, re.IGNORECASE)
    if not match:
        return None
    start = max(0, match.start() - 60)
    end = min(len(text), match.end() + 80)
    label = re.sub(r"\s+", " ", text[start:end]).strip()
    return match.group(0).strip(), label


def _percent(text: str) -> str:
    match = re.search(r"[+-]?\d+(?:\.\d+)?\s*%", text)
    return match.group(0).strip() if match else ""


def _split_label_desc(item: str) -> tuple[str, str]:
    parts = re.split(r"\s*(?:[:：\-–]|->|=>)\s*", item, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return item.strip(), ""


def _body_entries(slide: dict) -> list[tuple[str, str]]:
    return [_split_label_desc(item) for item in _slide_body(slide)]


def _fallback_entries(slide: dict) -> list[tuple[str, str]]:
    entries = _body_entries(slide)
    if entries:
        return entries
    title = _text(slide.get("title"))
    message = _text(slide.get("key_message"))
    return [(title or "Item", message)] if title or message else []


def _as_dict_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _house_b_points(text: str, slide: dict) -> list[dict[str, Any]]:
    labeled = _labeled_numbers(text)
    if labeled:
        return [
            {"label": item["label"], "value": item["value"], "unit": item.get("unit", "")}
            for item in labeled
        ]
    points = []
    for idx, (name, desc) in enumerate(_fallback_entries(slide), 1):
        points.append({"label": name or f"Item {idx}", "value": idx, "unit": "", "description": desc})
    return points


def _house_b_split_items(slide: dict) -> tuple[list[str], list[str]]:
    body = _slide_body(slide)
    if not body:
        return [], []
    midpoint = max(1, (len(body) + 1) // 2)
    return body[:midpoint], body[midpoint:] or body[:midpoint]


def _house_b_structured_from_body(field: str, template_id: str, slide: dict, text: str) -> Any:
    entries = _fallback_entries(slide)
    points = _house_b_points(text, slide)

    if field == "paragraphs":
        return _slide_body(slide) or [slide.get("key_message") or slide.get("title")]
    if field == "sections":
        return [
            {"takeaway": name or f"Takeaway {idx}", "bullets": [desc] if desc else []}
            for idx, (name, desc) in enumerate(entries[:4], 1)
        ]
    if field == "categories" and template_id == "assessment_table":
        rows = [
            {
                "kpi": item["label"],
                "target": "",
                "actual": str(item["value"]),
                "status": "flat",
                "status_label": "Review",
            }
            for item in points[:6]
        ]
        return [{"name": slide.get("title") or "Assessment", "rows": rows}] if rows else None
    if field in {"bubbles", "bus"}:
        return [
            {
                "group": "blue_dark",
                "label": item["label"],
                "label_pos": "right",
                "name": item["label"],
                "size": max(1, min(5, idx + 1)),
                "x": item["value"] if isinstance(item["value"], (int, float)) else idx + 1,
                "y": idx + 1,
            }
            for idx, item in enumerate(points[:8])
        ]
    if field == "items" and template_id == "prioritization_matrix":
        return [
            {"name": name or f"Initiative {idx}", "status": "flat", "x_band": min(2, idx % 3), "y_band": min(2, idx // 3)}
            for idx, (name, _desc) in enumerate(entries[:9])
        ]
    if field == "kpis":
        return [
            {"label": item["label"], "value": str(item["value"]), "context": item.get("unit", ""), "delta": "", "delta_dir": "flat"}
            for item in points[:6]
        ]
    if field == "trends":
        if template_id == "three_trends_table":
            return [
                {"name": name or f"Trend {idx}", "description": [desc] if desc else [], "examples": []}
                for idx, (name, desc) in enumerate(entries[:3], 1)
            ]
        if template_id == "three_trends_icons":
            return [
                {"label": name or f"Trend {idx}", "bullets": [desc] if desc else [], "icon": str(idx)}
                for idx, (name, desc) in enumerate(entries[:3], 1)
            ]
        return [
            {"label": name or f"Trend {idx}", "bullets": [desc] if desc else []}
            for idx, (name, desc) in enumerate(entries[:3], 1)
        ]
    if field == "areas":
        if template_id == "five_key_areas":
            return [
                {"name": name or f"Area {idx}", "description": desc}
                for idx, (name, desc) in enumerate(entries[:6], 1)
            ]
        return [
            {"name": name or f"Area {idx}", "bullets": [desc] if desc else []}
            for idx, (name, desc) in enumerate(entries[:7], 1)
        ]
    if field == "main_drivers":
        return [
            {"label": name or f"Driver {idx}", "secondaries": [{"label": desc, "underlying": []}] if desc else []}
            for idx, (name, desc) in enumerate(entries[:4], 1)
        ]
    if field == "ceo":
        return entries[0][0] if entries else slide.get("title")
    if field == "branches":
        return [
            {"head": name or f"Lead {idx}", "reports": [desc] if desc else []}
            for idx, (name, desc) in enumerate(entries[:5], 1)
        ]
    if field == "project_name":
        return slide.get("title") or slide.get("key_message")
    if field == "leader":
        name, desc = entries[0] if entries else ("Project lead", "")
        return {"name": name, "description": desc, "icon": "L"}
    if field == "members":
        return [
            {"name": name or f"Member {idx}", "description": desc, "icon": str(idx)}
            for idx, (name, desc) in enumerate(entries[1:7], 1)
        ] or [{"name": "Team member", "description": "", "icon": "1"}]
    if field == "functions":
        return [
            {"name": name or f"Function {idx}", "description": desc, "roles": [desc] if desc else []}
            for idx, (name, desc) in enumerate(entries[:5], 1)
        ]
    if field == "phases":
        size = 3 if template_id == "phases_chevron_3" else 4
        return [
            {
                "label": f"Phase {idx}",
                "name": name or f"Phase {idx}",
                "description": desc,
                "deliverables": [desc] if desc else [],
                "people": [],
                "timeframe": f"Phase {idx}",
                "activities": [name] if name else [],
                "outcomes": [desc] if desc else [],
            }
            for idx, (name, desc) in enumerate(entries[:size], 1)
        ]
    if field == "waves":
        return [
            {
                "name": name or f"Wave {idx}",
                "headline": name or f"Wave {idx}",
                "timeframe": f"Wave {idx}",
                "activities": [desc] if desc else [],
                "deliverables": [],
            }
            for idx, (name, desc) in enumerate(entries[:4], 1)
        ]
    if field == "weeks":
        return [str(idx + 1) for idx in range(max(3, min(8, len(entries) or 4)))]
    if field == "workstreams":
        weeks = max(3, min(8, len(entries) or 4))
        return [
            {"name": name or f"Workstream {idx}", "start_week": "1", "end_week": str(min(weeks, idx + 2)), "color": "blue_dark"}
            for idx, (name, _desc) in enumerate(entries[:5], 1)
        ]
    if field == "steps":
        if template_id == "process_activities":
            return [
                {
                    "name": name or f"Step {idx}",
                    "subtitle": f"Step {idx}",
                    "activities": [name] if name else [],
                    "interaction": "",
                    "deliverable": desc,
                }
                for idx, (name, desc) in enumerate(entries[:4], 1)
            ]
        return [
            {"name": name or f"Step {idx}", "description": desc}
            for idx, (name, desc) in enumerate(entries[:6], 1)
        ]
    if field == "stages":
        return [
            {"name": item["label"], "description": item.get("description", ""), "value": str(item["value"])}
            for item in points[:6]
        ]
    if field == "criteria":
        options = [name for name, _desc in entries[:4]] or ["Option A", "Option B"]
        scores = [2 for _ in options]
        return [{"name": "Fit", "scores": scores, "notes": ["" for _ in options]}]
    if field == "split_index":
        return max(1, min(3, (len(points) or len(entries) or 4) // 2))
    if field == "forecast_from_index":
        return max(1, min(4, (len(points) or len(entries) or 4) - 1))
    if field == "quote":
        return slide.get("key_message") or (entries[0][0] if entries else None)
    if field == "author":
        return "Source"
    if field in {"pros", "cons"}:
        left, right = _house_b_split_items(slide)
        return left if field == "pros" else right
    if field in {"left_items", "right_items"}:
        left, right = _house_b_split_items(slide)
        return left if field == "left_items" else right
    if field == "series":
        values = [item["value"] for item in points]
        return [{"name": slide.get("key_message") or "Series", "values": values}] if values else None
    return None


def _normalise_house_b_field(field: str, value: Any, template_id: str) -> Any:
    if field in {"categories"} and template_id == "assessment_table":
        if isinstance(value, list) and all(isinstance(item, dict) for item in value):
            return value
        rows = [{"kpi": item, "target": "", "actual": "", "status": "flat", "status_label": "Review"} for item in _as_text_list(value)]
        return [{"name": "Assessment", "rows": rows}] if rows else None
    if field in {"bubbles", "bus", "sections", "trends", "areas", "main_drivers", "branches", "members", "functions", "phases", "waves", "workstreams", "steps", "stages", "kpis", "series"}:
        items = _as_dict_list(value)
        return items if items else None
    if field == "leader":
        if isinstance(value, dict):
            return value
        text = _text(value)
        return {"name": text, "description": "", "icon": "L"} if text else None
    if field == "items" and template_id == "prioritization_matrix":
        items = _as_dict_list(value)
        return items if items else None
    if field == "criteria":
        if isinstance(value, list) and all(isinstance(item, dict) for item in value):
            return value
        names = _as_text_list(value)
        return [{"name": name, "scores": []} for name in names] if names else None
    return None


def _direct_value(field: str, slide: dict, deck: dict | list, index: int) -> Any:
    body = _slide_body(slide)
    meta = deck.get("meta", {}) if isinstance(deck, dict) else {}
    if field in {"title", "project_title"}:
        return slide.get("title") or meta.get("project")
    if field in {"concept_message", "main_claim", "core_question"}:
        return slide.get("key_message") or (body[0] if body else "")
    if field == "body":
        return slide.get("key_message") or (body[0] if body else "")
    if field in {"supporting_points", "sub_questions", "items", "commitments", "paragraphs"}:
        return body
    if field == "section_number":
        return f"{index + 1:02d}"
    if field == "section_title":
        return slide.get("title") or slide.get("key_message")
    if field == "left_label":
        return "As-is"
    if field == "right_label":
        return "To-be"
    return None


def _structured_from_body(field: str, template_id: str, slide: dict, pack: str | None, text: str) -> Any:
    body = _slide_body(slide)
    labeled = _labeled_numbers(text)

    if pack == "house_b":
        shaped = _house_b_structured_from_body(field, template_id, slide, text)
        if _present(shaped):
            return shaped

    if field == "visual_subject":
        return None
    if field == "metric":
        return slide.get("key_message") or (labeled[0]["label"] if labeled else "")
    if field == "comparison" and len(labeled) >= 2:
        return [{"label": item["label"], "value": item["value"]} for item in labeled[:8]]
    if field == "interpretation":
        return body or slide.get("key_message")
    if field == "categories" and labeled:
        return [item["label"] for item in labeled]
    if field == "values" and labeled:
        return [item["value"] for item in labeled]
    if field == "series" and labeled:
        return [{"name": slide.get("key_message") or "Series", "values": [item["value"] for item in labeled]}]
    if field in {"growth_pct", "growth_pct_first", "growth_pct_second", "historic_growth", "forecast_growth"}:
        return _percent(text)
    if field == "stat":
        number = _first_number(text)
        return number[0] if number else None
    if field == "stat_label":
        number = _first_number(text)
        return number[1] if number else (slide.get("key_message") or None)
    if field == "kpis" and labeled:
        return [{"label": item["label"], "value": item["value"], "context": item.get("unit", "")} for item in labeled[:6]]
    if field == "sections" and body:
        return [{"takeaway": item, "bullets": []} for item in body[:4]]
    if field in {"trends", "areas"} and body:
        key = "label" if template_id in {"three_trends_icons", "three_trends_numbered"} else "name"
        return [{key: _split_label_desc(item)[0], "bullets": [_split_label_desc(item)[1]] if _split_label_desc(item)[1] else []} for item in body[:7]]
    if field == "pillars" and body:
        return [_split_label_desc(item)[0] for item in body[:4]]
    if field == "one_line_per_pillar" and body:
        return [_split_label_desc(item)[1] or item for item in body[:4]]
    if field == "steps" and body:
        if template_id in {"process_flow_horizontal", "process_activities"} or pack == "house_b":
            return [{"name": _split_label_desc(item)[0], "description": _split_label_desc(item)[1]} for item in body[:6]]
        return body[:5]
    if field == "outputs" and body:
        outputs = [_split_label_desc(item)[1] for item in body if _split_label_desc(item)[1]]
        return outputs
    if field == "options" and body:
        return [_split_label_desc(item)[0] for item in body[:4]]
    if field == "recommendation":
        return slide.get("key_message") or None
    if field == "criteria":
        return None
    if field in {"risks", "roles", "cases", "workstreams"} and body:
        return body
    if field in {"severity", "mitigations", "metrics"}:
        return None
    if field == "client_safe_names":
        return None
    if field in {"as_is", "to_be", "left_items", "right_items"} and body:
        midpoint = max(1, len(body) // 2)
        left, right = body[:midpoint], body[midpoint:]
        if field in {"as_is", "left_items"}:
            return left
        return right
    if field == "transition_message":
        return slide.get("key_message") or None
    if field == "main_drivers" and body:
        return [{"label": item, "secondaries": []} for item in body[:4]]
    if field == "root":
        return slide.get("key_message") or slide.get("title")
    if field in {"phases", "waves"} and body:
        return [{"name": _split_label_desc(item)[0], "description": _split_label_desc(item)[1]} for item in body[:4]]
    if field == "stages":
        if labeled:
            return [{"name": item["label"], "value": item["value"], "description": item.get("unit", "")} for item in labeled[:6]]
        if body:
            return [{"name": _split_label_desc(item)[0], "description": _split_label_desc(item)[1]} for item in body[:6]]
    if field == "categories" and body:
        return body[:8]
    return None


def _normalise_field(field: str, value: Any, template_id: str, pack: str | None) -> Any:
    if not _present(value):
        return None
    if pack == "house_b":
        shaped = _normalise_house_b_field(field, value, template_id)
        if _present(shaped):
            return shaped
        if field in {
            "areas",
            "branches",
            "bubbles",
            "bus",
            "criteria",
            "functions",
            "items",
            "kpis",
            "leader",
            "main_drivers",
            "members",
            "phases",
            "sections",
            "series",
            "stages",
            "steps",
            "trends",
            "waves",
            "workstreams",
        }:
            return None
    if field in TEXT_FIELDS:
        if field == "interpretation" and isinstance(value, list):
            return _as_text_list(value)
        return _text(value) or value
    if field in LIST_TEXT_FIELDS:
        return _as_text_list(value)
    if field == "items":
        if template_id == "prioritization_matrix":
            return value if isinstance(value, list) and all(isinstance(item, dict) for item in value) else None
        return _as_text_list(value)
    if field in {"categories", "values", "time_units", "weeks"}:
        return _as_text_list(value) if field in {"categories", "time_units", "weeks"} else _number_values(value)
    if field == "comparison":
        if isinstance(value, list) and all(isinstance(item, dict) for item in value):
            return value
        nums = _labeled_numbers("\n".join(_as_text_list(value)))
        return [{"label": item["label"], "value": item["value"]} for item in nums] if nums else None
    if field == "criteria":
        if isinstance(value, list):
            if pack == "house_b" or template_id in ("comparison_table", "comparison_table_house_b"):
                return [
                    item if isinstance(item, dict) else {"name": _text(item), "scores": []}
                    for item in value
                    if _present(item)
                ]
            return value
        if isinstance(value, dict):
            return [{"name": _text(key), "scores": val if isinstance(val, list) else []} for key, val in value.items()]
        text_items = _as_text_list(value)
        return [{"name": item, "scores": []} for item in text_items] if text_items else None
    if field in {"options", "workstreams", "risks", "cases", "roles", "mitigations", "severity", "metrics"}:
        if isinstance(value, (list, dict)):
            return value
        return _as_text_list(value)
    if field in {"sections", "trends", "areas", "kpis", "main_drivers", "phases", "waves", "stages", "bubbles", "bus"}:
        if isinstance(value, list):
            return value
        return None
    if field == "series":
        if isinstance(value, list):
            return value
        return None
    if field in {"split_index", "forecast_from_index"}:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    if field in {"lead", "ceo", "leader"}:
        return value
    return value


# ---------------------------------------------------------------------------
# W31 리허설 마찰6: 제안사(자사) 프로필 — 보수적 채움 소스.
#
# 직접 바인딩 가능한 필드만 다룬다(회사 실적 목록 → portfolio_cases.cases/metrics/
# client_safe_names, 인력·조직 → org_roles.teams/roles/lead). 근거 없는 필드는 지금처럼
# 비운다(창작 금지 원칙 불변). fictional=true 회사에서 채운 슬라이드는 slide.example=True를
# 강제해 렌더러의 "예시 데이터" 배지·워터마크(W9 안전장치)가 항상 뜨게 한다 — 가상 데이터가
# 실제 제출물에 섞이는 것을 구조로 차단.
# ---------------------------------------------------------------------------

_COMPANY_ROLE_TEMPLATES = {"portfolio_cases"}


def _company_cases(company_profile: dict) -> list[dict[str, Any]]:
    records = company_profile.get("track_records") or []
    out = []
    is_example = bool(company_profile.get("fictional"))
    for r in records:
        if not isinstance(r, dict):
            continue
        client = r.get("client")
        desc = r.get("description")
        if not client and not desc:
            continue
        out.append({
            "client": client,
            "description": desc,
            "metric": r.get("metric"),
            **({"is_example": True} if is_example else {}),
        })
    return out


def _company_org_fields(company_profile: dict) -> dict[str, Any]:
    """org_roles.teams/roles/lead — compose.py의 `_org_rows` 선호 형상({team, role} dict 배열)에 맞춰
    직접 구성한다(문자열 병렬결합 어댑터에 기대지 않음 — R&R 열에 팀명이 중복 표시되는 것 방지)."""
    org = company_profile.get("organization") or {}
    out: dict[str, Any] = {}
    lead = org.get("lead")
    if isinstance(lead, dict) and lead.get("name"):
        out["lead"] = {"name": lead.get("name"), "description": lead.get("description")}
    teams = [t for t in (org.get("teams") or []) if isinstance(t, dict) and t.get("name")]
    if teams:
        out["teams"] = [{"name": t.get("name"), "roles": t.get("roles") or []} for t in teams]
        out["roles"] = [
            {"team": t.get("name"), "role": "·".join(t.get("roles") or []) or "-"}
            for t in teams
        ]
        return out
    people = [p for p in (company_profile.get("people") or []) if isinstance(p, dict) and p.get("name")]
    if people:
        out["roles"] = [
            {"team": p.get("name"), "role": p.get("role") or p.get("expertise") or "-"}
            for p in people
        ]
    return out


def _company_source_value(field: str, template_id: str, slide: dict, company_profile: "dict | None") -> Any:
    """profile.json에서 이 template의 이 field를 직접 채울 수 있으면 반환, 아니면 None."""
    if not company_profile:
        return None
    role = slide.get("role")
    if template_id in _COMPANY_ROLE_TEMPLATES or role == "company":
        cases = _company_cases(company_profile)
        if not cases:
            return None
        if field == "cases":
            return cases
        if field == "metrics":
            vals = [c.get("metric") for c in cases if c.get("metric")]
            return vals or None
        if field == "client_safe_names":
            vals = [c.get("client") for c in cases if c.get("client")]
            return vals or None
    if template_id == "org_roles":
        org_fields = _company_org_fields(company_profile)
        if field in org_fields:
            return org_fields[field]
    return None


def _mark_fictional_slide(slide: dict) -> None:
    """fictional=true 회사 데이터로 채워진 슬라이드에 [예시] 표시를 강제(W9 안전장치 대칭)."""
    slide["example"] = True
    tags = slide.setdefault("review_needed", [])
    if bind.EXAMPLE_REVIEW_TAG not in tags:
        tags.append(bind.EXAMPLE_REVIEW_TAG)


def _number_values(value: Any) -> list[int | float]:
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            if isinstance(item, dict) and "value" in item:
                item = item["value"]
            try:
                out.append(float(item) if "." in str(item) else int(item))
            except (TypeError, ValueError):
                continue
        return out
    nums = re.findall(r"[+-]?\d+(?:\.\d+)?", str(value))
    return [float(num) if "." in num else int(num) for num in nums]


def _field_value(
    field: str,
    template_id: str,
    slide: dict,
    deck: dict | list,
    analysis: Any,
    slide_analysis: dict,
    rfp_text: str,
    pack: str | None,
    index: int,
) -> Any:
    for source in (slide_analysis, analysis):
        found = _find_key(source, field)
        if _present(found):
            normalised = _normalise_field(field, found, template_id, pack)
            if _present(normalised):
                return normalised

    if not (field == "items" and template_id != "agenda"):
        direct = _direct_value(field, slide, deck, index)
        if _present(direct):
            normalised = _normalise_field(field, direct, template_id, pack)
            if _present(normalised):
                return normalised

    text = _source_blob(slide, slide_analysis, rfp_text)
    structured = _structured_from_body(field, template_id, slide, pack, text)
    normalised = _normalise_field(field, structured, template_id, pack)
    return normalised if _present(normalised) else None


def enrich_deck(
    deck: dict | list, analysis: Any, rfp_text: str = "", company_profile: "dict | None" = None,
) -> dict | list:
    """`company_profile`(W31 리허설 마찰6, 선택): 제안사(자사) profile.json.

    None이면(회사 미선택) 이 인자가 손대는 경로가 전혀 없어 기존 동작과 완전히 동일하다.
    있으면 직접 바인딩 가능한 필드(제안업체 실적→portfolio_cases, 인력·조직→org_roles)만
    보수적으로 채운다 — analysis/slide 소스 다음, 텍스트 휴리스틱(_structured_from_body)보다
    먼저 시도한다(사실 소스 우선순위: RFP/분석카드 > 자사 프로필 > 본문 텍스트 추정).
    profile.fictional=true면 채워진 슬라이드에 [예시] 표시를 강제한다(창작 데이터 유출 차단).
    """
    fictional = bool(company_profile and company_profile.get("fictional"))
    if isinstance(deck, list):
        slides = deck
        pack_hint = None
    elif isinstance(deck, dict):
        slides = deck.get("slides")
        meta = deck.get("meta") if isinstance(deck.get("meta"), dict) else {}
        pack_hint = meta.get("pack")
    else:
        raise ValueError("deck JSON root must be a slide list or an object with slides")
    if not isinstance(slides, list):
        raise ValueError("deck JSON must contain a slides array")

    catalogs = _load_catalogs(_text(pack_hint) or None)
    for index, slide in enumerate(slides):
        if not isinstance(slide, dict):
            continue
        template_id = _text(slide.get("template_id"))
        pack, tdef = _template_def(slide, catalogs, _text(pack_hint) or None)
        required = list(tdef.get("required_fields") or [])
        slide.setdefault("review_needed", [])

        # W7-C1: template_id 없음 = "레이아웃 미정"(스키마의 null)이지 "렌더러 고장"이 아니다.
        # required_fields가 애초에 없으므로 enrich가 검증할 것도, 지어낼 것도 없다 → 손대지 않는다.
        # (예전엔 여기서 "template '' has missing renderer" 태그를 붙이고 bind가 채운 fields를
        #  통째로 비웠다. 자동배정 폴백(bind._fallback_warning)이 만든 generic 슬라이드가
        #  그 경로로 들어가면 폴백이 태그를 되살리는 자기모순이 된다.)
        if not template_id:
            continue

        if template_id in NULL_RENDERER_TEMPLATES or tdef.get("renderer") is None:
            slide["fields"] = {}
            _add_review(slide, f"Stage7 enrichment: template '{template_id}' has missing renderer; fields left empty for manual/fallback handling.")
            continue

        fields = slide.setdefault("fields", {})
        if not isinstance(fields, dict):
            fields = {}
            slide["fields"] = fields

        slide_piece = _slide_analysis(analysis, slide)
        for field in required:
            if _present(fields.get(field)):
                continue
            company_value = _company_source_value(field, template_id, slide, company_profile)
            if _present(company_value):
                # 일반 _normalise_field는 다른 소스(휴리스틱 본문 파싱)를 겨냥한 규칙이라
                # "roles" 같은 필드를 텍스트 리스트로 뭉개버릴 수 있다(LIST_TEXT_FIELDS 규칙 —
                # org_roles의 {team,role} dict 행 구조와 충돌). company 소스는 이미 렌더러가
                # 기대하는 형상으로 직접 만들었으므로 정규화를 거치지 않고 그대로 쓴다.
                fields[field] = company_value
                if fictional:
                    _mark_fictional_slide(slide)
                continue
            value = _field_value(field, template_id, slide, deck, analysis, slide_piece, rfp_text, pack, index)
            if _present(value):
                fields[field] = value

        for field in required:
            if not _present(fields.get(field)):
                _add_review(slide, f"Stage7 enrichment: required field '{field}' unresolved for template '{template_id}'.")
    return deck


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage7 enrich canonical SlideModel deck JSON")
    parser.add_argument("deck_json")
    parser.add_argument("analysis_json")
    parser.add_argument("--rfp", help="Optional RFP text file")
    parser.add_argument("--output", "-o", help="Write enriched deck JSON to this path instead of stdout")
    args = parser.parse_args(argv)

    deck = _load_json(args.deck_json)
    analysis = _load_json(args.analysis_json)
    enriched = enrich_deck(deck, analysis, _load_text(args.rfp))
    payload = json.dumps(enriched, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
