# 실공고 선별 대시보드

나라장터 수집 실공고를 보고 **Go / Hold / Skip** 선별 + 메모를 남기는 로컬 대시보드.
⚠️ **2026-07-21(R8)부터 Go/Hold/Skip은 실행 트리거가 아니라 메모 기능**(모니터링 요원의 검토 흔적)이다 — 다음 단계로 자동 넘어가지 않는다.
착수(제안 파이프라인 투입)는 공고 카드의 **고유번호 복사 버튼** → Claude 채팅에 붙여넣기가 실행 통로다(대시보드 클릭 실행 아님). 옛 "제안서 생성" 버튼(`/api/render`)·복붙 프롬프트 조립(`/api/storyline-prompt`)은 W31에서 제거·Reuse 격리됨.

## 실행
```
python dashboard/server.py            # http://127.0.0.1:8754
python dashboard/server.py --port 9000
```
브라우저에서 열고, 각 공고에 Go/Hold/Skip(토글) + 메모. 변경 즉시 `dashboard/feedback.json`에 저장.

## 공고 검색 (AND/OR 불리언)
상단 검색창에 키워드를 입력하면 나라장터에서 **라이브 수집**(네트워크) 후 결과를 표시한다.
- `AI 플랫폼` 또는 `AI AND 플랫폼` → 둘 다 포함(AND)
- `빅데이터 OR 클라우드` → 둘 중 하나(OR). `&`/`|`도 가능: `AI&플랫폼`, `빅데이터|클라우드`
- 혼합: `AI 플랫폼 OR 빅데이터 구축` → `(AI AND 플랫폼) OR (빅데이터 AND 구축)`
- data.go.kr API는 단일 substring만 지원 → AND/OR은 그룹별 대표어 조회 + **클라이언트 필터**로 구현(`collector.parse_query`/`collect_query`).
- 검색 결과는 `last_search.json`에 저장되어 새로고침에도 유지. 검색 전 초기 화면은 최신 digest 기준.

## 데이터 출처
- 표시(한글): `proposal_system/vendor/proposal_core/digest/<날짜>.md` (최신 자동 선택)
- 식별/링크: `bids.db`의 `bid_no`·`detail_url`(g2b 링크)·`budget` — digest와 사업금액으로 조인
- ⚠️ `bids.db`의 한글 컬럼은 수집 시 인코딩 손실되어 digest를 신뢰원으로 사용. 새 수집일이 생기면 최신 digest를 자동 표시.

## 공고 분석 (stage 2·3 연결)
각 공고의 **📋 분석** 버튼 → 모달에서:
- **stage 2 (정규화)**: 공고 첨부(HWP/HWPX/PDF)를 나라장터에서 다운로드·파싱 → `proposal_core/data/<공고번호>/`
- **stage 3 (판단)**: 결정적 메타 + 첨부 본문으로 8섹션 분석 프롬프트(`analysis/<공고번호>_프롬프트.txt`) 조립 → Go/No-Go 분석카드
- **카드 생성 = 사람이 직접 LLM에 넣는 방식** (analyzer.py는 LLM 직접호출 안 함):
  1. 모달의 **① 분석 프롬프트**를 `📋 프롬프트 복사` → 원하는 LLM(Claude 등)에 붙여넣기
  2. LLM이 만든 분석카드(.md) 전체를 **② 붙여넣기창**에 넣고 `카드 저장·렌더`
  3. → `analysis/<공고번호>_분석카드.md` 저장 + 모달에 즉시 렌더. 다음 분석 시 자동 표시.
- 결정적 백본(첨부 다운로드·파싱·프롬프트 조립)은 서버가 자동 수행.
- API: `POST /api/analyze {bid_no}` → `{facts, manifest, prompt, prompt_path, card_exists, card_md}` · `POST /api/card {bid_no, card_md}` → 카드 저장

## 피드백 소비 (메모 조회 — 자동 파이프라인 투입 아님)
`feedback.json`은 사람이 남긴 메모 저장소다. Go로 표시된 공고를 나중에 조회할 때 쓴다:
```python
import json
go = [k for k,v in json.load(open("dashboard/feedback.json",encoding="utf-8")).items()
      if v.get("decision")=="go"]
```
실제 착수는 이 목록을 코드가 자동 소비하는 게 아니라, **사람이 번호를 골라 채팅에 붙여넣는 것**(R8)이다.

## API (stdlib http, 무의존)
- `GET /api/bids` → `{bids:[...], feedback:{...}}`
- `GET /api/feedback` → 현재 피드백
- `POST /api/feedback` `{bid_no, decision?, memo?}` → upsert (decision: go/hold/skip/"" 토글해제)
