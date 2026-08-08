# -*- coding: utf-8 -*-
"""PT_DESIGN proposal automation orchestrator.

This script keeps the existing demo/core projects read-only and writes all
practical run artifacts under PT_DESIGN/proposal_system/workspace.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

# Windows 기본 콘솔/파이프(cp949)에서 em-dash 등 비수록 문자로 print가 UnicodeEncodeError로
# 죽는 것 방지 — 출력은 진단용이라 크래시보다 대체문자(?)가 낫다. (W7 스모크 앵커 검증에서 실측)
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
import archive  # noqa: E402  (sibling module — W31 리허설 마찰9 run 보관소 왕복)
import company  # noqa: E402  (sibling module — W31 리허설 마찰6 제안사 자사 프로필 창고)
import deck_review  # noqa: E402  (sibling module — W3c 승인 전 덱 평가)
import curate  # noqa: E402  (sibling module — 큐레이션 생애주기: 라이브러리·register·참고자료 반입, DESIGN_ASSETS_LANE §5-④-③)
import design_brief  # noqa: E402  (sibling module — W3a 디자인 브리핑)
import design_contract  # noqa: E402  (sibling module — W31 R2·R5 run별 디자인 계약)
import gates  # noqa: E402  (sibling module — W31 리허설 마찰2 관문 다이얼 + 조건부 승격)
import imagedeck  # noqa: E402  (sibling module — W28 이미지 렌더 트랙: bundle/collect/compose)
import journey_check  # noqa: E402  (sibling module — W31 리허설 마찰4 — journey 폴더 검토_체크.md)
import journey_folders  # noqa: E402  (sibling module — W31 R7 단계 폴더 여정)
import knowledge_gaps  # noqa: E402  (sibling module — 가공 어휘 갭 로그, DESIGN_ASSETS_LANE §5-④-①)
import knowledge_ledger  # noqa: E402  (sibling module — ε패킷 지식 소비 체계: config 1점화·원장·지시 오버레이·안전장치)
import message_map  # noqa: E402  (sibling module — W15 메시지맵 결정 게이트 산출물)
import pipeline_state  # noqa: E402  (sibling module — N1 공정 상태머신)
import review_resolve  # noqa: E402  (sibling module — W5 검토요망 해소)
import skeleton  # noqa: E402  (sibling module — W10 표준 시나리오 스켈레톤 역제안)
import storyline_prompt  # noqa: E402  (sibling module — N2 storyline 프롬프트 공용 부품)


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
APP_ROOT = REPO_ROOT / "app"


def _pack_dir(pack) -> Path:
    """활성 packs/ 우선, 격리 packs_excluded/ 폴백 — 배제 하우스 자산은 --pack 명시 시만(결정 11·12).

    W31 E3: 실물은 <개발 원본 전용 경로> 격리, 이 경로는 상시 부재(is_dir() 폴백만 수행).
    """
    active = REPO_ROOT / "packs" / str(pack)
    if active.is_dir():
        return active
    excluded = REPO_ROOT / "packs_excluded" / str(pack)
    return excluded if excluded.is_dir() else active
CONFIG_PATH = ROOT / "config" / "pipeline.config.json"
WORKSPACE = ROOT / "workspace"
RUNS = WORKSPACE / "runs"
# NORTHSTAR 결정 13(W25): bid 단위 분석카드/프롬프트 산출물 위치(run들과 나란히).
ANALYSIS_DIR = WORKSPACE / "analysis"
ANALYSIS_DIR_LEGACY = ROOT / "vendor" / "proposal_core" / "analysis"
PROMPTS = ROOT / "prompts"
CATALOG = ROOT / "catalogs" / "layout_templates.json"
DESIGN_TIPS = ROOT / "design_tips"
ANONYMIZATION_CONFIG = APP_ROOT / "anonymization.config.json"


class PipelineInputError(ValueError):
    """Clear user-facing error for the render wiring command."""


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _record_state(run: Path, stage: str, **kwargs: Any) -> None:
    """N1: 커맨드 완료 시 자기 단계를 기록. 기록 실패가 산출물 생성을 되돌리지 않는다."""
    try:
        pipeline_state.record(run, stage, **kwargs)
    except Exception as exc:  # pragma: no cover - 기록은 부가 기능
        print(f"[WARN] pipeline_state 기록 실패({stage}): {exc}", file=sys.stderr)


def _checkpoint_cleared(run: Path, name: str) -> bool:
    state = pipeline_state.load(run)
    return bool(((state.get("checkpoints") or {}).get(name) or {}).get("cleared_at"))


def _require_human_ack(run: Path, name: str) -> dict[str, Any] | None:
    """사람 관문은 recorded clearance 또는 대시보드 ack만 통과시킨다."""
    state = pipeline_state.load(run)
    recorded = ((state.get("checkpoints") or {}).get(name) or {})
    cleared_at = recorded.get("cleared_at")
    changed = pipeline_state.is_stale(run, name, cleared_at) if cleared_at else None
    if cleared_at and not changed:
        return None
    ack = pipeline_state.read_ack(run, name)
    ack_changed = pipeline_state.is_stale(run, name, ack["at"]) if ack is not None else None
    if changed and (ack is None or ack_changed):
        label = pipeline_state.CHECKPOINT_LABEL[name]
        raise PipelineInputError(
            f"[사람 관문] waiting_human:{name} '{label}' "
            "(ack가 산출물 변경보다 오래됨 - 재검토 필요)"
        )
    if ack is None:
        label = pipeline_state.CHECKPOINT_LABEL[name]
        raise PipelineInputError(
            f"[사람 관문] '{label}' ack가 없다. "
            "대시보드(http://127.0.0.1:8754)에서 검토를 완료하라."
        )
    if ack_changed:
        raise PipelineInputError(
            f"[사람 관문] waiting_human:{name} "
            "(ack가 산출물 변경보다 오래됨 - 재검토 필요)"
        )
    return ack


def _record_knowledge_gaps(run: Path, gaps: list, source: str) -> None:
    """가공: catalog_gap을 run/knowledge_gaps.md(+json)에 영속화 + design-assets/gaps/ 싱크.

    부가 관측 — 차단자 아님(기록 실패가 wireframe/refine 파이프라인을 막지 않는다,
    DESIGN_ASSETS_LANE §5-④-①)."""
    try:
        result = knowledge_gaps.record(run, gaps, source)
        if result.get("path"):
            knowledge_gaps.sync_to_lane(run)
    except Exception as exc:  # pragma: no cover - 기록은 부가 기능
        print(f"[WARN] knowledge_gaps 기록 실패({source}): {exc}", file=sys.stderr)


def as_path(value: str | Path) -> Path:
    return Path(str(value))


def rel_or_abs(path: str | Path) -> Path:
    p = as_path(path)
    if p.is_absolute():
        return p
    return ROOT / p


def _guide_path(path: str | Path) -> Path:
    """가이드 자산 경로 해석: 절대→그대로, 상대→ROOT(proposal_system) 우선, 없으면 REPO_ROOT."""
    q = as_path(path)
    if q.is_absolute():
        return q
    a = ROOT / q
    if a.exists():
        return a
    b = REPO_ROOT / q
    return b if b.exists() else a


def resolve_design_guides(config: dict[str, Any], selected: str | list | None = None) -> list[dict]:
    """연화된 가이드 계약(정규형만 소비). CONTEXT/DESIGN_DIRECTOR_PASS.md §2.1.

    config knowledge.design_guides 항목은 둘 다 허용:
      - 문자열 경로  → spec_text만 있는 최소 가이드(id=파일 stem)
      - dict         → {id, spec_text, examples_dir?, tokens?, meta?, explicit_only?}
    필수는 spec_text(규칙 텍스트) 하나. 나머지는 옵션.
    selected(id 쉼표문자열/리스트/None): 선택·정렬. None=전체(단 explicit_only=true 항목은 제외 —
    창고 성격 가이드는 --design-guide로 id를 직접 지정할 때만 주입된다. W31 P2).
    """
    raw = (config.get("knowledge") or {}).get("design_guides") or []
    guides: list[dict] = []
    for item in raw:
        if isinstance(item, str):
            sp = _guide_path(item)
            guides.append({"id": sp.stem, "spec_text": sp, "examples": [], "tokens": None, "meta": None,
                            "explicit_only": False})
        elif isinstance(item, dict):
            sp = _guide_path(item.get("spec_text") or item.get("spec_md") or "")
            examples: list[str] = []
            ed = item.get("examples_dir")
            if ed:
                edp = _guide_path(ed)
                if edp.is_dir():
                    examples = sorted(str(x) for x in edp.glob("*.png"))
            guides.append({
                "id": item.get("id") or sp.stem,
                "spec_text": sp,
                "examples": examples,
                "tokens": _guide_path(item["tokens"]) if item.get("tokens") else None,
                "meta": _guide_path(item["meta"]) if item.get("meta") else None,
                "explicit_only": bool(item.get("explicit_only")),
            })
    if selected:
        want = selected.split(",") if isinstance(selected, str) else list(selected)
        want = [w.strip() for w in want if str(w).strip()]
        by_id = {g["id"]: g for g in guides}
        missing = [w for w in want if w not in by_id]
        if missing:
            raise PipelineInputError(
                f"--design-guide 미등록 id: {missing} (등록: {sorted(by_id)})"
            )
        guides = [by_id[w] for w in want]
    else:
        guides = [g for g in guides if not g.get("explicit_only")]
    return guides


# ---------------------------------------------------------------------------
# add-skin — 새 레퍼런스(PPTX/PDF) → 정규형 가이드(스킨) 구조적 통합.
#   ①포팅(tools/port_design_guide.py) ②선택 tokens(app/skin_extract.py, pptx만)
#   ③config.knowledge.design_guides 자동 등록(멱등) ④검증(resolve_design_guides).
#   런북·개념 = DESIGN_GUIDE_PORTING.md / CONTEXT/DESIGN_DIRECTOR_PASS.md §2.1.
# ---------------------------------------------------------------------------
TOOLS_DIR = REPO_ROOT / "tools"
SKINS_DIR = REPO_ROOT / "skins"
# 포터/추출기는 python-pptx·pdfplumber·win32com·poppler 의존 → 번들 런타임 인터프리터 우선.
# W32: 기계 국소 경로를 코드에 박지 않는다(공개 배포에 개발자 홈 경로가 새던 자리).
# 지정 통로 = 인자 > env PORT_DESIGN_PYTHON > 리포 루트 `.porter-python`(1줄, git 무시) > 현재 인터프리터.
_PORTER_PY_FILE = REPO_ROOT / ".porter-python"


def _porter_python_from_file() -> str | None:
    """`.porter-python` 1줄 파일에서 인터프리터 경로를 읽는다. 없으면 None(정상)."""
    try:
        text = _PORTER_PY_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text.splitlines()[0].strip().strip('"') if text else None


def _resolve_porter_python(arg: str | None) -> str:
    """포터/추출기용 파이썬 해석: 인자 > env PORT_DESIGN_PYTHON > .porter-python > 현재 인터프리터."""
    for c in (arg, os.environ.get("PORT_DESIGN_PYTHON"), _porter_python_from_file()):
        if c and Path(c).exists():
            return c
    return sys.executable


def _repo_rel(p: Path) -> str:
    """REPO_ROOT 상대 포워드슬래시 경로(config 저장용 — _guide_path가 REPO_ROOT 폴백 해석)."""
    try:
        return Path(os.path.relpath(p.resolve(), REPO_ROOT)).as_posix()
    except ValueError:
        return p.resolve().as_posix()  # 다른 드라이브 등 → 절대경로


def register_design_guide(config_path: Path, entry: dict) -> str:
    """config.knowledge.design_guides에 dict 항목을 멱등 등록(같은 id 있으면 교체). 반환=상태."""
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    know = cfg.setdefault("knowledge", {})
    guides = know.setdefault("design_guides", [])
    status = "added"
    for i, it in enumerate(guides):
        if isinstance(it, dict) and it.get("id") == entry["id"]:
            guides[i] = entry
            status = "replaced"
            break
        # 문자열 최소가이드의 stem이 같은 id면 충돌 경고(교체하지 않음).
        if isinstance(it, str) and as_path(it).stem == entry["id"]:
            raise PipelineInputError(
                f"id '{entry['id']}'가 기존 문자열 가이드('{it}')의 stem과 충돌 — 다른 --id 사용")
    if status == "added":
        guides.append(entry)
    config_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return status


def add_skin_cmd(args: argparse.Namespace) -> int:
    src = as_path(args.source)
    if not args.no_port and not src.is_absolute():
        src = (REPO_ROOT / src)
    if not args.no_port and not src.exists():
        raise PipelineInputError(f"--source 없음: {src}")
    gid = args.id.strip()
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", gid):
        raise PipelineInputError(f"--id는 영숫자·_.- 만: {gid!r}")
    out = as_path(args.out) if args.out else (REPO_ROOT / "_source" / "design_guides" / f"{gid}_ported")
    if not out.is_absolute():
        out = REPO_ROOT / out
    py = _resolve_porter_python(args.python)
    is_pptx = src.suffix.lower() == ".pptx"

    plan = [f"id={gid}", f"source={display_path(src)}", f"out={display_path(out)}",
            f"tokens={'yes(pptx)' if args.tokens and is_pptx else 'no'}", f"python={py}"]
    print("[ADD-SKIN] " + " · ".join(plan))
    if args.dry_run:
        print("[DRY-RUN] 실행 안 함")
        return 0

    # ① 포팅(임포터) — 이미 폴더가 있으면 --no-port로 건너뜀.
    if not args.no_port:
        porter = TOOLS_DIR / "port_design_guide.py"
        if not porter.is_file():
            # 공개 배포판은 임포터를 싣지 않는다(개발 원본 전용 창고를 참조하는 도구).
            raise PipelineInputError(
                "레퍼런스 임포터(tools/port_design_guide.py)가 이 사본에 없습니다 — 공개 배포판에서 "
                "제외된 개발 원본 전용 도구입니다. 이미 포팅된 가이드 폴더가 있다면 "
                "`add-skin --no-port --out <폴더>` 로 등록만 하세요."
            )
        cmd = [py, str(porter), "--source", str(src), "--out", str(out)]
        if args.process_md:
            cmd += ["--process-md", str(rel_or_abs(args.process_md))]
        if args.title:
            cmd += ["--title", args.title]
        print(f"  [port] {' '.join(cmd[1:3])} …")
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            sys.stderr.write((r.stderr or r.stdout or "")[-1500:] + "\n")
            raise PipelineInputError(f"포팅 실패(exit {r.returncode}) — 의존성(python-pptx/pdfplumber/poppler/COM) 확인")
    spec = out / "design_guide_ai.md"
    if not spec.exists():
        raise PipelineInputError(f"포팅 산출 없음: {spec} (포터 실패 또는 잘못된 --out)")

    # ② 선택: 결정론 tokens 스킨(pptx만) → skins/<id>.json
    tokens_rel = None
    if args.tokens:
        if not is_pptx:
            print("  [tokens] 건너뜀 — PDF는 geometry 없음(비전 가이드만).")
        else:
            SKINS_DIR.mkdir(parents=True, exist_ok=True)
            tok_out = SKINS_DIR / f"{gid}.json"
            tcmd = [py, str(APP_ROOT / "skin_extract.py"), str(src), str(tok_out)]
            print(f"  [tokens] skin_extract → {display_path(tok_out)}")
            tr = subprocess.run(tcmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if tr.returncode != 0 or not tok_out.exists():
                sys.stderr.write((tr.stderr or tr.stdout or "")[-1000:] + "\n")
                raise PipelineInputError("skin_extract 실패 — tokens 스킨 미생성")
            tokens_rel = _repo_rel(tok_out)

    # ③ config 등록(멱등)
    entry: dict[str, Any] = {"id": gid, "spec_text": _repo_rel(spec)}
    ex_dir = out / "assets" / "slides"
    if ex_dir.is_dir() and any(ex_dir.glob("*.png")):
        entry["examples_dir"] = _repo_rel(ex_dir)
    meta = out / "manifest.json"
    if meta.exists():
        entry["meta"] = _repo_rel(meta)
    status = register_design_guide(CONFIG_PATH, entry)

    # ④ 검증 — 새 id가 정규형으로 해석되는지.
    guides = resolve_design_guides(load_config(), gid)
    g = guides[0]
    print(f"[ADD-SKIN OK] design_guides {status}: id={gid} "
          f"(examples={len(g['examples'])}, meta={'y' if g['meta'] else 'n'})")
    print(f"  가이드 사용: stage8/stage9 --design-guide {gid}")
    if tokens_rel:
        print(f"  결정론 스킨: render --skins {gid}  (skins/{gid}.json)")
    return 0


def now_id() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def make_run_dir(name: str | None = None) -> Path:
    run = RUNS / (name or now_id())
    run.mkdir(parents=True, exist_ok=True)
    return run


def read_text(path: str | Path, max_chars: int | None = None) -> str:
    p = rel_or_abs(path)
    if not p.exists():
        return f"[MISSING] {p}"
    text = p.read_text(encoding="utf-8", errors="replace")
    if max_chars and len(text) > max_chars:
        return text[:max_chars] + f"\n\n[TRUNCATED {len(text) - max_chars} chars from {display_path(p)}]"
    return text


def display_path(path: str | Path) -> str:
    p = Path(path)
    try:
        return str(p.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(p)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def list_existing(paths: list[str]) -> list[str]:
    return [str(rel_or_abs(p)) for p in paths if rel_or_abs(p).exists()]


def find_pj_pt_texts(config: dict[str, Any], limit: int = 8) -> list[Path]:
    # 참고 제안서 텍스트는 실 거래 자료라 공개 배포판에서 자산·config 키가 함께 빠진다.
    # 키 부재 = 정상(빈 목록) — 크래시 금지.
    files: list[Path] = []
    for pattern in config.get("knowledge", {}).get("pj_pt_text_globs", []):
        pat = str(rel_or_abs(pattern))
        files.extend(Path(p) for p in glob.glob(pat))
    uniq: list[Path] = []
    seen = set()
    for f in sorted(files, key=lambda p: (p.name, str(p))):
        if f.exists() and str(f) not in seen:
            uniq.append(f)
            seen.add(str(f))
    return uniq[:limit]


def collect_markdown_files(folder: Path, exclude_names: set[str] | None = None) -> list[Path]:
    exclude_names = exclude_names or set()
    if not folder.exists():
        return []
    return sorted(
        p for p in folder.rglob("*.md")
        if p.name not in exclude_names and not any(part.startswith(".") for part in p.parts)
    )


def csv_list(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def selected_strategy_pattern_sets(config: dict[str, Any], args: argparse.Namespace) -> list[str]:
    override = csv_list(getattr(args, "pattern_sets", None))
    if override is not None:
        return override
    sets = config.get("knowledge", {}).get("strategy_pattern_sets")
    if not isinstance(sets, list):
        return []
    return [str(item).strip() for item in sets if str(item).strip()]


def resolve_strategy_pattern_sets(config: dict[str, Any], args: argparse.Namespace) -> list[dict[str, Any]]:
    selected = selected_strategy_pattern_sets(config, args)
    if not selected:
        return []

    registry = config.get("knowledge", {}).get("strategy_pattern_registry", {})
    if not isinstance(registry, dict):
        registry = {}

    resolved: list[dict[str, Any]] = []
    for name in selected:
        entry = registry.get(name)
        if not isinstance(entry, dict):
            print(f"[WARN] strategy pattern set not found: {name}", file=sys.stderr)
            continue
        resolved.append(
            {
                "name": name,
                "pattern": entry.get("pattern"),
                "profiles_dir": entry.get("profiles_dir"),
            }
        )

    if not resolved:
        print("[WARN] no valid strategy pattern sets; falling back to legacy strategy_pattern", file=sys.stderr)
        return []
    return resolved


# 참고 자산이 없을 때 사람에게 하는 말 — 침묵도, 크래시도 아니게.
# (W32 공개판: 실 클라이언트 자료인 strategy_lib·draft·raw_text는 배포판에서 빠진다.
#  빠진 자산은 '고장'이 아니라 '이 사본에는 없음'이며, 무엇이 대신인지 한 줄로 말한다.)
ABSENT_ASSET_NOTES = {
    "strategy_profiles": (
        "전략 프로파일(수주작 패턴 라이브러리)이 없습니다 — 공개 배포판에는 실 수주작 자산이 "
        "빠져 있습니다. 대신 pull-knowledge/기획지식/에 당신의 카드를 넣으면 같은 자리에서 쓰입니다."
    ),
    "stage5_storylines": (
        "기성 스토리라인 예시가 없습니다 — 실 제안 초안이라 공개 배포판에서 빠졌습니다. "
        "`start --brief <요구사항.md>` 로 당신의 run에서 새로 만듭니다."
    ),
    "pj_pt_texts": (
        "참고 제안서 텍스트 샘플이 없습니다 — 실 거래 자료라 공개 배포판에서 빠졌습니다. "
        "없어도 공정(start→go→ship)은 그대로 돕니다."
    ),
}


def status(json_mode: bool = False) -> dict[str, Any]:
    config = load_config()
    paths = {k: str(rel_or_abs(v)) for k, v in config["paths"].items()}
    path_status = {k: rel_or_abs(v).exists() for k, v in config["paths"].items()}

    core = rel_or_abs(config["paths"]["proposal_core"])
    knowledge = config.get("knowledge", {})
    # config 키 자체가 없어도(자산과 함께 지워진 경우) 크래시하지 않는다 — 부재는 정상 상태.
    strategy_dir_cfg = knowledge.get("strategy_profiles_dir")
    strategy_profiles = (
        collect_markdown_files(rel_or_abs(strategy_dir_cfg), {"_패턴.md"})
        if strategy_dir_cfg else []
    )
    storylines = [core / p for p in config.get("stage5", {}).get("storylines", [])]
    drafts = sorted((core / "draft").glob("*_초안.pptx")) if (core / "draft").exists() else []
    pj_texts = find_pj_pt_texts(config)
    design_tip_files = collect_markdown_files(DESIGN_TIPS)

    existing_storylines = [str(p) for p in storylines if p.exists()]
    notes = [
        ABSENT_ASSET_NOTES[key]
        for key, present in (
            ("strategy_profiles", strategy_profiles),
            ("stage5_storylines", existing_storylines),
            ("pj_pt_texts", pj_texts),
        )
        if not present
    ]

    result = {
        "paths": paths,
        "path_status": path_status,
        "stage5_storylines": existing_storylines,
        "stage5_existing_drafts": [str(p) for p in drafts],
        "strategy_profiles_count": len(strategy_profiles),
        "strategy_profiles": [str(p) for p in strategy_profiles[:12]],
        "pj_pt_text_count_sampled": len(pj_texts),
        "pj_pt_texts_sampled": [str(p) for p in pj_texts],
        "design_tips_count": len(design_tip_files),
        "design_tips": [str(p) for p in design_tip_files],
        "absent_asset_notes": notes,
        "workspace": str(WORKSPACE),
    }
    if not json_mode:
        print("# 제안 시스템 status")
        for k, ok in path_status.items():
            print(f"- {k}: {'OK' if ok else 'MISSING'} — {paths[k]}")
        print(f"- stage5 storylines: {len(result['stage5_storylines'])}")
        print(f"- existing drafts: {len(result['stage5_existing_drafts'])}")
        print(f"- strategy profiles: {len(strategy_profiles)}")
        print(f"- pj_pt text samples: {len(pj_texts)}")
        print(f"- design tips: {len(design_tip_files)}")
        for note in notes:
            print(f"  · {note}")
    return result


def prompt_header(stage: int, title: str, sources: list[str]) -> str:
    src = "\n".join(f"- {display_path(s)}" for s in sources)
    return f"""# {stage}단계 번들 — {title}

생성시각: {dt.datetime.now().isoformat(timespec='seconds')}

## 사용한 소스

{src}

---

