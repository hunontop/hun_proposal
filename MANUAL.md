# hun_proposal — 전체 매뉴얼 (어떤 에이전트든 여기부터)

> 📦 **이 폴더는 hun_proposal 공개 배포판입니다.** 개발 원본에서 **실행에 필요한 최소 코어만** 떼어낸 자립 사본이에요.
> - 설치·첫 실행은 먼저 [`README.md`](README.md)를 보세요.
> - 아래 본문 중 **§6 오케스트레이션·친구협업 · §7 재사용 도구 · §9의 역사 기록(RESUME/plan/state)** 및 `CONTEXT/`·`_source/`·`scheduler/` 관련 서술은
>   개발 원본 환경의 이야기라 **이 사본에는 포함되지 않습니다.** 혼자(SOLO) 쓰는 데 아무 지장 없습니다.
> - 실 클라이언트 자산(수주작 전략 프로파일·실 제안 초안·참고 제안서 원문)도 공개판에서 빠졌습니다 — 자세한 목록은 README §5.
> - 디자인·기획 지식은 자동 주입되지 않고 [`pull-knowledge/`](pull-knowledge/)에서 검색해 당겨 씁니다(직접 채우는 폴더).


> 이 폴더에 새로 들어온 에이전트(Claude/Codex/Gemini/사람 누구든)가 **시스템 전체를 한 번에 파악**하도록 쓴 단일 매뉴얼.
> 최종 갱신 2026-07-12 (W20 반영: 기본 팩 = `core` 중립 코어·무채, 하우스 팩은 `--pack` 명시 시만 — NORTHSTAR 결정 11. 이전 2026-07-08: 공정 재정의 완주 — 동사 3개 `start/go/ship`·상태머신·두 루프·승인 전 평가·이미지 PPTX·secure 익명화. 설계 정본 = `CONTEXT/NORTHSTAR_REDESIGN.md`).
> 2026-07-21 W31 여정 정리 반영: `run5`·`build-bundles`·`copy-demo-assets`·`piece` 서브커맨드·`ship --cinematic`·대시보드 `/api/render`·`/api/storyline-prompt`·발산 라우트 2종·`/monitor`는 제거·`<개발 원본 전용 경로>`로 격리(secure 익명화 훅·고유명사 스윕도 동반 격리 — secure 모드 자체는 존치하되 자동 익명화만 빠짐, 격리분 복원법은 코드 주석). 신설: `run/journey/` 단계 폴더 여정(R7)·`run/design_contract.json`(R2·R5)·`theme_confirm` 게이트(R3, 스킵 가능)·이미지 프롬프트 오버레이 `imagedeck_prompts_local/`(R6)·대시보드 공고 고유번호 복사 버튼(R8, 착수 통로)·Go/Hold/Skip=메모 전용(R8). 정본 = `CONTEXT/JOURNEY.md`(v1)·`CONTEXT/FEATURE_MAP_W31.md`.

> 🗺 **전체 구조 한눈 도식 → [`docs/architecture.svg`](docs/architecture.svg)**

---

## 0. 한 줄 정의

**요구사항(브리프 또는 나라장터 공고) → 장표 내용 → 레이아웃 → 디자인 → 잘 디자인된 HTML 덱**을 만드는 반자동 시스템. 단일 홈 `<개발 원본 전용 경로>`(SSOT).

- **1차 목표 = 잘 디자인된 HTML 덱.** PPTX·시네마틱은 승인된 HTML의 **파생물**(선택).
- **나라장터는 입구 어댑터의 한 구현**이지 시스템의 정의가 아니다(범용 브리프 입구 동급).

## 1. 60초 실행 — 기억할 동사는 3개뿐

```powershell
# 시작: 입력(공고번호 or 브리프) + 모드만 확정
python proposal_system/scripts/proposal_pipeline.py start --bid <공고번호> --mode direct
python proposal_system/scripts/proposal_pipeline.py start --brief <요구사항.md> --mode secure

# 진행: 다음 체크포인트까지 알아서. 몇 번을 쳐도 안전(멱등). 멈추면 이유+할 일을 말해준다.
python proposal_system/scripts/proposal_pipeline.py go --run <run>
python proposal_system/scripts/proposal_pipeline.py go --run <run> --confirm   # optional 관문 통과(human 관문은 무효 - 대시보드 ack만)

# 확정: 승인 + (선택) 파생물
python proposal_system/scripts/proposal_pipeline.py ship --run <run> [--pptx --pptx-mode image|native]

# 길을 잃었으면 언제든: 코드가 현재 위치·다음 한 줄을 답한다 (문서 고고학 불필요)
python proposal_system/scripts/proposal_pipeline.py status --run <run>

python dashboard/test_smoke.py        # 회귀 스모크 29/29 (네트워크 0)
python dashboard/server.py            # 대시보드 :8754 (secure 모드 표면·나라장터 선별)
```

- **모드**: `secure` = LLM 왕복이 복사-붙여넣기(외부 미노출) / `direct` = 세션 LLM·Codex가 관통(기본값). ⚠️ **익명화 자동 왕복(고유명사 치환→수거물 복원)은 W31에서 `<개발 원본 전용 경로>`로 격리됨** — 여정 대조에서 "여정 밖(초보자용 강의 자원)"으로 확정. secure 모드 자체(복붙 왕복 뼈대)는 살아 있으나 자동 익명화 기능은 빠졌다(`anonymization.config.json` enabled=true로 켜면 격리 안내 에러로 표면화).
- 기존 세부 커맨드(render/stage9/approve/…)는 전부 살아 있으나 **go가 호출하는 부품**이다. 새 기능은 새 커맨드를 만들지 못한다(동사 3개의 내부 단계로만 편입 — NORTHSTAR §3.0 규칙). **W31에서 `run5`·`build-bundles`·`copy-demo-assets`·`piece`(구현 공정)는 제거·Reuse 격리됨** — 남은 서브커맨드가 CLI 전체다(§9 문서 인덱스 위 헤더 참조).

## 2. 공정 — 두 루프 + 사람 체크포인트 3개

```
탐색 루프 (싸고 빠르게 여러 번)                 디벨롭 루프 (내용+디자인 동시 디벨롭 — ✋② 후 go가 자동 진입)
분석→message_map→스토리라인→렌더→배지→반복 →✋②→ [3]와이어프레임(W21·무채) → [4]stage9 정련 → [4+]고도화
        ↑✋①               (핵심 주장1+전략축2~4  bundle→결정기(LLM)→apply(병합·무채 재렌더)      │
       start              +근거 슬롯 · 결정 9①)  (frame×piece 결정·R1~R9 검증·재게이트)   → 디자인 고도화(refine ④+:
                          ※[3]·[4+]는 이제 go 자동 오케스트레이션 편입          목표 명세→레퍼런스→✋검토정지→실행 핸드오프)
                                                                  │
                                                            ✋③ 디자인 게이트 ─ 승인 / Claude Design 편집 / 반려
                                                                  │
                                                                ship ─ approve → (선택) PPTX(이미지=승인 HTML의 사진
                                                                        · native=편집용)
```

> **R7 폴더 여정(2026-07-21)**: `go`가 단계 진입 시 `run/journey/01_공고찾기~14_마무리/`를 열어 `_여기서-할-일.md`(단계 매뉴얼)·가독 뷰(`*_읽기.md` — storyline/wireframe 등 JSON의 파생 렌더, 자동 재생성·편집 금지)·사람 편집물(`회의체_메모.md` 등)을 배치한다. 기계 정본은 flat 유지, 폴더는 사람·에이전트 공용 안내 층(정본 = `proposal_system/scripts/journey_folders.py`). 착수(A1) 통로는 대시보드 공고 카드의 **고유번호 복사 버튼** → 채팅 붙여넣기(R8) — Go/Hold/Skip은 A0 모니터링 요원의 **메모**일 뿐 실행 트리거가 아니다.

