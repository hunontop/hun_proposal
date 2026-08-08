# -*- coding: utf-8 -*-
"""디자인 고도화 목표 명세 계약 — design_spec.json 검증·형태 레퍼런스 수집·핸드오프 (W23, 결정 15·16·17).

공정 위치: ④ 기본 디자인(stage9) 후, 평가(deck_review) 전. 다짜고짜 디자인하지 않는다:

  (a) [명세] 장표별 "디자인 목표"를 텍스트로 먼저 명세(무엇을·왜 + 이미지 종류 판정)
      → build_prompt가 자기완결 프롬프트를, 명세자(LLM)가 design_spec.json을 run 루트에 쓴다.
  (b) [레퍼런스] 그 명세를 질의로 형태 기준(frame×piece) 레퍼런스를 결정론 수집(0토큰).
      의미 범주가 아니라 형태 축이다 — "2x3 그리드가 필요하다"면 원전 원칙이 무엇이든 그
      형태의 조각을 차용한다. 없으면 지어내지 말고 catalog_gap을 선언한다.
  (c) [체크포인트] 사람이 design_spec.json + design_refs/를 검토·조정(완성 디자인보다 먼저,
      값싸게). 확정 후에만 실행 핸드오프로 넘어간다.
  (d) [핸드오프] 실행자(Claude Design 등)에게 내용 동결 계약과 함께 번들을 준다. 산출물 회수는
      기존 채널(stage9 --apply의 override 병합, 또는 approve --ingest의 diff 심판)을 재사용한다.

이 모듈은 app/render/wireframe.py의 자매다 — 같은 문법(오류=계약 위반·SSOT 안전 / 경고=표면화,
지어내지 말고 catalog_gap 선언)을 형태 목표 명세 축에 적용한다.

design_spec.json 스키마(run 루트, 명세자 LLM 작성):
    {"schema_version": 1, "run_id": "...", "generated_by": "명세자 식별(모델/세션)",
     "slides": [{"slide_id": "s01", "goal": "무엇을·왜(필수)",
                 "treatment": ["infographic"], "image_kind": "evidence|mood|conceptual|none",
                 "none_reason": "image_kind=none일 때 필수(한 줄 사유)",
                 "source_route": "codex_gen|user_asset|client_asset|web_sample (none이 아닐 때, 선택 — 미지정 시 기본값)",
                 "form_needs": [{"kind": "piece|frame", "id": "matrix_2x2", "why": "..."}],
                 "content_gap": null}],
     "catalog_gap": [{"slide_id": "s03", "need": "형태 서술", "why": "..."}]}

W27 P2(D5): image_kind=none은 none_reason 필수 — 이미지 수요를 무압력으로 도망가지 못하게
한다. image_kind≠none은 source_route로 수급처를 명시(미지정 시 validate()가 기본값을
채운다: mood/conceptual→codex_gen, evidence→user_asset). 이 검증은 refine --collect
(신규 수거) 경로에서만 적용된다 — 레거시 run의 기 수거 design_spec.json을 소급 재검증하는
경로는 없다(계약 변경은 신규 수거 시에만, 레거시 run 소급 금지 원칙).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import shutil
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
SPEC_NAME = "design_spec.json"
REFS_DIRNAME = "design_refs"
MANIFEST_NAME = "refs_manifest.json"
KNOWLEDGE_REFS_DIRNAME = "knowledge"  # design_refs/knowledge/<카드슬러그>/
KNOWLEDGE_REFS_LIMIT = 6  # 카드당 최대 이미지 장수(캐러셀 앞에서부터)

ROOT = Path(__file__).resolve().parents[2]  # 레포 루트(app/render/design_spec.py 기준)
PIPELINE_CONFIG_PATH = ROOT / "proposal_system" / "config" / "pipeline.config.json"

# 지식 카드 레이어 디렉터리(<개발 원본 전용 경로> 하위) — 실측 2026-07-15.
_CARD_LAYER_DIRS = {"wireframe": "와이어프레임", "theme": "테마"}
_IG_ID_RE = re.compile(r"ig_\d+")
_WATCH_FOR_MARKERS = ("**조작적 정의**", "**교정 규칙**")

# image_kind 어휘 고정 4종 — 벗어나면 error(치는 것은 검증기의 소관, 프롬프트는 판정 근거만 설명).
IMAGE_KINDS = ("evidence", "mood", "conceptual", "none")
IMAGE_KIND_POLICY = (
    "evidence=실자산 필수(자동 생성 금지 — 결정 5·6 대칭) / "
    "mood·conceptual=생성 개방 / none=이미지 불필요"
)
# 사용자 조정(2026-07-13, 5차 재개): 이미지 생성을 적극 고려하라 — 명세가 none으로 도망가면
# 생성 개방 경로(mood·conceptual)가 실행 단계에서 쓰일 기회 자체가 사라진다.
IMAGE_GENERATION_GUIDANCE = (
    "이미지 생성(mood·conceptual)을 적극 고려하라 — 이미지가 이해·설득을 보조할 수 있으면 "
    "none으로 남기지 말고 goal에 생성 방향(무엇을 그릴지·어떤 톤인지)을 함께 서술하라. "
    "none은 이미지가 정말 불필요할 때만. 단 evidence 판정 슬라이드는 생성 금지가 우선한다."
)

# W27 P2(D5·D6·D7): 이미지 수요·수급 — image_kind=none은 사유 필수(수요 신호 무압력 방지),
# image_kind≠none은 수급처(source_route)를 명시한다. 어휘는 design_spec 축(장표 단위) —
# image_slots.py의 슬롯 단위 source_route(선택)와 이름은 같으나 별개 필드다(레이어 분리).
SOURCE_ROUTES = ("codex_gen", "user_asset", "client_asset", "web_sample")
_DEFAULT_SOURCE_ROUTE = {"evidence": "user_asset", "mood": "codex_gen", "conceptual": "codex_gen"}
SOURCE_ROUTE_POLICY = (
    "codex_gen=생성 / user_asset=제안사 실자산 / client_asset=발주처 자산 / web_sample=웹 검색 샘플"
)
NONE_REASON_GUIDANCE = (
    "image_kind=none인 장표는 none_reason(한 줄 사유, 예: '텍스트 위계만으로 충분')이 필수다 — "
    "사유 없는 none은 검증 오류(수요 신호 무압력 방지, 결정 D5). "
    "none이 아닌 장표는 source_route로 수급처를 지정하라(" + SOURCE_ROUTE_POLICY + "). "
    "미지정 시 mood·conceptual은 codex_gen, evidence는 user_asset으로 기본값이 채워진다."
)

# treatment 권장 어휘 — 자유 문자열 허용(검증은 리스트 타입만).
TREATMENT_VOCAB = (
    "icon_support", "infographic", "photo", "diagram", "chart_upgrade",
    "typography", "layout_variation", "none",
)


def _compose():
    try:
        from . import compose  # 패키지 컨텍스트
    except ImportError:
        import compose  # top-level(sys.path에 app/render)
    return compose


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


# --- run 산출물 모듈 관례(design_brief.py 패턴) ------------------------------

def spec_path(run: "str | Path") -> Path:
    return Path(run) / SPEC_NAME


def exists(run: "str | Path") -> bool:
    return spec_path(run).is_file()


def load(run: "str | Path") -> "dict | None":
    p = spec_path(run)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save(run: "str | Path", spec: dict) -> Path:
    p = spec_path(run)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


# --- 검증 --------------------------------------------------------------------

def validate(spec: dict, deck: dict) -> dict:
    """계약 검증 → {"errors": [...], "warnings": [...], "stats": {...}, "catalog_gap": [...]}.

    문법은 wireframe.validate와 동일: 오류=계약 위반(적용 중단), 경고=표면화 대상.
    """
    contracts = _compose()._contracts()
    frames, pieces = contracts["frames"], contracts["pieces"]
    errors: list[str] = []
    warnings: list[str] = []
    gaps: list[dict] = []

    slides = spec.get("slides")
    if not isinstance(slides, list) or not slides:
        return {"errors": ["design_spec.slides가 비어 있음"], "warnings": [], "stats": {}, "catalog_gap": []}

    deck_by_id = {str(s.get("slide_id")): s for s in deck.get("slides", [])}
    spec_ids: set = set()
    form_needs_n = 0
    content_gaps_n = 0

    for ent in slides:
        if not isinstance(ent, dict):
            continue
        sid = str(ent.get("slide_id"))
        spec_ids.add(sid)
        if sid not in deck_by_id:
            errors.append(f"slide {sid}: deck.json에 없는 slide_id")
            continue

        goal = ent.get("goal")
        if not goal or not str(goal).strip():
            errors.append(f"slide {sid}: goal 없음 — 의도 먼저다, goal 없는 명세는 계약 위반")

        treatment = ent.get("treatment")
        if treatment is not None and not isinstance(treatment, list):
            errors.append(f"slide {sid}: treatment는 리스트여야 함(자유 문자열 허용, 타입만 검증)")

        knowledge_cards = ent.get("knowledge_cards")
        if knowledge_cards is not None:
            if not isinstance(knowledge_cards, list) or not all(isinstance(x, str) for x in knowledge_cards):
                errors.append(
                    f"slide {sid}: knowledge_cards는 문자열 슬러그 리스트여야 함 — "
                    "모르는 슬러그는 오류가 아니라 collect 때 gap으로 표면화된다"
                )

        image_kind = ent.get("image_kind")
        if image_kind not in IMAGE_KINDS:
            errors.append(
                f"slide {sid}: image_kind '{image_kind}' 미지원 — 허용 어휘 {IMAGE_KINDS} 중 하나여야 함"
            )
        elif image_kind == "none":
            none_reason = ent.get("none_reason")
            if not none_reason or not str(none_reason).strip():
                errors.append(
                    f"slide {sid}: image_kind=none인데 none_reason 없음 - "
                    "사유 없는 생략은 계약 위반(수요 신호 무압력 방지, W27 D5)"
                )
        else:
            source_route = ent.get("source_route")
            if source_route is None:
                # 검증기가 기본값을 채운다 — 소비자(collect_refs/handoff 등)가 분기하기 쉽게.
                ent["source_route"] = _DEFAULT_SOURCE_ROUTE.get(image_kind, "codex_gen")
            elif source_route not in SOURCE_ROUTES:
                errors.append(
                    f"slide {sid}: source_route '{source_route}' 미지원 - "
                    f"허용 어휘 {SOURCE_ROUTES} 중 하나여야 함"
                )

        for need in ent.get("form_needs") or []:
            if not isinstance(need, dict):
                continue
            form_needs_n += 1
            kind = need.get("kind")
            nid = need.get("id")
            if kind == "piece":
                if nid not in pieces:
                    errors.append(
                        f"slide {sid}: piece '{nid}' 미정의 — 지어내지 말고 catalog_gap에 선언하라"
                    )
            elif kind == "frame":
                if nid not in frames:
                    errors.append(
                        f"slide {sid}: frame '{nid}' 미정의 — 지어내지 말고 catalog_gap에 선언하라"
                    )
            else:
                errors.append(
                    f"slide {sid}: form_needs.kind '{kind}' 미지원(piece|frame) — "
                    "지어내지 말고 catalog_gap에 선언하라"
                )

        if ent.get("content_gap"):
            content_gaps_n += 1
            warnings.append(
                f"slide {sid}: 디자인이 내용을 더 요구 — 내용 루프로 백 후보(결정 15)"
            )

    for sid in deck_by_id:
        if sid not in spec_ids:
            warnings.append(f"slide {sid}: design_spec에 없음 — 전수 명세 권장")

    for g in spec.get("catalog_gap") or []:
        if isinstance(g, dict):
            gaps.append(g)

    stats = {
        "slides_spec": len(slides),
        "form_needs": form_needs_n,
        "catalog_gap": len(gaps),
        "content_gaps": content_gaps_n,
    }
    return {"errors": errors, "warnings": warnings, "stats": stats, "catalog_gap": gaps}


# --- 지식 카드 레퍼런스(D1·D2, W27 P1a) --------------------------------------
# 카드(텍스트) → examples 링크(폴백: 카드 자신 source) → grouped-images/ig_<id>/*.jpg.
# 저작권 경계: 여기서 복사되는 jpg는 run 내부 참고용 사본일 뿐이다 — deck.html 등
# 산출물에 임베드하지 않는다(레퍼런스 실물 대조는 실행자가 눈으로 보는 용도).

def _load_pipeline_config() -> dict:
    try:
        return json.loads(PIPELINE_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _reference_images_root() -> "Path | None":
    """config.knowledge.reference_images_root — 없거나 폴더가 없으면 None(하드 실패 금지)."""
    raw = (_load_pipeline_config().get("knowledge") or {}).get("reference_images_root")
    if not raw:
        return None
    p = Path(raw)
    if not p.is_absolute():
        p = ROOT / p
    return p if p.is_dir() else None


def _parse_card_md(path: Path) -> dict:
    """단순 줄 파싱(yaml 라이브러리 미사용) — frontmatter(key: value) + 본문."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    meta: dict[str, str] = {}
    body_lines: list[str] = []
    in_fm = False
    fm_done = False
    for line in lines:
        if not fm_done and line.strip() == "---":
            if not in_fm:
                in_fm = True
            else:
                in_fm = False
                fm_done = True
            continue
        if in_fm:
            if ":" not in line:
                continue
            key, _, val = line.partition(":")
            meta[key.strip()] = val.strip()
        elif fm_done:
            body_lines.append(line)
    meta["_body"] = "\n".join(body_lines)
    return meta