"""


def bundle_storyline_from_brief(run: Path, args: argparse.Namespace) -> Path:
    """N2: brief.md → storyline 생성 프롬프트 번들.

    나라장터 어댑터(`dashboard/server.py:build_storyline_prompt`)와 같은 부품
    (`storyline_prompt.render_prompt`)을 쓴다 — 소스만 "공고메타+분석카드"에서
    "브리프 문서"로 바뀐다(NORTHSTAR_REDESIGN §1-C1).
    """
    brief_path = run / "brief.md"
    if not brief_path.is_file():
        raise PipelineInputError(f"brief.md가 run에 없다: {brief_path} (`start --brief`로 만든 run이 맞는지 확인)")
    pack = getattr(args, "pack", None) or "core"
    pack_dir = _pack_dir(pack)
    if not (pack_dir / "templates.json").is_file():
        raise PipelineInputError(f"pack templates.json이 없다: {pack_dir}")
    catalog = storyline_prompt.load_catalog(pack_dir)
    # W10: 역제안 확정 후엔 백지 창작이 아니라 '확정된 스켈레톤 구조 채우기'다 —
    # skeleton.json이 있으면 그 구조를 프롬프트에 주입한다(사용자가 뺀/바꾼 장표가 반영됨).
    skel = skeleton.load_skeleton(run)
    skeleton_block = skeleton.structure_block(skel) if skel else None
    intro = (
        "당신은 제안서 스토리라인 설계자입니다.\n"
        "아래 브리프 문서만 사용하여 기존 proposal_pipeline.py render의 storyline 입력으로\n"
        "수용 가능한 JSON 객체 하나를 작성하세요. 설명, 마크다운 코드펜스, JSON 바깥 텍스트는 금지합니다."
    )
    if skeleton_block:
        intro += (
            "\n※ 아래 '확정된 스켈레톤 구조'는 사용자가 검토·확정한 덱의 뼈대입니다 — "
            "그 구성(슬라이드 수·순서·section·template_id)을 유지하고 예시 데이터를 브리프의 실제 사실로 채우세요."
        )
    # W15(결정 9①④): message_map을 스토리라인의 **메시지 계약**으로 주입한다 —
    # 모든 슬라이드 message가 어느 축을 지지하는지 axis id를 명시하게 한다(스켈레톤·리듬 종속은 W16).
    mm_doc = message_map.load(run)
    message_map_block = None
    if mm_doc is not None:
        message_map_block = (
            "[message_map — 이 덱의 메시지 계약 (반드시 지킬 것 · 결정 9①④⑤)]\n"
            + message_map.render_for_prompt(mm_doc)
            # W32 마찰29: 종전에는 message 본문에 축 id를 함께 적으라고 지시했으나(예: "(axis1 지지)"),
            # 그 텍스트를 기계가 소비하는 곳이 없고(추적성은 supports_axis 필드가 전담) 렌더러는
            # key_message를 그대로 조판하므로 **심사위원이 보는 장표에 내부 전략 주석이 노출**됐다
            # — 같은 프롬프트의 청중 계약("내부 전략 유출 금지")과 정면 충돌. 추적 채널을 필드로 일원화한다.
            + "\n※ 모든 슬라이드의 message(핵심 메시지)는 위 전략 축 중 하나를 지지해야 한다. "
            "축과 무관한 슬라이드는 만들지 마라 — 장표는 메시지가 요구하는 것만 도출한다. "
            "다만 message 본문에 축 id를 적지 마라(\"(axis1 지지)\" 같은 내부 표기는 청중이 읽는 "
            "장표에 그대로 조판된다) — 축 추적은 아래 supports_axis 필드가 전담한다."
            "\n※ supports_axis(결정 9①): 각 슬라이드에 그 슬라이드가 지지하는 축 id를 "
            "supports_axis 필드로 명시하라 — 스켈레톤이 이미 배정했으면 유지하라(장표→메시지 추적성)."
            "\n※ 분량 리듬(결정 9⑤): 스토리/전략 장표는 얇게(약 20~70어절), 근거 장표는 두껍게 "
            "(약 80~220어절)로 써서 덱 전체 최대/최소 어절 동적 범위가 ≥3배가 되게 하라 "
            "(균질 분포는 AI티의 내용 측 원인). 스켈레톤이 length_band를 배정했으면 그 밴드를 "
            "목표로 삼아라 — 강제는 아니고 gating_report가 실측·표면화한다."
        )
    institution_block = _institution_research_block(run)  # W26: 있으면 직인용 훅 동봉(없으면 바이트 불변)
    company_block = _company_profile_block(run)  # W31 리허설 마찰6: 있으면 자사 프로필 동봉(없으면 바이트 불변)
    master_design_block = _master_design_block(run)  # W31 R10 v2: 마스터 시안 확정 시만 동봉
    kc_profile = gates.load_config(run)["profile"]  # ε패킷: 지식 pull+보고 의무(config 표 소비)
    knowledge_block = knowledge_ledger.handoff_block(run, "storyline", kc_profile)
    prompt = storyline_prompt.render_prompt(
        intro=intro,
        source_sections=f"[브리프 문서]\n{read_text(brief_path, 60000)}",
        pack=pack,
        catalog=catalog,
        skeleton_block=skeleton_block,
        message_map_block=message_map_block,
        institution_research_block=institution_block,
        company_profile_block=company_block,
        master_design_block=master_design_block,
        knowledge_block=knowledge_block,
    )
    out = run / "storyline_prompt" / "storyline_prompt.md"
    write_text(out, _anonymize_bundle_text(run, prompt))
    return out


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _render_run_dir(raw: str | None, *, must_exist: bool) -> Path:
    if raw is None:
        if must_exist:
            raise PipelineInputError("render requires --stage6, --storyline, or an existing --run directory")
        return RUNS / now_id()

    value = Path(raw)
    if value.is_absolute():
        run = value.resolve()
    elif len(value.parts) >= 3 and tuple(part.lower() for part in value.parts[:3]) == (
        "proposal_system", "workspace", "runs"
    ):
        run = (REPO_ROOT / value).resolve()
    elif len(value.parts) >= 2 and tuple(part.lower() for part in value.parts[:2]) == ("workspace", "runs"):
        run = (ROOT / value).resolve()
    else:
        run = (RUNS / value).resolve()

    if not _inside(run, RUNS) or run == RUNS.resolve():
        raise PipelineInputError(f"render output must be a child of {RUNS}")
    if must_exist and not run.is_dir():
        raise PipelineInputError(f"run directory not found: {run}")
    return run


def _resolve_render_input(raw: str | Path, run: Path | None = None) -> Path:
    value = Path(str(raw))
    if value.is_absolute():
        path = value.resolve()
        if not path.is_file():
            raise PipelineInputError(f"input file not found: {path}")
        return path

    candidates: list[Path] = []
    if run is not None:
        candidates.append((run / value).resolve())
    candidates.extend(((REPO_ROOT / value).resolve(), (ROOT / value).resolve()))
    existing: list[Path] = []
    for candidate in candidates:
        if candidate.is_file() and candidate not in existing:
            existing.append(candidate)
    if len(existing) > 1:
        choices = ", ".join(str(path) for path in existing)
        raise PipelineInputError(f"ambiguous relative input '{raw}': {choices}")
    if not existing:
        checked = ", ".join(str(path) for path in candidates)
        raise PipelineInputError(f"input file not found: {raw} (checked: {checked})")
    return existing[0]


def _discover_run_json(run: Path, kind: str) -> Path | None:
    matches: list[Path] = []
    for path in sorted(run.rglob("*.json")):
        name = path.name.lower()
        if kind in {"stage6", "stage7", "stage8"}:
            matched = re.fullmatch(rf"{kind}(?:[_-].*)?\.json", name) is not None
        else:
            matched = name == "storyline.json" or name.endswith("_storyline.json")
        if matched:
            matches.append(path.resolve())
    if len(matches) > 1:
        choices = ", ".join(display_path(path) for path in matches)
        raise PipelineInputError(f"multiple {kind} inputs in run directory; pass --{kind} explicitly: {choices}")
    return matches[0] if matches else None


def _read_json_input(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PipelineInputError(f"cannot read {label}: {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise PipelineInputError(f"invalid JSON for {label}: {path}: {exc}") from exc


def _app_modules():
    for path in (str(REPO_ROOT), str(APP_ROOT)):
        if path not in sys.path:
            sys.path.insert(0, path)
    import adapt_storyline
    import bind
    import ingest
    import slide_model
    from render.dispatch import add_specs
    from render.htmlgen import render_html

    return adapt_storyline, bind, ingest, slide_model, add_specs, render_html


def _validate_stage_documents(stage_docs: dict[str, dict], slide_model_module) -> None:
    violations: list[str] = []
    for stage, document in stage_docs.items():
        errors = slide_model_module.validate(document, f"stage{stage}")
        violations.extend(f"stage{stage}: {error}" for error in errors)
    if violations:
        preview = "\n".join(f"  - {item}" for item in violations[:20])
        raise PipelineInputError(f"stage schema gate failed ({len(violations)} violation(s)):\n{preview}")


_ANON_MAP_NAME = "anonymization_map.json"


def _anon_hook_module():
    """anonymize_hook은 W31 E2에서 Reuse 격리됨(<개발 원본 전용 경로>).

    secure 모드 + anonymization config enabled일 때만 호출되는 경로다(direct 모드·
    disabled는 이 함수 자체가 안 불린다) — 이 에러는 실제로 secure+익명화를 켠
    사람에게만 표면화된다.
    """
    raise PipelineInputError(
        "secure 모드 익명화 훅(anonymize_hook)이 W31에서 Reuse 격리됨 — "
        "<개발 원본 전용 경로> 참조 (초보자용 강의 자원, 여정 밖 판정). "
        "anonymization.config.json의 enabled를 false로 끄거나, 격리된 모듈을 복사해 "
        "app/anonymize_hook.py로 되돌려라."
    )


def _run_mode(run: Path) -> str | None:
    try:
        return pipeline_state.load(run).get("mode")
    except Exception:  # pragma: no cover - 상태 조회 실패는 비활성으로 취급
        return None


def _anonymization_config(path: Path | None = None) -> dict:
    target = path or ANONYMIZATION_CONFIG
    if not target.is_file():
        # W31 E2: anonymization.config.json(기본값 enabled=false)이
        # <개발 원본 전용 경로> 이동됨 — 기본 경로 부재는 "비활성"의 기존
        # 기본값과 바이트 동일하게 취급한다(direct 모드·미설정 경로 크래시 방지). 사용자가
        # --anonymize-config로 다른(기본이 아닌) 경로를 명시했는데 그게 없으면 기존처럼 표면화.
        if target == ANONYMIZATION_CONFIG:
            return {"enabled": False}
        raise PipelineInputError(
            f"anonymization config를 찾을 수 없다: {target} — "
            "secure 익명화(anonymize_hook)는 W31에서 Reuse 격리됨(<개발 원본 전용 경로>)."
        )
    config = _read_json_input(target, "anonymization config")
    if not isinstance(config, dict) or not isinstance(config.get("enabled", False), bool):
        raise PipelineInputError("anonymization config must be an object with boolean 'enabled'")
    return config


def _anonymization_active(run: Path, config: dict | None = None) -> bool:
    """W-anon: secure 모드 + enabled일 때만 실제 훅을 호출한다.

    direct 모드·enabled=false는 바이트 동일 경로(훅 호출 자체가 없다).
    """
    cfg = config if config is not None else _anonymization_config()
    return bool(cfg.get("enabled", False)) and _run_mode(run) == "secure"


def _restore_collected_file(run: Path, path: Path) -> None:
    """secure+enabled일 때 run 안의 수거물 파일을 원문으로 in-place 복원한다.

    run 밖을 가리키는 명시적 입력(예: `--storyline`/`--overrides`로 다른 위치를 지정)은
    건드리지 않는다 — 복원 대상은 이 run의 왕복으로 생겨난 수거물뿐이다.
    """
    if not path.is_file() or not _anonymization_active(run) or not _inside(path, run):
        return
    mapping = _load_anon_map(run)
    if not mapping:
        return
    raw = path.read_text(encoding="utf-8", errors="replace")
    restored = _anon_hook_module().restore_text(raw, mapping)
    if restored != raw:
        write_text(path, restored)


def _load_anon_map(run: Path) -> dict[str, str]:
    p = run / _ANON_MAP_NAME
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_anon_map(run: Path, mapping: dict[str, str]) -> None:
    write_text(run / _ANON_MAP_NAME, json.dumps(mapping, ensure_ascii=False, indent=2))


def _glossary_terms() -> frozenset[str]:
    """N7-2 용어사전(tools/proper_noun_glossary.txt) 재사용 — 파서 중복 금지.

    프롬프트 산문에는 deck의 `발주처`류 키가 없어 패턴만으로는 못 잡는 고유명사가
    있다(예: 기관명이 조직명 접미사 정규식과 안 맞는 경우) — 이 사전이 그 표면을 보강한다.
    """
    tools_path = REPO_ROOT / "tools" / "proper_noun_sweep.py"
    if not tools_path.is_file():
        raise PipelineInputError(
            "secure 모드 고유명사 용어사전(proper_noun_sweep)이 W31에서 Reuse 격리됨 — "
            "<개발 원본 전용 경로> 참조 (초보자용 강의 자원, 여정 밖 판정). "
            "anonymization.config.json의 enabled를 false로 끄거나, 격리된 모듈을 복사해 "
            "tools/proper_noun_sweep.py로 되돌려라."
        )
    if str(REPO_ROOT / "tools") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "tools"))
    import proper_noun_sweep  # type: ignore
    return frozenset(proper_noun_sweep.load_glossary())


def _anonymize_bundle_text(run: Path, text: str) -> str:
    """secure+enabled일 때만 외부 LLM행 번들 텍스트를 익명화하고 매핑을 run에 누적 저장한다."""
    if not _anonymization_active(run):
        return text
    hook = _anon_hook_module()
    mapping = _load_anon_map(run)
    anon_text, updated = hook.anonymize_text(text, mapping, extra_terms=_glossary_terms())
    _save_anon_map(run, updated)
    return anon_text


def _load_anonymization_status(raw: str | None, run: Path) -> dict:
    path = _resolve_render_input(raw, run) if raw else ANONYMIZATION_CONFIG
    config = _anonymization_config(path)
    active = _anonymization_active(run, config)
    return {
        "config": display_path(path),
        "enabled": config.get("enabled", False),
        "mode": _run_mode(run),
        "hook_point": config.get(
            "hook_point",
            "secure_mode_llm_roundtrip (storyline_bundle/stage9_bundle/deck_review_bundle → anonymize_text; "
            "render/stage9_apply/deck_review → restore_text)",
        ),
        "implementation": config.get("implementation", "wired"),
        "applied": active,
    }


def _storyline_report(deck: dict, bind_report: dict, stage_docs: dict[str, dict], slide_model_module) -> dict:
    cross_docs = {"storyline": deck}
    cross_docs.update(stage_docs)
    return {
        "slides": len(deck.get("slides") or []),
        "schema_errors": slide_model_module.validate(deck, "slide_model"),
        "cross_validate": slide_model_module.cross_validate(cross_docs),
        "review_needed_total": sum(len(slide.get("review_needed") or []) for slide in deck.get("slides", [])),
        "open_questions_total": sum(len(slide.get("open_questions") or []) for slide in deck.get("slides", [])),
        "no_template": [
            slide["slide_id"] for slide in deck.get("slides", []) if not slide.get("template_id")
        ],
        "fields_bound": bind_report["bound"],
        "fields_missing": bind_report["flagged"],
        # W7-C1: 자동배정 폴백은 조용히 일어나면 안 된다 — 관측에 남기고 stderr로도 알린다.
        "template_fallback": bind_report.get("template_fallback") or [],
    }


def _warn_template_fallback(bind_report: dict) -> None:
    for item in bind_report.get("template_fallback") or []:
        print(f"[WARN] {item['warning']}", file=sys.stderr)


def render_run(args: argparse.Namespace) -> int:
    if args.stage6 and args.storyline:
        raise PipelineInputError("--stage6 and --storyline are mutually exclusive base inputs")
    if not (args.stage6 or args.storyline or args.run_dir):
        raise PipelineInputError("provide --stage6, --storyline, or --run")

    explicit_base = bool(args.stage6 or args.storyline)
    run = _render_run_dir(args.run_dir, must_exist=not explicit_base)

    stage6_path = _resolve_render_input(args.stage6, run) if args.stage6 else None
    storyline_path = _resolve_render_input(args.storyline, run) if args.storyline else None
    if not stage6_path and not storyline_path:
        stage6_path = _discover_run_json(run, "stage6")
        if stage6_path is None:
            storyline_path = _discover_run_json(run, "storyline")
    if stage6_path is None and storyline_path is None:
        raise PipelineInputError(
            f"no stage6 or *_storyline.json base input found under run directory: {run}"
        )

    stage7_path = (
        _resolve_render_input(args.stage7, run)
        if args.stage7
        else (_discover_run_json(run, "stage7") if run.is_dir() else None)
    )
    stage8_path = (
        _resolve_render_input(args.stage8, run)
        if args.stage8
        else (_discover_run_json(run, "stage8") if run.is_dir() else None)
    )
    labelled_paths = {
        label: path
        for label, path in (
            ("stage6", stage6_path),
            ("storyline", storyline_path),
            ("stage7", stage7_path),
            ("stage8", stage8_path),
        )
        if path is not None
    }
    resolved_values = list(labelled_paths.values())
    if len(set(resolved_values)) != len(resolved_values):
        raise PipelineInputError("the same JSON file cannot be used for multiple stage inputs")

    pack_dir = _pack_dir(args.pack)
    if not (pack_dir / "tokens.json").is_file() or not (pack_dir / "templates.json").is_file():
        raise PipelineInputError(f"pack is incomplete or missing: {pack_dir}")

    adapt_storyline, bind, ingest, sm, add_specs, render_html = _app_modules()
    s7 = _read_json_input(stage7_path, "stage7") if stage7_path else None
    s8 = _read_json_input(stage8_path, "stage8") if stage8_path else None
    stage_docs = {
        stage: document
        for stage, document in (("7", s7), ("8", s8))
        if document is not None
    }
    _validate_stage_documents(stage_docs, sm)

    if stage6_path is not None:
        s6 = _read_json_input(stage6_path, "stage6")
        if not isinstance(s6, dict):
            raise PipelineInputError("stage6 JSON root must be an object")
        _validate_stage_documents({"6": s6}, sm)
        project = args.project or ((s6.get("meta") or {}).get("project")) or "제안 검토덱"
        deck, report = ingest.merge(project, args.pack, s6, s7, s8)
        input_mode = "stage6"
    else:
        _restore_collected_file(run, storyline_path)
        storyline_doc = _read_json_input(storyline_path, "storyline")
        source_meta = storyline_doc.get("meta") if isinstance(storyline_doc, dict) else {}
        project = args.project or (source_meta.get("project") if isinstance(source_meta, dict) else None) or ""
        try:
            deck = adapt_storyline.adapt_storyline(
                storyline_doc,
                project=project,
                pack=args.pack,
                source_file=display_path(storyline_path),
            )
        except adapt_storyline.StorylineAdapterError as exc:
            raise PipelineInputError(f"storyline adapter failed: {exc}") from exc
        if s7:
            ingest.patch_stage7({slide["slide_id"]: slide for slide in deck["slides"]}, s7)
        if s8:
            ingest.patch_stage8({slide["slide_id"]: slide for slide in deck["slides"]}, s8)
        # W7-C1: enrich가 돌 예정이면 폴백을 미룬다 — 분석카드가 time_units/milestones를 실제로
        # 채울 수 있으므로, 그 기회를 주기 전에 템플릿을 놓아주면 근거 있는 간트를 잃는다.
        _will_enrich = bool(getattr(args, "analysis", None) or getattr(args, "rfp", None))
        bind_report = bind.bind_deck(
            deck, ingest._load_templates(args.pack), allow_fallback=not _will_enrich
        )
        _warn_template_fallback(bind_report)
        report = _storyline_report(deck, bind_report, stage_docs, sm)
        input_mode = "storyline"

    analysis_path = getattr(args, "analysis", None)
    rfp_path = getattr(args, "rfp", None)
    # W31 리허설 마찰6: run에 회사가 선택돼 있으면 enrich의 보수적 채움 소스로 profile을 준다
    # (직접 바인딩 가능한 필드만 — 근거 없는 필드는 지금처럼 비운다). 미선택 run은 company_profile=None
    # 이라 이 분기가 트리거하는 조건에도 안 걸리면 기존 동작과 완전히 동일(회귀 없음).
    _company_sel = company.load_selection(run)
    _company_profile = company.load(_company_sel["company_id"]) if _company_sel else None
    if analysis_path or rfp_path or _company_profile is not None:
        try:
            import enrich as _enrich
            _analysis = json.loads(Path(analysis_path).read_text(encoding="utf-8")) if analysis_path else {}
            _rfp_text = Path(rfp_path).read_text(encoding="utf-8") if rfp_path else ""
            deck = _enrich.enrich_deck(deck, _analysis, _rfp_text, company_profile=_company_profile)
        except Exception as exc:
            print(f"[WARN] enrich skipped: {exc}", file=sys.stderr)
        # W7-C1: 이제 enrich에게 기회를 줬으니 폴백을 판정한다(여전히 전 필드가 비었으면 generic).
        if input_mode == "storyline":
            _fallbacks = bind.apply_template_fallback(deck, ingest._load_templates(args.pack))
            if _fallbacks:
                report["template_fallback"] = _fallbacks
                _warn_template_fallback({"template_fallback": _fallbacks})
        # gating_report의 fields_missing/bound는 enrich 이전 스냅샷이라 stale → enrich 반영본으로 재계산.
        # (deepcopy에 재바인딩해 실 deck는 불변; flagged/bound 카운트만 사용)
        try:
            from copy import deepcopy
            _rebind = bind.bind_deck(deepcopy(deck), ingest._load_templates(args.pack))
            report["fields_bound"] = _rebind["bound"]
            report["fields_missing"] = _rebind["flagged"]
            report["fields_missing_note"] = "enrich 반영 후 재계산(stale 방지)"
        except Exception as exc:
            print(f"[WARN] fields_missing 재계산 실패: {exc}", file=sys.stderr)

    # W5: 검토요망 해소(§3.0 체크포인트 ②). bind/enrich가 태그를 다 붙인 **뒤**, 배지·리포트
    # 계산 **직전**에 적용한다. 여기 두는 이유: deck.json은 매 렌더마다 storyline에서 재구성되므로,
    # 해소가 렌더 밖에 있으면 다음 렌더에서 태그가 조용히 되살아난다(멱등성 = 태그 재생성 → 재해소).
    # 사람의 명시 결정이 없는 태그는 이 함수가 절대 건드리지 않는다(창작금지의 대칭 불변식).
    resolutions = review_resolve.load(run)
    if resolutions is not None:
        # binders 주입: body에 기입한 사실을 bind 파생 필드에 재투영(안 하면 deck.json에만 남고
        # deck.html에는 안 나온다 — 렌더러는 body가 아니라 fields를 읽는 템플릿이 많다).
        res_report = review_resolve.apply(deck, resolutions, binders=bind.BINDERS)
        report["review_resolution"] = review_resolve.summarize(
            res_report, review_resolve.resolutions_path(run)
        )
        if res_report["tags_removed"]:
            # 해소로 태그가 빠졌으므로 이전 계산값(ingest.merge/_storyline_report)은 stale.
            try:
                from copy import deepcopy
                _rebind = bind.bind_deck(deepcopy(deck), ingest._load_templates(args.pack))
                report["fields_bound"] = _rebind["bound"]
                report["fields_missing"] = _rebind["flagged"]
            except Exception as exc:
                print(f"[WARN] 해소 후 fields_missing 재계산 실패: {exc}", file=sys.stderr)
        print(f"[RESOLVE] {review_resolve.summary_line(res_report)}")
        for problem in res_report["problems"]:
            print(f"  [주의] 해소지 무효 항목: {problem}", file=sys.stderr)
        for note in res_report["notes"]:
            print(f"  [주의] {note}", file=sys.stderr)
    # 해소 여부와 무관하게 실측 재계산(자기보고 금지 — 리스트를 다시 센다).
    report["review_needed_total"] = sum(
        len(slide.get("review_needed") or []) for slide in deck.get("slides", [])
    )
    # W9 관측(안전장치 ④): 해소 후에도 남은 예시 데이터 슬라이드 실측(fact_supplied면 마크가 제거됨).
    # deck의 slide.example을 다시 센다 — gating_report에 기록해 ship 경고·대시보드가 소비한다.
    _example_ids = [s.get("slide_id") for s in deck.get("slides", []) if s.get("example")]
    report["example_slides"] = _example_ids
    report["example_slides_total"] = len(_example_ids)

    # W31 리허설 마찰6: 회사가 선택된 run에서 제안업체·사업관리·인력 계열 장이 여전히
    # 검토요망으로 남으면, 그 회사의 gaps.md에 결정론 append(중복 방지) — 다음 인테이크 때
    # 뭘 구해야 하는지 축적한다. 회사 미선택이면 완전히 무동작(회귀 없음).
    if _company_sel and _company_sel.get("company_id"):
        _gap_entries = _collect_company_gap_entries(deck, run.name)
        if _gap_entries:
            _added = company.append_gaps(_company_sel["company_id"], _gap_entries)
            if _added:
                print(f"[COMPANY] gaps.md 갱신: {_added}건 신규 -> "
                      f"{display_path(company.gaps_path(_company_sel['company_id']))}")

    deck["meta"]["source_files"] = [display_path(path) for path in labelled_paths.values()]
    report["schema_errors"] = sm.validate(deck, "slide_model")
    report["inputs"] = {label: display_path(path) for label, path in labelled_paths.items()}
    report["input_mode"] = input_mode
    report["pack"] = args.pack
    report["anonymization"] = _load_anonymization_status(args.anonymize_config, run)
    # 결정 8(§6): gating_report는 render마다 통째로 재작성되므로(state.json이 정본), 매번
    # state.json의 selection을 다시 옮겨 적는다 — 로직 이중화 없이 단일 소재지에서 파생.
    report["selection"] = pipeline_state.load(run).get("selection")
    # W15(결정 9①⑤): message_map이 있으면 실측 블록을 옮긴다(자기보고 아님 — map을 다시 세서
    # axes/slots/governing_ok 계산). 구공정·레거시 run엔 map이 없어 생략(소급 backfill 금지).
    _mm_doc = message_map.load(run)
    if _mm_doc is not None:
        report["message_map"] = message_map.gating_block(_mm_doc)

    # P3-1 리뷰 배지: 슬라이드별 발산추천/충실/밋밋 판정(순수 결정론·LLM 0토큰).
    try:
        import review_badges
        report["review_badges"] = review_badges.compute_review_badges(deck)
    except Exception as exc:
        print(f"[WARN] review_badges skipped: {exc}", file=sys.stderr)

    run.mkdir(parents=True, exist_ok=True)
    deck_path = run / "deck.json"
    gate_path = run / "gating_report.json"
    write_text(deck_path, json.dumps(deck, ensure_ascii=False, indent=2))
    if report["schema_errors"] or report["cross_validate"]:
        write_text(gate_path, json.dumps(report, ensure_ascii=False, indent=2))
        raise PipelineInputError(
            f"canonical gate failed; inspect {gate_path} "
            f"(schema={len(report['schema_errors'])}, cross={len(report['cross_validate'])})"
        )

    html_path = run / "deck.html"
    _skins = [s.strip() for s in (getattr(args, "skins", None) or "").split(",") if s.strip()] or None
    # render_run은 overrides를 렌더 호출에 전달하지 않는다(stage9 --apply만 전달·gating_report 미갱신) →
    # 이 시점의 html/pptx는 항상 overrides=false·image_slots=0. add_specs는 overrides/image_slots
    # 인자 자체가 없어 pptx는 이 축을 원천적으로 지원하지 않는다(하드코딩이 아니라 시그니처가 근거).
    html_report = render_html(deck, args.pack, html_path, skins=_skins)
    # W31 리허설 마찰3: 정본(deck.html) 생성 직후 문서형 파생 뷰(deck.doc.html)도 함께 생성 —
    # 연속 스크롤 문서로 재조판(검토·회의 정독용, 제출물 아님). render_html 출력엔 관여하지 않는다.
    _write_doc_view(deck, run)
    pptx_report = add_specs(
        deck, args.pack, run / "deck.pptx",
        skins=_skins, mode=getattr(args, "pptx_mode", "native"),
    ) if args.pptx else None
    manual_layer_exists = (run / "manual_layer.html").is_file()
    templates_by_id = ingest._load_templates(args.pack)
    report["required_fields_declared"] = sum(
        1 for t in templates_by_id.values() if t.get("required_fields")
    )
    report["applied_axes"] = {
        "html": {
            "pack": args.pack,
            "skins": list(_skins) if _skins else [],
            "overrides": False,
            "image_slots": 0,
            "manual_layer": manual_layer_exists,
        },
        "pptx": ({
            "pack": args.pack,
            "skins": list(_skins) if _skins else [],
            "overrides": False,
            "image_slots": 0,
            "manual_layer": False,
            "mode": pptx_report.get("mode"),
        } if pptx_report is not None else None),
    }
    report["render"] = {
        "html": html_report,
        "pptx": pptx_report,
    }
    # W3b(N3-5): 결정론 디자인 게이트 — 방금 쓴 deck.html 마크업 실측(LLM 0토큰·차단 없음).
    report["design_checks"] = _compute_design_checks(html_path)
    # W16(결정 9⑤): 분량 리듬 실측 — 덱 어절 분포(min/중앙/max/동적범위)·밴드 위반(표면화·차단 없음).
    _rhythm = _compute_length_rhythm(deck)
    if _rhythm is not None:
        report["length_rhythm"] = _rhythm
    write_text(gate_path, json.dumps(report, ensure_ascii=False, indent=2))
    # W10: 스켈레톤 역제안 렌더는 **render 단계로 기록하지 않는다** — 전 장표가 예시 더미이고
    # 아직 실 스토리라인이 없기 때문. 별도 stage `skeleton` + manifest_skeleton.json으로 남겨
    # 상태머신이 "render 미완(=역제안 확정 대기)"을 유지하게 한다(그래야 확정 후 채움 핸드오프로 간다).
    skeleton_mode = bool(getattr(args, "skeleton", False))
    manifest = {
        "run_dir": str(run),
        "deck": str(deck_path),
        "html": str(html_path),
        "pptx": str(run / "deck.pptx") if args.pptx else None,
        "gating_report": str(gate_path),
        "input_mode": input_mode,
        "pack": args.pack,
    }
    manifest_name = "manifest_skeleton.json" if skeleton_mode else "manifest_render.json"
    write_text(run / manifest_name, json.dumps(manifest, ensure_ascii=False, indent=2))
    if skeleton_mode:
        _record_state(
            run, "skeleton",
            artifacts={k: v for k, v in manifest.items() if k in ("deck", "html", "gating_report")},
            pack=args.pack,
            scenario=getattr(args, "scenario", None),
            slides=len(deck.get("slides", [])),
            example_slides=report.get("example_slides_total"),
        )
    else:
        _record_state(
            run, "render",
            artifacts={k: v for k, v in manifest.items() if k in ("deck", "html", "pptx", "gating_report")},
            pack=args.pack,
            skins=list(_skins) if _skins else [],
            input_mode=input_mode,
            # 이 시점의 deck.html은 항상 overrides 미반영(위 주석 참조) — stage9 재적용 판단의 근거.
            overrides_applied=False,
        )
    if args.json:
        print(json.dumps({"manifest": manifest, "gating": report}, ensure_ascii=False, indent=2))
    else:
        print(f"[DECK] {deck_path}")
        print(f"[HTML] {html_path} warnings={len(html_report['warnings'])}")
        if pptx_report:
            print(f"[PPTX] {pptx_report['out']} warnings={len(pptx_report['warnings'])}")
            # 폴백 슬라이드(적합 템플릿 없어 밋밋해진 것)를 사용자에게 표면화
            fb = [w for w in pptx_report["warnings"] if "폴백" in w or "적합 네이티브 렌더러 없음" in w]
            for w in fb:
                print(f"  [PPTX-폴백] {w}")
        print(f"[GATE] {gate_path}")
    return 0


# ---------------------------------------------------------------------------
# stage9 — 디자인 디렉터 패스(렌더 후·비전). 계약: CONTEXT/DESIGN_DIRECTOR_PASS.md
# ---------------------------------------------------------------------------

def _stage9_targets(deck: dict, slides_arg: str | None) -> tuple[list[str], str]:
    """대상 슬라이드 결정 — 모드 A(명시 --slides) 우선, 없으면 모드 B(review_badges '밋밋')."""
    if slides_arg:
        return [x.strip() for x in slides_arg.split(",") if x.strip()], "explicit"
    try:
        if str(APP_ROOT) not in sys.path:
            sys.path.insert(0, str(APP_ROOT))
        import review_badges  # type: ignore
        rb = review_badges.compute_review_badges(deck)
        bland = [str(b["slide_id"]) for b in rb.get("badges", []) if b.get("verdict") == "밋밋"]
        return bland, "auto(밋밋)"
    except Exception as exc:  # pragma: no cover - triage best-effort
        return [], f"auto-unavailable({exc})"


def build_design_brief(run: Path, args: argparse.Namespace) -> tuple[Path, dict, bool]:
    """W3a: 의사결정 게이트 산출물 `design_brief.json`(결정론 기본값). 이미 있으면 보존(사람 편집본).

    근거 = 렌더된 deck.json + review_badges(gating_report에 있으면 재사용). LLM 0토큰.
    """
    deck_path = run / "deck.json"
    if not deck_path.exists():
        raise PipelineInputError(f"deck.json 없음: {deck_path} (먼저 render 실행)")
    existing = design_brief.load(run)
    if existing is not None:
        return design_brief.brief_path(run), existing, False

    if str(APP_ROOT) not in sys.path:  # review_badges 폴백 계산 경로
        sys.path.insert(0, str(APP_ROOT))
    deck = json.loads(deck_path.read_text(encoding="utf-8"))
    gate_path = run / "gating_report.json"
    gating = json.loads(gate_path.read_text(encoding="utf-8")) if gate_path.exists() else None
    guides = resolve_design_guides(load_config(), getattr(args, "design_guide", None))
    # W31 마찰14: skins_dir을 넘겨 institution_research.json의 등록 스킨을 skin.value 초안으로 조회.
    brief = design_brief.build_default(run, deck, gating=gating, guides=guides, skins_dir=SKINS_DIR)
    return design_brief.save(run, brief), brief, True


_SLOT_RE = re.compile(r'class="dov-slot[ "]')
_SLOT_PH_RE = re.compile(r'class="dov-slot dov-slot--ph')


def _measure_slots(html: str) -> tuple[int, int]:
    """렌더된 HTML에서 슬롯 수를 **실측**(자기보고 불신). → (전체, placeholder)."""
    return len(_SLOT_RE.findall(html)), len(_SLOT_PH_RE.findall(html))


def _slide_word_count(slide: dict) -> int:
    """슬라이드 본문 어절 수(공백 분해). key_message + body + fields의 문자열 값."""
    parts: list[str] = []
    km = slide.get("key_message")
    if isinstance(km, str):
        parts.append(km)
    for b in (slide.get("body") or []):
        if isinstance(b, str):
            parts.append(b)

    def _walk(v: Any) -> None:
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, dict):
            for x in v.values():
                _walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                _walk(x)

    _walk(slide.get("fields") or {})
    return sum(len(p.split()) for p in parts if p and p.strip())


def _compute_length_rhythm(deck: dict) -> dict | None:
    """W16(결정 9⑤): 덱의 실제 분량 분포를 실측한다(자기보고 아님 — 덱을 다시 센다).

    각 슬라이드 어절 수 → min/중앙/max/동적범위. 슬라이드가 length_band를 선언했으면(스켈레톤·
    시나리오) 밴드 위반을 함께 기록한다. **차단하지 않는다** — 표면화 문법(결정 7~8). v1 P4.6
    확정: 동적 범위 ≥3배(스토리 얇게/근거 두껍게). 균질 분포는 AI티의 내용 측 원인.
    """
    slides = deck.get("slides") or []
    counts: list[int] = []
    violations: list[dict] = []
    for s in slides:
        if not isinstance(s, dict):
            continue
        wc = _slide_word_count(s)
        counts.append(wc)
        band = s.get("length_band")
        if isinstance(band, list) and len(band) == 2:
            lo, hi = band
            if wc < lo or wc > hi:
                violations.append({
                    "slide_id": s.get("slide_id"),
                    "words": wc, "band": [lo, hi],
                    "kind": "under" if wc < lo else "over",
                })
    if not counts:
        return None
    ordered = sorted(counts)
    mid = len(ordered) // 2
    median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    lo_c = min(counts)
    hi_c = max(counts)
    dyn = round(hi_c / lo_c, 2) if lo_c > 0 else None
    return {
        "slides": len(counts),
        "min": lo_c,
        "median": median,
        "max": hi_c,
        "dynamic_range": dyn,           # max/min (v1 목표 ≥3.0)
        "target_min_dynamic_range": 3.0,
        "band_violations": violations,  # 선언 밴드 위반(경고 1급 · 차단 없음)
        "measured_from": "deck.json slides (어절=공백분해)",
    }


def _compute_design_checks(html_path: Path) -> dict | None:
    """W3b: deck.html → gating_report.design_checks(결정론 게이트). 실패해도 렌더를 막지 않는다."""
    try:
        if str(APP_ROOT / "render") not in sys.path:
            sys.path.insert(0, str(APP_ROOT / "render"))
        import design_checks as dc_mod  # type: ignore
        return dc_mod.compute_design_checks(html_path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - 게이트는 부가 관측이지 차단자가 아니다
        print(f"[WARN] design_checks skipped: {exc}", file=sys.stderr)
        return None


def _browser_design_checks(html_path: Path) -> dict | None:
    """W6-A1: 정적 design_checks + **브라우저 실측 계층**.

    비용(브라우저 기동) 때문에 render 매회가 아니라 **stage9 --apply / 평가 직전**에만 부른다
    (그 시점의 deck.html이 사람이 보게 될 병합본이다). playwright가 없으면 layout_probe가
    `unmeasured`를 돌려준다 — 가짜 pass 금지.
    """
    checks = _compute_design_checks(html_path)
    if checks is None:
        return None
    try:
        if str(APP_ROOT / "render") not in sys.path:
            sys.path.insert(0, str(APP_ROOT / "render"))
        import design_checks as dc_mod  # type: ignore
        import layout_probe  # type: ignore
        return dc_mod.attach_browser_layer(checks, layout_probe.probe_html(html_path))
    except Exception as exc:  # pragma: no cover - 브라우저 계층도 차단자가 아니다
        print(f"[WARN] browser layout probe skipped: {exc}", file=sys.stderr)
        return checks


def _update_applied_axes(run: Path, *, overrides_path: Path, html_path: Path,
                          render_rep: dict | None = None,
                          skins: "list | None" = None) -> dict | None:
    """W1 관측 갭 해소: stage9 --apply가 gating_report.applied_axes.html을 실측 갱신한다.

    - 값의 출처는 **병합된 deck.html 자체**(슬롯 수를 세어서)와 override 파일 존재 — 자기보고 아님.
    - render가 다시 돌면 gating_report는 통째로 재작성되어 overrides=false로 돌아간다.
      그래서 상태의 정본은 여전히 pipeline_state.json이다(pipeline_state D2 경고와 정합).
    - 기존 소비 키(pack/skins/overrides/image_slots/manual_layer)의 이름·타입은 보존한다.
    - B2: `report["render"]["html"]`(out/slides/warnings/bytes)은 render 시점 값 그대로 낡는다
      (override 병합으로 파일이 커져도 bytes가 안 바뀜) — render_rep이 있으면 여기서도 갱신한다.
    """
    gate_path = run / "gating_report.json"
    if not gate_path.exists():
        print(f"[WARN] gating_report.json 없음 — applied_axes 갱신 생략: {gate_path}", file=sys.stderr)
        return None
    report = json.loads(gate_path.read_text(encoding="utf-8"))
    axes = report.get("applied_axes")
    if not isinstance(axes, dict):
        axes = {"html": None, "pptx": None}
    html_axis = axes.get("html")
    if not isinstance(html_axis, dict):
        # 레거시 gating_report(S6-1 이전) — 렌더 축을 모른다. 지어내지 않고 state 기록에서만 가져온다.
        rendered = (pipeline_state.load(run).get("stages") or {}).get("render") or {}
        html_axis = {
            "pack": rendered.get("pack"),
            "skins": rendered.get("skins") or [],
            "manual_layer": (run / "manual_layer.html").is_file(),
            "axes_source": "stage9 --apply가 신설(레거시 gating_report에는 applied_axes가 없었다)",
        }
    merged_html = html_path.read_text(encoding="utf-8")
    total, placeholder = _measure_slots(merged_html)
    html_axis.update({
        "overrides": True,
        "overrides_path": display_path(overrides_path),
        # W22: 디자인 적용이 실제로 넘긴 스킨 캐스케이드(미전달 시 기존 값 보존).
        "skins": list(skins) if skins else html_axis.get("skins") or [],
        "image_slots": total,
        "image_slots_placeholder": placeholder,
        "manual_layer": (run / "manual_layer.html").is_file(),
        "measured_from": "deck.html (슬롯 마크업 실측)",
        "updated_by": "stage9 --apply",
        "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
    })
    axes["html"] = html_axis
    report["applied_axes"] = axes
    if render_rep is not None:
        render_block = report.get("render") or {}
        render_block["html"] = render_rep
        report["render"] = render_block
    # design_checks 도 병합본 기준으로 다시 잰다 — 안 그러면 render 시점(슬롯 0)의 낡은 수치가 남는다.
    # 이 시점(stage9 --apply)이 브라우저 실측을 붙이는 자리다: override가 병합된 최종 마크업.
    checks = _browser_design_checks(html_path)
    if checks is not None:
        checks["updated_by"] = "stage9 --apply"
        report["design_checks"] = checks
    # W27 D6·D7: 이미지 수급 표면화 — override 슬롯 전수 카운트(생성/웹수급/실자산/placeholder).
    try:
        if str(APP_ROOT / "render") not in sys.path:
            sys.path.insert(0, str(APP_ROOT / "render"))
        import image_slots as img_mod  # type: ignore
        ov_data = json.loads(overrides_path.read_text(encoding="utf-8")) if overrides_path.exists() else {}
        report["image_provenance"] = img_mod.compute_image_provenance(ov_data, run_dir=run)
    except Exception as exc:  # pragma: no cover - 부가 관측, 차단자 아님
        print(f"[WARN] image_provenance skipped: {exc}", file=sys.stderr)
    write_text(gate_path, json.dumps(report, ensure_ascii=False, indent=2))
    return html_axis


def _repair_targets(browser: "dict | None") -> list[dict]:
    """W12: browser 실측 블록 → 수리 대상(layout_probe.repair_targets 재사용, 단일 소재지)."""
    if not browser:
        return []
    if str(APP_ROOT / "render") not in sys.path:
        sys.path.insert(0, str(APP_ROOT / "render"))
    try:
        import layout_probe  # type: ignore
    except Exception:
        return []
    return layout_probe.repair_targets(browser)


def _print_image_provenance(run: Path, report: dict) -> None:
    """W27 D6·D7: image_provenance 요약 1줄 + 이미지 리듬 경고(계획 대비 실채움 0장)."""
    prov = report.get("image_provenance")
    if prov:
        print(f"[GATE] image_provenance: generated={prov['generated']} "
              f"generated_evidence={prov['generated_evidence']}"
              f"(미해소={prov['generated_evidence_unresolved']}) "
              f"web_sample={prov['web_sample']}(출처기록={prov['web_sample_sourced']}) "
              f"real_asset={prov['real_asset']} placeholder={prov['placeholder']}")
    if not design_brief.exists(run):
        return
    brief = design_brief.load(run) or {}
    planned = len((brief.get("image_slots_plan") or {}).get("slots") or [])
    if not planned:
        return
    filled = (prov or {}).get("real_asset", 0) + (prov or {}).get("generated", 0)
    if not filled:
        print(f"[GATE] 경고: design_brief가 이미지 슬롯 {planned}개를 계획했으나 실제 채워진 "
              "이미지가 0장이다 - image_slots_plan 대비 미이행(stage9 --fill-images 또는 실자산 지정 필요).")


def _print_design_checks(run: Path) -> None:
    """gating_report.design_checks 요약 1줄(관측 노출 — 판정은 사람 몫)."""
    gate_path = run / "gating_report.json"
    if not gate_path.exists():
        return
    report = json.loads(gate_path.read_text(encoding="utf-8"))
    dc = report.get("design_checks")
    if not dc:
        return
    s = dc["summary"]
    im = s["image_slots"]
    print(f"[GATE] design_checks: status={dc['status']} overflow_risk={s['overflow_risk']} "
          f"density(over/under)={s['density_over']}/{s['density_under']} "
          f"bullets_over={s['bullets_over']} "
          f"slots={im['filled']}/{im['total']} (placeholder={im['placeholder']}, "
          f"fulfillment={im['fulfillment']})")
    _print_image_provenance(run, report)
    br = dc.get("browser")
    if not br:
        return
    bs = br.get("summary") or {}
    print(f"[GATE] design_checks.browser: status={br['status']} "
          f"overflow={bs.get('overflow')} occlusion={bs.get('occlusion')} "
          f"content_overlap={bs.get('content_overlap')} void={bs.get('void')}"
          + (f" — {br.get('reason')}" if br["status"] == "unmeasured" else ""))
    # W12: 실결함 계열 flag는 조용한 warn이 아니라 1급 "수리 대상"으로 끌어올린다(승격).
    targets = _repair_targets(br)
    if targets:
        tag = ", ".join(f"slide {t['slide_id']}({'/'.join(t['flags'])})" for t in targets)
        print(f"[GATE] 수리 대상 {len(targets)}건 — {tag}")
        print("        → design_overrides.json 정련 후 `stage9 --apply` 재실행으로 재실측"
              "(ship은 막지 않으나 조용히 통과하지 않는다).")
    for row in br.get("slides") or []:
        if not row["flags"]:
            continue
        detail = [f"{b['selector']}(height={b['height_px']}px,void_ratio={b['void_ratio']})"
                  for b in row.get("void_blocks") or []]
        detail += [f"{o['box']}({o['overlap_px']}px²)" for o in row.get("content_overlaps") or []]
        detail += [f"{o['target']}({o['ratio']})" for o in row.get("occlusions") or []]
        print(f"  - slide {row['slide_id']}: {', '.join(row['flags'])} "
              f"overflow={row['overflow_px']}px {' '.join(detail[:4])}")


STAGE9_SHOTS_DIR = ("assets", "slides")


def _stage9_screenshots(run: Path) -> tuple[list[Path], str | None]:
    """W6-A2: 번들에 실첨부할 슬라이드 PNG를 굽는다(`html_to_slide_pngs` 재사용 — 카메라는 하나).

    stage9 프롬프트는 "PNG를 보라"고 15회 요구하는데 코드는 눈을 주지 않았다(MANUAL §10 불일치).
    playwright가 없으면 **빈 목록 + 사유**를 돌려준다 — 번들이 그 사실을 정직하게 말한다.
    """
    html_path = run / "deck.html"
    if not html_path.exists():
        return [], f"deck.html 없음: {display_path(html_path)} (먼저 render)"
    if str(APP_ROOT / "render") not in sys.path:
        sys.path.insert(0, str(APP_ROOT / "render"))
    try:
        import rasterize  # type: ignore
    except Exception as exc:  # pragma: no cover
        return [], f"rasterize 임포트 실패: {exc}"
    if not rasterize.available():
        return [], "playwright 미설치(pip install playwright && playwright install chromium)"
    out_dir = run.joinpath(*STAGE9_SHOTS_DIR)
    try:
        return rasterize.html_to_slide_pngs(html_path, out_dir), None
    except Exception as exc:  # pragma: no cover - 브라우저 사고는 번들을 막지 않는다
        return [], f"래스터 실패: {type(exc).__name__}: {exc}"


def _stage9_screenshot_block(run: Path, shots: list[Path], reason: str | None,
                             targets: list[str]) -> str:
    """스크린샷 블록. direct=세션이 Read할 경로 / secure=사람이 첨부할 경로(외부 LLM 왕복)."""
    if not shots:
        return ("\n\n# 입력: 스크린샷 — **없음**\n"
                f"- 사유: {reason or '(미기록)'}\n"
                "- **스크린샷 없음 — 텍스트(deck.json·가이드·브리핑)만으로 판단 중이다.** "
                "픽셀 사실(겹침·오버플로·여백)은 확인되지 않았다. 비전 판단은 그 한계 안에서 하라.\n")
    secure = _run_mode(run) == "secure"
    want = set(targets)

    def _sid(p: Path) -> str:
        return p.stem.split("-")[-1].lstrip("0") or "0"

    lines = ["\n\n# 입력: 스크린샷 (deck.html 실사 래스터 — 비전 입력의 정본)\n"]
    lines.append(f"- 좌표계: {rasterize_viewport()} · 생성: `html_to_slide_pngs(deck.html)`\n")
    if secure:
        lines.append("- **secure 모드**: 아래 파일을 **사람이 대화에 첨부**해야 모델이 볼 수 있다"
                     "(경로만으로는 보이지 않는다).\n")
    else:
        lines.append("- **direct 모드**: 세션이 아래 경로를 **직접 Read**해 이미지로 보라.\n")
    for p in shots:
        mark = " ← 대상" if _sid(p) in want else ""
        lines.append(f"  - {display_path(p)}{mark}\n")
    return "".join(lines)


def rasterize_viewport() -> str:
    return "1280×720 (슬라이드 요소 캡처)"


def bundle_stage9(run: Path, args: argparse.Namespace) -> tuple[Path, list[str], str, list[Path]]:
    config = load_config()
    deck_path = run / "deck.json"
    if not deck_path.exists():
        raise PipelineInputError(f"deck.json 없음: {deck_path} (먼저 render 실행)")
    deck = json.loads(deck_path.read_text(encoding="utf-8"))
    targets, mode = _stage9_targets(deck, args.slides)
    guides = resolve_design_guides(config, getattr(args, "design_guide", None))
    shots, shots_reason = _stage9_screenshots(run)  # W6-A2: 눈 없이 비전 판단시키지 않는다

    parts = [
        prompt_header(9, "디자인 디렉터(렌더 후·비전)",
                      [str(deck_path)] + [str(p) for p in shots]),
        read_text(PROMPTS / "stage9_design_director.md"),
        f"\n\n# 대상 슬라이드 ({mode}): {', '.join(targets) or '(없음 — 전체 검토)'}\n",
        "\n# 입력: deck.json (내용 — 참조만, 변경 금지)\n",
        read_text(deck_path, 60000),
    ]

    # 입력 4원천(§2 계약 확장, W3a): run별 디자인 브리핑 — 가이드(정적 규칙층)와 달리 이 덱의 결정.
    brief = design_brief.load(run)
    if brief:
        parts.append(
            "\n\n# 입력: 디자인 브리핑 (design_brief.json — 이 run의 결정. 가이드보다 우선)\n"
            + design_brief.render_for_prompt(brief)
            + "\n\n브리핑의 리듬·슬롯 계획을 override로 구현하라. 계획과 다르게 판단했다면 그 이유를 "
              "override의 `note`에 남겨라(브리핑을 임의로 무시하지 말 것).\n"
        )
    else:
        parts.append(
            "\n\n# 입력: 디자인 브리핑 — **없음**(`go --confirm`이 생성한다). "
            "브리핑 없이 진행하므로 리듬·슬롯 계획은 디렉터 재량이다.\n"
        )

    parts.append("\n\n# 입력: 디자인 가이드(스킨 — 규칙층 SSOT. 브리핑이 id로 참조한다)\n")
    for g in guides:
        p = g["spec_text"]
        if not p.exists():
            continue
        parts.append(f"\n## [{g['id']}] {p.name}\n")
        parts.append(read_text(p, 30000))
        if g["examples"]:
            parts.append(
                f"\n(시각 예시 {len(g['examples'])}장 — 비전 입력으로 사용: "
                f"{Path(g['examples'][0]).parent})\n"
            )
    parts.append(_stage9_screenshot_block(run, shots, shots_reason, targets))
    parts.append(
        "\n\n# 렌더 산출물\n"
        f"- HTML: {run / 'deck.html'}\n"
        f"\n# 출력\n- `{run / 'design_overrides.json'}` 로 저장 → `stage9 --apply`로 검증·병합.\n"
    )
    out = run / "stage9_design" / "stage9_director_prompt.md"
    write_text(out, _anonymize_bundle_text(run, "".join(parts)))
    return out, targets, mode, shots


def _design_skins(run: Path, args: argparse.Namespace) -> "list | None":
    """[4] 디자인 적용 시 스킨 해석: --skins(CLI) > design_brief.skin.skins > state rendered.skins.

    design_brief.brand(로고/명칭 실자산)는 인라인 스킨 {"brand": ...}로 맨 뒤에 얹는다(캐스케이드 최후승).
    """
    cli_skins = getattr(args, "skins", None)
    if cli_skins:
        skins: list = [s.strip() for s in str(cli_skins).split(",") if s.strip()]
    else:
        brief = design_brief.load(run)
        brief_skins = ((brief or {}).get("skin") or {}).get("skins") or []
        if brief_skins:
            skins = list(brief_skins)
        else:
            rendered = (pipeline_state.load(run).get("stages") or {}).get("render") or {}
            skins = list(rendered.get("skins") or [])
    brief = design_brief.load(run)
    brand = (brief or {}).get("brand") or {}
    if any(brand.get(k) for k in ("client_name", "client_logo", "proposer_name", "proposer_logo")):
        skins = list(skins) + [{"brand": brand}]
    return skins or None


def apply_stage9(run: Path, args: argparse.Namespace) -> tuple[dict, Path, "list | None"]:
    deck_path = run / "deck.json"
    if not deck_path.exists():
        raise PipelineInputError(f"deck.json 없음: {deck_path}")
    ov_path = rel_or_abs(args.overrides) if args.overrides else run / "design_overrides.json"
    if not ov_path.exists():
        raise PipelineInputError(f"design_overrides.json 없음: {ov_path}")
    _restore_collected_file(run, ov_path)
    deck = json.loads(deck_path.read_text(encoding="utf-8"))

    if str(APP_ROOT / "render") not in sys.path:
        sys.path.insert(0, str(APP_ROOT / "render"))
    import overrides as ov_mod  # type: ignore
    ov = ov_mod.load_overrides(ov_path)
    errs = ov_mod.validate_overrides(ov, deck)
    if errs:
        for e in errs:
            print(f"[INVALID] {e}", file=sys.stderr)
        raise PipelineInputError(f"override 검증 실패({len(errs)}건) — 적용 중단(SSOT 안전)")
    for w in ov_mod.image_slot_warnings(ov):  # W27 D7: web_sample 출처 누락 — 차단 아님
        print(f"[WARN] {w}", file=sys.stderr)

    *_, render_html = _app_modules()
    html_path = run / "deck.html"
    if html_path.exists():  # 재현/롤백용 백업(1회 프로즌)
        write_text(run / "deck.pre_stage9.html", html_path.read_text(encoding="utf-8"))
    skins = _design_skins(run, args)  # W22: CLI > design_brief.skin.skins > state rendered.skins (+brand 최후승)
    rep = render_html(deck, args.pack, html_path, overrides=ov, skins=skins)
    _write_doc_view(deck, run)  # 마찰11: 재렌더 경로에서도 문서 뷰 동기 갱신(파생 뷰 stale 방지)
    return rep, ov_path, skins


def _institution_research_mod():
    """app/render/institution_research.py 로드(W26 — 기관 조사 검증·스킨 변환·번들)."""
    if str(APP_ROOT / "render") not in sys.path:
        sys.path.insert(0, str(APP_ROOT / "render"))
    import institution_research as ir_mod  # type: ignore
    return ir_mod


def _institution_research_block(run: Path) -> "str | None":
    """W26: message_map/storyline 핸드오프에 동봉할 직인용 훅 요약. 없으면 None(바이트 불변)."""
    ir_mod = _institution_research_mod()
    res = ir_mod.load(run)
    if res is None:
        return None
    return "# 입력: 기관 조사 (직인용 후보)\n" + ir_mod.render_for_prompt(res)


def _master_design_block(run: Path) -> "str | None":
    """W31 R10 v2(β2): message_map/storyline 핸드오프에 동봉할 확정 룩·밀도 요약.

    design_contract.json에 art_direction.look이 없으면 None(바이트 불변 — 마스터 시안 없는 run의
    프롬프트는 손대지 않는다, company_profile_block과 동일 문법). 밀도가 비표준이면 밴드 조정
    지침 1줄을 함께 담는다(R9·emphasis와 같은 원칙 — 디자인 결정을 내용 루프로 되돌린다)."""
    contract = design_contract.load(run)
    if contract is None:
        return None
    look = (contract.get("art_direction") or {}).get("look")
    if not look:
        return None
    lines = ["# 입력: 확정 룩(마스터 시안, 07_테마확정 · R10 v2)", f"- look: {look}"]
    density = contract.get("density") or "standard"
    lines.append(f"- density: {density}")
    if density != "standard":
        direction = "표준 밴드보다 적게(여백형)" if density == "spacious" else "표준 밴드보다 많게(밀집형)"
        lines.append(f"- ⚠️ 밀도 비표준 — 분량을 {direction} 조정해 이 룩에 맞춰라.")
    chosen_axis = (contract.get("art_direction") or {}).get("chosen_axis")
    if chosen_axis:
        lines.append(f"- 확정 축: {chosen_axis}")
    return "\n".join(lines)


def _company_profile_block(run: Path) -> "str | None":
    """W31 리허설 마찰6: message_map/storyline 핸드오프에 동봉할 자사 프로필 요약.

    run에 회사가 선택되지 않았거나 profile.json이 없으면 None(바이트 불변 — 기존 미선택
    run의 프롬프트는 손대지 않는다).
    """
    sel = company.load_selection(run)
    if sel is None:
        return None
    profile = company.load(sel.get("company_id") or "")
    if profile is None:
        return None
    return company.render_for_prompt(profile)


# 실측(gen_R26BK01642766-000 등): adapt_storyline은 slide.role을 section 원문 그대로 쓴다
# (영문 "company"가 아니라 "제안업체"/"사업관리"/"조직"/"실적") — skeleton.py의 level1 role
# 태그("company"/"management")는 조립 내부용이지 deck.json까지 오지 않는다. template_id가 더
# 신뢰할 수 있는 신호라 함께 본다(app/enrich.py._COMPANY_ROLE_TEMPLATES와 동일 범위 유지).
_COMPANY_GAP_ROLE_TAGS = {"제안업체", "사업관리", "조직", "실적", "company", "management", "organization"}
_COMPANY_GAP_TEMPLATE_IDS = {"portfolio_cases", "org_roles"}


def _collect_company_gap_entries(deck: dict, run_name: str) -> list[str]:
    """W31 리허설 마찰6: 제안사 관련 장 중 여전히 검토요망이 남은 슬라이드 → gaps.md 항목 문자열."""
    entries: list[str] = []
    for slide in deck.get("slides", []):
        role = slide.get("role")
        tid = slide.get("template_id")
        if role not in _COMPANY_GAP_ROLE_TAGS and tid not in _COMPANY_GAP_TEMPLATE_IDS:
            continue
        for tag in (slide.get("review_needed") or []):
            label = slide.get("title") or tid or role or "?"
            entries.append(f"[{run_name}] {label}: {tag}")
    return entries


def _wireframe_mod():
    """app/render/wireframe.py 로드(W21 — 결정기 계약 검증·병합·번들)."""
    if str(APP_ROOT / "render") not in sys.path:
        sys.path.insert(0, str(APP_ROOT / "render"))
    import wireframe as wf_mod  # type: ignore
    return wf_mod


def _docgen_mod():
    """app/render/docgen.py 로드(W31 리허설 마찰3 — deck.doc.html 문서형 파생 뷰, render_html과 독립)."""
    if str(APP_ROOT / "render") not in sys.path:
        sys.path.insert(0, str(APP_ROOT / "render"))
    import docgen as docgen_mod  # type: ignore
    return docgen_mod


def _write_doc_view(deck: dict, run: Path) -> None:
    """deck.html(정본) 옆에 deck.doc.html(문서형 파생 뷰)을 함께 생성한다. 실패해도 본선 render를
    막지 않는다(review_badges와 같은 관례 — 별책 파생 뷰는 정본 렌더 성패와 독립)."""
    try:
        doc_rep = _docgen_mod().render_doc(deck, run / "deck.doc.html")
        for w in doc_rep.get("warnings") or []:
            print(f"[WARN] deck.doc.html: {w}", file=sys.stderr)
    except Exception as exc:
        print(f"[WARN] deck.doc.html 생성 실패(문서 뷰 — 정본과 무관): {exc}", file=sys.stderr)


def wireframe_cmd(args: argparse.Namespace) -> int:
    """W21 [3] 와이어프레임 루프 부품 (go의 내부 단계 — 결정 10·12).

    --bundle: 결정기(LLM) 프롬프트 번들 생성 → run/wireframe_prompt/prompt.md
    --apply : run/wireframe.json(또는 --file) 검증 → deck.json 병합 → 무채 재렌더 →
              gating_report.wireframe 블록 + applied_axes.html.wireframe 실측 갱신.
    검증 오류 = 적용 중단(SSOT 안전, stage9 override 문법과 동일). 경고 = 표면화.
    """
    run = _render_run_dir(args.run_dir, must_exist=True)
    wf_mod = _wireframe_mod()
    deck_path = run / "deck.json"
    if not deck_path.exists():
        raise PipelineInputError(f"deck.json 없음: {deck_path} (내용 동결 전 — [1]~[2]를 먼저)")
    deck = json.loads(deck_path.read_text(encoding="utf-8"))

    if args.bundle:
        mm_path = run / "message_map.json"
        mm = json.loads(mm_path.read_text(encoding="utf-8")) if mm_path.exists() else None
        kc_profile = gates.load_config(run)["profile"]  # ε패킷: 지식 pull+보고 의무
        prompt = wf_mod.build_prompt(deck, mm, run=run, profile=kc_profile)
        out_dir = run / "wireframe_prompt"
        out_dir.mkdir(exist_ok=True)
        write_text(out_dir / "prompt.md", prompt)
        _record_state(run, "wireframe_bundle", artifacts={"prompt": str(out_dir / "prompt.md")})
        print(f"[WIREFRAME BUNDLE] {display_path(out_dir / 'prompt.md')} "
              f"(slides={len(deck.get('slides', []))}) — 결정기(LLM)에 주고 wireframe.json을 run 루트에 수거")
        if not getattr(args, "wf_apply", False):
            return 0

    if getattr(args, "wf_apply", False):
        wf_path = rel_or_abs(args.file) if getattr(args, "file", None) else run / "wireframe.json"
        if not wf_path.exists():
            raise PipelineInputError(f"wireframe.json 없음: {wf_path} (--bundle로 프롬프트를 만들어 결정기에 주고 수거하라)")
        wf = wf_mod.load(wf_path)
        validation = wf_mod.validate(wf, deck)
        for w in validation["warnings"]:
            print(f"[SURFACE] {w}", file=sys.stderr)
        if validation["errors"]:
            for e in validation["errors"]:
                print(f"[INVALID] {e}", file=sys.stderr)
            raise PipelineInputError(f"wireframe 검증 실패({len(validation['errors'])}건) — 적용 중단(SSOT 안전)")
        # ε패킷 안전장치①: knowledge_used 검증(누락=차단) + 원장 기록.
        k_errors, k_warnings = knowledge_ledger.validate_knowledge_used(wf, "wireframe")
        if k_errors:
            raise PipelineInputError(
                "wireframe 지식 보고 검증 실패(차단):\n  - " + "\n  - ".join(k_errors)
                + f"\n  {wf_path} 의 knowledge_used를 채우고(빈 배열도 명시) 다시 적용하라."
            )
        for w in k_warnings:
            print(f"[SURFACE] {w}", file=sys.stderr)
        knowledge_ledger.record(run, "wireframe", wf.get("knowledge_used") if isinstance(wf, dict) else None,
                                 source_file=str(wf_path))
        _record_knowledge_gaps(run, validation["catalog_gap"], "wireframe")
        # 재현/롤백 백업(1회 프로즌 — stage9 문법)
        if not (run / "deck.pre_wireframe.json").exists():
            write_text(run / "deck.pre_wireframe.json", deck_path.read_text(encoding="utf-8"))
        applied = wf_mod.merge_into_deck(deck, wf)
        write_text(deck_path, json.dumps(deck, ensure_ascii=False, indent=2))
        *_, render_html = _app_modules()
        html_path = run / "deck.html"
        skins = _design_skins(run, args)  # W22: CLI > design_brief.skin.skins > state rendered.skins (+brand 최후승)
        rep = render_html(deck, args.pack, html_path, skins=skins)
        _write_doc_view(deck, run)  # 마찰11: 뼈대 재조판 후 문서 뷰 동기 갱신(뼈대 검토가 낡은 정독 뷰를 보지 않게)
        # 게이트 갱신 — wireframe 블록 + applied_axes.html.wireframe (자기보고 아님: 검증 결과·렌더 실측)
        gate_path = run / "gating_report.json"
        if gate_path.exists():
            report = json.loads(gate_path.read_text(encoding="utf-8"))
            report["wireframe"] = wf_mod.gating_block(wf, validation)
            axes = report.get("applied_axes") or {}
            html_axis = axes.get("html") if isinstance(axes.get("html"), dict) else {}
            html_axis.update({
                "wireframe": True, "wireframe_slides": applied,
                # W22: 재렌더가 실제로 넘긴 스킨 캐스케이드(미전달 시 기존 값 보존).
                "skins": list(skins) if skins else html_axis.get("skins") or [],
                "updated_by": "wireframe --apply",
                "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
            })
            axes["html"] = html_axis
            report["applied_axes"] = axes
            render_block = report.get("render") or {}
            render_block["html"] = rep
            report["render"] = render_block
            report["design_checks"] = _compute_design_checks(html_path)
            _rhythm = _compute_length_rhythm(deck)
            if _rhythm is not None:
                report["length_rhythm"] = _rhythm
            write_text(gate_path, json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(f"[WARN] gating_report.json 없음 — wireframe 블록 기록 생략: {gate_path}", file=sys.stderr)
        _record_state(
            run, "wireframe_apply",
            artifacts={"wireframe": str(wf_path), "html": rep["out"]},
            slides_applied=applied, warnings=len(rep.get("warnings", [])),
            rule_warnings=len(validation["warnings"]), catalog_gap=len(validation["catalog_gap"]),
            unique_combos=(validation["stats"] or {}).get("unique_combos"),
        )
        print(f"[WIREFRAME APPLIED] {display_path(wf_path)} → {rep['out']} "
              f"(slides={applied}, combos={(validation['stats'] or {}).get('unique_combos')}, "
              f"rule_warnings={len(validation['warnings'])}, gap={len(validation['catalog_gap'])})")
        kc = knowledge_ledger.stage_counts(run, "wireframe")
        print(f"  지식: 카드 {kc['cards']} · 웹 {kc['web']}건")
        return 0

    raise PipelineInputError("wireframe: --bundle 또는 --apply 중 하나를 지정하라")


def _design_spec_mod():
    """app/render/design_spec.py 로드(W23 — 목표 명세 검증·형태 레퍼런스 수집·핸드오프)."""
    if str(APP_ROOT / "render") not in sys.path:
        sys.path.insert(0, str(APP_ROOT / "render"))
    import design_spec as ds_mod  # type: ignore
    return ds_mod


def refine_cmd(args: argparse.Namespace) -> int:
    """W23 ④+ 디자인 고도화 부품(go 외부·부품 커맨드 — 결정 15·16·17).

    --bundle : 명세자(LLM) 프롬프트 번들 생성 → run/refine_prompt/prompt.md
               (design_spec.json을 run 루트에 수거해 오기를 기다린다)
    --collect: design_spec.json 검증(오류=중단) → 형태 레퍼런스 결정론 수집(run/design_refs/)
               → [사람 체크포인트] 안내(완성 디자인보다 먼저, 값싸게 조정).
    --handoff: design_spec.json + refs_manifest.json → 실행자 번들(run/refine_handoff/prompt.md).
    """
    run = _render_run_dir(args.run_dir, must_exist=True)
    handoff_ack = _require_human_ack(run, "design_refs") if args.handoff else None
    ds_mod = _design_spec_mod()
    deck_path = run / "deck.json"
    if not deck_path.exists():
        raise PipelineInputError(f"deck.json 없음: {deck_path} (렌더 전 — [1]~[4] 기본 디자인을 먼저)")
    deck = json.loads(deck_path.read_text(encoding="utf-8"))

    if args.bundle:
        brief = design_brief.load(run)
        wf_path = run / "wireframe.json"
        wf = json.loads(wf_path.read_text(encoding="utf-8")) if wf_path.exists() else None
        gate_path = run / "gating_report.json"
        gating = json.loads(gate_path.read_text(encoding="utf-8")) if gate_path.exists() else None
        prompt = ds_mod.build_prompt(run, deck, design_brief=brief, wireframe=wf, gating=gating)
        out_dir = run / "refine_prompt"
        out_dir.mkdir(exist_ok=True)
        write_text(out_dir / "prompt.md", prompt)
        _record_state(run, "refine_bundle", artifacts={"prompt": str(out_dir / "prompt.md")})
        print(f"[고도화 번들] {display_path(out_dir / 'prompt.md')} "
              f"(slides={len(deck.get('slides', []))}) - 명세자(LLM)에 주고 design_spec.json을 run 루트에 수거")
        return 0

    if args.collect:
        spec_path = rel_or_abs(args.file) if getattr(args, "file", None) else run / "design_spec.json"
        if not spec_path.exists():
            raise PipelineInputError(f"design_spec.json 없음: {spec_path} (refine --bundle 먼저)")
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        validation = ds_mod.validate(spec, deck)
        if validation["errors"]:
            for e in validation["errors"]:
                print(f"[INVALID] {e}", file=sys.stderr)
            raise PipelineInputError(f"design_spec 검증 실패({len(validation['errors'])}건) — 적용 중단(SSOT 안전)")
        for w in validation["warnings"]:
            print(f"[SURFACE] {w}")
        for g in validation["catalog_gap"]:
            print(f"[SURFACE] catalog_gap: {g}")
        manifest = ds_mod.collect_refs(run, spec)
        _record_knowledge_gaps(run, manifest.get("catalog_gap") or [], "refine")
        # §5-④-③ 참고자료 반입 통로 열기 — 사람 체크포인트에서 파일·링크를 넣을 곳 표면화.
        note_path = None
        try:
            note_path = curate.open_intake(run)
        except Exception as exc:  # pragma: no cover - 부가 관측, 차단자 아님
            print(f"[WARN] 참고자료 반입 통로 준비 실패: {exc}", file=sys.stderr)
        stats = validation["stats"]
        _record_state(
            run, "refine_collect",
            catalog_gap=len(manifest.get("catalog_gap") or []),
            content_gaps=stats.get("content_gaps", 0),
            slides_spec=stats.get("slides_spec", 0),
            refs=sum(len(v) for v in (manifest.get("per_slide") or {}).values()),
        )
        print(f"[고도화 체크포인트] {display_path(run / 'design_spec.json')} + "
              f"{display_path(run / 'design_refs')} 를 검토·조정하라. "
              f"확정 후: refine --run {run.name} --handoff")
        if note_path is not None:
            print(f"  [참고자료] 이 덱에 참고할 파일·링크가 있으면 {display_path(note_path)} 안내대로 넣어라(선택).")
        return 0

    if args.handoff:
        spec_path = run / "design_spec.json"
        manifest_path = run / "design_refs" / "refs_manifest.json"
        if not spec_path.exists() or not manifest_path.exists():
            raise PipelineInputError(
                f"design_spec.json 또는 design_refs/refs_manifest.json 없음 — refine --collect 먼저"
            )
        spec = ds_mod.load(run)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        # §5-④-③ 사람이 design_refs/에 직접 넣은 파일·링크를 핸드오프에 동봉(부가 관측·차단자 아님).
        try:
            user_refs = curate.scan_intake(run)
        except Exception as exc:  # pragma: no cover
            print(f"[WARN] 참고자료 스캔 실패: {exc}", file=sys.stderr)
            user_refs = None
        prompt = ds_mod.build_handoff(run, spec, manifest, user_refs=user_refs)
        out_dir = run / "refine_handoff"
        out_dir.mkdir(exist_ok=True)
        write_text(out_dir / "prompt.md", prompt)
        _record_state(run, "refine_handoff", artifacts={"prompt": str(out_dir / "prompt.md")})
        if handoff_ack is not None:
            pipeline_state.clear_checkpoint(run, "design_refs")
        print(f"[고도화 핸드오프] {display_path(out_dir / 'prompt.md')} - 실행자(Claude Design 등)에게 전달. "
              f"산출물 회수: (A) design_overrides.json 확장 → `stage9 --run {run.name} --apply` "
              f"또는 (B) 완성 HTML → `approve --run {run.name} --ingest <html>`")
        return 0

    raise PipelineInputError("refine: --bundle / --collect / --handoff 중 하나를 지정하라")


def curate_cmd(args: argparse.Namespace) -> int:
    """큐레이션 생애주기 — 디자인 준비 라인의 스타일 자산 관리(전부 선택 사항, DESIGN_ASSETS_LANE §5-④-③).

    --list           : 흩어진 스킨·가이드를 한 표로 → design-assets/curation_manifest.json(+md).
    --register <id>  : 자산을 design-assets/로 복사·등록(싱크백). 원본 없으면 중단(지어내지 않음).
    --refs --run <r> : 참고자료 반입 통로 열기(design_refs/refs.md) + 현재 넣은 파일·링크 표면화.
    --sync-master --run <r> : DF3 — 확정 마스터 배경·장식 자산을 design-assets/references/로 싱크백.
    """
    if getattr(args, "curate_sync_master", False):
        if not getattr(args, "run_dir", None):
            raise PipelineInputError("curate --sync-master: --run <run>을 지정하라")
        run = _render_run_dir(args.run_dir, must_exist=True)
        res = curate.sync_master_assets(run)
        print(f"[SYNC MASTER] {res['dest']}")
        if res["copied"]:
            print(f"  복사됨: {', '.join(res['copied'])}")
        if res["missing"]:
            print(f"  [WARN] 원본 없음(건너뜀): {', '.join(res['missing'])}")
        return 0

    if getattr(args, "refs", False):
        if not getattr(args, "run_dir", None):
            raise PipelineInputError("curate --refs: --run <run>을 지정하라")
        run = _render_run_dir(args.run_dir, must_exist=True)
        note = curate.open_intake(run)
        scanned = curate.scan_intake(run)
        print(f"[참고자료 통로] {display_path(note)} — 파일은 폴더에 넣고, 링크는 이 파일에 붙여라(선택).")
        print(f"  현재 반입: 파일 {len(scanned['files'])} · 링크 {len(scanned['links'])}")
        for f in scanned["files"]:
            print(f"   - 파일 {f}")
        for u in scanned["links"]:
            print(f"   - 링크 {u}")
        return 0

    if getattr(args, "curate_register", None):
        res = curate.register(args.curate_register, kind=getattr(args, "kind", None))
        print(f"[창고에 담김] {res['kind']} '{res['id']}' → {res['dest']}")
        print(f"  라이브러리 갱신: {display_path(curate.MANIFEST_MD)}")
        return 0

    # 기본 = --list (라이브러리 목록·매니페스트 갱신)
    res = curate.write_manifest()
    c = res["counts"]
    print(f"[큐레이션 라이브러리] 스킨 {c['skins']} · 가이드 {c['guides']} · 창고보관 {c['registered']}")
    print(f"  → {res['md']} (전부 선택 사항 — 안 골라도 덱은 무채 core로 나온다)")
    for e in res["entries"]:
        mark = "✅" if e.get("registered") else "  "
        warn = "" if e.get("exists", True) else " ⚠️원본없음"
        print(f"   {mark} [{e['kind']}] {e['id']}{warn}")
    return 0


def _slug_institution(name: str) -> str:
    """스킨 파일명용 슬러그 — 영숫자만 남기고 나머지는 밑줄, 전부 비영숫자면 공백만 치환."""
    ascii_only = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")
    if ascii_only:
        return ascii_only.lower()
    return re.sub(r"\s+", "_", name.strip()) or "institution"


def _guess_institution_from_analysis(run: Path) -> "str | None":
    """run/analysis/의 분석카드 첫 표(발주처 행)에서 기관명을 추정. 못 찾으면 None."""
    analysis_dir = run / "analysis"
    if not analysis_dir.is_dir():
        return None
    cards = sorted(analysis_dir.glob("*_분석카드.md"))
    if not cards:
        return None
    text = cards[0].read_text(encoding="utf-8", errors="replace")
    m = re.search(r"\|\s*발주처\s*\|\s*([^|\n(]+)", text)
    return m.group(1).strip() if m else None


def _research_bundle(run: Path, args: argparse.Namespace) -> Path:
    """--bundle 로직(테스트에서도 직접 호출 가능하도록 run: Path를 직접 받는다 — apply_stage9 패턴)."""
    ir_mod = _institution_research_mod()
    institution = args.institution or _guess_institution_from_analysis(run)
    if not institution:
        raise PipelineInputError(
            "기관명을 추정하지 못했다 — run/analysis/에 '발주처' 행이 있는 분석카드가 없다. "
            "--institution <기관명>으로 명시하라."
        )
    analysis_md = None
    analysis_dir = run / "analysis"
    if analysis_dir.is_dir():
        cards = sorted(analysis_dir.glob("*_분석카드.md"))
        if cards:
            analysis_md = cards[0].read_text(encoding="utf-8", errors="replace")
    kc_profile = gates.load_config(run)["profile"]  # ε패킷: 지식 pull+보고 의무
    prompt = ir_mod.build_prompt(run, institution=institution, analysis_md=analysis_md, profile=kc_profile)
    out_dir = run / "research_prompt"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / "prompt.md"
    write_text(out, prompt)
    _record_state(run, "research_bundle", artifacts={"prompt": str(out)})
    print(f"[기관 조사 번들] {display_path(out)} "
          f"(기관={institution}) - 조사자(LLM/사람)에 주고 institution_research.json을 run 루트에 수거")
    return out


def _research_apply(run: Path, args: argparse.Namespace) -> dict:
    """--apply 로직(테스트에서도 직접 호출 가능하도록 run: Path를 직접 받는다 — apply_stage9 패턴).

    반환 = {"skin_id", "skin_path", "brief_updated"} — 검증 실패는 PipelineInputError로 중단.
    """
    ir_mod = _institution_research_mod()
    res = ir_mod.load(run)
    if res is None:
        raise PipelineInputError(
            f"institution_research.json 없음: {ir_mod.research_path(run)} "
            "(research --bundle로 프롬프트를 만들어 조사자에게 주고 수거하라)"
        )
    validation = ir_mod.validate(res)
    for w in validation["warnings"]:
        print(f"[SURFACE] {w}")
    if validation["errors"]:
        for e in validation["errors"]:
            print(f"[INVALID] {e}", file=sys.stderr)
        raise PipelineInputError(
            f"institution_research 검증 실패({len(validation['errors'])}건) — 적용 중단(SSOT 안전)"
        )
    # ε패킷 안전장치①: knowledge_used 검증(누락=차단) + 원장 기록.
    k_errors, k_warnings = knowledge_ledger.validate_knowledge_used(res, "research")
    if k_errors:
        raise PipelineInputError(
            "institution_research 지식 보고 검증 실패(차단):\n  - " + "\n  - ".join(k_errors)
            + f"\n  {ir_mod.research_path(run)} 의 knowledge_used를 채우고(빈 배열도 명시) 다시 적용하라."
        )
    for w in k_warnings:
        print(f"[SURFACE] {w}")
    knowledge_ledger.record(run, "research", res.get("knowledge_used"), source_file=str(ir_mod.research_path(run)))

    skin_id = None
    skin_written = None
    primary = ((res.get("brand_tokens") or {}).get("colors") or {}).get("primary")
    if primary:
        skin_id = getattr(args, "skin_id", None) or _slug_institution(res.get("institution") or run.name)
        SKINS_DIR.mkdir(parents=True, exist_ok=True)
        skin_out = SKINS_DIR / f"{skin_id}.json"
        if skin_out.is_file():
            print(f"[SURFACE] 기존 스킨 덮어씀: {display_path(skin_out)}")
        skin = ir_mod.to_skin(res, skin_id)
        write_text(skin_out, json.dumps(skin, ensure_ascii=False, indent=2) + "\n")
        skin_written = skin_out
        print(f"[기관 조사] 브랜드 스킨 등록: {display_path(skin_out)} (render --skins {skin_id})")
        # W31 마찰14: design_brief가 아직 없을 때 이후 생성 기본값(design_brief.build_default)이
        # 이 스킨을 skin.value 초안으로 조회할 수 있게, 등록 사실을 조사 파일 자체에 남긴다.
        if (res.get("_applied_skin") or {}).get("skin_id") != skin_id:
            res["_applied_skin"] = {
                "skin_id": skin_id,
                "note": "research --apply가 등록한 브랜드 스킨(design_brief.skin.value 초안 조회용, 마찰14)",
            }
            ir_mod.save(run, res)

    brief_updated = False
    skin_value_note = None
    brief = design_brief.load(run)
    if brief is not None:
        if skin_id:
            skin_field = brief.setdefault("skin", {})
            skins = skin_field.setdefault("skins", [])
            if skin_id not in skins:
                skins.append(skin_id)
                brief_updated = True
            # ⚠️ skin.value(계약 차용 소스, design_contract가 읽는다) vs skin.skins(render 스킨
            # 체인, W22) — 둘은 다른 키다. 여기서 채우는 건 value: 기존 값이 있으면 사용자 결정을
            # 덮지 않고 안내만 한다(마찰14 — "자동 승계"가 아니라 "빈 값일 때만 승계").
            if not skin_field.get("value"):
                skin_field["value"] = skin_id
                brief_updated = True
                skin_value_note = f"design_brief.skin.value = {skin_id} 승계(계약 차용 소스)"
            else:
                skin_value_note = (
                    f"design_brief.skin.value 기존값 보존({skin_field['value']}) — "
                    f"등록 스킨({skin_id})을 쓰려면 브리핑을 직접 수정하라"
                )
        brand = brief.setdefault("brand", {})
        if not brand.get("client_name") and res.get("institution"):
            brand["client_name"] = res.get("institution")
            brief_updated = True
        if brief_updated:
            design_brief.save(run, brief)

    artifacts = {"research": str(ir_mod.research_path(run))}
    if skin_written:
        artifacts["skin"] = str(skin_written)
    _record_state(run, "research_apply", artifacts=artifacts, skin_id=skin_id, brief_updated=brief_updated)
    print(f"[기관 조사 적용] {display_path(ir_mod.research_path(run))} 검증 완료"
          + (f" · 스킨={skin_id}" if skin_id else " · 브랜드색 없음(스킨 미등록)"))
    kc = knowledge_ledger.stage_counts(run, "research")
    print(f"  지식: 카드 {kc['cards']} · 웹 {kc['web']}건")
    if skin_value_note:
        print(f"  {skin_value_note}")
    elif skin_id:
        # design_brief.json이 아직 없다 — 실제 승계는 design_brief 생성 기본값이 이 스킨을
        # institution_research.json에서 조회해 skin.value 초안으로 채운다(마찰14, 자동 폴백 아님).
        print("  design_brief.json이 아직 없다 — 이후 생성 기본값이 이 스킨을 skin.value 초안으로 조회한다"
              "(B1에서 재확정 가능). 즉시 지정하려면 render --skins <id>.")
    return {"skin_id": skin_id, "skin_path": skin_written, "brief_updated": brief_updated}


def research_cmd(args: argparse.Namespace) -> int:
    """W26 [1] 기관 공개 조사 서브스텝(목표조정 8·9) — 문서 밖 근거 + 브랜드 스킨 경로.

    --bundle: 조사자(LLM) 프롬프트 번들 생성 → run/research_prompt/prompt.md
              (institution_research.json을 run 루트에 수거해 오기를 기다린다)
    --apply : institution_research.json 검증(오류=중단) → brand_tokens.colors.primary가 있으면
              skins/<id>.json 등록. design_brief.json이 있으면 skin.skins(렌더 체인)에 추가하고
              skin.value(계약 차용 소스)가 비어 있을 때만 채운다(있으면 보존 — W31 마찰14, 자동
              폴백 아님). design_brief.json이 아직 없으면 등록 스킨 id를 institution_research.json
              자체(`_applied_skin.skin_id`)에 남겨, 이후 design_brief 생성 기본값이 조회해
              skin.value 초안으로 쓴다.
    """
    run = _render_run_dir(args.run_dir, must_exist=True)
    if args.bundle:
        _research_bundle(run, args)
        return 0
    if args.apply:
        _research_apply(run, args)
        return 0
    raise PipelineInputError("research: --bundle 또는 --apply 중 하나를 지정하라")


def _company_bundle_cmd(company_id: str) -> None:
    company.ensure_scaffold(company_id)  # 처음 다루는 회사면 assets/·intake/를 여기서 연다(멱등).
    prompt = company.build_bundle_prompt(company_id)
    out = company.bundle_prompt_path(company_id)
    write_text(out, prompt)
    intake_n = len(list(company.intake_dir(company_id).glob("*"))) if company.intake_dir(company_id).is_dir() else 0
    print(f"[COMPANY BUNDLE] {display_path(out)} (회사={company_id} · intake 파일 {max(intake_n - 1, 0)}건 — "
          f"README 제외)")
    print(f"  intake/에 원본을 넣었다면 이 프롬프트를 LLM/사람에 주고 결과를 "
          f"company --apply --id {company_id} --file <경로> 로 수거하라.")


def _company_apply_cmd(company_id: str, file_path: str) -> dict:
    candidate_path = Path(file_path)
    if not candidate_path.is_file():
        raise PipelineInputError(f"파일 없음: {candidate_path}")
    try:
        incoming = json.loads(candidate_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PipelineInputError(f"JSON 파싱 실패: {candidate_path} ({exc})") from exc

    validation = company.validate(incoming)
    if validation["warnings"]:
        for w in validation["warnings"]:
            print(f"[SURFACE] {w}")
    if validation["errors"]:
        for e in validation["errors"]:
            print(f"[INVALID] {e}", file=sys.stderr)
        raise PipelineInputError(
            f"company profile 검증 실패({len(validation['errors'])}건) — 병합 중단(SSOT 안전)"
        )

    existing = company.load(company_id)
    merged, diff = company.merge_profile(existing, incoming)
    # 병합 결과 전체를 한 번 더 검증(부분 패치가 기존 문제를 못 가리게) — 특히 회사명 존재.
    final_check = company.validate(merged)
    if final_check["errors"]:
        for e in final_check["errors"]:
            print(f"[INVALID] {e}", file=sys.stderr)
        raise PipelineInputError(
            f"병합 결과가 여전히 무효({len(final_check['errors'])}건) — 저장 중단"
        )
    company.ensure_scaffold(company_id)
    path = company.save(company_id, merged)

    gaps = company.structural_gaps(merged)
    gap_added = company.append_gaps(company_id, [f"(구조 스캔) {g}" for g in gaps]) if gaps else 0

    added_total = sum(diff.get("added", {}).values())
    updated_total = sum(diff.get("updated", {}).values())
    print(f"[COMPANY APPLY] {display_path(path)} 병합 완료 (신규 {added_total}건 · 갱신 {updated_total}건)"
          + (f" · overview 갱신: {', '.join(diff['overview_updated'])}" if diff.get("overview_updated") else ""))
    if gaps:
        print(f"  [구조 스캔] 여전히 비어있는 섹션 {len(gaps)}건 -> {display_path(company.gaps_path(company_id))}"
              + (f"(신규 {gap_added}건)" if gap_added else "(이미 기록됨)"))
    return {"path": path, "diff": diff, "gaps": gaps}


def _company_list_cmd() -> None:
    rows = company.list_companies()
    print(company.format_list(rows))


def company_cmd(args: argparse.Namespace) -> int:
    """W31 리허설 마찰6 — 제안사(자사) 프로필 창고: --list / --bundle --id / --apply --id --file."""
    if getattr(args, "company_list", False):
        _company_list_cmd()
        return 0
    if getattr(args, "bundle", False):
        if not args.id:
            raise PipelineInputError("company --bundle: --id <회사id>가 필요하다")
        _company_bundle_cmd(args.id)
        return 0
    if getattr(args, "apply", False):
        if not args.id or not args.file:
            raise PipelineInputError("company --apply: --id <회사id> --file <JSON 경로>가 필요하다")
        _company_apply_cmd(args.id, args.file)
        return 0
    raise PipelineInputError("company: --list / --bundle --id <id> / --apply --id <id> --file <경로> 중 하나를 지정하라")


def _collab_tier() -> int:
    """CONTEXT/collab_state.json의 tier(없으면 0=SOLO). 이미지 생성 게이트용."""
    p = REPO_ROOT / "CONTEXT" / "collab_state.json"
    try:
        return int(json.loads(p.read_text(encoding="utf-8")).get("tier", 0))
    except Exception:
        return 0


def _sync_brief_slots(run: Path, ov_path: Path, ov: dict) -> list[str]:
    """W3b: design_brief.image_slots_plan의 슬롯을 override(정본)에 **추가만** 한다.

    브리핑이 없으면 무동작. 추가분이 있을 때만 파일을 다시 쓴다(멱등).
    """
    brief = design_brief.load(run)
    if not brief:
        return []
    added = design_brief.sync_slots_into_overrides(brief, ov)
    if added:
        write_text(ov_path, json.dumps(ov, ensure_ascii=False, indent=2))
    return added


def _skin_palette(pack: "str | None") -> dict[str, str]:
    """결정 5: 팩 tokens.json 색을 생성 프롬프트용 팔레트로 — 아이콘/배경이 테마와 정합.

    핵심 색만 뽑아 name #hex 로. 없으면 빈 dict(image_slots가 기본 팔레트로 폴백).
    """
    try:
        colors = json.loads(
            (_pack_dir(pack) / "tokens.json").read_text(encoding="utf-8")
        ).get("colors") or {}
    except Exception:
        return {}
    want = ("navy", "orange", "blue2", "gray_line", "gray_text", "black", "white")
    out: dict[str, str] = {}
    for k in want:
        v = colors.get(k)
        if isinstance(v, str) and v:
            out[k] = "#" + v.lstrip("#")
    return out


def fill_images_stage9(run: Path, args: argparse.Namespace) -> dict:
    """§7·B-9(+W3b): override의 image_slots를 채운다(mood/conceptual만·evidence 자동생성 금지).

    codex 러너로 SVG 생성 → run/stage9_design/slots/에 커밋. 이후 --apply 재렌더가 인라인.
    생성 대상 슬롯의 정본은 design_overrides.json — 그 전에 design_brief의 계획을 병합한다(W3b).
    생성 허용은 **이 커맨드를 친 사실**이 근거다(단발 위임, N3-4) — 협업 tier와 무관.
    `--no-generate`면 러너 없이 계획만 반영(slot → placeholder degrade).
    """
    ov_path = rel_or_abs(args.overrides) if args.overrides else run / "design_overrides.json"
    if not ov_path.exists():
        # 디렉터가 아직 안 돌았어도 브리핑의 슬롯 계획만으로 이미지 공급이 가능해야 한다(W3b).
        # 브리핑도 없으면 채울 근거가 없다 → 기존대로 실패.
        if not design_brief.exists(run):
            raise PipelineInputError(f"design_overrides.json 없음: {ov_path}")
        write_text(ov_path, json.dumps({"version": 1, "slides": {}}, ensure_ascii=False, indent=2))
        print(f"[STAGE9 FILL] design_overrides.json 신규 생성(브리핑 계획 기반): {display_path(ov_path)}")
    if str(APP_ROOT / "render") not in sys.path:
        sys.path.insert(0, str(APP_ROOT / "render"))
    if str(APP_ROOT) not in sys.path:
        sys.path.insert(0, str(APP_ROOT))
    import image_slots as img_mod  # type: ignore
    import json as _json
    ov = _json.loads(ov_path.read_text(encoding="utf-8"))
    added = _sync_brief_slots(run, ov_path, ov)
    for sid in added:
        print(f"  - brief_slot_added: {sid}")
    tier = _collab_tier()
    allow = not args.no_generate
    runner = None
    if allow:
        # W32 수동 루트: codex 미감지면 러너 없이 degrade(종전엔 subprocess가 조용히 빈 문자열을
        # 돌려줘 원인이 안 보였다) + 수동 대안(규약 경로에 직접 넣기)을 안내한다.
        if imagedeck.detect_producers().get("codex"):
            import codex_runner  # type: ignore
            runner = codex_runner.make_codex_runner(cwd=REPO_ROOT)
        else:
            print("[STAGE9 FILL] codex CLI 미감지 - 생성 없이 placeholder로 degrade한다(W32). "
                  "수동 대안: 슬롯 prompt로 이미지를 만들어 "
                  "run/stage9_design/slots/slide<키>_<슬롯id>.png(svg/jpg 가능)에 넣고 --apply 재실행.")
    palette = _skin_palette(getattr(args, "pack", None))
    rep = img_mod.fill_images(ov, run, tier=tier, runner=runner, allow_generate=allow,
                              palette=palette)
    rep["brief_slots_added"] = added
    no_prompt = rep.get("skipped_no_prompt") or []
    print(f"[STAGE9 FILL] tier={tier} generate={allow} generated={len(rep['generated'])} "
          f"cached={len(rep['cached'])} "
          f"degraded={len(rep['degraded'])} evidence-skip={len(rep['skipped_evidence'])} "
          f"no-prompt-skip={len(no_prompt)}")
    for k in ("generated", "degraded", "skipped_evidence", "skipped_no_prompt"):
        for sid in rep.get(k) or []:
            print(f"  - {k}: {sid}")
    if no_prompt:
        print(f"[STAGE9 FILL] ⚠ 빈 프롬프트 {len(no_prompt)}개 슬롯은 생성하지 않았다(제네릭 방지) — "
              f"배경 주제를 프롬프트에 채운 뒤 다시 --fill-images 하라: {', '.join(no_prompt)}")
    return rep


def stage9_cmd(args: argparse.Namespace) -> int:
    run = _render_run_dir(args.run_dir, must_exist=True)
    if getattr(args, "fill_images", False):
        rep = fill_images_stage9(run, args)
        _record_state(
            run, "stage9_fill_images",
            generated=len(rep["generated"]), cached=len(rep["cached"]),
            degraded=len(rep["degraded"]), skipped_evidence=len(rep["skipped_evidence"]),
            skipped_no_prompt=len(rep.get("skipped_no_prompt") or []),
            brief_slots_added=len(rep.get("brief_slots_added") or []),
        )
        if not args.apply:
            return 0
    if args.apply:
        rep, ov_path, skins = apply_stage9(run, args)
        # W1 갭 해소(W3a): 병합된 deck.html을 실측해 gating_report.applied_axes.html을 갱신한다.
        # 그래도 state.json이 정본 — render 재실행이 gating_report를 통째로 되돌리기 때문(D2).
        axis = _update_applied_axes(run, overrides_path=ov_path, html_path=Path(rep["out"]),
                                    render_rep=rep, skins=skins)
        _record_state(
            run, "stage9_apply",
            artifacts={"overrides": str(ov_path), "html": rep["out"]},
            slides=rep["slides"], warnings=len(rep.get("warnings", [])),
            gating_report_updated=axis is not None,
            image_slots=(axis or {}).get("image_slots", 0),
        )
        print(f"[STAGE9 APPLIED] overrides={display_path(ov_path)} → {rep['out']} "
              f"(slides={rep['slides']}, warnings={len(rep.get('warnings', []))})")
        if axis:
            print(f"[GATE] applied_axes.html: overrides={axis['overrides']} "
                  f"image_slots={axis['image_slots']} (placeholder={axis['image_slots_placeholder']})")
        _print_design_checks(run)
    else:
        out, targets, mode, shots = bundle_stage9(run, args)
        _record_state(run, "stage9_bundle", artifacts={"prompt": str(out)}, targets=targets,
                      target_mode=mode, screenshots=len(shots))
        print(f"[STAGE9 BUNDLE] {out}")
        print(f"- mode: {mode}")
        print(f"- targets: {', '.join(targets) or '(none)'}")
        if shots:
            print(f"- screenshots: {len(shots)}장 → {display_path(shots[0].parent)}")
        else:
            print("- screenshots: 없음 — 텍스트만으로 판단(번들에 사유 명시)")
    return 0


# ---------------------------------------------------------------------------
# W3c — 승인 전 덱 평가(§N6-1) + 시네마틱 파생(§N6-2). 신규 최상위 커맨드 0(go/ship 내부 단계).
#   go는 LLM을 호출하지 않는다(D4): 번들 조립·수거 검증만 결정론으로 한다.
# ---------------------------------------------------------------------------

def _gating(run: Path) -> dict:
    p = run / "gating_report.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _image_provenance_ship_warnings(gating: dict) -> list[str]:
    """W27 D6·D7: gating_report.image_provenance → ship 경고 문자열(차단 아님 — W5와 같은 문법).

    순수 함수(부작용 없음) — ship_cmd가 이 목록을 그대로 [SHIP 경고]로 찍는다.
    """
    prov = (gating or {}).get("image_provenance") or {}
    out: list[str] = []
    gen_ev_unresolved = prov.get("generated_evidence_unresolved", 0)
    if gen_ev_unresolved:
        out.append(
            f"AI 생성 evidence 딱지 잔존 {gen_ev_unresolved}건이 남은 채 승인한다 "
            "- 실자산으로 교체하거나 slot.generated_resolved에 사유를 명시하라."
        )
    web_sample_n = prov.get("web_sample", 0)
    if web_sample_n:
        out.append(
            f"웹 수급 자산 {web_sample_n}건(출처 기록 {prov.get('web_sample_sourced', 0)}건)이 "
            "포함된 채 승인한다 - 최종 교체 판단 재료로 남긴다(D7)."
        )
    return out


def bundle_deck_review(run: Path, args: argparse.Namespace) -> Path:
    """평가 프롬프트 번들. 입력 = deck.json + deck.html 실측 + gating_report + 브리핑 + 규칙층 가이드."""
    deck_path = run / "deck.json"
    html_path = run / "deck.html"
    if not deck_path.exists() or not html_path.exists():
        raise PipelineInputError(f"deck.json/deck.html 없음: {run} (먼저 render/stage9 --apply)")

    if str(APP_ROOT / "render") not in sys.path:  # deck_review.measure → design_checks
        sys.path.insert(0, str(APP_ROOT / "render"))
    # 평가 직전 = 브라우저 실측을 붙이는 두 번째 자리(첫 자리는 stage9 --apply). 평가자가
    # 픽셀 사실 없이 "PNG를 보라"는 말만 받던 공백을 메운다. 실패해도 정적 실측으로 진행한다.
    measured = _browser_design_checks(html_path) or deck_review.measure(
        html_path.read_text(encoding="utf-8"))

    gating = _gating(run)
    brief = design_brief.load(run)
    guides = resolve_design_guides(load_config(), getattr(args, "design_guide", None))
    guide_blocks = [
        (g["id"], read_text(g["spec_text"], 30000), len(g["examples"]))
        for g in guides if g["spec_text"].exists()
    ]

    text = deck_review.build_prompt(
        run=run,
        header=prompt_header(10, "덱 평가(승인 전·비전)", [str(deck_path), str(html_path)]),
        contract=read_text(PROMPTS / "deck_review.md"),
        deck_json_text=read_text(deck_path, 60000),
        measured=measured,
        recorded_checks=gating.get("design_checks"),
        applied_axes=(gating.get("applied_axes") or {}).get("html"),
        brief_block=design_brief.render_for_prompt(brief) if brief else None,
        guide_blocks=guide_blocks,
    )
    out = deck_review.prompt_path(run)
    write_text(out, _anonymize_bundle_text(run, text))
    return out


def collect_deck_review(run: Path) -> dict:
    """산출물 계약 검증 후 수거. 위반이면 실패한다 — 수거하지 못한 걸 수거했다고 하지 않는다."""
    _restore_collected_file(run, deck_review.review_path(run))
    rep = deck_review.collect(run)
    if rep["errors"]:
        for e in rep["errors"]:
            print(f"[INVALID] deck_review.md: {e}", file=sys.stderr)
        raise PipelineInputError(f"deck_review.md 계약 위반({len(rep['errors'])}건) — 수거 거부")
    return rep


def _record_pptx_raster_observation(run: Path, rep: dict, *, source_html: Path,
                                     pack: str | None = None, skins: list | None = None) -> None:
    """W4/B3: 슬라이드 래스터 PPTX의 관측을 별 블록에 적고, applied_axes.pptx도 실측 갱신한다.

    이 경로(ship --pptx-mode image)는 승인된 HTML을 그대로 찍는다 — native pptx(add_specs)와
    달리 override·image_slots·manual_layer가 실제로 실려 있다. `applied_axes.pptx`가 여전히
    render 시점 값(항상 null/false)에 머물면 "경로별 실제 적용 축" 정의를 어긴다(B3) — 그래서
    source_html을 직접 실측해 여기서도 채운다.
    """
    gate_path = run / "gating_report.json"
    if not gate_path.exists():
        return
    report = json.loads(gate_path.read_text(encoding="utf-8"))
    report["pptx_raster"] = {
        "mode": "image",
        "source_html": display_path(source_html),
        "slides_captured": rep["slides"],
        "out": display_path(Path(rep["out"])),
        "note": "승인된 HTML의 슬라이드별 스크린샷 조립 — deck.json에서 재렌더한 것이 아니다"
                "(add_specs 경로 아님, override·이미지가 그대로 찍힌다). "
                "이미지 PPTX: 텍스트 편집 불가·접근성 없음·용량 증가.",
        "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    axes = report.get("applied_axes")
    if not isinstance(axes, dict):
        axes = {"html": None, "pptx": None}
    html_axis = axes.get("html") if isinstance(axes.get("html"), dict) else {}
    total, placeholder = _measure_slots(source_html.read_text(encoding="utf-8"))
    axes["pptx"] = {
        "pack": pack,
        "skins": list(skins) if skins else [],
        "overrides": html_axis.get("overrides", (run / "design_overrides.json").exists()),
        "image_slots": total,
        "image_slots_placeholder": placeholder,
        "manual_layer": source_html.name == "manual_layer.html",
        "mode": "image",
        "measured_from": f"{display_path(source_html)} (슬라이드 래스터 실측)",
        "updated_by": "ship --pptx --pptx-mode image",
        "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    report["applied_axes"] = axes
    write_text(gate_path, json.dumps(report, ensure_ascii=False, indent=2))


def _ship_pptx_image(run: Path, view: dict) -> dict:
    """ship --pptx --pptx-mode image: 승인된 HTML을 슬라이드 단위로 캡처해 PPTX 조립(S6-2 본체).

    add_specs(deck, ...) 경로를 쓰지 않는다 — 그 경로는 deck.json에서 HTML을 내부적으로
    재생성하므로 우리가 승인한 deck.html(병합본)이 아니다. 여기서는 디스크의 승인된
    HTML 파일을 그대로 열어 캡처한다.
    """
    if str(APP_ROOT) not in sys.path:
        sys.path.insert(0, str(APP_ROOT))
    from render import rasterize as rasterize_mod  # type: ignore
    from render.dispatch import images_to_pptx  # type: ignore

    # W28: image 라우트면 조합본(deck.images.html)을 래스터한다(§2f "ship --pptx-mode image 재사용").
    route, _ = pipeline_state.render_route(run)
    manual_layer = run / "manual_layer.html"
    images_html = run / "deck.images.html"
    if route == "image_infographic" and images_html.exists():
        source_html = images_html
    elif manual_layer.exists():
        source_html = manual_layer
    else:
        source_html = run / "deck.html"
    if not source_html.exists():
        raise PipelineInputError(f"승인된 HTML 없음: {source_html} (먼저 render/stage9/approve)")

    img_dir = run / "pptx_slides"
    images = rasterize_mod.html_to_slide_pngs(source_html, img_dir)

    rendered = view["stages"].get("render", {})
    skins = rendered.get("skins") or None
    pack = rendered.get("pack", "house_a")
    rep = images_to_pptx(images, pack, run / "deck.pptx", skins=skins)
    rep["source_html"] = str(source_html)
    _record_pptx_raster_observation(run, rep, source_html=source_html, pack=pack, skins=skins)
    return rep


# ---------------------------------------------------------------------------
# 승인 표면(§8) — 부착형 게이트: 디렉터 유무·순수 렌더 뒤에도 사용.
#   표면 ① 정적 프리뷰 승인  ·  표면 ② Claude Design 편집본 회수(텍스트 가드→manual_layer freeze)
# publish/회수(claude.ai)는 Claude 오케스트레이션(Artifact+WebFetch) — 파이썬은 가드·freeze·기록만.
# ---------------------------------------------------------------------------

def approve_cmd(args: argparse.Namespace) -> int:
    run = _render_run_dir(args.run_dir, must_exist=True)
    design_ack = _require_human_ack(run, "design")
    deck_path = run / "deck.json"
    if not deck_path.exists():
        raise PipelineInputError(f"deck.json 없음: {deck_path}")
    deck = json.loads(deck_path.read_text(encoding="utf-8"))
    stamp = dt.datetime.now().isoformat(timespec="seconds")
    record: dict[str, Any] = {"status": "approved", "timestamp": stamp}

    if args.ingest:  # 표면 ② — Claude Design 편집본 회수
        edited_path = rel_or_abs(args.ingest) if not as_path(args.ingest).is_absolute() else as_path(args.ingest)
        if not edited_path.exists():
            raise PipelineInputError(f"편집본 없음: {edited_path}")
        edited_html = edited_path.read_text(encoding="utf-8", errors="replace")

        if str(APP_ROOT / "render") not in sys.path:
            sys.path.insert(0, str(APP_ROOT / "render"))
        import overrides as ov_mod  # type: ignore
        baseline_path = run / "deck.html"
        if not baseline_path.exists():
            raise PipelineInputError(f"베이스라인 deck.html 없음: {baseline_path} (편집 전 렌더본 필요)")
        baseline_html = baseline_path.read_text(encoding="utf-8", errors="replace")
        # 결정 7(2026-07-09): 차단하지 않는다 — 변경 명세를 생성해 run에 남기고 freeze를 진행한다.
        diff = ov_mod.manual_layer_diff(edited_html, deck, baseline_html)
        diff_path = run / "manual_layer_diff.md"
        write_text(diff_path, ov_mod.render_manual_layer_diff_md(diff))
        removed_n, added_n = len(diff["removed"]), len(diff["added"])
        if removed_n or added_n:
            print(f"[DIFF] manual_layer_diff.md: 삭제 {removed_n}건 · 추가 {added_n}건 "
                  f"— {diff_path} (freeze는 막지 않는다 · 결정 7)")
        else:
            print(f"[DIFF] manual_layer_diff.md: 변경 0건 — {diff_path}")

        frozen = run / "manual_layer.html"
        write_text(frozen, edited_html)
        record.update({
            "surface": "claude-design",
            "manual_layer": str(frozen),
            "source": args.source or str(edited_path),
            "manual_layer_diff": str(diff_path),
            "diff_removed": removed_n,
            "diff_added": added_n,
        })
        print(f"[APPROVED · manual_layer] {frozen} (source={record['source']})")
    else:  # 표면 ① — 정적 프리뷰 승인
        html_path = run / "deck.html"
        if not html_path.exists():
            raise PipelineInputError(f"deck.html 없음: {html_path} (먼저 render/stage9)")
        record.update({"surface": "static", "preview": str(html_path)})
        print(f"[APPROVED · static] {html_path}")

    write_text(run / "approval.json", json.dumps(record, ensure_ascii=False, indent=2))
    _record_state(
        run, "approve",
        artifacts={"approval": str(run / "approval.json")},
        surface=record.get("surface"),
    )
    if design_ack is not None:
        pipeline_state.clear_checkpoint(run, "design")
    return 0


# ---------------------------------------------------------------------------
# 보관소 왕복(W31 리허설 마찰9) — 부착형 커맨드(§3.0: 새 렌더 단계가 아니라 run 정리 유틸리티라
#   동사 3개 밖에 둔다. company/curate/add-skin과 같은 반열 — go가 호출하는 부품이 아니다).
# ---------------------------------------------------------------------------

def archive_cmd(args: argparse.Namespace) -> int:
    """`--list`(표) / `--restore <폴더명>`(복귀) / `--run <id>`(보관 이동) — 정확히 하나."""
    modes_given = sum(bool(v) for v in (args.archive_list, args.restore, args.run))
    if modes_given != 1:
        raise PipelineInputError("archive는 --run(보관) / --restore(복귀) / --list(표) 중 정확히 하나가 필요하다")

    if args.archive_list:
        print(archive.format_list(RUNS))
        return 0

    if args.restore:
        rep = archive.restore(args.restore, runs_root=RUNS)
        print(f"[RESTORE] {rep['folder']} -> {rep['restored_to']}")
        print(f"- 원 기계 id: {rep['run_id']}  (한글명이었음: {rep['korean_name']})")
        return 0

    run = _render_run_dir(args.run, must_exist=True)
    rep = archive.archive_run(run, name=args.name)
    print(f"[ARCHIVE] {run.name} -> {rep['dest']}")
    print(f"- 보관 폴더명: {rep['folder']}")
    print(f"- 한글명: {rep['korean_name']}  (출처: {rep['name_source']})")
    print(f"- 복귀: archive --restore {rep['folder']}")
    return 0


# ---------------------------------------------------------------------------
# 동사 3개 (§3.0) — start / go / ship
#   기존 커맨드는 삭제하지 않는다. 이 셋은 그것들을 **부품으로 호출하는 얇은 오케스트레이션**이다.
#   신규 커맨드는 이 3개가 마지막(§3.0 규칙): 새 기능은 이 중 하나의 내부 단계로만 편입된다.
# ---------------------------------------------------------------------------

def _run_state_view(run: Path) -> dict[str, Any]:
    """render 입력 탐색 규칙을 상태머신에 주입(규칙 복제 방지)."""
    render_input = None
    for kind in ("storyline", "stage6"):
        try:
            found = _discover_run_json(run, kind)
        except PipelineInputError:
            found = None  # 중복 입력 — go가 아니라 render가 명시적으로 실패하게 둔다
        if found:
            render_input = found
            break
    return pipeline_state.resolve(run, render_input=render_input)


def status_run_cmd(args: argparse.Namespace) -> int:
    run = _render_run_dir(args.run, must_exist=True)
    view = _run_state_view(run)
    if args.json:
        print(json.dumps(view, ensure_ascii=False, indent=2))
    else:
        print(pipeline_state.format_status(view))
        if archive.is_completed(run):  # W31 리허설 마찰9: 접점 ③ — 완료 run만, 아니면 침묵
            print(archive.hint_line(run))
    return 0


def _dashboard_feedback_go(bid: str) -> bool:
    """결정 8: dashboard/feedback.json에 이 공고가 Go로 기록됐는지 실측(자기보고 아님 — 파일 대조)."""
    path = REPO_ROOT / "dashboard" / "feedback.json"
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    entry = data.get(bid) if isinstance(data, dict) else None
    return bool(isinstance(entry, dict) and entry.get("decision") == "go")


def _copy_bid_analysis_assets(run: Path, bid: str) -> list[str]:
    """run 자립성(결정 13): direct 모드로 bid를 지정하면 해당 bid의 분석카드·프롬프트를
    run/analysis/로 복제한다(이동 아님 — bid 산출물은 여러 run이 공유 가능).

    없으면 조용히 스킵(대시보드 경로 산출물이라 없을 수 있다 — 경고 불요).
    """
    safe = bid.replace("/", "_")
    copied: list[str] = []
    for name in (f"{safe}_분석카드.md", f"{safe}_프롬프트.txt"):
        src = ANALYSIS_DIR / name
        if not src.is_file():
            src = ANALYSIS_DIR_LEGACY / name
        if not src.is_file():
            continue
        dest_dir = run / "analysis"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / name
        shutil.copyfile(src, dest)
        copied.append(str(dest))
    return copied


def start_cmd(args: argparse.Namespace) -> int:
    if bool(args.bid) == bool(args.brief):
        raise PipelineInputError("start는 --bid 또는 --brief 중 정확히 하나가 필요하다")

    brief: Path | None = None
    if args.bid:
        kind, ref = "bid", args.bid
        default_name = f"gen_{re.sub(r'[^A-Za-z0-9_.-]', '_', args.bid)}"  # 대시보드 규약과 동일
    else:
        brief = _resolve_render_input(args.brief)
        kind, ref = "brief", display_path(brief)
        default_name = brief.stem

    run = _render_run_dir(args.run_name or default_name, must_exist=False)
    run.mkdir(parents=True, exist_ok=True)
    if brief is not None:  # 범용 입구(N2): 브리프를 run에 고정해 재현성 확보
        write_text(run / "brief.md", brief.read_text(encoding="utf-8"))

    # 결정 8: 공고 선택 출처 확정(사람 전속 — 차단 없이 기록·표면화만).
    selected_by = args.selected_by
    feedback_match: bool | None = None
    unspecified_notice = False
    if kind == "bid":
        feedback_match = _dashboard_feedback_go(ref)
        if selected_by is None:
            selected_by = "dashboard" if feedback_match else "unspecified"
            unspecified_notice = selected_by == "unspecified"
    else:  # brief: 사용자가 문서를 직접 투입 — user 기본
        if selected_by is None:
            selected_by = "user"

    pipeline_state.init(
        run, mode=args.mode, input_kind=kind, input_ref=ref,
        selected_by=selected_by, bid=(ref if kind == "bid" else None),
        feedback_match=feedback_match,
    )
    copied_analysis: list[str] = []
    if kind == "bid":  # run 자립성(결정 13) — bid 산출물을 run/analysis/로 복제(있으면).
        copied_analysis = _copy_bid_analysis_assets(run, ref)
        if copied_analysis:
            _record_state(run, "start", artifacts={"analysis_copied": copied_analysis})
    if getattr(args, "gates", None):  # W31 리허설 마찰2: 착수 시 관문 프로파일 지정(선택)
        gates.save_config(run, profile=args.gates)
    company_id = getattr(args, "company", None)
    if company_id:  # W31 리허설 마찰6: run에 제안사 프로필 선택 기록(run 파일 — pipeline_state 불변)
        company.save_selection(run, company_id)
        if not company.exists(company_id):
            print(f"[!] 회사 '{company_id}'의 profile.json이 아직 없다 — 선택은 기록됐다. "
                  f"`company --bundle --id {company_id}`로 인테이크를 시작하거나 `company --list`로 창고를 확인하라.")
    print(f"[START] {run}")
    print(f"- 모드: {args.mode}   입력: {kind}={ref}")
    print(f"- 공고 선택 출처: {selected_by}")
    if getattr(args, "gates", None):
        print(f"- 관문 프로파일: {args.gates}")
    if company_id:
        print(f"- 제안사 프로필 선택: {company_id}")
    if unspecified_notice:
        print("[!] 누가 골랐는지 기록되지 않음 — 사람 선별이면 `start --selected-by user`로 명시하라.")
    if copied_analysis:
        print(f"- 분석카드 자산 복제: {len(copied_analysis)}건 -> {run / 'analysis'}")
    print(pipeline_state.format_status(_run_state_view(run)))
    threshold_hint = archive.start_threshold_hint(RUNS)  # W31 리허설 마찰9: 접점 ④ — 임계 미만 침묵
    if threshold_hint:
        print(f"[안내] {threshold_hint}")
    return 0


def _ns(**kw: Any) -> argparse.Namespace:
    return argparse.Namespace(**kw)


def _redo_skeleton(run: Path) -> None:
    """W31(리허설 마찰2): 뼈대를 현재 message_map으로 재조립할 수 있게 단계를 다시 연다.

    스켈레톤 단계는 산출물(manifest_skeleton.json) 존재로 완료 판정된다(pipeline_state.mark).
    따라서 재조립의 유일한 통로가 '사람이 파일을 손으로 지우기'였다 — 리허설에서 실제로
    막힌 지점이다. 여기서 백업을 남기고 그 판정 근거만 치운다(파괴 없음).
    """
    backed: list[str] = []
    for name in ("skeleton.json", "manifest_skeleton.json"):
        src = run / name
        if src.is_file():
            src.replace(run / f"{name}.bak_redo")
            backed.append(f"{name} → {name}.bak_redo")
    state = pipeline_state.load(run)
    if (state.get("stages") or {}).pop("skeleton", None) is not None:
        cps = state.get("checkpoints") or {}
        if "skeleton_review" in cps:
            cps["skeleton_review"]["cleared_at"] = None  # 재조립분은 다시 사람이 본다
        pipeline_state.save(run, state)
    if backed:
        print(f"[REDO SKELETON] 보존: {' · '.join(backed)} — 현재 message_map으로 재조립한다.")
    else:
        print("[REDO SKELETON] 기존 스켈레톤이 없다 — 그냥 새로 조립한다.")


def _go_skeleton(run: Path, args: argparse.Namespace) -> bool:
    """W10: 탐색 루프의 시작 = 백지가 아니라 역제안. 표준 시나리오를 더미로 즉시 렌더한다(0토큰).

    반환 True = go가 여기서 1회 멈춘다 — 사용자가 완성 덱의 모양을 보고 구성을 빼고/고칠 틈.
    skeleton.json이 편집 UI(design_brief와 같은 패턴). 확정 후 다음 `go`가 채움 핸드오프로 간다.
    """
    scenario = skeleton.load_scenario(getattr(args, "scenario", None))
    state = pipeline_state.load(run)
    input_ref = (state.get("input") or {}).get("ref")
    project = f"[예시] {input_ref}" if input_ref else None
    # W16(결정 9①): message_map에 종속 — 있으면 축별 장표 그룹으로 조립(Level 1 의무 골격 +
    # Ⅳ.사업내용 축 그룹). 없으면(레거시·직접투입) 기존 시나리오 통짜 경로(바이트 동일).
    mm_doc = message_map.load(run)
    house_knowledge = getattr(args, "house_knowledge", None)
    doc = skeleton.build_skeleton(
        scenario, project=project, message_map_doc=mm_doc, house_knowledge=house_knowledge
    )
    skel_path = skeleton.write_skeleton(run, doc)
    # 스켈레톤을 storyline 입력으로 즉시 렌더(example=true → W9 라벨·태그·ship 경고 자동).
    render_run(_ns(
        run_dir=str(run), stage6=None, stage7=None, stage8=None, storyline=str(skel_path),
        project=None, pack=args.pack, pattern_sets=None, pptx=False, pptx_mode="native",
        skins=args.skins, analysis=None, rfp=None, anonymize_config=None, json=False,
        skeleton=True, scenario=scenario.get("id"),
    ))
    mode_tag = "축별 조립(message_map 종속)" if (doc.get("meta") or {}).get("message_driven") else "시나리오 통짜"
    print(f"[SKELETON] {skel_path} (시나리오={scenario.get('id')} · {mode_tag} · "
          f"슬라이드 {len(doc['slides'])}장 · 전부 예시)")
    return True


def bundle_message_map(run: Path, args: argparse.Namespace) -> Path:
    """W15(결정 9①): message_map 생성 핸드오프 프롬프트(결정론·0토큰).

    소스 = 브리프 문서(있으면) 또는 입력 참조(bid — 분석카드를 세션이 함께 참조) +
    스켈레톤 구조(있으면). LLM 호출은 여기서 하지 않는다(D4) — go가 이 프롬프트에서 멈춘다.
    """
    brief_path = run / "brief.md"
    if brief_path.is_file():
        source = f"[브리프 문서]\n{read_text(brief_path, 60000)}"
    else:
        state = pipeline_state.load(run)
        ref = (state.get("input") or {}).get("ref") or run.name
        source = (f"[입력 참조] {ref}\n"
                  "(브리프 문서가 없다 — 공고·분석카드 내용을 세션이 함께 참조해 메시지를 설계하라.)")
    skel = skeleton.load_skeleton(run)
    skeleton_block = skeleton.structure_block(skel) if skel else None
    institution_block = _institution_research_block(run)  # W26: 있으면 직인용 훅 동봉(없으면 바이트 불변)
    company_block = _company_profile_block(run)  # W31 리허설 마찰6: 있으면 자사 프로필 동봉(없으면 바이트 불변)
    master_design_block = _master_design_block(run)  # W31 R10 v2: 마스터 시안 확정 시만 동봉
    # ε패킷(2026-07-23): 기획 입구 지식 pull+보고 의무 — config 표 소비(knowledge_ledger).
    kc_profile = gates.load_config(run)["profile"]
    knowledge_pull_block = message_map.knowledge_pull_text(run, kc_profile)
    prompt = message_map.build_handoff_prompt(
        source_sections=source, skeleton_block=skeleton_block,
        institution_research_block=institution_block,
        company_profile_block=company_block,
        master_design_block=master_design_block,
        knowledge_pull_block=knowledge_pull_block,
    )
    out = message_map.prompt_path(run)
    write_text(out, _anonymize_bundle_text(run, prompt))
    return out


def _go_message_map_bundle(run: Path, args: argparse.Namespace) -> None:
    """W15: 메시지맵 핸드오프 번들(결정론). LLM 호출은 여기서 하지 않는다(D4)."""
    out = bundle_message_map(run, args)
    _record_state(run, "message_map_bundle", artifacts={"prompt": str(out)})
    print(f"[MESSAGE MAP BUNDLE] {out}")


def _go_message_map_collect(run: Path, args: argparse.Namespace) -> None:
    """W15: message_map.json 수거·검증. 구조 위반(governing 0/2+)만 **차단**, 나머지는 표면화.

    secure+enabled면 수거물을 원문 복원한다(익명화 왕복 대칭 — storyline 수거와 동일).
    """
    mp = message_map.map_path(run)
    if not mp.is_file():
        raise PipelineInputError(f"message_map.json 없음: {mp} (핸드오프 프롬프트 결과를 저장했는지 확인)")
    _restore_collected_file(run, mp)
    doc = message_map.load(run)
    if doc is None:
        raise PipelineInputError(f"message_map.json 파싱 실패(JSON 객체가 아님): {mp}")
    errors, warnings = message_map.validate(doc)
    if errors:  # 구조 위반만 차단 — 결정 7~8 문법(나머지는 경고로 표면화).
        raise PipelineInputError(
            "message_map 구조 위반(차단):\n  - " + "\n  - ".join(errors)
            + f"\n  {mp} 를 고치고 `go`를 다시 쳐라(governing_message는 정확히 1개)."
        )
    # ε패킷 안전장치①(2026-07-23): knowledge_used 블록 검증 — 없으면 수거 자체를 차단한다
    # (구조 위반과 같은 문법 — "사람 말 오류", SSOT 안전과 동일한 이유로 조용한 생략을 막는다).
    k_errors, k_warnings = knowledge_ledger.validate_knowledge_used(doc, "message_map")
    if k_errors:
        raise PipelineInputError(
            "message_map 지식 보고 검증 실패(차단):\n  - " + "\n  - ".join(k_errors)
            + f"\n  {mp} 의 knowledge_used를 채우고(빈 배열도 명시) `go`를 다시 쳐라."
        )
    knowledge_ledger.record(run, "message_map", doc.get("knowledge_used"), source_file=str(mp))
    block = message_map.gating_block(doc)
    _record_state(run, "message_map", artifacts={"map": str(mp)},
                  axes=block["axes"], governing_ok=block["governing_ok"],
                  slots=block["slots"], warnings=warnings)
    s = block["slots"]
    print(f"[MESSAGE MAP] {mp} — 축 {block['axes']}개 · "
          f"슬롯 filled={s['filled']}/example={s['example']}/empty={s['empty']}")
    for w in warnings:  # 축 개수·주어(P2.1)·슬롯 없음 등 — 경고만(차단 아님).
        print(f"  [!] {w}")
    for w in k_warnings:
        print(f"  [!] {w}")
    kc = knowledge_ledger.stage_counts(run, "message_map")
    print(f"  지식: 카드 {kc['cards']} · 웹 {kc['web']}건")
    if s["empty"]:  # status=empty → 근거 미확보(창작금지 대칭). 검토요망 계열로 표면화.
        print(f"  [검토요망] 근거 슬롯 {s['empty']}건이 empty — 실근거면 status=filled, 예시면 example로 채워라.")


def _go_storyline_bundle(run: Path, args: argparse.Namespace) -> None:
    out = bundle_storyline_from_brief(run, args)
    _record_state(run, "storyline_bundle", artifacts={"prompt": str(out)})


def _go_storyline_knowledge_check(run: Path) -> None:
    """ε패킷 안전장치①: storyline.json 수거 지점의 knowledge_used 검증+원장 기록.

    render_run 자체(저수준·재사용 함수 — stage6 레거시 입력·skeleton 더미 렌더·수많은
    단위 테스트가 직접 호출)는 건드리지 않는다 — 거기서 강제하면 이 패킷과 무관한 경로까지
    깨진다. 대신 go 오케스트레이션의 이 지점(_go_render, 실제 LLM이 채운 storyline.json을
    수거해 렌더하는 자리)에서만 검증한다 — message_map의 `_go_message_map_collect`와 대칭.
    """
    if _discover_run_json(run, "stage6") is not None:
        return  # 레거시 stage6 입력이 우선이면 storyline 지식 검증 대상이 아니다.
    try:
        path = _discover_run_json(run, "storyline")
    except PipelineInputError:
        return  # 다중 매치 등은 render_run이 표준 오류로 다시 판정하게 둔다(중복 표면화 방지).
    if path is None:
        return
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return  # 파싱 실패는 render_run이 표준 경로에서 다시 표면화한다.
    errors, warnings = knowledge_ledger.validate_knowledge_used(doc, "storyline")
    if errors:
        raise PipelineInputError(
            "storyline 지식 보고 검증 실패(차단):\n  - " + "\n  - ".join(errors)
            + f"\n  {path} 의 knowledge_used를 채우고(빈 배열도 명시) `go`를 다시 쳐라."
        )
    knowledge_ledger.record(run, "storyline", doc.get("knowledge_used") if isinstance(doc, dict) else None,
                             source_file=str(path))
    for w in warnings:
        print(f"[SURFACE] {w}")
    kc = knowledge_ledger.stage_counts(run, "storyline")
    print(f"[STORYLINE] 지식: 카드 {kc['cards']} · 웹 {kc['web']}건")
    _surface_internal_marks(doc)


# W32 마찰29 방어선: 프롬프트에서 축 표기 지시를 없앴어도(제거는 상류 수리) 이미 만들어진
# storyline이나 습관으로 남는 표기는 청중 장표에 그대로 조판된다. 자동 제거는 기존 덱 호환을
# 해칠 수 있어 **경고로만** 표면화한다(사람이 지우고 재렌더 — 시연 1차에서 실제로 그렇게 해소).
_INTERNAL_MARK_RE = re.compile(r"\(\s*axis\d+\s*(지지|support)?\s*\)")


def _surface_internal_marks(doc: object) -> None:
    """message/title에 남은 내부 표기(예: "(axis1 지지)")를 찾아 경고한다."""
    if not isinstance(doc, dict):
        return
    hits: list[str] = []
    for s in doc.get("slides") or []:
        if not isinstance(s, dict):
            continue
        for key in ("message", "title"):
            text = s.get(key)
            if isinstance(text, str) and _INTERNAL_MARK_RE.search(text):
                hits.append(f"장 {s.get('n', '?')} {key}: {text.strip()[:60]}")
    if hits:
        print("[SURFACE] 내부 표기가 청중용 문구에 남아 있다(축 추적은 supports_axis 필드가 전담 — "
              "심사위원이 보는 장표에 조판된다):")
        for h in hits:
            print(f"  - {h}")
        print("  → storyline.json에서 표기를 지우고 `go`를 다시 쳐라(supports_axis는 유지).")


def _go_render(run: Path, args: argparse.Namespace) -> None:
    _go_storyline_knowledge_check(run)
    render_run(_ns(
        run_dir=str(run), stage6=None, stage7=None, stage8=None, storyline=None, project=None,
        pack=args.pack, pattern_sets=None, pptx=False, pptx_mode="native",
        skins=args.skins, analysis=args.analysis, rfp=args.rfp, anonymize_config=None, json=False,
    ))


def _go_design_brief(run: Path, args: argparse.Namespace) -> bool:
    """의사결정 게이트 산출물(W3a). 반환값 True = go가 여기서 멈춰야 한다(W7-C3).

    브리핑을 **방금 만들었다면** 사람이 파일을 볼 틈 없이 stage9 번들까지 관통하면 안 된다
    ("파일 수정이 편집 UI" 계약). 이미 있던 브리핑(사람 편집본)은 멈추지 않는다 — 멱등.
    """
    path, brief, created = build_design_brief(run, args)
    _plan = brief.get("image_slots_plan") or {}
    _record_state(run, "design_brief", artifacts={"brief": str(path)},
                  created=created, output_mode=(brief.get("output_mode") or {}).get("value"),
                  image_slots_planned=len(_plan.get("slots") or []),
                  background_candidates=len(_plan.get("background_candidates") or []))
    # 콘솔 출력은 cp949-안전 문자만(em-dash 금지 — 기본 Windows 콘솔에서 UnicodeEncodeError).
    print(f"[BRIEF] {path} {'(생성)' if created else '(기존 보존 - 사람 편집본)'}")
    print(f"  {design_brief.summary(brief)}")
    print("  이 파일을 직접 수정하는 것이 편집 UI다. 수정 후 `go`를 다시 치면 [4] 디자인 입히기(코드명 stage9)가 소비한다.")
    return created


def _go_design_contract(run: Path, args: argparse.Namespace) -> None:
    """W31 R2·R5(B1 테마 확정): design_brief 직후·(이미지|stage9) 번들 전 — run별 디자인 계약 동결.

    결정론(LLM 미호출) — [중립 템플릿 skins/_neutral.json] 위에 [design_brief.skin.value가
    가리키는 차용 스킨]을 딥머지(대체 아님 — 마찰15)하고 run 조정을 병합해 `run/design_contract.json`
    을 만든다(용어 정의: 차용 없으면 중립 그대로). 구조 키(canvas/export)가 없으면
    `DesignContractError`를 `PipelineInputError`로 감싸 사람 말 오류로 중단시킨다.
    이미 있으면 보존(design_brief와 같은 "편집 UI" 계열 — 사람이 chrome/image_contract를 직접
    손봤을 수 있다). 이 뒤에 오는 theme_confirm 게이트가 확인·건너뛰기를 담당한다(R3).
    브리핑을 고친 뒤 다시 동결하려면(계약이 이미 있어 보존되므로) `go --refreeze-contract`를
    쓴다(마찰14 ④ — `_refreeze_contract`).
    """
    if design_contract.exists(run):
        contract = design_contract.load(run) or {}
        created = False
    else:
        brief = design_brief.load(run) or {}
        try:
            contract = design_contract.build(run, brief=brief, skins_dir=SKINS_DIR)
        except design_contract.DesignContractError as exc:
            raise PipelineInputError(str(exc)) from exc
        design_contract.save(run, contract)
        created = True
    _record_state(run, "design_contract", artifacts={"contract": str(design_contract.path(run))},
                  source=(contract.get("meta") or {}).get("source"), created=created)
    print(f"[DESIGN_CONTRACT] {design_contract.path(run)} {'(생성)' if created else '(기존 보존 - 사람 편집본)'}")
    print(f"  {design_contract.summary(contract)}")


def _refreeze_downstream_notice(run: Path) -> None:
    """W31 마찰18 ⒜: 재동결 후 이 run이 이미 하류(이미지 번들 등)를 지났으면 재적용 순서를
    안내한다(경고만 — 진행을 막지 않는다). `_past_theme_gate`(pipeline_state._next_step)와
    같은 단계 목록(DOWNSTREAM_OF_THEME_STAGES)을 공유한다 — "재동결 통로는 열려 있는데 하류
    재적용 안내가 없다"는 잔여 실결함의 수리(CONTEXT/REHEARSAL_FRICTIONS_W31.md #18)."""
    state = pipeline_state.load(run)
    stages = state.get("stages") or {}
    hit = [s for s in pipeline_state.DOWNSTREAM_OF_THEME_STAGES if s in stages]
    if not hit:
        return
    if any(s.startswith("imagedeck") for s in hit):
        print("[REFREEZE] 이 run은 이미 이미지 단계를 지났다 - 새 계약 반영: "
              "imagedeck --bundle 재실행(→produce→collect→compose)")
    else:
        print(f"[REFREEZE] 이 run은 이미 하류 단계({', '.join(hit)})를 지났다 - "
              "새 계약을 반영하려면 해당 단계를 재실행하라(예: stage9 --bundle 재실행).")