사람이 서는 곳은 ①시작 결정(입력+모드 — **공고 확정은 사람 전속**: 대시보드 Go/Hold/Skip 선별 또는 `start --selected-by user`로 명시 지정. LLM은 후보 요약·추천까지만, `agent`/`unspecified` 출처는 결정 8에 따라 경고로 표면화된다) ②의사결정 게이트(`message_map.json`[핵심 주장1+전략축2~4+근거 슬롯 — 결정 9①]·스토리라인 확정+`design_brief.json`+`review_resolutions.json` 검토요망 해소) ③디자인 게이트(덱+평가 리포트 보고 승인/편집/반려) — **의무는 셋뿐**. 나머지는 `go`가 진행하고 LLM 산출물이 필요한 지점에서 핸드오프(secure=복붙 경로 안내 / direct=세션 지시)로 멈춘다.
> **⚠ human 관문 = 사람 전속 ack(W27 P0·P3 → W31 마찰4 개정)**: `skeleton_review`(스켈레톤 역제안 검토 — 스토리라인 생성 전, 건너뛰기 가능)·`decision`(✋②)·`design_refs`(디자인 레퍼런스 검토, 건너뛰기 가능)·`design`(✋③)은 **`go --confirm`이 무효**(비0 종료) — 열쇠는 두 등가 채널: ⒜대시보드(:8754) 카드의 [검토 완료]/[건너뛰기] 버튼 ⒝journey 단계 폴더의 `검토_체크.md` `[x]` 체크(W31 마찰4 — 검토물 옆에서 확인, 다음 go가 수거). 둘 다 **사람 전속**(세션·Claude 대리 금지 — CLAUDE.md 규약). **체크 표기는 관대하다(W32 마찰32)** — `[x]`·`[X]`·`[x ]`·`[ x]`처럼 공백 변형을 전부 수용한다(사람 손 편집 채널은 사람의 오타를 전제해야 한다. 종전에는 `[x ]` 하나로 미체크 판정이 나고 `go`가 "ack 없음"만 반복해 사용자가 원인을 알 수 없었다). 빈 칸은 종전대로 미체크이고, 수용 범위 밖 표기(`[v]`·`[o]` 등)는 `go`가 `[SURFACE] 인식 불가 표기 … [x]로 고쳐라`로 알려 준다 — 조용한 무시는 없다. 또한 **관문 다이얼**(W31 마찰2, `gates.json` full/standard/express)이 정지 관문을 고르고, 꺼진 관문도 나쁜 신호면 조건부 재정지한다. **재무장**: 확정 이후 감시 산출물(skeleton.json / storyline.json·message_map.json / design_spec.json / deck.html)이 수정되면 관문이 다시 뜬다 — "리뷰→수정→재검토"가 불변식(수정하고 그냥 넘어가는 정주행 차단). 낡은 ack는 소비되지 않는다. 레거시(상태파일 없는 지문 추론) run은 재무장 면제. 정본 = `pipeline_state.HUMAN_CHECKPOINTS`·`HUMAN_CHECKPOINT_WATCH`.
> **⚠ 상류 개정 → 뼈대 stale (W31 리허설 마찰 2b, 2026-07-22 — 관문 다이얼[행 2]과 별건, 정본=REHEARSAL_FRICTIONS_W31.md)**: `message_map.json`을 고쳐도 **스켈레톤은 자동 재조립되지 않는다** — 스켈레톤 단계는 산출물(`manifest_skeleton.json`) 존재로 완료 판정되고, `skeleton.json`은 사람이 장표를 빼고 고치는 **편집 UI**라 말없이 덮어쓰면 사람 편집이 날아가기 때문이다(의도된 설계). 다만 예전엔 **조용히** 낡아서 옛 축으로 계속 진행됐다 — 이제 `skeleton.meta.message_map_fingerprint`로 감지해 status/go 경고로 표면화한다. 재조립 통로는 **`go --redo-skeleton`**(기존 skeleton.json·manifest를 `.bak_redo`로 보존 후 현재 메시지맵으로 재조립, `skeleton_review` 관문도 다시 무장). 지문은 조립에 실제로 쓰이는 부분(핵심 주장·축 id/메시지·근거 슬롯)만 본다 — `audience_note`만 고치면 침묵. 지문 없는 옛 run도 침묵(오탐 0). 정본 = `skeleton.stale_reason`.
> **선택 관문(의무 아님 · 결정 2026-07-14 "B")**: **⒜발주처 조사**([1], bid에서만) — `go`가 그 자리에서 한 번 멈춰 "할래? 건너뛰려면 `go --confirm`"으로 **의식적 선택**을 받는다(연구는 여전히 --confirm 가능한 optional). ⒝디자인 레퍼런스 검토([4+])는 W27 P0에서 human 관문으로 승격됨(위 참조). 조사를 이미 했으면(institution_research.json) ⒜는 자동 충족. 정본 = `pipeline_state.OPTIONAL_CHECKPOINTS`.

- 분석([1]) 단계의 선택 서브스텝으로 `research --bundle`/`--apply`가 있다 — RFP 첨부 밖의 발주기관 공개 정보(홈페이지·건학이념·특성화)를 조사해 직인용 훅(P1.3)과 브랜드 토큰(대표색→스킨)을 함께 확보한다(§9.7, W26, 목표조정 8·9).
- **디자인지식 pull (search-first · 기계주입 아님)**: 형태·시각 노하우는 vault `ref/디자인지식/`에서 **당겨** 쓴다 — 파이프라인 자동주입이 아니다(확정 결정: pull이라 오작동 위험 0. 디자인 쪽 기계배선은 조용한 오보를 낸 전례가 있어 기각 — memory `peedori-design-knowledge-rebuild`·`avoid-speculative-coverage`). **층 격리 = 검색 폴더로 강제**: [3] 와이어프레임은 `와이어프레임/`(44)만, [4]/[4+] 테마·디자인은 `테마/`(22)만 조회(색·폰트가 형태 단계로 누수 금지 — 사용자 우려). `examples/`(36)는 카드 `examples:` 링크로만 도달(직접검색X). vault MCP 불가 시 온디스크 미러 `<개발 원본 전용 경로>`. 상세=§9.5·§9.6, 지도=vault `ref/디자인지식/_MOC`.
- **상태 정본 = `run/pipeline_state.json`** (각 커맨드가 완료 시 자기 단계 기록). 레거시 run은 산출물 지문으로 역추론하되 `[추론]` 표시(모르는 걸 아는 척하지 않음).
- **관측 정본 = `run/gating_report.json`**: `applied_axes`(경로별 실제 적용 축)·`design_checks`(결정론 이상치 탐지)·`anonymization`(실측 applied)·`review_resolution`(해소 이력 — 해소지 파싱 실측)·`pptx_raster`. 전부 **실측**이지 자기보고가 아니다.
- **원칙**: HTML이 정본. `deck.json` 텍스트·수치는 어떤 파생·정련도 못 바꾼다(SSOT 가드). **검토요망 태그 제거는 사람의 명시 resolution 기록이 있을 때만**(창작금지의 대칭 — 코드는 태그를 임의로 지우지 않는다). 잔존 태그는 `ship`을 차단하지 않고 경고로 표면화한다. 숫자가 좋아지면 의심하라.
- **금지 두 체제 분리(W27 D5·D6, 2026-07-15)**: **저작권 동기 금지는 완화** — 웹 검색 이미지 임베드(`web_sample`, 출처 URL 기록)·발주처 자산 다운로드·레퍼런스 모사 허용. **정직성 동기 금지는 유지** — 내용 불변·창작 금지·검토요망 계약. evidence 이미지는 **생성 허용 + 가시 딱지 "AI 생성 예시"**(`generated:true` 영속, 딱지 제거는 사람의 `generated_resolved` 기록만 — 검토요망 대칭). 잔존 딱지·웹 수급 자산은 `ship`이 경고로 표면화(차단 아님), 관측 = `gating_report.image_provenance`.

## 3. 아키텍처 — 3계층 (노하우 분리)

| 계층 | 위치 | 역할 |
|---|---|---|
| **엔진** | `app/` | SlideModel 바인딩·렌더(HTML/PPTX)·design_checks·익명화 훅. **도메인 노하우 0.** |
| **노하우 팩** | `packs/<name>/` | 주입식 디자인/템플릿 팩. **기본 = `core`(중립 코어·무채, W20 — 어휘 계약 frames/pieces.json)**. `lecture`=강의 트랙 전용 |
| **⛔ 격리 팩** | ~~`packs_excluded/`~~ → **W31에서 `<개발 원본 전용 경로>`로 완전 이전**(`house_a`·`house_b` + 짝인 `layouts_house_b`/`layouts_house_a` 렌더 플러그인·`pack_paths` 모듈). 로컬엔 폴더가 없다 — 코드의 `--pack` 폴백 경로는 상시 부재로 조용히 실패(크래시 아님). 재현 필요 시 격리분을 되돌려라. |
| **데이터** | `proposal_system/workspace/runs/` | run 산출물(state·deck·리포트·브리핑·평가·파생물) |

운용 본체 = `proposal_system/`(파이프라인+상태머신+동사 3개, vendor 스냅샷으로 자기완결).

### 3.5 렌더 구조도 (3축 분리 + 디스패치 + 폴백 가시화)

정본 SlideModel(`deck.json`)이 어떻게 그림이 되는가. **엔진 노하우 0** — 색/폰트/틀은 전부 팩·스킨·카탈로그에서 주입.

```
                        정본 SlideModel (deck.json)
                          slides[ {template_id, role, fields, ...} ]
                                        │
      ┌──── 3축 주입 (독립·조합, CSS처럼 캐스케이드) ──────────────────────┐
      │  ① 패턴셋 (무엇을 논증)   stage6 strategy_pattern_sets            │
      │  ② 카탈로그 (어떤 틀·공유) catalogs/layout_templates.json         │
      │  ③ 스킨 (어떻게 보임)     packs/<p>/tokens.json + skins/*.json     │
      │      + 규칙층: 디자인 가이드(md·비전 판단 기준) + design_brief     │
      └───────────────────────────────┬──────────────────────────────────┘
                                       ▼
                 app/render/dispatch.py  Deck(pack, skins=[...], mode=)
                                       │  슬라이드마다: REGISTRY(renderer명→role→generic 폴백)
             ┌─────────────────────────┼──────────────────────────────┐
             ▼ (HTML 정본)              ▼ (PPTX native — render/ship)   ▼ (PPTX image — ship 전용)
   app/render/htmlgen.py       app/render/renderers.py 11종     rasterize.html_to_slide_pngs()
   55 렌더러(SVG 리치)          (편집가능 도형/표/차트)            = 승인된 deck.html의 사진
             │                          │                        (override·이미지 그대로. 편집불가)
             ▼                          ▼                              ▼
        deck.html  ─ stage9 정련 ─→ deck.pptx(초안용)            deck.pptx(확정본)
             폴백 가시화: 필드 불일치→generic 폴백은 warnings로 보고(조용한 폴백 금지)
```

