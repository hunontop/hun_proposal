# 스킨 통합 매뉴얼 — 새 레퍼런스로 디자인 스킨/가이드 추가

> **현재 위상 (W31, 2026-07-21)**: `add-skin`은 재심사에서 **존치 확정** — 창고 **입고 경로 2개** 중 "외부 이식"(잘 만든 외부 덱을 분해해 반입)을 담당한다(다른 하나는 "졸업" = 끝난 run의 `design_contract.json`을 `curate`로 등록). 창고에 들어온 스킨은 **차용**(사용자가 특정 run의 계약 초안으로 명시 지정) 없이는 시스템이 자동 적용하지 않는다 — `quartz_guide`처럼 창고 성격의 가이드는 config에 `explicit_only`로 표시되어 `--design-guide`에 id를 직접 지정할 때만 적용된다(자동 주입 차단, W31 P2). 구 하우스 팩(옛 `house_a`·`house_b`)은 W31에서 `<개발 원본 전용 경로>`로 완전 이전됐다 — 로컬 참조 금지. 용어 정의 상세 = `CONTEXT/JOURNEY.md`. 아래 원샷 명령·절차 자체는 개정하지 않는다.

> 새 디자인 레퍼런스(PPTX/PDF) 하나를 **선택 가능한 스킨/가이드**로 시스템에 등록하는 절차.
> **원샷 명령 = `proposal_pipeline.py add-skin`** (포팅 → 선택 tokens → config 자동 등록 → 검증).
> 관련 문서: 포터 내부 = [`DESIGN_GUIDE_PORTING.md`](DESIGN_GUIDE_PORTING.md) · 가이드 계약 = [`CONTEXT/DESIGN_DIRECTOR_PASS.md §2.1`](CONTEXT/DESIGN_DIRECTOR_PASS.md).

> **표시 라벨 ↔ 내부 id**: 대시보드·문구에는 테마명으로 보이지만, 명령어(`--pack`/`--design-guide`/`--skins`)에는 **내부 id**를 쓴다.
> 기본 테마 = `core`(중립 코어, NORTHSTAR 결정 11) · 오렌지 테마 = `quartz`(결정론 스킨) / `quartz_guide`(비전 가이드, 창고·명시 선택 시만). 구 하우스 팩(옛 `house_a`/`house_b`)은 W31에서 `<개발 원본 전용 경로>`로 이전 — 로컬 참조 금지.
> `add-skin --id <새이름>`의 id가 곧 그 스킨의 명령어 이름이 된다(표시 라벨은 별도 지정 없이 id 사용).

## 1. 개념 — 스킨은 두 종류

한 레퍼런스는 **두 종류의 산출**을 만들 수 있고, 소비 지점이 다르다.

| | 비전 가이드 (주) | 결정론 tokens 스킨 (선택) |
|---|---|---|
| 무엇 | LLM·비전이 보는 규칙+예시 | 렌더러가 읽는 CSS 변수(색/폰트) |
| 입력 | PPTX / PDF | **PPTX만**(geometry 필요) |
| 산출 | ported 폴더(spec+examples+meta) | `skins/<id>.json` |
| 소비 | `stage8/stage9 --design-guide <id>` | `render --skins <id>` |
| 성격 | 포맷 관대(연화된 정규형) | 결정론 캐스케이드 |

`add-skin`은 **비전 가이드를 항상**, `--tokens`를 주면 **결정론 스킨도** 만든다.

## 2. 원샷 명령

```bash
python proposal_system/scripts/proposal_pipeline.py add-skin \
  --source <레퍼런스.pptx|pdf> \
  --id <스킨이름> \
  [--tokens]              # 결정론 tokens 스킨도 생성(pptx만)
```

예:
```bash
# 비전 가이드만
python proposal_system/scripts/proposal_pipeline.py add-skin --source _source/refs/acme.pptx --id acme

# 비전 가이드 + 결정론 스킨
python proposal_system/scripts/proposal_pipeline.py add-skin --source _source/refs/acme.pptx --id acme --tokens
```

### 하는 일 (4단계, 자동)
1. **포팅** — `tools/port_design_guide.py`로 레퍼런스를 ported 폴더로 변환
   (`design_guide_ai.md`=spec · `assets/slides/*.png`=examples · `manifest.json`=meta).
2. **(선택) tokens** — `--tokens` + PPTX면 `app/skin_extract.py`로 `skins/<id>.json` 생성.
3. **등록(멱등)** — `proposal_system/config/pipeline.config.json`의 `knowledge.design_guides`에
   dict 항목 `{id, spec_text, examples_dir, meta}` 추가(같은 id 있으면 교체).