def _refreeze_contract(run: Path) -> None:
    """W31 마찰14 ④ 재동결 통로: design_brief.json이 계약보다 새로워졌을 때 다시 얼린다.

    기존 `design_contract.json`을 `design_contract.prev.json`으로 보존(덮어씀 — 최근 1세대만
    보관)하고 현재 브리핑으로 재생성한다. theme_confirm 관문은 수동 리셋이 필요 없다 —
    `HUMAN_CHECKPOINT_WATCH["theme_confirm"]`이 `design_contract.json`의 mtime을 지켜보므로
    (pipeline_state._next_step의 `cleared()`), 재동결로 파일이 새로 쓰이는 순간 다음 상태 판정이
    자동으로 "[재무장] 확정 이후 산출물 변경" 사유를 표면화한다(wireframe_review와 동일 관례).

    W31 마찰18 ⒜: 재동결 통로 자체는 이미 열려 있었다(게이트 가드를 타지 않는다) — 잔여 실결함은
    재동결 **후** 하류(이미지 번들 등)가 이미 진행된 run에 재적용 순서를 안내하지 않던 것이었다.
    `_refreeze_downstream_notice`가 그 안내를 담당한다.
    """
    old = design_contract.path(run)
    if old.is_file():
        prev = run / "design_contract.prev.json"
        old.replace(prev)
        print(f"[REFREEZE] 기존 계약 보존: {prev.name}")
    else:
        print("[REFREEZE] 기존 계약이 없다 — 그냥 새로 동결한다.")
    brief = design_brief.load(run) or {}
    try:
        contract = design_contract.build(run, brief=brief, skins_dir=SKINS_DIR)
    except design_contract.DesignContractError as exc:
        raise PipelineInputError(str(exc)) from exc
    design_contract.save(run, contract)
    _record_state(run, "design_contract", artifacts={"contract": str(design_contract.path(run))},
                  source=(contract.get("meta") or {}).get("source"), created=True, refrozen=True)
    print(f"[REFREEZE] 재동결 완료: {design_contract.path(run)} "
          "(theme_confirm 관문이 다음 판정에서 재무장된다)")
    print(f"  {design_contract.summary(contract)}")
    _refreeze_downstream_notice(run)


