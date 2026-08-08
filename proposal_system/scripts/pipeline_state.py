"""N1 공정 상태머신 — `run/pipeline_state.json`.

설계 원칙(NORTHSTAR_REDESIGN §2-1 "상태는 코드가 답한다"):
  - **결정론·0토큰.** 이 모듈은 LLM을 호출하지 않는다. 파일 존재/타임스탬프만 읽는다.
  - **state.json이 정본.** 각 커맨드가 완료 시 자기 단계를 기록한다(`record()`).
  - **레거시 run은 산출물에서 추론.** state.json이 없던 시절의 run도 `status`가 답해야 하므로
    산출물 지문으로 역추론하되, 반드시 `source="inferred"`로 표시해 정직성을 유지한다
    (S6-1 정직화와 같은 계열 — 모르는 걸 아는 척하지 않는다).
  - **W1 관측 갭 해소(W3a).** `stage9 --apply`는 이제 `gating_report.applied_axes.html`을
    실측 갱신한다(overrides=true·image_slots=N). 그래도 상태의 정본은 state.json이다 —
    render가 다시 돌면 gating_report는 통째로 재작성되어 overrides=false로 돌아가기 때문.
    적용 여부의 근거 순서: (a) state.json의 stage9_apply 기록, (b) 레거시라면
    `deck.pre_stage9.html`(apply만이 쓰는 유일한 지문).

단계 이름은 커맨드 이름이다(§5 "stage 번호 개명 금지" — 별칭·라벨로만 해결).
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
STATE_NAME = "pipeline_state.json"

MODES = ("secure", "direct")

# 사용자 표면 체크포인트 3개(§3.0). 이 외에는 사람에게 묻지 않는다.
CHECKPOINTS = ("start", "decision", "design")

# 선택 관문(DESIGN_ASSETS_LANE §5-④ 후속, 사용자 결정 2026-07-14 "B"). 의무 3개와 다르다:
#   **건너뛸 수 있다** — `go --confirm` 한 번이면 통과(했든 안 했든). 하지만 소프트 정지와 달리
#   `go`를 다시 쳐도 자동으로 안 지나간다(에이전트가 무심코 밀고 지나가는 것을 막는다 —
#   정주행에서 "절차 없이 그대로 넘어가는" 문제의 해결). human 관문은 감시 산출물 변경 시 재무장된다.
#   ⚠️ 예외: 이 목록의 일부(`design_refs`·`skeleton_review`·`wireframe_review`·`theme_confirm`)는
#   HUMAN_CHECKPOINTS와도 겹친다 — 겹치는 이름에 한해 `go --confirm`은 무효다(MANUAL.md §2
#   "human 관문 = 사람 전속 ack" 참조, 대시보드 버튼·검토_체크.md만 유효). "건너뛸 수 있다"는
#   OPTIONAL_CHECKPOINTS 전용 항목(`research`)에만 그대로 적용된다 — 이 파일 안에서 두 집합이
#   겹치는 것은 모순이 아니라 "선택이지만 human 확인은 필요"라는 별개 축(HUMAN_CHECKPOINTS)이
#   추가로 걸린 것이다.
OPTIONAL_CHECKPOINTS = ("research", "design_refs", "skeleton_review", "wireframe_review", "theme_confirm")
# W28(D8·D10): 라우트 전속 관문 — image_infographic 라우트에서만 표면화한다(html_editable엔 안 뜸).
#   OPTIONAL/CHECKPOINTS 어디에도 안 넣어 기존 run 흐름·표시에 새지 않게 하고,
#   ALL_CHECKPOINTS에만 넣어 ack 기록(clear_checkpoint 검증)·재무장을 허용한다.
ROUTE_CHECKPOINTS = ("imagedeck_prompt_ack", "imagedeck_ack")
# 사람 전속 관문. OPTIONAL_CHECKPOINTS와 겹쳐도 된다(스키마·라벨 하위호환 유지).
HUMAN_CHECKPOINTS = ("skeleton_review", "decision", "wireframe_review", "design_refs", "design",
                     "imagedeck_prompt_ack", "imagedeck_ack", "theme_confirm")
ACK_DIR = "checkpoint_ack"
ALL_CHECKPOINTS = CHECKPOINTS + OPTIONAL_CHECKPOINTS + ROUTE_CHECKPOINTS

# W31 마찰18(β): 테마 게이트(theme_confirm/design_contract) 이후의 하류 단계들 — "지난 run은
# 소급 안 함" 판정(_next_step)과 "재동결 후 재적용 안내"(proposal_pipeline._refreeze_contract)가
# 공유하는 목록. 여기 하나만 바꾸면 두 곳 다 반영된다.
DOWNSTREAM_OF_THEME_STAGES = (
    "stage9_bundle", "stage9_apply", "refine_bundle", "refine_collect", "refine_handoff",
    "imagedeck_bundle", "imagedeck_collect", "imagedeck_compose",
    "deck_review_bundle", "deck_review", "approve",
)

HUMAN_CHECKPOINT_WATCH = {
    "skeleton_review": ("skeleton.json",),
    "decision": ("storyline.json", "message_map.json"),
    "wireframe_review": ("wireframe.json",),
    "design_refs": ("design_spec.json",),
    "design": ("deck.html",),
    # W30: 생산 전 프롬프트·레퍼런스 확인 — 재번들(manifest 갱신)마다 재무장.
    "imagedeck_prompt_ack": ("imagedeck_manifest.json",),
    # W28: 이미지 갱신마다 재정지 — 번들 재생성(manifest) 또는 재수거(collect)가 ack보다 최신이면 재무장.
    "imagedeck_ack": ("imagedeck_manifest.json", "imagedeck_collect.json"),
    # W31 R3: 테마(디자인 계약)가 다시 동결되면(design_contract.json mtime 갱신) 재확인 요구.
    "theme_confirm": ("design_contract.json",),
}

CHECKPOINT_LABEL = {
    "start": "시작 결정 (입력 + 모드)",
    "decision": "의사결정 게이트 (스토리라인·방향 확정 + 디자인 브리핑)",
    "design": "디자인 게이트 (완성 덱 검토)",
    # 선택 관문(의무 아님 — 건너뛰기 = go --confirm)
    "research": "발주처 조사 (선택 — 문서 밖 근거·브랜드 색)",
    "design_refs": "디자인 레퍼런스 검토 (선택 — 참고 파일·링크)",
    "skeleton_review": "스켈레톤 검토 (역제안 구조 확인 - 스토리라인 생성 전)",
    "wireframe_review": "뼈대 검토 (재조판 확인 - 테마 입히기 전)",
    # W30: 생산 전 확인 — 기대와 다른 이미지에 토큰을 태우기 전에 방향을 사람이 확정.
    "imagedeck_prompt_ack": "이미지 프롬프트·레퍼런스 확인 (생산 전 - image 라우트)",
    # W28(D10): 이미지 라우트 전속 — 사람이 이미지 장표를 정독·국소 교정 후 채택.
    "imagedeck_ack": "이미지 장표 승인 (사람 정독 후 채택 - image 라우트)",
    # W31 R3: 테마 확정 게이트 — 선택(회의 없이 기본값 진행 허용), 대시보드에서 ack 가능.
    "theme_confirm": "테마 확정 (디자인 계약 동결 확인 - 선택, 07_테마확정/design_contract_읽기.md 참고)",
}

# 내부 단계 → 사람이 읽는 라벨 (개명이 아니라 표시용 별칭)
STAGE_LABEL = {
    "start": "시작 (입력·모드 확정)",
    # W10: 탐색 루프의 시작 = 백지가 아니라 역제안 — 표준 시나리오 전 장표 더미 렌더(0토큰).
    "skeleton": "스켈레톤 역제안 (표준 시나리오 더미 덱 · W10)",
    # W26(목표조정 8·9): 분석([1])의 선택 서브스텝 — RFP 밖 문서 밖 근거 + 브랜드 토큰→스킨.
    # go 의무화 아님(CHECKPOINT_IMPLIED_BY 변경 없음) — [1] 안의 선택지.
    "research_bundle": "기관 조사 - 조사 프롬프트 (문서 밖 근거 · P1.3)",
    "research_apply": "기관 조사 - 수거 검증·브랜드 스킨 등록",
    # W15: 메시지 우선 공정(결정 9①) — RFP분석 후·스토리라인 전 1급 산출물. 핸드오프→검증.
    "message_map_bundle": "메시지맵 핸드오프 프롬프트 (핵심 주장·전략 축 · W15)",
    "message_map": "메시지맵 수거·검증 (message_map.json · 결정 9①)",
    "storyline_bundle": "브리프→스토리라인 프롬프트 번들 (N2)",
    "render": "렌더 (deck.json/html + 배지)",
    # W7-C2: 해소가 브리핑보다 **먼저**다. 브리핑의 evidence_candidates는 review_badges(=태그 존재)에서
    # 나오므로, 해소 전에 브리핑을 만들면 이미 서명으로 지운 슬라이드가 후보로 잔존한다.
    "review_resolve": "검토요망 해소 적용 (review_resolutions.json → 재렌더 · W5)",
    # W21(결정 10 [3]·결정 12): [3] 뼈대 잡기 — 내용 동결(✋②) 후·테마(stage9) 전. go 자동 편입.
    # decision 체크포인트가 게이트(동결 전 탐색 루프에선 next로 안 뜬다 — _next_step이 decision 뒤에서만 도달).
    # design_brief(방향·스킨·이미지 계획)보다 앞 — 뼈대(무채 형태)를 먼저 잡고 그 위에 디자인을 얹는다.
    "wireframe_bundle": "뼈대 잡기 - frame×piece 결정 프롬프트 (W21 · 무채)",
    "wireframe_apply": "뼈대 잡기 - 결정 검증·병합·무채 재렌더 (재게이트)",
    "design_brief": "디자인 브리핑 (의사결정 게이트 산출물)",
    # W31 R2·R5: run별 디자인 계약 동결 — design_brief 직후·(이미지 번들|stage9 번들) 전(B1).
    "design_contract": "디자인 계약 동결 (run별 정본 - chrome/image 2계약 분리 · W31 R2·R5)",
    "stage9_bundle": "디자인 입히기 - 정련 프롬프트 (코드명 stage9)",
    "stage9_fill_images": "이미지 슬롯 채움",
    "stage9_apply": "디자인 입히기 - 정련 적용 (override 병합)",
    # W23(결정 15·16·17): ④+ 디자인 고도화 — 기본 디자인 후·평가 전 부품(go 의무화 아님).
    "refine_bundle": "디자인 고도화 - 목표 명세 프롬프트 (4+ · 결정 16)",
    "refine_collect": "디자인 고도화 - 명세 검증·레퍼런스 수집 (형태 축 · 결정 17)",
    "refine_handoff": "디자인 고도화 - 실행 핸드오프 (내용 동결·diff 심판)",
    # W28(D8~D13): image_infographic 라우트 전용 단계 — stage9/refine 대신 이 셋을 관통한다.
    "imagedeck_bundle": "이미지 장표 - 프롬프트 번들 (장별·D12 역산 · W28)",
    "imagedeck_collect": "이미지 장표 - 수거 검증 (PNG px 실측·커버리지)",
    "imagedeck_compose": "이미지 장표 - HTML 크롬 조합 (deck.images.html)",
    "deck_review_bundle": "덱 평가 프롬프트 (승인 전 · W3c)",
    "deck_review": "LLM 덱 평가 수거 (deck_review.md)",
    "approve": "승인",
}

STAGE_ORDER = list(STAGE_LABEL)


# ---------------------------------------------------------------------------
# 로드 / 저장
# ---------------------------------------------------------------------------

def state_path(run: Path) -> Path:
    return Path(run) / STATE_NAME


def now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _mtime(path: Path) -> str:
    return dt.datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")


def _parse(stamp: str | None) -> dt.datetime | None:
    if not stamp:
        return None
    try:
        return dt.datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None


def _blank(run: Path) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_dir": str(run),
        "run_id": Path(run).name,
        "mode": None,
        "input": None,
        "selection": None,
        "created_at": None,
        "updated_at": None,
        "stages": {},
        "checkpoints": {name: {"cleared_at": None} for name in ALL_CHECKPOINTS},
    }


def load(run: Path) -> dict[str, Any]:
    """기록된 state.json (없으면 빈 골격)."""
    path = state_path(Path(run))
    if not path.is_file():
        return _blank(Path(run))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _blank(Path(run))
    base = _blank(Path(run))
    base.update(data)
    # 이후 스키마 확장에도 키가 항상 존재하도록 보정
    base.setdefault("stages", {})
    cps = base.setdefault("checkpoints", {})
    for name in ALL_CHECKPOINTS:
        cps.setdefault(name, {"cleared_at": None})
    return base


def save(run: Path, state: dict[str, Any]) -> Path:
    run = Path(run)
    run.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = now()
    path = state_path(run)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def init(
    run: Path, *, mode: str, input_kind: str, input_ref: str,
    selected_by: str | None = None, bid: str | None = None, feedback_match: bool | None = None,
) -> dict[str, Any]:
    """`start` 전용 — run의 모드·입력을 확정하고 state를 만든다.

    결정 8(§6): 공고 선택 출처(`selected_by`)도 여기서 함께 확정한다 —
    사람 전속 판단(무엇에 입찰하나)의 출처를 기록만 하고 차단은 하지 않는다.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}: {mode!r}")
    state = load(run)
    state["mode"] = mode
    state["input"] = {"kind": input_kind, "ref": input_ref}
    state["selection"] = {
        "selected_by": selected_by or "unspecified",
        "bid": bid,
        "feedback_match": feedback_match,
    }
    state["created_at"] = state.get("created_at") or now()
    stamp = now()
    state["stages"]["start"] = {"at": stamp, "source": "recorded", "artifacts": {}}
    state["checkpoints"]["start"] = {"cleared_at": stamp}
    save(run, state)
    # W29 메인 루트 승격(2026-07-20 사용자 결정): 신규 run은 image_infographic이 기본.
    # 명시 파일 기록이라 ✋②에서 사람이 html_editable로 바꾸는 자유는 그대로다.
    # 기존 run(파일 없음)은 render_route() 폴백=html_editable — 하위호환 불변.
    route_file = Path(run) / ROUTE_FILE
    if not route_file.is_file():
        set_render_route(run, "image_infographic", "auto", chosen_by="default_main_route")
    return state


