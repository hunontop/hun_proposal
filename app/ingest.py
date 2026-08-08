# -*- coding: utf-8 -*-
"""ingest — 6/7/8단계 AI 출력(JSON) → 정본 SlideModel 어댑트·병합.

3계층 엔진의 입력부. 단계별 출력 스키마(app/schemas/stage{6,7,8})를 검증하고,
정본 SlideModel(slide_model.schema)로 어댑트한 뒤 slide_id로 병합한다.
계약: plan.md "★ M1 정본 계약". 산출물 안정화 우선 — fields 바인딩은 AI가 준 것만 반영(없으면 body로 degrade).

사용:
  python app/ingest.py --stage6 s6.json [--stage7 s7.json] [--stage8 s8.json] \
                       --project "..." --pack core --out deck.json [--render out.html]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

APP = Path(__file__).resolve().parent
import slide_model as sm  # noqa: E402  (같은 디렉터리)


def _load(p: str | Path) -> Any:
    return json.loads(Path(p).read_text(encoding="utf-8"))


# --- 단계별 어댑터 (단계 출력 → 정본 slide 부분) ---------------------------

def adapt_stage6(doc: dict) -> dict[int, dict]:
    """6단계 내용확장 → 정본 slide(내용 본체)."""
    out: dict[int, dict] = {}
    for s in doc.get("slides", []):
        sid = s.get("slide_id")
        if sid is None:
            continue
        cc = s.get("copy_candidates") or {}
        body = cc.get("bullets") or s.get("supporting_points") or (
            [s["expanded_body"]] if s.get("expanded_body") else [])
        evidence = [
            {"source": e.get("source", ""), "fact": e.get("quote_or_fact", e.get("fact", "")),
             "confidence": e.get("confidence", "medium")}
            for e in (s.get("evidence") or [])
        ]
        out[sid] = {
            "slide_id": sid,
            "role": s.get("role", ""),
            "template_id": None,
            "title": cc.get("title") or s.get("original_title", ""),
            "key_message": cc.get("key_message") or s.get("claim", ""),
            "body": body,
            "fields": {},
            "evidence": evidence,
            "review_needed": list(s.get("review_needed") or []),
            "open_questions": list(s.get("open_questions") or []),
            "style": {},
        }
    return out


def patch_stage7(slides: dict[int, dict], doc: dict) -> None:
    """7단계 레이아웃 → template_id 부여 + 부족입력 검토요망."""
    for s in doc.get("slides", []):
        sid = s.get("slide_id")
        if sid not in slides:
            continue
        slides[sid]["template_id"] = s.get("selected_template_id") or slides[sid].get("template_id")
        for mi in (s.get("missing_inputs") or []):
            slides[sid]["review_needed"].append(f"[레이아웃 필수입력 부족] {mi}")
        # AI가 구조 데이터를 줬다면 fields로 흡수(있을 때만)
        if isinstance(s.get("fields"), dict):
            slides[sid]["fields"].update(s["fields"])


def patch_stage8(slides: dict[int, dict], doc: dict) -> None:
    """8단계 디자인 → style 오버레이."""
    for s in doc.get("slides", []):
        sid = s.get("slide_id")
        if sid not in slides:
            continue
        style = {k: s[k] for k in ("color_direction", "typography_direction", "shape_language", "design_intent")
                 if s.get(k)}
        if s.get("image_prompt", {}).get("needed"):
            slides[sid].setdefault("review_needed", []).append("[이미지 생성 필요] " + s["image_prompt"].get("subject", ""))
        slides[sid]["style"].update(style)


def _load_templates(pack: str) -> dict[str, dict]:
    p = APP.parent / "packs" / pack / "templates.json"
    if not p.exists():
        # 격리 하우스 팩 폴백 — --pack 명시 시만(결정 11·12). W31 E3: 실물은 <개발 원본 전용 경로> 격리, 이 경로는 상시 부재
        p = APP.parent / "packs_excluded" / pack / "templates.json"
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    items = data.get("templates", data) if isinstance(data, dict) else data
    return {t["id"]: t for t in items}


def merge(project: str, pack: str, s6: dict, s7: dict | None, s8: dict | None) -> tuple[dict, dict]:
    """단계 문서들 → 정본 deck + 게이팅 리포트."""
    import bind  # 같은 디렉터리

    slides = adapt_stage6(s6)
    if s7:
        patch_stage7(slides, s7)
    if s8:
        patch_stage8(slides, s8)
    deck = {
        "meta": {"project": project, "pack": pack},
        "slides": [slides[k] for k in sorted(slides)],
    }
    # fields 바인딩(텍스트형 채움 · 구조형 미확보는 검토요망)
    bind_report = bind.bind_deck(deck, _load_templates(pack))
    # 교차검증
    stage_docs = {"6": s6}
    if s7:
        stage_docs["7"] = s7
    if s8:
        stage_docs["8"] = s8
    report = {
        "slides": len(deck["slides"]),
        "schema_errors": sm.validate(deck, "slide_model"),
        "cross_validate": sm.cross_validate(stage_docs),
        "review_needed_total": sum(len(s["review_needed"]) for s in deck["slides"]),
        "open_questions_total": sum(len(s["open_questions"]) for s in deck["slides"]),
        "no_template": [s["slide_id"] for s in deck["slides"] if not s.get("template_id")],
        "fields_bound": bind_report["bound"],
        "fields_missing": bind_report["flagged"],
        # stage6 경로의 template_id는 stage7이 명시 지정한다 → 자동배정 폴백 대상이 아니다(항상 빈 목록).
        "template_fallback": bind_report.get("template_fallback") or [],
    }
    return deck, report


def main() -> int:
    ap = argparse.ArgumentParser(description="ingest 6/7/8 → 정본 deck")
    ap.add_argument("--stage6", required=True)
    ap.add_argument("--stage7")
    ap.add_argument("--stage8")
    ap.add_argument("--project", default="제안 검토덱")
    ap.add_argument("--pack", default="core")
    ap.add_argument("--out", required=True)
    ap.add_argument("--render", help="HTML 출력 경로(선택)")
    a = ap.parse_args()

    # 단계별 스키마 검증(게이트)
    for stage, path in (("6", a.stage6), ("7", a.stage7), ("8", a.stage8)):
        if not path:
            continue
        errs = sm.validate(_load(path), f"stage{stage}")
        if errs:
            print(f"[게이트 실패] stage{stage} 스키마 위반 {len(errs)}건:")
            for e in errs[:10]:
                print(f"  - {e}")
            return 2

    deck, report = merge(a.project, a.pack,
                         _load(a.stage6),
                         _load(a.stage7) if a.stage7 else None,
                         _load(a.stage8) if a.stage8 else None)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(deck, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== ingest 게이팅 리포트 ===")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"[정본 deck] {a.out}")

    if a.render:
        from render.htmlgen import render_html
        rep = render_html(deck, a.pack, a.render)
        print(f"[HTML] {rep['out']} ({rep['bytes']}B, slides={rep['slides']}, warnings={len(rep['warnings'])})")
    return 0


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(APP))
    raise SystemExit(main())
