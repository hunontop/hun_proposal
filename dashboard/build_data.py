# -*- coding: utf-8 -*-
"""대시보드 데이터 로더 — 실공고 25건을 digest(한글) + bids.db(bid_no·url) 조인.

digest .md = 한글 깨끗(표시 데이터원). bids.db = 한글 손실되었으나 bid_no/detail_url/budget 온전.
조인 키 = budget(사업금액). 중복 예산은 등장 순서로 매칭(best-effort).
"""
from __future__ import annotations

import datetime as dt
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "proposal_system" / "vendor" / "proposal_core"
DB = CORE / "bids.db"
# NORTHSTAR 결정 13(W25): digest 산출물 위치를 workspace/로 통합(run들과 나란히).
# 읽기는 새 위치 우선 + 레거시(vendor) 폴백 — 과거 산출물도 계속 표시.
DIGEST_DIR = ROOT / "proposal_system" / "workspace" / "digest"
DIGEST_DIR_LEGACY = CORE / "digest"


def _digest_candidates() -> list[Path]:
    """새 위치 + 레거시 위치의 digest .md를 합쳐 반환(읽기 전용 폴백)."""
    files: list[Path] = []
    if DIGEST_DIR.exists():
        files.extend(DIGEST_DIR.glob("*.md"))
    if DIGEST_DIR_LEGACY.exists():
        files.extend(DIGEST_DIR_LEGACY.glob("*.md"))
    return files


def _digit(s: str) -> str:
    """금액 문자열에서 숫자만 추출 (조인 키 정규화)."""
    return re.sub(r"[^0-9]", "", s or "")


def _latest_digest() -> Path | None:
    files = sorted(_digest_candidates())
    return files[-1] if files else None


def _safe_text(value) -> bool:
    """DB 폴백에 노출할 값이 정상 UTF-8이며 U+FFFD가 없는지 확인."""
    if value is None:
        return True
    if isinstance(value, str):
        if "\ufffd" in value:
            return False
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            return False
        return True
    if isinstance(value, (list, tuple)):
        return all(_safe_text(item) for item in value)
    if isinstance(value, dict):
        return all(_safe_text(k) and _safe_text(v) for k, v in value.items())
    return True


