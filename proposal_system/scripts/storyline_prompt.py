# -*- coding: utf-8 -*-
"""storyline 생성 프롬프트 조립 — 공용 부품 (N2).

원래 나라장터 전용으로 `dashboard/server.py`(`build_storyline_prompt`)에 있던
"분석카드 → storyline 프롬프트" 조립 로직을 어댑터 공통 부품으로 승격한 것.
나라장터(bid)는 이 부품의 한 구현이고, 범용 브리프 입구(N2, `start --brief`)는
또 다른 구현이다(NORTHSTAR_REDESIGN §1-C1 "나라장터는 어댑터의 한 구현").

이 모듈은 결정론·0토큰이다 — LLM을 호출하지 않고 프롬프트 텍스트만 조립한다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# 원문 그대로 이식(schema 자체는 입력 종류와 무관 — bid든 brief든 동일 storyline 계약을 만든다).
STORYLINE_SCHEMA_BLOCK = """[storyline 입력 스키마 — 정확히 이 키만 사용]
- 루트는 객체이며 meta·slides·knowledge_used 세 키를 포함합니다. meta.project는 공고명(또는 문서 제목)을 사용합니다.
- knowledge_used: (루트 키, ε패킷 안전장치① — 2026-07-23 확정, 생략 금지)
  {"cards": ["반영한 지식 카드 슬러그", ...], "web": [{"url": "https://...", "purpose": "용도 한 줄"}]}
  카드/웹을 하나도 안 썼으면 빈 배열로 명시하세요 — 필드 자체를 생략하면 수거 검증이 막습니다.
