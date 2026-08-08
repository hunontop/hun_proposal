# -*- coding: utf-8 -*-
"""W15 message_map — `run/message_map.json` (메시지 우선 공정의 1급 산출물).

NORTHSTAR_REDESIGN §6 결정 9-①③ + PLANNING_SEED_v1 확정 원칙.

message_map은 RFP 분석과 스토리라인 **사이**에 서는 내용의 결정 게이트 산출물이다
(design_brief가 디자인의 결정 게이트 산출물인 것과 대칭 — 둘은 공존한다. 내용=map/디자인=brief).

  핵심 주장 1(governing_message) + 전략 축 2~4(strategy_axes) + 축별 근거 슬롯.

**결정론·0토큰.** 이 모듈은 LLM을 호출하지 않는다 — 핸드오프 프롬프트를 조립하고
수거된 JSON을 스키마 검증할 뿐이다. LLM 산출(핸드오프)은 go가 멈추는 지점이다(D4).

검증 철학(결정 7~8): 구조 위반(governing 0/2+)만 **차단**, 나머지는 **표면화**(경고).
확정 원칙(실덱 4/4~3/3)만 규칙으로 승격한다 — 조건부·미검증은 프롬프트 지시로만 싣는다(결정 9③).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MAP_NAME = "message_map.json"

# v1 §4 근거 유형. 데이터·실적·체계는 필수(P4.1), 인력은 실현가능성 증명(P5.4). 비교·성과는 조건부라 제외.
EVIDENCE_TYPES = ("실적", "데이터", "체계", "인력")
SLOT_STATUS = ("empty", "example", "filled")

AXIS_MIN, AXIS_MAX = 2, 4                 # P2.3 정정(3~5 → 2~4), house_a 승
SUBJECT_BAD = ("제안사", "자사", "당사")   # P2.1 주어 검사(기계 검사 불가 — 문자열 힌트만)


# ---------------------------------------------------------------------------
# 로드 / 경로
# ---------------------------------------------------------------------------

def map_path(run: Path) -> Path:
    return Path(run) / MAP_NAME


def prompt_path(run: Path) -> Path:
    return Path(run) / "message_map" / "message_map_prompt.md"


def exists(run: Path) -> bool:
    return map_path(run).is_file()


def load(run: Path) -> dict[str, Any] | None:
    p = map_path(run)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------------------
# 접근자
# ---------------------------------------------------------------------------

def _governing_list(doc: dict[str, Any]) -> list[str]:
    """governing_message를 문자열 리스트로 정규화(문자열=1개, 리스트=길이, 빈값=0)."""
    gm = (doc or {}).get("governing_message")
    if gm is None:
        return []
    if isinstance(gm, str):
        return [gm] if gm.strip() else []
    if isinstance(gm, list):
        return [str(x) for x in gm if str(x).strip()]
    return [str(gm)] if str(gm).strip() else []


def governing_text(doc: dict[str, Any]) -> str:
    return " / ".join(_governing_list(doc))


def axes(doc: dict[str, Any]) -> list[dict[str, Any]]:
    a = (doc or {}).get("strategy_axes")
    return [x for x in a if isinstance(x, dict)] if isinstance(a, list) else []


def _all_slots(doc: dict[str, Any]) -> list[tuple[Any, dict[str, Any]]]:
    out: list[tuple[Any, dict[str, Any]]] = []
    for a in axes(doc):
        for s in (a.get("evidence_slots") or []):
            if isinstance(s, dict):
                out.append((a.get("id"), s))
    return out


def slot_counts(doc: dict[str, Any]) -> dict[str, int]:
    counts = {k: 0 for k in SLOT_STATUS}
    for _, s in _all_slots(doc):
        st = s.get("status")
        if st in counts:
            counts[st] += 1
    return counts


def empty_slots(doc: dict[str, Any]) -> list[tuple[Any, dict[str, Any]]]:
    return [(aid, s) for aid, s in _all_slots(doc) if s.get("status") == "empty"]


# ---------------------------------------------------------------------------
# 검증 (결정 7~8 문법: 구조 위반만 차단, 나머지는 표면화)
# ---------------------------------------------------------------------------

def validate(doc: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(errors, warnings) — errors는 차단(구조 위반), warnings는 표면화(경고 1급).

    - governing_message가 정확히 1개가 아니면 **오류**(P2.2 — 영역마다 핵심은 1개, 구조 위반).
    - 축 개수가 2~4 밖이면 **경고**(P2.3).
    - governing_message에 제안사/자사/당사가 보이면 **경고**(P2.1 — 주어=발주처/수혜집단).
    - 축에 근거 슬롯이 없으면 **경고**(계약: 축별 1개 이상).
    """
    errors: list[str] = []
    warnings: list[str] = []

    gl = _governing_list(doc)
    if len(gl) != 1:
        errors.append(
            f"governing_message는 정확히 1개여야 한다(현재 {len(gl)}개) — "
            "영역마다 핵심은 1개다(P2.2 확정원칙). 구조 위반이라 차단한다."
        )

    ax = axes(doc)
    n = len(ax)
    if n < AXIS_MIN or n > AXIS_MAX:
        warnings.append(
            f"전략 축 {n}개 — 권장 범위는 {AXIS_MIN}~{AXIS_MAX}(P2.3, house_a 승). 확인 필요."
        )

    gt = governing_text(doc)
    hit = [w for w in SUBJECT_BAD if w in gt]
    if hit:
        warnings.append(
            f"핵심 주장에 '{', '.join(hit)}'가 보인다 — 주장은 '너의 무엇을 위한 나의 무엇'"
            "(주어=발주처/수혜집단, P2.1). 제안사명을 지워도 성립하는지 확인 필요."
        )

    for i, a in enumerate(ax, 1):
        slots = a.get("evidence_slots") or []
        if not (isinstance(slots, list) and any(isinstance(s, dict) for s in slots)):
            warnings.append(f"축 '{a.get('id') or i}'에 근거 슬롯이 없다 — 축마다 1개 이상(계약).")

    return errors, warnings


