# -*- coding: utf-8 -*-
"""표준 시나리오 스켈레톤 — 탐색 루프의 시작 = 백지가 아니라 역제안 (W10).

설계 정본: CONTEXT/NORTHSTAR_REDESIGN.md §3.0(두 루프) + 신규 결정 4(2026-07-09).

역할: `start` 직후 스토리라인이 아직 없을 때, 시스템이 **표준 시나리오의 전 장표
세트를 더미(예시 라벨)로 즉시 렌더해 사용자에게 역제안**한다. 사용자는 완성 덱의
모양을 보고 구성을 빼고/고치고, 이후 LLM은 **확정된 구조를 채우는** 역할로 격하된다.

이 모듈은 결정론·0토큰이다 — 시나리오 JSON(기존 자산 조립: 패턴셋 목차 골격 +
core(중립 코어) 카탈로그 template_id + W9 예시 데이터 정책)을 storyline 스키마로 변환할
뿐 LLM을 호출하지 않는다.

시나리오는 `proposal_system/scenarios/*.json`에 두어 복수 시나리오 확장을 연다
(제안/피칭 등). 첫 시나리오 = `public_proposal`(공공 제안 표준 목차).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import message_map  # sibling — W16 메시지맵 종속(축별 조립). message_map은 skeleton을 임포트 안 함(무순환).

SCENARIOS_DIR = Path(__file__).resolve().parents[1] / "scenarios"
# W28(목표조정 2 완결, 2026-07-13): 기본=중립 코어 시나리오. 이전 기본(public_proposal)은
# 자체가 strategy_lib/_패턴.md 수주덱 채굴 골격에서 조립돼 "고민"(G1) 슬롯이 기본 경로에
# 그대로 노출됐다(W27은 skeleton.py 폴백만 중립화 — 시나리오가 level1을 선언하면 폴백은
# 무시돼 오염이 남았다). 채굴 골격은 --scenario public_proposal 명시 시만(opt-in·레거시 재현).
DEFAULT_SCENARIO = "public_proposal_core"

# W9 예시 데이터 정책과 동일 태그 — adapt_storyline이 flag → review_needed로 옮기고,
# render가 "예시 데이터" 라벨을, ship이 잔존 경고를 자동으로 붙인다.
EXAMPLE_FLAG = "실데이터로 교체 필요"

# ---------------------------------------------------------------------------
# W16(결정 9①): 메시지맵 종속 축별 조립에 쓰는 상수
# ---------------------------------------------------------------------------

# 근거 슬롯 type → (카탈로그 template_id, section 어휘). v1 §4 유형(실적/데이터/체계/인력).
EVIDENCE_TEMPLATE = {
    "실적": ("portfolio_cases", "실적"),
    "데이터": ("data_interpretation", "데이터"),
    "체계": ("process_steps", "프로세스"),
    "인력": ("org_roles", "조직"),
}
_EVIDENCE_FALLBACK = ("data_interpretation", "데이터")

# W16(결정 9⑤): 분량 리듬 밴드(어절). 스토리/전략 장표는 얇게, 근거 장표는 두껍게 —
# 덱 전체 동적 범위 ≥3배 목표(v1 P4.6 확정: 실측 하위25% 44 / 상위25% 201어절 참고).
# **강제 아님** — 선언이며 gating_report가 실측·표면화한다(표면화 문법, 결정 7~8).
THIN_BAND = [20, 70]
THICK_BAND = [80, 220]

# W16(결정 9①④): 대목차 Level 1 고정 골격(RFP 작성요령 서식 — 협상 불가 의무 슬롯, SEED-2 §8.1).
# Ⅰ.제안개요(복창 의무) → Ⅱ.제안업체 일반 → Ⅲ.사업관리 →
# Ⅳ.사업내용(axis_groups 마커 — 내부는 축별 서사 자유 Level 2) → 마무리.
# 시나리오가 level1을 선언하면 그쪽이 우선, 없으면 이 기본 골격을 쓴다(항상 존재 보장).
#
# W27(목표조정 2, 2026-07-12 사용자 결정): 수주덱 채굴 지식(G계열)은 시스템이 기본 적용하지
# 않는다 — opt-in 자산. 경계(앵커 판단): P계열·RFP 작성요령 의무 서식(대목차 Ⅰ~Ⅳ 순서 자체
# 포함 — RFP 서식 의무로 판단해 코어 잔류)은 중립 코어에 남기고, G계열(G1 고민 오프닝·
# G6 성과관리 닫기 관성·G8 특장점 3분해)은 GSERIES_LEVEL1_OVERLAY로 옮겨 opt-in화한다.
# build_skeleton(house_knowledge="gseries")를 명시해야만 복원된다(기본 None=중립).
DEFAULT_LEVEL1: list[dict[str, Any]] = [
    # 문서 프레임 의무 슬롯 3종(D23 개정 2026-07-14): 표지·목차는 맨 앞, 끝인사는 맨 끝.
    # frame 마커가 붙은 슬롯은 대목차(agenda) 자동 조립에서 제외된다(자기 자신·프레임 비열거).
    {"section": "표지", "title": "[예시] 제안서 표지 — 사업명이 들어갈 자리",
     "message": "[예시] 제안을 관통하는 단일 컨셉 한 줄", "template_id": "cover_slide",
     "role": "cover", "frame": "cover", "length_band": THIN_BAND,
     "fields": {"project_title": "[예시] ○○기관 사업 제안", "concept_message": "[예시] 제안을 관통하는 단일 컨셉 한 줄"},
     "note": "문서 프레임 — 발주처가 처음 마주하는 표지(role=cover → 클라이언트 브랜드 마크 자리 자동 활성). 제안명=message_map/분석이 채움, 지어내기 0."},
    {"section": "목차", "title": "[예시] 목차", "template_id": "agenda",
     "role": "agenda", "frame": "agenda", "length_band": THIN_BAND,
     "note": "문서 프레임 — 대목차(Level 1) 섹션 제목 자동 조립(지어내기 0). items는 골격이 채운다."},
    {"section": "제안개요", "title": "[예시] Ⅰ. 제안 개요 — 사업 이해 복창", "template_id": "executive_summary",
     "role": "overview", "mandatory": True, "length_band": THIN_BAND,
     "note": "복창 의무 슬롯(RFP 작성요령 서식 — 협상 불가). 발주 요구를 우리 언어로 복창해 이해를 증명."},
    {"section": "제안업체", "title": "[예시] Ⅱ. 제안업체 일반현황·특장점", "template_id": "portfolio_cases",
     "role": "company", "length_band": THICK_BAND,
     "note": "제안업체 일반현황(RFP 의무 서식). Ⅱ.제안업체 일반 부문."},
    {"section": "사업관리", "title": "[예시] Ⅲ. 사업관리 — 추진조직·일정", "template_id": "org_roles",
     "role": "management", "length_band": THICK_BAND,
     "note": "추진조직·R&R·추진일정(실현가능성·사업관리 역량 증명, P5.4). Ⅲ.사업관리 부문."},
    {"axis_groups": True, "section": "사업내용",
     "note": "Ⅳ. 사업내용 — message_map 전략 축별 전략+근거(Level 2 서사 자유). 축이 여기에 조립된다."},
    {"section": "마무리", "title": "[예시] 마무리 — 이행 약속", "template_id": "process_steps",
     "role": "closing", "length_band": THIN_BAND,
     "note": "마무리 슬롯(중립). G6 성과관리 닫기 관성은 opt-in 오버레이로 이동(목표조정 2)."},
    {"section": "끝인사", "title": "감사합니다", "template_id": "closing_thanks",
     "role": "endcard", "frame": "closing", "length_band": THIN_BAND,
     "note": "문서 프레임 — 명시 끝인사(감사합니다 / End of document). G6 마무리 뒤 별도 슬롯(발표덱 관례). 정적 문구, 지어내기 0."},
]

# W27: G계열(수주덱 채굴 지식) opt-in 오버레이 — house_knowledge="gseries" 지정 시에만
# _build_axis_skeleton이 이 오버레이를 병합한다(고민 슬롯 삽입 + G6/G8 노트 복원).
# 지식 유실 금지(결정 근거): G1 원문은 이 리스트에, G6/G8 원문은 GSERIES_NOTE_OVERRIDES에 보존.
GSERIES_LEVEL1_OVERLAY: list[dict[str, Any]] = [
    {"section": "고민", "title": "[예시] 제안에 앞선 우리의 고민", "template_id": "problem_questions",
     "role": "opening", "length_band": THIN_BAND,
     "note": "G1 고민 오프닝 — 제안개요 복창 직전(물음표로 끝나는 고민 2~3개, 4/4 수주작 공통)."},
]

# G6(마무리)·G8(제안업체) 원 노트 — opt-in 시 해당 section의 note를 이걸로 교체(내용 복원).
GSERIES_NOTE_OVERRIDES: dict[str, str] = {
    "제안업체": "제안업체 일반현황(말미에 G8 특장점 3분해). Ⅱ.제안업체 일반 부문.",
    "마무리": "G6 — 성과관리·효과조사로 닫는 관성(closing_matrix 대체, 결정 9④).",
}


def _agenda_items(level1: list[dict[str, Any]]) -> list[str]:
    """대목차(agenda) 항목 = level1의 콘텐츠 섹션 제목 자동 조립(지어내기 0).

    문서 프레임 슬롯(frame 마커: 표지·목차·끝인사)은 제외한다 — 목차는 자기 자신과
    프레임을 열거하지 않는다. axis_groups 마커(사업내용)는 대목차 한 항목으로 포함.
    """
    items: list[str] = []
    for entry in level1:
        if entry.get("frame"):
            continue
        section = entry.get("section")
        if section:
            items.append(str(section))
    return items


def _apply_gseries_overlay(level1: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """house_knowledge="gseries" opt-in: 고민 슬롯을 제안개요 앞에 삽입 + G6/G8 노트 복원.

    W28: DEFAULT_LEVEL1뿐 아니라 **시나리오가 선언한 level1**에도 적용된다(선언 시나리오 위에
    얹기 — 안 그러면 opt-in 경로가 level1 선언 시나리오[신규 기본 public_proposal_core 포함]에서
    작동 불능해진다). 이미 "고민" section이 있는 level1(레거시 public_proposal.json처럼 자체
    G1을 declare한 경우)에는 중복 삽입하지 않는다 — 멱등.

    D23 개정(2026-07-14): 문서 프레임 슬롯(표지·목차)이 맨 앞에 오므로 고민(G1)은 프레임
    뒤·첫 콘텐츠 슬롯(제안개요) 앞에 삽입한다 — 표지·목차보다 뒤, 제안개요보다 앞."""
    has_gomin = any(e.get("section") == "고민" for e in level1)
    merged: list[dict[str, Any]] = []
    inserted = has_gomin
    for entry in level1:
        entry = dict(entry)
        if not inserted and not entry.get("frame"):
            merged.extend(dict(e) for e in GSERIES_LEVEL1_OVERLAY)
            inserted = True
        override = GSERIES_NOTE_OVERRIDES.get(entry.get("section"))
        if override:
            entry["note"] = override
        merged.append(entry)
    if not inserted:                       # 모두 프레임(비정상) — 말미에 부착
        merged.extend(dict(e) for e in GSERIES_LEVEL1_OVERLAY)
    return merged


class SkeletonError(ValueError):
    """시나리오 로드/변환 실패를 사용자 표면 오류로 승격."""


def available_scenarios() -> list[str]:
    if not SCENARIOS_DIR.is_dir():
        return []
    return sorted(p.stem for p in SCENARIOS_DIR.glob("*.json"))


def load_scenario(scenario_id: str | None) -> dict[str, Any]:
    sid = (scenario_id or DEFAULT_SCENARIO).strip()
    path = SCENARIOS_DIR / f"{sid}.json"
    if not path.is_file():
        raise SkeletonError(
            f"시나리오 없음: {sid} (등록: {available_scenarios() or '(없음)'}) — "
            f"{SCENARIOS_DIR} 에 <id>.json 추가"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SkeletonError(f"시나리오 JSON 파손: {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("slides"), list) or not data["slides"]:
        raise SkeletonError(f"시나리오 형식 오류: {path} (slides 배열 필요)")
    return data


def _example_fields_by_template(scenario: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """시나리오 slides에서 template_id → 예시 fields를 추출(결정론·기존 자산 재사용).

    축 조립 슬라이드가 이 예시 fields를 재사용해 카탈로그 required_fields를 충족한다 —
    빈 필드로 두면 canonical 게이트(schema_errors)가 더미 역제안을 막는다(W10 경로가
    예시 fields를 실은 것과 같은 이유). 새 발명 없음: public_proposal.json이 이미 갖고 있다.
    """
    out: dict[str, dict[str, Any]] = {}
    for item in scenario.get("slides", []):
        if not isinstance(item, dict):
            continue
        tid = item.get("template_id")
        fields = item.get("fields")
        if tid and isinstance(fields, dict) and tid not in out:
            out[tid] = fields
    return out


def _mk_axis_slide(
    n: int, section: str, title: str, message: str, template_id: str | None, *,
    band: list[int], fields: dict[str, Any] | None = None,
    supports_axis: str | None = None, note: str | None = None, mandatory: bool = False,
) -> dict[str, Any]:
    """축별 조립·Level 1 골격의 storyline 슬라이드 1장(전부 example — W10 승계).

    supports_axis(장표→메시지 추적성 · 결정 9①)와 length_band(분량 리듬 · 결정 9⑤)는
    adapt_storyline이 deck.json까지 운반한다(conditional key — 없으면 안 심어 바이트 보존).
    fields는 시나리오의 예시 fields를 재사용(required_fields 충족 — 게이트 통과).
    """
    slide: dict[str, Any] = {
        "n": n, "section": section, "title": title, "message": message,
        "bullets": [], "template_id": template_id,
        "example": True, "flag": [EXAMPLE_FLAG],
        "length_band": list(band),
    }
    if isinstance(fields, dict) and fields:
        slide["fields"] = json.loads(json.dumps(fields, ensure_ascii=False))  # 깊은 복사(공유 방지)
    if supports_axis:
        slide["supports_axis"] = supports_axis
    if mandatory:
        slide["mandatory"] = True   # 복창 의무 슬롯 표식(RFP 작성요령 서식)
    if note:
        slide["note"] = note        # adapt_storyline 무시(스키마 안전) · 핸드오프가 소비
    return slide


def _build_axis_skeleton(
    scenario: dict[str, Any], doc: dict[str, Any], *, project: str | None = None,
    house_knowledge: str | None = None,
) -> dict[str, Any]:
    """W16(결정 9①④): message_map 종속 — 시나리오 통짜가 아니라 **축별 장표 그룹**을 조립.

    대목차 Level 1 고정 골격(의무 슬롯) + Ⅳ.사업내용에 message_map 전략 축을 조립:
      각 축 message → 전략 장표(supports_axis) · evidence_slots → 근거 장표(type→template role).

    W28(수정): 시나리오가 level1을 직접 선언해도 house_knowledge="gseries"면 그 선언된 골격
    위에 G계열 오버레이(고민 슬롯 + G6/G8 노트)가 병합된다(W27에서는 선언 시나리오는 무조건
    무시돼 opt-in 경로가 level1 선언 시나리오에서 작동 불능이었다 — 신규 기본
    public_proposal_core가 level1을 선언하므로 이 조건을 고쳐야 opt-in이 살아난다).
    house_knowledge가 None이면(기본) 선언 여부와 무관하게 그대로 — 무변경 원칙 유지.
    """
    level1 = scenario.get("level1") or DEFAULT_LEVEL1
    if house_knowledge == "gseries":
        level1 = _apply_gseries_overlay(level1)
    ex_fields = _example_fields_by_template(scenario)
    ax = message_map.axes(doc)
    governing = message_map.governing_text(doc)
    slides: list[dict[str, Any]] = []
    n = 0
    for entry in level1:
        if entry.get("axis_groups"):
            # Ⅳ. 사업내용 — 메시지가 요구하는 것만 도출(장표는 축에 종속).
            section = entry.get("section", "사업내용")
            for i, a in enumerate(ax, 1):
                aid = a.get("id") or f"axis{i}"
                n += 1
                slides.append(_mk_axis_slide(
                    n, "전략", f"[예시][{aid}] {a.get('message', '전략 축')}",
                    a.get("message", ""), "strategy_pillars",
                    band=THIN_BAND, fields=ex_fields.get("strategy_pillars"),
                    supports_axis=aid,
                    note=f"전략 축 {aid} — Level 2 서사 자유(사업내용 부문 내부)."))
                for s in (a.get("evidence_slots") or []):
                    if not isinstance(s, dict):
                        continue
                    tid, sect = EVIDENCE_TEMPLATE.get(str(s.get("type")), _EVIDENCE_FALLBACK)
                    n += 1
                    status = s.get("status")
                    slides.append(_mk_axis_slide(
                        n, sect, f"[예시] {s.get('desc', '근거')}",
                        s.get("desc", ""), tid,
                        band=THICK_BAND, fields=ex_fields.get(tid),
                        supports_axis=aid,
                        note=f"근거[{s.get('type', '?')}/{status}] {section} — {s.get('desc', '')}"))
            continue
        n += 1
        role = entry.get("role")
        # 제안개요(복창 의무)는 governing_message를 복창 자리로 삼는다(사업 이해 증명).
        msg = entry.get("message") or (governing if role == "overview" else "")
        tid = entry.get("template_id")
        # 문서 프레임 슬롯(D23 개정)은 entry가 직접 선언한 fields를 쓴다(시나리오 예시 fields
        # 재사용 대신). 목차(agenda)는 대목차 섹션 제목을 자동 조립한다(지어내기 0).
        entry_fields = entry.get("fields")
        if entry.get("frame") == "agenda":
            entry_fields = {"items": _agenda_items(level1)}
        fields = entry_fields if entry_fields is not None else (ex_fields.get(tid) if tid else None)
        slides.append(_mk_axis_slide(
            n, entry.get("section", ""), entry.get("title", ""), msg, tid,
            band=entry.get("length_band", THIN_BAND),
            fields=fields,
            note=entry.get("note"), mandatory=bool(entry.get("mandatory")),
        ))

    proj = project or scenario.get("label") or scenario.get("id") or "제안 스켈레톤"
    return {
        "meta": {
            "project": str(proj),
            "scenario": scenario.get("id"),
            "skeleton": True,
            "message_driven": True,           # W16: 축 조립 경로임을 표식
            "governing_message": governing,
            # W31(리허설 마찰2): 조립 입력의 지문 — 상류 개정 후 stale 감지용(stale_reason).
            "message_map_fingerprint": message_map_fingerprint(doc),
        },
        "slides": slides,
    }


def build_skeleton(
    scenario: dict[str, Any], *, project: str | None = None,
    message_map_doc: dict[str, Any] | None = None,
    house_knowledge: str | None = None,
) -> dict[str, Any]:
    """시나리오 → storyline 스키마 더미 문서(전 장표 example=true).

    W16(결정 9①): `message_map_doc`이 있고 전략 축이 있으면 **축별 장표 그룹**을 조립한다
    (`_build_axis_skeleton`). 없으면 아래 기존 시나리오 경로 그대로 — W15 바이트 동일 원칙 승계.

    W27(목표조정 2): `house_knowledge="gseries"`를 명시해야만 수주덱 채굴 지식(G계열 —
    고민 오프닝·성과관리 닫기·특장점 3분해) 오버레이가 병합된다. 기본 None=중립 골격.

    각 슬라이드: n(연속)·section·title·message·bullets·template_id + 예시 fields.
    - example=true + flag=[EXAMPLE_FLAG] → W9 3중 안전장치가 자동 적용(라벨·태그·ship 경고).
    - note("왜 이 장표가 필요한가")는 storyline 슬라이드에 실어 둔다 — adapt_storyline은
      알려진 키만 읽으므로 렌더 덱에는 안 들어가고(스키마 안전), 채움 핸드오프 프롬프트가
      소비한다(구조 주입).
    """
    if message_map_doc is not None and message_map.axes(message_map_doc):
        return _build_axis_skeleton(
            scenario, message_map_doc, project=project, house_knowledge=house_knowledge
        )

    slides: list[dict[str, Any]] = []
    for i, item in enumerate(scenario["slides"], 1):
        if not isinstance(item, dict):
            raise SkeletonError(f"시나리오 slide {i}: 객체가 아니다")
        slide: dict[str, Any] = {
            "n": i,
            "section": item.get("section", ""),
            "title": item.get("title", ""),
            "message": item.get("message", ""),
            "bullets": list(item.get("bullets") or []),
            "template_id": item.get("template_id"),
            "example": True,
            "flag": [EXAMPLE_FLAG],
        }
        if isinstance(item.get("fields"), dict):
            slide["fields"] = item["fields"]
        if item.get("note"):
            slide["note"] = item["note"]  # adapt_storyline 무시(스키마 안전) · 프롬프트가 소비
        # W16(결정 9⑤): 시나리오가 분량 밴드를 선언했으면 실어 나른다(선언 없으면 키 미추가 —
        # 밴드 없는 기존 시나리오는 바이트 동일 유지). supports_axis는 축 조립 경로에서만 생긴다.
        band = item.get("length_band")
        if isinstance(band, list) and len(band) == 2:
            slide["length_band"] = list(band)
        slides.append(slide)

    proj = project or scenario.get("label") or scenario.get("id") or "제안 스켈레톤"
    return {
        "meta": {
            "project": str(proj),
            "scenario": scenario.get("id"),
            "skeleton": True,
        },
        "slides": slides,
    }


def message_map_fingerprint(message_map_doc: dict[str, Any] | None) -> str | None:
    """축 조립의 입력이 된 message_map의 지문(핵심 주장 + 축 id·메시지 + 근거 슬롯).

    W31(리허설 마찰2): 상류(message_map) 개정 후 하류(skeleton)가 낡는 것을 **감지**하기
    위한 값이다. 지문은 조립에 실제로 쓰이는 부분만 본다 — audience_note 같은 비조립
    필드를 고쳐도 "뼈대가 낡았다"고 시끄럽게 굴지 않기 위해서다.
    """
    if not message_map_doc:
        return None
    axes = message_map.axes(message_map_doc) or []
    payload = {
        "governing": (message_map_doc.get("governing_message") or "").strip(),
        "axes": [
            {
                "id": (a.get("id") or "").strip(),
                "message": (a.get("message") or "").strip(),
                "slots": [
                    {"type": (s.get("type") or "").strip(),
                     "desc": (s.get("desc") or "").strip(),
                     "status": (s.get("status") or "").strip()}
                    for s in (a.get("evidence_slots") or [])
                ],
            }
            for a in axes
        ],
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def stale_reason(run: Path) -> str | None:
    """스켈레톤이 현재 message_map보다 낡았으면 사유 1줄, 아니면 None.

    자동 재생성은 하지 않는다 — skeleton.json은 **사용자가 장표를 빼고 고치는 편집 UI**라
    말없이 덮어쓰면 사람의 편집을 파괴한다(결정 4). 감지해서 알리고, 재생성 여부는 사람이
    `go --redo-skeleton`으로 정한다.
    """
    skel = load_skeleton(run)
    if not skel:
        return None
    meta = skel.get("meta") or {}
    if not meta.get("message_driven"):
        return None  # 시나리오 통짜 경로 — message_map 종속이 아니다(레거시 침묵)
    doc = message_map.load(run)
    if doc is None:
        return None
    now = message_map_fingerprint(doc)
    was = meta.get("message_map_fingerprint")
    if was is None:
        # 지문 도입 이전에 만들어진 스켈레톤 — 낡았다고 단정할 근거가 없다(침묵).
        return None
    if now == was:
        return None
    return (
        "스켈레톤이 현재 message_map보다 낡았다 — 메시지맵을 고친 뒤 뼈대를 재조립하지 "
        "않았다(축·근거가 옛 메시지맵 기준). 사람 편집 보존 때문에 자동 재생성하지 않는다. "
        "재조립하려면 `go --redo-skeleton`(기존 skeleton.json은 .bak_redo로 보존), "
        "지금 구조를 유지하려면 그대로 진행하라."
    )


def skeleton_path(run: Path) -> Path:
    return Path(run) / "skeleton.json"


def write_skeleton(run: Path, skeleton: dict[str, Any]) -> Path:
    path = skeleton_path(run)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(skeleton, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_skeleton(run: Path) -> dict[str, Any] | None:
    path = skeleton_path(run)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def structure_block(skeleton: dict[str, Any]) -> str:
    """확정된 스켈레톤 구조를 채움 핸드오프 프롬프트에 주입할 텍스트 블록.

    사용자가 skeleton.json에서 뺀/바꾼 슬라이드가 그대로 반영된다(파일이 편집 UI).
    LLM은 이 구조(슬라이드 수·순서·섹션·template_id)를 유지하고 예시 데이터를 입력
    문서의 실제 사실로 교체한다 — 백지 창작이 아니라 구조 채우기.
    """
    lines: list[str] = [
        "[확정된 스켈레톤 구조 — 이 구성을 채우세요]",
        "아래는 사용자가 검토·확정한 제안 덱의 뼈대입니다. 지켜야 할 규칙:",
        "1) 슬라이드 수·순서·section·template_id를 유지합니다(사용자가 이미 뺄/바꿀 장표를 정했습니다).",
        "2) 각 슬라이드의 예시(example) 데이터를 입력 문서의 **실제 사실**로 교체합니다.",
        "   근거가 없으면 창작하지 말고 flag(\"확인 필요\")로 남기거나, 구조가 핵심인 슬라이드는",
        "   example=true를 유지한 채 데모 데이터로 두세요(W9 예시 데이터 정책).",
        "3) note는 '이 장표가 왜 필요한가'입니다 — 내용을 채울 때 그 의도를 만족시키세요.",
        "",
    ]
    # W16(결정 9①⑤): 장표별 supports_axis(장표→메시지 추적성)와 분량 밴드를 계약에 실어
    # 채움 핸드오프가 축 배정·리듬을 유지하게 한다(새 블록 없이 이 블록을 확장 — 결정 9⑤).
    driven = bool((skeleton.get("meta") or {}).get("message_driven"))
    if driven:
        lines.append(
            "※ 이 스켈레톤은 message_map에 종속해 축별로 조립됐습니다 — 각 슬라이드의 "
            "supports_axis(지지 축)와 분량 밴드를 유지하세요(장표는 메시지가 요구하는 것만)."
        )
        lines.append("")
    for s in skeleton.get("slides", []):
        n = s.get("n")
        section = s.get("section", "")
        title = s.get("title", "")
        tid = s.get("template_id") or "(자동배정)"
        axis = s.get("supports_axis")
        axis_tag = f" · 지지축={axis}" if axis else ""
        mand = " · [복창 의무]" if s.get("mandatory") else ""
        band = s.get("length_band")
        band_tag = f" · 분량밴드 {band[0]}~{band[1]}어절" if isinstance(band, list) and len(band) == 2 else ""
        lines.append(
            f"- 슬라이드 {n} · [{section}]{axis_tag}{mand}{band_tag} · template_id={tid} · 제목자리: {title}"
        )
        note = s.get("note")
        if note:
            lines.append(f"    └ 왜 필요한가: {note}")
    return "\n".join(lines)