- 각 슬라이드(slides 원소)는 다음 키만 사용합니다(다른 키는 넣지 마세요):
  - n: 1부터 연속된 정수(슬라이드 번호, 필수)
  - section: 슬라이드 성격(예: 표지, 목차, 문제, 요약, 일정/로드맵, 프로세스, 비교, 조직, 전략, 데이터, 사례, 결론). 레이아웃 자동배정에 사용됩니다.
  - title: 제목
  - message: 핵심 메시지 한 줄
  - bullets: 본문 문자열 배열
  - flag: 확인이 필요한 항목 문자열 배열(근거 없는 수치·일정·인력·실적·고객명은 본문에 창작하지 말고 여기에 "확인 필요"로 기록)
  - example: (선택, boolean) 이 슬라이드의 fields가 **'예시'로 명시된 데모 데이터**임을 표시합니다(아래 예시 데이터 정책 참조). true면 렌더러가 "예시 데이터" 라벨을 얹고 파이프라인이 "실데이터로 교체 필요" 태그를 자동으로 답니다.
  - supports_axis: (선택) 이 슬라이드가 지지하는 message_map 전략 축의 id 문자열(예: "axis1"). 장표→메시지 추적성(결정 9①). 스켈레톤이 배정했으면 유지하세요.
  - length_band: (선택) [최소, 최대] 어절 밴드(분량 리듬 목표 · 결정 9⑤). 스켈레톤이 배정했으면 유지하세요 — **하드 제약입니다: 밴드 초과 금지.** 채운 내용이 밴드 상한을 넘을 것 같으면 문장을 줄이세요(불릿을 나누거나 요약하세요). 밴드 위반은 gating_report가 실측·표면화하지만, 표면화는 경고일 뿐 안전망이 아닙니다 — 실측 사례에서 밴드 3~4배 초과 장이 네 단계 뒤 이미지 생성에서 텍스트가 카드 밖으로 넘치는 실물 파손으로 이어졌습니다(W31 마찰22). 하한 밑으로 너무 얇아지는 것도 피하세요.
  - separate_budget: (선택) G5 별도예산/비예산 표기(실행 장표 한정). 예산 상한을 지키며 물량을 늘리는 공공 제안 협상 장치. **근거가 있을 때만** 채우세요(자동 창작 금지 — 사실 항목).
  - emphasis: (선택) "hero"만 사용합니다. 이 슬라이드가 디자인 강조(hero) 장으로 확정됐다는 표식입니다. **A5(내용 동결) 회의에서 사람이 확정했을 때만** 채우세요 — LLM이 스스로 새 강조 장을 지정하지 마세요. 시스템이 표지·간지(구획)·결론·핵심 전략 축 지지 장을 후보로 제안하면, 사람이 그중 실제로 강조할 장을 골라 이 필드를 남깁니다. 이미 채워져 있으면 재생성 시에도 그대로 유지하세요(스켈레톤이 배정한 supports_axis와 같은 취급).
  - form_intent: (선택) 이 장의 **형태 의도** 한 줄 — 내용의 관계(순차/병렬/대비/수렴/표/전면 강조 등)를 보고 적습니다(예: "3단계 순차 흐름", "좌우 대비", "핵심 수치 1개 전면", "2×2 매트릭스"). **사실 창작이 아니라 설계 의도이므로 직접 적어도 됩니다**(emphasis와 다른 성격 — 그쪽은 사람 전속). pull한 디자인지식(와이어프레임 카드)의 어휘로 근거를 세우세요. **적었으면 그에 맞는 template_id를 고르고 그 템플릿의 required_fields를 fields에 채우세요.** 뼈대(와이어프레임) 결정기가 이 의도를 원전 원칙과 대조해 최종 판단합니다(권장이지 강제가 아님).
  - art_note: (선택) 이 장의 **분위기·강조 의도** 한 줄(예: "따뜻한 톤으로 안심", "숫자가 주인공"). 색상값·폰트명 같은 결정값은 적지 마세요 — 룩의 최종 결정은 디자인 계약(B1) 몫이고, 이 메모는 이미지 프롬프트에 '의도 참고'로만 전달됩니다.
  - template_id: (선택) 위 카탈로그 id 중 하나. 생략하면 파이프라인이 section/제목으로 자동 배정합니다. 아래 fields를 채운다면 그 필드가 속한 카탈로그 템플릿 id를 여기에 명시해 정합을 맞추세요.
  - fields: (선택) 해당 template의 required_fields를 채운 구조화 객체. 표·타임라인·조직도 등 구조가 있는 슬라이드는 bullets 대신(또는 함께) 여기에 구조화해 담으면 렌더러가 꽉 찬 시각요소를 그립니다. 자주 쓰는 shape:
    · data_interpretation: {"metric":"지표 이름", "comparison":[{"label":"항목1","value":70}, {"label":"항목2","value":30}], "interpretation":["수치가 의미하는 바 한 줄", ...]} — comparison은 반드시 이 shape의 객체 배열이다("70% vs 30%" 같은 문자열 요약으로 넣지 말 것 — 렌더러가 차트를 못 그린다).
    · risk_dashboard: {"risks":[{"name":..,"severity":"높음|중간|낮음","mitigation":..}, ...], "severity":[...], "mitigations":[...]}
    · comparison_table: {"options":["안A","안B"], "criteria":[{"name":"기준","values":["A값","B값"]}, ...], "recommendation":"권고 한 줄"}
    · roadmap_gantt: {"time_units":["착수","..","완료"], "workstreams":[{"label":"업무","cells":[true,false,..]}, ...], "milestones":[{"time_unit":"완료","label":"최종보고"}, ...]}
    · org_roles: {"lead":{"name":"총괄","description":..}, "teams":[{"name":"팀","roles":["역할1","역할2"]}, ...]}
    · cover_cinematic: {"visual_subject":"표지 이미지 주제(문구)"}
    · portfolio_cases: {"cases":["사업명: 한 줄 설명", ...], "metrics":["지표: 값", ...], "client_safe_names":["공개 가능한 발주처명", ...]} — cases/metrics는 **"라벨: 설명" 형태의 문자열 배열**이다. `{"name":..,"description":..}` 같은 객체를 넣지 말 것(렌더러가 문자열을 기대한다).
    · agenda: {"items":[{"title":"목차 항목", "relief":"이 항목이 해소하는 상대의 우려"}, ...]} — relief는 선택(모르면 생략, 빈 문자열로 채우지 말 것).
  ※ shape가 위에 없는 template의 fields는 **문자열 또는 문자열 배열**을 기본으로 삼으세요. 위 예시에 객체 배열로 명시된 자리(comparison·risks·criteria·workstreams·teams 등)가 아니면 객체를 넣지 마세요 — 문자열 기대 자리에 객체가 들어오면 렌더러가 그것을 사람이 읽을 문자열로 접고 "fields shape 불일치" 경고를 남깁니다(원문 그대로 조판되지는 않지만, 의도한 구성은 깨집니다).
