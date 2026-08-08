"""가공 어휘 갭 로그 — `run/knowledge_gaps.md` + `knowledge_gaps.json` (DESIGN_ASSETS_LANE §3·§5-④-①).

`catalog_gap`은 이미 wireframe(--apply)·refine(--collect)에서 계산되지만 콘솔에 스쳐 지나가고
`gating_report`의 카운트로만 남는다 — **지속 기록·처리 경로가 없다**. 이 모듈은 그 gap을 받아주는
집이다: 사람이 읽는 표(`knowledge_gaps.md`, 1급 산출물) + 정본 사이드카(`knowledge_gaps.json`).

**불변식**
  - **지어내지 않는다**: gap 텍스트는 원본 그대로 옮긴다(요약·창작 금지). Tier1/Tier2 자동분류도
    하지 않는다 — 퍼지 매칭은 부정확하다. `처리상태`는 항상 사람이 채운다(기본값=`미해결`).
  - **멱등**: 같은 gap(키 = slide_id + need 텍스트)은 재실행에 중복 추가되지 않는다.
  - **사람 편집 보존**: 사람이 `knowledge_gaps.md`의 처리상태 칸을 직접 고쳐도(json을 안 건드려도)
    다음 기록 시 보존된다 — 매 기록 전에 기존 md를 다시 파싱해 상태를 되읽는다.
  - **부가 관측, 차단자 아님**: 이 로그의 기록 실패가 wireframe/refine 파이프라인을 막지 않는다
    (호출부가 예외를 삼키고 [WARN]만 표면화 — `proposal_pipeline._record_knowledge_gaps` 참고).

입력 형상(호출부가 그대로 넘긴다 — 정규화는 이 모듈이 흡수):
  - wireframe.validate()의 catalog_gap: ``{"slide_id": "3", "wanted": "자유 서술"}``
  - design_spec.collect_refs()의 catalog_gap: 최상위 선언 ``{"slide_id","need","why"}`` +
    수집중 발견 ``{"slide_id","kind","id","why"}`` 혼재.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
JSON_FILENAME = "knowledge_gaps.json"
MD_FILENAME = "knowledge_gaps.md"
DEFAULT_STATUS = "미해결"
_KEY_SEP = "§"


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _md_escape(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ").strip()


def _md_unescape(text: str) -> str:
    return (text or "").replace("\\|", "|").strip()


def _key(slide_id: str, need: str) -> str:
    return f"{slide_id}{_KEY_SEP}{need}"


def _normalize(gap: Any, source: str) -> "dict | None":
    """호출부마다 다른 catalog_gap 형상을 공통 {slide_id, need, why}로 흡수.

    지어내지 않는다 — 원본 텍스트를 그대로 옮긴다(요약·재작성 없음).
    """
    if not isinstance(gap, dict):
        return None
    slide_id = str(gap.get("slide_id") if gap.get("slide_id") is not None else "?")
    if "wanted" in gap:  # wireframe.validate() 형상
        need = str(gap.get("wanted") or "").strip()
        why = ""
    elif gap.get("need") is not None:  # design_spec 최상위 선언 형상
        need = str(gap.get("need") or "").strip()
        why = str(gap.get("why") or "").strip()
    elif "kind" in gap or "id" in gap:  # design_spec.collect_refs() 수집중 발견 형상
        need = f"{gap.get('kind') or '?'}:{gap.get('id') or '?'}"
        why = str(gap.get("why") or "").strip()
    else:
        need = json.dumps(gap, ensure_ascii=False, sort_keys=True)
        why = ""
    if not need:
        return None
    return {"slide_id": slide_id, "need": need, "why": why}


def _sort_key(entry: dict) -> tuple:
    sid = str(entry.get("slide_id") or "")
    try:
        sid_rank: tuple = (0, int(sid))
    except ValueError:
        sid_rank = (1, sid)
    return (sid_rank, entry.get("need") or "")


def _load_existing(run: Path) -> dict[str, dict]:
    """기존 knowledge_gaps.json → key(slide_id+need)로 색인. 없으면 빈 dict(모르는 걸 지어내지 않는다)."""
    p = run / JSON_FILENAME
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, dict] = {}
    for e in data.get("entries") or []:
        if not isinstance(e, dict):
            continue
        key = e.get("key") or _key(str(e.get("slide_id")), str(e.get("need") or ""))
        out[key] = dict(e)
    return out


def _parse_md_statuses(run: Path) -> dict[str, str]:
    """기존 knowledge_gaps.md 표를 다시 읽어 key→처리상태를 회수(사람이 md를 직접 고친 경우 보존)."""
    p = run / MD_FILENAME
    if not p.is_file():
        return {}
    statuses: dict[str, str] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 5:
            continue
        slide, need, _why, _source, status = cells[:5]
        if slide in ("slide", "---") or set(slide) <= {"-"}:
            continue
        key = _key(slide, _md_unescape(need))
        if status:
            statuses[key] = status
    return statuses


def render_md(run_id: str, entries: list[dict]) -> str:
    lines = [
        f"# 어휘 갭 로그 — {run_id}",
        "",
        "wireframe/refine 결정기가 \"카탈로그에 없다\"고 선언한 형태 요청을 그대로 기록한다. "
        "지어내지 않는다(Tier 자동분류 없음) — 처리상태(미해결/보류/신설함/새지식필요[Tier2])는 "
        "사람이 채운다. 기본값=미해결.",
        "",
        "| slide | need | why | source | 처리상태 |",
        "|---|---|---|---|---|",
    ]
    for e in entries:
        lines.append(
            f"| {e.get('slide_id', '')} | {_md_escape(e.get('need', ''))} | "
            f"{_md_escape(e.get('why', ''))} | {e.get('source', '')} | "
            f"{e.get('status') or DEFAULT_STATUS} |"
        )
    return "\n".join(lines) + "\n"


def _write(run: Path, entries: list[dict]) -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run.name,
        "updated_at": _now(),
        "entries": entries,
    }
    # 멱등 보장: entries가 이전 기록과 동일하면 updated_at 타임스탬프도 보존한다.
    # (안 그러면 재실행이 초 경계를 넘을 때 updated_at만 달라져 바이트 동일성이 깨진다 —
    #  update_status/record 멱등 계약이 벽시계 타이밍에 흔들리는 원인.)
    p = run / JSON_FILENAME
    if p.is_file():
        try:
            prev = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            prev = None
        if isinstance(prev, dict) and prev.get("entries") == entries:
            payload["updated_at"] = prev.get("updated_at", payload["updated_at"])
    p.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (run / MD_FILENAME).write_text(render_md(run.name, entries), encoding="utf-8")


def record(run: "str | Path", gaps: list, source: str) -> dict:
    """gaps(호출부 원본 형상)를 정규화해 merge — 멱등·사람 처리상태 보존.

    반환: {"entries": [...], "added": N, "path": "<md 경로>"|None}
    entries가 (기존 포함) 비어 있으면 파일을 새로 만들지 않는다(gap 없는 run에 소음 남기지 않음).
    """
    run = Path(run)
    existing = _load_existing(run)
    for key, status in _parse_md_statuses(run).items():
        if key in existing and status:
            existing[key]["status"] = status

    now = _now()
    added = 0
    for raw in gaps or []:
        norm = _normalize(raw, source)
        if norm is None:
            continue
        key = _key(norm["slide_id"], norm["need"])
        if key in existing:
            entry = existing[key]
            entry["last_seen_at"] = now
            srcs = {s for s in str(entry.get("source") or "").split(",") if s}
            srcs.add(source)
            entry["source"] = ",".join(sorted(srcs))
            if norm["why"] and not entry.get("why"):
                entry["why"] = norm["why"]
        else:
            existing[key] = {
                "key": key,
                "slide_id": norm["slide_id"],
                "need": norm["need"],
                "why": norm["why"],
                "source": source,
                "status": DEFAULT_STATUS,
                "first_seen_at": now,
                "last_seen_at": now,
            }
            added += 1

    if not existing:
        return {"entries": [], "added": 0, "path": None}

    entries = sorted(existing.values(), key=_sort_key)
    _write(run, entries)
    return {"entries": entries, "added": added, "path": str(run / MD_FILENAME)}


def _load_with_md_statuses(run: Path) -> dict[str, dict]:
    """json 색인 + md에서 사람이 직접 고친 처리상태를 되읽어 병합(record와 동일 규율)."""
    existing = _load_existing(run)
    for key, status in _parse_md_statuses(run).items():
        if key in existing and status:
            existing[key]["status"] = status
    return existing


def find(run: "str | Path", *, slide_id: "str | None" = None, need: "str | None" = None) -> list[dict]:
    """gap 엔트리 회수(bundle --gap용). slide_id 지정 시 일치, need 지정 시 부분일치.

    지어내지 않는다 — 없으면 빈 리스트(모르는 걸 아는 척하지 않는다). 정렬은 표와 동일.
    """
    existing = _load_with_md_statuses(Path(run))
    sid = None if slide_id is None else str(slide_id)
    out: list[dict] = []
    for entry in existing.values():
        if sid is not None and str(entry.get("slide_id")) != sid:
            continue
        if need and need not in str(entry.get("need") or ""):
            continue
        out.append(entry)
    return sorted(out, key=_sort_key)


def update_status(
    run: "str | Path", status: str, *, slide_id: "str | None" = None, need: "str | None" = None
) -> dict:
    """매칭 gap의 처리상태를 status로 갱신(piece --apply용) — 멱등·사람 편집 보존.

    매칭 = (slide_id 지정 시 일치) AND (need 지정 시 need 텍스트 부분일치).
    둘 다 미지정이면 무엇을 고칠지 알 수 없으므로 ValueError(지어내지 않는다).
    반환: {"matched": [key...], "updated": N, "path": "<md 경로>"|None}.
    매칭 0건이면 파일을 건드리지 않는다(조용한 신규 생성 금지).
    """
    run = Path(run)
    if slide_id is None and not need:
        raise ValueError("update_status: slide_id 또는 need 중 하나는 지정해야 한다")
    existing = _load_with_md_statuses(run)
    sid = None if slide_id is None else str(slide_id)
    matched: list[str] = []
    for key, entry in existing.items():
        if sid is not None and str(entry.get("slide_id")) != sid:
            continue
        if need and need not in str(entry.get("need") or ""):
            continue
        matched.append(key)
    for key in matched:
        existing[key]["status"] = status
    if matched:
        entries = sorted(existing.values(), key=_sort_key)
        _write(run, entries)
        return {"matched": matched, "updated": len(matched), "path": str(run / MD_FILENAME)}
    return {"matched": [], "updated": 0, "path": None}


def count_unresolved(run: "str | Path") -> int:
    """status 표면화용 — knowledge_gaps.json이 없으면 0(모르는 걸 아는 척하지 않는다: gap 자체가 없다는 뜻)."""
    p = Path(run) / JSON_FILENAME
    if not p.is_file():
        return 0
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    return sum(
        1 for e in data.get("entries") or []
        if isinstance(e, dict) and e.get("status") == DEFAULT_STATUS
    )


def sync_to_lane(run: "str | Path", repo_root: "Path | None" = None) -> "Path | None":
    """design-assets/gaps/<run-id>_knowledge_gaps.md로 단순 복사 갱신(LANE §1 체크아웃/싱크백)."""
    run = Path(run)
    md_path = run / MD_FILENAME
    if not md_path.is_file():
        return None
    root = repo_root or Path(__file__).resolve().parents[2]
    gaps_dir = root / "design-assets" / "gaps"
    gaps_dir.mkdir(parents=True, exist_ok=True)
    dest = gaps_dir / f"{run.name}_{MD_FILENAME}"
    dest.write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")
    return dest
