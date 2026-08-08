"""큐레이션 생애주기 — 디자인 준비 라인 §5-④-③ (DESIGN_ASSETS_LANE).

디자이너가 미리·따로 준비하는 **스타일 자산**(스킨=색 토큰 · 가이드=디자인 규칙)의 생애주기.
①②(gap 지속 로그 · Tier1 즉석 신설)에 이어 ③=**큐레이션 스타일의 "받아주는 집"**을 만든다.

세 가지 일 (전부 **선택 사항** — 아무 자산도 안 써도 덱은 무채 core로 나온다):
  1. **목록 보기** `scan_library`/`write_manifest` — 흩어진 스킨·가이드를 한 표로(legibility).
  2. **창고에 담기** `register` — run이 만든 좋은 스타일을 design-assets/로 복사·등록(싱크백).
  3. **참고자료 반입** `open_intake`/`scan_intake` — 디자인 단계에서 사람이 파일·링크를 넣으면
     핸드오프에 함께 실어 실행자에게 전달.

**불변식**(①② 형제 규율 계승):
  - **지어내지 않는다**: 원본 없는 자산을 register하지 않는다(원본 파일 없으면 중단). Tier
    자동분류·자동 마이그레이션 없음(콘텐츠가 부를 때 register — `avoid-speculative-coverage`).
  - **사람 편집 보존**: `refs.md`가 이미 있으면 덮지 않는다(사람이 붙인 링크가 산다).
  - **격리 보존**: 큐레이션=테마층 자산이다. 색↔형태 누수는 이 라인에서도 폴더로 강제된다.
  - **부가 관측, 차단자 아님**: 반입 스캔 실패가 refine 파이프라인을 막지 않는다(호출부가
    예외를 삼키고 [WARN]만 표면화).

이 모듈은 순수 헬퍼다(파일 I/O만 — 서브프로세스·상태기록은 호출부 proposal_pipeline).
"""

from __future__ import annotations

import datetime as dt
import json
import re
import shutil
from pathlib import Path

# ROOT 계층: curate.py = proposal_system/scripts/ → parents[1]=proposal_system · parents[2]=repo.
PS_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PS_ROOT / "config" / "pipeline.config.json"

SKINS_DIR = REPO_ROOT / "skins"
ASSETS_DIR = REPO_ROOT / "design-assets"
ASSET_SKINS = ASSETS_DIR / "skins"
ASSET_GUIDES = ASSETS_DIR / "guides"
ASSET_REFERENCES = ASSETS_DIR / "references"  # DF3: 확정 배경·장식 자산 싱크백 대상(§ 3-b 아래)
MANIFEST_JSON = ASSETS_DIR / "curation_manifest.json"
MANIFEST_MD = ASSETS_DIR / "curation_library.md"

# 참고자료 반입 (design_spec.REFS_DIRNAME과 같은 폴더 공유 — 시스템 프리뷰와 공존, 매니페스트로 구분)
REFS_DIRNAME = "design_refs"
REFS_NOTE = "refs.md"
REFS_MANIFEST = "refs_manifest.json"
_URL_RE = re.compile(r"https?://\S+")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)  # 안내 주석 속 예시 URL은 반입으로 세지 않는다