4. **검증** — `resolve_design_guides()`로 새 id가 정규형으로 해석되는지 확인 후 사용법 출력.

### 사용
```bash
# 비전 가이드 선택(디자인 방향·디렉터 패스)
python proposal_system/scripts/proposal_pipeline.py stage8 ... --design-guide acme
python proposal_system/scripts/proposal_pipeline.py stage9 --run <run> --design-guide acme
# 결정론 스킨 캐스케이드(--tokens로 만든 경우)
python proposal_system/scripts/proposal_pipeline.py render ... --skins acme
```
복수 캐스케이드: `--design-guide acme,quartz_guide` / `--skins quartz,acme`(뒤가 앞을 덮음).

## 3. 옵션

| 플래그 | 의미 |
|---|---|
| `--source` (필수) | 레퍼런스 `.pptx`/`.pdf`. 상대경로=repo 루트 기준. |
| `--id` (필수) | 스킨 id(영숫자·`_.-`). `--design-guide`/`--skins`에서 이 이름을 씀. |
| `--tokens` | 결정론 tokens 스킨도 생성(**PPTX만**; PDF면 자동 스킵). |
| `--out` | 포팅 산출 폴더(기본 `_source/design_guides/<id>_ported`). |
| `--process-md` | 포터에 넘길 판단기준 MD(선택). |
| `--title` | 가이드 제목(선택). |
| `--no-port` | 포팅 건너뜀(이미 ported 폴더 있음) — **등록만**. `--out`으로 폴더 지정. |
| `--python` | 포터/추출기 파이썬(기본: 번들 런타임→현재 인터프리터). env `PORT_DESIGN_PYTHON`도 가능. |
| `--dry-run` | 계획만 출력, 쓰기 없음. |

## 4. 런타임 의존성 (포팅 단계)

포터/추출기는 특수 의존성이 필요해 **별도 인터프리터**로 subprocess 실행된다:
- `python-pptx`(PPTX 텍스트), `pdfplumber`(PDF 텍스트), PowerPoint COM(`win32com`, PPTX→PNG/PDF), Poppler `pdftoppm`(PDF→PNG).
- 기본 인터프리터 = 번들 codex-runtime python(위 의존성 포함). 다른 환경이면 `--python`/`PORT_DESIGN_PYTHON`로 지정.
- **degrade**: COM/Poppler가 막히면 PNG 렌더가 빠질 수 있으나 text/JSON/MD는 생성된다(examples가 0장일 수 있음 → 비전 예시 없이 spec만).

## 5. 문제 해결

- **포팅 실패(exit≠0)** → 의존성(python-pptx/pdfplumber/poppler/COM) 확인. `--python`으로 올바른 인터프리터 지정.
- **examples=0** → 슬라이드 PNG 미생성(COM/Poppler 문제). spec_text만으로도 비전 가이드는 동작(예시 없이).
- **id 충돌** → 기존 문자열 가이드의 stem과 같으면 거부됨 → 다른 `--id`.
- **tokens 스킵됨** → 입력이 PDF임(geometry 없음). 결정론 스킨은 PPTX 원본 필요.
- **다른 드라이브 산출** → config에 절대경로로 저장됨(상대화 불가). 이식성 위해 산출 폴더는 repo 하위 권장.

## 6. 수동 폴백 (add-skin 없이)

구조적 명령을 못 쓰는 환경이면 수동 3단계(= add-skin이 자동화하는 것):
1. 포팅: `DESIGN_GUIDE_PORTING.md`의 실행 예시대로 `port_design_guide.py` 직접 실행.
2. 등록: `pipeline.config.json`의 `knowledge.design_guides`에 dict 1개 추가(`quartz_guide` 항목이 템플릿).
3. (선택) tokens: `python app/skin_extract.py <ref.pptx> skins/<id>.json`.

## 7. 검증 상태

- `add-skin`: dry-run·등록전용(`--no-port`)·멱등(재실행=replaced)·**실 포터 종단**(예시스튜디오 PPTX→ported 12예시 + `--tokens`→`skins/*.json{colors,fonts}` + config 등록 + resolve 검증) 확인(2026-07-07). smoke 14/14.
- 배포는 ported **폴더째**(이미지 상대경로 유지). `_source/` 산출물은 대체로 미추적(gitignore) — 팀 공유 시 폴더 동기화.
