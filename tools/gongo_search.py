#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gongo_search — 기업마당(bizinfo) 키워드 검색 + 상세/첨부 수집 CLI.

나라장터 API 키가 없어도 되는 공고 수집 경로(무키). vendored ir-search(MIT,
tools/ir_search/)의 크롤러를 그대로 쓰되, 목록 요청에 **서버측 검색 파라미터**
(condition/keyword — 2026-08-04 실측)를 주입해 페이지 수를 아낀다.

사용 (수강생 실습 기준):
  python tools/gongo_search.py "소셜벤처" --max-pages 5 -o 수집.jsonl
  python tools/gongo_search.py "소셜벤처" --where content     # 본문 검색(더 넓음)
  python tools/gongo_search.py detail <공고URL> --download-dir attachments/

검색 옵션:
  --where title|content|tag   검색 범위 (기본 title=지원사업명, content=내용, tag=해시태그)
  --local-filter              서버측 검색 대신 전량 목록 후 제목 로컬 필터(2안 폴백 —
                              사이트 개편으로 서버 검색이 깨졌을 때)
  (접수중 공고만 검색한다 — 목록 요청의 schEndAt=N 고정)

출력: JSONL(한 줄=한 공고 {source,id,title,field,org,apply_start,apply_end,reg_date,url})
      + 같은 폴더에 run_manifest.json(수집 커버리지).

종료코드(ir-search fail-closed 계약 유지):
  0 성공(0건 검색결과 포함 — '등록된 게시물이 없습니다' 확인 시)
  2 부분 실패(수집물은 저장됨 — 성공으로 취급 금지)
  3 차단 신호(401/403/CAPTCHA) — 우회하지 않고 수동 확인으로 전환
"""
import argparse
import sys
import urllib.parse
from pathlib import Path

_VENDOR = Path(__file__).resolve().parent / "ir_search"
if str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

import attach_download  # noqa: E402
import sources_crawl as sc  # noqa: E402
from run_manifest import make_run, update_manifest  # noqa: E402

# 검색 범위 → bizinfo 검색 폼의 condition 값 (2026-08-04 실측: 폼 data-option)
WHERE = {"title": "searchPblancNm", "content": "CONTS", "tag": "TAGNAME"}
# 검색결과 0건일 때 목록 영역에 뜨는 문구 (실측) — 파서 실패와 구별하는 근거
EMPTY_MARKER = "등록된 게시물이 없습니다"


def _utf8_console():
    """Windows 콘솔/파이프(cp949)에서 한글 로그가 UnicodeEncodeError로 죽지 않게."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _make_bizinfo_fetch():
    """bizinfo 전용 fetcher — 200 위장 차단(CAPTCHA)도 수동 전환(exit 3)으로 통일."""
    raw, backend = sc.make_fetcher(sc.SOURCE_DOMAINS["bizinfo"])

    def fetch(url, data=None):
        status, text = raw(url, data)
        if status == 200 and sc.looks_blocked(text):
            raise attach_download.ManualEscalation("200 위장 차단(CAPTCHA/접근거부)")
        return status, text

    print(f"[gongo-search] fetch backend: {backend}", file=sys.stderr)
    if backend == "urllib":
        print("[gongo-search] tip: pip install 'curl_cffi>=0.15' — 차단될 때",
              file=sys.stderr)
    return fetch


