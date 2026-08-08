# 조각(piece) 카탈로그 프리뷰 — 시각 사전

조각 렌더러 = 원전 표현원칙의 정제 도식. [4] 레퍼런스 지시·EXP-3 번들은 페이지 통짜 캡처가 아니라 이것과 crop 원형을 쓴다(레퍼런스 이미지가 책 페이지 통짜 캡처면 도식이 노이즈에 묻힌다 — 사용자 지적).

생성: `python tools/piece_catalog.py` (재실행 멱등, 기존 png 덮어쓰기). 픽스처=계약 requires 충족 최소 데이터(tools/piece_catalog.py의 PIECE_FIXTURES).

| id | group | 원전 source | 이미지 |
|---|---|---|---|
| big_number | 숫자 | 표현원칙 1-1, 1-3 (기획의_정석 p052·p054) | [big_number.png](./big_number.png) |
| stat_card | 숫자·성과 | 표현원칙 1-2(숫자 4종: 가성비/인원/시간/개수), 4-1(기대효과 6도구) (p053·p124~126) | [stat_card.png](./stat_card.png) |
| calc_arrow | 숫자 | 표현원칙 1-4 (p124) | [calc_arrow.png](./calc_arrow.png) |
| contrast_pair | 비교 | 표현원칙 2-1 (p056~058) | [contrast_pair.png](./contrast_pair.png) |
| compare_table | 비교 | 표현원칙 2-3, 2-4 (p059~062) · [[1등이-아니면-축을-바꾼다]](축 선정은 결정기 지침) | [compare_table.png](./compare_table.png) |
| before_after | 비교 | 표현원칙 2-5 (p124) | [before_after.png](./before_after.png) |
| loop_pair | 비교 | 표현원칙 2-5 (p124 — 정성 항목의 전vs후 대체) | [loop_pair.png](./loop_pair.png) |
| part_of_whole | 비교 | 표현원칙 2-2 구성(all vs part) (p056) | [part_of_whole.png](./part_of_whole.png) |
| flow_arrow | 비교 | 표현원칙 2-2 흐름(before vs after) (p056) | [flow_arrow.png](./flow_arrow.png) |
| matrix_2x2 | 구조 | 표현원칙 3-1 (p116) · ref_images/p116 | [matrix_2x2.png](./matrix_2x2.png) |
| connect_diagram | 구조 | 표현원칙 3-2 (p115~116) | [connect_diagram.png](./connect_diagram.png) |
| group_naming | 구조 | 표현원칙 3-3 (p113~121) | [group_naming.png](./group_naming.png) |
| analogy_hero | 비유 | 표현원칙 5-1 (p063~066) | [analogy_hero.png](./analogy_hero.png) |
| journey_flow | 구조 | [[구시렁은-흐름도로-그린다]] (p037~038) | [journey_flow.png](./journey_flow.png) |
| match_pairs | 구조 | [[문제와-제안을-1대1로-매칭한다]] (p040~042) | [match_pairs.png](./match_pairs.png) |
| claim_proof_split | 숫자·구조 | [[주장을-쪼개-각각을-숫자로-증명한다]] (p108) | [claim_proof_split.png](./claim_proof_split.png) |
| funnel_3layer | 숫자 | [[tam-sam-som]] (p088) | [funnel_3layer.png](./funnel_3layer.png) |
| chart | 공용 | 구현 어휘(원전 무표 — 숫자·비교 조각의 시각화 수단) | [chart.png](./chart.png) |
| text_block | 공용 | 구현 어휘 · 표현원칙 3-2 연동 | [text_block.png](./text_block.png) |
| image_evidence | 공용 | 구현 어휘 · 정직성 계약 | [image_evidence.png](./image_evidence.png) |
| quote | 공용·성과 | 표현원칙 4-1 도구④ 예상 반응(가상 게시글·해시태그·헤드라인) (p125) | [quote.png](./quote.png) |
| timeline_gantt | 의무 | RFP 작성요령 서식(추진일정 의무) | [timeline_gantt.png](./timeline_gantt.png) |
| org_table | 의무 | RFP 작성요령 서식(추진조직·R&R 의무, P5.4) | [org_table.png](./org_table.png) |
| case_card | 의무 | RFP 작성요령 서식(유사 실적 의무) | [case_card.png](./case_card.png) |
| agenda | 의무 | 장르 규범(대목차) · [[목차는-상대의-두려움-목록이다]] (p130) | [agenda.png](./agenda.png) |
| pillar_card | 구조 | 표현원칙 P2.3 메시지 위계(핵심 주장 1 + 하위 메시지 2~4, 하위마다 3WR) (CONTEXT/research/PLANNING_SEED_v1.md:74 · SEED_VALIDATION_v0) | [pillar_card.png](./pillar_card.png) |

총 26종 중 26종 성공, 0종 실패.

## 원전 도식 crop 원형 (공개판에서 제외)

원전 책 페이지에서 잘라낸 도판은 **출판물이라 이 공개 배포판에 동봉하지 않습니다.**
조각 프리뷰(위 표의 png)는 이 저장소의 렌더러가 직접 그린 것이라 그대로 있습니다.
crop 원형이 필요하면 직접 준비해 `catalog_previews/원전_원형/`에 두세요.
