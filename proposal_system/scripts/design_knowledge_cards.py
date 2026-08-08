# -*- coding: utf-8 -*-
"""디자인지식 카드 운반 배선 (δ패킷, W31, 2026-07-30 확정).

공정 위치: 와이어프레임 결정기(A6, app/render/wireframe.py)가 장별로 `knowledge_cards`
(디자인지식 카드 name 슬러그)를 이미 고른다 — 그러나 imagedeck의 장별 이미지 생성 프롬프트에는
**이름만** 실려 생성기(Codex)는 그 카드가 무슨 내용인지 모른다. 이 모듈이 메우는 배선 =
**선택된 카드의 본문(조작적 정의 발췌)과 실물 레퍼런스 이미지를 장별 프롬프트에 동봉**한다.

⚠️ 이것은 W27 P1a에서 기각된 "기계 무차별 주입"이 아니다. 카드 선택(무엇을 실을지)은
A6 결정기(LLM)가 pull로 이미 했다 — 이 모듈은 그 선택분만 결정론으로 운반(bundle)할 뿐,
스스로 카드를 고르거나 지어내지 않는다(design_spec.py의 R9 축B 카드 인용과 같은 문법 —
"선택은 LLM, 운반은 코드"). knowledge_cards가 비어 있으면(A6가 카드를 안 골랐으면) 이 모듈은
아무것도 하지 않는다(조용한 무동작 — 강제 주입 아님).

카드 정본(온디스크, vault): `<vault_dir>/와이어프레임/<name>.md`(형태, 1순위) ·
`<vault_dir>/테마/<name>.md`(색, 2순위) · `<vault_dir>/examples/<name>.md`(비포애프터, 3순위).
카드 형식 = frontmatter(name·claim·layer·examples·때때로 ref_images 다중 포인터) + 본문
("**조작적 정의**"/"**교정 규칙**" 절 우선, 없으면 본문 첫 문단).

실물 이미지는 `design://<상대경로>` 포인터(카드 frontmatter `ref_images:`)로 참조된다 —
해석 규칙(공유뇌 ref/policy/자산-경로-체계, 2026-07-24 수립)은
`<knowhow_root_file 내용>/design/<상대경로>`. `knowhow_root_file`(기본 `~/.knowhow-root`)이
없으면 문서화된 전역 기본값(`<개발 원본 전용 경로>`)으로 폴백한다(실측 전제 — 기계-국소 쪽지 파일이라
독립 배포판에는 아예 없을 수 있다).

⚠️ `sources/books/프레젠테이션-디자인/` 시드(153개 원본)는 status: unverified — 카드로 승격되기
전까지는 이 모듈이 조회하는 `와이어프레임/테마/examples` 세 디렉터리에 없으므로 애초에 운반
대상이 되지 않는다(카드 승격 후에만 자동으로 조회 대상에 들어온다 — 별도 예외 처리 불필요).

vault·knowhow는 **읽기 전용**이다 — 이 모듈은 절대 쓰지 않는다.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]  # proposal_system/scripts -> 레포 루트
PIPELINE_CONFIG_PATH = ROOT / "proposal_system" / "config" / "pipeline.config.json"

# 카드 레이어 디렉터리 — 조회 순서(1순위 와이어프레임 -> 테마 -> examples, design_spec.py의
# _find_card_file과 같은 관례).
_CARD_LAYER_DIRS = {"wireframe": "와이어프레임", "theme": "테마"}

# 실측 전제(공유뇌 ref/policy/자산-경로-체계, 2026-07-24): ~/.knowhow-root 파일 부재 시의
# 문서화된 전역 기본값. 파일이 있으면 그 내용이 항상 이긴다 — 이 상수는 안전망일 뿐이다.
_LEGACY_KNOWHOW_FALLBACK = Path("<개발 원본 전용 경로>")

_DESIGN_URI_PREFIX = "design://"
_LIST_ITEM_COMMENT_RE = re.compile(r"\s+#")  # `- design://... # 주석` 꼬리 주석 제거

_EXCERPT_MARKERS = ("**조작적 정의**", "**교정 규칙**")
CARD_EXCERPT_LIMIT = 600  # 카드당 발췌 상한(자) — 프롬프트 비대 방지
IMAGE_LIMIT_PER_SLIDE = 4  # 장당 구조 레퍼런스 이미지 상한 — 프롬프트 비대 방지

CARRY_HEADER = "## 장 구조 지식(뼈대 결정기 선택 - 운반)"


# --- config -------------------------------------------------------------------

def _load_pipeline_config() -> dict:
    try:
        return json.loads(PIPELINE_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _vault_dir() -> "Path | None":
    """config.design_knowledge.vault_dir — 없거나 폴더가 없으면 None(하드 실패 금지).

    독립 배포판(vault 미동봉)을 고려한 우아 생략 — 테스트는 이 함수를 monkeypatch해
    임시 폴더를 주입한다(실제 vault 의존 금지)."""
    raw = (_load_pipeline_config().get("design_knowledge") or {}).get("vault_dir")
    if not raw:
        return None
    p = Path(raw)
    if not p.is_absolute():
        p = ROOT / p
    return p if p.is_dir() else None


def _knowhow_root() -> "Path | None":
    """config.design_knowledge.knowhow_root_file(기본 ~/.knowhow-root)의 내용(절대경로 한 줄)을
    읽어 knowhow 루트를 돌려준다. 쪽지 파일이 없으면 문서화된 기본값(_LEGACY_KNOWHOW_FALLBACK)
    으로 폴백한다. config 자체가 없거나 어느 경로도 폴더가 아니면 None(우아 생략)."""
    cfg = _load_pipeline_config().get("design_knowledge") or {}
    raw = cfg.get("knowhow_root_file")
    if raw is None:
        return None
    root_file = Path(os.path.expanduser(os.path.expandvars(raw)))
    if root_file.is_file():
        try:
            lines = root_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        content = lines[0].strip() if lines else ""
        if content:
            p = Path(content)
            return p if p.is_dir() else None
    return _LEGACY_KNOWHOW_FALLBACK if _LEGACY_KNOWHOW_FALLBACK.is_dir() else None


def resolve_design_uri(uri: str, knowhow_root: "Path | None") -> "Path | None":
    """`design://<상대경로>` -> `<knowhow_root>/design/<상대경로>`. 접두어가 다르거나 루트가
    없으면 None(지어내지 않는다)."""
    if not isinstance(uri, str) or not uri.startswith(_DESIGN_URI_PREFIX):
        return None
    if knowhow_root is None:
        return None
    rel = uri[len(_DESIGN_URI_PREFIX):].strip()
    if not rel:
        return None
    return knowhow_root / "design" / Path(rel)


# --- 카드 파싱(결정론 텍스트 파싱 — YAML 라이브러리 미사용) --------------------
# design_spec.py._parse_card_md와 같은 관례(frontmatter `key: value` 줄 파싱 + 본문 분리)를
# 그대로 따르되, 이 vault의 카드는 `ref_images:`처럼 값이 다음 줄부터 `  - item` 리스트로
# 이어지는 형식을 쓰므로(design_spec.py 카드 트리에는 없던 형식) 그 확장만 추가한다.

def _maybe_list(raw: str) -> Any:
    """`[a, b]` 브래킷 한 줄 리스트를 파싱(design_spec._parse_bracket_list와 동일 문법)."""
    s = (raw or "").strip()
    if s.startswith("[") and s.endswith("]"):
        return [x.strip() for x in s[1:-1].split(",") if x.strip()]
    return raw


def _parse_card(path: Path) -> dict:
    """카드 md -> frontmatter dict(+ `_body`). 다중 항목 키(`ref_images:` 다음 줄부터
    `  - design://...  # 주석`)는 리스트로 모은다."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    meta: dict[str, Any] = {}
    body_lines: list[str] = []
    in_fm = False
    fm_done = False
    list_key: "str | None" = None
    for line in lines:
        if not fm_done and line.strip() == "---":
            if not in_fm:
                in_fm = True
            else:
                in_fm = False
                fm_done = True
            continue
        if in_fm:
            stripped = line.strip()
            if list_key is not None and stripped.startswith("- "):
                item = stripped[2:].strip()
                item = _LIST_ITEM_COMMENT_RE.split(item, 1)[0].strip()
                if item:
                    meta.setdefault(list_key, []).append(item)
                continue
            list_key = None
            if ":" not in line:
                continue
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            if not val:
                list_key = key  # 다음 줄부터 `  - item`을 모으는 리스트 헤더 후보
                meta.setdefault(key, [])
                continue
            meta[key] = _maybe_list(val)
        elif fm_done:
            body_lines.append(line)
    meta["_body"] = "\n".join(body_lines)
    return meta


