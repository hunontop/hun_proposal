# app/render/vendor — 외부에서 들여온 렌더 자산

## deck-stage.js

- **출처**: `<개발 원본 전용 경로>` (사용자 자산 · 2026-08-02 반입, 1,760줄)
- **쓰는 곳**: `app/render/viewer.py`가 읽어 **덱 HTML에 인라인**한다(파일 참조 아님).
- **왜 인라인인가**: 이 엔진의 덱 HTML은 자기완결 계약이다(외부 의존 0). `<script src=…>`로 두면
  `file://`에서 열 때 별도 서버가 필요해지는데, 인라인하면 더블클릭만으로 돈다 —
  **W32 실측(2026-08-02)**: `file://`에서 컴포넌트 등록·화면 맞춤·키보드 페이징·두 창
  동기화(BroadcastChannel/localStorage 양쪽)가 전부 동작함을 확인했다.
- **⚠️ 인라인 시 필수 처리**: 61행 주석에 `</script>`가 들어 있다. HTML 파서는 JS 주석을
  모르므로 그대로 넣으면 **스크립트가 거기서 끊긴다**. `viewer.py`가 `</script` → `<\/script`로
  치환한다(치환을 빼면 조용히 깨진다 — 실제로 한 번 밟은 함정이다).
- **수정 금지**: 이 파일은 원본 그대로 둔다. 동작을 바꿔야 하면 `viewer.py` 쪽에서 감싼다
  (원본을 고치면 상류와 갈라져 다음 반입 때 충돌한다).

기능 요약(원본 docstring 발췌): 키보드 내비(←/→·PgUp/PgDn·Space·Home/End·숫자키) · 고정
디자인 크기를 `transform: scale()`로 뷰포트에 맞춤(레터박스) · 활성 장만 표시하고 나머지는
`visibility:hidden`으로 **상태 보존**(비디오·입력값 유지) · 썸네일 레일 · 발표자 노트
(`<script type="application/json" id="speaker-notes">`) · `@media print`로 장당 1페이지 PDF ·
`slidechange` CustomEvent. `noscale` 속성은 1:1 렌더(PPTX/래스터라이즈용), `no-rail`은 레일 끔.