def record(run: Path, stage: str, *, artifacts: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    """커맨드 완료 시 자기 단계를 기록한다. state.json이 없어도 조용히 만든다(레거시 run 승격).

    호출부(render/stage9/approve)는 실패해도 본 공정을 막지 않아야 하므로 예외를 삼키지 않는다 —
    대신 호출부가 try/except로 감싼다(기록 실패가 산출물 생성을 되돌리지 않도록).
    """
    state = load(run)
    entry: dict[str, Any] = {"at": now(), "source": "recorded", "artifacts": artifacts or {}}
    entry.update(extra)
    state["stages"][stage] = entry
    state["created_at"] = state.get("created_at") or entry["at"]
    save(run, state)
    return state


def clear_checkpoint(run: Path, name: str) -> dict[str, Any]:
    if name not in ALL_CHECKPOINTS:
        raise ValueError(f"unknown checkpoint: {name}")
    state = load(run)
    state["checkpoints"][name] = {"cleared_at": dt.datetime.now().isoformat(timespec="microseconds")}
    save(run, state)
    return state


def ack_path(run: Path, name: str) -> Path:
    return Path(run) / ACK_DIR / f"{name}.json"


# W31 리허설 마찰4: 대시보드 버튼과 journey 폴더의 검토_체크.md(journey_check.py)는 등가 채널이다 —
# 둘 다 "사람이 직접 확인했다"는 provenance를 남긴다. 이 튜플이 사람 ack로 인정하는 via의 전부다.
HUMAN_ACK_VIA = ("dashboard", "journey_check")


def read_ack(run: Path, name: str) -> dict[str, Any] | None:
    """사람이 직접 남긴 유효한 관문 ack만 읽는다(대시보드 버튼 또는 journey 폴더 체크 — 파이프라인은
    스스로 생성하지 않는다). 두 채널 중 먼저 기록된 쪽이 파일을 선점하며, 그 뒤로는 어느 채널도
    다른 채널의 기록을 덮어쓰지 않는다(journey_check.collect_ack가 이미 유효한 ack가 있으면
    쓰지 않는 것으로 보장 — W27 D4의 "대시보드만 쓴다" 불변은 그대로, journey_check도 같은 규율)."""
    path = ack_path(run, name)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("gate") != name or data.get("via") not in HUMAN_ACK_VIA:
        return None
    if data.get("decision") not in ("confirm", "skip"):
        return None
    if not isinstance(data.get("at"), str) or not data["at"].strip():
        return None
    return data


def read_any_ack(run: Path, name: str) -> dict[str, Any] | None:
    """표시 전용 조회 — via 불문 ack를 읽는다(W31 R-마찰2: gates.py의 자동 통과 기록도 보인다).

    신뢰 판정(사람이 실제로 확인했는가)에는 절대 쓰지 않는다 — 그건 `read_ack`(via=='dashboard'만
    인정) 전속이다. 이 함수는 status/journey 표시가 "자동 통과(신호 깨끗)"인지 사람 confirm/skip인지
    구분해서 보여주기 위한 것뿐이다.
    """
    path = ack_path(run, name)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def is_human(name: str) -> bool:
    return name in HUMAN_CHECKPOINTS


# W28(D8·D13): 렌더 2분기. route/wireframe_mode는 ✋②(decision) ack 시점에 대시보드가
# run/render_route.json에 영속화한다(wireframe보다 앞서 알아야 skip 가능 - D13).
# 파일이 없으면 기존 공정 그대로(html_editable) — 기존 run은 바이트 동일하게 흐른다.
RENDER_ROUTES = ("html_editable", "image_infographic")
ROUTE_FILE = "render_route.json"


def render_route(run: Path) -> tuple[str, str]:
    """(route, wireframe_mode). 기본=('html_editable','auto'). image 라우트에서만 분기가 켜진다."""
    p = Path(run) / ROUTE_FILE
    if not p.is_file():
        return "html_editable", "auto"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "html_editable", "auto"
    route = data.get("route") if isinstance(data, dict) else None
    mode = data.get("wireframe_mode") if isinstance(data, dict) else None
    if route not in RENDER_ROUTES:
        route = "html_editable"
    if mode not in ("on", "off", "auto"):
        mode = "auto"
    return route, mode


def set_render_route(run: Path, route: str, wireframe_mode: str = "auto",
                     chosen_by: str = "dashboard") -> Path:
    """✋② ack 화면(또는 테스트)이 라우트를 확정한다. 검증 후 render_route.json 기록."""
    if route not in RENDER_ROUTES:
        raise ValueError(f"route must be one of {RENDER_ROUTES}: {route!r}")
    if wireframe_mode not in ("on", "off", "auto"):
        raise ValueError(f"wireframe_mode must be on/off/auto: {wireframe_mode!r}")
    p = Path(run) / ROUTE_FILE
    p.write_text(json.dumps(
        {"route": route, "wireframe_mode": wireframe_mode,
         "chosen_by": chosen_by, "chosen_at": now()},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def imagedeck_images_present(run: Path) -> bool:
    """번들 manifest의 모든 out_name이 imagedeck/slides/에 실재하는지(= Codex 생산 완료)."""
    run = Path(run)
    mp = run / "imagedeck_manifest.json"
    if not mp.is_file():
        return False
    try:
        manifest = json.loads(mp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    slides = manifest.get("slides") or []
    # W29: HTML 전용 장(cover/toc/divider)은 이미지 생산 대상이 아니다 - compose가 렌더.
    image_slides = [s for s in slides if s.get("render") != "html"]
    if not image_slides:
        return False
    sd = run / "imagedeck" / "slides"
    return all((sd / s.get("out_name", "")).is_file() for s in image_slides)


def imagedeck_progress(run: Path) -> "tuple[int, int]":
    """(생산된 장 수, 대상 장 수) — W32 마찰27 진행률 표시용. 판정 로직은 건드리지 않는다.

    이미지 생산은 장당 수십 초~수 분 × 20장이라 중단·재개가 잦은 구간인데, 종전 status는
    "생산 이미지가 아직 없다"만 말해 5/20 상태로 돌아온 사람이 처음부터 다시 도는 줄 알았다.
    `--produce`는 원래 미생산 장만 처리하는 재실행 안전 설계다 — 그 사실을 보이게 만든다.
    """
    run = Path(run)
    mp = run / "imagedeck_manifest.json"
    if not mp.is_file():
        return (0, 0)
    try:
        manifest = json.loads(mp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return (0, 0)
    image_slides = [s for s in (manifest.get("slides") or []) if s.get("render") != "html"]
    sd = run / "imagedeck" / "slides"
    done = sum(1 for s in image_slides if (sd / s.get("out_name", "")).is_file())
    return (done, len(image_slides))


def _gate_note(run: Path, name: str) -> str:
    """W31 R-마찰2: gates.py 판정을 checkpoint의 why에 한 줄 덧붙인다(읽기 전용 — 파일을 쓰지 않는다).

    gates.py 대상이 아닌 체크포인트(start·decision·design 등)는 빈 문자열 — 표시가 그대로다.
    실패(임포트·판독 오류)는 조용히 무시한다 — 이 안내는 부가 정보이지 상태 조회를 깨뜨릴 이유가
    아니다(다른 _*_warnings 헬퍼와 같은 관례).
    """
    try:
        import gates  # sibling, 지연 임포트(순환 방지 — message_map/design_contract와 동일 관례)
    except Exception:
        return ""
    if name not in gates.GATE_IDS:
        return ""
    try:
        d = gates.decide(run, name)
    except Exception:
        return ""
    if d["action"] == "auto_pass":
        return f"[관문 프로파일={d['profile']}: 다음 go에서 자동 통과 예정 - {d['reason']}]"
    if d.get("mode") == "auto":
        return f"[관문 프로파일={d['profile']}: 자동 통과 대상이었으나 신호 나쁨 - 정지 유지({d['reason']})]"
    return f"[관문 프로파일={d['profile']}: 정지 관문]"


def is_stale(run: Path, name: str, cleared_at: str | None) -> str | None:
    """human 관문 감시 산출물이 clearance/ack보다 최신이면 첫 파일명을 반환한다."""
    stamp = _parse(cleared_at)
    if stamp is None:
        return None
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone().replace(tzinfo=None)
    for filename in HUMAN_CHECKPOINT_WATCH.get(name, ()):
        path = Path(run) / filename
        if not path.is_file():
            continue
        try:
            mtime = dt.datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            continue
        # 주의: 이 비교는 ack 타임스탬프가 **파일 mtime과 같은 해상도**여야 옳다. 그래서
        # ack을 쓰는 세 통로가 모두 마이크로초를 남긴다(dashboard/server.py의 /api/ack ·
        # journey_check.collect_ack · gates.py). mtime을 초로 내려 맞추려 하지 말 것 —
        # 그러면 "ack 뒤의 재번들 = 재무장"이 같은 초 안에서 죽는다(W32에 시도했다가 되돌림:
        # theme_confirm·imagedeck 재무장 검증 3종이 깨졌다).
        if mtime > stamp:
            return filename
    return None


# ---------------------------------------------------------------------------
# 레거시 추론 — 산출물 지문
# ---------------------------------------------------------------------------

def infer(run: Path) -> dict[str, dict[str, Any]]:
    """state.json 없이 만들어진 run의 단계를 산출물에서 역추론.

    각 지문은 "그 커맨드만이 남기는 파일"이어야 한다. 특히 stage9_apply의 지문은
    `deck.pre_stage9.html` — `apply_stage9()`만이 이 파일을 쓴다(W1 갭 우회).
    """
    run = Path(run)
    stages: dict[str, dict[str, Any]] = {}

    def mark(stage: str, probe: Path, **extra: Any) -> None:
        if probe.is_file():
            stages[stage] = {
                "at": _mtime(probe),
                "source": "inferred",
                "evidence": probe.name,
                "artifacts": {},
                **extra,
            }

    mark("skeleton", run / "manifest_skeleton.json")
    mark("research_bundle", run / "research_prompt" / "prompt.md")
    # research_apply는 추론하지 않는다 — institution_research.json 자체는 run 루트 지문(LLM
    # 산출물, deck_review 원칙과 동일하게 검증 통과를 존재만으로 증명 못함)이고, 등록되는
    # skins/<id>.json은 run **밖**(repo 루트)이라 run 지문으로 쓸 수 없다. state.json 기록만이 근거.
    mark("storyline_bundle", run / "storyline_prompt" / "storyline_prompt.md")
    mark("render", run / "manifest_render.json")
    mark("design_brief", run / "design_brief.json")
    # W31 R2: design_contract.json 자체는 결정론 산출물이라(LLM 산출물이 아니다) 존재만으로 지문 삼는다
    # (design_brief와 동일 원칙 — 사람 편집 가능성과 무관하게 파일 존재 = 그 단계를 지났다는 증거).
    mark("design_contract", run / "design_contract.json")
    # W21: 와이어프레임 지문. bundle = 프롬프트(그 커맨드만 남긴다). apply = deck.pre_wireframe.json
    #   (apply만이 쓰는 1회 프로즌 백업 — stage9_apply의 deck.pre_stage9.html과 동일 원리).
    #   wireframe.json 자체는 결정기(LLM) 산출물이라 지문으로 쓰지 않는다(있어도 apply 전일 수 있음).
    mark("wireframe_bundle", run / "wireframe_prompt" / "prompt.md")
    mark("wireframe_apply", run / "deck.pre_wireframe.json")
    mark("stage9_bundle", run / "stage9_design" / "stage9_director_prompt.md")
    mark("stage9_apply", run / "deck.pre_stage9.html")
    # W23: design_spec.json 자체는 LLM 산출물이라 추론하지 않는다(deck_review 원칙과 동일).
    mark("refine_bundle", run / "refine_prompt" / "prompt.md")
    mark("refine_collect", run / "design_refs" / "refs_manifest.json")
    mark("refine_handoff", run / "refine_handoff" / "prompt.md")
    mark("deck_review_bundle", run / "deck_review" / "deck_review_prompt.md")
    # `deck_review`(수거)는 **추론하지 않는다.** deck_review.md는 LLM 산출물이라 존재만으로는
    # 계약(필수 섹션·verdict)을 지켰다는 증거가 못 된다 — 검증기를 통과한 기록만이 수거다.
    # (지문 조건 "그 커맨드만이 남기는 파일"을 파일 존재가 만족하지 못하는 유일한 단계.)

    slots = run / "stage9_design" / "slots"
    if slots.is_dir() and any(slots.iterdir()):
        stages["stage9_fill_images"] = {
            "at": _mtime(slots), "source": "inferred", "evidence": "stage9_design/slots/", "artifacts": {},
        }

    approval = run / "approval.json"
    if approval.is_file():
        try:
            rec = json.loads(approval.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            rec = {}
        stages["approve"] = {
            "at": rec.get("timestamp") or _mtime(approval),
            "source": "inferred",
            "evidence": "approval.json",
            "artifacts": {"approval": str(approval)},
            "surface": rec.get("surface"),
        }
    return stages


# ---------------------------------------------------------------------------
# 해석 — 병합 + 경고 + 다음 한 줄
# ---------------------------------------------------------------------------

# 체크포인트를 이미 지났다는 **산출물 증거**. 레거시 run(기록 없음)의 backfill용.
#   근거: 그 산출물이 존재한다는 건 사람이 그 게이트를 (공정 밖에서라도) 이미 통과시켰다는 뜻.
#   기록된 clearance가 있으면 그쪽이 우선한다.
CHECKPOINT_IMPLIED_BY = {
    "start": ("storyline_bundle", "render", "design_brief",
              "wireframe_bundle", "wireframe_apply", "stage9_bundle", "stage9_apply",
              "refine_bundle", "refine_collect", "refine_handoff",
              "imagedeck_bundle", "imagedeck_collect", "imagedeck_compose",
              "deck_review_bundle", "deck_review", "approve"),
    # design_brief는 의사결정 게이트의 산출물이다 — 존재하면 그 게이트를 지났다는 뜻.
    # W21: 와이어프레임([3])이 돌았다면 내용 동결(✋②)을 지난 것이다(decision이 wireframe을 게이트).
    # W23: 고도화가 돌았다면(refine_*) decision 게이트는 지난 것이다.
    # W28: 이미지 라우트 단계(imagedeck_*)도 decision 뒤에서만 도달한다.
    "decision": ("design_brief", "wireframe_bundle", "wireframe_apply", "stage9_bundle", "stage9_apply",
                 "refine_bundle", "refine_collect", "refine_handoff",
                 "imagedeck_bundle", "imagedeck_collect", "imagedeck_compose",
                 "deck_review_bundle", "deck_review", "approve"),
    # human 관문은 하류 산출물로 소급 통과시키지 않는다. ack 없음 = 대기(마이그레이션 없음).
    "design": (),
}


def _effective_checkpoints(
    recorded: dict[str, Any], stages: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name in CHECKPOINTS:
        rec = recorded.get(name, {}) or {}
        if rec.get("cleared_at"):
            out[name] = {"cleared_at": rec["cleared_at"], "source": "recorded"}
            continue
        evidence = [s for s in CHECKPOINT_IMPLIED_BY[name] if s in stages]
        if evidence:
            first = min(evidence, key=lambda s: stages[s].get("at") or "")
            out[name] = {
                "cleared_at": stages[first].get("at"),
                "source": "inferred",
                "evidence": first,
            }
        else:
            out[name] = {"cleared_at": None, "source": "recorded"}
    # 선택 관문: 산출물 추론(implied) 없이 기록된 통과만 반영(건너뛰기=명시 --confirm 기록).
    for name in OPTIONAL_CHECKPOINTS:
        rec = recorded.get(name, {}) or {}
        out[name] = {"cleared_at": rec.get("cleared_at"), "source": "recorded"}
    # W28: 라우트 관문(imagedeck_ack)도 기록된 통과만 반영(추론 없음). image 라우트에서만 _next_step이 참조.
    for name in ROUTE_CHECKPOINTS:
        rec = recorded.get(name, {}) or {}
        out[name] = {"cleared_at": rec.get("cleared_at"), "source": "recorded"}
    return out


def review_needed_total(run: Path) -> int | None:
    """gating_report의 실측 잔존 태그 수. 없으면 None(모르는 걸 아는 척하지 않는다)."""
    p = Path(run) / "gating_report.json"
    if not p.is_file():
        return None
    try:
        gate = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = gate.get("review_needed_total")
    return value if isinstance(value, int) else None


def _review_needed_warnings(run: Path) -> list[str]:
    """W5: 잔존 검토요망을 경고로 표면화한다 — **차단하지 않는다**(게이트 철학)."""
    total = review_needed_total(run)
    if not total:
        return []
    return [
        f"검토요망 {total}건 잔존 — 근거 미확보 콘텐츠가 덱에 남아 있다. "
        f"{run / 'review_resolutions.json'} 의 decision을 채우고 `go`(해소는 사람 결정이 있을 때만)."
    ]


def _knowledge_gap_unresolved_total(run: Path) -> int:
    """run/knowledge_gaps.json의 미해결 건수. 파일 없으면 0(gap 자체가 없다는 뜻 — 모르는 척 안 함)."""
    p = Path(run) / "knowledge_gaps.json"
    if not p.is_file():
        return 0
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    return sum(
        1 for e in data.get("entries") or []
        if isinstance(e, dict) and e.get("status") == "미해결"
    )


def _knowledge_gap_warnings(run: Path) -> list[str]:
    """가공 어휘 갭(DESIGN_ASSETS_LANE §5-④-①) 표면화 — 0건이면 침묵(소음 방지)."""
    total = _knowledge_gap_unresolved_total(run)
    if not total:
        return []
    return [f"미해결 어휘 갭 {total}건 — {Path(run) / 'knowledge_gaps.md'} 참조."]


def _repair_targets(run: Path) -> list[dict]:
    """W12: gating_report.design_checks.browser의 실결함 계열 flag → 수리 대상 목록.

    실측 플래그의 단일 소재지는 `layout_probe.REPAIR_FLAGS`다 — 이 모듈은 그걸 재사용한다
    (상수 이중화로 표류하지 않게). app/render는 오케스트레이터가 항상 올려주지는 않으므로
    여기서 __file__ 기준으로 경로를 확보한 뒤 지연 임포트한다. 실패하면 조용히 빈 목록
    (게이트 승격은 있으면 좋은 것이지 상태 조회를 깨뜨릴 이유가 아니다)."""
    p = Path(run) / "gating_report.json"
    if not p.is_file():
        return []
    try:
        gate = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    browser = ((gate.get("design_checks") or {}).get("browser")) or None
    if not browser:
        return []
    render_dir = Path(__file__).resolve().parents[2] / "app" / "render"
    import sys
    if str(render_dir) not in sys.path:
        sys.path.insert(0, str(render_dir))
    try:
        import layout_probe  # type: ignore
    except Exception:
        return []
    return layout_probe.repair_targets(browser)


def _design_defect_warnings(run: Path) -> list[str]:
    """W12: 실측 게이트 승격 — 실결함 계열 flag를 조용한 warn에서 상태 경고로 끌어올린다.

    `ship`을 차단하지 않되(기존 게이트 철학) 디자인 게이트(go/status) 안내에 결함이
    조용히 지나갈 수 없게 노출한다."""
    targets = _repair_targets(run)
    if not targets:
        return []
    tag = ", ".join(f"slide {t['slide_id']}({'/'.join(t['flags'])})" for t in targets)
    return [
        f"디자인 실측 수리 대상 {len(targets)}건 — {tag}. "
        f"`stage9 --apply` 재실행으로 수리·재실측(ship은 막지 않는다). "
        f"상세: {run / 'gating_report.json'} 의 design_checks.browser."
    ]


def _selection_warning(state: dict[str, Any]) -> list[str]:
    """결정 8(W14): 공고 선택 출처가 agent/unspecified면 1급 경고로 표면화(차단하지 않는다)."""
    selected_by = (state.get("selection") or {}).get("selected_by")
    if selected_by not in ("agent", "unspecified"):
        return []
    if selected_by == "agent":
        return ["공고 선택 출처=agent — 입찰 판단은 사람 전속(결정 8), 확인 필요."]
    return ["공고 선택 출처=unspecified — 누가 골랐는지 기록되지 않았다(결정 8). "
            "사람 선별이면 다음 run부터 `start --selected-by user`로 명시하라."]


def _manual_layer_diff_warning(run: Path) -> list[str]:
    """결정 7(W13): Claude Design 편집본의 내용 변경 명세를 1급으로 표면화한다(차단하지 않는다)."""
    p = Path(run) / "manual_layer_diff.md"
    if not p.is_file():
        return []
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return []
    if "변경 0건" in text:
        return []
    return [f"Claude Design 편집본 내용 변경 명세 있음 — {p} 를 검토하라(삭제·추가는 차단하지 않는다, 결정 7)."]


def _message_map_warnings(run: Path) -> list[str]:
    """W15(결정 9①): message_map 검증 결과를 1급으로 표면화한다.

    차단은 collect(go)가 governing 위반만 별도로 한다 — 여기서는 errors도 경고로 노출해
    status/go에서 사람이 본다(구공정·레거시 run엔 map이 없어 침묵)."""
    import message_map  # sibling, 0토큰(정규식·카운트만)
    doc = message_map.load(run)
    if doc is None:
        return []
    errors, warns = message_map.validate(doc)
    out: list[str] = [f"message_map 구조 위반(차단 대상): {e}" for e in errors]
    out.extend(f"message_map 경고: {w}" for w in warns)
    empties = message_map.empty_slots(doc)
    if empties:
        out.append(
            f"message_map 근거 슬롯 {len(empties)}건이 empty — 근거 미확보(창작금지 대칭, 검토요망). "
            "실근거면 status=filled, 예시면 example로 채워라."
        )
    return out


def _skeleton_stale_warnings(run: Path) -> list[str]:
    """W31(리허설 마찰2): 상류(message_map) 개정 후 하류(skeleton)가 낡은 것을 표면화.

    조용한 실패였다 — 메시지맵을 고쳐도 스켈레톤 단계는 manifest_skeleton.json 존재로
    완료 판정돼 재조립되지 않고(정상: 편집 UI 보호), 사람에게 알리지도 않았다. 감지만
    한다 — 재생성은 `go --redo-skeleton`으로 사람이 정한다(지문 없는 옛 run은 침묵).
    """
    import skeleton  # sibling, 0토큰(해시·비교만)
    reason = skeleton.stale_reason(run)
    return [reason] if reason else []


def _contract_downstream_stale_warnings(run: Path) -> list[str]:
    """W31 마찰18 ⒝: design_contract.json이 imagedeck_manifest.json보다 새로우면(재동결 후
    재번들을 아직 안 한 것) 표면화한다. 둘 다 있어야 비교 대상이 있다(파일럿·html 라우트 run은
    imagedeck_manifest.json 자체가 없어 침묵)."""
    run = Path(run)
    contract_path = run / "design_contract.json"
    manifest_path = run / "imagedeck_manifest.json"
    if not (contract_path.is_file() and manifest_path.is_file()):
        return []
    try:
        if contract_path.stat().st_mtime > manifest_path.stat().st_mtime + 2:
            return ["[하류 stale] 계약이 이미지 번들보다 새로움 - 재번들 권장(imagedeck --bundle)."]
    except OSError:
        return []
    return []


def _density_band_warning(run: Path) -> list[str]:
    """W31 R10(β2): master_design.density(design_contract.json에 기록)가 standard가 아니고
    storyline이 이미 있으면 분량 밴드 재조정을 표면화한다(경고 1급 — 차단 없음, R9·emphasis와
    동일 원칙: 디자인에 닿는 결정은 내용 루프로 되돌려 표면화만 한다)."""
    run = Path(run)
    contract_path = run / "design_contract.json"
    if not contract_path.is_file() or not (run / "storyline.json").is_file():
        return []
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    density = (contract or {}).get("density")
    if not density or density == "standard":
        return []
    return [
        f"[밀도 비표준] 마스터 시안 밀도={density} — 분량 밴드 재조정 → A5 부분 재생성 권장"
        "(스토리라인이 이 밀도 확정보다 먼저 있었다 — go --redo-skeleton 계열로 재작업할지 검토하라)."
    ]


def _length_rhythm_warnings(run: Path) -> list[str]:
    """W16(결정 9⑤): 분량 리듬 실측(gating_report.length_rhythm)을 경고 1급으로 표면화한다.

    동적 범위 <3배(균질 = AI티 신호)와 선언 밴드 위반을 노출한다 — **차단하지 않는다**
    (선언+실측 표면화 문법). gating_report·length_rhythm이 없으면 침묵(구공정·미측정)."""
    p = Path(run) / "gating_report.json"
    if not p.is_file():
        return []
    try:
        gate = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    lr = (gate or {}).get("length_rhythm")
    if not isinstance(lr, dict):
        return []
    out: list[str] = []
    dyn = lr.get("dynamic_range")
    target = lr.get("target_min_dynamic_range", 3.0)
    # 슬라이드가 너무 적으면(≤2) 동적 범위 경고는 소음 — 밴드 위반만 본다.
    if isinstance(dyn, (int, float)) and lr.get("slides", 0) >= 3 and dyn < target:
        out.append(
            f"분량 리듬 동적 범위 {dyn}배 < 목표 {target}배 — 장표 분량이 균질하다(AI티의 "
            f"내용 측 원인, 결정 9⑤). 스토리 장표는 얇게·근거 장표는 두껍게 하라(min={lr.get('min')}"
            f"/중앙={lr.get('median')}/max={lr.get('max')} 어절)."
        )
    viol = lr.get("band_violations") or []
    if viol:
        ids = ", ".join(str(v.get("slide_id")) for v in viol[:6])
        more = " 등" if len(viol) > 6 else ""
        out.append(
            f"분량 밴드 위반 {len(viol)}건(slide {ids}{more}) — 선언 밴드 밖(경고 1급·차단 없음). "
            "⚠️ 이미지 단계에서 오버플로(카드 밖 텍스트 범람)로 실현된 실측 사례가 있다(W31 마찰22) — "
            "08_프롬프트확인에서 위반 목록을 확인하라(3장 이상이면 imagedeck_prompt_ack 관문이 "
            "자동 재정지된다). 스토리/근거 role에 맞게 분량을 조정하라."
        )
    return out


def _message_map_view(run: Path) -> dict[str, Any] | None:
    """게이트 표시용 요약(결정 9③: 의사결정 게이트 승인 대상). map이 없으면 None."""
    import message_map  # sibling
    doc = message_map.load(run)
    if doc is None:
        return None
    return {
        "governing_message": message_map.governing_text(doc),
        "axes": [{"id": a.get("id"), "message": a.get("message")} for a in message_map.axes(doc)],
        "gating": message_map.gating_block(doc),
    }


def resolve(run: Path, *, render_input: Path | None = None) -> dict[str, Any]:
    """기록된 state + 산출물 추론을 병합하고, 경고와 '다음 커맨드 한 줄'을 계산한다.

    `render_input`은 호출부(proposal_pipeline._discover_run_json)가 넘긴다 —
    스토리라인/stage6 탐색 규칙이 두 곳에 복제되어 표류하는 걸 막기 위함.
    """
    run = Path(run)
    state = load(run)
    inferred = infer(run)
    recorded = state.get("stages", {})

    merged: dict[str, dict[str, Any]] = {}
    for stage in STAGE_ORDER:
        if stage in recorded:
            merged[stage] = recorded[stage]
        elif stage in inferred:
            merged[stage] = inferred[stage]

    # B1: deck_review.md가 수거(기록) 이후 갱신되면(예: 사람이 revise→approve로 고침) 낡은
    # verdict가 영원히 남는다 — mtime이 기록시각보다 새로우면 재수거해 verdict를 갱신한다.
    # 계약(필수 섹션·verdict) 검증은 그대로 통과해야 하고, 위반이면 기존 기록을 유지한다.
    dr_recorded = merged.get("deck_review")
    review_md = run / "deck_review.md"
    if dr_recorded and review_md.is_file():
        t_review_file = _parse(_mtime(review_md))
        t_review_recorded = _parse(dr_recorded.get("at"))
        if t_review_file and t_review_recorded and t_review_file > t_review_recorded + dt.timedelta(seconds=2):
            import deck_review as _deck_review  # sibling module, 0토큰(정규식 검증만)
            fresh = _deck_review.collect(run)
            if fresh.get("found") and not fresh["errors"]:
                merged["deck_review"] = {
                    **dr_recorded,
                    "verdict": fresh["verdict"],
                    "chars": fresh.get("chars"),
                    "recollected_at": now(),
                    "recollected_reason": "deck_review.md mtime > 기록 시각",
                }

    has_state_file = state_path(run).is_file()
    warnings: list[str] = []

    if not has_state_file:
        warnings.append(
            "state 파일 없음 — 단계를 산출물에서 추론했다(레거시 run). "
            "타임스탬프·모드는 정확하지 않을 수 있다."
        )
    if not state.get("mode"):
        warnings.append("실행 모드(secure/direct) 미기록 — `start --mode`로 확정된 run이 아니다.")

    t_render = _parse(merged.get("render", {}).get("at"))
    t_apply = _parse(merged.get("stage9_apply", {}).get("at"))
    t_approve = _parse(merged.get("approve", {}).get("at"))
    tol = dt.timedelta(seconds=2)

    # W1 갭: stage9 --apply는 gating_report를 갱신하지 않으므로, 이후 render가 돌면
    # deck.html은 조용히 overrides 없는 판으로 되돌아간다. 이걸 경고로 표면화한다.
    if t_apply and t_render and t_render > t_apply + tol:
        warnings.append(
            "stage9 적용 후 render가 다시 실행됨 — deck.html은 현재 override 미반영본이다"
            "(gating_report.applied_axes.overrides=false가 근거). `stage9 --apply` 재실행 필요."
        )
    # 평가는 그 시점의 deck.html을 봤다. 이후 덱이 바뀌면 평가는 낡은 자료다(차단은 안 한다).
    review_md = run / "deck_review.md"
    if review_md.is_file():
        t_review = _parse(_mtime(review_md))
        newer = [n for n, t in (("render", t_render), ("stage9_apply", t_apply))
                 if t and t_review and t > t_review + tol]
        if newer:
            warnings.append(
                f"deck_review.md 이후 {', '.join(newer)}가 다시 실행됨 — 평가가 낡은 덱을 본 것이다. "
                "재평가를 권한다(deck_review.md 삭제 후 `go`)."
            )
    else:
        # D3(마찰 D): 평가 수거 전이라도 **번들**이 낡을 수 있다 — stage9 --apply/render가
        # 번들 이후 돌면 프롬프트가 낡은 덱(옛 실측)을 담는다. 재번들을 안내한다(재수거 계열).
        review_prompt = run / "deck_review" / "deck_review_prompt.md"
        if review_prompt.is_file():
            t_bundle = _parse(_mtime(review_prompt))
            newer = [n for n, t in (("render", t_render), ("stage9_apply", t_apply))
                     if t and t_bundle and t > t_bundle + tol]
            if newer:
                warnings.append(
                    f"deck_review 번들 생성 이후 {', '.join(newer)}가 다시 실행됨 — 번들이 낡은 덱"
                    "(옛 실측)을 담았다. 재번들 필요(`go`가 재생성 후 재평가)."
                )

    if t_approve:
        newer = [n for n, t in (("render", t_render), ("stage9_apply", t_apply)) if t and t > t_approve + tol]
        if newer:
            warnings.append(f"승인 후 {', '.join(newer)}가 다시 실행됨 — approval.json이 낡았다. `ship` 재실행 필요.")
    elif "render" in merged:
        warnings.append("승인(approve) 없음 — 덱이 확정되지 않았다.")

    warnings.extend(_review_needed_warnings(run))
    warnings.extend(_design_defect_warnings(run))  # W12: 실측 게이트 승격(조용한 warn → 상태 경고)
    warnings.extend(_manual_layer_diff_warning(run))  # W13: 결정 7 — 자유편집 diff 표면화
    warnings.extend(_selection_warning(state))  # W14: 결정 8 — 공고 선택 출처 표면화(레거시 run은 침묵: selection=None)
    warnings.extend(_message_map_warnings(run))  # W15: 결정 9① — 메시지맵 검증 표면화(구공정 run은 침묵: map 없음)
    warnings.extend(_skeleton_stale_warnings(run))  # W31 리허설 마찰2: 상류 개정 후 뼈대 stale 표면화
    warnings.extend(_contract_downstream_stale_warnings(run))  # W31 마찰18 ⒝: 재동결 후 재번들 안내
    warnings.extend(_length_rhythm_warnings(run))  # W16: 결정 9⑤ — 분량 리듬 실측 표면화(미측정 run은 침묵)
    warnings.extend(_knowledge_gap_warnings(run))  # §5-④-①: 가공 어휘 갭 표면화(0건이면 침묵)
    warnings.extend(_density_band_warning(run))  # W31 R10(β2): 마스터 시안 비표준 밀도 표면화

    checkpoints = _effective_checkpoints(state.get("checkpoints", {}), merged)
    route, wf_mode_img = render_route(run)  # W28: 라우트(기본 html_editable)
    step = _next_step(state, merged, checkpoints, run=run, render_input=render_input)

    # W24: 진행 바 판정. W21로 wireframe_* 가 STAGE_ORDER에 편입되어 merged에 이미 담긴다.
    position = progress_position(merged, checkpoints)

    # W31 R-마찰2: 관문 프로파일(읽기 전용 — resolve는 파일을 쓰지 않는다, gates.decide는
    # go_cmd가 별도로 다시 부른다). 실패해도 상태 조회를 막지 않는다(부가 정보).
    gates_view: dict[str, Any] = {"profile": "standard", "overrides": {}}
    try:
        import gates  # sibling, 지연 임포트(순환 방지)
        gates_view = gates.load_config(run)
    except Exception:
        pass

    knowledge_lines: list[str] = []
    try:
        import knowledge_ledger  # sibling, 지연 임포트(순환 방지) — ε패킷 안전장치③(상시 표면화)
        knowledge_lines = knowledge_ledger.surface_lines(run)
    except Exception:
        pass

    return {
        "run_dir": str(run),
        "run_id": run.name,
        "mode": state.get("mode"),
        "input": state.get("input"),
        "has_state_file": has_state_file,
        "stages": merged,
        "checkpoints": checkpoints,
        "message_map": _message_map_view(run),  # W15: 게이트 표시(결정 9③) — 없으면 None
        "warnings": warnings,
        "next": step,
        "progress": {"position": position, "label": PROGRESS_LABEL[position]},  # W24 진행 바
        "render_route": {"route": route, "wireframe_mode": wf_mode_img},  # W28 렌더 라우트
        "gates": gates_view,  # W31 R-마찰2: 관문 프로파일(profile/overrides) — 대시보드 status 경유
        "knowledge": knowledge_lines,  # ε패킷 안전장치③: 단계별 "지식: 카드 N · 웹 M건" 표면화
    }


def _py() -> str:
    return "python proposal_system/scripts/proposal_pipeline.py"


def _message_map_next(
    run: Path, stages: dict[str, dict[str, Any]], mode: str | None, rid: str
) -> dict[str, Any] | None:
    """W15(결정 9①): RFP분석 후·스토리라인 전. 핸드오프(LLM)→검증(수거).

    스켈레톤 역제안을 본 뒤, 스토리라인 채움보다 **앞**에 온다 — 장표는 메시지가 요구하는
    것만 도출하므로(결정 9①), 메시지맵이 먼저 확정돼야 한다. 완료면 None(다음 단계로).
    """
    mm = Path(run) / "message_map.json"
    if not mm.is_file():
        if "message_map_bundle" not in stages:
            return {
                "kind": "command",
                "why": "메시지 우선 설계(결정 9①) — 핵심 주장·전략 축 핸드오프를 아직 만들지 않았다.",
                "command": f"{_py()} go --run {rid}",
                "stage": "message_map_bundle",
            }
        handoff = "secure" if mode == "secure" else "direct"
        who = "외부 LLM에 붙여넣고 결과를" if handoff == "secure" else "세션 LLM/Codex가"
        return {
            "kind": "llm",
            "why": "message_map.json이 없다 — 핵심 주장 1 + 전략 축 2~4 + 근거 슬롯(내용 결정 게이트 산출물).",
            "handoff": handoff,
            "command": f"{Path(run) / 'message_map' / 'message_map_prompt.md'} 를 {who} {mm} 로 저장",
        }
    if "message_map" not in stages:
        return {
            "kind": "command",
            "why": "message_map.json이 있으나 스키마 검증·수거가 안 됐다(governing 1개·축 2~4 검사).",
            "command": f"{_py()} go --run {rid}",
            "stage": "message_map",
        }
    return None


def _next_step(
    state: dict[str, Any],
    stages: dict[str, dict[str, Any]],
    checkpoints: dict[str, dict[str, Any]],
    *,
    run: Path,
    render_input: Path | None,
) -> dict[str, Any]:
    """다음에 할 일 한 줄. `blocked_by`가 있으면 사람/LLM 개입이 필요하다는 뜻.

    kind:
      - "command"    : go가 스스로 실행할 수 있는 결정론 단계
      - "checkpoint" : 사람이 결정할 것 (go는 여기서 멈춘다)
      - "llm"        : LLM 산출물이 필요 (go는 여기서 멈추고 핸드오프를 출력한다)
      - "done"       : 종료
    """
    rid = run.name
    mode = state.get("mode")
    # W28(D8·D13): 렌더 라우트. 기본 html_editable → 아래 분기 전부 no-op(기존 흐름 보존).
    route, wf_mode_img = render_route(run)
    is_image_route = route == "image_infographic"

    stale_human: dict[str, str] = {}

    def cleared(name: str) -> bool:
        cp = checkpoints.get(name, {}) or {}
        cleared_at = cp.get("cleared_at")
        if not cleared_at:
            return False
        if is_human(name) and cp.get("source") == "recorded":
            changed = is_stale(run, name, cleared_at)
            if changed:
                stale_human[name] = changed
                return False
        return True

    def checkpoint_why(name: str, why: str) -> str:
        changed = stale_human.get(name)
        if changed:
            why = f"[재무장] 확정 이후 산출물 변경({changed}) - 재검토 필요. {why}"
        note = _gate_note(run, name)
        if note:
            why = f"{why} {note}"
        return why

    if not cleared("start"):
        return {
            "kind": "checkpoint",
            "checkpoint": "start",
            "why": "입력·모드가 확정되지 않았다.",
            "command": f"{_py()} start --bid <공고번호> --mode secure|direct",
        }

    # --- 탐색 루프: 스토리라인 입력이 있어야 render가 돈다 ---
    if "render" not in stages:
        if render_input is None:
            kind = (state.get("input") or {}).get("kind")
            # [1] 선택 관문: 발주처 조사(§9.7) — 문서 밖 근거(미션·건학이념→도입 직인용)와 브랜드 색을
            #     넣을 기회. bid(공고)에서만 의미(발주기관이 있어야 조사). 이미 했으면(institution_research.json)
            #     자동 충족. 안 하면 `go --confirm`으로 건너뛴다(B — 무심코 지나가지 않게, 결정 2026-07-14).
            if (kind == "bid" and not cleared("research")
                    and not (run / "institution_research.json").is_file()):
                return {
                    "kind": "checkpoint",
                    "checkpoint": "research",
                    "optional": True,
                    "why": ("선택: 발주처 공개 조사로 '문서 밖 근거'(발주기관 미션·건학이념·특성화 → "
                            "제안 도입부에 직접 인용)와 브랜드 색(대표색 → 스킨)을 확보할 수 있다. "
                            "안 해도 진행된다 — 건너뛰려면 --confirm."),
                    "command": f"{_py()} go --run {rid} --confirm   "
                               f"(또는 조사하려면: {_py()} research --run {rid} --bundle)",
                    "review": [str(run / "analysis")],
                }
            storyline_prompt_path = run / "storyline_prompt" / "storyline_prompt.md"
            # W16(결정 9①): 메시지 우선 — message_map이 스켈레톤보다 **앞**이다. RFP 분석 후
            # 핵심 주장·전략 축을 먼저 확정하고, 그것에 **종속해** 장표(스켈레톤)를 축별로 조립한다
            # ("스켈레톤 역제안은 message_map 종속으로 격하", 결정 9①). 완료면 None으로 다음 단계.
            mm_step = _message_map_next(run, stages, mode, rid)
            if mm_step is not None:
                return mm_step
            # W10→W16: 메시지맵 확정 후, 표준 시나리오 스켈레톤을 message_map에 종속해 **축별로**
            # 조립해 더미(예시)로 즉시 렌더·역제안한다(0토큰). map이 없으면 시나리오 통짜(레거시).
            if "skeleton" not in stages:
                return {
                    "kind": "command",
                    "why": "메시지맵 확정 후 — message_map에 종속한 축별 장표 스켈레톤을 더미로 역제안한다(0토큰).",
                    "command": f"{_py()} go --run {rid}",
                    "stage": "skeleton",
                }
            # 스켈레톤을 봤다(역제안) → 이제 LLM은 백지 창작이 아니라 **확정된 구조를 채운다**.
            if not cleared("skeleton_review"):
                return {
                    "kind": "checkpoint",
                    "checkpoint": "skeleton_review",
                    "optional": True,
                    "human": True,
                    "why": checkpoint_why(
                        "skeleton_review",
                        "스켈레톤 역제안을 검토하라(장 구성·축 배분) - 스토리라인은 이 구조를 채운다. "
                        "검토/건너뛰기는 대시보드에서.",
                    ),
                    "command": "대시보드에서 스켈레톤 검토 완료 또는 건너뛰기 (실행 명령 아님)",
                    "review": [str(run / "deck.html"), str(run / "skeleton.json")],
                }
            skel_note = "확정된 스켈레톤 구조를 채운다(역제안 확정 후 — 백지 창작 아님). "
            if kind == "brief" and "storyline_bundle" not in stages:
                # brief.md + skeleton.json → 채움 프롬프트 번들(N2). 결정론 단계라 go가 직접 실행한다.
                return {
                    "kind": "command",
                    "why": skel_note + "브리프+스켈레톤에서 채움 프롬프트를 아직 번들하지 않았다.",
                    "command": f"{_py()} go --run {rid}",
                    "stage": "storyline_bundle",
                }
            if mode == "secure":
                # 복붙 왕복. (build-bundles 폐기 — W31 처분: 분석카드+skeleton을 직접 붙여넣는다.)
                if kind == "brief":
                    hint = f"{storyline_prompt_path} 를 외부 LLM에 붙여넣고 결과를 {run / 'storyline.json'} 로 저장"
                else:
                    hint = (f"분석카드 + {run / 'skeleton.json'} 를 외부 LLM에 붙여넣고 "
                            f"결과를 {run / 'storyline.json'} 로 저장")
                return {
                    "kind": "llm",
                    "why": skel_note + "스토리라인 입력이 없다 (secure 모드: 복붙 왕복).",
                    "handoff": "secure",
                    "command": hint,
                }
            source = str(storyline_prompt_path) if kind == "brief" else f"분석카드 + {run / 'skeleton.json'}"
            # W31 리허설 마찰6: bid 경로는 번들 파일이 없으므로(직접 핸드오프), 여기 힌트에
            # 자사 프로필 소재지를 붙여 채움 시 참고하게 한다(있을 때만 — 없으면 문구 불변).
            try:
                import company  # sibling, 지연 임포트(순환 방지 — gates/message_map과 동일 관례)
                sel = company.load_selection(run)
                if sel and sel.get("company_id"):
                    source += f" + {company.profile_path(sel['company_id'])}(선택된 회사 프로필)"
            except Exception:
                pass
            return {
                "kind": "llm",
                "why": skel_note + "스토리라인 입력이 없다 (direct 모드: 세션 LLM/Codex가 생성).",
                "handoff": "direct",
                "command": f"세션 LLM 또는 Codex가 {source} → {run / 'storyline.json'} 생성 → `{_py()} go --run {rid}`",
            }
        return {
            "kind": "command",
            "why": "스토리라인 입력이 있고 아직 렌더되지 않았다.",
            "command": f"{_py()} render --run {rid}",
            "stage": "render",
        }

    # --- 체크포인트 2: 의사결정 게이트 (탐색 → 디벨롭 경계) ---
    if not cleared("decision"):
        return {
            "kind": "checkpoint",
            "checkpoint": "decision",
            "human": True,
            "why": checkpoint_why(
                "decision",
                "스토리라인·방향을 확정해야 디벨롭 루프로 넘어간다. "
                "대시보드에서 확정(ack)하면 다음 `go`가 design_brief.json을 결정론 기본값으로 만든다"
                "(그 파일이 편집 UI). 검토요망(창작경계 flag)도 이 화면에서 처리한다 - "
                "review_resolutions.json의 decision을 채우면 다음 `go`가 반영한다(비워두면 태그 유지). "
                "이후 남은 단계: [3]뼈대 잡기 > [4]디자인 입히기 > [4+]디자인 고도화 > [5]마무리·검토 "
                "(동결=방향·메시지 확정이지, 시각 완성이 아니다 - 디자인은 뒤에서 계속 좋아진다).",
            ),
            "command": "대시보드에서 스토리라인·방향 확정 (실행 명령 아님)",
            "review": [str(run / "deck.html"), str(run / "gating_report.json"),
                       str(run / "review_resolutions.json"), str(run / "storyline.json"),
                       str(run / "message_map.json")],
        }

    # --- W5: 검토요망 해소. 해소지는 사람이 직접 고치는 살아있는 파일(design_brief와 같은 패턴) →
    #     파일이 프롬프트보다 최신이면 다시 적용해야 한다. 적용 = 재렌더이므로 stage9 앞에 둔다.
    #     이미 디자인 게이트를 지난 run(레거시·승인본)은 소급 요구하지 않는다(deck_review와 동일 원칙).
    #     W7-C2: **브리핑보다 앞**이다 — 브리핑은 해소된 덱을 근거로 삼아야 한다(evidence_candidates).
    resolutions = run / "review_resolutions.json"
    t_resolve = _parse(stages.get("review_resolve", {}).get("at"))
    if cleared("design"):
        t_resolve = t_resolve or _parse(stages.get("render", {}).get("at"))
    if not t_resolve:
        return {
            "kind": "command",
            "why": "검토요망 해소가 아직 적용되지 않았다 — 해소지 골격을 만들고 결정된 항목만 반영한다.",
            "command": f"{_py()} go --run {rid}",
            "stage": "review_resolve",
        }
    if resolutions.is_file() and _parse(_mtime(resolutions)) > t_resolve + dt.timedelta(seconds=2):
        return {
            "kind": "command",
            "why": "review_resolutions.json이 마지막 해소 적용보다 최신이다 — 사람의 결정을 덱에 반영한다.",
            "command": f"{_py()} go --run {rid}",
            "stage": "review_resolve",
        }

    # --- [3] 뼈대 잡기(W21 와이어프레임) — 내용 동결 후·디자인 브리핑/테마 전. go 자동 편입(결정 10·12). ---
    #     이 지점은 decision 청산 뒤에만 도달한다 → decision이 wireframe을 게이트(동결 전 탐색
    #     루프에선 wireframe이 next로 안 뜬다). bundle(결정론)→핸드오프(결정기 LLM)→apply(검증·병합·무채 재렌더).
    #     무채 형태를 먼저 잡고 그 위에 디자인(브리핑·stage9)을 얹는다(MANUAL §2 "✋②→와이어프레임").
    #     이미 디자인 게이트를 지난 run(레거시·승인본)은 소급 요구하지 않는다(deck_review·refine과 동일).
    # W28 D13: image 라우트 + wireframe_mode=off면 뼈대(bundle/apply/review)를 통째 스킵한다
    #   (이미지 모델이 template_id로 배치 추론 - 헛돈 방지). on/auto면 기존대로 뼈대를 잡는다.
    skip_wireframe = is_image_route and wf_mode_img == "off"
    if not skip_wireframe and not cleared("design"):
        wf_json = run / "wireframe.json"
        if "wireframe_apply" not in stages:
            if not wf_json.is_file():
                if "wireframe_bundle" not in stages:
                    return {
                        "kind": "command",
                        "why": "[3] 뼈대 잡기 — 장별 frame×piece 결정 프롬프트가 아직 없다(내용 동결 후 형태).",
                        "command": f"{_py()} go --run {rid}",
                        "stage": "wireframe_bundle",
                    }
                handoff = "secure" if mode == "secure" else "direct"
                who = "외부 LLM에 붙여넣고 결과를" if handoff == "secure" else "세션 LLM/Codex가"
                return {
                    "kind": "llm",
                    "why": "wireframe.json이 없다 — 결정기(LLM)가 장별 메시지 유형(수치/비교/구조/성과/서사)을 "
                           "판별해 frame×piece를 결정해야 한다(내용 불변·재배열만).",
                    "handoff": handoff,
                    "command": f"{run / 'wireframe_prompt' / 'prompt.md'} 를 {who} {wf_json} 로 저장",
                }
            return {
                "kind": "command",
                "why": "wireframe.json이 있으나 deck.json 병합·무채 재렌더가 안 됐다 — [3] 뼈대 적용 필요.",
                "command": f"{_py()} go --run {rid}",
                "stage": "wireframe_apply",
            }

    # W27 P4-A: 적용된 무채 뼈대를 테마 전에 사람이 확인한다. design_brief 단계가 있는
    # 레거시 run에는 신규 관문을 최초 소급 노출하지 않는다. 단, 한 번 recorded-clear 된 run은
    # wireframe.json 변경 시 기존 stale-ack 기계로 재무장되어 하류 단계가 있어도 다시 표면화한다.
    wf_review_recorded = bool(
        ((state.get("checkpoints") or {}).get("wireframe_review") or {}).get("cleared_at")
    )
    if (
        not skip_wireframe
        and "wireframe_apply" in stages
        and ("design_brief" not in stages or wf_review_recorded)
        and not cleared("wireframe_review")
    ):
        return {
            "kind": "checkpoint",
            "checkpoint": "wireframe_review",
            "optional": True,
            "human": True,
            "why": checkpoint_why(
                "wireframe_review",
                "재조판된 무채 뼈대를 검토하라(frame×piece·배치) - 테마는 이 뼈대 위에 입혀진다. "
                "검토/건너뛰기는 대시보드에서.",
            ),
            "command": "대시보드에서 뼈대 검토 완료 또는 건너뛰기 (실행 명령 아님)",
            "review": [str(run / "deck.html"), str(run / "wireframe.json"),
                       str(run / "gating_report.json")],
        }

    # --- 디벨롭 루프: 디자인 브리핑(방향) → 디자인 디렉터(정련) ---
    if "design_brief" not in stages and not (run / "design_brief.json").is_file():
        return {
            "kind": "command",
            "why": "디자인 브리핑이 없다 — 의사결정 게이트의 산출물(결정론 기본값).",
            "command": f"{_py()} go --run {rid}",
            "stage": "design_brief",
        }

    # --- W31 R2·R3·R5: run별 디자인 계약 동결(design_contract.json) + 테마 확정 게이트(theme_confirm). ---
    #     위치 = design_brief 직후·(이미지 번들 | stage9 번들) 전(B1 "테마 확정"). 이미 이 지점을
    #     지난 run(design_contract 도입 전에 하류가 이미 진행된 레거시·파일럿 run)은 소급 요구하지
    #     않는다 — wireframe_review/refine 블록과 동일한 "게이트를 지난 run은 소급 안 함" 문법.
    import design_contract  # sibling module, 지연 임포트(message_map과 동일 관례)
    _past_theme_gate = any(s in stages for s in DOWNSTREAM_OF_THEME_STAGES)
    if not _past_theme_gate:
        if "design_contract" not in stages and not design_contract.exists(run):
            return {
                "kind": "command",
                "why": "디자인 계약(design_contract.json)이 없다 — design_brief를 병합해 run별 정본을 동결한다(R2).",
                "command": f"{_py()} go --run {rid}",
                "stage": "design_contract",
            }
        if not cleared("theme_confirm"):
            return {
                "kind": "checkpoint",
                "checkpoint": "theme_confirm",
                "optional": True,
                "human": True,
                "why": checkpoint_why(
                    "theme_confirm",
                    "테마(디자인 계약)를 확정하라 — 차용/중립 출처·색·폰트·chrome/image 분리 내역은 "
                    "07_테마확정/design_contract_읽기.md 에서 확인. 기본값(중립 또는 브리프 승계) 그대로 "
                    "진행해도 된다. 검토 완료 또는 건너뛰기는 대시보드의 사람 결정만 허용한다.",
                ),
                "command": "대시보드에서 테마 확정 또는 건너뛰기 (실행 명령 아님)",
                "review": [str(run / design_contract.CONTRACT_NAME)],
            }

    # --- W28 D8~D13: image_infographic 라우트 — stage9/refine/deck_review 대신 이미지 장표 관통. ---
    #     (a)번들 → (b)Codex 생산[정지] → (c)수거검증 → (e)imagedeck_ack[사람] → (f)HTML 크롬 조합
    #     → 공유 tail(디자인 게이트·approve)로 합류. html_editable(기본)엔 이 블록이 no-op.
    if is_image_route and not cleared("design"):
        imgd_manifest = run / "imagedeck_manifest.json"
        if "imagedeck_bundle" not in stages or not imgd_manifest.is_file():
            return {
                "kind": "command",
                "why": "[이미지] 장별 프롬프트 번들이 없다 — storyline+스킨을 장별 이미지 프롬프트로 조립(D12 역산).",
                "command": f"{_py()} imagedeck --run {rid} --bundle",
                "stage": "imagedeck_bundle",
            }
        # (a2) 사람 전속 관문(W30): 생산 전 프롬프트·레퍼런스 확인 — 기대와 다른 이미지에
        # 토큰을 태우기 전에 방향(프롬프트 문구·레퍼런스·스킨)을 사람이 확정한다. 재무장=재번들.
        if not cleared("imagedeck_prompt_ack"):
            return {
                "kind": "checkpoint",
                "checkpoint": "imagedeck_prompt_ack",
                "human": True,
                "why": checkpoint_why(
                    "imagedeck_prompt_ack",
                    "생산에 들어가기 전에 장별 프롬프트(imagedeck_prompts/)와 레퍼런스 이미지를 "
                    "확인하라. 프롬프트·스킨·레퍼런스를 고쳤으면 재번들(--bundle) 후 다시 확인. "
                    "레퍼런스는 run/imagedeck_refs/global(전체) 또는 slides/<NN>(장별)에 넣거나 "
                    "--ref로 지정 - 비어 있으면 design-assets/references/seed 시드가 기본 적용된다."),
                "command": "대시보드에서 프롬프트·레퍼런스 확인 후 승인 (실행 명령 아님)",
                "review": [str(run / "imagedeck_prompts"),
                           str(run / "imagedeck_manifest.json")],
            }
        if not imagedeck_images_present(run):
            handoff = "secure" if mode == "secure" else "direct"
            if handoff == "secure":
                command = (f"외부 이미지 모델로 {run / 'imagedeck_prompts'}/ 의 각 프롬프트로 이미지를 그려 "
                           f"{run / 'imagedeck' / 'slides'}/ 에 저장(파일명=manifest out_name) → `{_py()} go --run {rid}`")
            else:  # W29 승격: 정식 생산 커맨드(Codex 단발 위임 자동화 - 장별 px 즉시 실측·재실행 안전)
                command = f"{_py()} imagedeck --run {rid} --produce"
            # W32 마찰27: 부분 생산 상태를 표시한다(판정은 불변 — 표시만). 중단 후 돌아온 사람이
            # 처음부터 다시 도는 줄 알던 자리 — `--produce`는 미생산 장만 처리한다(재실행 안전).
            _done, _total_img = imagedeck_progress(run)
            if _done:
                why = (f"[이미지] 이미지 {_done}/{_total_img}장 생산됨 — 나머지를 이어서 그려야 한다"
                       f"(재실행하면 미생산 장만 처리한다).")
            else:
                why = "[이미지] 생산 이미지가 아직 없다 — 프롬프트 번들로 장별 PNG를 그려야 한다(D9 Codex 전속)."
            return {
                "kind": "llm",
                "why": why,
                "handoff": handoff,
                "command": command,
            }
        t_ic = _parse(stages.get("imagedeck_collect", {}).get("at"))
        t_ib = _parse(stages.get("imagedeck_bundle", {}).get("at"))
        if "imagedeck_collect" not in stages or (t_ib and t_ic and t_ib > t_ic + dt.timedelta(seconds=2)):
            return {
                "kind": "command",
                "why": "[이미지] 생산 이미지의 px·커버리지·파일명 검증이 안 됐다 — 수거 검증 필요.",
                "command": f"{_py()} imagedeck --run {rid} --collect",
                "stage": "imagedeck_collect",
            }
        if not (stages.get("imagedeck_collect") or {}).get("passed"):
            # 검증 불합격(px 불일치·커버리지 미달·누락) — 루프 대신 정지. collect_report의 재생성
            # 지시로 이미지를 고친 뒤 재수거한다(go 자동 반복 안 함 - 이미지 수정은 사람/Codex 몫).
            return {
                "kind": "llm",
                "why": "[이미지] 수거 검증 불합격 — px/커버리지/파일명 문제. collect_report의 재생성 지시로 이미지를 고쳐야 한다.",
                "handoff": "direct" if mode != "secure" else "secure",
                "command": (f"{run / 'imagedeck' / 'collect_report.md'} 의 불합격 항목을 고쳐 "
                            f"{run / 'imagedeck' / 'slides'}/ 재저장 → `{_py()} imagedeck --run {rid} --collect`"),
            }
        # (e) 사람 전속 관문: 이미지 장표 정독 후 채택(재무장=manifest/collect 갱신 시). 검수(d)는 대시보드 선택.
        if not cleared("imagedeck_ack"):
            return {
                "kind": "checkpoint",
                "checkpoint": "imagedeck_ack",
                "human": True,
                "why": checkpoint_why(
                    "imagedeck_ack",
                    "생산된 이미지 장표를 정독하고(문구·수치·[예시]·누락 binds·금지 스타일) 채택하라. "
                    "Claude 검수는 대시보드에서 선택(요청/스킵). 국소 교정은 이미지 재생성 후 재수거."),
                "command": "대시보드에서 이미지 장표 승인 또는 검수 요청 (실행 명령 아님)",
                "review": [str(run / "imagedeck" / "collect_report.md"), str(run / "imagedeck" / "slides")],
            }
        if "imagedeck_compose" not in stages:
            return {
                "kind": "command",
                "why": "[이미지] 승인된 이미지를 HTML 크롬(제목·로고)과 조합 — deck.images.html.",
                "command": f"{_py()} imagedeck --run {rid} --compose",
                "stage": "imagedeck_compose",
            }
        # 이미지 관통 완료 → 공유 tail(디자인 게이트)로 낙하.

    overrides = run / "design_overrides.json"
    if not is_image_route and "stage9_bundle" not in stages and not overrides.is_file():
        return {
            "kind": "command",
            "why": "[4] 디자인 입히기(코드명 stage9) 정련 프롬프트가 아직 없다.",
            "command": f"{_py()} stage9 --run {rid}",
            "stage": "stage9_bundle",
        }
    # 사람이 브리핑을 고쳤는데 프롬프트가 그대로면 편집이 디렉터에게 전달되지 않는다.
    brief_file = run / "design_brief.json"
    t_bundle = _parse(stages.get("stage9_bundle", {}).get("at"))
    if brief_file.is_file() and t_bundle and not overrides.is_file():
        if _parse(_mtime(brief_file)) > t_bundle + dt.timedelta(seconds=2):
            return {
                "kind": "command",
                "why": "design_brief.json이 정련 프롬프트([4] 디자인 입히기·코드명 stage9)보다 최신이다 - 편집 반영을 위해 재번들.",
                "command": f"{_py()} stage9 --run {rid}",
                "stage": "stage9_bundle",
            }
    if not is_image_route and not overrides.is_file():
        handoff = "secure" if mode == "secure" else "direct"
        who = "외부 LLM에 붙여넣고 결과를" if handoff == "secure" else "세션 LLM/Codex가"
        return {
            "kind": "llm",
            "why": "design_overrides.json이 없다 - [4] 디자인 입히기(코드명 stage9) 정련 판단이 필요하다.",
            "handoff": handoff,
            "command": f"{run / 'stage9_design' / 'stage9_director_prompt.md'} 를 {who} {overrides} 로 저장",
        }

    t_apply = _parse(stages.get("stage9_apply", {}).get("at"))
    t_render = _parse(stages.get("render", {}).get("at"))
    if not is_image_route and (not t_apply or (t_render and t_render > t_apply + dt.timedelta(seconds=2))):
        return {
            "kind": "command",
            "why": "override가 있으나 deck.html에 반영되지 않았다 - [4] 디자인 입히기(코드명 stage9) 적용 필요.",
            "command": f"{_py()} stage9 --run {rid} --apply",
            "stage": "stage9_apply",
        }

    # --- [4+] 디자인 고도화(W23 refine) — 기본 디자인(stage9) 후·평가(deck_review) 전. go 자동 편입. ---
    #     bundle(결정론)→명세자(LLM: design_spec.json)→collect(검증·레퍼런스 수집·[사람 검토 정지])
    #     →handoff(실행자 번들). 이미 게이트를 지난 run은 소급 요구하지 않는다(deck_review와 동일 원칙).
    if not is_image_route and not cleared("design"):
        spec_json = run / "design_spec.json"
        if "refine_handoff" not in stages:
            if not spec_json.is_file():
                if "refine_bundle" not in stages:
                    return {
                        "kind": "command",
                        "why": "[4+] 디자인 고도화 — 장표별 디자인 목표 명세 프롬프트가 아직 없다"
                               "(다짜고짜 디자인 안 함 — 목표를 먼저 값싸게).",
                        "command": f"{_py()} go --run {rid}",
                        "stage": "refine_bundle",
                    }
                handoff = "secure" if mode == "secure" else "direct"
                who = "외부 LLM에 붙여넣고 결과를" if handoff == "secure" else "세션 LLM/Codex가"
                return {
                    "kind": "llm",
                    "why": "design_spec.json이 없다 — 명세자(LLM)가 장표별 디자인 목표(goal·treatment·"
                           "image_kind·form_needs)를 텍스트로 먼저 써야 한다.",
                    "handoff": handoff,
                    "command": f"{run / 'refine_prompt' / 'prompt.md'} 를 {who} {spec_json} 로 저장",
                }
            if "refine_collect" not in stages:
                return {
                    "kind": "command",
                    "why": "design_spec.json이 있으나 검증·형태 레퍼런스 수집이 안 됐다 — [4+] 명세 수거 필요.",
                    "command": f"{_py()} go --run {rid}",
                    "stage": "refine_collect",
                }
            # [4+] 사람 전속 관문: 명세·레퍼런스를 값싸게 검토하고, 참고할 파일·링크를 넣을 기회.
            #     confirm/skip 모두 대시보드 ack만 허용한다. optional 표시는 하위호환용이다.
            if not cleared("design_refs"):
                return {
                    "kind": "checkpoint",
                    "checkpoint": "design_refs",
                    "optional": True,
                    "human": True,
                    "why": checkpoint_why(
                        "design_refs", "명세·형태 레퍼런스를 검토하고(완성 디자인보다 먼저·값싸게), 참고 자료가 "
                            "있으면 파일은 design_refs/ 폴더에·링크는 design_refs/refs.md에 넣어라. "
                            "검토 완료 또는 건너뛰기는 대시보드의 사람 결정만 허용한다."),
                    "command": f"{_py()} go --run {rid}",
                    "review": [str(run / "design_spec.json"), str(run / "design_refs")],
                }
            return {
                "kind": "command",
                "why": "명세·레퍼런스 검토가 끝났다 — [4+] 실행 핸드오프를 생성한다(내용 동결·diff 심판).",
                "command": f"{_py()} go --run {rid}",
                "stage": "refine_handoff",
            }

    # --- 승인 전 평가(W3c·§6 결정 3): stage9 → LLM 평가 → 디자인 게이트 → approve ---
    #     이미 게이트를 지난 run(레거시·승인본)은 소급 요구하지 않는다.
    #     W28: image 라우트는 deck_review(deck.html 평가)를 건너뛴다 — 사람 정독은 imagedeck_ack가 담당.
    if not is_image_route and not cleared("design"):
        review_md = run / "deck_review.md"
        review_prompt = run / "deck_review" / "deck_review_prompt.md"
        if not review_md.is_file():
            if "deck_review_bundle" not in stages and not review_prompt.is_file():
                return {
                    "kind": "command",
                    "why": "승인 전 덱 평가 프롬프트가 없다 — 평가가 디자인 게이트의 판단 자료다.",
                    "command": f"{_py()} go --run {rid}",
                    "stage": "deck_review_bundle",
                }
            handoff = "secure" if mode == "secure" else "direct"
            who = "외부 LLM에 붙여넣고 결과를" if handoff == "secure" else "세션 LLM/Codex가"
            return {
                "kind": "llm",
                "why": "deck_review.md가 없다 — 승인 전 LLM 덱 평가가 필요하다.",
                "handoff": handoff,
                "command": f"{review_prompt} 를 {who} {review_md} 로 저장",
            }
        if "deck_review" not in stages:
            return {
                "kind": "command",
                "why": "deck_review.md가 있으나 계약 검증·수거가 안 됐다.",
                "command": f"{_py()} go --run {rid}",
                "stage": "deck_review",
            }

    # --- 체크포인트 3: 디자인 게이트 ---
    if not cleared("design"):
        if is_image_route:
            review = [str(run / "deck.images.html"), str(run / "imagedeck" / "collect_report.md")]
            why = "완성 이미지 덱(deck.images.html)을 보고 승인/반려를 결정한다(이미지 정독은 imagedeck_ack에서 완료)."
        else:
            review = [str(run / "deck.html"), str(run / "deck_review.md")]
            verdict = (stages.get("deck_review") or {}).get("verdict")
            why = ("완성 덱과 평가 리포트를 보고 승인/편집/반려를 결정한다."
                   + (f" (LLM 권고: {verdict})" if verdict else ""))
        return {
            "kind": "checkpoint",
            "checkpoint": "design",
            "human": True,
            "why": checkpoint_why("design", why),
            "command": f"{_py()} go --run {rid}   (대시보드 검토 완료 후)",
            "review": review,
        }

    if "approve" not in stages:
        return {"kind": "command", "why": "승인만 남았다.", "command": f"{_py()} ship --run {rid}", "stage": "approve"}

    # B4: 이미 만든 파생물은 "다음"에서 빼야 한다 — 자기보고(state.json)가 아니라 실제 파일로 판정한다
    # (approve 단계 기록은 ship 호출마다 통째로 덮이므로 자기보고만으로는 과거 파생물을 놓친다).
    remaining = []
    if not (run / "deck.pptx").is_file():
        remaining.append("--pptx")
    if not remaining:
        return {"kind": "done", "why": "승인 완료. PPTX 파생물도 이미 만들었다.",
                "command": "(없음 — 더 만들 파생물 없음)"}
    return {"kind": "done", "why": "승인 완료.",
            "command": f"{_py()} ship --run {rid} {'|'.join(remaining)}   (선택: 남은 파생)"}


# ---------------------------------------------------------------------------
# you-are-here 진행 바 (W24 — NORTHSTAR 결정 11 ①③ + 목표조정 6b)
# ---------------------------------------------------------------------------

# 6-스텝 공정 지도(정본 표기 — 그대로 노출한다). ✋②는 게이트(사람 결정)라 판정 결과값이 아니다.
PROGRESS_BAR = ("공정 지도: [1]내용 만들기 > (2)내용 확정 > [3]뼈대 잡기 > "
                "[4]디자인 입히기 > [4+]디자인 고도화 > [5]마무리·검토")

PROGRESS_LABEL = {
    "1": "[1] 내용 만들기",
    "3": "[3] 뼈대 잡기",
    "4": "[4] 디자인 입히기",
    "4+": "[4+] 디자인 고도화",
    "5": "[5] 마무리·검토",
}

_REFINE_STAGES = ("refine_bundle", "refine_collect", "refine_handoff")
_STAGE9_STAGES = ("stage9_bundle", "stage9_apply")
_WIREFRAME_STAGES = ("wireframe_bundle", "wireframe_apply")


def progress_position(stages: dict[str, dict[str, Any]], checkpoints: dict[str, dict[str, Any]]) -> str:
    """W24: 진행 바 현재 위치 판정 — 결정론(stages·checkpoints 실측 매핑만, 추측 금지).

    우선순위(순서대로 검사 — W21로 wireframe이 stage9와 design_brief 사이에 낀 것을 반영):
      1. approve 기록 또는 design 체크포인트 청산 → "5"
      2. refine_* 기록 있고 approve 없음 → "4+"
      3. stage9_bundle/stage9_apply 중 하나라도 기록 → "4" (테마 = 디자인 입히기)
      4. wireframe_bundle/wireframe_apply 중 하나라도 기록(단 stage9 전) → "3" (뼈대 잡기)
      5. design_brief만 기록(뼈대 전) → "4" (의사결정 게이트 산출물 확정 — 디벨롭 진입)
      6. decision 체크포인트 청산(그 다음은 아직 미기록) → "3"
      7. 그 전(start~render·message_map 등) → "1"

    stage9를 wireframe보다 먼저 검사하는 것이 핵심 — wireframe 기록은 stage9 phase에도 남아 있으므로,
    stage9가 있으면 "4"가 우선한다(과거 [3]으로 되돌아가 보이지 않게).

    반환값은 PROGRESS_LABEL의 키 중 하나("1"/"3"/"4"/"4+"/"5").
    """
    if "approve" in stages or bool((checkpoints.get("design") or {}).get("cleared_at")):
        return "5"
    if any(s in stages for s in _REFINE_STAGES) and "approve" not in stages:
        return "4+"
    if any(s in stages for s in _STAGE9_STAGES):
        return "4"
    if any(s in stages for s in _WIREFRAME_STAGES):
        return "3"
    if "design_brief" in stages:
        return "4"
    if bool((checkpoints.get("decision") or {}).get("cleared_at")):
        return "3"
    return "1"


def format_progress_bar(view: dict[str, Any]) -> list[str]:
    progress = view.get("progress") or {}
    label = progress.get("label")
    if not label:  # resolve()를 거치지 않은 view(테스트·부분 뷰) — stages/checkpoints로 직접 판정
        position = progress_position(view.get("stages", {}), view.get("checkpoints", {}))
        label = PROGRESS_LABEL.get(position, PROGRESS_LABEL["1"])
    return [PROGRESS_BAR, f"현재: ▶ {label}"]


# ---------------------------------------------------------------------------
# 출력
# ---------------------------------------------------------------------------

def format_status(view: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.extend(format_progress_bar(view))
    lines.append(f"# run: {view['run_id']}")
    mode = view.get("mode") or "(미기록)"
    inp = view.get("input") or {}
    ref = f"{inp.get('kind')}={inp.get('ref')}" if inp else "(미기록)"
    lines.append(f"- 모드: {mode}   입력: {ref}")
    lines.append(f"- 상태 출처: {'pipeline_state.json' if view['has_state_file'] else '산출물 추론(레거시)'}")

    lines.append("\n## 완료 단계")
    done = view["stages"]
    if not done:
        lines.append("- (없음)")
    for stage in STAGE_ORDER:
        if stage not in done:
            continue
        e = done[stage]
        tag = "" if e.get("source") == "recorded" else f"  [추론: {e.get('evidence', '?')}]"
        lines.append(f"- [x] {STAGE_LABEL[stage]} — {e.get('at')}{tag}")

    lines.append("\n## 체크포인트")
    for name in CHECKPOINTS:
        cp = view["checkpoints"].get(name, {})
        at = cp.get("cleared_at")
        mark = "x" if at else " "
        tag = f"  [추론: {cp.get('evidence')} 존재]" if at and cp.get("source") == "inferred" else ""
        lines.append(f"- [{mark}] {CHECKPOINT_LABEL[name]}" + (f" — {at}{tag}" if at else ""))
    run_dir = Path(view.get("run_dir") or ".")

    def _auto_tag(name: str) -> str:
        """W31 R-마찰2: 자동 통과(via='auto') 청산이면 사람 confirm과 구분되는 표식을 붙인다."""
        ack = read_any_ack(run_dir, name)
        if ack and ack.get("via") == "auto":
            return "  [자동 통과 - 신호 깨끗]"
        return ""

    # 선택 관문(의무 아님 — 건너뛰기=go --confirm): 통과했으면 표시, 아니면 "제안 예정"으로.
    for name in OPTIONAL_CHECKPOINTS:
        cp = view["checkpoints"].get(name, {})
        at = cp.get("cleared_at")
        mark = "x" if at else " "
        state_tag = f" — {at}{_auto_tag(name)}" if at else " (아직 · 해당 단계에서 제안)"
        lines.append(f"- [{mark}] {CHECKPOINT_LABEL[name]}{state_tag}")
    # W28: 라우트 관문(imagedeck_ack)은 image_infographic 라우트에서만 노출한다.
    if (view.get("render_route") or {}).get("route") == "image_infographic":
        for name in ROUTE_CHECKPOINTS:
            cp = view["checkpoints"].get(name, {})
            at = cp.get("cleared_at")
            mark = "x" if at else " "
            state_tag = f" — {at}{_auto_tag(name)}" if at else " (아직 · 이미지 관통 단계에서 제안)"
            lines.append(f"- [{mark}] {CHECKPOINT_LABEL[name]}{state_tag}")

    # W31 R-마찰2: 관문 프로파일(run/gates.json — 없으면 standard 기본).
    gv = view.get("gates") or {}
    lines.append("\n## 관문 프로파일 (W31 리허설 마찰2)")
    profile_line = f"- 프로파일: {gv.get('profile', 'standard')}"
    if gv.get("overrides"):
        profile_line += f"  (개별 조정: {gv['overrides']})"
    lines.append(profile_line)
    lines.append("  full=전 관문 정지 · standard(기본)=회의 관문만 정지 · express=비스킵 2종도 조건부(신호 나쁘면 정지)")

    # W15(결정 9①③): 메시지맵(내용 결정 게이트 산출물) 노출 — 의사결정 게이트 승인 대상.
    mm = view.get("message_map")
    if mm:
        lines.append("\n## 메시지맵 (의사결정 게이트 승인 대상 · 결정 9①)")
        gov_flag = "" if mm["gating"]["governing_ok"] else "  [!] governing 위반(정확히 1개 아님)"
        lines.append(f"- 핵심 주장: {mm['governing_message'] or '(없음)'}{gov_flag}")
        for a in mm["axes"]:
            lines.append(f"- 축 [{a.get('id') or '?'}]: {a.get('message') or ''}")
        s = mm["gating"]["slots"]
        lines.append(f"- 근거 슬롯: filled={s['filled']} example={s['example']} empty={s['empty']}")

    # ε패킷 안전장치③(2026-07-23): 단계별 지식 사용 상시 표면화(기록 있는 단계만 — 강제 아님).
    if view.get("knowledge"):
        lines.append("\n## 지식 사용 (ε패킷 원장 — knowledge_ledger.json)")
        lines.extend(view["knowledge"])

    if view["warnings"]:
        lines.append("\n## 경고")
        for w in view["warnings"]:
            lines.append(f"- [!] {w}")

    step = view["next"]
    lines.append("\n## 다음")
    if step.get("kind") == "checkpoint" and is_human(step.get("checkpoint", "")):
        cp = step["checkpoint"]
        lines.append(f"- [사람 대기] waiting_human:{cp}")
        # W31 리허설 마찰7: 대시보드 버튼(또는 journey 폴더 체크)을 이미 눌렀어도 status는 다음
        # go가 소비하기 전까지 checkpoints.cleared_at을 그대로 두므로 "아직"으로만 보였다 —
        # 상태 판정(cleared_at)은 바꾸지 않고 표시만 덧붙인다.
        pending_ack = read_any_ack(run_dir, cp)
        if (pending_ack and pending_ack.get("via") in HUMAN_ACK_VIA
                and pending_ack.get("decision") in ("confirm", "skip")
                and not is_stale(run_dir, cp, pending_ack.get("at"))):
            lines.append(
                "  [ack 있음(대시보드/폴더 체크) — 다음 go가 소비] "
                f"via={pending_ack['via']} decision={pending_ack['decision']}"
            )
    lines.append(f"- 왜: {step['why']}")
    lines.append(f"- 다음 커맨드: {step['command']}")
    for path in step.get("review", []):  # 체크포인트에서 사람이 읽을 자료(디자인 게이트 = 덱 + 평가)
        lines.append(f"- 검토: {path}")
    return "\n".join(lines)