- **핵심 원리**: 같은 정본 덱 + 다른 축 = 다른 산출. 렌더러는 `fields`만 읽고 색은 tokens에서(하드코딩 금지).
- **PPTX 두 경로의 용도**: `native`(render 시점 가능) = 편집 가능한 초안·나라장터 제출용 / `image`(ship 전용) = **디자인 확정본** — stage9 정련·이미지가 픽셀 그대로. 후자가 "HTML이 정본"의 귀결.
- **fields shape 계약 (W32 마찰28)**: `fields`는 LLM 산출물이라 **문자열을 기대하는 자리에 객체가 들어오는 오답**이 잦다(shape가 프롬프트에 미문서인 template일수록). 종전에는 `str(dict)`가 그대로 조판돼 `{'name'` 같은 원시 dict가 장표에 노출됐고 `warnings=0`이라 사람 정독 전엔 아무도 못 잡았다. 이제 두 층으로 막는다 — ⒜**프롬프트**가 shape를 명시하고("shape 미문서 template의 fields는 문자열/문자열 배열이 기본") ⒝**렌더러**가 관용 코어스한다: 객체는 `라벨: 상세`로 접되 **`warnings`로 표면화**한다(살리되 숨기지 않는다 — 고칠 곳은 상류 storyline이므로 조용한 정상화는 정직성 계약 위반). 정본 = `app/render/text_coerce.py` 한 곳이고 렌더 경로 4개(`htmlgen`·`compose`·`layouts_core`·`docgen`)가 공유한다(각자 `_esc`를 갖고 있어 한 곳만 고치면 나머지가 샌다). str·숫자 입력은 종전과 바이트 동일.
- **청중 계약 = 제작용 어휘를 장표에 그리지 않는다 (W32 마찰29·31)**: 이 덱을 받는 것은 **수신 기관(심사위원)**이므로 내부 추적·검수용 표기는 장표에 나가면 안 된다. 실측 사고 2건이 근거다 — ①N2 프롬프트가 `message`에 `(axis1 지지)` 축 표기를 지시해 심사위원 노출(추적은 `supports_axis` **필드**가 전담, 표기 지시는 제거·수거 시 잔존 패턴을 경고) ②목차 조각이 relief 미신고 시 "해소수단 미배정" 배지를 장표에 그림(→ relief 있을 때만 표기하고 미신고는 **검수 채널**로). **검수 신호는 `warnings`가 아니라 리포트의 `review_notes`로 간다** — 선택 필드 미기입은 결함이 아니라서, `warnings`에 섞으면 "warnings=0 = 무결" 계약이 깨진다(전수 렌더 테스트가 그 계약에 의존). 같은 계약이 **이미지 프롬프트에도** 적용된다(W32 마찰36⑸) — storyline 덤프의 작업용 키(`visual`·`evidence`·`supports_axis` 등)는 생성기에게도 "청중"이므로 `_PROMPT_WORKING_KEYS` 필터로 걸러 싣는다(§9.8 `--bundle`).

## 4. 표면 2개 — 대시보드(정문) + CLI(진행). 모드(direct/secure)는 별개 축.

**핵심(오해 금지)**: **대시보드 = 시작의 정문**이지 "secure 전용"이 아니다. **표면(대시보드 vs CLI)과 모드(direct vs secure)는 다른 축**이다 — 대시보드로 시작해도 모드는 `direct`(세션 LLM 관통)일 수 있다. 시동어 "제안 시작" = 대시보드로 출발(CLAUDE.md). 같은 공정 지도를 두 표면이 공유한다.

- **대시보드(:8754) = 전체 공정의 1급 진입 표면**: 나라장터 검색→분석카드→**Go/Hold/Skip(2026-07-21부터 실행 트리거 아닌 A0 모니터링 요원의 메모 층, R8)**→**공고 고유번호 복사 버튼**(R8 신설)으로 공고 확정(A1 착수 판단) → 채팅에 붙여넣으면 그것이 곧 `start` 실행 통로다(클릭 실행 아님). **run 시작 후엔 카드가 현황(다음 단계)+이어가기 CLI 명령을 표면**해 자연스럽게 CLI로 넘긴다(2026-07-15). ⚠️ **클릭형 실행 트리거(옛 "제안서 생성" 버튼=`/api/render`, 스토리라인 복붙=`/api/storyline-prompt`, 발산 라우트 2종)는 W31에서 전부 제거·Reuse 격리됨** — 정본 실행 통로는 CLI `go`뿐이다.
- **모드 = `start`에서 정한다**(대시보드 진입과 무관): `direct`=세션 LLM/Codex가 분석·스토리라인·정련을 관통(복붙 없음, 기본값) / `secure`=외부 LLM 복붙 왕복(내부 데이터 미노출 — 자동 익명화는 격리됨, §1 참조).

- 반자동화의 정의: 무인이 아니라 — LLM이 산출물을 만들고 **사람은 관문에서 검수·Go**만 한다.
- **대시보드→CLI 핸드오프(2026-07-15)**: 공고 카드에 상태머신 **현황**(다음 단계 라벨)과 **이어가기 CLI 명령**(복사 버튼)을 노출한다 — 대시보드에서 시작해 자연스럽게 CLI로 넘어가고, 이후 대시보드는 현황을 보여주는 흐름(선택 관문 2개는 CLI `go`에만 — 사용자 결정). 정본 = `dashboard/server._run_status_summary`(pipeline_state.resolve 재사용, 엔진 신규 0).
- 대시보드 백로그(비차단): 레퍼런스 선택 UI, ~~status/next 시각화(N4)~~ → **기본 완료**(카드 현황+핸드오프), run_render의 --skins/--pptx-mode 노출.

## 5. 디렉터리 지도

| 경로 | 용도 |
|---|---|
| `app/` | 렌더 엔진 + design_checks + codex_runner.py(공용 Codex 단발 위임 러너, W31 신설) — anonymize_hook은 W31에서 Reuse 격리(엔진계층에서 빠짐) |
| `packs/` | core(중립 코어·기본) — 렌더러가 바인딩하는 어휘. 강의 팩은 공개판에서 제외 — 격리 하우스(house_a·house_b)는 `<개발 원본 전용 경로>`로 완전 이전(로컬에 `packs_excluded/` 없음) |
| `proposal_system/scripts/` | **파이프라인 본체**: proposal_pipeline.py(동사 3개)·pipeline_state.py·design_brief.py·deck_review.py·storyline_prompt.py·design_contract.py(W31 R2·R5)·journey_folders.py(W31 R7). `cinematic.py`는 W31에서 Reuse 격리(제거) |
| `proposal_system/workspace/runs/` | run 산출물(gitignore) — `journey/` 단계 폴더 포함(W31 R7) |
| `dashboard/` | 전체 공정 1급 진입 표면(:8754, secure 전용 아님·§4)·나라장터 선별 UI + test_smoke.py |
| `scheduler/` | 무인 정기수집(collect_job.py)·친구 워처(watch.py) |
| `tools/` | port_design_guide.py(가이드 임포터)·piece_catalog.py(조각 어휘 사전 보존) — `proper_noun_sweep.py`는 W31에서 Reuse 격리(secure 익명화 동반 이동) |
| `skins/` | 결정론 tokens 스킨(`_meta.provenance`=기록용·`self_contained` 명시) |
| `CONTEXT/` | 오케스트레이션 레이어(§6) |
| `_source/` | 원본 실험실(heavy). **인덱스만, 전체 훑기 금지.** |

## 6. 오케스트레이션 / 친구 협업 레이어 (`CONTEXT/`)

- **공정 안내는 문서가 아니라 `status --run`이 한다.** RESUME/plan/state는 역사 기록(§9).
- `agents/<codex|gemini>/{inbox,outbox}.md` — 친구 메시지 버스. `agents/CONTROL.md` — 친구 제어 정본.
- ⚠️ **협업은 단계 다이얼**: `CONTEXT/collab_state.json` tier. **0 SOLO**(기본)=Claude 단독 · **2 ACTIVE** · **3 UNATTENDED**. 단발 위임(예: Codex 이미지 생성)은 다이얼 무관. 변경은 사용자만. 정본 = `CONTEXT/COLLAB_TIERS.md`.

## 7. 재사용 도구 (이 프로젝트 밖)

범용 협업 도구는 **`<개발 원본 전용 경로>`**(독립 git): trim_outbox.py·watch.py·monitor/. 모니터는 공통 런처 — `monitor_start.bat "<개발 원본 전용 경로>"` / `monitor_stop.bat`, `.port` reuse.