def _parse_bracket_list(raw: str) -> list[str]:
    """`examples: [a, b]` 형식 값 파싱 — 비어있으면 []."""
    raw = (raw or "").strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    return [x.strip() for x in raw.split(",") if x.strip()]


def _extract_ig_ids(source_raw: str) -> list[str]:
    """`source: peedori_ ig_123, ig_456` → ["ig_123", "ig_456"]."""
    return _IG_ID_RE.findall(source_raw or "")


def _extract_watch_for(body: str) -> "str | None":
    """본문에서 "**조작적 정의**" 또는 "**교정 규칙**" 이하를 그대로 발췌."""
    lines = (body or "").splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        for marker in _WATCH_FOR_MARKERS:
            if not stripped.startswith(marker):
                continue
            collected: list[str] = []
            rest = stripped[len(marker):].lstrip(": ").strip()
            if rest:
                collected.append(rest)
            for nxt in lines[i + 1:]:
                nxt_s = nxt.strip()
                if not nxt_s:
                    if collected:
                        break
                    continue
                if nxt_s.startswith("[["):
                    break
                collected.append(nxt_s)
            if collected:
                return "\n".join(collected)
    return None


def _find_card_file(cards_root: Path, slug: str) -> "tuple[Path, str] | None":
    """카드 슬러그 → (경로, 디렉터리기반 layer). examples/ 카드 직접 인용도 허용."""
    for layer, dirname in _CARD_LAYER_DIRS.items():
        p = cards_root / dirname / f"{slug}.md"
        if p.is_file():
            return p, layer
    p = cards_root / "examples" / f"{slug}.md"
    if p.is_file():
        return p, "example"
    return None


