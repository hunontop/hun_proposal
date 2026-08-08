# PPT 자동화 표준셋 — 버전 A

제안서 슬라이드를 코드로 생성하는 컴포넌트 라이브러리. **17개 슬라이드 유형 + 공통 헤더**를 두 가지 형태로 제공한다.

- **form B — python-pptx 빌더** ([`builders.py`](builders.py)): 실제 `.pptx` 슬라이드 생성. 새 제안서 조립용.
- **form D — React 컴포넌트** ([`react/`](react/)): 웹 화면용. 미리보기/웹 제안 도구용.

공유 디자인 토큰: [`spec.json`](spec.json) · 규격 문서: [`DESIGN_SYSTEM.md`](DESIGN_SYSTEM.md)

## 빠른 시작

### form B (PPTX 생성)
```bash
cd ppt_standard_setA
python builders.py            # _demo_setA.pptx 생성 (17유형 1장씩)
```
```python
from builders import new_deck, blank, cover, section_cover, contrast_diagram
prs = new_deck()
cover(blank(prs), title="프레젠테이션 제목", question="핵심 메시지 한 줄", client="조직명/작성자")
contrast_diagram(blank(prs), ("2","본론","섹션 제목"),
    "현재와 목표 — 방향 전환",
    ("현재 상태(As-Is)", "현재의 한계…"),
    ("목표 상태(To-Be)", "전환 후의 모습…"))
prs.save("제안서.pptx")
```
모든 빌더의 첫 인자는 슬라이드 객체, 콘텐츠 유형은 헤더 인자 `(챕터번호, 챕터명, 섹션명)`를 받는다(표지/목차/섹션표지 제외).

### form D (React)
```jsx
import { Cover, ContrastDiagram, ClosingMatrix } from "./react/components";

<ContrastDiagram
  header={{ chapterNo: "2", chapterName: "본론", section: "섹션 제목" }}
  title="현재와 목표 — 방향 전환"
  left={["현재 상태(As-Is)", "현재의 한계…"]}
  right={["목표 상태(To-Be)", "전환 후의 모습…"]} />
```
props는 빌더 인자와 1:1 대응. `tokens.js`의 `Slide` 프레임이 27.52:19.05 캔버스를 잡는다.

## 검증 상태
- form B: 17유형 전부 PowerPoint 렌더 확인 (`_render/s_1~17.png`). 네이비/오렌지 위계·레이아웃 일관.
- form D: 대표 4종 위젯 렌더 확인 (대화에 표시됨).

## 구성
```
ppt_standard_setA/
  spec.json            공유 토큰
  builders.py          form B — 18개 빌더 + 데모 생성기
  react/
    tokens.js          색/폰트/Slide 프레임
    components.jsx      form D — 18개 컴포넌트
  DESIGN_SYSTEM.md     디자인 규격
  _demo_setA.pptx      빌더 데모 산출물 (17장)
  _render/             렌더 검증 이미지
```

## 확장 방법
새 유형 추가 시: ① `builders.py`에 함수 추가 → ② `components.jsx`에 동일 props 컴포넌트 추가 → ③ `spec.json` `components` 배열에 이름 등록 → ④ `DESIGN_SYSTEM.md` 표에 한 줄.
