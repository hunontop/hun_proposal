# PPT 자동화 표준셋 — 버전 A · 디자인 시스템

> 제안서 슬라이드 자동 생성을 위한 기본 디자인 규격. 모든 컴포넌트(빌더/React)가 이 토큰을 따른다.
> 토큰 원본: [`spec.json`](spec.json)

## 1. 캔버스
| 항목 | 값 |
|------|----|
| 슬라이드 | 27.52 cm × 19.05 cm (가로형, 비율 ≈ 1.445:1) |
| 원점 | 좌상단 (0,0) · 단위: 위치/크기 cm, 글자 pt, 색 RRGGBB |
| 본문 여백 | 좌우 1.0 cm · 제목 top 2.1 cm · 본문 top 4.2 cm · 페이지번호 top 18.1 cm |

## 2. 컬러
| 역할 | HEX |
|------|-----|
| Primary Navy | `#1E4A8C` |
| Accent Orange | `#F37321` (밝은 변형 `#FF7900`) |
| Black / White | `#000000` / `#FFFFFF` |
| Secondary Blue | `#156082` |
| Gray (배경/선/텍스트) | `#E8E8E8` / `#D5D5D5` / `#595959` |
| 보조 강조 | Purple `#7E28E1` · Yellow `#FBC44D` · Red `#FF0000`(경고 한정) |

규칙: 1슬라이드 = Navy(구조) + Orange(포인트) + 무채색. 보조색은 데이터 구분에만. 리스크 맥락에만 Red.

## 3. 타이포그래피 (Pretendard)
| 쓰임 | 굵기 | 크기 |
|------|------|------|
| 대형 타이틀 | Black | 44–54 pt |
| 슬라이드 제목 | ExtraBold | 28–32 pt |
| 소제목/라벨 | SemiBold | 20–22 pt |
| 본문 | Medium | 16–17 pt |
| 캡션/출처 | Light | 12–14 pt |

위계: 굵기(Black→Medium→Light) + 색(Navy→Orange→Gray)로 1·2·3차 정보를 가른다.

## 4. 컴포넌트 17유형 + 공통 헤더
| # | 컴포넌트 | 빌더 함수 / React | 용도 |
|---|----------|-------------------|------|
| 0 | 헤더 바 | `header_bar` / `HeaderBar` | 콘텐츠 슬라이드 공통 상단(챕터번호+브레드크럼) |
| 1 | 표지 | `cover` / `Cover` | 핵심 질문 + 타이틀 |
| 2 | 목차 | `toc` / `Toc` | 번호 인덱스 그리드 |
| 3 | 섹션표지 | `section_cover` / `SectionCover` | 세로 패널 + 대형 숫자 |
| 4 | 하위섹션표지 | `subsection_cover` / `SectionCover sub` | 하위 섹션 진입 |
| 5 | 도입·문제제기 | `problem_intro` / `ProblemIntro` | 리드 + 본문 |
| 6 | 데이터 차트 | `data_chart` / `DataChart` | 막대 + 강조 1개 |
| 7 | 대비형 | `contrast_diagram` / `ContrastDiagram` | AS-IS/TO-BE 2열 |
| 8 | 카드형 | `card_grid` / `CardGrid` | 2–4열 카드 |
| 9 | 스토리보드 | `storyboard` / `Storyboard` | 씬 비주얼 + 캡션 |
| 10 | 타임라인·매트릭스 | `timeline_matrix` / `TimelineMatrix` | 시간축 × 타깃 |
| 11 | 표·타임테이블 | `table_block` / `TableBlock` | 헤더 Navy + 줄무늬 |
| 12 | STEP·프로세스 | `process_steps` / `ProcessSteps` | 번호 배지 + 화살표 |
| 13 | 지도형 | `map_block` / `MapBlock` | 권역 핀 라벨 |
| 14 | 인물 카드 | `person_cards` / `PersonCards` | 원형 + 이름/경력 |
| 15 | 조직도 | `org_chart` / `OrgChart` | 루트 + 하위 박스 |
| 16 | 실적·포트폴리오 | `portfolio_case` / `PortfolioCase` | 썸네일 + 라벨 |
| 17 | 마무리 매트릭스 | `closing_matrix` / `ClosingMatrix` | 단계별 킬링포인트 |

## 5. 흐름 골격
각 챕터는 **문제제기 → 현황분석 → 인사이트 → 솔루션(상세) → 기대효과**를 반복한다.
표준 덱 구성: 표지 → 목차 → [챕터: 섹션표지 → 도입 → 데이터/대비 → 솔루션(카드/표/프로세스/맵) → 마무리] → 포트폴리오 → 마무리 매트릭스.
