"""W5 검토요망 해소 — `run/review_resolutions.json`.

NORTHSTAR_REDESIGN §3.0 체크포인트 ②("발산 추천·창작경계 flag도 이 한 화면에서 함께 처리")의
빠져 있던 배선. `review_needed` 태그는 생산(storyline flag/bind/ingest/enrich)·표시(HTML 배지·
gating_report·대시보드)·보존(stage9 가드·시네마틱·익명화)까지 완비였으나 **해소 공정이 없었다**
— 코드 전체가 append-only였고, 사람이 storyline.json을 손으로 고치는 공정 밖 행위만 남아 있었다.

**불변식 (창작금지 원칙의 대칭)**
    태그 제거는 **사람의 명시 resolution 기록이 있을 때만** 일어난다.
    코드는 어떤 경우에도 태그를 임의로 지우지 않는다. 지어내지 않는 것과 같은 이유로,
    "근거가 없다"는 사실도 사람의 서명 없이 사라지면 안 된다.

**결정 3종**
  - ``fact_supplied``      : 사람이 사실을 제공했다 → target(fields/body)에 기입 + 태그 제거
  - ``no_basis_confirmed`` : 근거 없음을 사람이 확인했다 → 콘텐츠 유지, 태그만 제거
                             (제거의 근거는 이 파일에 남는다 — "사라진" 게 아니라 "서명된" 것)
  - ``deferred``           : 보류 → 무변경(태그 유지)
  그 외(빈 decision·미상 값·fact 없는 fact_supplied) = **미결**이며 태그를 건드리지 않는다.

**적용 지점 = `render_run`**(bind/enrich 직후, 배지·gating_report 계산 직전).
deck.json은 매 렌더마다 storyline에서 재구성되므로, 해소를 렌더 파이프라인 안에 두어야
재렌더에도 살아남는다(idempotent: 태그가 다시 생기고 → 다시 해소된다). deck.json만 후편집하면
다음 렌더에서 조용히 되살아난다.

**편집 UI = 이 JSON 파일 자체** — `design_brief.json`과 같은 패턴(살아있는 문서, 골격은
결정론 생성·기존은 보존). 결정론·0토큰. LLM을 호출하지 않는다.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
RESOLUTIONS_NAME = "review_resolutions.json"

# 사람이 기록할 수 있는 결정. 이 외의 값은 미결로 취급한다(모르는 값에 의미를 부여하지 않는다).
DECISIONS = ("fact_supplied", "no_basis_confirmed", "deferred")

# 태그 제거를 유발하는 결정. deferred는 여기 없다 — 보류는 무변경이다.
_RESOLVING = ("fact_supplied", "no_basis_confirmed")

# W9 예시 데이터: 이 접두로 시작하는 태그를 **fact_supplied**로 해소하면(=사람이 실데이터를 제공)
# 슬라이드의 예시 마크(slide.example)까지 함께 제거한다 — 라벨/워터마크/ship 경고가 사라진다.
# 접두 문자열은 bind.EXAMPLE_REVIEW_TAG와 맺은 계약이다(bind가 태그를 생산·여기서 소비).
# no_basis_confirmed(근거 없음 확정)는 예시를 유지한다 — 마크를 지우지 않는다(태그만 제거).
EXAMPLE_TAG_PREFIX = "[예시 데이터]"

# 태그 → 기입 대상 필드 추론(결정론). 근거: 태그를 만든 코드가 필드명을 문자열에 박아 넣는다.
#   - bind.bind_deck       : "[필수입력 미확보] <field> — 구조 데이터 필요(지어내지 않음)"
#   - ingest.patch_stage7  : "[레이아웃 필수입력 부족] <field>"
_FIELD_TAG_RES = (
    re.compile(r"^\[필수입력 미확보\]\s*(?P<field>[^\s—]+)"),
    re.compile(r"^\[레이아웃 필수입력 부족\]\s*(?P<field>[^\s—]+)"),
)


def resolutions_path(run: Path) -> Path:
    return Path(run) / RESOLUTIONS_NAME


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def load(run: Path) -> dict[str, Any] | None:
    p = resolutions_path(Path(run))
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def save(run: Path, doc: dict[str, Any]) -> Path:
    p = resolutions_path(Path(run))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# 골격 — 태그 전수 → 해소지 항목
# ---------------------------------------------------------------------------

def _key(slide_id: Any, tag: str) -> str:
    return f"{slide_id}::{tag}"


def _target_for(tag: str) -> dict[str, Any]:
    """기입 대상 기본값. 필드명을 태그에서 못 읽으면 body 추가로 떨어뜨린다."""
    for rx in _FIELD_TAG_RES:
        m = rx.match(tag.strip())
        if m:
            return {"kind": "field", "name": m.group("field")}
    return {"kind": "body"}


def _entry(slide: dict, tag: str) -> dict[str, Any]:
    return {
        "slide_id": slide.get("slide_id"),
        "slide_title": slide.get("title") or "",
        "tag": tag,
        "decision": "",                  # ← 사람이 채운다: fact_supplied | no_basis_confirmed | deferred
        "fact": None,                    # fact_supplied일 때만 필수. 문자열 또는 JSON 값.
        "target": _target_for(tag),      # fact를 어디에 기입할지(사람이 고쳐도 된다)
        "decided_at": None,              # 결정 기록 시각 — 결정이 채워지면 자동 각인
        "decided_by": None,
        "note": "",
    }


def tags_of(deck: dict) -> list[tuple[dict, str]]:
    out: list[tuple[dict, str]] = []
    for slide in deck.get("slides") or []:
        if not isinstance(slide, dict):
            continue
        for tag in slide.get("review_needed") or []:
            text = str(tag)
            if text:
                out.append((slide, text))
    return out


def build_skeleton(run: Path, deck: dict, existing: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    """태그 전수 → 해소지 골격. **기존 항목은 보존**(사람 편집본이 정본). 반환 = (문서, 신규 항목 수).

    태그가 사라진 항목(storyline 수정 등)도 지우지 않는다 — 사람의 결정 기록은 역사다.
    대신 `stale=true`로 표시해 적용기가 조용히 무시하게 한다.
    """
    run = Path(run)
    prev_items = list((existing or {}).get("items") or []) if isinstance(existing, dict) else []
    by_key = {
        _key(i.get("slide_id"), str(i.get("tag") or "")): i
        for i in prev_items
        if isinstance(i, dict)
    }
    live = {_key(s.get("slide_id"), t) for s, t in tags_of(deck)}

    items: list[dict[str, Any]] = []
    added = 0
    for slide, tag in tags_of(deck):
        k = _key(slide.get("slide_id"), tag)
        found = by_key.pop(k, None)
        if found is not None:
            found.pop("stale", None)
            items.append(found)
        else:
            items.append(_entry(slide, tag))
            added += 1
    for k, orphan in by_key.items():                      # 덱에 더는 없는 태그의 결정 기록
        orphan["stale"] = True
        items.append(orphan)

    doc = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run.name,
        "generated_at": (existing or {}).get("generated_at") or _now(),
        "updated_at": _now(),
        "generated_by": "go (의사결정 게이트 정지 시 — 결정론 골격, LLM 0토큰)",
        "editing": (
            "이 파일을 직접 수정하는 것이 편집 UI다. 항목의 decision을 채우고 `go`를 다시 쳐라. "
            "decision을 비워두면 태그는 그대로 남는다(코드는 태그를 임의로 지우지 않는다)."
        ),
        "decisions": {
            "fact_supplied": "사실을 제공했다 → fact를 target에 기입하고 태그를 제거한다. fact 필수.",
            "no_basis_confirmed": "근거 없음을 확인했다 → 콘텐츠는 그대로, 태그만 제거한다(이 기록이 근거).",
            "deferred": "보류 → 아무것도 바꾸지 않는다(태그 유지).",
        },
        "invariant": "태그 제거는 사람의 명시 resolution 기록이 있을 때만. 창작금지 원칙의 대칭.",
        "items": items,
    }
    _stamp_decisions(doc)
    return doc, added


def _stamp_decisions(doc: dict[str, Any]) -> int:
    """결정이 채워졌는데 기록 시각이 없는 항목에 시각을 각인. 반환 = 각인한 수."""
    n = 0
    for item in doc.get("items") or []:
        if not isinstance(item, dict):
            continue
        if item.get("decision") in DECISIONS and not item.get("decided_at"):
            item["decided_at"] = _now()
            n += 1
    return n


def sync(run: Path, deck: dict) -> tuple[Path, dict[str, Any], int, int]:
    """해소지 골격 생성/갱신 + 결정 시각 각인. 반환 = (경로, 문서, 신규 항목 수, 각인 수)."""
    existing = load(run)
    doc, added = build_skeleton(run, deck, existing)
    stamped = _stamp_decisions(doc)
    return save(run, doc), doc, added, stamped


# ---------------------------------------------------------------------------
# 적용기 — 결정론. 사람이 기록한 항목만 만진다.
# ---------------------------------------------------------------------------

def _classify(item: dict[str, Any]) -> tuple[str, str]:
    """(bucket, reason). bucket ∈ DECISIONS | 'pending' | 'invalid' | 'stale'."""
    if item.get("stale"):
        return "stale", "덱에 없는 태그"
    decision = item.get("decision") or ""
    if not decision:
        return "pending", "결정 미기록"
    if decision not in DECISIONS:
        return "invalid", f"미상 decision: {decision!r}"
    if decision == "fact_supplied" and item.get("fact") in (None, "", [], {}):
        return "invalid", "fact_supplied인데 fact가 비어 있다"
    return decision, ""


def _reproject_body(slide: dict, old_body: list, binders: dict | None, notes: list[str]) -> None:
    """body에 추가한 사실을 **bind가 body에서 파생시킨 필드**에 다시 투영한다.

    필요한 이유: 렌더러는 body가 아니라 fields를 읽는 템플릿이 많고(problem_questions →
    fields.sub_questions), bind는 해소기보다 **먼저** 돈다. 재투영이 없으면 사람이 기입한 사실이
    deck.json에만 남고 deck.html에는 안 나온다(= 조용한 유실).

    안전장치: 현재 필드값이 **옛 body에서 파생한 값과 정확히 같을 때만** 갱신한다. 다르면 사람/LLM이
    직접 쓴 값이므로 건드리지 않고 `notes`에 남긴다 — 덮어쓰느니 표면화한다.
    """
    if not binders:
        return
    binder = binders.get(slide.get("template_id") or "") or binders.get(slide.get("role") or "")
    if not binder:
        notes.append(f"slide {slide.get('slide_id')}: 바인더 없음 — body만 갱신(렌더 반영은 템플릿에 달림)")
        return
    old_slide = dict(slide, body=old_body)
    try:
        derived_old, derived_new = binder(old_slide), binder(slide)
    except Exception:  # 바인더는 순수 함수지만, 실패해도 해소 자체를 되돌리지 않는다
        return
    fields = slide.setdefault("fields", {})
    for key, new_value in derived_new.items():
        if key not in derived_old or derived_old[key] == new_value:
            continue
        if fields.get(key) == derived_old[key]:
            fields[key] = new_value                     # bind가 만든 값 → 재투영
        else:
            notes.append(
                f"slide {slide.get('slide_id')}: fields.{key}가 bind 파생값이 아니다 "
                f"— body에만 기입했다(렌더 반영 여부 확인 필요)"
            )


def _write_fact(slide: dict, item: dict[str, Any], binders: dict | None, notes: list[str]) -> str:
    target = item.get("target") or {}
    fact = item["fact"]
    if target.get("kind") == "field" and target.get("name"):
        slide.setdefault("fields", {})[str(target["name"])] = fact
        return f"fields.{target['name']}"
    body = slide.setdefault("body", [])
    if not isinstance(body, list):
        return "body"
    text = fact if isinstance(fact, str) else json.dumps(fact, ensure_ascii=False)
    if text in body:
        return "body"
    old_body = list(body)
    body.append(text)
    _reproject_body(slide, old_body, binders, notes)
    return "body"


def apply(deck: dict, doc: dict[str, Any] | None, *, binders: dict | None = None) -> dict[str, Any]:
    """해소지의 **결정된 항목만** deck에 반영(in-place). 그 외 태그는 절대 건드리지 않는다.

    `binders`는 `bind.BINDERS`(app/bind.py) — body 기입분을 bind 파생 필드에 재투영하기 위해
    주입받는다(scripts→app 임포트 결합을 피하려 인자로 받는다). 없으면 재투영을 건너뛴다.

    반환 = 실측 리포트. `tags_removed`는 실제로 리스트에서 사라진 태그 수이지 결정 수가 아니다
    (결정이 있어도 태그가 이미 없으면 0 — 자기보고 금지).
    """
    counts = {k: 0 for k in DECISIONS}
    counts.update({"pending": 0, "invalid": 0, "stale": 0})
    applied: list[dict[str, Any]] = []
    problems: list[str] = []
    unmatched: list[str] = []
    notes: list[str] = []
    tags_removed = 0
    facts_applied = 0

    items = list((doc or {}).get("items") or [])
    slides = {s.get("slide_id"): s for s in (deck.get("slides") or []) if isinstance(s, dict)}

    # 결정된 항목만 (slide_id, tag) 정확 일치로 찾는다. 근사 매칭 없음 — 잘못 지우느니 안 지운다.
    for item in items:
        if not isinstance(item, dict):
            counts["invalid"] += 1
            continue
        bucket, reason = _classify(item)
        counts[bucket] = counts.get(bucket, 0) + 1
        if bucket == "invalid":
            problems.append(f"slide {item.get('slide_id')}: {reason}")
            continue
        if bucket not in _RESOLVING:
            continue

        slide = slides.get(item.get("slide_id"))
        tag = str(item.get("tag") or "")
        if slide is None or tag not in (slide.get("review_needed") or []):
            unmatched.append(f"slide {item.get('slide_id')}: {tag[:30]}")
            continue

        where = ""
        example_cleared = False
        if bucket == "fact_supplied":
            where = _write_fact(slide, item, binders, notes)
            facts_applied += 1
            # W9: 실데이터가 예시를 대체했다 → 예시 마크 제거(라벨/워터마크/경고 해제).
            # 마크는 사람의 fact_supplied 서명 위에서만 사라진다(불변식 유지).
            if tag.startswith(EXAMPLE_TAG_PREFIX) and slide.get("example"):
                slide.pop("example", None)
                example_cleared = True
        slide["review_needed"] = [t for t in slide["review_needed"] if str(t) != tag]
        tags_removed += 1
        applied.append({
            "slide_id": item.get("slide_id"),
            "tag": tag,
            "decision": bucket,
            "decided_at": item.get("decided_at"),
            "wrote": where or None,
            **({"example_cleared": True} if example_cleared else {}),
        })

    return {
        "items_total": len(items),
        "counts": counts,
        "tags_removed": tags_removed,
        "facts_applied": facts_applied,
        "applied": applied,
        "unmatched": unmatched,
        "problems": problems,
        "notes": notes,
    }


def summarize(report: dict[str, Any], path: Path | str | None) -> dict[str, Any]:
    """gating_report에 실을 요약. **해소지 파싱 실측**이지 자기보고가 아니다."""
    counts = report.get("counts") or {}
    return {
        "resolutions_file": str(path) if path else None,
        "items_total": report.get("items_total", 0),
        "resolved": counts.get("fact_supplied", 0) + counts.get("no_basis_confirmed", 0),
        "fact_supplied": counts.get("fact_supplied", 0),
        "no_basis_confirmed": counts.get("no_basis_confirmed", 0),
        "deferred": counts.get("deferred", 0),
        "pending": counts.get("pending", 0),
        "invalid": counts.get("invalid", 0),
        "stale": counts.get("stale", 0),
        "tags_removed": report.get("tags_removed", 0),
        "facts_applied": report.get("facts_applied", 0),
        "unmatched": list(report.get("unmatched") or []),
        "problems": list(report.get("problems") or []),
        "notes": list(report.get("notes") or []),
        "note": "태그 제거 수는 해소지의 결정 기록 수와 대조 가능해야 한다(tags_removed ≤ resolved).",
    }


def summary_line(rep: dict[str, Any]) -> str:
    c = rep.get("counts") or rep  # apply 리포트 / summarize 결과 둘 다 받는다
    def g(k: str) -> int:
        return int((c.get(k) if isinstance(c, dict) else 0) or 0)
    return (
        f"해소 {g('fact_supplied') + g('no_basis_confirmed')}건 "
        f"(사실기입 {g('fact_supplied')} · 근거없음확정 {g('no_basis_confirmed')}) / "
        f"보류 {g('deferred')} / 미결 {g('pending')} / 무효 {g('invalid')} "
        f"→ 태그 제거 {int(rep.get('tags_removed') or 0)}건"
    )