def _collect_ig_images(images_root: Path, ig_ids: list[str], limit: int = KNOWLEDGE_REFS_LIMIT) -> list[Path]:
    """ig id 순서대로 grouped-images/ig_<id>/*.jpg를 모아 상한까지(캐러셀 앞에서부터)."""
    out: list[Path] = []
    grouped = images_root / "grouped-images"
    for ig_id in ig_ids:
        folder = grouped / ig_id
        if not folder.is_dir():
            continue
        for img in sorted(folder.glob("*.jpg")):
            out.append(img)
            if len(out) >= limit:
                return out
    return out


def _resolve_card(cards_root: Path, images_root: Path, slug: str) -> dict:
    """카드 슬러그 → {"layer","claim","watch_for","resolved_via","images"(Path 리스트),"gap"}.

    해석 순서: 카드의 examples: 링크(비어있지 않으면) → 그 example 카드들의 source ig 폴더.
    examples가 비면 폴백 = 카드 자신의 source: ig 폴더. 카드/이미지가 없으면 지어내지 않고
    gap 사유를 채운다(images=[]).
    """
    found = _find_card_file(cards_root, slug)
    if not found:
        return {
            "layer": None, "claim": "", "watch_for": "", "resolved_via": "source",
            "images": [], "gap": f"카드 파일 없음: {slug}",
        }
    path, dir_layer = found
    meta = _parse_card_md(path)
    layer = meta.get("layer") or dir_layer
    claim = meta.get("claim") or meta.get("proves") or ""
    watch_for = _extract_watch_for(meta.get("_body", "")) or claim

    examples_list = _parse_bracket_list(meta.get("examples", ""))
    ig_ids: list[str] = []
    if examples_list:
        resolved_via = "examples"
        for ex_slug in examples_list:
            ex_path = cards_root / "examples" / f"{ex_slug}.md"
            if not ex_path.is_file():
                continue
            ex_meta = _parse_card_md(ex_path)
            ig_ids.extend(_extract_ig_ids(ex_meta.get("source", "")))
    else:
        resolved_via = "source"
        ig_ids = _extract_ig_ids(meta.get("source", ""))

    if not ig_ids:
        return {
            "layer": layer, "claim": claim, "watch_for": watch_for, "resolved_via": resolved_via,
            "images": [], "gap": "레퍼런스 ig 폴더를 찾지 못함(examples/source 모두 무효)",
        }

    images = _collect_ig_images(images_root, ig_ids)
    if not images:
        return {
            "layer": layer, "claim": claim, "watch_for": watch_for, "resolved_via": resolved_via,
            "images": [], "gap": f"이미지 폴더 없음/비어있음: {ig_ids}",
        }
    return {
        "layer": layer, "claim": claim, "watch_for": watch_for, "resolved_via": resolved_via,
        "images": images, "gap": None,
    }