- ★ 창작 금지 원칙: fields의 모든 값은 **입력 문서에 실제 있는 사실**만 사용합니다. 점수·심각도·일정·인력·실적처럼 근거가 없는 값을 **사실인 것처럼** fields에 지어내는 것은 금지입니다.
- ★ 예시 데이터 정책(창작금지의 정교화): 그래프·시장조사·비교표처럼 구조가 핵심인 슬라이드는 비워 두지 말고 **예시임을 명시한 데모 데이터**를 깔아 구성을 보여주세요. 그때는 반드시 (1) 그 슬라이드에 `"example": true`를 세우고 (2) flag에 "실데이터로 교체 필요"를 기록합니다. 렌더러가 "예시 데이터" 라벨을 얹으므로 **예시를 사실처럼 표시하는 것은 여전히 금지**입니다. 예시로도 채울 근거가 전혀 없으면 종전처럼 flag에 "확인 필요"로 남기고 fields를 비웁니다.
- 입력 문서에 있는 사실만 단정합니다. 부족한 정보는 bullets에 지어내지 말고 flag로 처리합니다(예시 데이터는 위 정책대로 example=true로 명시).
- ★ 청중 계약: 분석카드의 **배점표·평가전략·경쟁분석** 절은 슬라이드 **구성·우선순위 판단에만** 사용하고, 그 내용을 슬라이드 콘텐츠로 옮기지 마세요. 이 덱을 받는 것은 **수신 기관(발주처)**이며, "가격 배점 20%" 같은 우리 측 내부 전략·점수 배분은 수신 기관 관점의 콘텐츠가 아닙니다(내부 전략 유출 금지). 슬라이드에는 수신 기관이 읽을 제안 내용만 담습니다.
- JSON 문법이 유효해야 하며 최종 출력은 JSON 객체 하나뿐이어야 합니다.
"""


def load_catalog(pack_dir: Path) -> list[dict[str, Any]]:
    templates = json.loads((pack_dir / "templates.json").read_text(encoding="utf-8"))
    return [
        {
            "id": item.get("id"),
            "required_fields": item.get("required_fields", []),
            "use_when": item.get("use_when", []),
        }
        for item in templates
        if isinstance(item, dict)
    ]


def render_prompt(
    *,
    intro: str,
    source_sections: str,
    pack: str,
    catalog: list[dict[str, Any]],
    skeleton_block: str | None = None,
    message_map_block: str | None = None,
    institution_research_block: str | None = None,
    company_profile_block: str | None = None,
    master_design_block: str | None = None,
    knowledge_block: str | None = None,
) -> str:
    """storyline 생성 프롬프트 조립.

    `intro`/`source_sections`만 어댑터별로 다르다(나라장터=공고메타+분석카드,
    brief=브리프 문서) — 카탈로그·스키마 블록은 공용.

    `skeleton_block`(W10): 역제안 확정 후 주입되는 '확정된 스켈레톤 구조'.
    `message_map_block`(W15): message_map을 스토리라인의 메시지 계약으로 주입(결정 9①·④).
    `institution_research_block`(W26): 기관 공개 조사(문서 밖 근거)의 직인용 훅 요약 —
    institution_research.json이 없으면 None(블록 자체가 없어 기존 프롬프트와 바이트 동일).
    `company_profile_block`(W31 리허설 마찰6): 제안사(자사) 프로필 요약(회사개요·특장점·
    수행실적·인력·조직) — 회사가 선택되지 않았으면 None(바이트 동일).
    `master_design_block`(W31 R10 v2 — 디자인 선행 루트): 마스터 시안이 먼저 확정돼 있으면
    확정 룩·밀도 요약(비표준 밀도는 밴드 조정 지침 1줄 포함) — 없으면 None(바이트 동일).
    `knowledge_block`(ε패킷, 2026-07-23): 지식 pull 지시 + knowledge_used 보고 의무
    (`knowledge_ledger.handoff_block`) — 호출부가 항상 넘기므로 실사용에서는 None이 아니다.
    전부 None이면 기존 프롬프트와 바이트 동일(기존 직접 투입 경로 무손상).
    """
    skeleton_section = f"\n{skeleton_block}\n" if skeleton_block else ""
    message_map_section = f"\n{message_map_block}\n" if message_map_block else ""
    institution_section = f"\n{institution_research_block}\n" if institution_research_block else ""
    company_section = f"\n{company_profile_block}\n" if company_profile_block else ""
    master_design_section = f"\n{master_design_block}\n" if master_design_block else ""
    knowledge_section = f"\n{knowledge_block}\n" if knowledge_block else ""
    return f"""{intro}

{source_sections}
{institution_section}{company_section}{master_design_section}{message_map_section}{skeleton_section}{knowledge_section}
[선택 pack]
{pack}

[사용 가능한 템플릿 카탈로그]
{json.dumps(catalog, ensure_ascii=False, indent=2)}

{STORYLINE_SCHEMA_BLOCK}"""