def _contract_stale_warning(run: Path) -> None:
    """W31 마찰14 ④: design_brief.json이 동결된 계약보다 새로우면 재동결을 안내한다(경고만 —
    진행을 막지 않는다. 계약 소비는 여전히 동결 시점 스냅샷이라는 사실을 표면화하는 목적)."""
    if not design_contract.exists(run):
        return
    brief_path = design_brief.brief_path(run)
    if not brief_path.is_file():
        return
    contract = design_contract.load(run) or {}
    frozen_at = (contract.get("meta") or {}).get("frozen_at")
    if not frozen_at:
        return
    try:
        frozen_stamp = dt.datetime.fromisoformat(frozen_at)
        # frozen_at은 초 단위(design_contract._now())라 브리핑 mtime의 마이크로초를 그대로 비교하면
        # "같은 초 안에서 계약이 브리핑보다 나중에 저장됐는데도 stale로 오판"할 수 있다 — 마이크로초를
        # 잘라 같은 정밀도로 맞춘다(같은 초 = stale 아님, 다음 초부터만 stale).
        brief_mtime = dt.datetime.fromtimestamp(brief_path.stat().st_mtime).replace(microsecond=0)
    except (ValueError, OSError):
        return
    if brief_mtime > frozen_stamp:
        print("[GO 경고] 계약 stale — 브리핑이 더 새로움. 재동결: go --refreeze-contract")


