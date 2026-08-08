# 비정형 디자인 팁 MD 작성 규격

> 목적: 별도 프로젝트에서 수집한 비정형 디자인 노하우를 제안서 자동화 시스템이 검색·판단·적용할 수 있는 형태로 축적한다. 이 규격을 따르면 특정 폴더에 `.md` 파일을 넣는 것만으로 6~8단계 에이전트가 필요한 팁만 골라 참조할 수 있다.

---

## 1. 폴더 구조 권장안

```text
design_tips/
  00_index.md
  content/
    메시지_압축.md
    근거_확장.md
  layout/
    하우스B형_결론상단.md
    이미지보드_콜아웃.md
  visual/
    레퍼런스_프롬프트화.md
    생성이미지_지시법.md
    예쁜도형_사용법.md
  proposal/
    공공홍보_고민도입.md
    수행계획_풍성화.md
  anti_patterns/
    원본테마_과적합.md
    장식이미지_남용.md
```

`00_index.md`에는 전체 파일 목록과 각 파일의 한 줄 설명만 둔다. 실제 판단 기준은 각 팁 파일의 메타데이터와 본문에 둔다.

---

## 2. 팁 파일 표준 템플릿

각 팁 파일은 아래 구조를 유지한다.

```markdown
---
id: visual.reference-prompting.v1
title: 레퍼런스를 프롬프트로 전환하기
stage: 8
category: visual
roles: [cover, section_divider, image_board, concept]
applies_when:
  - 레퍼런스의 분위기는 살리고 싶지만 원본 주제/이미지는 따라가면 안 될 때
  - 새 주제에 맞는 이미지·도형·색상 언어를 다시 생성해야 할 때
avoid_when:
  - 원본 레이아웃을 그대로 복제해야 하는 검증용 작업
  - 브랜드 가이드가 이미 확정되어 레퍼런스 변주가 금지된 작업
inputs_required:
  - reference_summary
  - target_topic
  - audience
  - output_slide_role
evidence_level: heuristic
priority: medium
tags: [reference, image-generation, prompt, style-transfer]
---

# 핵심 원칙

레퍼런스를 이미지나 테마로 직접 복사하지 말고, 먼저 시각 언어로 번역한다.

## 적용 절차

1. 레퍼런스에서 주제 고유 요소를 제거한다.
2. 남는 요소를 구조, 톤, 재료, 이미지 문법, 도형 문법으로 나눈다.
3. 새 주제의 실제 소재와 결합해 이미지/도형 지시문을 만든다.

## 적용 예시

- 나쁨: "이 레퍼런스처럼 만들어줘."
- 좋음: "검은 배경, 좌측 35% 여백, 우측에 실제 현장 이미지 1개, 오렌지 얇은 라벨, 하단 결론 바를 사용한다. 원본의 우주/학생 이미지는 쓰지 않는다."

## 출력에 반영할 문장

`visual_prompt`: 레퍼런스의 분위기를 구조·톤·재료로만 계승하고, 이미지는 새 주제의 실제 장면으로 생성한다.

## 검수 기준

- 원본 주제의 이미지·오브젝트가 남아 있지 않은가?
- 새 주제의 실제 대상이 첫 화면에서 보이는가?
- 장식이 아니라 메시지 이해에 필요한 이미지인가?
```

---

## 3. 필수 메타데이터

| 필드 | 의미 | 예시 |
|---|---|---|
| `id` | 고유 ID. 폴더가 바뀌어도 유지 | `layout.matrix-priority.v1` |
| `title` | 사람이 읽는 제목 | `우선순위 매트릭스 강조법` |
| `stage` | 적용 단계. 6=내용, 7=구조/레이아웃, 8=디자인 | `8` |
| `category` | `content`, `layout`, `visual`, `proposal`, `anti_pattern` 중 하나 | `visual` |
| `roles` | 적용 가능한 슬라이드 역할 | `[data, roadmap, image_board]` |
| `applies_when` | 적용 조건 | `선택지를 평가할 때` |
| `avoid_when` | 적용 금지 조건 | `축이 불명확할 때` |
| `inputs_required` | 이 팁을 쓰려면 필요한 입력 | `criteria`, `options` |
| `evidence_level` | 근거 수준. `case`, `heuristic`, `preference`, `anti_pattern` | `heuristic` |
| `priority` | 충돌 시 우선순위. `high`, `medium`, `low` | `medium` |
| `tags` | 검색 키워드 | `[public-proposal, image, contrast]` |

