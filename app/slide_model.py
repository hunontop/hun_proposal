# -*- coding: utf-8 -*-
"""정본 SlideModel — 로드·검증·단계간 교차검증.

3계층 아키텍처의 허브(②엔진). 노하우 0 — 색/패턴을 모른다.
계약: CONTEXT/plan.md "★ M1 정본 계약 (1)". 스키마: app/schemas/slide_model.schema.json

검증은 jsonschema가 있으면 사용, 없으면 최소 수동 검사로 폴백(의존 최소화).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

APP = Path(__file__).resolve().parent
SCHEMAS = APP / "schemas"


def _load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate(doc: dict, schema_name: str = "slide_model") -> list[str]:
    """스키마 검증. 위반 메시지 리스트 반환(빈 리스트=통과)."""
    schema = _load_json(SCHEMAS / f"{schema_name}.schema.json")
    try:
        import jsonschema  # type: ignore

        errs = sorted(
            jsonschema.Draft7Validator(schema).iter_errors(doc),
            key=lambda e: list(e.path),
        )
        return [f"{'/'.join(map(str, e.path)) or '(root)'}: {e.message}" for e in errs]
    except ImportError:
        # 폴백: 최소 검사(필수 키만)
        problems: list[str] = []
        for key in schema.get("required", []):
            if key not in doc:
                problems.append(f"(root): 필수 키 누락 '{key}'")
        return problems


def slide_ids(doc: dict) -> set[int]:
    return {s["slide_id"] for s in doc.get("slides", []) if "slide_id" in s}


def cross_validate(stage_docs: dict[str, dict]) -> list[str]:
    """단계 문서들의 slide_id 집합이 일치하는지 교차검증.

    stage_docs 예: {"6": {...}, "7": {...}, "8": {...}}
    불변식(plan.md): 모든 단계의 slide_id 집합이 같아야 한다.
    """
    problems: list[str] = []
    sets = {name: slide_ids(doc) for name, doc in stage_docs.items()}
    if not sets:
        return problems
    union: set[int] = set().union(*sets.values())
    for name, ids in sets.items():
        missing = union - ids
        if missing:
            problems.append(f"단계 {name}: slide_id 누락 {sorted(missing)}")
    return problems


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("사용: python slide_model.py <deck.json> [schema_name]")
        raise SystemExit(1)
    name = sys.argv[2] if len(sys.argv) > 2 else "slide_model"
    errors = validate(_load_json(sys.argv[1]), name)
    if errors:
        print(f"[검증 실패] {len(errors)}건")
        for e in errors:
            print(f"  - {e}")
        raise SystemExit(2)
    print("[검증 통과]")