def gating_block(doc: dict[str, Any]) -> dict[str, Any]:
    """gating_report에 실을 실측 블록(자기보고 아님 — map을 다시 세서 계산)."""
    return {
        "axes": len(axes(doc)),
        "slots": slot_counts(doc),
        "governing_ok": len(_governing_list(doc)) == 1,
    }


# ---------------------------------------------------------------------------
# 표면 (프롬프트 주입 / 게이트 표시 공용)
# ---------------------------------------------------------------------------

def render_for_prompt(doc: dict[str, Any]) -> str:
    """storyline 프롬프트 주입 + status/go 게이트 표시 공용 요약."""
    lines = [f"- 핵심 주장(governing): {governing_text(doc) or '(없음)'}"]
    for i, a in enumerate(axes(doc), 1):
        aid = a.get("id") or f"axis{i}"
        lines.append(f"- 전략 축 [{aid}]: {a.get('message', '')}")
        for s in (a.get("evidence_slots") or []):
            if isinstance(s, dict):
                lines.append(
                    f"    · 근거[{s.get('type', '?')}/{s.get('status', '?')}]: {s.get('desc', '')}"
                )
    note = doc.get("audience_note")
    if note:
        lines.append(f"- 청중(심사위원) 관점: {note}")
    return "\n".join(lines)


def summary(doc: dict[str, Any]) -> str:
    block = gating_block(doc)
    s = block["slots"]
    return (
        f"governing_ok={block['governing_ok']} axes={block['axes']} "
        f"slots={{filled:{s['filled']}, example:{s['example']}, empty:{s['empty']}}}"
    )


# ---------------------------------------------------------------------------
# KC 패킷 ① — 기획 입구 지식 체크 (2026-07-24 확정, 단계 전환 1회 발동)
# ---------------------------------------------------------------------------

def knowledge_pull_text(run: "Path | str", profile: str | None) -> str | None:
    """KC 패킷① 기획 입구 지식 체크 → ε패킷(2026-07-23)에서 config 표 소비로 일반화.

    ε패킷 이전에는 이 함수가 `ref/기획지식/`·`ref/경험설계지식/` 경로 문구를 하드코딩했다
    (vault 재편 전 경로 — 지금은 `ref/기획지식/메시지설계/`·`ref/기획지식/경험설계/`로 이동).
    이제는 `pipeline.config.json`의 `knowledge_stages.message_map` 표를 읽는
    `knowledge_ledger.handoff_block`에 위임한다 — 새 지식 도메인 추가가 코드 수정이 아니라
    vault 폴더 + config 한 줄이 되도록.

    반환값은 이제 **None을 반환하지 않는다**(안전장치① — 보고 의무는 profile과 무관하게 항상
    동봉돼야 한다, 2026-07-23 사용자 확정: "자동 모드에서도 보고 없이 진행 금지"). express
    프로파일은 "vault를 조회하라"는 pull 넛지만 생략하고, knowledge_used 보고 의무 문구는
    그대로 남는다 — KC 패킷 시절의 "express는 완전히 생략" 동작에서 바뀐 지점(호출부·테스트
    갱신 필요).
    """
    import knowledge_ledger  # sibling, 지연 임포트(순환 방지 — 이 리포 전역 관례)

    return knowledge_ledger.handoff_block(run, "message_map", profile)


# ---------------------------------------------------------------------------
# 핸드오프 프롬프트 (LLM이 message_map.json을 만든다 — go는 여기서 멈춘다)
# ---------------------------------------------------------------------------