SCHEMA_VERSION = 1


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _relrepo(p: "str | Path") -> str:
    """repo 루트 상대경로(forward-slash) — 매니페스트 저장·표시용. 밖이면 그대로."""
    q = Path(p)
    try:
        return str(q.resolve().relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(q)


def _abs(relpath: "str | Path") -> Path:
    p = Path(relpath)
    return p if p.is_absolute() else (REPO_ROOT / p)


def _guide_path(path: "str | Path") -> Path:
    """가이드 경로 해석(proposal_pipeline._guide_path 미러 — 순환 import 회피).

    절대→그대로, 상대→ROOT(proposal_system) 우선, 없으면 REPO_ROOT.
    """
    q = Path(str(path))
    if q.is_absolute():
        return q
    a = PS_ROOT / q
    if a.exists():
        return a
    b = REPO_ROOT / q
    return b if b.exists() else a


# --- 1. 목록 보기 (라이브러리 스캔) -----------------------------------------

def scan_skins() -> list[dict]:
    """skins/*.json 을 스캔 → 스킨 자산 목록(_meta 그대로 옮김, 지어내지 않음)."""
    out: list[dict] = []
    if not SKINS_DIR.is_dir():
        return out
    for p in sorted(SKINS_DIR.glob("*.json")):
        meta: dict = {}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            meta = data.get("_meta") or {}
        except (OSError, json.JSONDecodeError):
            pass  # 파싱 실패해도 존재 자체는 기록(모르는 값은 빈 채로)
        sid = meta.get("name") or p.stem
        out.append({
            "kind": "skin",
            "id": sid,
            "source_path": _relrepo(p),
            "exists": True,
            "registered": (ASSET_SKINS / f"{sid}.json").is_file(),
            "self_contained": meta.get("self_contained"),
            "provenance": str(meta.get("provenance") or ""),
            "note": str(meta.get("derivation") or ""),
        })
    return out


def scan_guides() -> list[dict]:
    """config knowledge.design_guides 를 스캔 → 가이드 자산 목록(문자열/dict 양형 흡수)."""
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw = (config.get("knowledge") or {}).get("design_guides") or []
    out: list[dict] = []
    for item in raw:
        if isinstance(item, str):
            sp = _guide_path(item)
            gid = sp.stem
            prov, note = "", ""
        elif isinstance(item, dict):
            sp = _guide_path(item.get("spec_text") or item.get("spec_md") or "")
            gid = item.get("id") or sp.stem
            prov = _relrepo(_guide_path(item["meta"])) if item.get("meta") else ""
            note = "examples_dir 있음" if item.get("examples_dir") else ""
        else:
            continue
        out.append({
            "kind": "guide",
            "id": gid,
            "source_path": _relrepo(sp),
            "exists": sp.exists(),
            "registered": (ASSET_GUIDES / f"{gid}.md").is_file(),
            "self_contained": None,  # 가이드는 해당 없음(스킨 전용 개념)
            "provenance": prov,
            "note": note,
        })
    return out


def scan_library() -> list[dict]:
    """스킨 + 가이드 통합 목록(정렬: 종류→id)."""
    entries = scan_skins() + scan_guides()
    return sorted(entries, key=lambda e: (e["kind"], e["id"]))


def render_library_md(entries: list[dict]) -> str:
    lines = [
        "# 큐레이션 라이브러리 — 디자인 준비 라인",
        "",
        "미리 준비해둔 스타일 자산(스킨=색 토큰 · 가이드=디자인 규칙) 목록. **전부 선택 사항** — "
        "아무것도 안 골라도 덱은 무채(core)로 나온다. `curate --list`가 이 표를 갱신한다.",
        "",
        "- **창고보관** = design-assets/ 아래에 보관됨(체크아웃/싱크백 대상). `curate --register <id>`로 담는다.",
        "- 원본이 사라진 자산은 ⚠️로 표면화(지어내지 않는다).",
        "",
        "| 종류 | id | 원본 위치 | 창고보관 | 자기완결 | 출처/메모 |",
        "|---|---|---|---|---|---|",
    ]
    sc_label = {True: "예", False: "아니오", None: "-"}
    for e in entries:
        reg = "✅" if e.get("registered") else "—"
        sc = sc_label.get(e.get("self_contained"), "-")
        prov = (e.get("provenance") or e.get("note") or "").replace("|", "\\|").replace("\n", " ").strip()
        exists = "" if e.get("exists", True) else " ⚠️(원본없음)"
        lines.append(
            f"| {e['kind']} | {e['id']} | {e['source_path']}{exists} | {reg} | {sc} | {prov} |"
        )
    return "\n".join(lines) + "\n"


def write_manifest(entries: "list[dict] | None" = None) -> dict:
    """design-assets/curation_manifest.json(정본) + curation_library.md(사람) 갱신."""
    entries = scan_library() if entries is None else entries
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    counts = {
        "skins": sum(1 for e in entries if e["kind"] == "skin"),
        "guides": sum(1 for e in entries if e["kind"] == "guide"),
        "registered": sum(1 for e in entries if e.get("registered")),
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": _now(),
        "counts": counts,
        "entries": entries,
    }
    MANIFEST_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    MANIFEST_MD.write_text(render_library_md(entries), encoding="utf-8")
    return {"counts": counts, "entries": entries, "md": _relrepo(MANIFEST_MD)}


# --- 2. 창고에 담기 (register = 싱크백) --------------------------------------

def register(asset_id: str, kind: "str | None" = None) -> dict:
    """스킨/가이드 자산을 design-assets/로 복사·등록(멱등). 매니페스트 갱신.

    원본 파일이 없으면 중단(지어내지 않는다). id가 스킨·가이드 양쪽에 있으면 kind로 명시.
    """
    entries = scan_library()
    matches = [
        e for e in entries
        if e["id"] == asset_id and (kind is None or e["kind"] == kind)
    ]
    if not matches:
        known = sorted({e["id"] for e in entries})
        raise ValueError(
            f"큐레이션 자산 '{asset_id}' 없음 — `curate --list`로 확인(등록 후보: {known})"
        )
    if len(matches) > 1:
        kinds = sorted({e["kind"] for e in matches})
        raise ValueError(f"id '{asset_id}'가 여러 종류에 있음({kinds}) — --kind로 지정하라")
    e = matches[0]
    src = _abs(e["source_path"])
    if not src.is_file():
        raise ValueError(f"원본 파일 없음: {src} (지어내지 않는다 — 창고에 담을 수 없음)")
    if e["kind"] == "skin":
        ASSET_SKINS.mkdir(parents=True, exist_ok=True)
        dest = ASSET_SKINS / f"{e['id']}.json"
    else:
        ASSET_GUIDES.mkdir(parents=True, exist_ok=True)
        dest = ASSET_GUIDES / f"{e['id']}.md"
    shutil.copyfile(src, dest)
    write_manifest()  # registered 플래그 재반영
    return {"kind": e["kind"], "id": e["id"], "dest": _relrepo(dest)}


# --- 2b. 마스터 자산 싱크백 (DF3, DECK_FIRST_DESIGN.md §2-②·§3) -------------
#
# 기존 register()는 skins/*.json·config design_guides에서 스캔한 "스킨/가이드"만 다룬다(kind가
# 그 둘로 고정) — 마스터 시안이 확정한 배경 PNG·장식 이미지는 그 어느 kind도 아니라 register()가
# 커버하지 못한다(대상 자체가 스캔 후보에 없음). §1 레인 폴더 중 `references/`(이미 seed/ 시드
# 레퍼런스가 쓰는 폴더)가 이 자산의 자리다 — register()의 창고 담기 문법(원본 없으면 중단·복사·
# 멱등)을 그대로 따르되, "선택 사항·사람이 명시적으로 부를 때만"(register()와 같은 철학 — Tier
# 자동분류/자동 마이그레이션 없음, avoid-speculative-coverage) 별도 함수로 최소 추가한다. run별
# 폴더로 격리한다(여러 run의 마스터 자산이 references/ 밑에서 섞이지 않게).

def sync_master_assets(run: "str | Path", *, subdir: "str | None" = None) -> dict:
    """DF3: `run/design_contract.json`이 동결한 배경(chrome.frame.image)·장식(decor_slots) 자산을
    `design-assets/references/<subdir 또는 run명>/`으로 복사(싱크백). 선택 사항 — 명시 호출 시만
    (`curate --sync-master --run <run>`), master-apply가 자동으로 부르지 않는다(창고에 담을지는
    사람이 고른다 — register()와 같은 문 앞 원칙).

    원본이 없는 항목은 지어내지 않고 missing으로만 표면화(중단하지 않음 — 나머지는 계속 담는다).
    """
    run = Path(run)
    contract_path = run / "design_contract.json"
    if not contract_path.is_file():
        raise ValueError(f"design_contract.json 없음: {contract_path} (먼저 imagedeck --master-apply)")
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"design_contract.json 파싱 실패: {exc}") from exc
    chrome = contract.get("chrome_contract") or {}
    frame = (chrome.get("chrome") or {}).get("frame") or {}
    dest_dir = ASSET_REFERENCES / (subdir or run.name)

    copied: list[str] = []
    missing: list[str] = []

    def _copy(rel: "str | None") -> None:
        if not rel:
            return
        src = Path(str(rel))
        if not src.is_absolute():
            src = run / rel
        if not src.is_file():
            missing.append(str(rel))
            return
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        if dest.exists() and dest.resolve() != src.resolve():
            stem, suf = src.stem, src.suffix
            i = 1
            while (dest_dir / f"{stem}_{i}{suf}").exists():
                i += 1
            dest = dest_dir / f"{stem}_{i}{suf}"
        if dest.resolve() != src.resolve():
            shutil.copyfile(src, dest)
        copied.append(_relrepo(dest))

    _copy(frame.get("image"))
    for slot in chrome.get("decor_slots") or []:
        _copy(slot.get("image"))
    if not copied and not missing:
        raise ValueError(
            f"{contract_path}에 background/decor_slots가 없다 — 싱크백할 자산이 없다"
            "(마스터 시안에 background/decor_slots를 지정해 --master-apply로 먼저 동결하라)"
        )
    return {"dest": _relrepo(dest_dir), "copied": copied, "missing": missing}