def _parse_digest(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 5:
            continue
        dday, close, name, inst, budget = cells[:5]
        if dday == "D-day":  # header
            continue
        if all(set(c) <= {"-"} for c in cells[:5]):  # markdown separator |---|---|
            continue
        rows.append({
            "dday": dday,
            "close_dt": close,
            "bid_name": name,
            "inst_name": inst,
            "budget_label": budget,
            "budget_num": _digit(budget),
        })
    return rows


def _db_by_budget() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    if not DB.exists():
        return out
    con = sqlite3.connect(str(DB))
    try:
        for bid_no, budget, url, close in con.execute(
            "SELECT bid_no, budget, detail_url, close_dt FROM bids"
        ):
            key = _digit(budget)
            out.setdefault(key, []).append({
                "bid_no": bid_no,
                "detail_url": url,
                "db_close_dt": close,
            })
    finally:
        con.close()
    return out


def items_to_bids(items: list[dict]) -> list[dict]:
    """collector API items → 대시보드 bid 딕셔너리(마감 임박순). fresh items는 한글 정상."""
    import datetime as _dt
    import importlib.util

    # collector 헬퍼 재사용 (parse_close, dday, fmt_budget)
    spec = importlib.util.spec_from_file_location("_collector", CORE / "collector.py")
    col = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(col)  # type: ignore
    except Exception:
        col = None

    now = _dt.datetime.now()
    rows = []
    for it in items:
        close = it.get("bidClseDt") or ""
        if col:
            label, order = col.dday(col.parse_close(close), now)
            budget = col.fmt_budget(it.get("asignBdgtAmt") or it.get("presmptPrce"))
        else:
            label, order, budget = "-", 10**9, (it.get("asignBdgtAmt") or "-")
        bid_no = (it.get("bidNtceNo") or "") + "-" + (it.get("bidNtceOrd") or "")
        rows.append({
            "dday": ("🔴 " if 0 <= order <= 3 else "") + label,
            "close_dt": close or "-",
            "bid_name": it.get("bidNtceNm") or "",
            "inst_name": it.get("ntceInsttNm") or "-",
            "budget_label": budget,
            "budget_num": _digit(str(it.get("asignBdgtAmt") or it.get("presmptPrce") or "")),
            "bid_no": bid_no,
            "detail_url": it.get("bidNtceDtlUrl") or it.get("bidNtceUrl") or "",
            "id": bid_no,
            "_order": order,
        })
    rows.sort(key=lambda r: r["_order"])
    for r in rows:
        r.pop("_order", None)
    return rows


def load_bids() -> list[dict]:
    """최신 비어있지 않은 digest, 없으면 안전한 DB 행으로 표시 목록을 만든다."""
    digest = None
    rows = []
    for candidate in sorted(_digest_candidates(), key=lambda p: p.name, reverse=True):
        parsed = _parse_digest(candidate)
        if parsed:
            digest, rows = candidate, parsed
            break
    if digest is None:
        return _load_bids_from_db()
    db = _db_by_budget()
    # budget별 소비 포인터 (중복 예산 순서 매칭)
    used: dict[str, int] = {}
    for i, r in enumerate(rows):
        key = r["budget_num"]
        cands = db.get(key, [])
        idx = used.get(key, 0)
        match = cands[idx] if idx < len(cands) else (cands[0] if cands else None)
        used[key] = idx + 1
        r["bid_no"] = match["bid_no"] if match else f"UNKNOWN-{i:02d}"
        r["detail_url"] = match["detail_url"] if match else ""
        r["id"] = r["bid_no"]
        r["digest_date"] = digest.stem
    return rows


def _load_bids_from_db(limit: int = 100) -> list[dict]:
    """digest가 모두 비었을 때 raw를 노출하지 않고 정상 텍스트 DB 행만 반환."""
    if not DB.exists():
        return []
    con = sqlite3.connect(str(DB))
    try:
        records = con.execute(
            """
            SELECT bid_no, bid_name, inst_name, budget, close_dt, detail_url, notice_dt
              FROM bids
             ORDER BY CASE WHEN close_dt IS NULL OR close_dt='' THEN 1 ELSE 0 END,
                      close_dt ASC, notice_dt DESC, bid_no ASC
             LIMIT ?
            """,
            (limit,),
        ).fetchall()
    finally:
        con.close()
    now = dt.datetime.now()
    rows = []
    for bid_no, name, inst, budget, close, url, notice in records:
        values = (bid_no, name, inst, budget, close, url, notice)
        if not _safe_text(values):
            continue
        try:
            close_dt = dt.datetime.strptime((close or "")[:16], "%Y-%m-%d %H:%M")
            delta = close_dt - now
            days = delta.days + (1 if delta.total_seconds() >= 0 and delta.seconds else 0)
            dday = "D-DAY" if days == 0 else (f"D-{days}" if days > 0 else "마감")
        except (TypeError, ValueError):
            dday = "-"
        rows.append({
            "dday": dday,
            "close_dt": close or "-",
            "bid_name": name or "",
            "inst_name": inst or "-",
            "budget_label": budget or "-",
            "budget_num": _digit(str(budget or "")),
            "bid_no": bid_no,
            "detail_url": url or "",
            "id": bid_no,
            "digest_date": "bids.db",
        })
    return rows


if __name__ == "__main__":
    import json
    bids = load_bids()
    print(f"loaded {len(bids)} bids")
    matched = sum(1 for b in bids if not b["bid_no"].startswith("UNKNOWN"))
    print(f"bid_no matched: {matched}/{len(bids)}")
    print(json.dumps(bids[:2], ensure_ascii=False, indent=1))
