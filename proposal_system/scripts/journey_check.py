# -*- coding: utf-8 -*-
"""W31 리허설 마찰4(CONTEXT/REHEARSAL_FRICTIONS_W31.md #4) — journey 폴더의 관문 확인 채널.

배경(사용자 확정 2026-07-21): ack 관문마다 대시보드로 이동해 버튼을 눌러야 하는 것이 마찰이었다.
해법: 사람이 정지 관문에 도달했을 때 그 관문의 journey 단계 폴더에 `검토_체크.md`(사람 편집물)를
발급한다 — 검토물 옆에서 `[x]` 체크만 하면 다음 `go`가 수거해 대시보드 버튼과 동등한 ack를 남긴다.

  - **발급**: `issue(run, gate)` — go가 사람 관문에서 멈출 때마다 호출(멱등 — 같은 라운드면 재작성
    안 함, 사람이 체크 중인 내용을 건드리지 않는다).
  - **수거**: `collect_ack(run, gate)` — 다음 go가 호출. `[x]` + 라운드 토큰 일치를 확인하면
    `checkpoint_ack/<gate>.json`(via="journey_check")을 쓴다. 이미 유효한 사람 ack(대시보드든
    이 채널이든)가 있으면 손대지 않는다("먼저 온 쪽이 이김").
  - **재무장**: 감시 산출물이 바뀌면(`pipeline_state.HUMAN_CHECKPOINT_WATCH`) 라운드 토큰이
    달라진다 — `issue()`가 이를 감지해 새 토큰의 미체크 양식을 재발급한다. 이전 체크는 이미
    ack json에 소비·기록되어 있으므로 유실이 아니다.

**무결성 규율**: 이 채널이 만드는 파일은 사람 전속이다 — Claude(정주행이든 어느 세션이든)는
체크박스를 대신 채우지 않는다(대시보드 버튼과 동일 등급, CLAUDE.md "정주행·리허설 세션 규약" 참고).

라운드 토큰은 그 관문의 감시 대상 산출물(`HUMAN_CHECKPOINT_WATCH`) mtime에서 결정론으로 유도한다
(LLM 없음·0토큰) — "무장 시각 기반 문자열"을 실제로 재무장을 유발하는 그 타임스탬프들로 구현한
것이다(별도 상태 파일 없이 파일끼리 대조하는 이 리포의 기존 관례, `pipeline_state.is_stale`과
동형). 새 "지금 시각"을 찍어 저장했다면 다음 go 시점에 그 값을 재현할 방법이 없어 검증이 불가능
하므로, 재현 가능한 mtime 기반 해시를 쓴다.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

CHECK_NAME = "검토_체크.md"

HUMAN_ONLY_HEADER = (
    "> ✋ 사람 전속 — Claude(어느 세션이든)는 이 체크를 절대 대신 채우지 않는다"
    "(대시보드 버튼과 동일 등급). 대신 채운 흔적이 발견되면 그 판단은 무효로 취급한다.\n\n"
)

# 관문 -> journey 폴더 키(REHEARSAL_FRICTIONS_W31.md #4 근거 — gates.py 패킷 보고 기준 매핑).
# design_refs는 폴더가 없다(기존 갭 — 대시보드 채널만 유지, 이 모듈은 조용히 발급하지 않는다).
GATE_FOLDER_KEY: dict[str, str] = {
    "skeleton_review": "04",
    "decision": "05",
    "wireframe_review": "06",
    "theme_confirm": "07",
    "imagedeck_prompt_ack": "08",
    "imagedeck_ack": "11",
    "design": "12",
}

_TOKEN_RE = re.compile(r"<!--\s*round-token:\s*([0-9a-fA-F]+)\s*-->")
# W32 마찰32: 사람이 손으로 편집하는 채널이라 **사람의 오타를 전제**해야 한다. 종전 `\[([ xX])\]`는
# 대괄호 안이 정확히 한 글자일 때만 맞아, `[x ]`(x 뒤 공백)로 저장하면 미체크로 판정하고 go는
# "ack 없음"만 반복했다 — 사용자는 체크했는데 왜 안 넘어가는지 알 수 없었다(실측: go 2회 무반응).
# 공백 변형(`[x]`·`[X]`·`[x ]`·`[ x]`·`[  X ]`)을 전부 수용한다. 대시보드 버튼에는 없는 실패 모드다.
_REVIEW_RE = re.compile(r"-\s*\[\s*([xX])?\s*\]\s*검토 완료")
_SKIP_RE = re.compile(r"-\s*\[\s*([xX])?\s*\]\s*건너뛰기")
# ⒝ 그래도 남는 미지 표기(`[v]`·`[o]`·`[✓]` 등)는 조용히 무시하지 않고 사람에게 알린다.
_UNKNOWN_MARK_RE = re.compile(r"-\s*\[\s*([^\]\sxX][^\]]*)\]\s*(검토 완료|건너뛰기)")

# KC 패킷(2026-07-24 확정) — 이 관문의 검토_체크.md에 지식 체크 수행 확인 항목을 덧붙인다
# (express 프로파일은 생략). decision=①(기획 입구), imagedeck_ack=③(산출 출구) 대응.
# 정보용 체크박스일 뿐 collect_ack의 판정(검토 완료/건너뛰기)에는 관여하지 않는다.
_KC_GATE_ITEM: dict[str, str] = {
    "decision": ("지식 체크 확인 — ① 기획 입구(ref/기획지식/메시지설계·ref/기획지식/경험설계 "
                 "pull 인용, message_map.json/storyline.json 대조)"),
    "imagedeck_ack": ("지식 체크 확인 — ③ 산출 출구(imagedeck_review.md의 "
                       "'지식 대조' 섹션 수행)"),
}


def _folder(run: Path, gate: str):
    import journey_folders  # sibling, 지연 임포트(순환 방지 — 이 리포 전역 관례)

    key = GATE_FOLDER_KEY.get(gate)
    if key is None:
        return None
    return journey_folders.folder_path(Path(run), key)


def round_token(run: Path, gate: str) -> str:
    """관문의 감시 산출물 mtime에서 유도한 결정론 토큰. 재무장(mtime 변경) 때만 값이 바뀐다."""
    import pipeline_state  # sibling, 지연 임포트

    watch = pipeline_state.HUMAN_CHECKPOINT_WATCH.get(gate, ())
    parts = [f"gate={gate}"]
    for name in watch:
        p = Path(run) / name
        if p.is_file():
            try:
                parts.append(f"{name}@{p.stat().st_mtime_ns}")
                continue
            except OSError:
                pass
        parts.append(f"{name}@absent")
    raw = "|".join(parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _extract_token(text: str) -> str | None:
    m = _TOKEN_RE.search(text)
    return m.group(1) if m else None


def _extract_checks(text: str) -> tuple[bool, bool]:
    m1 = _REVIEW_RE.search(text)
    m2 = _SKIP_RE.search(text)
    return bool(m1 and m1.group(1)), bool(m2 and m2.group(1))


def _unknown_marks(text: str) -> list[str]:
    """인식 불가 체크 표기 목록(마찰32⒝) — `[x]`로 고치라고 알려 주기 위한 재료."""
    return [f"[{m.group(1)}] {m.group(2)}" for m in _UNKNOWN_MARK_RE.finditer(text)]


def _render(run: Path, gate: str, token: str) -> str:
    import gates  # sibling, 지연 임포트(순환 방지)
    import journey_folders  # sibling, 지연 임포트
    import pipeline_state  # sibling, 지연 임포트

    label = pipeline_state.CHECKPOINT_LABEL.get(gate, gate)
    key = GATE_FOLDER_KEY[gate]
    skippable = gate in gates.SKIPPABLE_GATE_IDS
    lines = [
        HUMAN_ONLY_HEADER,
        f"# 검토_체크 — {label}",
        "",
        f"관문: `{gate}` (폴더 `{journey_folders.FOLDERS[key]}`)",
        "",
        "## 무엇을 보고 판단하나",
        f"- 이 폴더의 `{journey_folders.MANUAL_NAME}`(안내)와 `{OUTPUT_VIEW_NAME}`"
        "(이 폴더의 산출물·계보 — 있다면)을 먼저 본다.",
        "- 대시보드(http://127.0.0.1:8754)에서 같은 관문을 봐도 된다(등가 채널 — 아무 쪽이나).",
        "",
        "## 체크",
        "> 대괄호 안에 `x`를 넣으면 된다 — `[x]`. 앞뒤 공백(`[x ]`·`[ x]`)이나 대문자(`[X]`)도 인정한다."
        " 다른 표시(`[v]`·`[o]` 등)는 인정하지 않고, 그런 게 있으면 다음 `go`가 알려 준다.",
        "",
        "- [ ] 검토 완료",
    ]
    if skippable:
        lines.append("- [ ] 건너뛰기(스킵 가능 관문만 표기)")
    else:
        lines.append("- (이 관문은 건너뛸 수 없음 — 검토 완료만 가능, 대시보드와 동일 제약)")
    kc_item = _KC_GATE_ITEM.get(gate)
    if kc_item and gates.load_config(run)["profile"] != "express":
        lines.append(f"- [ ] {kc_item}")
    lines += [
        "",
        f"<!-- round-token: {token} -->",
        "",
        "> 체크 후 다음 `go`가 이 표시를 수거해 checkpoint_ack에 기록한다(대시보드 버튼을 누른 것과 "
        "동일하게 취급). 위 체크박스만 고치고 라운드 토큰 줄은 건드리지 않는다 — 감시 산출물이 "
        "다시 바뀌면(재무장) 다음 go가 새 토큰의 미체크 양식으로 갈아 끼운다(이전 체크는 이미 "
        "기록되어 유실이 아니다).",
    ]
    return "\n".join(lines) + "\n"


OUTPUT_VIEW_NAME = "산출물.html"  # journey_folders.py와 공유하는 이름(원 정의는 그쪽).


def issue(run: Path, gate: str) -> Path | None:
    """사람 관문에서 go가 멈출 때 호출 — 없거나 라운드가 낡았으면 새로 쓴다.

    반환값은 "이번 호출에서 실제로 (재)작성했는가"다 — 이미 이번 라운드 양식이 있으면(사람이
    체크 중일 수 있다) None을 반환하고 손대지 않는다.
    """
    folder = _folder(run, gate)
    if folder is None or not Path(folder).is_dir():
        return None  # design_refs처럼 폴더 매핑이 없거나, 아직 그 폴더가 열리지 않았다.
    token = round_token(run, gate)
    path = Path(folder) / CHECK_NAME
    if path.is_file():
        try:
            existing = path.read_text(encoding="utf-8")
        except OSError:
            existing = ""
        if _extract_token(existing) == token:
            return None  # 이미 이번 라운드 양식 — 사람이 체크 중일 수 있으니 건드리지 않는다.
    text = _render(run, gate, token)
    path.write_text(text, encoding="utf-8")
    return path


def read(run: Path, gate: str) -> dict[str, Any] | None:
    """현재 검토_체크.md의 파싱 결과(표시/디버깅용) — {path, token, token_current, review_done, skip_done}."""
    folder = _folder(run, gate)
    if folder is None:
        return None
    path = Path(folder) / CHECK_NAME
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    review_done, skip_done = _extract_checks(text)
    return {
        "path": path,
        "token": _extract_token(text),
        "token_current": round_token(run, gate),
        "review_done": review_done,
        "skip_done": skip_done,
        "unknown_marks": _unknown_marks(text),   # 마찰32⒝: 조용한 무시 제거
    }


def collect_ack(run: Path, gate: str) -> Path | None:
    """검토_체크.md의 [x]+토큰 일치를 확인해 checkpoint_ack/<gate>.json(via="journey_check")을 쓴다.

    이미 유효한 사람 ack(대시보드든 이 채널이든)가 있으면 손대지 않는다 — "먼저 온 쪽이 이긴다"의
    구현: 이 함수는 read_any_ack로 선점 여부부터 확인한다. 토큰 불일치(구 라운드 체크)는 조용히
    무시한다(다음 go의 issue()가 새 양식을 재발급한다).
    """
    import datetime as dt
    import json as _json

    import gates  # sibling, 지연 임포트
    import pipeline_state  # sibling, 지연 임포트

    existing = pipeline_state.read_any_ack(run, gate)
    if (existing and existing.get("via") in pipeline_state.HUMAN_ACK_VIA
            and existing.get("decision") in ("confirm", "skip")):
        return None  # 이미 사람 ack가 있다(어느 채널이든) — 재작성하지 않는다.

    view = read(run, gate)
    if view is None or view["token"] != view["token_current"]:
        return None  # 파일이 없거나, 구 라운드 체크(재무장 이후) — 무시.

    decision: str | None = None
    if view["skip_done"] and gate in gates.SKIPPABLE_GATE_IDS:
        decision = "skip"
    elif view["review_done"]:
        decision = "confirm"
    if decision is None:
        return None  # 아직 체크 안 함.

    payload = {
        "gate": gate,
        "decision": decision,
        "via": "journey_check",
        "at": dt.datetime.now().isoformat(timespec="microseconds"),
    }
    path = pipeline_state.ack_path(Path(run), gate)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