def _sync_resolutions(run: Path) -> tuple[Path, dict, int, int]:
    """해소지 골격 생성/갱신(멱등·기존 보존). deck.json이 있어야 태그를 셀 수 있다."""
    deck_path = run / "deck.json"
    if not deck_path.exists():
        raise PipelineInputError(f"deck.json 없음: {deck_path} (먼저 render 실행)")
    deck = json.loads(deck_path.read_text(encoding="utf-8"))
    return review_resolve.sync(run, deck)


def _go_resolution_skeleton(run: Path) -> None:
    """체크포인트 ②(§3.0) 정지 시 — 검토요망 전체를 해소지 골격으로 노출한다."""
    try:
        path, doc, added, _ = _sync_resolutions(run)
    except PipelineInputError:
        return
    pending = sum(1 for i in doc["items"] if not i.get("decision") and not i.get("stale"))
    print(f"[RESOLVE] {path} (신규 {added}건 · 미결 {pending}건)")
    print("  이 파일의 decision을 채우는 것이 편집 UI다 — 비워두면 태그는 유지된다(코드는 임의로 안 지운다).")


def _go_review_resolve(run: Path, args: argparse.Namespace) -> None:
    """W5: 해소지의 **결정된 항목만** 덱에 반영 → 증분 재렌더(태그 제거·사실 기입은 render_run 안에서).

    재렌더이므로 deck.html은 override 미반영본으로 돌아간다 — 그 사실은 상태머신이
    "stage9 적용 후 render 재실행" 경고/다음 단계로 이미 표면화한다(중복 게이트 만들지 않는다).
    """
    path, doc, added, stamped = _sync_resolutions(run)
    if stamped:
        print(f"[RESOLVE] 결정 기록 시각 각인 {stamped}건 → {path}")
    _go_render(run, args)                       # ← render_run이 review_resolutions.json을 소비한다
    gate = _gating(run)
    res = gate.get("review_resolution") or {}
    _record_state(run, "review_resolve", artifacts={"resolutions": str(path)},
                  items_total=res.get("items_total", len(doc["items"])),
                  resolved=res.get("resolved", 0),
                  tags_removed=res.get("tags_removed", 0),
                  review_needed_total=gate.get("review_needed_total"))
    print(f"[RESOLVE] 잔존 검토요망 {gate.get('review_needed_total')}건 "
          f"(해소 {res.get('resolved', 0)} · 보류 {res.get('deferred', 0)} · 미결 {res.get('pending', 0)})")