def _truncate(text: str, limit: int = CARD_EXCERPT_LIMIT) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + " ...(절단)"


def _extract_excerpt(body: str, fallback_claim: str) -> str:
    """본문에서 "**조작적 정의**"(우선) 또는 "**교정 규칙**" 절을 발췌 — design_spec.py의
    _extract_watch_for와 같은 관례. 마커가 없으면 본문 첫 문단, 그마저 없으면 claim으로
    폴백한다(design_spec.py 카드 트리와 달리 이 vault는 마커 없는 카드도 있을 수 있어 추가한
    확장). 카드당 CARD_EXCERPT_LIMIT자로 절단."""
    lines = (body or "").splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        for marker in _EXCERPT_MARKERS:
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
                return _truncate("\n".join(collected))
    paragraph: list[str] = []
    for line in lines:
        s = line.strip()
        if not s:
            if paragraph:
                break
            continue
        if s.startswith("[["):
            break
        paragraph.append(s)
    if paragraph:
        return _truncate("\n".join(paragraph))
    return _truncate(fallback_claim or "")


def _find_card_file(vault: Path, name: str) -> "tuple[Path, str] | None":
    """카드 이름 -> (경로, 디렉터리기반 layer). 조회 순서: 와이어프레임(1순위) -> 테마 ->
    examples."""
    for layer, dirname in _CARD_LAYER_DIRS.items():
        p = vault / dirname / f"{name}.md"
        if p.is_file():
            return p, layer
    p = vault / "examples" / f"{name}.md"
    if p.is_file():
        return p, "example"
    return None