# --- 3. 참고자료 반입 (파일 + 링크) ------------------------------------------

_REFS_TEMPLATE = """# 참고자료 — {run_id}

이 폴더(`{refs}/`)는 **이 덱의 디자인에 참고할 자료**를 담는 곳입니다. **선택 사항**입니다 —
아무것도 안 넣어도 디자인은 진행됩니다.

## 파일로 주기
참고 이미지·PDF·덱을 이 폴더에 그냥 넣으세요. 디자인 고도화 핸드오프(`refine --handoff`)가
자동으로 목록에 넣어 실행자에게 함께 전달합니다.
(시스템이 만든 조각 프리뷰 png·{manifest}·이 파일은 자동 제외됩니다.)

## 링크로 주기
아래에 URL을 붙여넣으세요 — 한 줄에 하나, 뒤에 메모를 달아도 됩니다:

<!-- 링크를 이 줄 아래에 추가 (예: https://example.com/moodboard  발주처가 좋아한 톤) -->
"""


def open_intake(run: "str | Path") -> Path:
    """design_refs/ 폴더 + refs.md 안내를 준비(사람이 파일·링크를 넣을 통로를 연다).

    refs.md가 이미 있으면 덮지 않는다(사람이 붙인 링크 보존). 폴더는 collect가 이미
    만들 수 있으나(시스템 프리뷰), 반입 통로 표면화는 여기서 보장한다.
    """
    run = Path(run)
    refs = run / REFS_DIRNAME
    refs.mkdir(parents=True, exist_ok=True)
    note = refs / REFS_NOTE
    if not note.exists():
        note.write_text(
            _REFS_TEMPLATE.format(run_id=run.name, refs=REFS_DIRNAME, manifest=REFS_MANIFEST),
            encoding="utf-8",
        )
    return note