def _go_deck_review_bundle(run: Path, args: argparse.Namespace) -> None:
    """W3c: 승인 전 평가 프롬프트(결정론). LLM 호출은 여기서 하지 않는다(D4)."""
    out = bundle_deck_review(run, args)
    _record_state(run, "deck_review_bundle", artifacts={"prompt": str(out)})
    print(f"[REVIEW BUNDLE] {out}")


def _go_deck_review_collect(run: Path, args: argparse.Namespace) -> None:
    rep = collect_deck_review(run)
    _record_state(run, "deck_review", artifacts={"review": rep["path"]},
                  verdict=rep["verdict"], chars=rep["chars"])
    print(f"[REVIEW] {rep['path']} verdict={rep['verdict']} chars={rep['chars']}")
    print("  평가는 판단 자료다 — 승인은 사람이 디자인 게이트에서 결정한다(차단하지 않는다).")


def _go_stage9(run: Path, args: argparse.Namespace, *, apply: bool) -> None:
    stage9_cmd(_ns(
        run_dir=str(run), slides=None, design_guide=args.design_guide, pack=args.pack,
        apply=apply, fill_images=False, no_generate=False, overrides=None, json=False,
        skins=getattr(args, "skins", None),
    ))


def _go_wireframe(run: Path, args: argparse.Namespace, *, apply: bool) -> None:
    """W21 [3] 뼈대 잡기 go 편입 — 기존 wireframe_cmd 재사용(중복구현 금지).

    bundle: frame×piece 결정 프롬프트만 만들고 정지(go는 이후 wireframe.json llm 핸드오프에서 멈춘다).
    apply : wireframe.json 검증→deck 병합→무채 재렌더→재게이트. 결과 요약을 go 층에서 가시화한다.
    """
    wireframe_cmd(_ns(
        run_dir=str(run), bundle=not apply, wf_apply=apply, file=None,
        pack=args.pack, skins=getattr(args, "skins", None),
    ))
    if apply:  # 가시화(핵심 요청): 재조판·조합·catalog_gap 요약 + 덱 프리뷰 경로.
        wf = _gating(run).get("wireframe") or {}
        stats = wf.get("stats") or {}
        gap = len(wf.get("catalog_gap") or [])
        print(f"  [결과] 재조판 {stats.get('slides_in_wireframe')}장 · 조합 {stats.get('unique_combos')}종 "
              f"· catalog_gap {gap}건")
        print(f"  덱 미리보기: {run / 'deck.html'}")
        # 미해결 어휘 갭은 status 경고(§5-④-①)가 이미 표면화한다 — 여기서 중복 안 함.


def _go_refine_bundle(run: Path, args: argparse.Namespace) -> None:
    """W23 [4+] 디자인 고도화 - 목표 명세 프롬프트(결정론). 기존 refine_cmd 재사용."""
    refine_cmd(_ns(run_dir=str(run), bundle=True, collect=False, handoff=False, file=None))


def _go_refine_collect(run: Path, args: argparse.Namespace) -> bool:
    """W23 [4+] 명세 검증·레퍼런스 수집 → **1회 정지**(사람이 design_spec·design_refs 검토).

    반환 True = go가 여기서 멈춘다(skeleton 역제안·브리핑 신규 생성과 동일 메커니즘).
    완성 디자인보다 먼저, 값싸게 고칠 틈을 준다(결정 17).
    """
    refine_cmd(_ns(run_dir=str(run), bundle=False, collect=True, handoff=False, file=None))
    st = (pipeline_state.load(run).get("stages") or {}).get("refine_collect") or {}
    print(f"  [결과] 명세 {st.get('slides_spec')}장 · 레퍼런스 {st.get('refs')}건 "
          f"· catalog_gap {st.get('catalog_gap')}건 · content_gap {st.get('content_gaps')}건")
    # 정지는 design_refs 선택 관문이 담당한다(B — go --confirm으로만 통과, 무심코 안 지나감).
    # 여기서 return True(소프트 정지)를 하면 `go` 재실행에 그냥 밀려버린다(정주행 스킵의 원인).
    return False


def _go_imagedeck_bundle(run: Path, args: argparse.Namespace) -> None:
    """W28 [이미지] 장별 프롬프트 번들 — go 편입. wireframe_mode는 render_route.json에서."""
    _, wf_mode = pipeline_state.render_route(run)
    imagedeck_cmd(_ns(run=str(run), bundle=True, collect=False, compose=False,
                      skin=None, wireframe_mode=wf_mode, ref=None, ab=None))


def _go_imagedeck_collect(run: Path, args: argparse.Namespace) -> None:
    """W28 [이미지] 생산 이미지 수거 검증(px 실측). 불합격도 기록 — 정지는 _next_step이 판단."""
    imagedeck_cmd(_ns(run=str(run), bundle=False, collect=True, compose=False,
                      skin=None, wireframe_mode="auto", ref=None, ab=None))
    # ε패킷 — KC③(산출 출구) 검수는 선택이라(MANUAL "바로 정독·채택"도 유효) 누락을 차단하지
    # 않는다(soft). 사람이 이미 imagedeck_review.md의 '지식 사용 기록'을 채웠으면 여기서 수거한다
    # — go를 다시 칠 때마다 idempotent하게 재시도(파일 없거나 비어 있으면 조용히 지나간다).
    review = imagedeck.collect_review_knowledge(run)
    if review.get("errors"):
        raise PipelineInputError(
            "imagedeck_review 지식 보고 검증 실패(차단):\n  - " + "\n  - ".join(review["errors"])
            + f"\n  {run / imagedeck.REVIEW_MD} 의 '지식 사용 기록'을 고치고 `go`를 다시 쳐라."
        )
    if review.get("recorded"):
        kc = knowledge_ledger.stage_counts(run, "imagedeck_review")
        print(f"[IMAGEDECK REVIEW] 지식 사용 기록 수거: 카드 {kc['cards']} · 웹 {kc['web']}건")


def _go_imagedeck_compose(run: Path, args: argparse.Namespace) -> None:
    """W28 [이미지] 승인 이미지 + HTML 크롬 조합 → deck.images.html."""
    imagedeck_cmd(_ns(run=str(run), bundle=False, collect=False, compose=True,
                      skin=None, wireframe_mode="auto", ref=None, ab=None))


def _go_refine_handoff(run: Path, args: argparse.Namespace) -> bool:
    """W23 [4+] 실행 핸드오프 프롬프트(결정론) → 정지. 산출물 회수는 기존 채널(stage9 --apply / approve --ingest).

    반환 True = go가 여기서 멈춘다 — 사람이 핸드오프를 실행자(Claude Design 등)에게 전달할 틈.
    """
    refine_cmd(_ns(run_dir=str(run), bundle=False, collect=False, handoff=True, file=None))
    return True


# W24(결정 15 보완): ✋② 동결 게이트 안내에 붙는 downstream 예고 1줄 — 동결이 "끝"으로
# 읽히지 않게 남은 공정을 예고한다(콘솔 출력 규율: em-dash 금지, cp949-안전 문자만).
_DOWNSTREAM_NOTICE = ("이후 남은 단계: [3]뼈대 잡기 > [4]디자인 입히기 > [4+]디자인 고도화 > [5]마무리·검토 "
                      "(동결=방향·메시지 확정이지, 시각 완성이 아니다 - 디자인은 뒤에서 계속 좋아진다)")


def go_cmd(args: argparse.Namespace) -> int:
    """다음 체크포인트까지 자동 진행. 멱등(완료 단계는 건너뜀). 멈추면 이유 + 할 일을 출력한다.

    **go는 LLM을 호출하지 않는다.** 결정론 단계만 실행하고, LLM 산출물이 필요한 지점에서 멈춰
    핸드오프를 출력한다 — secure 모드에서는 복붙 왕복(프롬프트 경로 → 붙여넣을 경로),
    direct 모드에서는 세션 LLM/Codex 호출 지시. 지도는 동일하고 핸드오프 문구만 다르다.
    """
    run = _render_run_dir(args.run, must_exist=True)

    if getattr(args, "gates", None):  # W31 리허설 마찰2: 중도 프로파일 변경 → gates.json에 지속
        gates.save_config(run, profile=args.gates)
        print(f"[GO] 관문 프로파일 변경: {args.gates}")

    if getattr(args, "redo_skeleton", False):
        _redo_skeleton(run)

    if getattr(args, "refreeze_contract", False):  # W31 마찰14 ④
        _refreeze_contract(run)
    else:
        _contract_stale_warning(run)

    if args.confirm:
        view = _run_state_view(run)
        step = view["next"]
        if step["kind"] != "checkpoint":
            print(f"[GO] --confirm: 지금 대기 중인 체크포인트가 없다 (현재: {step['kind']}).", file=sys.stderr)
        else:
            cp = step["checkpoint"]
            if pipeline_state.is_human(cp):
                label = pipeline_state.CHECKPOINT_LABEL[cp]
                print(
                    f"[GO 거부] '{label}'은 사람 전속 관문 — "
                    "대시보드(http://127.0.0.1:8754)에서 검토/건너뛰기를 눌러라. "
                    "--confirm은 이 관문에 무효.",
                    file=sys.stderr,
                )
                return 2
            pipeline_state.clear_checkpoint(run, cp)
            if cp in pipeline_state.OPTIONAL_CHECKPOINTS:
                print(f"[GO] 선택 관문 건너뜀(또는 완료): {pipeline_state.CHECKPOINT_LABEL[cp]}")
            else:
                print(f"[GO] 체크포인트 통과: {pipeline_state.CHECKPOINT_LABEL[cp]}")
            if cp == "decision":
                print(f"  {_DOWNSTREAM_NOTICE}")

    # 승인은 `ship`의 몫이다 — go는 approve를 실행하지 않는다(디자인 게이트에서 멈춘다).
    executors = {
        "skeleton": lambda: _go_skeleton(run, args),
        "message_map_bundle": lambda: _go_message_map_bundle(run, args),
        "message_map": lambda: _go_message_map_collect(run, args),
        "storyline_bundle": lambda: _go_storyline_bundle(run, args),
        "render": lambda: _go_render(run, args),
        "design_brief": lambda: _go_design_brief(run, args),
        "design_contract": lambda: _go_design_contract(run, args),
        "review_resolve": lambda: _go_review_resolve(run, args),
        # W21 [3] 뼈대 잡기 — bundle은 프롬프트만(정지=wireframe.json llm 핸드오프), apply는 병합·재렌더.
        "wireframe_bundle": lambda: _go_wireframe(run, args, apply=False),
        "wireframe_apply": lambda: _go_wireframe(run, args, apply=True),
        "stage9_bundle": lambda: _go_stage9(run, args, apply=False),
        "stage9_apply": lambda: _go_stage9(run, args, apply=True),
        # W23 [4+] 디자인 고도화 — collect·handoff는 1회 정지(return True)로 사람 검토·전달 틈을 준다.
        "refine_bundle": lambda: _go_refine_bundle(run, args),
        "refine_collect": lambda: _go_refine_collect(run, args),
        "refine_handoff": lambda: _go_refine_handoff(run, args),
        # W28 [이미지] 라우트 — bundle/collect/compose. 정지는 _next_step(llm/checkpoint)이 판단.
        "imagedeck_bundle": lambda: _go_imagedeck_bundle(run, args),
        "imagedeck_collect": lambda: _go_imagedeck_collect(run, args),
        "imagedeck_compose": lambda: _go_imagedeck_compose(run, args),
        "deck_review_bundle": lambda: _go_deck_review_bundle(run, args),
        "deck_review": lambda: _go_deck_review_collect(run, args),
    }

    paused_stage: str | None = None
    for _ in range(len(pipeline_state.STAGE_ORDER) + 2):  # 진행 보장 + 무한루프 방지
        view = _run_state_view(run)
        step = view["next"]
        if step["kind"] == "checkpoint" and pipeline_state.is_human(step["checkpoint"]):
            gate = step["checkpoint"]
            # W31 리허설 마찰4: journey 폴더의 검토_체크.md도 대시보드 버튼과 동등한 채널이다 —
            # [x]+라운드 토큰 일치를 확인해 아직 사람 ack가 없을 때만 승격한다("먼저 온 쪽이 이김").
            try:
                journey_check.collect_ack(run, gate)
                # W32 마찰32⒝: 인식 불가 체크 표기는 조용히 무시하지 않는다 — 사람은 체크했다고
                # 믿는데 go는 "ack 없음"만 반복하므로 스스로 원인을 알 수 없다(실측: go 2회 무반응).
                _chk = journey_check.read(run, gate)
                for _mark in (_chk or {}).get("unknown_marks") or []:
                    print(f"[SURFACE] 검토_체크에 인식 불가 표기: '{_mark}' - [x]로 고쳐라 "
                          f"(빈칸은 [ ], 체크는 [x]. 대소문자/앞뒤 공백은 허용된다)")
            except Exception as exc:  # pragma: no cover - 안내 채널, 파이프라인을 막지 않는다
                print(f"[WARN] journey_check 수거 실패({gate}): {exc}", file=sys.stderr)
            ack = pipeline_state.read_ack(run, gate)
            if ack is not None:
                changed = pipeline_state.is_stale(run, gate, ack["at"])
                if changed:
                    print(f"[GO 대기] waiting_human:{gate} (ack가 산출물 변경보다 오래됨 - 재검토 필요)")
                    break
                pipeline_state.clear_checkpoint(run, gate)
                print(f"[GO] ack 확인: {gate} decision={ack['decision']} via={ack.get('via', 'dashboard')}")
                continue
            # W31 리허설 마찰2: 사람 ack가 없을 때만 관문 다이얼을 본다(대시보드의 사람 결정이
            # 언제나 우선 — 이미 사람이 확인했다면 위 분기에서 이미 처리되고 여기 오지 않는다).
            if gate in gates.GATE_IDS:
                gd = gates.decide(run, gate)
                if gd["action"] == "auto_pass":
                    gates.write_auto_ack(run, gate, gd)
                    pipeline_state.clear_checkpoint(run, gate)
                    print(f"[GO] 자동 통과(프로파일={gd['profile']}): "
                          f"{pipeline_state.CHECKPOINT_LABEL[gate]} — {gd['reason']}")
                    continue
        if step["kind"] != "command" or step["stage"] not in executors:
            break
        stage = step["stage"]
        print(f"[GO] {pipeline_state.STAGE_LABEL[stage]} …")
        # W10 스켈레톤 역제안 / W7-C3 브리핑 신규 생성 — 사람이 파일을 볼 틈을 위해 1회 정지한다.
        if executors[stage]() is True:
            paused_stage = stage
            break
    else:
        print("[GO] 진행 한도 도달 — status로 확인하라.", file=sys.stderr)

    view = _run_state_view(run)
    step = view["next"]
    # 체크포인트 ②(§3.0): flag도 "이 한 화면에서" 처리한다 — 해소지를 여기서 만들어 노출한다.
    if step["kind"] == "checkpoint" and step["checkpoint"] == "decision":
        _go_resolution_skeleton(run)

    # W31 R7: 단계 폴더 여정 — 산출물이 생긴 폴더를 열고 파생 뷰(R1)를 갱신한다. 기록 실패가
    # 본 공정을 막지 않는다(journey_folders는 안내 층이지 파이프라인 계약이 아니다).
    try:
        journey_report = journey_folders.sync(run)
        if journey_report.get("newly_opened"):
            print(f"[JOURNEY] 새 폴더: {', '.join(journey_report['newly_opened'])}")
        if journey_report.get("views_rendered"):
            print(f"[JOURNEY] 가독 뷰 갱신: {', '.join(journey_report['views_rendered'])}")
        if journey_report.get("meeting_notes_created"):
            print(f"[JOURNEY] 회의체 메모 신설(최초 1회): {', '.join(journey_report['meeting_notes_created'])}")
    except Exception as exc:  # pragma: no cover - 안내 층, 파이프라인을 막지 않는다
        print(f"[WARN] journey 폴더 동기화 실패: {exc}", file=sys.stderr)

    # W31 리허설 마찰4: 지금 사람이 멈춰 있는 관문의 journey 폴더에 검토_체크.md를 발급/갱신한다
    # (journey_folders.sync 이후라 폴더가 이미 열려 있다). 실패해도 본 공정을 막지 않는다.
    if step["kind"] == "checkpoint" and pipeline_state.is_human(step["checkpoint"]):
        try:
            check_path = journey_check.issue(run, step["checkpoint"])
            if check_path:
                print(f"[JOURNEY] 검토_체크 발급/갱신: {check_path}")
        except Exception as exc:  # pragma: no cover - 안내 층, 파이프라인을 막지 않는다
            print(f"[WARN] journey_check 발급 실패: {exc}", file=sys.stderr)

    if args.json:
        print(json.dumps(view, ensure_ascii=False, indent=2))
        return 0

    print()
    print(pipeline_state.format_status(view))
    if paused_stage == "skeleton":
        # W10 역제안 정지 — "이 구성을 보고 뺄 장표/바꿀 장표를 정하라"로 멈춘다.
        # (콘솔 출력은 cp949-안전 문자만 — em-dash 금지. 기존 _go_design_brief와 같은 규율.)
        print(f"\n[GO 정지] 표준 시나리오 스켈레톤을 역제안했다: 전 장표를 예시 데이터로 즉시 렌더했다(0토큰).")
        print(f"  덱 미리보기: {run / 'deck.html'}")
        print(f"  구성 편집(편집 UI): {skeleton.skeleton_path(run)}  · 뺄 장표는 슬라이드를 지우고, 바꿀 장표는 template_id/section을 고쳐라.")
        print("  이 구성을 보고 뺄 장표/바꿀 장표를 정하라. 확정되면 `go`를 다시 쳐라.")
        print("  다음 `go`는 확정된 스켈레톤 구조를 LLM이 채우도록 핸드오프한다(백지 창작이 아니라 구조 채우기).")
    elif paused_stage == "design_brief":
        print(f"\n[GO 정지] {design_brief.brief_path(run)} 을 검토·수정하라. 다음 `go`가 소비한다.")
        print("  (수정 없이 그대로 진행하려면 그냥 `go`를 다시 쳐라 — 브리핑은 기본값으로 확정된다.)")
        print(f"  {_DOWNSTREAM_NOTICE}")
    elif paused_stage == "refine_collect":
        # W23 [4+] 명세 검토 정지 — 완성 디자인보다 먼저, 값싸게 고칠 틈(결정 17).
        print(f"\n[GO 정지] 디자인 고도화 명세·레퍼런스를 검토하라(완성 디자인보다 먼저·값싸게).")
        print(f"  명세 편집(편집 UI): {run / 'design_spec.json'}")
        print(f"  레퍼런스: {run / 'design_refs'}")
        print("  검토·조정 후 `go`를 다시 치면 [4+] 실행 핸드오프를 생성한다.")
    elif paused_stage == "refine_handoff":
        # W23 [4+] 실행 핸드오프 정지 — 산출물 회수는 기존 채널(stage9 --apply / approve --ingest).
        print(f"\n[GO 정지] 디자인 고도화 실행 핸드오프를 생성했다: {run / 'refine_handoff' / 'prompt.md'}")
        print("  실행자(Claude Design 등)에 전달하고, 산출물은 (A) design_overrides.json 확장 후 "
              "`stage9 --apply` 또는 (B) 완성 HTML을 `approve --ingest`로 회수하라.")
        print("  고도화를 건너뛰고 평가로 진행하려면 그냥 `go`를 다시 쳐라(핸드오프는 선택적 정련이다).")
    elif step["kind"] == "llm":
        print(f"\n[GO 정지] LLM 산출물 필요 ({step['handoff']} 모드)")
    elif step["kind"] == "checkpoint":
        if pipeline_state.is_human(step["checkpoint"]):
            print(f"[GO 대기] waiting_human:{step['checkpoint']}")
        print(f"\n[GO 정지] 사람 결정 필요 — {pipeline_state.CHECKPOINT_LABEL[step['checkpoint']]}")
        # decision 게이트의 downstream 예고는 status의 "## 다음" why에 이미 실려 있다(중복 출력 안 함).
        for path in step.get("review", []):
            print(f"  검토: {path}")
    return 0


