# 큐레이션 라이브러리 — 디자인 준비 라인

미리 준비해둔 스타일 자산(스킨=색 토큰 · 가이드=디자인 규칙) 목록. **전부 선택 사항** — 아무것도 안 골라도 덱은 무채(core)로 나온다. `curate --list`가 이 표를 갱신한다.

- **창고보관** = design-assets/ 아래에 보관됨(체크아웃/싱크백 대상). `curate --register <id>`로 담는다.
- 원본이 사라진 자산은 ⚠️로 표면화(지어내지 않는다).

| 종류 | id | 원본 위치 | 창고보관 | 자기완결 | 출처/메모 |
|---|---|---|---|---|---|
| guide | DESIGN_SYSTEM | proposal_system/vendor/pj_pt/DESIGN_SYSTEM.md | — | - |  |
| guide | quartz_guide | _source/PT_DESIGN_extra/outputs/ppt_design_guide_예시스튜디오_ported/design_guide_ai.md | — | - | _source/PT_DESIGN_extra/outputs/ppt_design_guide_예시스튜디오_ported/manifest.json |
| guide | ppt_design_guide_경제형 | proposal_system/knowledge/design_guides/ppt_design_guide_경제형.md | — | - |  |
| skin | lecture-dark | skins/lecture-dark.json | — | 예 | <개발 원본 전용 경로> 덱 룩(#0c0e13 다크, Pretendard) 토큰화 |
| skin | quartz | skins/quartz.json | — | 예 | _source/pj_pt/_폰트교체본/예시스튜디오_제안_예시고객사_v2_폰트교체.pptx |
| skin | univ_sample | skins/univ_sample.json | — | 아니오 | https://www.univ_sample.ac.kr/univ_sample/intro/vision02.do |