## 8. 현재 상태·정책 (2026-07-08 공정 재정의 완주)

- ✅ **트랙 ①길·②덱·③출력 전부 완료** (W1~W4·W-anon, 커밋 `0a07f5c`→`7973f93`, main 병합됨): 상태머신+동사 3개, 브리프 입구, 디자인 브리핑, Codex 이미지 공급, design_checks, 승인 전 LLM 평가, 시네마틱 파생, secure 익명화 왕복, 이미지 PPTX. **스모크 29/29.**
- 설계 정본 = `CONTEXT/NORTHSTAR_REDESIGN.md`(북극성·진단·결정 기록). 세션 인계 기록 = `<개발 원본 전용 경로>`.
- ⚠️ **"스모크 통과"가 "UI 경로 검증"은 아니다**: 스모크는 모듈 단위만 돈다. 종단 주장을 하려면 실제 관문을 밟아라. 같은 원리 — **산출물이 없으면 실행된 것이 아니다**(W4 교훈).
- 남은 후속(비차단): 실전 공고 1건 start→go→ship 완전 종단 · design_checks 임계값 사람 대조 · 시네마틱 모드별 임계값 · 대시보드 status 뷰 개조(N4).
- 친구 협업 기본 tier 0 SOLO. 공유뇌(Obsidian) 유지. 검증 원칙: **자기보고 불신 → 코드/로그/테스트로 검증.**

## 9. 문서 인덱스 — 살아있는 문서 vs 역사 기록

**살아있는 문서 (여기만 보면 된다):**

| 목적 | 문서 |
|---|---|
| **여기부터(트리거)** | `README.md` |
| **전체 매뉴얼** | `MANUAL.md` (이 문서) |
| **지금 공정 위치·다음 할 일** | ~~문서 아님~~ → `status --run <run>` (코드가 답한다) |
| **공정 설계 정본·결정 기록** | `CONTEXT/NORTHSTAR_REDESIGN.md` |
| 디자인 디렉터(stage9) 스펙 | `CONTEXT/DESIGN_DIRECTOR_PASS.md` |
| 대시보드 사용법 | `QUICKSTART.md` |
| 스킨 추가 | `SKIN_INTEGRATION.md` (내부: `DESIGN_GUIDE_PORTING.md`) |
| 친구 제어 | `CONTEXT/agents/CONTROL.md` · 협업 다이얼 `CONTEXT/COLLAB_TIERS.md` |
| 에이전트 부트스트랩 | `CLAUDE.md` · `AGENTS.md` · `GEMINI.md` |
| 튜토리얼(7관문 정주행) | `docs/`(mkdocs) |

**역사 기록 (콜드스타트 진입점 아님 — 과거 결정의 근거를 찾을 때만):**

| 문서 | 성격 |
|---|---|
| `CONTEXT/RESUME.md` | 2026-06~07 세션 인계 카드 누적(공정 서사는 status로 대체됨) |
| `CONTEXT/QUALITY_PLAN.md` | Phase 1~3 품질개선 설계·실측 기록 |
| `CONTEXT/plan.md` · `state.md` | M1 계약·상세 로그 |
| `proposal_system/docs/PIPELINE.md` | 1~8단계 원 설계 |

## 9.5 와이어프레임 루프 (W21, 결정 10 [3]·결정 12 — `go` 자동 편입: ✋② 후 자동 진입)

**형태 결정 = 원전 표현원칙의 몫** (하우스 지식 아님). 내용 동결(✋②) 후, 테마(stage9) 전.
**go 자동 오케스트레이션 편입**: ✋② 통과 후 `go`가 `wireframe_bundle`(프롬프트→정지·핸드오프)→[결정기 LLM이 `wireframe.json` 수거]→`wireframe_apply`(검증·병합·무채 재렌더)를 자동 진행한다. `decision` 체크포인트가 게이트 — 동결 전 탐색 루프에선 wireframe이 `go`의 next로 뜨지 않는다. 서브커맨드(`wireframe --bundle/--apply`)는 그대로 살아 있다(수동 루프·재적용용).

- `wireframe --run <run> --bundle` → `run/wireframe_prompt/prompt.md`(동결 내용+어휘 frame 7·piece 25+R1~R9+스키마, 자기완결). 결정기(LLM)가 장별 메시지 유형(수치/비교/구조/성과/서사)을 판별해 frame×piece를 결정한 `wireframe.json`을 run 루트에 쓴다. **내용 불변**(binds/기존 값 재배열만), 없는 형태는 `catalog_gap` 선언.
- `wireframe --run <run> --apply` → 계약 검증(오류=중단·SSOT 안전 / R1·R2·R9·requires=경고 표면화) → deck.json 병합(`deck.pre_wireframe.json` 백업) → **무채 core 재렌더** → 재게이트(`gating_report.wireframe` 블록: selected_by·조합 통계·layout_groups·갭 / `applied_axes.html.wireframe` / design_checks·리듬 재실측).
- 루프 = 결정기 재실행+재적용(싸게 반복). [4] 테마의 조정권은 T1(토큰)/T2(파라미터·rendition)/T3(구조=이 루프 재진입만) — `CONTEXT/W21_CATALOG_REBUILD.md` §4.5.
- **지식 색인 동봉(W27 P4, 2026-07-15 — pull의 배선 강화)**: `wireframe --bundle` 프롬프트에 **와이어프레임 층 카드 색인(name+claim 한 줄×44)이 결정론으로 실린다**(pull을 세션 기억에 맡기지 않음 — 루트=config `knowledge.reference_images_root`, 부재 시 "색인 없음" 명시). **`테마/`(색·폰트)는 절대 미포함**(누수 차단). 결정기는 장별 적용 카드를 `knowledge_cards`로 인용하고, apply가 `gating_report.wireframe.applied_knowledge`에 기록한다(적용 관측 가능).
- **✋ wireframe_review human 관문(W27 P4)**: `wireframe --apply`(무채 재조판) 후·design_brief 전 정지 — 대시보드 [검토 완료]/[건너뛰기]만 통과(--confirm 무효). **재무장 감시 = wireframe.json** — 결정기 재실행·T3 재진입 등 뼈대가 갱신될 때마다 관문이 다시 뜬다(업데이트마다 정지). design_brief가 이미 있는 레거시 run엔 첫 표면화가 뜨지 않는다.
- **🔬 form_intent 통로 (W32 마찰36 — 시험 적용, 되돌림 조항 발효 중)**: 스토리라인 계약에 `form_intent`(장별 형태 의도, 선택)·`art_note`(분위기 메모, 선택)가 등재됐다 — 스토리라인 단계가 `디자인지식/와이어프레임`을 pull 하게 되면서 생성 LLM이 형태 의도를 남길 수 있게 된 것(실측 근거: 지식을 실은 세션은 계약에 키가 없어도 `visual`을 스스로 적었다 — 강의 덱 60장). 결정기는 이를 **권장 입력**으로 받아 원전 원칙과 대조한다(그대로 베끼면 실패 신호). `art_note`는 이미지 프롬프트의 명시 구획으로만 전달되고, `visual`·`evidence`·`supports_axis` 등 **작업용 키는 이미지 프롬프트 덤프에서 필터**된다(내부 어휘 유출 차단 — 마찰29·31 계열). 정본·되돌림 기준 = `CONTEXT/REHEARSAL_FRICTIONS_W31.md` 행 36(가역: config 한 줄 원복이 1차 스위치).

## 9.6 디자인 고도화 루프 (W23, 결정 15·16·17 — ④ 기본 디자인 후·`go` 자동 편입)

**다짜고짜 디자인하지 않는다.** ④ 기본 디자인(stage9) 후·평가(deck_review) 전 위치. 정본 = `app/render/design_spec.py`(wireframe.py의 자매 — 같은 문법: 오류=계약 위반·SSOT 안전 / 경고=표면화·catalog_gap).

