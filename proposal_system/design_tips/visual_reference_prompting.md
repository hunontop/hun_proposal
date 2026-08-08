---
id: visual.reference-prompting.v1
title: 레퍼런스를 프롬프트로 전환하기
stage: 8
category: visual
roles: [cover, section_divider, image_board, concept, evidence_visual]
applies_when:
  - 레퍼런스의 분위기는 살리고 싶지만 원본 주제와 이미지는 따라가면 안 될 때
  - 새 주제에 맞는 이미지와 도형 언어를 다시 생성해야 할 때
avoid_when:
  - 원본 레이아웃을 그대로 복제해야 하는 검증 작업
  - 브랜드 가이드가 확정되어 레퍼런스 변주가 금지된 작업
inputs_required:
  - reference_summary
  - target_topic
  - output_slide_role
evidence_level: heuristic
priority: high
tags: [reference, prompt, image-generation, style-transfer]
---

# 핵심 원칙

레퍼런스를 "이미지"가 아니라 "시각 언어"로 번역한다. 원본의 소재, 고객명, 주제 오브젝트를 따라가지 말고 구조와 톤만 가져온다.

## 적용 절차

1. 레퍼런스의 구조를 적는다: 제목 위치, 이미지 위치, 정보 밀도, 여백.
2. 레퍼런스의 톤을 적는다: 어둡다/밝다, 문서형/시네마틱, 진지함/역동성.
3. 레퍼런스의 재료를 적는다: 사진, 캡처, 아이콘, 굵은 도형, 얇은 선, 큰 숫자.
4. 원본 주제 요소를 금지 목록으로 옮긴다.
5. 새 주제의 실제 소재로 이미지 프롬프트를 만든다.

## 좋은 출력 예

`visual_prompt`: 검은 배경, 좌측 35% 여백에 큰 결론 문장, 우측에 새 주제의 실제 현장 이미지 1개, 오렌지 얇은 라벨, 하단 결론 바를 사용한다. 원본 레퍼런스의 우주/학생/CSR 이미지는 사용하지 않는다.

## 검수 기준

- 원본 주제의 이미지나 오브젝트가 남아 있지 않은가?
- 새 주제의 실제 대상이 첫눈에 보이는가?
- 이미지가 장식이 아니라 메시지 이해에 필요한가?

