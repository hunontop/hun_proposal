# -*- coding: utf-8 -*-
"""run 보관소 왕복 (W31 리허설 마찰9, 2026-07-22~23 사용자 확정 설계).

활성 `workspace/runs/`는 기존 이관 시스템이 기계명(`gen_<bid>` 등)에 의존하므로 **건드리지
않는다**. 완료된 run을 사람이 알아볼 수 있게 정리하는 곳은 별도 창고
`workspace/archive/`뿐이다 — 보관 폴더명만 한글화한다(`YYYY-MM_한글명`).

    proposal_system/workspace/archive/
        2026-07_예시공공기관-홍보용역/    ← 원래 run 전체가 통째로 옮겨온 것(자립)
            pipeline_state.json ...(기존 run 내용 그대로)
            _archive_meta.json          ← 이 모듈이 남기는 유일한 신규 파일(원 기계 id·이관 일시·
                                            한글명·유도 출처)

`archive --run <id>`가 이동(자립 — state·journey·산출물 포함), `archive --restore <폴더명>`이
meta의 원 기계 id로 무손실 복귀, `archive --list`가 활성 완료 run + 보관소 표를 보여준다
(전부 `proposal_pipeline.archive_cmd`가 얇게 호출한다 — §3.0 규칙: 새 기능은 동사 3개의 내부
또는 이런 부착형 커맨드로만 편입, 렌더 파이프라인 자체는 건드리지 않는다).

한글명 유도(결정론·0토큰, LLM 미호출)는 4계층 우선순위다:
  1. 분석카드(`run/analysis/` 자립 복제본 → 없으면 `workspace/analysis/` 전역본)의
     제목(사업명)·발주처 표 행.
  2. 대시보드 `last_search.json`의 같은 공고번호 항목(inst_name·bid_name).
  3. run의 `institution_research.json`(기관명만).
  4. brief 입구 run의 `brief.md` 첫 제목.
  실패하면 기계 id를 그대로 쓴다(`fallback_id`) — 모르는 걸 아는 척하지 않는다(코드베이스
  전역 원칙, pipeline_state.py의 [추론] 표시와 동일 정신).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import shutil
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
META_NAME = "_archive_meta.json"

# proposal_system/scripts/archive.py -> parents[1] = proposal_system
ARCHIVE_ROOT = Path(__file__).resolve().parents[1] / "workspace" / "archive"
# REPO_ROOT/dashboard/last_search.json — 대시보드 최근 검색 결과(공고명·발주처 캐시).
LAST_SEARCH_PATH = Path(__file__).resolve().parents[2] / "dashboard" / "last_search.json"

MAX_NAME_LEN = 60

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WS_RE = re.compile(r"\s+")
_DASHES_RE = re.compile(r"-{2,}")
_TITLE_RE = re.compile(r"^#.*?[—-]\s*(.+?)\s*$", re.MULTILINE)
_INST_ROW_RE = re.compile(r"\|\s*발주처[^\|]*\|\s*([^\|]+?)\s*\|")
_MD_HEADING_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


class ArchiveError(ValueError):
    """사람이 읽는 오류 — archive/restore 사용 중 발견되는 입력·상태 문제(코드 크래시가 아니다)."""


# ---------------------------------------------------------------------------
# 이름 위생(폴더명 안전화)
# ---------------------------------------------------------------------------

def sanitize_name(raw: str) -> str:
    """Windows 폴더명 금지 문자 제거 + 공백→대시 + 길이 제한. 빈 결과면 ''(호출부가 폴백)."""
    text = _INVALID_CHARS.sub("", raw or "").strip()
    text = _WS_RE.sub(" ", text).strip()
    text = text.replace(" ", "-")
    text = _DASHES_RE.sub("-", text).strip("-._ ")
    if not text:
        return ""
    return text[:MAX_NAME_LEN]


# ---------------------------------------------------------------------------
# 한글명 유도 — 4계층 우선순위(결정론)
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> "dict | None":
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _bid_ref(run: Path) -> "str | None":
    """state.json의 input.ref(kind=bid)에서 공고번호. 없으면 run 이름의 gen_ 접두를 벗겨 추정."""
    try:
        import pipeline_state  # sibling, 지연 임포트(순환 방지)
        state = pipeline_state.load(run)
    except Exception:
        state = {}
    inp = (state or {}).get("input") or {}
    if inp.get("kind") == "bid" and inp.get("ref"):
        return str(inp["ref"])
    name = run.name
    if name.startswith("gen_"):
        return name[len("gen_"):]
    return None


def _short_business(business_name: str, institution: "str | None") -> str:
    """사업명에서 기관명 접두를 떼고 뒤쪽 의미있는 토큰 1~2개만 남긴다(과도한 원제목 대신 짧은 키워드)."""
    text = (business_name or "").strip()
    if institution:
        inst = institution.strip()
        if inst and text.startswith(inst):
            text = text[len(inst):].strip()
    tokens = [t for t in re.split(r"\s+", text) if t]
    tail = tokens[-2:] if len(tokens) >= 2 else tokens
    return "".join(tail)


def _combine(institution: str, business_short: str) -> str:
    if institution and business_short:
        return f"{institution}-{business_short}"
    return institution or business_short


def _parse_analysis_card(path: Path) -> "tuple[str, str] | None":
    text = None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    title_m = _TITLE_RE.search(text)
    inst_m = _INST_ROW_RE.search(text)
    business = title_m.group(1).strip() if title_m else ""
    institution_raw = inst_m.group(1).strip() if inst_m else ""
    institution = re.split(r"[\(（]", institution_raw)[0].strip() if institution_raw else ""
    if not business and not institution:
        return None
    return institution, business


def _analysis_dir_candidates(run: Path) -> "list[Path]":
    """run 자립 복제본(결정 13, `_copy_bid_analysis_assets`) 우선, 리포 전역 위치 폴백."""
    dirs = [run / "analysis"]
    workspace = run.parent.parent  # RUNS(workspace/runs)의 부모 = workspace(런타임 계약, 테스트도 동일 구조로 맞춘다)
    dirs.append(workspace / "analysis")
    return dirs


def _from_analysis_card(run: Path, bid: str) -> "tuple[str, str] | None":
    safe = bid.replace("/", "_")
    for d in _analysis_dir_candidates(run):
        p = d / f"{safe}_분석카드.md"
        if p.is_file():
            parsed = _parse_analysis_card(p)
            if parsed:
                return parsed
    return None


def _from_last_search(bid: str) -> "tuple[str, str] | None":
    data = _load_json(LAST_SEARCH_PATH)
    if not isinstance(data, dict):
        return None
    for entry in data.get("bids") or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("bid_no") == bid or entry.get("id") == bid:
            inst = (entry.get("inst_name") or "").strip()
            biz = (entry.get("bid_name") or "").strip()
            if inst or biz:
                return inst, biz
    return None


def _from_institution_research(run: Path) -> "str | None":
    doc = _load_json(run / "institution_research.json")
    if isinstance(doc, dict):
        inst = str(doc.get("institution") or "").strip()
        return inst or None
    return None


def _from_brief_title(run: Path) -> "str | None":
    p = run / "brief.md"
    if not p.is_file():
        return None
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return None
    m = _MD_HEADING_RE.search(text)
    return m.group(1).strip() if m else None


def infer_name(run: Path) -> "tuple[str, str]":
    """(한글명 후보, 유도 출처). 실패하면 (run.name, 'fallback_id')."""
    run = Path(run)
    bid = _bid_ref(run)

    if bid:
        parsed = _from_analysis_card(run, bid)
        if parsed:
            institution, business = parsed
            name = _combine(institution, _short_business(business, institution) if business else "")
            if name:
                return name, "분석카드"

    if bid:
        found = _from_last_search(bid)
        if found:
            institution, business = found
            name = _combine(institution, _short_business(business, institution) if business else "")
            if name:
                return name, "last_search"

    inst = _from_institution_research(run)
    if inst:
        return inst, "institution_research"

    title = _from_brief_title(run)
    if title:
        return title, "brief_title"

    return run.name, "fallback_id"


# ---------------------------------------------------------------------------
# 보관 폴더명 = YYYY-MM_한글명 (충돌 시 -2 접미)
# ---------------------------------------------------------------------------

def _month_prefix(run: Path) -> str:
    """run이 실제 만들어진(시작된) 달을 우선(파일링 의미상 이관 시각보다 origin이 유의미) —
    state.json created_at → run 폴더 mtime → (그래도 없으면) 오늘, 순으로 폴백한다."""
    parsed: "dt.datetime | None" = None
    try:
        import pipeline_state  # sibling, 지연 임포트(순환 방지)
        state = pipeline_state.load(run)
        stamp = (state or {}).get("created_at")
        if stamp:
            parsed = dt.datetime.fromisoformat(stamp)
    except Exception:
        parsed = None
    if parsed is None:
        try:
            parsed = dt.datetime.fromtimestamp(run.stat().st_mtime)
        except OSError:
            parsed = dt.datetime.now()
    return parsed.strftime("%Y-%m")


def build_folder_name(run: Path, korean_name: str) -> str:
    safe = sanitize_name(korean_name) or sanitize_name(run.name) or run.name
    return f"{_month_prefix(run)}_{safe}"


def _resolve_conflict(base_name: str, archive_root: Path) -> str:
    if not (archive_root / base_name).exists():
        return base_name
    n = 2
    while (archive_root / f"{base_name}-{n}").exists():
        n += 1
    return f"{base_name}-{n}"


# ---------------------------------------------------------------------------
# 이동/복귀
# ---------------------------------------------------------------------------

def archive_run(run: Path, *, name: "str | None" = None,
                archive_root: "Path | None" = None) -> dict[str, Any]:
    """run 전체를 보관소로 이동(자립 — state·journey·산출물 포함) + `_archive_meta.json` 기록."""
    run = Path(run)
    if not run.is_dir():
        raise ArchiveError(f"run 폴더 없음: {run}")
    root = archive_root if archive_root is not None else ARCHIVE_ROOT
    root.mkdir(parents=True, exist_ok=True)

    if name:
        korean_name, name_source = name, "user_specified"
    else:
        korean_name, name_source = infer_name(run)

    base_folder = build_folder_name(run, korean_name)
    folder_name = _resolve_conflict(base_folder, root)
    dest = root / folder_name
    run_id = run.name

    meta = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "korean_name": korean_name,
        "name_source": name_source,
        "folder_name": folder_name,
        "archived_at": dt.datetime.now().isoformat(timespec="seconds"),
    }

    shutil.move(str(run), str(dest))
    (dest / META_NAME).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "folder": folder_name, "dest": dest, "run_id": run_id,
        "korean_name": korean_name, "name_source": name_source,
    }


def restore(folder_name: str, *, runs_root: Path,
            archive_root: "Path | None" = None) -> dict[str, Any]:
    """보관 폴더를 meta의 원 기계 id로 `runs/`에 복귀(무손실). 동일 id 활성 존재 시 거부."""
    root = archive_root if archive_root is not None else ARCHIVE_ROOT
    src = root / folder_name
    if not src.is_dir():
        raise ArchiveError(f"보관 폴더 없음: {src}")
    meta = _load_json(src / META_NAME)
    if not isinstance(meta, dict) or not meta.get("run_id"):
        raise ArchiveError(f"보관 메타 없음/손상됨: {src / META_NAME} (수동 복구 필요 — 파괴하지 않았다)")
    run_id = str(meta["run_id"])
    dest = runs_root / run_id
    if dest.exists():
        raise ArchiveError(
            f"복귀 대상이 이미 활성 run으로 존재한다: {dest} "
            "(먼저 그 run을 정리하거나 이름을 바꾼 뒤 다시 시도하라)"
        )
    runs_root.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return {
        "restored_to": dest, "run_id": run_id,
        "korean_name": meta.get("korean_name"), "folder": folder_name,
    }


# ---------------------------------------------------------------------------
# 완료 판정 + 표(--list)
# ---------------------------------------------------------------------------

def is_completed(run: Path) -> bool:
    """승인·출하 완료 판정 — `approval.json` 존재(= `ship`/`approve`가 실제로 돈 실측 증거)."""
    return (Path(run) / "approval.json").is_file()


def count_active_completed(runs_root: Path) -> int:
    if not runs_root.is_dir():
        return 0
    return sum(1 for d in runs_root.iterdir() if d.is_dir() and is_completed(d))


def list_active_completed(runs_root: Path) -> list[dict]:
    rows: list[dict] = []
    if not runs_root.is_dir():
        return rows
    for d in sorted(runs_root.iterdir()):
        if not d.is_dir() or not is_completed(d):
            continue
        rec = _load_json(d / "approval.json") or {}
        rows.append({"id": d.name, "approved_at": rec.get("timestamp") or "?"})
    return rows


def list_archived(archive_root: "Path | None" = None) -> list[dict]:
    root = archive_root if archive_root is not None else ARCHIVE_ROOT
    rows: list[dict] = []
    if not root.is_dir():
        return rows
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        meta = _load_json(d / META_NAME) or {}
        rows.append({
            "folder": d.name,
            "run_id": meta.get("run_id", "?"),
            "korean_name": meta.get("korean_name", "?"),
            "archived_at": meta.get("archived_at", "?"),
        })
    return rows


def format_list(runs_root: Path, archive_root: "Path | None" = None) -> str:
    active = list_active_completed(runs_root)
    archived = list_archived(archive_root)
    lines = ["## 활성 — 완료(승인) run (보관 대기 후보)"]
    if active:
        header = f"{'run id':<42} 승인 시각"
        lines += [header, "-" * len(header)]
        lines += [f"{r['id']:<42} {r['approved_at']}" for r in active]
    else:
        lines.append("(없음)")
    lines.append("")
    lines.append("## 보관소")
    if archived:
        header = f"{'보관 폴더명':<38} {'원 기계 id':<32} 한글명"
        lines += [header, "-" * len(header)]
        lines += [f"{r['folder']:<38} {r['run_id']:<32} {r['korean_name']}" for r in archived]
    else:
        lines.append("(없음)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 안내 접점(ship 말미 / status 힌트 / start 임계) — 결정론 한 줄
# ---------------------------------------------------------------------------

def hint_line(run: Path) -> str:
    name, _source = infer_name(run)
    suggested = sanitize_name(name) or run.name
    return f"보관: archive --run {run.name} (한글명 제안: {suggested})"


def start_threshold_hint(runs_root: Path, threshold: int = 3) -> "str | None":
    n = count_active_completed(runs_root)
    if n < threshold:
        return None
    return f"완료 run {n}개 보관 대기 — `archive --list`로 확인."