- **(a) 목표 명세** `refine --run <run> --bundle` → `run/refine_prompt/prompt.md`(deck.json 현행 형태+design_brief 요약+frame 7·piece 25 어휘+스키마, 자기완결). 명세자(LLM)가 **장표별 디자인 목표를 텍스트로 먼저** 쓴다(무엇을·왜=`goal`, `treatment`, `image_kind`[evidence|mood|conceptual|none — **none은 `none_reason` 필수·none 아니면 `source_route` 수급처**(W27 P2)], `knowledge_cards`[적용할 디자인지식 카드 슬러그 — W27 P1a], `form_needs`[형태 축 질의 — 의미 범주 아님], `content_gap`[디자인이 내용을 더 요구하면 여기, 임의 창작 금지])을 `design_spec.json`으로 run 루트에 수거.
- **(b+) 레퍼런스 실물 수집(W27 P1a)**: `--collect`가 `knowledge_cards` → 카드 `examples:` 링크 → (비면) 카드 자신 `source:` 순으로 **레퍼런스 jpg를 `run/design_refs/knowledge/`에 복사**(카드당 6장·멱등, 루트=config `knowledge.reference_images_root`). `refs_manifest.knowledge_refs`에 claim·조작적정의(`watch_for`)·갭 기록. 핸드오프 번들에 "레퍼런스 실물 (반드시 보고 작업)" 섹션으로 실린다 — 텍스트 claim만으로는 시각 정보가 0비트라는 실증(배경 네모상자 사건) 후속.
- **(b) 레퍼런스 결정론 수집** `refine --run <run> --collect` → design_spec.json 검증(오류=중단) → `form_needs`의 (kind,id)를 형태 축으로 조회해 `run/design_refs/`에 piece 프리뷰 png 복사(frame은 정의 요약만, file=null) + `refs_manifest.json`(레퍼런스↔장표 목적 추적성). 미지 형태는 지어내지 않고 `catalog_gap`으로 표면화.
- **[사람 체크포인트]** design_spec.json + design_refs/를 검토·조정 — 완성 디자인보다 **먼저, 값싸게** 고친다.
- **(c) 실행 핸드오프** `refine --run <run> --handoff` → `run/refine_handoff/prompt.md`(계약 5조: 내용 불변·정직성 장치 보존·evidence 생성 시 딱지 필수(W27 D6)·산출물 회수 2택·content_gap 임의보강 금지). **⚠ human 관문(W27 P0)**: `design_refs` ack(대시보드 검토/건너뛰기 버튼) 없이는 `--handoff`가 비0 종료 — `go --confirm`도 무효. `design` 게이트(approve/ship)도 동일. 실행자(Claude Design 등)의 산출물 회수는 **기존 채널 재사용**: (A) `design_overrides.json` 확장 → `stage9 --apply`로 검증·병합(권장) 또는 (B) 완성 HTML → `approve --ingest`로 diff 심판·freeze.
- **지식 pull(§2, 층 격리 유지)**: 명세자가 목표를 쓸 때 **필드별로 조회 폴더를 가른다** — `form_needs`(형태 축)는 `ref/디자인지식/와이어프레임/`, `treatment`·`image_kind`(색·이미지·장식)는 `ref/디자인지식/테마/`(22)만. `examples/`는 링크로만. 한 단계에 두 층을 다뤄도 **필드↔폴더 매핑**으로 색↔형태 격리가 산다. 자동주입 아님(pull).
- **go 자동 오케스트레이션 편입**(와이어프레임과 같은 위치): stage9(④) 적용 후·평가(deck_review) 전 `go`가 `refine_bundle`(프롬프트→정지·핸드오프)→[명세자 LLM이 `design_spec.json` 수거]→`refine_collect`(검증·레퍼런스 수집→**사람 검토 1회 정지**)→`refine_handoff`(실행 핸드오프→정지)를 자동 진행한다. `design` 게이트가 게이트 — 이미 승인된 run엔 소급 요구하지 않는다. 핸드오프는 선택적 정련이라 산출물 없이 `go`를 다시 쳐도 평가로 진행한다. 서브커맨드(`refine --bundle/--collect/--handoff`)는 그대로 살아 있다.

## 9.7 기관 조사 서브스텝 (W26, 목표조정 8·9 — 분석[1] 안의 선택지)

**같은 조사 1소스에서 내용과 형태가 함께 나온다.** RFP 첨부 파싱만으로는 발주기관의 미션·건학이념·특성화 같은 "문서 밖 근거"(P1.3: 발주처의 숨은 관심사는 문서 밖에서 수집해 도입에 직인용)를 모을 수 없다. 정본 = `app/render/institution_research.py`(wireframe.py·design_spec.py의 자매).

- `research --run <run> --bundle [--institution <이름>]` → `run/research_prompt/prompt.md`(조사자 LLM/사람에게 발주기관 공개 조사를 지시 — 미션·건학이념·특성화·직인용 후보·브랜드 토큰[대표색 hex·서체·로고 소재 URL, 다운로드 금지]). 기관명 미지정 시 분석카드의 발주처 행에서 추정. 결과는 `institution_research.json`으로 run 루트에 수거.
- `research --run <run> --apply [--skin-id <id>]` → 검증(오류=중단: institution·sources 없으면 직인용 불가 / 경고: content_hooks의 source 없음=출처요망) → `brand_tokens.colors.primary` 있으면 `skins/<id>.json` 등록(대표색→렌더러 navy·accent→orange 어휘 승격) + `design_brief.skin.skins`/`brand.client_name` 자동 승계.
- 직인용 훅 요약은 message_map/storyline 핸드오프 번들에 자동 동봉(design_brief 동봉과 같은 패턴) — 도입 직인용·홍보 축 정합에 바로 쓰인다.
- 웹 조사 자체는 이 서브스텝의 몫이 아니다(LLM/사람) — 파이프라인은 프롬프트 번들·검증·스킨 생성만 한다(결정론). **의무화는 아니지만 이제 `go`가 [1]에서 선택 관문으로 한 번 제안한다**(bid 모드·조사 전, 결정 2026-07-14 "B" — §2 선택 관문 ⒜). institution_research.json이 있으면 자동 충족. 건너뛰기 = `go --confirm`.

## 9.8 이미지 렌더 라우트 (W28, D8~D13 — `image_infographic`: 장표를 이미지가 통째로 그린다)

**렌더 2분기.** ✋②(내용 동결) ack 화면에서 `render_route`를 고른다(→`run/render_route.json`, 대시보드/`set_render_route`가 기록). 두 라우트의 상류(storyline·wireframe·message_map)는 완전 공유 — 렌더러만 갈린다.
- **`image_infographic`(메인 — W29 승격, 2026-07-20 사용자 결정)**: `imagedeck` 관통(하이브리드 크롬 §9.8.1). **신규 run은 `start`(init)가 이 라우트를 기본 기록**하며, ✋②에서 사람이 바꿀 수 있다. 정본 = `proposal_system/scripts/imagedeck.py`. 최종 pptx는 ship `--pptx-mode image`(파일럿 실증 완료).
- **`html_editable`(보조 — `CONTEXT/JOURNEY.md` Part C 표기로는 "수정형 pptx 루트", 조건부 존치)**: 기존 stage9→refine 루트. 편집 가능한 산출물(HTML·pptx native)이 꼭 필요할 때 — 사용자가 LLM에 명시 요청한 경우에만 열고, 열 때 "완성도 낮음"을 먼저 고지한다(JOURNEY Part C). **레거시 run(render_route.json 없음)은 이 경로**(하위호환·바이트 동일).

**B1 테마 확정 = `run/design_contract.json` (W31 R2·R5 신설, 정본 = `proposal_system/scripts/design_contract.py`)**: 전역 스킨(차용 없으면 중립 템플릿 `skins/_neutral.json`)+design_brief+run 조정을 병합한 **run별 1회성 디자인 정본**(`chrome_contract`=HTML/pptx 조립 전용·`image_contract`=이미지 프롬프트 주입 전용, 2계약 분리). bundle/compose가 소비하는 유일한 디자인 정본 — 전역 `skins/*`를 직접 프롬프트에 요약 주입하던 옛 방식은 대체됨. **`theme_confirm` 게이트**(선택 관문·스킵 가능)가 동결 확인을 담당한다. 스킨(창고)은 **졸업본**(프로젝트 종료 후 `curate`로 등록)이며 시스템이 자동 적용하지 않는다 — **inkline 자동 폴백은 W31에서 제거됨**(차용 없으면 중립 템플릿에서 시작). 창고 입고 경로 2개: ①졸업(끝난 run의 design_contract를 `curate`로 등록) ②외부 이식(잘 만든 외부 덱을 `add-skin`으로 분해해 반입) — 용어 정의 상세는 `CONTEXT/JOURNEY.md`.