def _collect_knowledge_refs(run: Path, refs_dir: Path, spec: dict) -> list[dict]:
    """spec.slides[*].knowledge_cards 유니크 목록 → 카드별 레퍼런스 jpg 수집(멱등).

    reference_images_root 미설정/부재면 경고 1줄 + 스킵([] 반환) — 하드 실패 금지
    (독립 배포 호환, 결정 D1·§3 P1a).
    """
    images_root = _reference_images_root()
    if images_root is None:
        print(
            "[design_spec] 지식 카드 레퍼런스 루트 미설정 또는 부재 - 레퍼런스 수집 스킵"
            "(config: knowledge.reference_images_root)"
        )
        return []
    cards_root = images_root / "cards"

    slides_by_card: dict[str, list[str]] = {}
    for ent in spec.get("slides") or []:
        if not isinstance(ent, dict):
            continue
        sid = str(ent.get("slide_id"))
        for slug in ent.get("knowledge_cards") or []:
            if not isinstance(slug, str) or not slug.strip():
                continue
            bucket = slides_by_card.setdefault(slug, [])
            if sid not in bucket:
                bucket.append(sid)

    knowledge_dir = refs_dir / KNOWLEDGE_REFS_DIRNAME
    out: list[dict] = []
    for slug, sids in slides_by_card.items():
        resolved = _resolve_card(cards_root, images_root, slug)
        if resolved.get("gap"):
            print(f"[design_spec] 지식 카드 레퍼런스 갭: {slug} - {resolved['gap']}")
            out.append({
                "card": slug, "layer": resolved.get("layer"), "claim": resolved.get("claim", ""),
                "watch_for": resolved.get("watch_for", ""), "slides": sids, "images": [],
                "resolved_via": resolved.get("resolved_via", "source"), "gap": resolved["gap"],
            })
            continue

        dest_dir = knowledge_dir / slug
        dest_dir.mkdir(parents=True, exist_ok=True)
        rel_images: list[str] = []
        for src in resolved["images"]:
            dest_name = f"{src.parent.name}_{src.name}"
            dest = dest_dir / dest_name
            if not dest.exists():  # 멱등 — 이미 있으면 재복사 안 함
                shutil.copyfile(src, dest)
            rel_images.append(f"{REFS_DIRNAME}/{KNOWLEDGE_REFS_DIRNAME}/{slug}/{dest_name}")
        out.append({
            "card": slug, "layer": resolved.get("layer"), "claim": resolved.get("claim", ""),
            "watch_for": resolved.get("watch_for", ""), "slides": sids, "images": rel_images,
            "resolved_via": resolved.get("resolved_via", "source"), "gap": None,
        })
    return out