---

## 4. 본문 작성 규칙

- 한 파일에는 하나의 팁만 담는다.
- 팁은 취향이 아니라 판단 규칙으로 쓴다.
- 반드시 `적용 조건`과 `쓰지 말 조건`을 함께 적는다.
- 가능한 경우 "나쁨/좋음" 예시를 짧게 넣는다.
- 이미지 생성 팁은 피사체, 구도, 재료, 조명, 금지 요소를 분리해서 쓴다.
- 도형 팁은 도형의 의미 역할을 먼저 적고, 색상·크기·위치는 뒤에 둔다.
- 원본 레퍼런스의 특정 고객명, 브랜드명, 실데이터는 넣지 않는다.
- 다른 파일을 참조할 때는 `related:` 항목이나 본문 링크를 쓴다.

---

## 5. 에이전트 적용 로직

시스템은 팁을 다음 순서로 선별한다.

1. 현재 단계와 `stage`가 맞는 팁만 후보로 둔다.
2. 현재 슬라이드 역할과 `roles`가 겹치는 팁을 우선한다.
3. 현재 입력에 `inputs_required`가 충족되는지 확인한다.
4. `applies_when`에 해당하고 `avoid_when`에 걸리지 않는 팁만 적용한다.
5. 여러 팁이 충돌하면 `priority`가 높은 팁을 우선하고, 그래도 충돌하면 보수적인 쪽을 선택한다.
6. `anti_pattern` 팁은 항상 최종 검수 단계에서 한 번 더 적용한다.

---

## 6. 6~8단계별 팁 유형

### 6단계: 내용 풍성화

추천 팁 유형:

- 제안서 본문을 채우는 질문 리스트
- 발주처 관점의 고민 확장
- 평가항목별 써야 할 근거
- "검토요망"으로 비워야 할 내용
- 실적·인력·예산을 지어내지 않는 문장 패턴

산출물 반영 위치:

- `content_brief.md`
- `slide_content_draft.json`
- 슬라이드별 `evidence`, `open_questions`, `review_needed`

### 7단계: 내용-레이아웃 매칭

추천 팁 유형:

- 메시지 역할별 템플릿 선택 규칙
- 표/매트릭스/로드맵/이미지 보드 구분법
- 하우스B형 템플릿 카탈로그 변형 규칙
- 같은 내용의 대안 레이아웃 비교

산출물 반영 위치:

- `layout_plan.json`
- 슬라이드별 `layout_role`, `template_id`, `selection_reason`, `rejected_templates`

### 8단계: 디자인화

추천 팁 유형:

- 레퍼런스 프롬프트화
- 새 주제에 맞는 이미지 생성 지시
- 예쁜 도형 사용법
- 색/질감/사진/아이콘의 의미 역할
- 원본 테마 과적합 방지

산출물 반영 위치:

- `design_prompt.md`
- 슬라이드별 `visual_prompt`, `image_prompt`, `shape_language`, `style_constraints`

---

## 7. 좋은 팁 파일의 기준

- 이 팁을 적용할지 말지 기계적으로 판단할 수 있다.
- 적용 후 산출물의 어느 필드가 바뀌는지 명확하다.
- 레퍼런스 복제가 아니라 새 주제 변환에 도움이 된다.
- "예쁘게" 같은 추상 표현보다 구도, 밀도, 대비, 소재, 역할이 드러난다.
- 검수 질문이 있어 사람이 빠르게 맞고 틀림을 판단할 수 있다.

---

## 8. 초기 작성 과제

별도 프로젝트에서 우선 만들면 좋은 파일:

```text
visual/레퍼런스_프롬프트화.md
visual/생성이미지_지시법.md
visual/예쁜도형_사용법.md
visual/원본테마_과적합_방지.md
layout/템플릿_선택_이유쓰기.md
layout/내용밀도별_레이아웃_분기.md
content/제안서_본문_풍성화_질문.md
proposal/평가항목별_내용확장.md
anti_patterns/요약만_있고_근거없는_슬라이드.md
anti_patterns/블러를_스타일로_오해.md
```