공정(전부 `go` 자동 편입, 정지는 `_next_step`이 판단):
- `imagedeck --run <run> --bundle` → `run/imagedeck_prompts/NN.md`(장별) + `imagedeck_manifest.json`. storyline+wireframe+design_contract를 프롬프트로 결정론 조립. **캔버스 역산(D12)**: 생성 px = export − 크롬밴드(스킨 `chrome.header_h/footer_h`, 0이면 export 그대로). **wireframe 모드(D13)**: `on/off/auto` — `off`면 `go`가 뼈대(bundle/apply/review)를 통째 스킵. A/B 승격 = `--ab <장번호>`(on/off 두 벌). **프롬프트 오버레이(W31 R6)**: 사람이 `run/journey/.../imagedeck_prompts_local/NN.md`에 장별 추가 지시를 얹으면 재번들에도 살아남게 병합 주입된다 — 페이지별 JSON 분리 대신 이 통로로 수정. **작업용 키 필터(W32 마찰36⑸)**: storyline 덤프에서 `visual`·`form_intent`·`evidence`·`supports_axis`·`deck_class` 등 내부 키를 걸러 싣는다(종전에는 통째 `json.dumps`라 세션 작업 메모가 생성기에 유출됐다). `art_note`만 "Art-direction note" 명시 구획으로 전달(의도 참고 — 결정값은 계약이 우선).
- ✋ `imagedeck_prompt_ack`(사람 전속·건너뛸 수 없음, W30) — **생산 전** 장별 프롬프트(`imagedeck_prompts/`)와 레퍼런스 이미지를 확인·수정하는 관문. 기대와 다른 이미지에 토큰을 태우기 전에 방향을 확정한다. 프롬프트·스킨·레퍼런스 수정 후 재번들하면 **재무장**(감시=manifest). 승인=대시보드.
- `imagedeck --run <run> --produce` (W29 승격) — 미생산 이미지 장을 Codex에 순차 단발 위임(D9)·장별 px 즉시 실측·재실행 안전(있는 장 skip). `--only 3,5`로 국소 재생성, `--timeout`(기본 900초/장). direct 모드 `go` 정지 안내가 이 명령을 가리킨다. (secure 모드는 종전대로 프롬프트 수동 반출.) **codex CLI 미감지면 수동 생산 루트로 자동 전환**(가이드를 여정 09 폴더에 생성, 복붙→`--adopt` 수거 — §9.8.3 부록).
  - **모델·effort (W32 마찰33)**: `--model`/`--effort`로 오버라이드한다. 미지정 시 모델은 러너 기본값(`gpt-5.5`), **effort는 produce 한정 `low`**다 — A/B/C 실측(2026-08-02) 결과 **시간 주범은 모델이 아니라 effort**였다(5.5/high 4:10/장·위반0 · 5.5/low 2:14/장·위반0 · luna/high 2:26/장·**위반 33%**). 텍스트 경로(`stage9 --fill-images`)의 기본값 `high`는 불변. produce 시작 시 `모델=… · effort=…`를 콘솔에 찍어 조용한 기본값 대신 사람이 판단할 통로를 준다.
  - **실패분 재위임 (W32 마찰34)**: px 불일치 장은 불량본을 **`<이름>.rejected[N].png`로 개명**해 남긴다 — 증거는 보존하되(무엇이 왜 틀렸는지 눈으로 대조) skip 판정(존재 기반)을 벗어나 **재실행하면 그 장을 다시 위임**한다. 종전에는 불량 파일이 그대로 남아 `생성 0 · skip N`이 되어 자기 안내("재실행하면 실패분만 다시 위임")와 모순됐고, 탈출구가 "산출물 손삭제"(금지 원칙과 충돌)뿐이었다. 반려본은 생산 장수 집계·`--export` 반출에서 제외된다.
  - **진행률 (W32 마찰27)**: `status`가 `이미지 5/20장 생산됨 — 나머지를 이어서 그려야 한다(재실행하면 미생산 장만 처리한다)`로 표시한다(판정 로직 불변·표시만). 장당 수십 초~수 분 × 20장이라 중단·재개가 잦은 구간인데, 종전에는 "생산 이미지가 아직 없다"만 말해 돌아온 사람이 처음부터 다시 도는 줄 알았다.
- `imagedeck --run <run> --collect` → PNG 헤더 px 실측(stdlib·신규의존성 0)·커버리지·파일명 검증. 불합격(px 불일치·누락)이면 `go`가 루프 없이 정지하고 재생성 지시(`collect_report.md`).
- `imagedeck_ack`(사람 전속 관문·건너뛸 수 없음): 이미지 정독 후 채택. **검수는 선택** — 대시보드에서 `[🔍 Claude 검수 요청]`(→`imagedeck_review.md` scaffold, 세션이 이미지 Read 후 정본 대조) 또는 `[바로 정독·채택]`. 이미지 갱신(재번들·재수거)마다 **재무장**(감시=manifest/collect).
- `imagedeck --run <run> --compose` → `deck.images.html`(크롬=상단 제목·하단 발주처/제안사 로고 밴드[D11 실자산 필수·생성 금지], 본문=이미지). 이후 디자인 게이트·`ship --pptx --pptx-mode image`(deck.images.html 래스터) 합류.
  - **검토·발표 표면 = `<deck-stage>` (W32 마찰35, 2026-08-02 채택)**: 이 파일은 이미지 장표 승인 관문의 **공식 검토물**인데 종전에는 `width:1920px` 고정이라 전체화면에서도 넘쳐 브라우저 축소로 우회해야 했고 키보드 넘김도 없었다. 이제 컴포넌트를 **HTML에 인라인**한다 — `transform:scale` 화면 맞춤(레터박스)·**화면 단위 페이징**(활성 장만 표시, 나머지 `visibility:hidden`이라 상태 보존)·썸네일 레일·`←/→`·`PgUp/PgDn`·`Home/End`·숫자키·발표자 노트·인쇄 시 장당 1페이지 PDF.
  - **발표 모드(두 창 동기화)**: 창 두 개를 열고 URL 뒤에 `?present`(발표자 — 송신) / `?clean`(전면 — 수신·레일 자동 off)을 붙인다. `BroadcastChannel` 주 + `localStorage` 폴백 이중화. **⚠️ 같은 브라우저 안에서만** 오간다 — 서로 다른 브라우저 둘(Chrome↔Edge)은 원리상 불가이고 그건 서버가 필요하다.
  - **서버 불필요**: 자기완결 HTML이라 `file://` 더블클릭으로 연다. 무서버 실증(2026-08-02) — 컴포넌트 등록·맞춤·키 페이징·두 창 동기화 전부 동작, 실물 run 덱(19장)에서 콘솔 오류 0.
  - 원본은 `app/render/vendor/deck-stage.js`(**수정 금지** — 고칠 일은 `app/render/viewer.py`에서 감싼다, 경위는 `vendor/README.md`). ⚠️ **인라인 함정**: 원본 주석에 닫는 script 토큰이 있어 이스케이프하지 않으면 HTML 파서가 스크립트를 거기서 끊어 **조용히** 깨진다. **PNG 래스터라이즈(덱 프리뷰) 경로는 컴포넌트 비활성** — 활성 장만 보이고 축소돼 실물 px가 어긋난다. `deck.html`(htmlgen)은 `100vh` 스크롤 스냅이라 종전 내비 유지(별도 축).

### 9.8.1 하이브리드 크롬 · 장 클래스 (W29, D14 — 스킨 `inkline`)

**스킨이 `slide_classes`를 선언하면**(정본 예 = `skins/inkline.json`) 이미지 라우트가 **하이브리드**로 동작한다 — 헤더(섹션배지·제목·부제·제안사 로고·flag 딱지)와 푸터(발주처 로고·프로젝트명·페이지)는 **HTML 크롬이 조립**하고, **이미지는 본문 콘텐츠만** 그린다. 미선언 스킨(quartz)은 종전 그대로(전 장 통짜 이미지 — 하위호환 게이트).
- **장 클래스 5종**: `content`(기본 — 본문만 이미지, edge-to-edge로 생성하고 여백은 HTML `chrome.body_margin`이 고정 예약[페이지간 좌우 여백 일관성] — inkline은 1792×784) · `full_image`(전체 이미지 + 오버레이 푸터, storyline `deck_class`로 지정) · `cover`/`toc`/`divider`(**풀 HTML** — 프롬프트 없음, compose가 storyline에서 렌더. template_id `cover_slide`/`toc`/`divider` 자동 매핑).
- **flag 승격**: `[예시]`·`검토요망`이 content 장에서는 이미지가 아닌 **HTML 딱지** — 실데이터 확정 시 이미지 재생성 없이 딱지만 제거.
- **유연성 계약**(같은 덱 안 변주): 푸터/헤더 높이 = 클래스 spec·장별 `chrome_override`(장별 기대 px가 manifest·collect에 따라감) · 바깥 프레임 띠 = 스킨 `chrome.frame`(**inset 밴드** — 오버레이 금지, 안쪽 전체·이미지 px가 역산 연동돼 콘텐츠 가림 없음) · 구간별 스타일 전환 = 스킨 `variants` + storyline `style_variant`(크롬 CSS 변수 오버라이드) · 배경이미지 = HTML 장(표지·목차·간지)은 `fields.background_image`가 z-바닥 레이어+스크림, content 장은 같은 필드(또는 덱 공통 `chrome.frame.image`)가 **바깥층 배경**이 되어 띠·본문 여백으로 자연스럽게 비침(.inner 투명화). 레이어 구조 `.slide(띠/배경)>.inner>[.bg]>크롬/본문`.
- 검수 대조표에 크롬 분리 항목 추가(제목·배지가 이미지 안에 **중복되면 fix**). 스모크 = `HybridChromeSmoke`.
- **하이브리드 pptx = 정본 산출물 (W30, 사용자 결정 2026-07-20)**: `imagedeck --run <run> --compose-pptx` → `deck.images.pptx` — 크롬(배지·제목·부제·푸터·페이지)과 표지·목차·간지를 **pptx 네이티브 텍스트박스·도형**으로 조립(PowerPoint에서 직접 수정 가능), 본문 콘텐츠 이미지만 픽셀. deck.images.html과 같은 정본에서 결정론 조립(스킨 토큰·variants·frame 띠·배경이미지 동일 반영). **image 라우트에서 `ship --pptx`의 기본 산출(deck.pptx)이 이 하이브리드**이며, 전량 픽셀본이 필요할 때만 `--pptx-mode image`.

### 9.8.2 덱 우선(Deck-First) 아키텍처 — 디자인 SSOT = HTML 틀 (W28 DF1~DF6, 2026-07-24 구현 완료)

