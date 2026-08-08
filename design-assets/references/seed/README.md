# 시드 레퍼런스 (W31 β1, 마찰20)

사용자 취향 기준의 기본 레퍼런스 — 프로젝트에 맞게 교체·삭제 가능.

- `original_style_reference.png` — 카드형 인포그래픽 디자인 언어(구조·아이콘·카드 구성).
- `approved_quartz_reference.png` — 승인된 색상·시리즈 일관성(Quartz 스킨 계보).

원본: `<개발 원본 전용 경로>`(사용자가 처음 마음에 들었던 기준, 2026-07-21 확정).

## 조회 순서 (imagedeck bundle, 마찰20)

`imagedeck --bundle`은 장별 레퍼런스를 다음 순서로 찾는다 — **폴더 = 범위 선언**:

1. `run/imagedeck_refs/slides/<NN>/` — 그 장에만 적용.
2. `run/imagedeck_refs/global/` — 이 run 전체에 적용.
3. 여기(`design-assets/references/seed/`) — 위 두 곳이 모두 비어 있을 때만 쓰이는 기본값.

시드가 쓰이면 프롬프트에 "(기본값 — 교체 가능)"이 표기된다. 이 폴더 자체를 비우면(또는 시드
파일을 지우면) 레퍼런스가 하나도 없는 상태가 되어 프롬프트의 "Reference roles" 문단이 아예
빠지고, 크롬 이웃 브리핑(art direction)만으로 자립한다.
