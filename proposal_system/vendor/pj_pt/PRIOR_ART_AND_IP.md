# 선행기술·IP 조사 정리 (별도 프로젝트)

> 본 문서는 "PPTX 기밀 분리 익명화 + 연산 재생" 시스템과 유사한 상용·공개·특허 사례를
> 정리한 것이다. 법률 자문이 아니며, 상용화/공개 결정 전 변리사(특허) 검토가 필요하다.
> 작성일: 2026-06-04

---

## 1. 한 줄 요약

"민감 자료를 익명화 → 외부 LLM으로 작업 → 원본에 반영"이라는 **큰 개념은 신규성이 없다.**
상용 제품·오픈소스·특허·학술 논문이 모두 존재한다. 우리 시스템의 차별점은
**PPTX 레이아웃 보존 + 연산 재생(operation-replay) + 내부/외부 LLM 이원화**라는 구체적 조합이다.

---

## 2. 카테고리별 선행 사례

### 2-1. 텍스트/PII 익명화 프록시 (상용·오픈소스 다수)
LLM 전송 전 민감정보를 가리고 응답에서 복원하는 "프라이버시 프록시/게이트웨이" 패턴.

| 이름 | 형태 | 특징 |
|------|------|------|
| Skyflow LLM Privacy Vault | 상용 | 토큰화로 외부 LLM 전송 전 비식별화, 참조 무결성 유지 |
| Microsoft Presidio | 오픈소스 | PII 탐지·익명화 SDK (텍스트, 이미지 일부) |
| PII Shield (Azure) | 상용/레퍼런스 | LLM 호출마다 PII 가리고 응답에서 역치환 |
| Protecto / Grepture / Nightfall | 상용/오픈소스 | 게이트웨이형 스캔·레닥션·로깅 |
| DontFeedTheAI | 오픈소스 | 펜테스트용 익명화 프록시, **per-engagement vault**(가역 매핑) |

대상은 주로 **텍스트/구조화 데이터의 PII**, **가역 익명화(replace→복원)** 제공.

### 2-2. 가역 레닥션 + 매핑 볼트 (특허)
- **US 11,949,840** — "Redacting confidential information in a document and reversal thereof"
  → 우리가 초기 검토한 "볼트 기반 역매핑"과 동일 개념.

### 2-3. 구조만 노출하고 편집을 원본에 적용 (우리 연산 재생과 거의 동일) ★중요
- **US 10,621,371 / US 11,188,664** (Specifio, Inc. / 발명자 Kevin Knight 외)
  - 제목: *"...stripping away content and meaning... such that only structural and/or
    grammatical information... conveyed to the non-privileged person..."*
  - 요지: **내용·의미를 벗겨 구조/문법만 비권한자에게 전달 → 비권한자가 편집 → 원본에 반영.**
  - 우리의 "익명화본 편집 → ops 재생" 흐름과 본질적으로 같다. **가장 근접한 선행 특허.**
  - 출원 2018-05-31, 등록 2020-07-14 (10,621,371).
- 학술:
  - **Agent-DocEdit** — 편집 요청을 문서 구조에 grounding 후 API 호출 편집 프로그램 생성
  - **DocEdit-v2** — 멀티모달 LLM 기반 문서 구조 편집
  - **Executable and Verifiable Text-Editing (InkSync)** — 실행 가능한 편집 연산 제안
  - **The Edit Trick** — sed형 편집 연산으로 원문 보존하며 적용

### 2-4. PPTX 레이아웃 보존 익명화 (자동 툴 미발견)
- 더미 텍스트 + 이미지 블러로 레이아웃 유지하며 가리는 기법은 **수동 가이드**만 존재
  (SlideModel "obfuscate", Redactable PPT redaction 등).
- **자동화된 PPTX 전용 파이프라인**(글자 수 1:1 더미 + 비례 블러 + 도형 ID 앵커)은
  상용/공개 사례를 찾지 못함.

---

## 3. 우리 시스템의 차별점 (덜 일반적인 부분)

1. **PPTX 레이아웃 무결성 특화** — 글자 수 1:1 더미, 이미지 크기 비례 블러, 도형 ID 보존
2. **연산 재생을 "디자인 편집"에 적용** + **인바운드 ops 스키마에 내용(텍스트) 연산이 없음**
   → 외부에서 내용을 주입해 되돌릴 경로 자체가 없다(보안 속성).
3. **내부 폐쇄 LLM(내용) ↔ 외부 LLM(디자인) 이원화** + 역할별 프롬프트(내부/외부 규칙 상반)

> 단, 위 3가지도 2-3의 특허 청구항 범위에 따라 "구현 변형"으로 해석될 수 있으므로
> **청구항(claim) 단위 비교**가 필요하다(개념·제목이 아니라 청구항이 권리 범위다).

---

## 4. IP 워치리스트 (추적 대상)

| 번호 | 제목(요지) | 비고 |
|------|-----------|------|
| US 10,621,371 | content-stripped 편집 후 원본 반영 | **최우선 검토** |
| US 11,188,664 | 위 특허의 계속출원(continuation) | 청구항 차이 확인 |
| US 11,949,840 | 레닥션 및 역복원 | 볼트 방식 관련 |

확인 필요 항목:
- [ ] 각 특허의 **독립 청구항** 전문 확보 및 요소(element) 분해
- [ ] **존속 여부**(유지료 납부, 만료/포기 여부)
- [ ] **패밀리/지정국** — 한국(KR)·EP·JP 대응 특허 존재 여부
- [ ] 무효화 가능 **선행기술**(우리/제3자) 존재 여부
- [ ] 회피 설계(design-around) 여지 — 청구항 필수요소 중 회피 가능 요소

---

## 5. 다음 단계 (별도 프로젝트로)

1. 위 3건의 청구항 전문 수집 → 요소별 대조표 작성
2. 변리사 **FTO(freedom-to-operate)/비침해 의견** 의뢰
3. 공개/상용화 시나리오별 리스크 평가 (오픈소스 공개 vs 사내 사용 vs SaaS)
4. 회피 설계 또는 라이선스 협의 필요성 판단

---

## 6. 출처

- PII Shield (Microsoft): https://techcommunity.microsoft.com/blog/azuredevcommunityblog/introducing-pii-shield-a-privacy-proxy-for-every-llm-call/4514726
- Reversible Data Anonymization (DZone): https://dzone.com/articles/llm-pii-anonymization-guide
- Skyflow LLM Privacy Vault: https://www.skyflow.com/post/generative-ai-data-privacy-skyflow-llm-privacy-vault
- Microsoft Presidio + LangGraph (DEV): https://dev.to/sreeni5018/microsoft-presidio-and-langgraph-enhancing-ai-agents-with-robust-pii-protection-and-data-14oo
- DontFeedTheAI (GitHub): https://github.com/zeroc00I/LLM-anonymization
- US 10,621,371: https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/10621371
- US 11,949,840: https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11949840
- Agent-DocEdit (OpenReview): https://openreview.net/forum?id=1ba209BACA
- DocEdit-v2 (arXiv): https://arxiv.org/html/2410.16472v1
- Executable/Verifiable Text-Editing — InkSync (arXiv): https://arxiv.org/pdf/2309.15337
- The Edit Trick (Medium): https://waleedk.medium.com/the-edit-trick-efficient-llm-annotation-of-documents-d078429faf37
- Obfuscate a PowerPoint (SlideModel): https://slidemodel.com/obfuscate-powerpoint-presentation/
- Redact in PowerPoint (Redactable): https://www.redactable.com/blog/ppt-redaction