**디자인 정본은 하나뿐 — `design_contract.json`의 `chrome_contract`(HTML/PPTX 조립 틀)다.** 강의 덱 실전(`CONTEXT/LECTURE_DECK_FRICTIONS_2026-07-24.md`)에서 "덱 디자인용 값"과 "이미지 프롬프트 주입용 값"이 각기 SSOT를 주장해 품질이 요동친 것(L5·L6·L9·L10)을 구조로 해소한 재설계다. 상세 스펙·마찰 근거 = `CONTEXT/DECK_FIRST_DESIGN.md`(정본, ①~⑦ 확정 모델).

- **프롬프트 다이어트(DF1, `3d1d869`)**: 이미지 프롬프트에서 테마(색·폰트·레이아웃) 정의를 뺐다 — 프롬프트에 남는 건 **행동 규칙**(캔버스 px·정직성·바인딩·텍스트 무결성·분량/오버플로 정책)뿐. 색·폰트·배치는 HTML 틀(chrome_contract)의 몫.
- **자산 슬롯**(`decor_slots` — 배경 외 장식 자산의 위치·크기·경로 계약, DF2 `dcfd6e0`): `chrome_contract.decor_slots`에 코너 장식 등을 선언하면 HTML·PPTX 양쪽 compose가 공용으로 렌더한다. 장 클래스별 opt-out 가능, 자산 부재 시 조용히 넘어가지 않고 경고.
- **마스터 자산 동결**(DF3 `3e5af7b`, R10과 연동 — `CONTEXT/JOURNEY.md` B1): `imagedeck --master-apply`가 확정 마스터 시안의 배경 PNG·장식을 `chrome_contract.chrome.frame.image`/`decor_slots`로 동결한다 — "디자인 타임 1회 생성 → 사람 검수 → 동결"이라는 기존 마스터 시안 절차에 배경·장식 자산 생성이 편입됐다. 확정 자산은 `curate --sync-master --run <run>`으로 design-assets 레인(`CONTEXT/DESIGN_ASSETS_LANE.md`)에 싱크백할 수 있다(선택).
- **덱 프리뷰**(`imagedeck --run <run> --preview`, DF4 `cbc0511`): 계약 동결 후 "틀+배경(본문 비움)" 완성 슬라이드를 장 클래스별로 실제 렌더해(**playwright/chromium 정식 채택** — 미설치면 명확한 오류로 중단) `imagedeck_refs/deck_preview/<class>.png`에 저장한다. 레퍼런스 조회가 3계층(slide>global>seed)에서 **4계층**(slide>global>**deck-preview**>seed)으로 확장 — 개별 지정이 없는 장은 "자기가 끼워질 완성 틀"을 실물 레퍼런스로 자동 받는다(`resolve_slide_refs`).
- **마무리 오버라이드**(`run/deck_overrides.json`, DF6 `fd1ffec`): 특정 장만 storyline 재동결 없이 색·`style_variant`(ⓐ 재조립만으로 반영·본문 px 불변) 또는 `chrome_override`/`deck_class`(ⓑ 구조 변형 — 본문 생성 px가 바뀌어 재생성 필요, `collect`의 px 실측이 안전망)를 조정하는 "오버레이 수정 → 재조립" 루프. `bundle`/`compose`가 콘솔에 장별 ⓐ/ⓑ 분류를 안내한다. 파일이 없으면 조립 결과는 이전과 바이트 동일(하위호환).
- **R10 마스터 시안(`CONTEXT/JOURNEY.md` B1, "덱 마스터 디자인 공정")**: 테마 확정을 "계약 값 동결"에서 **실물 룩 확정**으로 승격 — 발주처 브랜드(기관 조사)+자사 아이덴티티+주제 적합색+사용자 레퍼런스+디자인지식 pull을 종합해 마스터 시안(공통 배경·크롬·대표 장 1~2개 실물)을 만들고, `theme_confirm` 관문에서 사람이 검토한 뒤 위 `--master-apply`로 계약에 동결한다. 확정 시안은 시리즈 레퍼런스로 등록되어 이후 전 장 생성에 자동 동봉된다(시리즈 일관성의 근본 장치). 진입 루트는 내용 선행(기본)·디자인 선행·급행(스킵) 3갈래(상세는 JOURNEY B1·R10).

### 9.8.3 수동 이미지 생산 루트 (W32 — codex/agy CLI 없는 사용자, 부록)

**파이프라인의 이미지 계약은 "누가 그렸는가"가 아니라 "정확한 px의 PNG가 매니페스트 `out_name`으로 `imagedeck/slides/`에 존재"뿐이다** — codex는 그 파일을 만드는 드라이버 하나일 뿐이므로, CLI가 없는 환경에서는 사람이 같은 계약을 손으로 이행한다. 이후 공정(`--collect` 검증 → `--compose` 조합)은 경로 무분기로 동일하다.

- **자동 감지·전환**: `imagedeck --bundle` 말미와 `--produce` 진입 시 `codex`/`agy` CLI를 감지(`imagedeck.detect_producers`, `shutil.which` 실측)한다. codex 미감지면 `--produce`는 **실패가 아니라 경로 전환**이다 — 수동 생산 가이드를 여정 폴더에 만들고(아래) 절차를 안내한 뒤 종료 0(+state에 `imagedeck_manual_guide` 기록). agy는 참고 감지만 한다(이미지 생산 러너는 codex 전용 — agy 이미지 생성은 미실증이라 배선하지 않음, speculative 금지).
- **가이드 = 여정 폴더 산출물**: `run/journey/09_이미지생산/이미지_수동생산_가이드.md` — 절차 5단계 + 장별 표(프롬프트 파일·최종 파일명·기대 px·**상태 실측**). `--manual-guide`로 언제든 재생성(상태 열 갱신), `--adopt`가 끝날 때마다 자동 갱신. journey 09 `_여기서-할-일.md`도 가이드 존재 시 수동 루트 안내로 바뀐다.
- **절차 요약**: ①`imagedeck_prompts/NN.md`를 이미지 생성 LLM(ChatGPT·Gemini 등)에 복붙 — **Reference roles의 레퍼런스 이미지는 채팅에 직접 첨부**(경로 문자열은 웹 LLM이 못 읽음), "저장 경로" 문구는 무시 ②생성 이미지를 한 폴더에 다운로드, **파일명은 장 번호로 시작**(`05.png`, A/B 장은 `05A.png` — png/jpg/webp 무관) ③`imagedeck --adopt <폴더> --run <run>` ④`--collect` → `--compose`.
- **adopt 수거 헬퍼**(`imagedeck.adopt`, Pillow 필수 — `pip install Pillow`): 파일명(장 번호 시작 또는 `out_name` 정확 일치)으로만 매칭하고 나머지는 unmatched 보고한다(브라우저 기본명 "image (3).png" 순서 추측 배치 금지 — 오배치 침묵 통과보다 거부가 낫다). 매칭분은 PNG 변환 + 기대 px로 비율 유지 cover-crop 리사이즈 + `out_name` 개명 후 배치. 이미 있는 장은 **교체**(replaced — produce의 skip-존재와 다른 문법: adopt는 사람이 파일을 넣은 명시 행동). `--only 3,5` 국소 처리 가능.
- **stage9(html_editable) 슬롯도 같은 원리**: `--fill-images`는 규약 경로(`run/stage9_design/slots/slide<키>_<슬롯id>.png|svg|jpg`)에 자산이 있으면 cached로 건너뛴다 — codex 미감지 시 degrade 사유와 수동 대안(직접 그 경로에 넣고 `--apply`)을 콘솔에 안내한다. 이쪽은 px 계약 없음.
- 스모크 = `W32ManualProduceRouteSmoke`(dashboard/test_smoke.py).

## 9.9 지식 체크 3+1 절차 (KC, 2026-07-24 확정 — 커밋 `e45b8ee`)

**경험설계지식이 새 참조 도메인이다** — 기존 `ref/디자인지식/`(형태·시각)과 별개로, 발주처·수혜집단이 겪는 여정·터치포인트·기회정의를 다루는 `ref/경험설계지식/`을 도입했다. 지식 pull은 여전히 search-first(§2 원칙과 동일 — 기계 자동주입 아님, 세션이 `obsidian_search`로 능동 조회).