def load_card(name: str, *, vault: "Path | None" = None) -> dict:
    """카드 이름 -> {"name","found","layer","claim","excerpt","images","gap"}.

    "images"는 카드 자신의 ref_images + 카드가 `examples:`로 가리키는 example 카드의
    ref_images(1홉만 — example 카드는 다시 examples를 갖지 않으므로 재귀 불필요)를 합친
    [{"uri","via"}] 목록이다(design:// 해석은 carry_knowledge가 한다 — 여기는 포인터만 모음).
    """
    if vault is None:
        vault = _vault_dir()
    if vault is None:
        return {
            "name": name, "found": False, "layer": None, "claim": "", "excerpt": "",
            "images": [], "gap": "vault 미설정/부재 - 카드 운반 생략(config: design_knowledge.vault_dir)",
        }
    found = _find_card_file(vault, name)
    if not found:
        return {
            "name": name, "found": False, "layer": None, "claim": "", "excerpt": "",
            "images": [], "gap": f"카드 파일 없음: {name}",
        }
    path, dir_layer = found
    meta = _parse_card(path)
    layer = meta.get("layer") or dir_layer
    claim = meta.get("claim") or meta.get("proves") or ""
    excerpt = _extract_excerpt(meta.get("_body", ""), claim)

    images: list[dict] = []
    for uri in meta.get("ref_images") or []:
        if isinstance(uri, str) and uri.strip():
            images.append({"uri": uri.strip(), "via": name})
    for ex_name in meta.get("examples") or []:
        if not isinstance(ex_name, str) or not ex_name.strip():
            continue
        ex_path = vault / "examples" / f"{ex_name.strip()}.md"
        if not ex_path.is_file():
            continue  # 1홉 폴백일 뿐 — example 미발견은 gap이 아니다(원 카드는 찾았다).
        ex_meta = _parse_card(ex_path)
        for uri in ex_meta.get("ref_images") or []:
            if isinstance(uri, str) and uri.strip():
                images.append({"uri": uri.strip(), "via": ex_name.strip()})

    return {
        "name": name, "found": True, "layer": layer, "claim": claim, "excerpt": excerpt,
        "images": images, "gap": None,
    }


