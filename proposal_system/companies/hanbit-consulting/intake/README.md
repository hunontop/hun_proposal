# intake/

회사소개서·이력서·수주목록 같은 **비정형 원본**을 여기 드롭한다.

`python proposal_system/scripts/proposal_pipeline.py company --bundle --id <이 회사 id>` 가
이 폴더의 파일 목록 + 기존 profile.json 요약을 묶어 정형화 프롬프트를 만든다. 그 프롬프트를
LLM(또는 사람)에게 주면 profile.json 스키마에 맞는 병합 패치 JSON을 작성할 수 있다
(창작 금지 — 이 폴더의 문서에 없는 사실은 절대 만들지 않는다. 항목마다 source에 파일명을
남겨라). 결과를 저장한 뒤:

    python proposal_system/scripts/proposal_pipeline.py company --apply --id <id> --file <결과.json>

검증(스키마·출처 누락) 후 profile.json에 병합된다(덮어쓰기 아님 — 기존 항목은 보존·갱신).
