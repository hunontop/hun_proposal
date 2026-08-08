# hun_proposal — 요구사항에서 잘 디자인된 덱까지

**요구사항(브리프 또는 나라장터 공고) → 잘 디자인된 HTML 덱**을 만드는 반자동 시스템.
이 폴더는 **어디에 두든 그대로 실행되는 자립 사본**입니다(경로 하드코딩 없음).

- 1차 산출물 = **HTML 덱**. PPTX·시네마틱은 승인된 HTML의 파생물(선택).
- 시스템 전체를 파악하려면 → **[`MANUAL.md`](MANUAL.md)** (공정·아키텍처·문서 인덱스가 한 곳에).
- 구조 도식 → [`docs/architecture.svg`](docs/architecture.svg)

> ⚙️ 이 폴더는 개발 원본에서 **자동 생성된 공개 사본**입니다. 코드를 직접 고치지 말고
> 원본에서 고친 뒤 다시 생성하세요. (당신이 채우는 `pull-knowledge/` 지식카드는 보존됩니다.)

---

## 1. 설치 (한 번)

Python 3.10+ 필요.

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

여기까지면 **스모크와 3단계 데모가 전부 돕니다.** 스크린샷 기반 디자인 실측과 이미지
PPTX를 쓸 때만 브라우저 엔진을 추가로 받으세요:

```powershell
python -m playwright install chromium     # 선택
```

> 브라우저가 없으면 관련 검증은 **skip**으로 표시되고 넘어갑니다 — 실패로 끝나지 않습니다.
> (없는 걸 "통과"라고 말하지도 않습니다: 브라우저 계층은 `unmeasured`로 기록됩니다.)

## 2. 잘 됐는지 확인

```powershell
python dashboard/test_smoke.py     # 회귀 스모크 (네트워크 0)
```

`OK (skipped=N)` 이면 정상입니다. skip은 이 사본에 없는 개발 원본 전용 검증과, 브라우저
엔진을 아직 안 받았을 때의 실측 검증입니다.

## 2.5 공고 수집 (무키 경로 — 기업마당 키워드 검색)

나라장터 API 키 없이도 공고를 모을 수 있습니다 (vendored [ir-search](tools/ir_search/) 기반, MIT):

```powershell
python tools/gongo_search.py "소셜벤처" --max-pages 5 -o 수집.jsonl     # 키워드 검색 → JSONL
python tools/gongo_search.py "소셜벤처" --where content                # 본문까지 넓게 검색
python tools/gongo_search.py detail <공고URL> --download-dir attachments/   # 상세+첨부 수집
```

> 서드파티 고지 → [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)

## 3. 60초 실행 — 동사 3개

```powershell
python proposal_system/scripts/proposal_pipeline.py start --brief <요구사항.md> --mode direct
python proposal_system/scripts/proposal_pipeline.py go --run <run>
python proposal_system/scripts/proposal_pipeline.py status --run <run>   # 현재 위치·다음 한 줄
python proposal_system/scripts/proposal_pipeline.py ship --run <run> [--pptx]
```

- **모드**: `direct` = 세션 LLM이 관통 / `secure` = LLM 왕복을 복사-붙여넣기(내부 데이터 미노출).
- 대시보드(공정의 정문): `python dashboard/server.py` → [`QUICKSTART.md`](QUICKSTART.md)
  첫 실행에서는 **수집한 공고가 0건**입니다 — §2.5로 모으거나 대시보드에서 검색하세요.

## 4. 지식 채우기 (당신 몫)

이 시스템은 기획·디자인 지식을 **자동 주입하지 않고 검색해서 당겨(pull)** 씁니다.
[`pull-knowledge/`](pull-knowledge/) 폴더에 당신의 카드를 넣으세요.

- **지금(3단계=와이어프레임까지 데모)**: [`pull-knowledge/기획지식/`](pull-knowledge/기획지식/)에 기획·전략·메시지 노하우 카드만 넣으면 됩니다.
- 위치는 config 1점화: `proposal_system/config/pipeline.config.json` → `knowledge.pull_knowledge_dir`.
- 자세한 규칙(층 격리·나중에 디자인지식 추가) → [`pull-knowledge/README.md`](pull-knowledge/README.md)

## 5. 이 배포판에 든 것 / 빠진 것

이 사본은 **포함 목록(allowlist)** 으로 만들어집니다 — 개발 원본에 무엇이 새로 생기든,
빌드 스크립트에 명시적으로 적히기 전에는 여기 실리지 않습니다.

**포함(최소 실행 코어)**: `app/`(엔진) · `proposal_system/{scripts,config,catalogs,knowledge,scenarios,prompts,companies}` ·
`packs/core`(렌더러 어휘) · `skins/` · `dashboard/`(코드) · `design-assets/` · `tools/` ·
`pull-knowledge/`(당신이 채움) · vendor **코드**

**의도적으로 뺀 것**:

| 뺀 것 | 왜 |
|---|---|
| 실공고 제안요청서 원문 (샘플 1건만 동봉) | 타 기관 제안요청서를 공개 저장소에 싣지 않는다 |
| 수주작 전략 프로파일(`strategy_lib/`)·초안(`draft/`)·전략브리프(`brief/`) | 실 제안 자산 |
| 참고 제안서 추출 텍스트(`pj_pt/raw_text/`) | 실 거래 자료 |
| 대시보드의 마지막 검색·선별 기록·과거 run 산출물 | 남의 검색·판단 기록이 첫 화면에 뜰 이유가 없다 |
| 원전 도판 crop(`packs/core/catalog_previews/원전_원형/`) | 출판물 도판 |
| 레퍼런스 임포터(`tools/port_design_guide.py`) | 개발 원본 전용 외부 창고를 참조 |
| 강의 팩(`packs/lecture/`) | 특정 강의 덱 전용 어휘 — 공개 제품과 무관 |
| `CONTEXT/`·`scheduler/`·`_source/`·에이전트 부트스트랩 | 오케스트레이션·협업·실험실 — 혼자 쓰는 실행에 불필요 |

> 빠진 자산을 참조하던 자리는 **사람 말로 된 안내**로 폴백합니다(`status`가 한 줄로 말합니다).
> MANUAL 본문이 위 항목을 언급하면 개발 원본 환경 이야기입니다.

## 6. 원칙 (짧게)

- **HTML이 정본.** `deck.json`의 텍스트·수치는 어떤 파생·정련도 못 바꿉니다(SSOT 가드).
- **실적 이미지 자동 생성 금지**(가짜 실적 방지). 검토요망 태그는 사람의 명시 해소 기록이 있을 때만 제거.
- **숫자가 갑자기 좋아지면 의심하라.** 자기보고 대신 코드/로그/스모크로 검증.

## 7. 라이선스

MIT — [`LICENSE`](LICENSE). 동봉한 서드파티 고지는 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