# --- 장별 운반(imagedeck.bundle이 호출하는 진입점) -----------------------------

def carry_knowledge(names: "list[str] | None") -> dict:
    """와이어프레임 slide.knowledge_cards -> 카드 본문+실물 이미지 운반 결과(결정론, 0 LLM 토큰).

    names가 비어 있으면(A6가 카드를 안 골랐으면) vault/knowhow를 건드리지도 않고 즉시 빈
    결과를 돌려준다(카드 미인용 run의 프롬프트 바이트를 그대로 보존 — 회귀 방지).
    """
    clean_names = [n.strip() for n in (names or []) if isinstance(n, str) and n.strip()]
    result: dict = {"requested": clean_names, "cards": [], "missing": [], "images": [], "images_gap": []}
    if not clean_names:
        return result

    vault = _vault_dir()
    knowhow = _knowhow_root()
    if vault is None:
        print(
            "[design_knowledge_cards] vault 미설정/부재 - 카드 운반 생략"
            "(config: design_knowledge.vault_dir)"
        )

    budget_exhausted = False
    for name in clean_names:
        card = load_card(name, vault=vault)
        result["cards"].append(card)
        if not card["found"]:
            result["missing"].append(name)
            continue
        if budget_exhausted:
            continue
        for img in card.get("images", []):
            if len(result["images"]) >= IMAGE_LIMIT_PER_SLIDE:
                budget_exhausted = True
                break
            resolved = resolve_design_uri(img["uri"], knowhow)
            if resolved is None or not resolved.is_file():
                print(
                    f"[design_knowledge_cards] 이미지 실재 확인 실패 - 생략: "
                    f"card={name} uri={img['uri']}"
                )
                result["images_gap"].append({"card": name, "uri": img["uri"], "via": img["via"]})
                continue
            result["images"].append({
                "card": name, "layer": card.get("layer"), "uri": img["uri"],
                "via": img["via"], "path": str(resolved),
            })
    return result


def structure_reference_role(img: dict) -> str:
    """imagedeck._reference_block이 쓰는 역할 라벨 — β1 3계층 레퍼런스와 같은 지위로 이어붙일
    때 이 이미지가 "구조 레퍼런스"(디자인지식 카드발)임을 명시한다."""
    return f"구조 레퍼런스 - 디자인지식 카드 '{img.get('card')}'(layer={img.get('layer')})"


def render_prompt_block(carry: dict) -> "str | None":
    """장 프롬프트에 이어붙일 "## 장 구조 지식(뼈대 결정기 선택 - 운반)" 절. 카드 인용이 없으면
    None(문단 자체를 만들지 않음 — 기존 프롬프트와 바이트 동일 보존)."""
    if not carry.get("requested"):
        return None
    lines = [
        CARRY_HEADER,
        "",
        "와이어프레임 결정기(A6)가 이 장에 적용을 선택한 디자인지식 카드다 - 기계가 무차별로",
        "주입한 것이 아니라 LLM이 pull로 고른 카드를 결정론으로 운반(본문+실물 이미지 동봉)할",
        "뿐이다. 아래 조작적 정의를 실제로 적용하라.",
        "",
    ]
    for card in carry.get("cards", []):
        if not card.get("found"):
            lines.append(f"- **{card['name']}** [카드 미발견]")
            continue
        claim = card.get("claim") or "(claim 없음)"
        lines.append(f"- **{card['name']}** (layer={card.get('layer')}): {claim}")
        excerpt = card.get("excerpt")
        if excerpt:
            for exline in excerpt.splitlines():
                lines.append(f"    {exline}")
    return "\n".join(lines)
