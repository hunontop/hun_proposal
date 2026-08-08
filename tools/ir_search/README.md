# ir_search — vendored 크롤러 (기업마당 등 공고 수집)

**출처**: [ir-search](https://github.com/djfksjd/ir-search) (MIT) → [gongo-fetch](https://github.com/hunontop/gongo-fetch) 추출본(2026-07)에서 반입.
라이선스 전문 = 이 폴더의 [`LICENSE`](LICENSE), 고지 = 저장소 루트 [`THIRD_PARTY_NOTICES.md`](../../THIRD_PARTY_NOTICES.md).

> **스냅샷입니다.** 여기엔 기업마당 경로에 필요한 3파일만 있습니다. **전체 수집기**
> (K-Startup·NIPA·KOCCA·SMTECH + Claude Code 스킬 형태)는
> **[hunontop/gongo-fetch](https://github.com/hunontop/gongo-fetch)** 를 쓰세요.
> 정부 사이트 HTML 변경은 그쪽에서 먼저 고쳐집니다 — 수집만 필요하면 이 저장소 대신 그걸 받으면 됩니다.

| 파일 | 무엇 |
|---|---|
| `sources_crawl.py` | bizinfo(기업마당)·nipa·kocca·smtech 목록/상세/첨부 크롤러. robots 준수·리다이렉트 허용목록·fail-closed 종료코드(0/2/3) |
| `attach_download.py` | 첨부 다운로드 공용 모듈 (검증된 리다이렉트·50MB 캡·sha256) |
| `run_manifest.py` | run_manifest.json(coverage) 기록기 |

**로컬 수정(vendored patch)**: `sources_crawl.py`에 `BIZINFO_EXTRA_QUERY` 훅 1개 추가
(`[vendored patch — hun_proposal]` 주석으로 표시) — 상위 래퍼 `tools/gongo_search.py`가
서버측 키워드 검색 파라미터를 주입하는 데 쓴다. 그 외에는 원본 그대로.

**사용 진입점**: 직접 부르지 말고 [`tools/gongo_search.py`](../gongo_search.py)를 쓰세요.