# --- 레퍼런스 수집(결정론 — LLM 0토큰) ---------------------------------------

def collect_refs(run: "str | Path", spec: dict) -> dict:
    """spec의 form_needs에서 (kind, id) 유니크 목록을 뽑아 run/design_refs/에 수집.

    piece → catalog_previews/<id>.png 복사. frame → 복사할 프리뷰가 없으니 frames.json의
    정의 요약만 기록(file=null). 미지 kind/id는 gap=true로 표면화(지어내지 않는다).
    반환 = refs_manifest.json과 동일한 dict.
    """
    run = Path(run)
    refs_dir = run / REFS_DIRNAME
    refs_dir.mkdir(parents=True, exist_ok=True)

    contracts = _compose()._contracts()
    frames, pieces = contracts["frames"], contracts["pieces"]
    catalog_dir = _compose()._CONTRACT_DIR / "catalog_previews"

    per_slide: dict[str, list[dict]] = {}
    collected_gaps: list[dict] = []

    for ent in spec.get("slides") or []:
        if not isinstance(ent, dict):
            continue
        sid = str(ent.get("slide_id"))
        items: list[dict] = []
        for need in ent.get("form_needs") or []:
            if not isinstance(need, dict):
                continue
            kind = need.get("kind")
            nid = need.get("id")
            purpose = need.get("why") or ent.get("goal") or ""
            if kind == "piece" and nid in pieces:
                src = catalog_dir / f"{nid}.png"
                if src.is_file():
                    dest = refs_dir / f"{nid}.png"
                    shutil.copyfile(src, dest)
                    items.append({
                        "purpose": purpose, "kind": kind, "id": nid,
                        "file": f"{REFS_DIRNAME}/{nid}.png", "gap": False,
                    })
                else:
                    items.append({"purpose": purpose, "kind": kind, "id": nid, "file": None, "gap": True})
                    collected_gaps.append({"slide_id": sid, "kind": kind, "id": nid, "why": purpose})
            elif kind == "frame" and nid in frames:
                fdef = frames[nid]
                summary = {k: fdef.get(k) for k in ("label", "slots", "use", "n", "variants") if k in fdef}
                items.append({
                    "purpose": purpose, "kind": kind, "id": nid,
                    "file": None, "gap": False, "frame_def": summary,
                })
            else:
                items.append({"purpose": purpose, "kind": kind, "id": nid, "file": None, "gap": True})
                collected_gaps.append({"slide_id": sid, "kind": kind, "id": nid, "why": purpose})
        if items:
            per_slide[sid] = items

    knowledge_refs = _collect_knowledge_refs(run, refs_dir, spec)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "per_slide": per_slide,
        "catalog_gap": list(spec.get("catalog_gap") or []) + collected_gaps,
        "knowledge_refs": knowledge_refs,
        "sources_note": (
            "원전 crop 원형 = packs/core/catalog_previews/원전_원형/ (사람 열람용) · "
            "지식 카드 레퍼런스 jpg = run 내부 참고용 사본(산출물 임베드 금지)"
        ),
    }
    (refs_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


# --- 결정기(명세자) 프롬프트 번들 --------------------------------------------

def _vocab_table() -> str:
    contracts = _compose()._contracts()
    lines = ["### frame (형태 축 — 콘텐츠 영역 슬롯 분할, 7종)"]
    for f in contracts["frames"].values():
        lines.append(f"- `{f['id']}`: {f.get('label', '')} — {f.get('use', '')}")
    lines.append("")
    lines.append("### piece (형태 축 — 원전 원칙의 원자 표현, 25종)")
    for p in contracts["pieces"].values():
        lines.append(f"- `{p['id']}` [{p.get('group', '')}] — {p.get('source', '')}")
    return "\n".join(lines)


_SPEC_SCHEMA_EXAMPLE = """{
  "schema_version": 1,
  "run_id": "...",
  "generated_by": "명세자 식별(모델/세션)을 여기에",
  "slides": [
    {"slide_id": "3", "goal": "이 장표가 시각적으로 달성할 것(무엇을·왜)",
     "treatment": ["infographic"], "image_kind": "conceptual", "source_route": "codex_gen",
     "form_needs": [{"kind": "piece", "id": "matrix_2x2", "why": "현위치 대비 목표 사분면을 대비시킨다"}],
     "knowledge_cards": ["빈공간-마감"],
     "content_gap": null},
    {"slide_id": "4", "goal": "표만으로 충분한 장표", "treatment": [], "image_kind": "none",
     "none_reason": "텍스트 위계만으로 충분 — 이미지가 오히려 산만하게 한다"}
  ],
  "catalog_gap": [{"slide_id": "5", "need": "형태 서술(자유문)", "why": "왜 필요한지"}]
}"""


def build_prompt(
    run: "str | Path", deck: dict, *,
    design_brief: "dict | None" = None,
    wireframe: "dict | None" = None,
    gating: "dict | None" = None,
) -> str:
    """명세자(LLM)에게 줄 자기완결 프롬프트 — 현행 장표 상태 + 어휘 + 규칙 + 스키마."""
    run = Path(run)
    lr = (gating or {}).get("length_rhythm") or {}
    band_by_sid = {str(v.get("slide_id")): v for v in (lr.get("band_violations") or [])}

    parts = [
        "# 디자인 고도화 목표 명세 — ④+ (내용 동결 후, 형태·연출 목표만)",
        "",
        "너는 **디자인 고도화 목표 명세자**다. 다짜고짜 디자인하지 않는다 — 각 장표의 디자인",
        "목표를 텍스트로 먼저 명세한다(무엇을·왜 + 이미지 종류 판정). 형태 레퍼런스 수집과",
        "실행은 이후 결정론 단계(--collect/--handoff)가 한다 — 너는 목표만 쓴다.",
        "",
        "## 절대 규칙",
        "1. **내용 불변** — 텍스트·수치는 deck.json이 정본이다. 명세는 시각 목표만 서술한다",
        "   (창작·요약·수치 변경 금지).",
        "2. **form_needs는 형태/구조 축으로 질의하라(의미 범주가 아니다).** \"2x3 그리드가",
        "   필요하다\"처럼 형태로 말하라 — 어느 원전 원칙이든 그 형태의 조각을 차용한다.",
        "3. 원하는 형태가 아래 어휘에 없으면 **지어내지 말고 catalog_gap에 선언**하라.",
        f"4. image_kind 판정은 필수다({IMAGE_KIND_POLICY}).",
        f"   {IMAGE_GENERATION_GUIDANCE}",
        "5. 디자인이 내용 보강을 요구하면 **content_gap에 서술**하라(임의 창작 금지 —",
        "   내용 루프로 백 후보가 된다, 결정 15).",
        "6. 장표별로 적용할 디자인지식 카드를 `knowledge_cards`(슬러그 배열)로 인용하라",
        "   (공유뇌 ref/디자인지식/ 검색 결과의 name 슬러그). 특히 빈 공간·픽토그램·배치",
        "   판단의 근거 카드를 명시하라.",
        "7. 장표마다 \"사람 디자이너라면 여기 사진/이미지를 넣겠는가\"를 판단해 image_kind를",
        "   답하라. none이면 none_reason 한 줄(예: '텍스트 위계만으로 충분'). none이 아니면",
        "   source_route로 수급처를 지정하라(" + SOURCE_ROUTE_POLICY + ").",
        "",
        f"treatment 권장 어휘(자유 문자열 허용): {', '.join(TREATMENT_VOCAB)}",
        "",
        "## 어휘 (형태 축 — 이 밖의 frame/piece id는 지어내지 말고 catalog_gap으로)",
        _vocab_table(),
        "",
        "## 출력 스키마 (design_spec.json — run 루트에 저장)",
        "```json", _SPEC_SCHEMA_EXAMPLE, "```",
        "",
    ]
    if design_brief:
        try:
            import design_brief as design_brief_mod  # sibling(proposal_system/scripts)
            parts += ["## design_brief 요약", design_brief_mod.render_for_prompt(design_brief), ""]
        except Exception:
            pass
    parts.append("## 현행 장표 상태 (deck.json 발췌 — slide_id·role·title·key_message·현행 형태)")
    wf_slides = {str(e.get("slide_id")): e for e in (wireframe or {}).get("slides", [])} if wireframe else {}
    for s in deck.get("slides", []):
        sid = str(s.get("slide_id"))
        parts.append(f"### slide {sid} — role={s.get('role')}")
        parts.append(f"제목: {s.get('title')}")
        if s.get("key_message"):
            parts.append(f"키메시지: {s.get('key_message')}")
        slots = s.get("slots")
        wf_ent = wf_slides.get(sid)
        if slots:
            pieces_here = [x.get("piece") for x in slots if isinstance(x, dict)]
            parts.append(f"현행 형태: frame={s.get('frame')} pieces={pieces_here}")
        elif wf_ent:
            parts.append(f"현행 형태(와이어프레임): frame={wf_ent.get('frame')}")
        else:
            parts.append(f"현행 형태: template_id={s.get('template_id')}")
        if s.get("example"):
            parts.append("주의: [예시] 슬라이드 — 정직성 배지 보존 필수.")
        band = band_by_sid.get(sid)
        if band:
            parts.append(f"분량 리듬: 밴드 위반({band.get('kind')}, words={band.get('words')}/band={band.get('band')})")
        parts.append("")
    return "\n".join(parts)


# --- 실행 핸드오프 ------------------------------------------------------------

def build_handoff(
    run: "str | Path", spec: dict, manifest: dict, user_refs: "dict | None" = None
) -> str:
    """실행자(Claude Design 등)에게 줄 번들 — 명세+레퍼런스대로 deck.html의 시각을 격상하라.

    계약 5조(불변): ①본문 텍스트·수치 불변(내용 동결 — deck.json 정본) ②정직성 장치 보존
    ([예시] 배지·워터마크·검토요망 바·출처요망 딱지) ③evidence 이미지 자동생성 금지(실자산만)
    ④산출물 = (A) design_overrides.json 확장 → `stage9 --apply`로 검증·병합(권장) 또는
    (B) 완성 HTML → `approve --ingest`로 diff 심판·freeze ⑤content_gap 발견 시 임의 보강
    금지 — 목록 보고(내용 루프로 백).

    user_refs(선택) = curate.scan_intake(run) 결과 {"files","links"} — 사람이 design_refs/에
    직접 넣은 참고 파일·링크. 있으면 별도 절로 실어 실행자에게 함께 전달한다(§5-④-③).
    """
    run = Path(run)
    per_slide = manifest.get("per_slide") or {}
    urefs = user_refs or {}
    uref_files = urefs.get("files") or []
    uref_links = urefs.get("links") or []
    has_user_refs = bool(uref_files or uref_links)
    parts = [
        "# 디자인 고도화 실행 핸드오프 (④+ · 내용 동결 · diff 심판)",
        "",
        "너는 **디자인 고도화 실행자**(Claude Design 등)다. 아래 명세와 레퍼런스대로",
        f"{run / 'deck.html'} 의 시각을 격상하라 — 내용은 이미 동결되어 있다.",
        "",
        "## 입력",
        f"- 현재 병합본: {run / 'deck.html'}",
        f"- 형태 레퍼런스: {run / REFS_DIRNAME}/ (개별 조각 프리뷰 png + {MANIFEST_NAME})",
        f"- 장표별 명세: {spec_path(run)}",
    ]
    if has_user_refs:
        parts.append(f"- **사용자 제공 레퍼런스**: {run / REFS_DIRNAME}/ (파일 {len(uref_files)} · 링크 {len(uref_links)}) — 아래 절")
    parts.append("")
    parts.extend([
        "## 계약 5조 (불변 — 어기면 폐기)",
        "1. **본문 텍스트·수치 불변** — deck.json이 정본이다. 문구·수치를 새로 짓거나 고치지 마라.",
        "2. **정직성 장치 보존** — [예시] 배지·워터마크·검토요망 바·출처요망 딱지를 지우거나 가리지 마라.",
        "3. **evidence 이미지 자동 생성 금지** — image_kind=evidence 슬라이드는 실자산만 쓴다.",
        "4. 산출물 회수는 둘 중 하나: "
        "(A) design_overrides.json을 확장해 `stage9 --apply`로 검증·병합(권장) "
        "또는 (B) 완성 HTML을 `approve --ingest`로 넘겨 diff 심판·freeze.",
        "5. content_gap을 발견해도 임의로 보강하지 마라 — 목록으로 보고하라(내용 루프로 백).",
        "",
        "## 장표별 명세 표 (goal · treatment · image_kind · refs)",
    ])
    for ent in spec.get("slides") or []:
        sid = str(ent.get("slide_id"))
        refs = per_slide.get(sid) or []
        ref_desc = ", ".join(
            f"{r.get('kind')}:{r.get('id')}" + ("(catalog_gap)" if r.get("gap") else "")
            for r in refs
        ) or "-"
        parts.append(
            f"- slide {sid}: goal=\"{ent.get('goal')}\" treatment={ent.get('treatment')} "
            f"image_kind={ent.get('image_kind')} refs=[{ref_desc}]"
        )
    if has_user_refs:
        parts.append("")
        parts.append("## 사용자 제공 레퍼런스 (사람이 직접 넣음 — 참고만, 계약 5조 우선)")
        parts.append(f"위치: {run / REFS_DIRNAME}/ · 이 자료는 톤·방향 참고용이다. 본문 내용·정직성 장치는 계약 5조가 이긴다.")
        for f in uref_files:
            parts.append(f"- 파일: `{REFS_DIRNAME}/{f}`")
        for u in uref_links:
            parts.append(f"- 링크: {u}")

    knowledge_refs = manifest.get("knowledge_refs") or []
    if knowledge_refs:
        parts.append("")
        parts.append("## 레퍼런스 실물 (반드시 보고 작업)")
        parts.append(
            "direct 모드면 이 세션이 아래 이미지 파일을 직접 Read해서 보고, 결과물이 이 레퍼런스"
            " 수준인지 자가 대조하라(secure 모드는 사람이 직접 첨부·대조한다)."
        )
        for kr in knowledge_refs:
            slides_desc = ", ".join(kr.get("slides") or []) or "-"
            parts.append("")
            parts.append(f"### 카드: {kr.get('card')} (layer={kr.get('layer')}, slides: {slides_desc})")
            parts.append(f"- claim: {kr.get('claim')}")
            if kr.get("watch_for"):
                parts.append(f"- watch_for(조작적 정의/교정 규칙): {kr.get('watch_for')}")
            if kr.get("gap"):
                parts.append(f"- gap: {kr.get('gap')} — 레퍼런스 실물 없음, 카드 텍스트만 참고")
            else:
                for img in kr.get("images") or []:
                    parts.append(f"  - {run / img}")

    gaps = manifest.get("catalog_gap") or []
    if gaps:
        parts.append("")
        parts.append("## catalog_gap (형태 어휘에 없음 — 지어내지 말 것, 사람 판단 대상)")
        for g in gaps:
            parts.append(f"- slide {g.get('slide_id')}: {g.get('id') or g.get('need')} — {g.get('why', '')}")
    return "\n".join(parts)