def cmd_search(args):
    if args.local_filter:
        sc.BIZINFO_EXTRA_QUERY = ""  # 2안: 전량 목록 후 로컬 필터
    else:
        sc.BIZINFO_EXTRA_QUERY = "&" + urllib.parse.urlencode({
            "condition": WHERE[args.where],
            "condition1": "AND",
            "keyword": args.keyword,
        })
    fetch = _make_bizinfo_fetch()
    try:
        items, error, stats = sc.crawl("bizinfo", fetch, args.max_pages)
    except attach_download.ManualEscalation as e:
        print(f"MANUAL [gongo-search] 차단 신호({e}) — 우회하지 않고 수동 확인",
              file=sys.stderr)
        sys.exit(3)

    if args.local_filter:
        kw = args.keyword.strip()
        before = len(items)
        items = [i for i in items if kw in i["title"]]
        print(f"[gongo-search] 로컬 필터: {before}건 중 제목 매치 {len(items)}건",
              file=sys.stderr)

    # 검색결과 0건 vs 사이트 개편 구별: crawl()은 1페이지 0건을 개편 신호로
    # 다루지만(전량 크롤 기준), 검색에서는 정상 상황이다 — 빈 결과 문구로 판별.
    if error and not items and stats["pages_fetched"] <= 1 and not args.local_filter:
        page1 = (sc.BIZINFO_LIST_URL + "?rows=15&cpage=1&schEndAt=N"
                 + sc.BIZINFO_EXTRA_QUERY)
        try:
            status, h = fetch(page1)
            if status == 200 and EMPTY_MARKER in h:
                error, stats["stop_reason"] = None, "no-results"
                print(f"[gongo-search] 검색결과 0건 (키워드: {args.keyword!r})",
                      file=sys.stderr)
        except Exception:  # noqa: BLE001 — 판별 실패면 원래의 partial 판정 유지
            pass

    out = Path(args.output)
    if out.parent and not out.parent.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
    import json
    with open(out, "w", encoding="utf-8") as f:
        for i in items:
            f.write(json.dumps(i, ensure_ascii=False) + "\n")
    print(f"[gongo-search] saved: {out} ({len(items)}건)", file=sys.stderr)

    status_word = "partial" if error else "ok"
    update_manifest(str(out), [make_run(
        "bizinfo", status_word, 2 if error else 0,
        pages_fetched=stats["pages_fetched"], collected=len(items),
        stop_reason=stats["stop_reason"],
        errors=[error] if error else [], duplicates=stats["duplicates"],
    )])
    if error:
        print(f"WARNING [gongo-search] partial: {error} — 수집물은 저장됐지만 "
              "커버리지 불완전(exit 2)", file=sys.stderr)
        sys.exit(2)


def cmd_detail(args):
    fetch = sc.make_detail_fetcher()
    sc.cmd_detail(fetch, args.urls, args.output,
                  download_dir=args.download_dir, merge_into=args.merge_into)


def main():
    _utf8_console()
    ap = argparse.ArgumentParser(
        prog="gongo_search",
        description="기업마당 키워드 검색·상세/첨부 수집 (무키 경로, ir-search MIT 기반)")
    sub = ap.add_subparsers(dest="cmd")

    p_det = sub.add_parser("detail", help="상세 페이지 본문 저장 (+첨부 다운로드)")
    p_det.add_argument("urls", nargs="+", help="공고 상세 URL")
    p_det.add_argument("-o", "--output", default="details",
                       help="본문 텍스트 저장 폴더 (기본 details/)")
    p_det.add_argument("--download-dir",
                       help="첨부를 이 폴더에(공고별 하위 폴더) 다운로드")
    p_det.add_argument("--merge-into",
                       help="목록 jsonl에 content_hash/attachments 병합")

    p_srch = sub.add_parser("search", help="키워드 검색 (기본 커맨드 — 생략 가능)")
    for p in (p_srch,):
        p.add_argument("keyword", help="검색어 (예: 소셜벤처)")
        p.add_argument("--where", choices=sorted(WHERE), default="title",
                       help="검색 범위: title=지원사업명(기본)·content=내용·tag=해시태그")
        p.add_argument("--max-pages", type=int, default=5, help="페이지 상한(기본 5)")
        p.add_argument("-o", "--output", default="수집.jsonl", help="출력 JSONL")
        p.add_argument("--local-filter", action="store_true",
                       help="2안 폴백: 전량 목록 후 제목 로컬 필터")

    argv = sys.argv[1:]
    # 편의 규약: 첫 인자가 서브커맨드가 아니면 검색어로 본다 —
    #   python tools/gongo_search.py "소셜벤처" --max-pages 5
    if argv and argv[0] not in ("detail", "search", "-h", "--help"):
        argv = ["search"] + argv
    args = ap.parse_args(argv)
    if args.cmd is None:
        ap.print_help()
        sys.exit(1)
    if args.cmd == "detail":
        cmd_detail(args)
    else:
        cmd_search(args)


if __name__ == "__main__":
    main()