- **① 기획 입구**: `decision` 관문 진입 전 message_map 핸드오프 프롬프트가 `ref/기획지식/`·`ref/경험설계지식/` pull 요구 문구를 동봉한다(`message_map.knowledge_pull_text`). 반영한 카드는 message_map.json의 기존 문자열 필드(전략 축 message·근거 슬롯 desc)에 대괄호 슬러그 인용으로 남긴다 — 스키마 변경 없음.
- **② 디자인 입구**: 기존 W27 P1a(§9.6 "(b+) 레퍼런스 실물 수집")가 이 자리를 이미 담당 — `refine --collect`가 `knowledge_cards`→카드 `examples:`→`source:` 순으로 레퍼런스 실물을 `run/design_refs/knowledge/`에 수집한다. KC는 이 기존 절차를 ①·③과 같은 3+1 모델의 한 지점으로 재확인할 뿐 신규 구현이 아니다.
- **③ 산출 출구**: `imagedeck_ack` 관문 직전 `imagedeck_review.md`(검수 scaffold)에 "지식 대조" 섹션이 자동 삽입된다(`imagedeck._knowledge_check_lines`) — 테마 카드 기준 역검사(강조색 과다·여백·위계)와 여정 논리 대조를 사람이 체크한다.
- **발동 = 단계 전환 1회**(반복 재발동 없음 — 매 `go`마다 다시 뜨지 않는다). **프로파일 연동**(`gates.json`, §9.8 위·`REHEARSAL_FRICTIONS_W31.md` 관문 다이얼과 동일 축): `standard`(기본)=①③ 수행·`express`=전부 생략(속도 우선)·`full`=③에 장별 샘플링 심화 문항 추가.
- **`검토_체크.md` 항목**: `decision`(①)·`imagedeck_ack`(③) 관문의 검토_체크.md에 지식 체크 확인용 정보 체크박스가 덧붙는다 — **판정에는 관여하지 않는다**(검토 완료/건너뛰기 판정과 별개, 순수 확인용).
- **온디맨드**: 위 3지점 밖에서도 사용자가 세션에게 **"지식 체크"**라고 트리거하면 그 자리에서 즉시 pull·대조를 수행한다(코드 트리거가 아니라 세션 관례 — 3고정 지점 + 1 온디맨드 = "3+1").

### 9.9.1 지식 원장 읽는 법 (`지식_사용.md` — W32 마찰30 개정)

원장 정본은 `run/knowledge_ledger.json`, 사람이 읽는 파생 뷰는 각 journey 단계 폴더의 `지식_사용.md`다(신설 경위 = `CONTEXT/JOURNEY.md` R11③). **덱에 반영된 지식은 두 종류이고 뷰에서 절이 갈린다**:

- **단계별 기록(pull)** = 세션이 vault를 조회해 쓰고 `knowledge_used`로 **신고**한 것. 카드마다 vault 실제 폴더를 병기한다.
- **구운 지식(baked)** = 조각(piece) 카탈로그에 **이미 구워져 있는** 원전 원칙. 조회 이벤트가 없어 pull 채널로는 안 잡히지만 장표에는 반영돼 있다(예: 목차 조각의 해소 근거 배지 = `[[목차는-상대의-두려움-목록이다]]`). 덱이 실제로 쓴 조각에서 **자동 도출**하며 신고물이 아니다 — 그래서 절을 분리해 표기한다. 관문 검토자가 "이 표기 왜 붙었지"의 출처를 여기서 찾는다. pull 기록이 0건이어도 표시한다(그때가 구운 지식이 **유일한** 반영 흔적이다).

두 가지 표시를 읽을 줄 알아야 한다:
- **⚠️ 1차 범위 밖** — 그 단계에 지정된 pull 폴더 밖에서 가져온 카드. **열람은 자유이므로 그 자체는 잘못이 아니다**(감사 표시일 뿐). 다만 정당한 참조가 매번 찍히면 경고가 무뎌지므로, 범위는 `pipeline.config.json`의 `knowledge_stages` 표에서 조정한다 — 2026-08-02 기준 기획지식 계열 4단계는 루트 `기획지식`을 포함한다(3WR 계열 핵심 카드가 하위 폴더가 아니라 루트에 있다는 vault 실측 반영). 판정이 prefix 매칭이라 **루트를 넣으면 하위 폴더도 전부 범위 안**이 된다.
- **⛔ 강등: vault 실물 미확인** — 카드 이름으로 vault에서 파일을 못 찾았다는 뜻이고 **지식으로 인정하지 않는다**(`status`/`go`의 지식 줄에도 건수·이름이 표면화된다). 실측된 원인 1위는 **유령노트**(Obsidian 인덱스에는 있는데 디스크에 `.md` 파일이 없음 — 메모리 `obsidian-mcp-md-extension-trap` 계열). 이때는 vault를 고쳐야 한다: 인덱스에서 본문을 회수해 실제 파일로 다시 쓰고, **디스크 실물로 대조**한다(인덱스는 이 상황에서 근거가 못 된다).

## 9.10 외부 콘텐츠 인입 규약 (구 DF7 — lecture 등)

강의 덱(`<개발 원본 전용 경로>`) 등 이 프로젝트 밖 콘텐츠를 만들 때도 **엔진은 이 저장소가 SSOT**다 — 엔진 함수를 조각으로 빌려오지 않는다. 정문은 **`start --brief` 인입 → 표준 공정(go) → `imagedeck --export DEST` 반출**뿐이다(memory `lecture-deck-reuses-hun_proposal-engine`: 엔진SSOT=hun_proposal·콘텐츠/트리거SSOT=외부 프로젝트).

- **포맷 정본**: `<개발 원본 전용 경로>` — 외부 콘텐츠를 브리프로 어떻게 정리해 넣을지의 계약.
- **금지선 4개**(강의 덱 마찰 L3·L8이 실측한 우회로 — `CONTEXT/LECTURE_DECK_FRICTIONS_2026-07-24.md`): ①엔진 함수 직접 호출(임포트해서 조각만 쓰기) ②수동 codex 호출(정규 경로 `imagedeck --produce` 밖에서 샌드박스 우회) ③산출물 손 수정(`deck.images.html` 등 — compose 재실행에서 소실, §9.8.2 "마무리 오버라이드" 채널이 정식 답) ④수동 사본 복사(엔진 산출물을 손으로 다른 저장소에 복사 — 재생성분이 사본에 반영 안 돼 조용히 낡음, 정식 답은 `imagedeck --export DEST`).

## 10. 종장 공정 상세 — stage9 · 평가 · 파생 (전부 `go`/`ship` 내부)

**stage9 = 렌더 후 비전 정련** (표준 공정, 옵션 아님). `deck.json` 본문(사실·수치·검토게이트) 불변, override는 append-only+css(SSOT 가드).

- **입력 4원천**: deck.json + 디자인 가이드(규칙층) + **스크린샷**(`stage9` 번들이 `deck.html`을 래스터해 `<run>/assets/slides/slide-NN.png`로 굽고 경로를 실첨부 — direct=세션이 Read / secure=사람이 첨부. playwright 없으면 "스크린샷 없음 — 텍스트만으로 판단 중"을 번들에 명시) + **design_brief.json**(의사결정 게이트 산출물 — 출력모드·스킨·리듬·이미지 슬롯 계획. 사람이 파일을 직접 수정하는 게 편집 UI).
- **디자인 게이트 2계층**(`gating_report.design_checks`): 정적 파싱(렌더 매회) + **브라우저 실측**(`design_checks.browser` — `stage9 --apply`·평가 직전에만. 오버플로 px·슬롯↔본문 겹침. playwright 없으면 `unmeasured` — 가짜 pass 없음).
- **이미지 슬롯**: `mood|conceptual|evidence` Codex 생성(`--fill-images`, 단발 위임 가능 — tier 무관). **생성된 evidence는 가시 딱지 "AI 생성 예시"**(W27 D6: 금지→표시 전환 2026-07-15) — 실자산 교체 또는 사람의 `generated_resolved` 기록 전까지 딱지가 남고 ship이 잔존 수를 표면화한다. 수급 route = `codex_gen|user_asset|client_asset|web_sample`(design_spec `source_route`, web_sample은 출처 URL 기록).
- **승인 전 LLM 평가**: stage9 후 평가 번들 → `deck_review.md` 수거(계약 검증 통과 필수 — 파일 존재≠평가) → 디자인 게이트의 판단 자료.
- **채점(review_badges) = 디자인 지표 재활용(W31 R9)**: `gating_report.json.review_badges`(장별 발산추천/충실/밋밋 판정)는 A5 회의 라운드의 품질 신호이자, 점수 낮은 장을 B1~B2(배경이미지 생성 권장·디자인지식 적용 대상)로 전달하는 지표다. 발산 팬아웃·복붙 병합 등 나머지 divergence 기계·대시보드 발산 라우트는 W31에서 초보자용 강의 자원으로 Reuse 격리됨 — 채점만 여정에 존치.
- **`ship` 파생물**: `--pptx --pptx-mode image`(승인 HTML의 슬라이드 사진 — 편집불가·확정본) / `native`(편집용). ~~`--cinematic`~~은 W31에서 폐기(scripts/cinematic.py와 함께 Reuse 격리).
- **테마 라벨**: **기본=`core`(중립 코어·무채 — go/render/stage9의 `--pack` 기본값, NORTHSTAR 결정 11·W20)** · 격리 하우스(`house_a`·`house_b` — W31에서 `<개발 원본 전용 경로>`로 완전 이전, 로컬에 `packs_excluded/` 없음·참조 금지) · 스킨: 오렌지=`quartz`/`quartz_guide`(가이드) · 강의=`lecture`+`lecture-dark`. 새 하우스 스타일(창고 외부 이식) 추가 = `add-skin --source <ref.pptx|pdf> --id <id>` (`SKIN_INTEGRATION.md`).
- **브랜드 크롬(W22)**: 스킨/design_brief의 `brand`(클라이언트·제안사 로고 — 실자산 필수·생성 금지)를 렌더러 `_frame`이 매 장 크롬으로 삽입. 디자인 적용(stage9/wireframe --apply)이 design_brief.skin+brand를 자동 승계.