def ship_cmd(args: argparse.Namespace) -> int:
    """승인 + 산출물 확정. `--pptx`는 여기서만."""
    run = _render_run_dir(args.run, must_exist=True)
    view = _run_state_view(run)
    if "render" not in view["stages"]:
        raise PipelineInputError(f"렌더 산출물이 없다 — 먼저 `go --run {run.name}`")
    _require_human_ack(run, "design")

    # W5: 잔존 검토요망은 **차단하지 않는다** — 경고로 표면화한다(근거 없는 콘텐츠를 사람이 알고 내보낸다).
    residual = pipeline_state.review_needed_total(run)
    if residual:
        res = (_gating(run).get("review_resolution") or {})
        print(f"[SHIP 경고] 검토요망 {residual}건이 남은 채 승인한다 "
              f"(해소 {res.get('resolved', 0)} · 보류 {res.get('deferred', 0)} · 미결 {res.get('pending', 0)}) "
              f"— {review_resolve.resolutions_path(run)}", file=sys.stderr)

    # W9 안전장치 ③: 잔존 예시 데이터도 **차단하지 않고** 경고한다(실데이터 미교체를 사람이 알고 내보낸다).
    _ex_slides = (_gating(run).get("example_slides") or [])
    if _ex_slides:
        print(f"[SHIP 경고] 예시 데이터 {len(_ex_slides)}건이 실데이터로 교체되지 않은 채 승인한다 "
              f"(슬라이드 {_ex_slides}) · 해소지의 해당 태그를 fact_supplied로 교체하면 예시 마크가 사라진다: "
              f"{review_resolve.resolutions_path(run)}", file=sys.stderr)

    if not view["checkpoints"].get("design", {}).get("cleared_at"):
        # 승인 전 평가(§6 결정 3)는 **판단 자료**다 — 없으면 경고하되 차단하지 않는다(게이트 철학).
        if "deck_review" not in view["stages"]:
            print("[SHIP 경고] deck_review.md 없이 승인한다 — 디자인 게이트의 판단 자료가 없다. "
                  f"평가를 원하면 `go --run {run.name}` 후 다시 ship.", file=sys.stderr)

    # W27 D6·D7: 이미지 수급 표면화 — 차단하지 않는다(W5와 같은 문법. 사람이 알고 내보낸다).
    for w in _image_provenance_ship_warnings(_gating(run)):
        print(f"[SHIP 경고] {w}", file=sys.stderr)

    rc = approve_cmd(_ns(run_dir=str(run), ingest=args.ingest, source=args.source))
    if rc != 0:
        return rc

    if args.pptx:
        _route, _ = pipeline_state.render_route(run)
        if _route == "image_infographic" and args.pptx_mode != "image":
            # W30 정본(사용자 결정 2026-07-20): image 라우트의 기본 pptx = 하이브리드
            # (크롬·표지·목차·간지 = 네이티브 수정 가능, 본문 = 이미지). 전량 픽셀본이
            # 필요할 때만 --pptx-mode image로 종전 래스터 경로를 쓴다.
            rep = imagedeck.compose_pptx(run)
            shutil.copyfile(rep["out"], run / "deck.pptx")
            print(f"[PPTX·hybrid] {run / 'deck.pptx'} 장={rep['slides']} "
                  f"이미지={rep['images_used']} 네이티브={rep['html_native']} (정본 - 크롬 수정 가능)")
            if rep["missing"]:
                print(f"  [주의] 이미지 누락 {len(rep['missing'])}건: {rep['missing']}")
            _record_state(run, "approve",
                          artifacts={"approval": str(run / "approval.json"),
                                     "pptx": str(run / "deck.pptx")},
                          surface="static" if not args.ingest else "claude-design",
                          pptx_mode="hybrid_imagedeck")
        elif args.pptx_mode == "image":
            # W4(S6-2 본체): 승인된 HTML의 슬라이드별 스크린샷을 그대로 조립한다 —
            # deck.json에서 add_specs로 재렌더하지 않는다(그러면 승인 후 override가
            # 다시 반영 안 된 HTML을 찍게 된다).
            rep = _ship_pptx_image(run, view)
            print(f"[PPTX·image] {rep['out']} slides={rep['slides']} source={rep['source_html']}")
            for w in rep["warnings"]:
                print(f"  [주의] {w}")
            _record_state(run, "approve", artifacts={"approval": str(run / "approval.json"), "pptx": rep["out"]},
                          surface="static" if not args.ingest else "claude-design", pptx_mode=args.pptx_mode)
        else:
            # PPTX는 승인된 deck.json의 파생물(N5). deck.html은 건드리지 않는다 —
            # render를 다시 부르면 stage9 override가 조용히 날아간다.
            deck = json.loads((run / "deck.json").read_text(encoding="utf-8"))
            *_, add_specs, _render_html = _app_modules()
            rendered = view["stages"]["render"]
            skins = rendered.get("skins") or None
            pack = rendered.get("pack", "house_a")
            rep = add_specs(deck, pack, run / "deck.pptx", skins=skins, mode=args.pptx_mode)
            print(f"[PPTX] {rep['out']} warnings={len(rep['warnings'])}")
            print("  [주의] pptx는 [4] 디자인 입히기(코드명 stage9) override·image_slots를 지원하지 않는다(add_specs 시그니처가 근거).")
            _record_state(run, "approve", artifacts={"approval": str(run / "approval.json"), "pptx": rep["out"]},
                          surface="static" if not args.ingest else "claude-design", pptx_mode=args.pptx_mode)

    print()
    print(pipeline_state.format_status(_run_state_view(run)))
    print(archive.hint_line(run))  # W31 리허설 마찰9: 완료 후 접점 ① — 안내만, 실행 강제 아님
    return 0


def _imagedeck_refs(run: Path, args: argparse.Namespace) -> list[str]:
    """W31 마찰20(β): CLI `--ref` 명시(있으면 전 장 최우선 — 종전 동작 보존). 없으면 빈 리스트를
    반환하고, `imagedeck.bundle()`이 장별로 3계층(`imagedeck_refs/slides/<NN>` > `.../global` >
    `design-assets/references/seed`)을 직접 조회한다(더 이상 이 함수가 `design_refs/`를 스캔하지
    않는다 — 그 폴더는 별개 트랙인 refine/stage9의 것이라 여기서 읽는 건 혼선이었다)."""
    return list(getattr(args, "ref", None) or [])


def _master_bundle_cmd(run: Path, args: argparse.Namespace) -> int:
    """W31 R10 v2(β2): `imagedeck --master-bundle` — 복합 입력함 브리핑 → master_design_prompt.md.

    research/company의 --bundle과 같은 문법(결정론 조립, LLM 미호출). 내용(storyline) 유무와
    무관하게 동작한다 — 디자인 선행 루트(start → 조사 → 마스터 시안 → 내용)가 이 성질에 의존한다.
    """
    rep = imagedeck.master_bundle(run, skins_dir=SKINS_DIR)
    _record_state(run, "imagedeck_master_bundle", artifacts={"prompt": rep["prompt"]},
                  institution_present=rep["institution_present"], company_present=rep["company_present"],
                  refs_source=rep["refs_source"], content_present=rep["content_present"])
    print(f"[MASTER BUNDLE] {rep['prompt']}")
    print(f"  발주처 조사={'있음' if rep['institution_present'] else '없음'} · "
          f"자사 프로필={'선택됨' if rep['company_present'] else '없음'} · "
          f"레퍼런스={rep['refs_source']}({rep['refs_count']}장) · "
          f"내용={'있음' if rep['content_present'] else '없음(디자인 선행 가능 — R10 v2)'}")
    try:
        profile = gates.load_config(run).get("profile")
    except Exception:
        profile = None
    contract = design_contract.load(run)
    if contract is not None and design_contract.is_full_skin(contract):
        print("  [안내] 차용 스킨이 이미 완전 스펙(full_skin)이다 - 차용본이 곧 마스터이므로 시안 생성을 생략해도 된다.")
    elif profile == "express":
        print("  [express] 마스터 시안 공정은 권장(생략 가능) - 상세 안내는 축약됐다.")
    print(f"  시안 확정 후 `imagedeck --master-apply --file <{imagedeck.MASTER_DESIGN_NAME} 경로> "
          f"--run {run.name}`.")
    return 0


