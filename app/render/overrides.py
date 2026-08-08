# -*- coding: utf-8 -*-
"""stage9 디자인 디렉터 override 로더 + SSOT 안전 검증기.

계약(CONTEXT/DESIGN_DIRECTOR_PASS.md §5·§6):
- override는 **append-only + css/class만** → deck.json 본문(사실·수치·검토게이트)은 구조적으로 불변.
- 검증기는 (a) 구조(허용 키·타입), (b) 슬라이드 키가 실제 덱에 존재, (c) SSOT 안전
  = append_html이 기존 본문 텍스트를 '재생'하지 않는지(중복·창작 오염 방지)를 본다.
이미지 슬롯 정책(W27 D6): role=evidence 생성은 허용 + 딱지 표시(생성기 측 게이트는
image_slots.fill_images가 소재지). image_slot_warnings()는 web_sample 출처 누락을
비차단 경고로 표면화한다(D7).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_ALLOWED_SLIDE_KEYS = {"class", "css", "append_html", "image_slots", "note"}


def load_overrides(path: "str | Path") -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _slide_keys(deck: dict) -> set[str]:
    """override가 참조 가능한 키 집합: slide_id들 + 1-기반 인덱스 문자열."""
    keys: set[str] = set()
    for i, s in enumerate(deck.get("slides", []), 1):
        keys.add(str(i))
        if s.get("slide_id") is not None:
            keys.add(str(s["slide_id"]))
    return keys


def _visible_texts(deck: dict) -> list[str]:
    """덱 본문에서 나온 눈에 보이는 텍스트 조각(길이 6+). append 중복 탐지용."""
    out: list[str] = []

    def walk(v: Any):
        if isinstance(v, str):
            t = v.strip()
            if len(t) >= 6:
                out.append(t)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    for s in deck.get("slides", []):
        walk({k: s.get(k) for k in ("title", "key_message", "body", "fields")})
    return out


def validate_overrides(ov: dict, deck: dict) -> list[str]:
    """오류 목록 반환(빈 리스트=통과). 하드 실패만 오류로 올린다."""
    errors: list[str] = []
    if not isinstance(ov, dict):
        return ["overrides: 최상위가 객체가 아님"]
    if ov.get("version") != 1:
        errors.append(f"version: 1 이어야 함(받음: {ov.get('version')!r})")
    slides = ov.get("slides")
    if not isinstance(slides, dict):
        return errors + ["slides: 객체 필요"]

    valid_keys = _slide_keys(deck)
    deck_texts = _visible_texts(deck)

    for key, entry in slides.items():
        where = f"slides[{key}]"
        if key not in valid_keys:
            errors.append(f"{where}: 덱에 없는 슬라이드 키")
            continue
        if not isinstance(entry, dict):
            errors.append(f"{where}: 객체 필요")
            continue
        bad = set(entry) - _ALLOWED_SLIDE_KEYS
        if bad:
            errors.append(f"{where}: 허용되지 않은 키 {sorted(bad)}")
        for fld in ("class", "css", "append_html", "note"):
            if fld in entry and not isinstance(entry[fld], str):
                errors.append(f"{where}.{fld}: 문자열 필요")
        # SSOT 안전: append_html은 장식/슬롯만 — 덱 본문 텍스트를 그대로 품으면(재생) 거부.
        ah = entry.get("append_html") or ""
        if isinstance(ah, str) and ah:
            plain = re.sub(r"<[^>]+>", " ", ah)
            for t in deck_texts:
                if len(t) >= 12 and t in plain:
                    errors.append(f"{where}.append_html: 덱 본문 텍스트 재생 감지 → SSOT 위반 (\"{t[:20]}…\")")
                    break
        # 이미지 슬롯 검증. role 유효성(evidence 자동생성 금지는 생성기 책임) + 결정 5/6 계약.
        for slot in entry.get("image_slots") or []:
            if not isinstance(slot, dict) or slot.get("role") not in ("mood", "conceptual", "evidence"):
                errors.append(f"{where}.image_slots: role은 mood|conceptual|evidence")
                continue
            fmt = slot.get("format")
            if fmt is not None and str(fmt).lower().lstrip(".") not in ("svg", "png", "jpg", "jpeg"):
                errors.append(f"{where}.image_slots: format은 svg|png|jpg|jpeg (받음: {fmt!r})")
            layer = slot.get("layer")
            if layer is not None and str(layer).lower() not in ("background", "foreground"):
                errors.append(f"{where}.image_slots: layer는 background|foreground (받음: {layer!r})")
            # 결정 6: background 선언 시 가독성 처리(treatment) 필수 — 선언만으로는 통과 못 한다.
            if str(layer or "").lower() == "background" and not str(slot.get("treatment") or "").strip():
                errors.append(
                    f"{where}.image_slots[{slot.get('id')}]: layer=background 는 treatment 필수"
                    "(오버레이·그라디언트·반투명 패널로 가독성 확보)")
    return errors


def image_slot_warnings(ov: dict) -> list[str]:
    """비차단 경고(W27 D7) — source_route=web_sample인데 source_url 없으면 1줄(출처요망 대칭).

    validate_overrides()의 오류(하드 실패) 목록과 별개다 — 여기는 표면화 대상이지 적용을
    막지 않는다(D7: "차단하지 않는다 — 최종 교체 판단 재료만 남긴다").
    """
    warnings: list[str] = []
    for key, entry in (ov.get("slides") or {}).items():
        if not isinstance(entry, dict):
            continue
        for slot in entry.get("image_slots") or []:
            if not isinstance(slot, dict):
                continue
            if str(slot.get("source_route") or "").strip() != "web_sample":
                continue
            if not str(slot.get("source_url") or "").strip():
                warnings.append(
                    f"slides[{key}].image_slots[{slot.get('id')}]: "
                    "source_route=web_sample인데 source_url 없음 - 출처요망"
                )
    return warnings


def _norm(s: str) -> str:
    """공백 제거 정규화 — HTML 편집 후 띄어쓰기 차이로 인한 오탐 방지."""
    return re.sub(r"\s+", "", str(s))


def _plain_text_from_html(html_str: str) -> str:
    import html as _html
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html_str, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return _html.unescape(t)


# deck.json 사실이 렌더 시 변형되는 경우(①마커 제거 등) 정규화용 — htmlgen._strip_enum_marker와 동형.
_ENUM_MARKER_RE = re.compile(r"^\s*(?:[①-⑳]️?|\(\d{1,2}\)|\d{1,2}[.)])\s*")


def _fact_texts(deck: dict) -> list[str]:
    """가드 대상 사실 텍스트: 본문(title/key_message/body/fields 문자열) + 검토게이트."""
    facts = _visible_texts(deck)
    for s in deck.get("slides", []):
        for g in (s.get("review_needed") or []) + (s.get("open_questions") or []):
            gs = str(g).strip()
            if gs:
                facts.append(gs)
    return facts


def _text_blocks(html_str: str) -> list[str]:
    """HTML 태그 경계 기준 텍스트 조각(문단/라인 단위) — 전체 뭉치가 아니라 조각별 비교용."""
    import html as _html
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html_str, flags=re.S | re.I)
    raw = re.split(r"<[^>]+>", t)
    out: list[str] = []
    for r in raw:
        s = _html.unescape(r)
        s = re.sub(r"\s+", " ", s).strip()
        if len(s) >= 10:
            out.append(s)
    return out


def _review_flag_texts(deck: dict) -> list[str]:
    """review_needed 중 [예시] 태그가 붙은 항목만 — diff와의 겹침 표시용(결정 7 ③)."""
    out: list[str] = []
    for s in deck.get("slides", []):
        for g in s.get("review_needed") or []:
            gs = str(g).strip()
            if "[예시]" in gs:
                out.append(gs)
    return out


def _overlaps_review_flag(text: str, flag_texts: list[str]) -> bool:
    nt = _norm(text)
    return any(nt in _norm(f) or _norm(f) in nt for f in flag_texts)


def manual_layer_diff(edited_html: str, deck: dict, baseline_html: str) -> dict:
    """Claude Design 자유편집본 vs 베이스라인 — 내용 변경 명세(결정 7: 차단 대신 표면화).

    베이스라인 deck.html(편집 전 렌더본)을 기준으로:
    ① 삭제된 사실 — 베이스라인엔 있으나 편집본엔 없는 SSOT 텍스트(구 check_manual_layer 로직 그대로,
       deck.json 직접 대조는 렌더 변형으로 오탐이 나 "렌더된 텍스트" 기준을 유지한다)
    ② 추가된 텍스트 — 편집본에만 있는 조각(역방향 비교, 태그 경계 단위)
    ③ 둘 다 review_needed의 [예시] 태그 항목과 겹치면 표시 — "예시→실데이터 교체"와
       "출처 없는 신규 주장"을 사람이 즉시 구분하도록.
    freeze를 막지 않는다 — 결과는 문서화된 관측이지 판정이 아니다.
    """
    base_blob = _norm(_plain_text_from_html(baseline_html))
    edit_blob = _norm(_plain_text_from_html(edited_html))
    flag_texts = _review_flag_texts(deck)

    removed: list[dict] = []
    seen: set[str] = set()
    for t in _fact_texts(deck):
        nt = _norm(_ENUM_MARKER_RE.sub("", t))
        if len(nt) < 10 or nt in seen:
            continue
        seen.add(nt)
        if nt in base_blob and nt not in edit_blob:
            removed.append({"text": t[:80], "review_flag": _overlaps_review_flag(t, flag_texts)})

    added: list[dict] = []
    seen_added: set[str] = set()
    for blk in _text_blocks(edited_html):
        nb = _norm(blk)
        if nb in seen_added or nb in base_blob:
            continue
        seen_added.add(nb)
        added.append({"text": blk[:80], "review_flag": _overlaps_review_flag(blk, flag_texts)})

    return {"removed": removed[:40], "added": added[:40]}


def render_manual_layer_diff_md(diff: dict) -> str:
    """manual_layer_diff.md 본문 — 변경 0건도 명시(빈 파일 금지)."""
    removed = diff.get("removed") or []
    added = diff.get("added") or []
    lines = ["# Claude Design 편집본 — 내용 변경 명세", ""]
    if not removed and not added:
        lines.append("변경 0건 — 편집본이 베이스라인 대비 사실 텍스트를 삭제·추가하지 않았다.")
        return "\n".join(lines) + "\n"
    lines.append(f"삭제 {len(removed)}건 · 추가 {len(added)}건")
    if removed:
        lines.append("\n## 삭제된 사실 (베이스라인에 있었으나 편집본에 없음)")
        for r in removed:
            tag = " [예시 태그 겹침 — 실데이터 교체 가능성]" if r["review_flag"] else ""
            lines.append(f"- {r['text']}{tag}")
    if added:
        lines.append("\n## 추가된 텍스트 (편집본에만 있음)")
        for a in added:
            tag = " [예시 태그 겹침 — 실데이터 교체로 보임]" if a["review_flag"] else " [출처 없는 신규 텍스트 — 확인 필요]"
            lines.append(f"- {a['text']}{tag}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    import sys
    ov = load_overrides(sys.argv[1])
    deck = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    errs = validate_overrides(ov, deck)
    if errs:
        print("[INVALID]")
        for e in errs:
            print(" -", e)
        raise SystemExit(1)
    print("[OK] overrides valid")
