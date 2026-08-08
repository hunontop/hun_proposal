"""W3a 디자인 브리핑 — `run/design_brief.json` (트랙 ②의 첫 조각).

NORTHSTAR_REDESIGN §3.0(체크포인트 2 = 의사결정 게이트)·N3-1.

**가이드(정적 규칙층) vs 브리핑(run별 동적 결정)의 경계** — 중복 발명 금지의 근거:

  | | 디자인 가이드(스킨) | 디자인 브리핑 |
  |---|---|---|
  | 실체 | `knowledge.design_guides` 카탈로그(`resolve_design_guides()`) | `run/design_brief.json` |
  | 만든이 | 사람/임포터(`tools/port_design_guide.py` → `add-skin`) | `go --confirm`(결정론 기본값) → 사람이 편집 |
  | 수명 | 팩·스킨 단위, **run 무관·재사용** | **run 1개**, 디벨롭 루프가 갱신 |
  | 답하는 질문 | "무엇이 좋은 디자인인가"(그리드·위계·연출 규칙) | "**이** 덱을 어떻게 만들 것인가"(모드·리듬·슬롯) |
  | 소비자 | stage8/stage9 프롬프트(비전), htmlgen 캐스케이드(tokens) | stage9 프롬프트, (향후) 이미지 공급·게이트 |

브리핑은 가이드를 **복제하지 않고 id로 참조만 한다**(`design_guides.selected`). 규칙 텍스트는
언제나 가이드 쪽 SSOT. 반대로 가이드는 슬라이드 번호를 모른다 — 리듬·슬롯 계획은 브리핑만의 것.

**결정론·0토큰.** 기본값의 근거는 렌더 산출물(`deck.json`)과 `review_badges`뿐이다.
사용자가 이 JSON을 직접 고치는 것이 편집 UI다(§N3-1 "살아있는 문서").
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
BRIEF_NAME = "design_brief.json"

OUTPUT_MODES = ("document", "cinematic")

# 페이지 리듬 값 — 렌더러가 아직 소비하지 않는다(디렉터 판단 기준). 새 어휘를 늘리지 않는다.
DENSITIES = ("hero", "normal", "dense")

_CINEMATIC_TEMPLATE_HINT = "cinematic"
_DENSE_BULLETS = 5

# W31 마찰14(2026-07-22): institution_research --apply가 남기는 등록 스킨 조회 필드.
_APPLIED_SKIN_FIELD = "_applied_skin"

# 결정 1(2026-07-09): hero 기본값 = **스토리 피크** 기반(상한 2~3장). 예전 "밋밋→hero"는 폐기 —
# thin 슬라이드가 곧 hero가 되어 실덱 11장 중 7장이 hero였다(리듬 사망). 리듬은 내용의 얇음이
# 아니라 스토리 구조가 정한다. 피크 어휘 = 표지·핵심 약속·비전 전환.
# 결정 2026-07-15: hero 배경은 **자동 라이브 슬롯이 아니다** — background_candidates 제안으로만
# 표면화한다(evidence_candidates와 대칭). 예전엔 hero마다 빈 프롬프트 bg 슬롯을 주입했는데,
# 그 슬롯이 (1) 프롬프트가 없어 제네릭 이미지를 뽑고 (2) 디렉터가 같은 슬라이드에 선언한 배경을
# 조용히 덮었다. 이제 배경은 사람/디렉터가 제안을 보고 프롬프트를 채워 **명시 선언**할 때만.
_HERO_CAP = 3
_HERO_VOCAB: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cover", ("표지", "cover", "타이틀", "title slide")),
    ("promise", ("핵심 약속", "핵심약속", "약속", "가치제안", "가치 제안", "value proposition",
                 "핵심 메시지", "핵심메시지", "key message")),
    ("vision", ("비전", "vision", "전환", "transition", "미래상", "future")),
)


def brief_path(run: Path) -> Path:
    return Path(run) / BRIEF_NAME


def exists(run: Path) -> bool:
    return brief_path(run).is_file()


def load(run: Path) -> dict[str, Any] | None:
    p = brief_path(run)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _badges(deck: dict, gating: dict | None) -> list[dict]:
    """review_badges — gating_report에 있으면 그걸 쓰고(재계산 회피), 없으면 계산."""
    rb = ((gating or {}).get("review_badges") or {}).get("badges")
    if rb:
        return list(rb)
    try:
        import review_badges  # type: ignore  # sys.path는 호출부(proposal_pipeline)가 세운다
        return review_badges.compute_review_badges(deck).get("badges", [])
    except Exception:
        return []


def _slide_index(deck: dict) -> dict[Any, dict]:
    return {s.get("slide_id"): s for s in (deck.get("slides") or []) if isinstance(s, dict)}


def _density(badge: dict, slide: dict) -> tuple[str, str]:
    """비-hero 슬라이드의 리듬(hero는 스토리 피크가 별도로 승격 — _hero_ids)."""
    bullets = int((badge.get("signals") or {}).get("bullets") or 0)
    if bullets >= _DENSE_BULLETS:
        return "dense", f"불릿 {bullets}개 — 정보 밀도가 높다."
    return "normal", "기본값(스토리 피크가 아니면 normal — 결정 1)."


def _hero_haystack(slide: dict) -> str:
    return f"{slide.get('role') or ''} {slide.get('title') or ''} {slide.get('section') or ''}".lower()


def _hero_ids(slides: dict[Any, dict], badges: list[dict]) -> dict[Any, str]:
    """스토리 피크 슬라이드 → {slide_id: category}. 상한 _HERO_CAP, 우선순위 cover>promise>vision→순서.

    결정 1: 리듬은 스토리 구조가 정한다(thin 여부 무관). 피크 어휘에 걸리는 슬라이드만 hero로,
    많아도 2~3장으로 제한해 리듬을 살린다.
    """
    cands: list[tuple[int, int, Any, str]] = []  # (우선순위, 등장순서, slide_id, category)
    for order, b in enumerate(badges):
        sid = b.get("slide_id")
        text = _hero_haystack(slides.get(sid, {}))
        for prio, (cat, kws) in enumerate(_HERO_VOCAB):
            if any(k in text for k in kws):
                cands.append((prio, order, sid, cat))
                break
    cands.sort(key=lambda c: (c[0], c[1]))
    return {sid: cat for _, _, sid, cat in cands[:_HERO_CAP]}


def _hero_candidate(slide_id: Any, category: str) -> dict:
    """스토리 피크 슬라이드의 **배경 제안**(라이브 슬롯 아님 — evidence_candidates와 대칭).

    결정 2026-07-15: 자동으로 라이브 슬롯을 주입하지 않는다. 빈 프롬프트 슬롯이 제네릭 이미지를
    뽑거나 디렉터 선언 배경을 조용히 덮던 문제 때문. hero라도 배경은 **명시 선언**할 때만 —
    사람/디렉터가 이 제안을 보고 프롬프트(주제)를 채워 image_slots로 올린다.
    권장 연출: role=mood(분위기 배경)·layer=background(가독성 treatment 필수)·format=jpg(사진풍 풀블리드).
    """
    return {
        "slide_id": slide_id,
        "suggested_role": "mood",
        "suggested_layer": "background",
        "suggested_format": "jpg",
        "suggested_treatment": "사진풍 풀블리드 배경 + 하단 그라디언트 오버레이 55% (배경 위 한 문장 가독성)",
        "why": (f"스토리 피크({category}) — 배경 이미지+한 문장(결정 1). 넣으려면 이 슬라이드에 "
                f"프롬프트(주제)를 채운 배경 슬롯을 image_slots로 선언하라(빈 프롬프트는 생성 안 함)."),
    }


def _institution_registered_skin(run: Path, skins_dir: "Path | None") -> "str | None":
    """W31 마찰14 수리: institution_research.json이 등록한 브랜드 스킨을 조회.

    `research --apply`가 브랜드색을 찾으면 `skins/<id>.json`을 등록하고, 그 등록 사실을
    `institution_research.json`의 `_applied_skin.skin_id`에 남긴다(proposal_pipeline._research_apply).
    브리핑이 아직 없던 시점에 조사가 먼저 끝났다면(전형적 순서), 이후 브리핑 기본값 생성이 여기서
    그 등록 스킨을 찾아 `skin.value`의 **초안**으로 채운다 — 자동 폴백이 아니라 "조사가 만든 초안
    제안"이다(사용자가 B1/theme_confirm에서 재확정 가능, design_contract.resolve_source가 실제
    소비). `skins_dir`이 주어지면 파일이 실재하는지까지 확인해, 지워지거나 아직 안 만들어진
    스킨을 초안으로 얹지 않는다.
    """
    p = Path(run) / "institution_research.json"
    if not p.is_file():
        return None
    try:
        res = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    skin_id = ((res or {}).get(_APPLIED_SKIN_FIELD) or {}).get("skin_id")
    if not skin_id:
        return None
    if skins_dir is not None and not (Path(skins_dir) / f"{skin_id}.json").is_file():
        return None
    return str(skin_id)


def build_default(
    run: Path,
    deck: dict,
    *,
    gating: dict | None = None,
    guides: list[dict] | None = None,
    skins_dir: "Path | None" = None,
) -> dict[str, Any]:
    """결정론 기본값. 근거 = 렌더된 deck.json + review_badges(+ gating_report.applied_axes).

    `skins_dir`(선택): 주어지면 institution_research.json의 등록 스킨을 조회해 `skin.value`
    초안을 채운다(W31 마찰14). 생략하면 종전처럼 `skin.value`는 비어 있다(호환).
    """
    run = Path(run)
    badges = _badges(deck, gating)
    slides = _slide_index(deck)

    templates = [s.get("template_id") for s in slides.values()]
    cinematic_n = sum(1 for t in templates if t and _CINEMATIC_TEMPLATE_HINT in str(t))

    heroes = _hero_ids(slides, badges)  # {slide_id: category} — 상한 2~3장(결정 1)
    rhythm: list[dict] = []
    slots: list[dict] = []
    background_candidates: list[dict] = []
    evidence_candidates: list[dict] = []
    for b in badges:
        sid = b.get("slide_id")
        slide = slides.get(sid, {})
        if sid in heroes:
            density = "hero"
            why = f"스토리 피크({heroes[sid]}) — 배경 이미지+한 문장(결정 1). 상한 {_HERO_CAP}장."
        else:
            density, why = _density(b, slide)
        rhythm.append({
            "slide_id": sid,
            "template_id": slide.get("template_id"),
            "verdict": b.get("verdict"),
            "density": density,
            "why": why,
        })
        if sid in heroes:
            background_candidates.append(_hero_candidate(sid, heroes[sid]))
        if (b.get("signals") or {}).get("has_flag"):
            evidence_candidates.append({
                "slide_id": sid,
                "why": "review_needed 플래그 — 근거 자산(실측 이미지)이 있으면 evidence 슬롯으로 직접 추가하라.",
            })

    applied = ((gating or {}).get("applied_axes") or {}).get("html") or {}
    guide_ids = [g["id"] for g in (guides or [])]
    registered_skin = _institution_registered_skin(run, skins_dir)

    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run.name,
        "generated_at": _now(),
        "generated_by": "go --confirm (결정론 기본값 — LLM 0토큰)",
        "editing": "이 파일을 직접 수정하는 것이 편집 UI다. stage9 번들이 그대로 소비한다.",
        "output_mode": {
            "value": "document",
            "options": list(OUTPUT_MODES),
            "rationale": (
                f"문서형이 정본, 시네마틱은 파생물(NORTHSTAR §N6). 참고: 덱의 cinematic 계열 템플릿 "
                f"{cinematic_n}/{len(templates)}장. 피칭 단독 목적이면 이 값을 'cinematic'으로 고쳐라."
            ),
        },
        "design_guides": {
            "selected": guide_ids,
            "rationale": "가이드는 규칙층 SSOT — 브리핑은 id로 참조만 한다(규칙 텍스트 복제 금지).",
        },
        "skin": {
            # ⚠️ 두 키의 역할이 다르다(W31 마찰14 — 서로 대체하지 않는다):
            #   - value: design_contract.build()의 **차용 소스**(resolve_source가 읽는다).
            #     여기서는 institution_research --apply의 등록 스킨을 **초안 제안**으로 채운다
            #     (자동 폴백 아님 — 사용자가 B1/theme_confirm에서 재확정 가능).
            #   - skins: render/htmlgen의 **스킨 체인**(W22, `render --skins a,b`와 같은 축) —
            #     design_contract는 이 키를 읽지 않는다. gating_report.applied_axes.html(렌더
            #     실측)에서 채워지며, 이 시점엔 대개 비어 있다(아직 그 축으로 렌더한 적이 없음).
            "value": registered_skin,
            "pack": applied.get("pack"),
            "skins": applied.get("skins") or [],
            "source": (
                f"institution_research --apply 등록 스킨({registered_skin}) 조회 — 조사가 만든 "
                "초안 제안(자동 폴백 아님, B1에서 재확정 가능)" if registered_skin else
                "gating_report.applied_axes.html (렌더 실측)" if applied else
                "미측정(gating_report에 applied_axes 없음, institution_research 등록 스킨도 없음)"
            ),
        },
        "brand": {
            "client_name": None, "client_logo": None,
            "proposer_name": None, "proposer_logo": None,
            "placement": {"client": "cover", "proposer": "all"},
            "policy": "로고=실자산 필수(자동 생성 금지, 결정 5·6 대칭). 경로=절대 또는 repo/run 상대. 값을 채우면 디자인 적용(stage9/wireframe --apply)이 캐스케이드 최후승으로 반영한다.",
        },
        "page_rhythm": {
            "default": "normal",
            "vocabulary": list(DENSITIES),
            "slides": rhythm,
        },
        "image_slots_plan": {
            "policy": {
                "generatable": ["mood", "conceptual"],
                "evidence": "자동 생성 금지 — 실자산만(사람이 slot.path로 지정). DESIGN_DIRECTOR_PASS §7 불변.",
                "format": "내용이 정한다(결정 5): 아이콘·도형=svg / 투명=png / 사진풍·풀블리드 배경=jpg 우선(용량).",
                "layer": "background 선언 시 가독성 treatment(오버레이·그라디언트·반투명 패널) 필수 — probe가 실측(결정 6).",
                "auto_background": "off(결정 2026-07-15) — 스토리 피크라도 배경을 자동 주입하지 않는다. background_candidates 제안을 보고 사람/디렉터가 프롬프트를 채워 명시 선언한다. 빈 프롬프트 슬롯은 생성하지 않고 경고한다(제네릭·덮어쓰기 방지).",
            },
            "slots": slots,
            "background_candidates": background_candidates,
            "evidence_candidates": evidence_candidates,
        },
        "notes": [
            "이 브리핑은 1회 확정이 아니라 디벨롭 루프가 갱신하는 살아있는 문서다(N3-1).",
            "슬롯 계획은 제안이다 — 실제 슬롯은 design_overrides.json의 image_slots가 정본이다.",
        ],
    }


# ── W3b: 브리핑 슬롯 계획 → design_overrides.json(정본) 동기화 ────────────────
# 브리핑의 슬롯은 **계획**이고 정본은 override의 image_slots다(위 notes 참조). 이미지 공급
# 단계는 정본만 읽으므로, 계획을 정본에 **추가만** 한다(기존 슬롯 수정·삭제 없음).
_SLOT_FIELDS = ("id", "role", "layer", "format", "treatment", "prompt", "path")


def plan_slots(brief: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """브리핑 계획 → [(슬라이드 키, override용 슬롯 dict)]. `slide_id`·`source`는 슬롯에서 뺀다."""
    out: list[tuple[str, dict[str, Any]]] = []
    for s in ((brief or {}).get("image_slots_plan") or {}).get("slots") or []:
        if not isinstance(s, dict) or s.get("slide_id") is None or not s.get("id"):
            continue
        slot = {k: s[k] for k in _SLOT_FIELDS if s.get(k) not in (None, "")}
        out.append((str(s["slide_id"]), slot))
    return out


def sync_slots_into_overrides(brief: dict[str, Any], overrides: dict[str, Any]) -> list[str]:
    """계획 슬롯 중 override에 **없는 것만** 추가(in-place). 반환 = 추가된 슬롯 식별자.

    - 동일 (슬라이드, slot id)가 이미 있으면 건드리지 않는다 — 사람/디렉터 편집본이 우선.
    - role 게이트(evidence 자동생성 금지)는 여기서 흉내내지 않는다. 계약의 단일 소재지는
      `fill_images()`의 `skipped_evidence` 분기다(중복 게이트 = 계약 분산 = 표류 원인).
    """
    if not isinstance(overrides.get("slides"), dict):
        overrides["slides"] = {}
    added: list[str] = []
    for key, slot in plan_slots(brief):
        entry = overrides["slides"].setdefault(key, {})
        if not isinstance(entry, dict):
            continue
        slots = entry.setdefault("image_slots", [])
        if not isinstance(slots, list):
            continue
        if any(isinstance(x, dict) and x.get("id") == slot["id"] for x in slots):
            continue
        slots.append(slot)
        added.append(f"slide{key}:{slot['id']}")
    return added


def save(run: Path, brief: dict[str, Any]) -> Path:
    p = brief_path(Path(run))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(brief, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def summary(brief: dict[str, Any]) -> str:
    rhythm = (brief.get("page_rhythm") or {}).get("slides") or []
    counts: dict[str, int] = {}
    for r in rhythm:
        counts[r.get("density", "?")] = counts.get(r.get("density", "?"), 0) + 1
    slots = (brief.get("image_slots_plan") or {}).get("slots") or []
    roles: dict[str, int] = {}
    for s in slots:
        roles[s.get("role", "?")] = roles.get(s.get("role", "?"), 0) + 1
    plan = brief.get("image_slots_plan") or {}
    bg = len(plan.get("background_candidates") or [])
    ev = len(plan.get("evidence_candidates") or [])
    return (
        f"mode={(brief.get('output_mode') or {}).get('value')} "
        f"skin.value={(brief.get('skin') or {}).get('value') or '-'} "
        f"guides={','.join((brief.get('design_guides') or {}).get('selected') or []) or '-'} "
        f"rhythm={{{', '.join(f'{k}:{v}' for k, v in sorted(counts.items()))}}} "
        f"slots={{{', '.join(f'{k}:{v}' for k, v in sorted(roles.items())) or '-'}}} "
        f"background_candidates={bg} evidence_candidates={ev}"
    )


def render_for_prompt(brief: dict[str, Any]) -> str:
    """stage9 프롬프트에 실을 브리핑 요약(디렉터가 지켜야 할 결정만)."""
    om = (brief.get("output_mode") or {}).get("value")
    lines = [f"- 출력 모드: **{om}**", f"- 스킨: value(차용 소스)={(brief.get('skin') or {}).get('value')} "
             f"pack={(brief.get('skin') or {}).get('pack')} "
             f"skins(렌더 체인)={(brief.get('skin') or {}).get('skins')}"]
    brand = brief.get("brand") or {}
    if any(brand.get(k) for k in ("client_name", "client_logo", "proposer_name", "proposer_logo")):
        lines.append(
            f"- brand: client={brand.get('client_name')}/{brand.get('client_logo')} "
            f"proposer={brand.get('proposer_name')}/{brand.get('proposer_logo')} "
            f"placement={(brand.get('placement') or {})}"
        )
    else:
        lines.append("- brand: 미지정")
    rhythm = (brief.get("page_rhythm") or {}).get("slides") or []
    hero = [str(r["slide_id"]) for r in rhythm if r.get("density") == "hero"]
    dense = [str(r["slide_id"]) for r in rhythm if r.get("density") == "dense"]
    lines.append(f"- 페이지 리듬: hero={', '.join(hero) or '-'} / dense={', '.join(dense) or '-'} / 나머지 normal")
    plan = brief.get("image_slots_plan") or {}
    for s in plan.get("slots") or []:
        layer = s.get("layer") or "foreground"
        fmt = s.get("format") or "svg"
        lines.append(
            f"- 이미지 슬롯 계획: slide {s['slide_id']} → id={s['id']} role={s['role']} "
            f"layer={layer} format={fmt} treatment=\"{s.get('treatment', '')}\""
        )
    bg = plan.get("background_candidates") or []
    if bg:
        lines.append(
            f"- 배경 후보(스토리 피크·슬롯 미생성, 자동 주입 없음): "
            f"slide {', '.join(str(b['slide_id']) for b in bg)} — 배경을 넣으려면 프롬프트(주제)를 "
            f"채운 layer=background 슬롯으로 명시 선언하라(빈 프롬프트는 생성 안 함)"
        )
    ev = plan.get("evidence_candidates") or []
    if ev:
        lines.append(
            f"- evidence 후보(슬롯 미생성, 자동생성 금지): "
            f"{', '.join(str(e['slide_id']) for e in ev)} — 실자산이 있을 때만 사람이 추가"
        )
    return "\n".join(lines)
