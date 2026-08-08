# -*- coding: utf-8 -*-
"""
M1 collector — 나라장터 입찰공고 수집 (용역 + 키워드 'AI')

핵심 로직(적응형 기간):
  최근 1일부터 조회 → 공고가 0건이면 기간을 하루씩 늘려 최소 1건이 잡힐 때까지 확장.
  (상한 MAX_DAYS 도달 시 중단 — 무한루프 방지, 작업원칙 4: 가드레일)

산출물:
  - bids.db (SQLite) : 신규 공고만 dedupe 적재
  - digest/YYYY-MM-DD.md : 오늘 새로 수집된 공고 다이제스트
"""
import os
import sys
import json
import sqlite3
import datetime as dt

import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "bids.db")
# NORTHSTAR 결정 13(W25): digest도 workspace/로 통합(analyzer.py의 ANALYSIS_DIR과 동일 원칙).
DIGEST_DIR = os.path.normpath(os.path.join(ROOT, "..", "..", "workspace", "digest"))
DIGEST_DIR_LEGACY = os.path.join(ROOT, "digest")

# 입찰공고정보서비스 - 용역 키워드 검색
BASE = "http://apis.data.go.kr/1230000/ad/BidPublicInfoService"
OP = "getBidPblancListInfoServcPPSSrch"

# 키워드: 명령행 인자(첫 비옵션) > 환경변수 BID_KEYWORD > 기본 "AI"
KEYWORD = (next((a for a in sys.argv[1:] if not a.startswith("-")), None)
           or os.environ.get("BID_KEYWORD") or "AI")
MAX_DAYS = 30   # 기간 확장 상한 (가드레일)
PAGE_ROWS = 100  # 한 페이지 최대 행수