def _system_ref_names(run: Path) -> set[str]:
    """refs_manifest.json에 등재된 시스템 파일 basename(사용자 반입 파일과 구분)."""
    mani = run / REFS_DIRNAME / REFS_MANIFEST
    names: set[str] = set()
    if not mani.is_file():
        return names
    try:
        data = json.loads(mani.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return names
    for items in (data.get("per_slide") or {}).values():
        for it in items or []:
            f = it.get("file")
            if f:
                names.add(Path(f).name)
    return names


def scan_intake(run: "str | Path") -> dict:
    """사람이 넣은 참고자료 회수 → {"files": [basename...], "links": [url...]}.

    파일 = design_refs/ 안 파일 중 시스템 프리뷰·매니페스트·refs.md를 뺀 나머지(사용자 반입).
    링크 = refs.md의 http(s) URL(순서 보존·중복 제거). 없으면 빈 목록(지어내지 않는다).
    """
    run = Path(run)
    refs = run / REFS_DIRNAME
    if not refs.is_dir():
        return {"files": [], "links": []}
    reserved = {REFS_NOTE, REFS_MANIFEST}
    system = _system_ref_names(run)
    files: list[str] = []
    for p in sorted(refs.iterdir()):
        if not p.is_file() or p.name in reserved or p.name in system:
            continue
        files.append(p.name)
    links: list[str] = []
    note = refs / REFS_NOTE
    if note.is_file():
        text = _COMMENT_RE.sub("", note.read_text(encoding="utf-8"))  # 예시 주석 제거 후 스캔
        seen: set[str] = set()
        for url in _URL_RE.findall(text):
            url = url.rstrip(").,>")  # 마크다운 꼬리 문자 정리
            if url not in seen:
                seen.add(url)
                links.append(url)
    return {"files": files, "links": links}
