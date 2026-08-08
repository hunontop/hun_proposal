# PT_DESIGN 제안 자동화 시스템

`PT_DESIGN`은 기존 제안 자동화 자산을 내부 스냅샷으로 가져와 실무용으로 발전시키는 독립 작업대다.

외부 프로젝트를 직접 참조하지 않고, 필요한 본체와 지식 파일은 `vendor/` 아래에 둔다.

목표는 5단계 초안 생성 이후를 자동화 가능한 형태로 확장하는 것이다.

```text
1 수집      나라장터/RFP/자료 수집
2 분석      8섹션 분석카드
3 전략      수주작 패턴 매칭, 전략브리프
4 생성      스토리라인 JSON
5 검토      구조 PPTX 초안 + 검토요망
6 내용확장  슬라이드별 본문 초안, 근거, 질문, 빈칸
7 레이아웃  내용 역할별 템플릿 선택과 배치 설계
8 디자인    레퍼런스 프롬프트화, 이미지/도형/스타일 지시
```

## 핵심 원칙

- 계산은 코드, 판단은 AI, 책임은 사람.
- AI에게 바로 PPT를 만들게 하지 않고 단계별 산출물을 만든다.
- 근거 없는 내용은 채우지 않고 `검토요망`으로 남긴다.
- 디자인은 원본 레퍼런스를 복제하지 않고 시각 언어로 번역한 뒤 새 주제에 맞게 다시 만든다.
- 노하우는 폴더에 넣는 것만으로 끝내지 않고, 적용 조건과 금지 조건을 가진 MD/JSON으로 축적한다.

## 빠른 시작

```powershell
python proposal_system\scripts\proposal_pipeline.py status
python proposal_system\scripts\proposal_pipeline.py build-bundles
```

API 키 없이 5단계 샘플 PPTX를 생성하려면:

```powershell
python proposal_system\scripts\proposal_pipeline.py run5
```

나라장터 라이브 수집까지 포함하려면 `vendor/proposal_core/.env`를 만든 뒤:

```powershell
python proposal_system\scripts\proposal_pipeline.py run5 --live --keyword AI
```

콕핏:

```powershell
cd proposal_system\cockpit
node server.js
```

브라우저에서 `http://localhost:5710`을 연다.

배치파일로 실행/종료:

```powershell
start_cockpit.bat
stop_cockpit.bat
```

또는 `proposal_system\start_cockpit.bat`, `proposal_system\stop_cockpit.bat`를 직접 실행한다.

## 주요 위치

| 경로 | 역할 |
|---|---|
| `config/pipeline.config.json` | 외부 프로젝트 경로와 기본 샘플 설정 |
| `scripts/proposal_pipeline.py` | 5~8단계 오케스트레이터 |
| `catalogs/layout_templates.json` | 7단계 레이아웃 선택 카탈로그 |
| `design_tips/` | 8단계 비정형 디자인 팁 축적 위치 |
| `workspace/runs/` | 실행 산출물 |
| `cockpit/` | 실무용 로컬 콕핏 |
| `vendor/proposal_core/` | 1~5단계 실행 본체 스냅샷 |
| `vendor/pj_pt/` | PPTX 보안/디자인 시스템 지식 스냅샷 |
| `vendor/demo_cockpit/` | 기존 시연 콕핏 원본 스냅샷 |

## 독립성 기준

- 기본 실행은 `vendor/proposal_core/draft/*.json`만 사용하므로 원본 프로젝트가 없어도 동작한다.
- 라이브 수집은 로컬 `.env`가 필요하다. `.env`는 복사하지 않고 `.env.example`만 제공한다.
- 6~8단계 번들은 `vendor/`, `knowledge/`, `design_tips/`만 읽는다.
- 원본 프로젝트를 다시 가져오고 싶을 때만 별도 import/copy 작업을 수행한다.