def load_env(path):
    env = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def fetch_page(key, bgn, end, page_no, keyword=None):
    """한 페이지 조회 → (totalCount, items). keyword 미지정 시 전역 KEYWORD."""
    params = {
        "serviceKey": key,
        "pageNo": page_no,
        "numOfRows": PAGE_ROWS,
        "inqryDiv": 1,  # 공고게시일시 기준
        "inqryBgnDt": bgn,
        "inqryEndDt": end,
        "type": "json",
        "bidNtceNm": KEYWORD if keyword is None else keyword,
    }
    r = requests.get(f"{BASE}/{OP}", params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    resp = data.get("response", {})
    header = resp.get("header", {})
    if header.get("resultCode") not in ("00", "0", None):
        raise RuntimeError(f"API 오류: {header}")
    body = resp.get("body", {})
    total = int(body.get("totalCount", 0) or 0)
    items = body.get("items", [])
    if isinstance(items, dict):
        items = items.get("item", [])
    if isinstance(items, dict):
        items = [items]
    return total, (items or [])


def fetch_all(key, bgn, end, keyword=None):
    """기간 내 전체 공고 페이지네이션 수집"""
    total, first = fetch_page(key, bgn, end, 1, keyword)
    items = list(first)
    if total > PAGE_ROWS:
        pages = (total + PAGE_ROWS - 1) // PAGE_ROWS
        for p in range(2, pages + 1):
            _, more = fetch_page(key, bgn, end, p, keyword)
            items.extend(more)
    return total, items


def collect_adaptive(key, keyword=None, predicate=None):
    """1일부터 시작해 공고 ≥1건이 될 때까지 기간을 하루씩 확장.

    keyword: API bidNtceNm 대표어(미지정 시 전역 KEYWORD).
    predicate: items 클라이언트 필터(AND/OR 조건). 적용 후 ≥1건이어야 확장 종료.
    """
    now = dt.datetime.now()
    end_str = now.strftime("%Y%m%d") + "2359"
    seed = KEYWORD if keyword is None else keyword
    for days in range(1, MAX_DAYS + 1):
        bgn = (now - dt.timedelta(days=days - 1)).strftime("%Y%m%d") + "0000"
        total, items = fetch_all(key, bgn, end_str, seed)
        if predicate is not None:
            items = [it for it in items if predicate(it)]
        n = len(items) if predicate is not None else total
        print(f"[조회] 최근 {days}일 ({bgn[:8]}~{end_str[:8]}) → {n}건", file=sys.stderr)
        if n > 0:
            return days, bgn, end_str, items
    print(f"[중단] {MAX_DAYS}일까지 확장했으나 공고 0건", file=sys.stderr)
    return MAX_DAYS, None, end_str, []


# ── 불리언 검색 (AND/OR) — API는 단일 substring만 지원하므로 클라이언트 필터로 구현 ──
def parse_query(q):
    """쿼리 → OR그룹 리스트. 각 그룹 = AND텀 리스트.

    'AI 플랫폼 OR 빅데이터 구축' → [['AI','플랫폼'], ['빅데이터','구축']]
    OR 구분자: 'OR'(대소문자무시) 또는 '|'. AND 구분자: 'AND'/'&'/공백.
    """
    import re
    if not q or not q.strip():
        return [[KEYWORD]]
    groups = re.split(r"\s+OR\s+|\s*\|\s*", q.strip(), flags=re.IGNORECASE)
    parsed = []
    for g in groups:
        terms = [t for t in re.split(r"\s+AND\s+|\s*&\s*|\s+", g.strip(), flags=re.IGNORECASE) if t]
        if terms:
            parsed.append(terms)
    return parsed or [[KEYWORD]]


def match_query(name, groups):
    """공고명이 어느 한 OR그룹의 모든 AND텀을 (대소문자무시) 포함하면 True."""
    low = (name or "").lower()
    return any(all(t.lower() in low for t in group) for group in groups)


def collect_query(key, query):
    """AND/OR 불리언 쿼리로 수집. 그룹별 대표어로 API 조회 + 그룹 필터 → 합집합 dedupe."""
    groups = parse_query(query)
    seen, merged = set(), []
    max_days = 1
    for group in groups:
        seed = max(group, key=len)  # 그룹 내 가장 긴(선택적인) 텀을 API 대표어로
        pred = lambda it, g=group: match_query(it.get("bidNtceNm"), [g])
        days, _bgn, _end, items = collect_adaptive(key, seed, pred)
        max_days = max(max_days, days)
        for it in items:
            uid = (it.get("bidNtceNo") or "") + "-" + (it.get("bidNtceOrd") or "")
            if uid not in seen:
                seen.add(uid)
                merged.append(it)
    return max_days, merged


def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS bids (
            bid_no       TEXT PRIMARY KEY,   -- 공고번호+차수
            bid_ord      TEXT,
            bid_name     TEXT,
            inst_name    TEXT,               -- 공고기관
            demand_inst  TEXT,              -- 수요기관
            notice_dt    TEXT,              -- 공고일시
            close_dt     TEXT,              -- 마감일시
            budget       TEXT,              -- 사업금액/추정가격
            detail_url   TEXT,
            collected_at TEXT,              -- 수집 시각
            raw          TEXT                -- 원본 JSON
        )
    """)
    con.commit()
    return con


def _has_unsafe_text(value):
    """중첩 API 응답에서 UTF-8 불가 문자열 또는 대체문자를 찾는다."""
    if isinstance(value, str):
        if "\ufffd" in value:
            return True
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            return True
        return False
    if isinstance(value, dict):
        return any(
            _has_unsafe_text(key) or _has_unsafe_text(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_has_unsafe_text(item) for item in value)
    return False


def upsert(con, items):
    """신규는 적재·반환하고, 안전한 기존 공고는 최신 API 값으로 갱신."""
    new_rows = []
    now_iso = dt.datetime.now().isoformat(timespec="seconds")
    for it in items:
        bid_no = (it.get("bidNtceNo") or "") + "-" + (it.get("bidNtceOrd") or "")
        exists = con.execute("SELECT 1 FROM bids WHERE bid_no=?", (bid_no,)).fetchone()
        if exists:
            # 정상 DB 행을 손상된 재응답으로 덮지 않는다. 행 단위로 전부 갱신하거나 전부 보존한다.
            if _has_unsafe_text(it):
                continue
            con.execute(
                """
                UPDATE bids
                   SET bid_ord=?,
                       bid_name=?,
                       inst_name=?,
                       demand_inst=?,
                       notice_dt=?,
                       close_dt=?,
                       budget=?,
                       detail_url=?,
                       collected_at=?,
                       raw=?
                 WHERE bid_no=?
                """,
                (
                    it.get("bidNtceOrd"),
                    it.get("bidNtceNm"),
                    it.get("ntceInsttNm"),
                    it.get("dminsttNm"),
                    it.get("bidNtceDt"),
                    it.get("bidClseDt"),
                    it.get("asignBdgtAmt") or it.get("presmptPrce"),
                    it.get("bidNtceDtlUrl") or it.get("bidNtceUrl"),
                    now_iso,
                    json.dumps(it, ensure_ascii=False),
                    bid_no,
                ),
            )
            continue
        row = (
            bid_no,
            it.get("bidNtceOrd"),
            it.get("bidNtceNm"),
            it.get("ntceInsttNm"),
            it.get("dminsttNm"),
            it.get("bidNtceDt"),
            it.get("bidClseDt"),
            it.get("asignBdgtAmt") or it.get("presmptPrce"),
            it.get("bidNtceDtlUrl") or it.get("bidNtceUrl"),
            now_iso,
            json.dumps(it, ensure_ascii=False),
        )
        con.execute(
            "INSERT INTO bids VALUES (?,?,?,?,?,?,?,?,?,?,?)", row
        )
        new_rows.append(it)
    con.commit()
    return new_rows


def fmt_budget(v):
    try:
        return f"{int(float(v)):,}원"
    except (TypeError, ValueError):
        return v or "-"


def parse_close(s):
    """마감일시 문자열 → datetime (실패 시 None)"""
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None


def dday(close_dt, now):
    """D-day 문자열. 마감까지 남은 일수(음수=마감지남)."""
    if close_dt is None:
        return "-", 10**9  # 정렬 시 맨 뒤
    delta = close_dt - now
    d = delta.days + (1 if delta.seconds else 0) if delta.total_seconds() >= 0 else delta.days
    if delta.total_seconds() < 0:
        return "마감", 10**8  # 마감 지남 → 미상(10**9)보다 앞, 진행중 건보다는 뒤
    label = "D-DAY" if d == 0 else f"D-{d}"
    return label, d


def write_digest(days, new_rows, total_in_period, keyword_label=None):
    os.makedirs(DIGEST_DIR, exist_ok=True)
    today = dt.datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(DIGEST_DIR, f"{today}.md")
    lines = [
        f"# 입찰공고 다이제스트 — {today}",
        "",
        f"- 검색: 용역 · 키워드 `{KEYWORD if keyword_label is None else keyword_label}`",
        f"- 적응형 기간: 최근 **{days}일** (이 기간 내 공고 {total_in_period}건)",
        f"- **신규 {len(new_rows)}건** (기존 적재분 제외)",
        "",
    ]
    if not new_rows:
        lines.append("> 신규 공고 없음 (모두 기존 수집분)")
    else:
        now = dt.datetime.now()
        # 마감 임박순 정렬 (마감 지난 건/미상은 뒤로)
        enriched = []
        for it in new_rows:
            cdt = parse_close(it.get("bidClseDt"))
            label, order = dday(cdt, now)
            enriched.append((order, label, it))
        enriched.sort(key=lambda x: x[0])

        lines.append("> 🔴 마감 임박순. 기술제안서 방문제출 등은 분석카드에서 재확인.")
        lines.append("")
        lines.append("| D-day | 마감일시 | 사업명 | 공고기관 | 사업금액 |")
        lines.append("|---|---|---|---|---|")
        for order, label, it in enriched:
            name = (it.get("bidNtceNm") or "").replace("|", "/")
            inst = it.get("ntceInsttNm") or "-"
            budget = fmt_budget(it.get("asignBdgtAmt") or it.get("presmptPrce"))
            close = it.get("bidClseDt") or "-"
            mark = "🔴 " if 0 <= order <= 3 else ""
            lines.append(f"| {mark}{label} | {close} | {name} | {inst} | {budget} |")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


def bids_as_json(days, items):
    """수집 items → 콕핏용 간결 JSON(마감 임박순)."""
    now = dt.datetime.now()
    out = []
    for it in items:
        cdt = parse_close(it.get("bidClseDt"))
        label, order = dday(cdt, now)
        out.append({
            "공고명": it.get("bidNtceNm"),
            "공고번호": (it.get("bidNtceNo") or "") + "-" + (it.get("bidNtceOrd") or ""),
            "기관": it.get("ntceInsttNm") or "-",
            "금액": fmt_budget(it.get("asignBdgtAmt") or it.get("presmptPrce")),
            "공고일": it.get("bidNtceDt") or "",
            "마감": it.get("bidClseDt") or "-",
            "dday": label,
            "order": order,
            "url": it.get("bidNtceDtlUrl") or it.get("bidNtceUrl") or "",
        })
    out.sort(key=lambda b: b["공고일"], reverse=True)   # 최근 공고일 순(최신 먼저)
    return {"keyword": KEYWORD, "days": days, "count": len(items), "bids": out}


def main():
    json_mode = "--json" in sys.argv
    env = load_env(os.path.join(ROOT, ".env"))
    key = env.get("DATA_GO_KR_API_KEY", "")
    if not key or "여기에" in key:
        if json_mode:
            print(json.dumps({"error": "API 키 미설정 (.env DATA_GO_KR_API_KEY)"}, ensure_ascii=False))
        else:
            print("[오류] .env 의 DATA_GO_KR_API_KEY 가 설정되지 않음")
        sys.exit(1)

    days, bgn, end, items = collect_adaptive(key)

    if json_mode:                       # 콕핏 검색 — DB 적재(선택→분석용) 후 목록 JSON 반환
        con = init_db()
        upsert(con, items)
        con.close()
        print(json.dumps(bids_as_json(days, items), ensure_ascii=False))
        return

    con = init_db()
    new_rows = upsert(con, items)
    path = write_digest(days, new_rows, len(items))
    con.close()

    print(f"[완료] 신규 {len(new_rows)}건 적재 → {path}")


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
    main()