def _master_apply_cmd(run: Path, args: argparse.Namespace) -> int:
    """W31 R10 v2(β2): `imagedeck --master-apply --file <json>` — 검증 → 계약 반영 → 레퍼런스 등록.

    ①master_design.json 검증(오류=중단·SSOT 안전) ②design_contract.json을 재동결 문법으로 갱신
    (기존 계약은 design_contract.prev.json으로 보존 — `_refreeze_contract`와 동형)하며 art_direction·
    density를 기록 ③확정 시안 이미지를 imagedeck_refs/global/에 등록(β1 3계층 조회가 자동 동봉).
    ④DF3(2026-07-24, DECK_FIRST_DESIGN.md §2-②·§3): background/decor_slots가 지정됐으면(둘 다
    선택) `imagedeck/design_assets/`로 복사해 chrome_contract.chrome.frame.image / decor_slots로
    동결한다 — 미지정이면 이 단계 자체가 조용히 생략된다(하위호환, 계약 바이트 동일).
    """
    file_arg = getattr(args, "master_file", None)
    doc_path = Path(file_arg) if file_arg else (run / imagedeck.MASTER_DESIGN_NAME)
    if not doc_path.is_file():
        raise PipelineInputError(
            f"master_design.json 없음: {doc_path} (--file로 경로를 지정하거나 먼저 --master-bundle로 "
            "프롬프트를 만들어 시안을 확정하라)"
        )
    try:
        doc = json.loads(doc_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PipelineInputError(f"master_design.json 파싱 실패: {exc}") from exc

    validation = imagedeck.validate_master_design(doc, run)
    for w in validation["warnings"]:
        print(f"[SURFACE] {w}")
    if validation["errors"]:
        for e in validation["errors"]:
            print(f"[INVALID] {e}", file=sys.stderr)
        raise PipelineInputError(f"master_design 검증 실패({len(validation['errors'])}건) — 적용 중단(SSOT 안전)")
    # ε패킷 안전장치①: knowledge_used 검증(누락=차단) + 원장 기록.
    k_errors, k_warnings = knowledge_ledger.validate_knowledge_used(doc, "master_design")
    if k_errors:
        raise PipelineInputError(
            "master_design 지식 보고 검증 실패(차단):\n  - " + "\n  - ".join(k_errors)
            + f"\n  {doc_path} 의 knowledge_used를 채우고(빈 배열도 명시) 다시 적용하라."
        )
    for w in k_warnings:
        print(f"[SURFACE] {w}")
    knowledge_ledger.record(run, "master_design", doc.get("knowledge_used"), source_file=str(doc_path))

    registered = imagedeck.register_master_refs(run, doc.get("assets") or [])

    # DF3: 배경 PNG·장식 자산 — 둘 다 선택. 미지정이면 register_master_assets 자체를 호출하지
    # 않는다(imagedeck/design_assets/ 빈 폴더조차 만들지 않음 — 완전한 하위호환).
    bg_input, decor_input = doc.get("background"), doc.get("decor_slots")
    bg_rel: str | None = None
    decor_resolved: list[dict] = []
    if bg_input or decor_input:
        bg_rel, decor_resolved = imagedeck.register_master_assets(
            run, background=bg_input, decor_slots=decor_input
        )

    prev_note = None
    if design_contract.exists(run):
        prev = run / "design_contract.prev.json"
        design_contract.path(run).replace(prev)
        prev_note = str(prev)
    brief = design_brief.load(run) or {}
    try:
        contract = design_contract.build(run, brief=brief, skins_dir=SKINS_DIR)
    except design_contract.DesignContractError as exc:
        raise PipelineInputError(str(exc)) from exc
    contract["density"] = doc.get("density", "standard")
    contract["art_direction"] = {
        "look": doc.get("look"),
        "chosen_axis": doc.get("chosen_axis"),
        "sources": doc.get("sources") or [],
        "registered_refs": registered,
        "confirmed_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    if bg_rel:
        contract["chrome_contract"].setdefault("chrome", {}).setdefault("frame", {})["image"] = bg_rel
    if decor_resolved:
        contract["chrome_contract"]["decor_slots"] = decor_resolved
    design_contract.save(run, contract)
    _record_state(run, "imagedeck_master_apply",
                  artifacts={"contract": str(design_contract.path(run)), "master_design": str(doc_path)},
                  density=contract["density"], chosen_axis=doc.get("chosen_axis"),
                  registered_refs=len(registered), background=bool(bg_rel), decor_slots=len(decor_resolved))
    print(f"[MASTER APPLY] {design_contract.path(run)} density={contract['density']} "
          f"chosen_axis={doc.get('chosen_axis') or '(없음)'} 등록 레퍼런스={len(registered)}장")
    kc = knowledge_ledger.stage_counts(run, "master_design")
    print(f"  지식: 카드 {kc['cards']} · 웹 {kc['web']}건")
    if prev_note:
        print(f"  기존 계약 보존: {prev_note} (theme_confirm 관문이 다음 판정에서 재무장된다)")
    if registered:
        print(f"  시리즈 레퍼런스 등록: {', '.join(registered)} (imagedeck --bundle이 자동 동봉)")
    if bg_rel:
        print(f"  배경 동결: chrome_contract.chrome.frame.image={bg_rel} (전 장 공유 - compose가 렌더)")
    if decor_resolved:
        ids = ", ".join(str(s.get("id") or s.get("image")) for s in decor_resolved)
        print(f"  장식 슬롯 동결: chrome_contract.decor_slots={len(decor_resolved)}건({ids})")
    if bg_rel or decor_resolved:
        print("  design-assets 싱크백(선택): `curate --sync-master --run "
              f"{run.name}`로 design-assets/references/에 보관할 수 있다(DESIGN_ASSETS_LANE §1).")
    _refreeze_downstream_notice(run)
    return 0


def _preview_cmd(run: Path, args: argparse.Namespace) -> int:
    """DF4(CONTEXT/DECK_FIRST_DESIGN.md §2-③·§3 DF4 행): `imagedeck --preview` — 계약 동결 후
    틀+배경(본문 비움) 프리뷰 PNG를 장 클래스별로 렌더 → imagedeck_refs/deck_preview/<class>.png.
    storyline/manifest와 무관(master-bundle/master-apply와 같은 성질 — design_contract.json만
    전제). 실패(계약 미동결·playwright 미설치)는 imagedeck.ImagedeckError로 사람 말 오류 전달
    (imagedeck_cmd 밖 dispatch가 [ERROR]로 감싼다)."""
    rep = imagedeck.render_deck_preview(run)
    _record_state(run, "imagedeck_preview",
                  artifacts={"deck_preview_dir": rep["out_dir"]},
                  rendered=len(rep["rendered"]), skipped_classes=rep["skipped_classes"])
    print(f"[IMAGEDECK preview] {rep['out_dir']} 렌더={len(rep['rendered'])}장")
    for r in rep["rendered"]:
        print(f"  - {r['class']}({r['image_scope']}): {r['out']}")
    if rep["skipped_classes"]:
        print(f"  건너뜀(image=none - 프롬프트 자체가 없어 프리뷰 불필요): {', '.join(rep['skipped_classes'])}")
    for w in rep["warnings"]:
        print(f"  [주의] {w}")
    print("  이후 `imagedeck --bundle`이 이 프리뷰를 전 장 4계층 레퍼런스"
          "(slide>global>deck_preview>seed)로 자동 동봉한다.")
    return 0


def _print_deck_overrides(rep: dict) -> None:
    """DF6(DECK_FIRST_DESIGN.md §2-⑦ 경로 B): 장별로 안전 분류 안내를 콘솔에 출력.
    [A]=재조립만(색·style_variant 등 - 본문 이미지 px 불변), [B]=구조 변형(chrome_override·
    deck_class - 본문 생성 px가 바뀔 수 있어 해당 장 이미지 재생성이 필요할 수 있다. collect의
    px 실측 검증이 그 불일치를 잡아준다). imagedeck.bundle/compose/compose_pptx가 공유하는
    rep["deck_overrides"] 상세(빈 리스트/미존재 모두 무해 - 아무것도 찍지 않는다)."""
    for o in (rep.get("deck_overrides") or []):
        tag = ("[A:재조립만]" if o["category"] == "a"
               else "[B:px변형 - 해당 장 재생성 필요할 수 있음, collect가 검출]")
        print(f"  [오버라이드] 장 {o['n']}: {', '.join(o['keys'])} - {tag}")


def imagedeck_cmd(args: argparse.Namespace) -> int:
    """W28 이미지 렌더 트랙: --bundle(프롬프트 조립) / --collect(px 검증) / --compose(HTML 크롬).

    상태머신 밖에서도 기존 run에 직접 실행 가능(증분1). go 편입은 증분2.
    """
    run = _render_run_dir(args.run, must_exist=True)

    # W31 R10 v2(β2): 덱 마스터 디자인 공정 — storyline 유무·pipeline_state 순서와 무관하게 동작한다
    # (research/company와 같은 독립 서브커맨드 문법 — _next_step 상태머신을 타지 않으므로 조기 실행을
    # 막을 게이트 자체가 없다. 디자인 선행 루트는 이 성질에 의존한다).
    if getattr(args, "master_bundle", False):
        return _master_bundle_cmd(run, args)
    if getattr(args, "master_apply", False):
        return _master_apply_cmd(run, args)
    # DF4(DECK_FIRST_DESIGN.md §3 DF4 행): --preview도 같은 성질 — storyline/manifest 무관,
    # design_contract.json 동결만 전제한다.
    if getattr(args, "preview", False):
        return _preview_cmd(run, args)

    if args.bundle:
        # W31 R2·R5: design_contract.json(run별 정본)이 있으면 그것만 쓴다 — skin_path는 필요 없다
        # (imagedeck.bundle이 내부에서 계약을 우선 조회한다). 계약이 없는 run(파일럿·레거시, 또는
        # go 편입 없이 이 커맨드를 바로 호출하는 경우)만 종전처럼 skin 파일을 해석한다.
        # ⚠️ W29 "기본값=inkline" 자동 폴백은 폐기했다(용어 정의 이행 과제, R5) —
        # inkline도 이제 design_brief.skin.value로 명시 차용했을 때만 쓰이는 창고 스킨 중 하나다.
        # 값이 없으면 skins/_neutral.json(중립 템플릿)에서 시작한다.
        skin_path = None
        if not design_contract.exists(run):
            skin_name = getattr(args, "skin", None)
            if not skin_name:
                brief = design_brief.load(run) or {}
                skin_name = ((brief.get("skin") or {}).get("value")) or design_contract.NEUTRAL_SKIN_NAME
            skin_path = imagedeck.resolve_skin(skin_name, SKINS_DIR)
        ab = set()
        for tok in (getattr(args, "ab", None) or []):
            ab.add(int(tok) if str(tok).isdigit() else tok)
        refs = _imagedeck_refs(run, args)
        rep = imagedeck.bundle(run, skin_path, wireframe_mode=args.wireframe_mode,
                               refs=refs, ab_slides=ab)
        _record_state(run, "imagedeck_bundle",
                      artifacts={"manifest": str(run / imagedeck.MANIFEST_NAME)},
                      skin=rep["skin"], wireframe_mode=rep["wireframe_mode"],
                      slides=len(rep["slides"]), gen_canvas=rep["gen_canvas"],
                      bundle_hash=rep["bundle_hash"],
                      overflow_splits=len(rep.get("overflow_splits") or []))
        print(f"[IMAGEDECK bundle] 스킨={rep['skin']} 모드={rep['wireframe_mode']} "
              f"장={len(rep['slides'])} 생성캔버스={rep['gen_canvas']['w']}x{rep['gen_canvas']['h']}")
        print(f"  프롬프트: {run / imagedeck.PROMPTS_DIR}  ·  매니페스트: {run / imagedeck.MANIFEST_NAME}")
        # W31 마찰20(β): --ref 명시가 없으면 장별 실제 조회 결과(slide/global/seed/none)를 집계해
        # 보여준다 — 시드가 쓰였으면 그것도 "미지정" 오판을 막기 위해 안내한다.
        if refs:
            print(f"  레퍼런스(명시 --ref, 전 장 적용): {', '.join(refs)}")
        else:
            tiers = [s.get("references_source") for s in rep["slides"] if s.get("render") != "html"]
            seed_n, slide_n, global_n, none_n = (tiers.count(t) for t in ("seed", "slide", "global", "none"))
            if slide_n or global_n:
                print(f"  레퍼런스: 장별 {slide_n}장 · 전체 {global_n}장 (run/imagedeck_refs/).")
            if seed_n:
                print(f"  레퍼런스: 시드 기본값 사용 {seed_n}장(design-assets/references/seed/, 교체 가능).")
            if none_n:
                print(f"  [주의] 레퍼런스 이미지 없음 {none_n}장 - run/imagedeck_refs/global 또는 "
                      "slides/<NN>/에 넣거나 --ref로 지정하라(시리즈 일관성).")
        # W31 γ패킷(마찰23): 결정론 사전 분할 발생/포기 보고.
        splits = rep.get("overflow_splits") or []
        if splits:
            for sp in splits:
                print(f"  [분할] 장 {sp['n']}: {sp['chars']}자 > 용량추정 {sp['capacity_at_min_font']}자"
                      f"(하한폰트 {sp['min_font_px']}px) - A/B 사전 분할({sp['reason']}).")
        skipped = [s for s in rep["slides"] if s.get("overflow_split_skipped")]
        for s in skipped:
            print(f"  [주의] 장 {s['n']}: 분량 초과했지만 분할 불가 - {s.get('overflow_split_skip_reason', '')}")
        _print_deck_overrides(rep)  # DF6: run/deck_overrides.json이 얹은 장이 있으면 ⓐ/ⓑ 안내.
        # W32: 생산 CLI 감지에 따라 다음 단계 안내를 가른다(없으면 수동 루트 가이드 자동 생성).
        det = imagedeck.detect_producers()
        if det.get("codex"):
            print(f"  [Codex 단발 위임] 각 프롬프트로 이미지를 그려 {run / imagedeck.SLIDES_DIR}/ 에 저장 "
                  f"(파일명=매니페스트 out_name). 이후 `imagedeck --collect --run {run.name}`.")
        else:
            guide = imagedeck.write_manual_guide(run)
            print(f"  [수동 생산 루트] codex CLI 미감지 - 가이드를 여정 폴더에 생성했다: {display_path(guide)}")
            print("  프롬프트 복붙 생성 -> 다운로드(파일명=장 번호 시작) -> "
                  f"`imagedeck --adopt <폴더> --run {run.name}` -> `imagedeck --collect --run {run.name}`.")
        return 0

    if getattr(args, "produce", False):
        # W29 승격: 임시 드라이버 → 정식 생산 커맨드. Codex 단발 위임(사람 관문과 무관한 기계 생산).
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # 파일명 비cp949 안전
        except (AttributeError, OSError):
            pass
        # W32 수동 루트: codex CLI 미감지 → 실패가 아니라 **자동 경로 전환**이다. 가이드를 여정
        # 09 폴더에 만들고 복붙→adopt→collect 절차를 안내한다(같은 파일 계약이라 이후 공정 무분기).
        det = imagedeck.detect_producers()
        if not det.get("codex"):
            guide = imagedeck.write_manual_guide(run)
            print("[IMAGEDECK produce] codex CLI 미감지 - 수동 생산 루트로 전환한다(W32).")
            if det.get("agy"):
                print("  (agy CLI는 감지됐지만 이미지 생산 러너는 codex 전용이다 - 수동 루트를 쓴다.)")
            print(f"  가이드(여정 폴더): {display_path(guide)}")
            print("  절차: 프롬프트 복붙 생성 -> 이미지를 한 폴더에 다운로드(파일명=장 번호 시작) ->")
            print(f"        `imagedeck --adopt <폴더> --run {run.name}` -> `imagedeck --collect --run {run.name}`")
            _record_state(run, "imagedeck_manual_guide", artifacts={"guide": str(guide)},
                          agy_detected=bool(det.get("agy")))
            return 0
        if str(APP_ROOT) not in sys.path:
            sys.path.insert(0, str(APP_ROOT))
        import codex_runner  # type: ignore
        # 이미지 생산 한정 기본 effort=low (W32 시연 A/B/C 실측·사용자 확정 2026-08-02:
        # 시간 주범은 모델이 아니라 effort — 5.5/low가 5.5/high 대비 절반 시간에 위반 0.
        # 텍스트 경로의 make_codex_runner 기본값(high)은 건드리지 않는다 — 마찰33).
        runner_kw = {"cwd": run, "timeout": int(getattr(args, "timeout", 900)),
                     "effort": str(getattr(args, "effort", None) or "low")}
        if getattr(args, "model", None):
            runner_kw["model"] = str(args.model)
        runner = codex_runner.make_codex_runner(**runner_kw)
        # W32 마찰33 잔여⑵: 조용한 기본값 대신 **사람이 보는 판단 통로**로 만든다 — 무엇으로
        # 생산 중인지 화면에 찍고 바꾸는 법을 함께 안내한다(모델 세대가 바뀌면 여기서 드러난다).
        _eff = runner_kw["effort"]
        _mdl = runner_kw.get("model") or "gpt-5.5(러너 기본값)"
        print(f"[IMAGEDECK produce] 모델={_mdl} · effort={_eff}"
              + ("" if getattr(args, "model", None) else " - 바꾸려면 `--model`/`--effort`"))
        if _eff == "low":
            print("  (effort=low는 W32 실측 기본값: 5.5/high 대비 장당 시간 절반·px 위반 0)")
        only = {t.strip() for t in str(getattr(args, "only", "") or "").split(",") if t.strip()}
        rep = imagedeck.produce(run, runner, only=only or None,
                                progress=lambda msg: print(msg, flush=True))
        _record_state(run, "imagedeck_produce",
                      generated=len(rep["generated"]), skipped=len(rep["skipped"]),
                      failed=len(rep["failed"]))
        print(f"[IMAGEDECK produce] 생성 {len(rep['generated'])} · skip {len(rep['skipped'])} · "
              f"실패 {len(rep['failed'])}")
        if rep["failed"]:
            print(f"  실패 장: {rep['failed']} - 재실행하면 실패분만 다시 위임한다.")
        print(f"  이후 `imagedeck --collect --run {run.name}` (전량 px 실측).")
        return 0 if not rep["failed"] else 1

    if getattr(args, "manual_guide", False):
        # W32 수동 루트: 가이드만 (재)생성 — 상태 열 실측 갱신 겸용.
        guide = imagedeck.write_manual_guide(run)
        print(f"[IMAGEDECK manual-guide] 수동 생산 가이드 생성: {display_path(guide)}")
        print("  프롬프트 복붙 -> 다운로드(파일명=장 번호 시작) -> "
              f"`imagedeck --adopt <폴더> --run {run.name}` -> `--collect`.")
        return 0

    if getattr(args, "adopt", None):
        # W32 수동 루트 수거 헬퍼: 다운로드 폴더의 이미지를 PNG 변환·기대 px 리사이즈·개명·배치.
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # 파일명 비cp949 안전
        except (AttributeError, OSError):
            pass
        only = {t.strip() for t in str(getattr(args, "only", "") or "").split(",") if t.strip()}
        rep = imagedeck.adopt(run, Path(args.adopt), only=only or None)
        _record_state(run, "imagedeck_adopt",
                      adopted=len(rep["adopted"]), replaced=len(rep["replaced"]),
                      unmatched=len(rep["unmatched"]), failed=len(rep["failed"]),
                      missing=len(rep["missing"]))
        print(f"[IMAGEDECK adopt] 배치 {len(rep['adopted'])} · 교체 {len(rep['replaced'])} · "
              f"미매칭 {len(rep['unmatched'])} · 실패 {len(rep['failed'])} · 남은 장 {len(rep['missing'])}")
        for name in rep["adopted"]:
            print(f"  [ok  ] {name}")
        for name in rep["replaced"]:
            print(f"  [교체] {name}")
        for name in rep["unmatched"]:
            print(f"  [미매칭] {name} - 파일명을 장 번호로 시작하게 바꿔라(예: 05.png, A/B 장은 05A.png).")
        for msg in rep["failed"]:
            print(f"  [실패] {msg}")
        if rep["missing"]:
            print(f"  아직 없는 장: {', '.join(rep['missing'])}")
        print(f"  이후 `imagedeck --collect --run {run.name}` (전량 px 실측).")
        return 0 if not rep["failed"] else 1

    if args.collect:
        rep = imagedeck.collect(run)
        _record_state(run, "imagedeck_collect",
                      artifacts={"report": str(run / imagedeck.COLLECT_NAME)},
                      coverage=rep["coverage"], passed=rep["pass"],
                      pixel_warnings=rep.get("pixel_warnings", 0))
        cov = rep["coverage"]
        print(f"[IMAGEDECK collect] 커버리지 {cov['ok']}/{cov['total']} · "
              f"판정 {'PASS' if rep['pass'] else 'FAIL'}")
        for r in rep["slides"]:
            if r["status"] != "ok":
                print(f"  [{r['status']}] 장 {r['n']}{r.get('variant') or ''} - {r.get('reason','')}")
        # W31 γ패킷(마찰24): 픽셀 휴리스틱 — warn 등급(오탐 여지 있음, px 판정과 별개).
        if rep.get("pixel_heuristics_available"):
            print(f"  픽셀 휴리스틱 경고: {rep.get('pixel_warnings', 0)}건(warn - fail 아님)")
            for r in rep["slides"]:
                flags = ((r.get("pixel_heuristics") or {}).get("flags")) or []
                if flags:
                    print(f"    [WARN] 장 {r['n']}{r.get('variant') or ''}: {', '.join(flags)}")
        else:
            print(f"  픽셀 휴리스틱: {rep.get('pixel_heuristics_note', '미측정')}")
        print(f"  리포트: {run / imagedeck.COLLECT_MD}")
        print(f"  검수 scaffold(자동 생성): {run / imagedeck.REVIEW_MD}")
        return 0 if rep["pass"] else 1

    if getattr(args, "review_scaffold", False):
        rep = imagedeck.review_scaffold(run)
        print(f"[IMAGEDECK review] 검수 scaffold {rep['out']} (장 {rep['slides']})")
        print("  세션이 각 이미지를 Read로 열어 정본과 대조하고 verdict를 채운다(자동 OCR 금지).")
        print("  검수는 선택 - 사람이 바로 정독·채택해도 된다(대시보드). 최종 채택 = imagedeck_ack.")
        return 0

    if getattr(args, "compose_pptx", False):
        rep = imagedeck.compose_pptx(run)
        _record_state(run, "imagedeck_compose_pptx",
                      artifacts={"pptx": rep["out"]}, slides=rep["slides"],
                      images_used=rep["images_used"], html_native=rep["html_native"])
        print(f"[IMAGEDECK compose-pptx] {rep['out']} 장={rep['slides']} "
              f"이미지={rep['images_used']} 네이티브={rep['html_native']}")
        print("  크롬(제목·부제·푸터)과 표지·목차·간지는 PowerPoint에서 직접 수정 가능 - "
              "본문 이미지만 픽셀.")
        if rep["missing"]:
            print(f"  [주의] 이미지 누락 {len(rep['missing'])}건: {rep['missing']}")
        _print_deck_overrides(rep)  # DF6
        return 0

    if args.compose:
        rep = imagedeck.compose(run)
        _record_state(run, "imagedeck_compose",
                      artifacts={"html": rep["out"]}, slides=rep["slides"],
                      images_used=rep["images_used"])
        print(f"[IMAGEDECK compose] {rep['out']} 장={rep['slides']} 이미지={rep['images_used']}")
        if rep["missing"]:
            print(f"  [주의] 이미지 누락 {len(rep['missing'])}건: {rep['missing']}")
        if rep["chrome"]["header_h"] == 0 and rep["chrome"]["footer_h"] == 0:
            print("  [주의] 크롬 밴드 0 - 로고/제목 HTML 크롬 없이 이미지만 조합했다(스킨 chrome 참조).")
        _print_deck_overrides(rep)  # DF6
        return 0

    if getattr(args, "export", None):
        rep = imagedeck.export_outputs(run, Path(args.export))
        print(f"[IMAGEDECK export] {rep['dest']} - 신규/갱신 {len(rep['copied'])} · "
              f"최신본 skip {len(rep['skipped'])} · 총 {rep['total']}건")
        if rep["copied"]:
            print(f"  복사됨: {', '.join(rep['copied'][:10])}"
                  + (f" 외 {len(rep['copied']) - 10}건" if len(rep["copied"]) > 10 else ""))
        return 0

    raise PipelineInputError("imagedeck: --bundle / --produce / --adopt / --manual-guide / --collect / --compose / --preview / --export 중 하나를 지정하라.")


def main() -> int:
    parser = argparse.ArgumentParser(description="제안 자동화 파이프라인 (start / go / ship)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_status = sub.add_parser("status", help="--run 없으면 시스템 전역 상태, 있으면 그 run의 공정 위치·다음 커맨드")
    p_status.add_argument("--run", "--run-dir", dest="run", help="N1: run의 공정 상태머신 조회")
    p_status.add_argument("--json", action="store_true")

    # --- 동사 3개 (§3.0) — 사용자 표면은 이것이 전부 ---
    p_start = sub.add_parser("start", help="동사①: 입력(공고번호 or brief.md) + 모드 확정 → run 생성")
    p_start.add_argument("--bid", help="나라장터 공고번호 (어댑터 입구)")
    p_start.add_argument("--brief", help="범용 요구사항 문서 경로 (범용 입구)")
    p_start.add_argument("--mode", required=True, choices=list(pipeline_state.MODES),
                         help="secure=복붙 왕복(외부 LLM 미노출) | direct=세션 LLM/Codex 관통")
    p_start.add_argument("--run-name", dest="run_name")
    p_start.add_argument("--selected-by", dest="selected_by", choices=["user", "dashboard", "agent"],
                         default=None,
                         help="공고 선택 출처(결정 8). 미지정 시 --bid는 dashboard/feedback.json Go 기록과 대조해 "
                              "자동 실측(없으면 unspecified) / --brief는 user 기본. 사람 선별이 아니면 agent로 명시.")
    p_start.add_argument("--gates", choices=list(gates.PROFILES), default=None,
                         help="W31 리허설 마찰2: 관문 프로파일(full=전 관문 정지 · standard(기본)=회의 관문만 "
                              "정지 · express=비스킵 2종도 조건부). 미지정 시 gates.json 없음(=standard 취급).")
    p_start.add_argument("--company", default=None,
                         help="W31 리허설 마찰6(선택): 제안사 프로필 창고(proposal_system/companies/<id>)에서 "
                              "이 run에 쓸 회사를 선택(run/company_selection.json에 기록). 미지정 시 현행 동작 불변 "
                              "— `company --list`로 창고 확인.")

    p_go = sub.add_parser("go", help="동사②: 다음 체크포인트까지 자동 진행(멱등). LLM은 호출하지 않는다")
    p_go.add_argument("--run", "--run-dir", dest="run", required=True)
    p_go.add_argument("--confirm", action="store_true", help="대기 중인 체크포인트를 통과 처리하고 계속")
    p_go.add_argument("--gates", choices=list(gates.PROFILES), default=None,
                      help="W31 리허설 마찰2: 관문 프로파일 중도 변경(gates.json에 지속). 미지정=기존 유지.")
    p_go.add_argument("--redo-skeleton", action="store_true",
                      help="W31: message_map 개정 후 뼈대를 현재 메시지맵으로 재조립"
                           "(기존 skeleton.json·manifest는 .bak_redo로 보존)")
    p_go.add_argument("--refreeze-contract", dest="refreeze_contract", action="store_true",
                      help="W31 마찰14: design_brief 수정 후 design_contract.json을 재동결. 기존 계약은 "
                           "design_contract.prev.json으로 보존하고 브리핑으로 재생성 — theme_confirm 관문이 "
                           "다음 판정에서 재무장된다.")
    p_go.add_argument("--scenario", default=skeleton.DEFAULT_SCENARIO,
                      help=f"W10 역제안 스켈레톤 시나리오 id(기본 {skeleton.DEFAULT_SCENARIO}). "
                           "등록=proposal_system/scenarios/<id>.json")
    p_go.add_argument("--house-knowledge", dest="house_knowledge", default=None,
                      help="수주덱 채굴 지식 오버레이(opt-in - 목표조정 2): gseries")
    p_go.add_argument("--pack", default="core")
    p_go.add_argument("--skins")
    p_go.add_argument("--design-guide", dest="design_guide")
    p_go.add_argument("--analysis")
    p_go.add_argument("--rfp")
    p_go.add_argument("--json", action="store_true")

    p_ship = sub.add_parser("ship", help="동사③: 승인 + 산출물 확정. --pptx는 여기서만")
    p_ship.add_argument("--run", "--run-dir", dest="run", required=True)
    p_ship.add_argument("--pptx", action="store_true", help="승인된 deck.json에서 PPTX 파생(deck.html 불변)")
    p_ship.add_argument("--pptx-mode", dest="pptx_mode", default="native", choices=["native", "image", "hybrid"])
    p_ship.add_argument("--ingest", help="표면②: Claude Design 편집본 HTML — 가드 후 manual_layer freeze")
    p_ship.add_argument("--source", help="편집본 출처(Artifact URL 등)")

    p_render = sub.add_parser("render", help="Ingest stage JSON or storyline and render a canonical deck")
    p_render.add_argument("--run", "--run-dir", dest="run_dir")
    p_render.add_argument("--stage6")
    p_render.add_argument("--stage7")
    p_render.add_argument("--stage8")
    p_render.add_argument("--storyline")
    p_render.add_argument("--project")
    p_render.add_argument("--pack", default="core",
                          help="디자인 테마(팩 id): core=중립 코어(기본·무채) | house_a/house_b=하우스 플러그인 예제(명시 시)")
    p_render.add_argument("--pattern-sets", help="Reserved for render workflows that also build Stage 6 bundles")
    p_render.add_argument("--pptx", action="store_true", help="Also render deck.pptx through app/render/dispatch")
    p_render.add_argument("--pptx-mode", dest="pptx_mode", default="native",
                          choices=["native", "image", "hybrid"],
                          help="PPTX 렌더 방식: native(기본, 편집가능 셰이프) | image(HTML→PNG) | hybrid. image/hybrid는 playwright 필요.")
    p_render.add_argument("--skins", help="③스킨 캐스케이드 소스(쉼표구분: 스킨이름/경로). pack.tokens 위에 순서대로 오버라이드. 예: --skins quartz(오렌지 테마)")
    p_render.add_argument("--analysis", help="Analysis JSON for Stage7 enrichment (optional)")
    p_render.add_argument("--rfp", help="RFP text file for Stage7 enrichment (optional)")
    p_render.add_argument("--anonymize-config")
    p_render.add_argument("--json", action="store_true")

    p_s9 = sub.add_parser("stage9", help="디자인 디렉터 패스(렌더 후): 프롬프트 번들 또는 --apply(override 검증·병합)")
    p_s9.add_argument("--run", "--run-dir", dest="run_dir", required=True)
    p_s9.add_argument("--slides", help="모드 A: 대상 슬라이드(쉼표구분 slide_id). 미지정 시 모드 B(review_badges 밋밋)")
    p_s9.add_argument("--design-guide", dest="design_guide", help="가이드 스킨 id(쉼표구분, 캐스케이드). 미지정=전체. 등록=config knowledge.design_guides")
    p_s9.add_argument("--pack", default="core",
                      help="디자인 테마(팩 id): core=중립 코어(기본·무채) | house_a/house_b=하우스 플러그인 예제(명시 시)")
    p_s9.add_argument("--apply", action="store_true", help="design_overrides.json 검증 후 deck.html에 병합·재렌더")
    p_s9.add_argument("--fill-images", dest="fill_images", action="store_true",
                      help="§7·B-9: image_slots 채움(mood/conceptual만·evidence 금지·tier<2 degrade). tier≥2에서 codex SVG 생성. --apply와 함께 쓰면 채운 뒤 병합")
    p_s9.add_argument("--no-generate", dest="no_generate", action="store_true",
                      help="fill 시 생성 러너 비활성(전부 placeholder degrade — 배선 확인용)")
    p_s9.add_argument("--overrides", help="override 경로(기본: <run>/design_overrides.json)")
    p_s9.add_argument("--skins", help="디자인 스킨 캐스케이드(쉼표구분: 스킨이름/경로). 미지정=design_brief.skin.skins > 마지막 render의 skins 승계")
    p_s9.add_argument("--json", action="store_true")

    p_wf = sub.add_parser("wireframe", help="W21 [3] 와이어프레임 루프(go 내부 단계): --bundle(결정기 프롬프트) / --apply(wireframe.json 검증·병합·무채 재렌더·재게이트)")
    p_wf.add_argument("--run", "--run-dir", dest="run_dir", required=True)
    p_wf.add_argument("--bundle", action="store_true", help="결정기(LLM) 프롬프트 번들 생성 → run/wireframe_prompt/prompt.md")
    p_wf.add_argument("--apply", dest="wf_apply", action="store_true", help="run/wireframe.json 검증→deck.json 병합→core 무채 재렌더→gating wireframe 블록")
    p_wf.add_argument("--file", help="wireframe.json 경로(기본: <run>/wireframe.json)")
    p_wf.add_argument("--pack", default="core", help="재렌더 팩(기본 core — [3]는 무채)")
    p_wf.add_argument("--skins", help="디자인 스킨 캐스케이드(쉼표구분: 스킨이름/경로). 미지정=design_brief.skin.skins > 마지막 render의 skins 승계")

    p_refine = sub.add_parser(
        "refine",
        help="[4+] 디자인 고도화(결정 15-17): --bundle(목표 명세 프롬프트) / --collect(명세 검증+형태 레퍼런스 수집+사람 체크포인트) / --handoff(실행자 번들)",
    )
    p_refine.add_argument("--run", "--run-dir", dest="run_dir", required=True)
    p_refine.add_argument("--bundle", action="store_true", help="명세자(LLM) 프롬프트 번들 생성 → run/refine_prompt/prompt.md")
    p_refine.add_argument("--collect", action="store_true", help="design_spec.json 검증 → 형태 레퍼런스 수집(run/design_refs/) → 사람 체크포인트 안내")
    p_refine.add_argument("--handoff", action="store_true", help="실행자(Claude Design 등) 핸드오프 번들 → run/refine_handoff/prompt.md")
    p_refine.add_argument("--file", help="design_spec.json 경로(기본: <run>/design_spec.json)")

    p_imgd = sub.add_parser(
        "imagedeck",
        help="W28 이미지 렌더 트랙: --bundle(장별 프롬프트+manifest·D12 역산) / --collect(PNG px 실측·커버리지) / --compose(HTML 크롬 조합→deck.images.html)",
    )
    p_imgd.add_argument("--run", "--run-dir", dest="run", required=True)
    p_imgd.add_argument("--bundle", action="store_true", help="storyline+wireframe+스킨 → run/imagedeck_prompts/NN.md + manifest (정지=Codex 단발 위임)")
    p_imgd.add_argument("--produce", action="store_true", help="W29: 미생산 이미지 장을 Codex에 순차 단발 위임(장별 px 즉시 실측·재실행 안전)")
    p_imgd.add_argument("--only", default="", help="produce/adopt: 장 번호 쉼표 목록(예: 3,5) - 지정 장만 처리")
    p_imgd.add_argument("--timeout", type=int, default=900, help="produce: Codex 장당 타임아웃 초(기본 900)")
    p_imgd.add_argument("--model", default=None, help="produce: codex 모델 오버라이드(미지정=러너 기본값 gpt-5.5 — W32 시연 마찰33)")
    p_imgd.add_argument("--effort", default=None, help="produce: codex reasoning effort 오버라이드(미지정=low — W32 A/B/C 실측·사용자 확정 2026-08-02)")
    p_imgd.add_argument("--adopt", metavar="DIR",
                        help="W32 수동 루트 수거 헬퍼: DIR의 이미지(파일명=장 번호 시작, png/jpg/webp)를 "
                             "PNG 변환·기대 px 리사이즈(cover-crop)·out_name 개명 후 imagedeck/slides/에 배치(Pillow 필요)")
    p_imgd.add_argument("--manual-guide", dest="manual_guide", action="store_true",
                        help="W32 수동 루트: 복붙 절차·장별 표(파일명·px·상태 실측) 가이드를 여정 09 폴더에 (재)생성")
    p_imgd.add_argument("--collect", action="store_true", help="run/imagedeck/slides/*.png 존재·해상도 px·커버리지·파일명 검증")
    p_imgd.add_argument("--compose", action="store_true", help="승인 이미지 + HTML 크롬(제목·로고) → run/deck.images.html")
    p_imgd.add_argument("--compose-pptx", dest="compose_pptx", action="store_true",
                        help="W30: 하이브리드 pptx → run/deck.images.pptx (크롬·표지·목차·간지=네이티브 수정 가능, 본문=이미지)")
    p_imgd.add_argument("--review-scaffold", dest="review_scaffold", action="store_true",
                        help="Q2 Claude 검수 계약: 장별 정본 대조표 → run/imagedeck_review.md (선택 - 세션이 이미지 Read 후 채움)")
    p_imgd.add_argument("--export", metavar="DEST",
                        help="W28 마찰L3: run 산출물(slides/*.png·manifest·deck.images.html/pptx)을 워크스페이스 밖 "
                             "DEST로 신규/갱신분만 복사(단방향, 원본 불변) - 이식용 로컬 사본의 조용한 stale 방지")
    p_imgd.add_argument("--skin", help="run/design_contract.json이 없을 때만 쓰는 폴백: 스킨 이름(skins/<name>.json) 또는 경로. "
                                       "미지정=design_brief.skin.value > _neutral(중립 템플릿, W31 R5 — inkline 자동폴백 폐기)")
    p_imgd.add_argument("--wireframe-mode", dest="wireframe_mode", default="auto",
                        choices=["on", "off", "auto"], help="D13 wireframe 적용(기본 auto: 있으면 적용)")
    p_imgd.add_argument("--ref", action="append", help="레퍼런스 이미지 경로(반복, 전 장 최우선). 2종=디자인언어+승인색. 미지정=장별>전체(run/imagedeck_refs/)>시드 조회(마찰20)")
    p_imgd.add_argument("--ab", action="append", help="A/B 승격할 장 번호(반복): on/off 두 벌 생성(lecture 04 실험)")
    p_imgd.add_argument("--master-bundle", dest="master_bundle", action="store_true",
                        help="W31 R10 v2(β2): 복합 입력함(발주처·자사·주제·레퍼런스·디자인지식 pull) 브리핑 → "
                             "run/master_design_prompt.md (내용 유무 무관 — 디자인 선행 가능)")
    p_imgd.add_argument("--master-apply", dest="master_apply", action="store_true",
                        help="W31 R10 v2(β2): master_design.json 검증 → design_contract에 art_direction/density 기록"
                             "(재동결 문법 — prev 보존) + 확정 시안을 imagedeck_refs/global/에 시리즈 레퍼런스로 등록")
    p_imgd.add_argument("--file", dest="master_file",
                        help="--master-apply: master_design.json 경로(기본: <run>/master_design.json)")
    p_imgd.add_argument("--preview", action="store_true",
                        help="DF4(DECK_FIRST_DESIGN.md §3): 계약 동결 후 틀+배경(본문 비움) 프리뷰 PNG를 "
                             "장 클래스별로 렌더 → imagedeck_refs/deck_preview/<class>.png "
                             "(playwright 필요 — pip install playwright && playwright install chromium). "
                             "이후 --bundle이 4계층 레퍼런스(slide>global>deck_preview>seed)로 자동 동봉")

    p_research = sub.add_parser(
        "research",
        help="[1] 내용 만들기 - 기관 공개 조사(문서 밖 근거·브랜드 토큰): --bundle(조사 프롬프트) / --apply(수거 검증+스킨 등록)",
    )
    p_research.add_argument("--run", "--run-dir", dest="run_dir", required=True)
    p_research.add_argument("--bundle", action="store_true", help="조사자(LLM) 프롬프트 번들 생성 → run/research_prompt/prompt.md")
    p_research.add_argument("--institution", help="기관명(미지정 시 run/analysis/ 분석카드의 발주처 행에서 추정)")
    p_research.add_argument("--apply", action="store_true", help="institution_research.json 검증 → skins/<id>.json 등록 → design_brief 승계")
    p_research.add_argument("--skin-id", dest="skin_id", help="스킨 id(기본: 기관명 슬러그)")

    p_company = sub.add_parser(
        "company",
        help="제안사(자사) 프로필 창고(W31 리허설 마찰6): --list(창고 표) / --bundle --id(인테이크 프롬프트) / --apply --id --file(검증·병합)",
    )
    p_company.add_argument("--list", dest="company_list", action="store_true", help="창고 회사 표(id·명칭·fictional·실적 수·최근 갱신)")
    p_company.add_argument("--bundle", action="store_true", help="intake/ 원본 목록+기존 profile 요약 동봉 정형화 프롬프트 생성")
    p_company.add_argument("--id", help="회사 id(proposal_system/companies/<id>)")
    p_company.add_argument("--apply", action="store_true", help="수거 JSON 검증(스키마·출처 누락=오류) 후 profile.json에 병합 + gaps.md 갱신")
    p_company.add_argument("--file", help="--apply: 병합할 JSON 파일 경로")

    p_curate = sub.add_parser(
        "curate",
        help="큐레이션 생애주기(DESIGN_ASSETS_LANE §5-④-③ · 전부 선택): --list(라이브러리 표) / --register <id>(창고에 담기) / --refs --run(참고자료 반입)",
    )
    p_curate.add_argument("--list", dest="curate_list", action="store_true", help="스킨·가이드 라이브러리 표 갱신 → design-assets/curation_manifest.json(+md) (기본 동작)")
    p_curate.add_argument("--register", dest="curate_register", metavar="ID", help="자산을 design-assets/로 복사·등록(싱크백). 원본 없으면 중단")
    p_curate.add_argument("--kind", choices=["skin", "guide"], help="register: id가 스킨·가이드 양쪽에 있을 때 종류 지정")
    p_curate.add_argument("--refs", action="store_true", help="참고자료 반입 통로 열기(design_refs/refs.md) + 현재 넣은 파일·링크 표면화 (--run 필요)")
    p_curate.add_argument("--sync-master", dest="curate_sync_master", action="store_true",
                          help="DF3: 확정 마스터 배경·장식 자산(design_contract.chrome_contract)을 design-assets/references/로 싱크백 (--run 필요, 선택 사항)")
    p_curate.add_argument("--run", "--run-dir", dest="run_dir", help="refs / sync-master: 대상 run")

    p_appr = sub.add_parser("approve", help="승인 표면(부착형): 정적 프리뷰 승인 또는 --ingest(Claude Design 편집본 회수·가드·freeze)")
    p_appr.add_argument("--run", "--run-dir", dest="run_dir", required=True)
    p_appr.add_argument("--ingest", help="표면②: Claude Design 편집본 HTML 경로 — 텍스트 안전 가드 후 manual_layer.html로 freeze")
    p_appr.add_argument("--source", help="편집본 출처(Artifact URL 등) — provenance 기록")

    p_skin = sub.add_parser("add-skin", help="새 레퍼런스(PPTX/PDF) → 정규형 가이드(스킨) 통합: 포팅→(선택 tokens)→config 자동 등록→검증")
    p_skin.add_argument("--source", required=True, help="레퍼런스 .pptx 또는 .pdf(상대=repo 루트 기준)")
    p_skin.add_argument("--id", required=True, help="가이드 id(영숫자·_.-; --design-guide/--skins에서 사용)")
    p_skin.add_argument("--out", help="포팅 산출 폴더(기본: _source/design_guides/<id>_ported)")
    p_skin.add_argument("--process-md", dest="process_md", help="포터에 넘길 프로세스/판단기준 MD(선택)")
    p_skin.add_argument("--title", help="가이드 제목(선택)")
    p_skin.add_argument("--tokens", action="store_true", help="결정론 tokens 스킨도 생성(pptx만) → skins/<id>.json(render --skins)")
    p_skin.add_argument("--python", help="포터/추출기용 파이썬(기본: 번들 런타임→현재 인터프리터). env PORT_DESIGN_PYTHON도 가능")
    p_skin.add_argument("--no-port", dest="no_port", action="store_true", help="포팅 건너뜀(이미 --out 폴더 있음) — 등록만")
    p_skin.add_argument("--dry-run", dest="dry_run", action="store_true", help="계획만 출력, 쓰기 없음")

    p_archive = sub.add_parser(
        "archive",
        help="W31 리허설 마찰9 run 보관소 왕복: --run(보관 이동) / --restore(복귀) / --list(활성 완료+보관소 표)",
    )
    p_archive.add_argument("--run", "--run-dir", dest="run", help="보관할 활성 run(기계명 그대로 지정)")
    p_archive.add_argument("--name", help="보관 한글명(미지정 시 분석카드/last_search/기관조사/brief 순으로 자동 유도)")
    p_archive.add_argument("--restore", help="복귀시킬 보관 폴더명(`YYYY-MM_한글명`) — 원 기계 id로 runs/에 복귀")
    p_archive.add_argument("--list", dest="archive_list", action="store_true",
                           help="활성 중 완료(승인) run + 보관소 목록 표")

    args = parser.parse_args()

    if args.cmd == "status":
        if args.run:  # N1: run 단위 공정 상태
            try:
                return status_run_cmd(args)
            except PipelineInputError as exc:
                print(f"[ERROR] {exc}", file=sys.stderr)
                return 2
        result = status(json_mode=args.json)  # 기존 전역 상태(호환 유지)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd in ("start", "go", "ship"):
        handler = {"start": start_cmd, "go": go_cmd, "ship": ship_cmd}[args.cmd]
        try:
            return handler(args)
        except PipelineInputError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 2
    if args.cmd == "add-skin":
        return add_skin_cmd(args)
    if args.cmd == "render":
        try:
            return render_run(args)
        except PipelineInputError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 2
    if args.cmd == "stage9":
        try:
            return stage9_cmd(args)
        except PipelineInputError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 2
    if args.cmd == "wireframe":
        try:
            return wireframe_cmd(args)
        except PipelineInputError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 2
    if args.cmd == "imagedeck":
        try:
            return imagedeck_cmd(args)
        except (PipelineInputError, imagedeck.ImagedeckError) as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 2
    if args.cmd == "refine":
        try:
            return refine_cmd(args)
        except PipelineInputError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 2
    if args.cmd == "research":
        try:
            return research_cmd(args)
        except PipelineInputError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 2
    if args.cmd == "curate":
        try:
            return curate_cmd(args)
        except (PipelineInputError, ValueError) as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 2
    if args.cmd == "company":
        try:
            return company_cmd(args)
        except (PipelineInputError, ValueError) as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 2
    if args.cmd == "approve":
        try:
            return approve_cmd(args)
        except PipelineInputError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 2
    if args.cmd == "archive":
        try:
            return archive_cmd(args)
        except (PipelineInputError, archive.ArchiveError) as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 2
    return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
