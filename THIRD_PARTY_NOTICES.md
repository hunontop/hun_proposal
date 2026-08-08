# Third-Party Notices

이 저장소는 아래 서드파티 소프트웨어를 포함(vendored)합니다.

## ir-search (MIT)

- 위치: `tools/ir_search/` (`sources_crawl.py`, `attach_download.py`, `run_manifest.py`)
- 원저작자: © 2026 djfksjd — https://github.com/djfksjd/ir-search
- 경유: gongo-fetch 추출본 (© 2026 Sanghoon Choi) — https://github.com/hunontop/gongo-fetch
- 로컬 수정: `sources_crawl.py`에 검색 파라미터 주입 훅 1개
  (`[vendored patch — hun_proposal]` 주석으로 표시)

> **여기 있는 건 의도적 스냅샷입니다.** 이 저장소는 어디에 두든 그대로 도는 자립 사본이라,
> 수집기를 외부 의존으로 두지 않고 필요한 부분만 동봉했습니다(기업마당 경로 3파일).
> **전체·최신판**(K-Startup·NIPA·KOCCA·SMTECH 포함, Claude Code 에이전트 스킬 형태)은
> **[hunontop/gongo-fetch](https://github.com/hunontop/gongo-fetch)** 에 있습니다 —
> 정부 사이트가 HTML을 바꾸면 그쪽이 먼저 갱신됩니다.

### MIT License 전문

```
MIT License

Copyright (c) 2026 Sanghoon Choi (gongo-fetch extraction)
Copyright (c) 2026 djfksjd (original ir-search — https://github.com/djfksjd/ir-search)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

(vendored 사본 옆에도 동일 전문이 `tools/ir_search/LICENSE`로 동봉되어 있습니다.)
