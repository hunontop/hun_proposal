# -*- coding: utf-8 -*-
"""문자열 기대 자리의 관용 코어스 + 기록 (W32 마찰28).

**왜 있나**: fields는 LLM 산출물이고, 문자열을 기대하는 자리에 `{"name":.., "description":..}`
같은 객체를 넣는 것은 구조화 필드에서 나오는 **자연스러운 오답**이다(shape가 프롬프트에
미문서인 template일수록 잦다). 종전에는 각 렌더러의 `_esc`가 `str(dict)`를 그대로 조판해
`{'name'` 같은 원시 dict가 **심사위원이 보는 장표에** 노출됐고, render warnings=0이라 사람이
정독하기 전까지 아무도 못 잡았다(시연 1차 장 4·13 실측).

**계약**: 살리되 숨기지 않는다 — 객체는 사람이 읽을 문자열로 접고(`라벨: 상세`),
그 사실을 `records`에 남겨 호출자가 warnings로 표면화한다. 고칠 곳은 상류 storyline의
shape이므로 조용한 정상화는 정직성 계약 위반이다.

**공용인 이유**: 렌더 경로가 넷이다 — `htmlgen`(엔진 REGISTRY)·`compose`(골격×조각)·
`layouts_core`(agenda·process_steps·table_block·timeline_matrix·endcard = 마찰28⒞가 지목한
shape 미문서 template들이 여기 산다)·`docgen`(deck.doc.html 정독 뷰). 각자 `_esc`를 갖고 있어
한 곳만 고치면 나머지 셋이 그대로 샌다.
"""
from __future__ import annotations

import json
from typing import Any

# 객체를 접을 때 라벨·상세로 쓸 키 후보(먼저 맞는 것 하나만 쓴다).
LABEL_KEYS = ("label", "name", "title", "term", "key", "step", "phase")
DETAIL_KEYS = ("description", "detail", "desc", "text", "summary", "value", "note", "content")

# 렌더 1회분 코어스 기록. 호출자(render_html/render_slide)가 reset→drain으로 수거한다.
records: list[str] = []


def as_text(x: Any) -> str:
    """문자열 기대 자리의 관용 코어스. str/숫자/None은 종전 동작과 동일(바이트 불변)."""
    if x is None:
        return ""
    if isinstance(x, str):
        return x
    if isinstance(x, dict):
        label = next((str(x[k]) for k in LABEL_KEYS if x.get(k)), "")
        detail = next((str(x[k]) for k in DETAIL_KEYS if x.get(k)), "")
        if not label and not detail:
            # 알려진 키가 하나도 없으면 값만 이어 붙인다 — 원시 dict 노출보다는 낫다.
            detail = " · ".join(str(v) for v in x.values() if v not in (None, "", [], {}))
        records.append(f"객체→문자열 코어스: {json.dumps(x, ensure_ascii=False)[:120]}")
        return f"{label}: {detail}" if (label and detail) else (label or detail)
    if isinstance(x, (list, tuple)):
        records.append(f"배열→문자열 코어스: {json.dumps(list(x), ensure_ascii=False, default=str)[:120]}")
        return " · ".join(as_text(i) for i in x if i not in (None, ""))
    return str(x)


def reset() -> None:
    records.clear()


def drain() -> list[str]:
    """수거 + 비우기. 같은 슬라이드에서 반복된 같은 코어스는 1건으로 접는다."""
    out = list(dict.fromkeys(records))
    records.clear()
    return out
