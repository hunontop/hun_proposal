# -*- coding: utf-8 -*-
"""와이어프레임 결정기 계약 — wireframe.json 검증·병합·게이트 블록 (W21, 결정 10 [3]·결정 12).

공정 위치: [2] 내용 동결 후, [4] 테마 전. 결정기(LLM)가 동결된 내용을 읽고
장별 메시지 유형을 판별해 frame×piece를 결정한 wireframe.json을 쓰면,
이 모듈이 계약을 검증하고 deck.json에 병합한다(무채 core 재렌더는 파이프라인 몫).

wireframe.json 스키마(정본 설계 = CONTEXT/W21_CATALOG_REBUILD.md §5):
    {"schema_version": 1, "selected_by": "llm:<결정기 식별>",
     "slides": [{"slide_id": "6", "message_type": "구조",
                 "frame": "flow_seq", "rendition": "boxed",
                 "layout_group": "axis1-plan", "variation_reason": null,
                 "slots": [{"piece": "flow_arrow", "size": "wide", "binds": "*"}],
                 "principles": ["3-3"], "catalog_gap": []}]}

검증 철학(이 프로젝트 문법): 오류 = 계약 위반(적용 중단·SSOT 안전, stage9 override와 동일).
경고 = 정직성 표면화 대상(적용은 하되 게이트에 실림 — R1·R2·R9·requires 미충족).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _compose():
    try:
        from . import compose  # 패키지 컨텍스트
    except ImportError:
        import compose  # top-level(sys.path에 app/render)
    return compose


def _design_spec():
    try:
        from . import design_spec
    except ImportError:
        import design_spec
    return design_spec


def _knowledge_card_index() -> str:
    """와이어프레임 카드의 frontmatter name·claim만 프롬프트 색인으로 만든다."""
    ds = _design_spec()
    root = ds._reference_images_root()
    if root is None:
        return "(디자인지식 색인 없음 - config knowledge.reference_images_root 미설정)"
    cards_dir = root / "cards" / "와이어프레임"
    if not cards_dir.is_dir():
        return "(디자인지식 색인 없음 - config knowledge.reference_images_root 미설정)"
    lines = ["## 디자인지식 카드 색인 (형태 원칙 - 와이어프레임 층 전용)"]
    for path in sorted(cards_dir.glob("*.md")):
        try:
            meta = ds._parse_card_md(path)
        except (OSError, UnicodeError):
            continue
        name = str(meta.get("name") or path.stem).strip()
        claim = str(meta.get("claim") or "").strip()
        lines.append(f"- {name}: {claim}")
    if len(lines) == 1:
        return "(디자인지식 색인 없음 - config knowledge.reference_images_root 미설정)"
    return "\n".join(lines)


# R1(2-2): 비교 유형별 조각 분류 — 한 슬라이드에 서로 다른 유형 혼합 금지.
_COMPARE_KIND = {
    "contrast_pair": "대조", "compare_table": "대조",
    "before_after": "흐름", "flow_arrow": "흐름", "loop_pair": "흐름",
    "part_of_whole": "구성",
}


def load(path: "str | Path") -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _slot_resolves(slot: dict, slide: dict) -> "dict | None":
    """compose._slot_data와 동일 규칙으로 슬롯 데이터 해석(검증 전용, 부작용 없음)."""
    data = slot.get("data")
    if isinstance(data, dict) and data:
        return data
    binds = slot.get("binds")
    fields = slide.get("fields") or {}
    if binds == "*":
        return fields if fields else None
    if binds:
        val = fields.get(binds)
        if isinstance(val, dict) and val:
            return val
        if val not in (None, "", [], {}):
            return {"body": val}
    return None


def validate(wf: dict, deck: dict) -> dict:
    """계약 검증 → {"errors": [...], "warnings": [...], "stats": {...}, "catalog_gap": [...]}."""
    contracts = _compose()._contracts()
    frames, pieces = contracts["frames"], contracts["pieces"]
    presets = contracts.get("presets", {})
    errors: list[str] = []
    warnings: list[str] = []
    gaps: list[dict] = []
    deck_by_id = {str(s.get("slide_id")): s for s in deck.get("slides", [])}

    if not isinstance(wf.get("slides"), list) or not wf["slides"]:
        return {"errors": ["wireframe.slides가 비어 있음"], "warnings": [], "stats": {}, "catalog_gap": []}
    if not wf.get("selected_by"):
        errors.append("selected_by 없음 — 출처 표기 의무(결정 8 문법)")

    group_frames: dict[str, set] = {}
    frames_used: set = set()
    pieces_used: set = set()
    presets_used: set = set()
    combos: set = set()

    for ent in wf["slides"]:
        sid = str(ent.get("slide_id"))
        slide = deck_by_id.get(sid)
        if slide is None:
            errors.append(f"slide {sid}: deck.json에 없는 slide_id")
            continue
        knowledge_cards = ent.get("knowledge_cards")
        if knowledge_cards is not None:
            if not isinstance(knowledge_cards, list) or not all(
                isinstance(card, str) for card in knowledge_cards
            ):
                errors.append(
                    f"slide {sid}: knowledge_cards는 문자열 슬러그 리스트여야 함"
                )

        frame_id = ent.get("frame")
        slots_src = ent.get("slots")
        preset_id = ent.get("preset")
        if frame_id is None and preset_id is not None:
            # preset 확장(§6 동급 참여): frame 대신 preset이 오면 presets.json의 frame으로 검증 대체.
            pdef = presets.get(preset_id)
            if pdef is None:
                errors.append(f"slide {sid}: preset '{preset_id}' 미정의 — 없는 조합은 catalog_gap으로 선언하라")
                continue
            presets_used.add(preset_id)
            frame_id = pdef.get("frame")
            if not slots_src:
                slots_src = pdef.get("slots")
        if frame_id not in frames:
            errors.append(f"slide {sid}: frame '{frame_id}' 미정의 — 없는 형태는 catalog_gap으로 선언하라")
            continue
        frames_used.add(frame_id)
        slots = [s for s in (slots_src or []) if isinstance(s, dict)]
        if not slots:
            errors.append(f"slide {sid}: slots 없음")
            continue
        kinds: set = set()
        filled = 0
        for slot in slots:
            pid = slot.get("piece")
            pdef = pieces.get(pid)
            if pdef is None:
                errors.append(f"slide {sid}: piece '{pid}' 미정의 — catalog_gap으로 선언하라")
                continue
            pieces_used.add(pid)
            combos.add(f"{frame_id}×{pid}")
            if pid in _COMPARE_KIND:
                kinds.add(_COMPARE_KIND[pid])
            data = _slot_resolves(slot, slide)
            if data is None:
                warnings.append(f"slide {sid}: piece '{pid}' 슬롯 데이터 미해석(R2 — 렌더에서 제외됨)")
                continue
            filled += 1
            missing = [k for k in pdef.get("requires", []) if data.get(k) in (None, "", [], {})]
            if missing:
                warnings.append(f"slide {sid}: '{pid}' 필수 필드 누락 {missing} — 렌더가 검토요망 표면화")
        if len(kinds) > 1:
            warnings.append(f"slide {sid}: 비교 유형 혼합 {sorted(kinds)} (R1 위반 — 한 장 한 유형)")
        if filled == 0:
            warnings.append(f"slide {sid}: 유효 슬롯 0 (R2 — 전면 검토요망으로 렌더됨)")
        group = ent.get("layout_group")
        if group:
            group_frames.setdefault(group, set())
            if frame_id not in group_frames[group] and group_frames[group] and not ent.get("variation_reason"):
                warnings.append(
                    f"slide {sid}: layout_group '{group}' 내 frame 변주({sorted(group_frames[group])[0]}→{frame_id})에 "
                    "variation_reason 없음 (R9 — 무사유 변주=AI티 신호)"
                )
            group_frames[group].add(frame_id)
        for g in ent.get("catalog_gap") or []:
            gaps.append({"slide_id": sid, "wanted": g})

    stats = {
        "slides_in_wireframe": len(wf["slides"]),
        "slides_in_deck": len(deck_by_id),
        "frames_used": sorted(frames_used),
        "pieces_used": sorted(pieces_used),
        "presets_used": sorted(presets_used),
        "unique_combos": len(combos),
        "layout_groups": {g: sorted(f) for g, f in group_frames.items()},
    }
    return {"errors": errors, "warnings": warnings, "stats": stats, "catalog_gap": gaps}


_MERGE_KEYS = ("frame", "preset", "rendition", "layout_group", "variation_reason", "slots", "message_type", "principles")


def merge_into_deck(deck: dict, wf: dict) -> int:
    """wireframe 결정을 deck.json 슬라이드에 병합(template_id는 provenance로 보존). 반환=적용 장수."""
    deck_by_id = {str(s.get("slide_id")): s for s in deck.get("slides", [])}
    applied = 0
    for ent in wf.get("slides", []):
        slide = deck_by_id.get(str(ent.get("slide_id")))
        if slide is None:
            continue
        for k in _MERGE_KEYS:
            if ent.get(k) is not None:
                slide[k] = ent[k]
        slide["wireframe_selected_by"] = wf.get("selected_by")
        applied += 1
    return applied


def gating_block(wf: dict, validation: dict) -> dict:
    """gating_report['wireframe'] 블록 — 장별 결정과 위반·갭을 표면화(감추지 않음)."""
    wf_slides = [ent for ent in wf.get("slides", []) if isinstance(ent, dict)]
    cards: set[str] = set()
    slides_with_cards = 0
    for ent in wf_slides:
        raw = ent.get("knowledge_cards")
        if not isinstance(raw, list):
            continue
        cited = {card.strip() for card in raw if isinstance(card, str) and card.strip()}
        if cited:
            slides_with_cards += 1
            cards.update(cited)
    return {
        "schema_version": 1,
        "selected_by": wf.get("selected_by"),
        "stats": validation.get("stats") or {},
        "rule_warnings": validation.get("warnings") or [],
        "catalog_gap": validation.get("catalog_gap") or [],
        "applied_knowledge": {
            "cards": sorted(cards),
            "slides_with_cards": slides_with_cards,
            "slides_total": len(wf_slides),
        },
        "slides": [
            {"slide_id": str(e.get("slide_id")), "message_type": e.get("message_type"),
             "frame": e.get("frame"), "rendition": e.get("rendition") or "boxed",
             "layout_group": e.get("layout_group"), "variation_reason": e.get("variation_reason"),
             "pieces": [s.get("piece") for s in (e.get("slots") or []) if isinstance(s, dict)],
             "principles": e.get("principles") or []}
            for e in wf.get("slides", [])
        ],
    }


# --- 결정기 프롬프트 번들 ------------------------------------------------------

def _vocab_summary() -> str:
    contracts = _compose()._contracts()
    lines = ["### frame (골격 — 콘텐츠 영역 슬롯 분할)"]
    for f in contracts["frames"].values():
        lines.append(f"- `{f['id']}`: {f.get('label', '')} — {f.get('use', '')}")
    lines.append("")
    lines.append("### piece (조각 — 원전 원칙의 원자 표현. source가 결정 근거다)")
    for p in contracts["pieces"].values():
        req = ", ".join(p.get("requires", []))
        lines.append(f"- `{p['id']}` [{p.get('group', '')}] requires({req}) — {p.get('source', '')}")
    return "\n".join(lines)


def _preset_summary() -> str:
    contracts = _compose()._contracts()
    lines = ["### preset (의무 규범 조합 — 그대로 쓰거나 해체 가능, 특권 없음)"]
    for p in contracts.get("presets", {}).values():
        lines.append(f"- `{p['id']}` [{p.get('frame', '')}]: {p.get('label', '')} — {p.get('source', '')}")
    return "\n".join(lines)


def _rules_summary() -> str:
    pieces_path = _compose()._CONTRACT_DIR / "pieces.json"
    rules = json.loads(pieces_path.read_text(encoding="utf-8")).get("rules", {})
    return "\n".join(f"- **{k}**: {v}" for k, v in rules.items())


_SCHEMA_EXAMPLE = """{
  "schema_version": 1,
  "selected_by": "llm:<모델/세션 식별을 여기에>",
  "knowledge_used": {"cards": ["반영한 지식 카드 슬러그", "..."],
                      "web": [{"url": "https://...", "purpose": "용도 한 줄"}]},
  "slides": [
    {"slide_id": "7", "message_type": "비교",
     "frame": "split_v", "rendition": "boxed",
     "layout_group": "axis1-evidence", "variation_reason": null,
     "slots": [
       {"piece": "before_after", "size": "half",
        "data": {"metrics": ["지표"], "before": ["45"], "after": ["80"]}},
       {"piece": "text_block", "size": "half", "binds": "interpretation"}
     ],
     "principles": ["2-5"], "knowledge_cards": ["<카드 name>"],
     "notes": null, "catalog_gap": []}
  ]
}"""


def build_prompt(deck: dict, message_map: "dict | None" = None, *,
                  run: "str | None" = None, profile: "str | None" = None) -> str:
    """결정기(LLM)에게 줄 자기완결 프롬프트 — 동결 내용 + 어휘 + 규칙 + 스키마.

    `run`(ε패킷, 2026-07-23): 넘기면 knowledge_ledger의 pull 지시+보고 의무(안전장치①)를
    말미에 동봉한다. 이 δ패킷 지식 카드 색인(`_knowledge_card_index`, 결정론 자동 주입)과는
    별개 층이다 — δ는 "카드 색인을 항상 보여준다", ε는 "vault를 능동 조회하라는 지시 + 무엇을
    썼는지 보고하라는 의무"다. `run`을 안 넘기면(기존 단위 테스트 호출부) 기존 프롬프트와
    바이트 동일(하위호환).
    """
    parts = [
        "# 와이어프레임 결정 — [3] 장 수준 형태 결정 (무채·내용 불변)",
        "",
        "너는 와이어프레임 결정기다. 아래 **동결된 내용**을 읽고 장별 메시지 유형",
        "(수치/비교/구조/성과/서사)을 판별한 뒤, 원전 표현원칙(각 piece의 source)에 따라",
        "frame×piece를 결정해 wireframe.json을 작성하라.",
        "",
        "## 절대 규칙",
        "- **내용을 바꾸지 마라.** 텍스트·수치의 생성·삭제·수정 금지 — binds로 기존 필드를",
        "  가리키거나, 기존 필드 값을 재배열한 data만 허용(요약·창작 금지).",
        "- 형태 선택의 근거는 **메시지 유형→원전 원칙**이다. 하우스 관행이 아니다.",
        "- 원하는 형태가 어휘에 없으면 **지어내지 말고 catalog_gap에 선언**하라.",
        "- 같은 역할 그룹은 layout_group으로 묶고 같은 frame을 써라. 의도적 변주만",
        "  variation_reason과 함께 허용(R9).",
        "- AI티(장식·정렬)는 네 소관이 아니다 — [4] 테마 공정 몫. 너는 형태 선택만 한다.",
        "- 장별 frame×piece 결정에 적용한 카드를 `knowledge_cards`로 인용하라(적용 없으면 생략).",
        "  원칙과 어긋난 결정은 그 이유를 notes에 남겨라.",
        "",
        "## 조합 규칙 (검증기가 표면화한다)",
        _rules_summary(),
        "",
        "## 어휘 (이 밖의 frame/piece id는 계약 위반)",
        _vocab_summary(),
        "",
        _preset_summary(),
        "",
        _knowledge_card_index(),
        "",
        "## 출력 스키마 (wireframe.json — run 루트에 저장)",
        "```json", _SCHEMA_EXAMPLE, "```",
        "",
        "## 동결된 내용 (deck.json 발췌 — slide_id·role·title·key_message·fields)",
    ]
    for s in deck.get("slides", []):
        parts.append(f"### slide {s.get('slide_id')} — role={s.get('role')} · 현행 template={s.get('template_id')}")
        parts.append(f"제목: {s.get('title')}")
        if s.get("key_message"):
            parts.append(f"키메시지: {s.get('key_message')}")
        parts.append("fields:")
        parts.append("```json")
        parts.append(json.dumps(s.get("fields") or {}, ensure_ascii=False, indent=1))
        parts.append("```")
        # W31 R9(리허설 마찰17): A5(내용 동결)에서 확정한 디자인 강조(emphasis=hero) 장은
        # hero 계열 골격(hero_body 등, 어휘에 있으면)을 권장한다 — 최종 선택은 여전히 결정기
        # 몫(강제 아님). emphasis 없는 장은 이 줄 자체가 없어 기존 프롬프트와 바이트 동일.
        if s.get("emphasis") == "hero":
            parts.append(
                "**디자인 강조(emphasis=hero) 장** — hero_body 등 강조 계열 골격을 권장한다"
                "(A5에서 사람이 확정한 구조 결정, 축B — 밋밋 보완과 다르다)."
            )
        # W32 마찰36: 스토리라인이 남긴 형태 의도(form_intent)는 권장 입력이다 — 원전 원칙과
        # 대조해 판단하고, 근거 없이 그대로 베끼지 않는다(결정기의 독립 판단이 정본. 그대로
        # 복사가 관찰되면 되돌림 기준 '오염 신호'다). 없는 장은 이 줄 자체가 없어 기존
        # 프롬프트와 바이트 동일(emphasis 훅과 같은 방식).
        if s.get("form_intent"):
            parts.append(
                f"형태 의도(form_intent — 스토리라인 작성자/생성기 기입): {s['form_intent']} "
                "— 원전 원칙과 대조해 판단하라(권장이지 강제가 아님. 근거 없이 그대로 베끼지 말 것)."
            )
    if message_map:
        parts += ["", "## message_map (전략 축 — layout_group 힌트)",
                  "```json", json.dumps(message_map, ensure_ascii=False, indent=1), "```"]
    if run is not None:
        import sys as _sys
        scripts_dir = Path(__file__).resolve().parents[2] / "proposal_system" / "scripts"
        if str(scripts_dir) not in _sys.path:
            _sys.path.insert(0, str(scripts_dir))
        import knowledge_ledger  # sibling of proposal_pipeline — 지연 임포트(순환 방지)
        parts += ["", knowledge_ledger.handoff_block(run, "wireframe", profile)]
    return "\n".join(parts)