_SCHEMA_BLOCK = """[message_map.json 스키마 — 정확히 이 키만 사용, JSON 객체 하나만 출력]
{
  "governing_message": "핵심 주장 1문장",       // 정확히 1개(P2.2)
  "strategy_axes": [                             // 2~4개(P2.3), 상호 배타적
    {"id": "axis1", "message": "하위 메시지 1문장",
     "evidence_slots": [                         // 축마다 1개 이상
       {"type": "실적|데이터|체계|인력", "desc": "근거 설명",
        "status": "empty|example|filled", "source": null 또는 "출처 문자열"}
     ]}
  ],
  "audience_note": "심사위원 관점 1줄(선택)",
  "knowledge_used": {                            // ε패킷 안전장치①(2026-07-23) — 생략 금지
    "cards": ["반영한 지식 카드 슬러그", "..."],  // 없으면 빈 배열 []
    "web": [{"url": "https://...", "purpose": "용도 한 줄"}]  // 없으면 빈 배열 []
  }
}"""

_PRINCIPLES_BLOCK = """[확정 기획 원칙 — 반드시 지킬 것 (PLANNING_SEED_v1 확정 원칙)]
- P2.2 영역마다 핵심은 **정확히 1개**다 — governing_message는 병렬 슬로건이 아니라 한 문장.
- P2.1 핵심 주장은 "**너의 무엇을 위한 나의 무엇**"으로 쓴다 — 주어는 **발주처/수혜집단**이며
  제안사명(자사·당사·제안사)을 지워도 성립해야 한다. 표지가 아니라 전략 층위의 주장이다.
- P2.3 하위 메시지(전략 축)는 **2~4개**, 상호 배타적으로 나눈다.
- P1.3 발주처의 숨은 관심사는 문서 밖(발주기관 공개문서)에서 수집해 도입에 직인용한다.
- P1.4 결과 진술을 **원인 또는 간극**으로 변환한다(진단).
- P1.5 5Why로 발주처의 진짜 why(왜 지금·왜 여기·왜 이것)에 도달한다.
  → 도입~진단(P1.3~1.5) 3종은 축의 근거 슬롯 desc에 힌트로 반영하라.
- P4.1 근거 유형: **데이터·실적·체계는 필수**, 인력은 실현가능성 증명(P5.4). 비교·성과는 조건부.
- 창작 금지: 근거가 없으면 status=empty로 두고 지어내지 마라
  (status=example은 '예시임을 명시'할 때만, status=filled는 실근거가 있을 때만)."""


def build_handoff_prompt(
    *, source_sections: str, skeleton_block: str | None = None,
    institution_research_block: str | None = None,
    company_profile_block: str | None = None,
    master_design_block: str | None = None,
    knowledge_pull_block: str | None = None,
) -> str:
    """message_map 생성 핸드오프. `source_sections`(브리프/공고)만 입구별로 다르다.

    `institution_research_block`(W26): institution_research.json이 있으면 직인용 훅
    요약을 동봉한다(P1.3 — 문서 밖 근거). 없으면 None(기존 프롬프트와 바이트 동일).
    `company_profile_block`(W31 리허설 마찰6): 회사가 선택돼 있으면 제안사(자사) 프로필
    요약을 동봉한다(핵심 주장·전략 축 설계에 자사 강점을 반영). 없으면 None(바이트 동일).
    `master_design_block`(W31 R10 v2 — 디자인 선행 루트): 마스터 시안이 먼저 확정돼
    있으면 확정 룩·밀도 요약을 동봉한다(같은 문법 — 없으면 None, 바이트 동일).
    `knowledge_pull_block`(KC 패킷 ①, 2026-07-24 확정): `knowledge_pull_text(profile)`이
    만든 경험설계지식·기획지식 pull 요구 문구. express 프로파일이면 호출부가 None을
    넘겨 생략한다(바이트 동일).
    """
    skeleton_section = f"\n{skeleton_block}\n" if skeleton_block else ""
    institution_section = f"\n{institution_research_block}\n" if institution_research_block else ""
    company_section = f"\n{company_profile_block}\n" if company_profile_block else ""
    master_design_section = f"\n{master_design_block}\n" if master_design_block else ""
    knowledge_pull_section = f"\n{knowledge_pull_block}\n" if knowledge_pull_block else ""
    return f"""당신은 제안 기획의 메시지 설계자입니다.
아래 입력만 사용해 message_map.json 하나를 작성하세요. 설명·마크다운 코드펜스·JSON 바깥
텍스트는 금지합니다 — 최종 출력은 유효한 JSON 객체 하나뿐이어야 합니다.

{_PRINCIPLES_BLOCK}

{_SCHEMA_BLOCK}

{source_sections}
{institution_section}{company_section}{master_design_section}{skeleton_section}{knowledge_pull_section}"""
