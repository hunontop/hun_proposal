# -*- coding: utf-8 -*-
"""W31 리허설 마찰 2호 해소 — run별 관문 프로파일 + 조건부 승격 (`run/gates.json`).

배경(사용자 승인 2026-07-21): 관문이 전부-아니면-전무였다 — `go --confirm`/대시보드 스킵 연타는
무검토 통과, 반대로 사람이 신경 쓰지 않는 선택 관문까지 전부 대시보드 정지를 요구했다. 해법:

  1. **run별 관문 프로파일**(`full`/`standard`/`express`) — 프로파일마다 각 관문을
     "정지"(사람이 대시보드에서 confirm/skip해야 통과) 또는 "자동"(신호가 깨끗하면 go가 조용히
     통과)으로 분류한다.
  2. **조건부 승격** — "자동" 관문이라도 그 관문의 결정론 신호가 나쁘면 정지로 되돌린다("꺼진
     관문도 나쁜 신호 시 자동 재정지"). 신호 데이터가 아예 없으면: 스킵 가능 관문은 통과, 비스킵
     2종(imagedeck_prompt_ack·imagedeck_ack)은 보수적으로 정지.

**scope(대상 관문)** — `pipeline_state.HUMAN_CHECKPOINTS` 8개 중, 사용자 표면 3대 체크포인트
(start·decision·design)와 그 "회의 관문" 계열은 이 다이얼의 대상이 **아니다**(항상 정지 —
approve/ship과 같은 계열의 불변). 다이얼 대상은 나머지 6개뿐이다:
  - **스킵 가능 4종**(`dashboard.server.SKIPPABLE_ACK_GATES`와 동일 목록 — 값만 복제, 대시보드는
    이 모듈을 import하지 않으므로 단일 소재지는 서버 상수. 값 자체는 W27 결정으로 안정적):
    `design_refs · skeleton_review · wireframe_review · theme_confirm`.
  - **비스킵 2종**(대시보드에 건너뛰기 버튼 자체가 없다 — W28/W30 결정): `imagedeck_prompt_ack
    · imagedeck_ack`. express 프로파일에서도 완전히 꺼지지 않는다 — 신호가 나쁘면 정지로
    돌아온다(W27 "이빨" 절충 유지).

결정론·0토큰 — 이 모듈은 LLM을 호출하지 않는다(pipeline_state.py·design_contract.py와 같은 계열).
실제 side-effect(state.json 체크포인트 clear·ack 파일 쓰기)는 이 모듈이 하지 않는다 — `go_cmd`가
`decide()`의 판정을 보고 실행한다(읽기 전용 `pipeline_state.resolve()`가 파일을 쓰지 않는다는
기존 규율을 그대로 따른다). 이 모듈이 쓰는 파일은 `run/gates.json`(설정 자체, `save_config`)과
`run/checkpoint_ack/<gate>.json`(자동 통과 기록, `write_auto_ack` — 호출부가 명시적으로 부를 때만).
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
GATES_NAME = "gates.json"

PROFILES = ("full", "standard", "express")
DEFAULT_PROFILE = "standard"

# 스킵 가능 4종 — dashboard/server.py의 SKIPPABLE_ACK_GATES와 동일한 값(대시보드 "건너뛰기" 버튼
# 허용 목록). 비스킵 2종 — imagedeck 라우트 전속, 대시보드에 스킵 버튼이 없다(W28 D8·W30).
SKIPPABLE_GATE_IDS = ("design_refs", "skeleton_review", "wireframe_review", "theme_confirm")
NON_SKIPPABLE_GATE_IDS = ("imagedeck_prompt_ack", "imagedeck_ack")
GATE_IDS = SKIPPABLE_GATE_IDS + NON_SKIPPABLE_GATE_IDS

# 프로파일별 기본값: gate_id -> "stop"|"auto". override(gates.json.overrides)가 있으면 최후승.
#   full     : 전 관문 정지(현행 "편집 모드"와 동일 — 다이얼 신설 이전 동작 그대로).
#   standard : 회의 관문만 정지(decision·design은 다이얼 밖이라 항상 정지 — 아래 표에 없음).
#              theme_confirm(B1 테마 확정)·imagedeck_prompt_ack·imagedeck_ack(B2·B5, 비스킵)만
#              정지, 나머지(스켈레톤/뼈대/디자인고도화 검토)는 자동 통과 대상.
#   express  : 스킵 가능 4종은 전부 자동. 비스킵 2종은 "자동"으로 분류하되 아래 decide()의
#              조건부 승격이 항상 함께 걸린다 — express에서도 완전히 꺼지지 않는다.
PROFILE_DEFAULTS: dict[str, dict[str, str]] = {
    "full": {g: "stop" for g in GATE_IDS},
    "standard": {
        "design_refs": "auto",
        "skeleton_review": "auto",
        "wireframe_review": "auto",
        "theme_confirm": "stop",
        "imagedeck_prompt_ack": "stop",
        "imagedeck_ack": "stop",
    },
    "express": {
        "design_refs": "auto",
        "skeleton_review": "auto",
        "wireframe_review": "auto",
        "theme_confirm": "auto",
        "imagedeck_prompt_ack": "auto",
        "imagedeck_ack": "auto",
    },
}

# ---------------------------------------------------------------------------
# 조건부 승격 임계값 — 실측 가능한 신호만, 임계는 단순하게(상수 + 근거 주석).
#   근거 파일/필드:
#     - gating_report.json.review_needed_total (proposal_pipeline.render_run이 기록)
#     - gating_report.json.review_badges.counts["발산추천"|"밋밋"|"충실"] (app/review_badges.py)
#     - gating_report.json.design_checks.browser (app/render/layout_probe.repair_targets 실측)
#     - gating_report.json.length_rhythm.band_violations (proposal_pipeline._compute_length_rhythm)
#     - imagedeck_manifest.json.slides[].flags/missing_binds (생산 전 — imagedeck.bundle)
#     - imagedeck_collect.json.slides[].status (수거 검증 — imagedeck.collect)
# ---------------------------------------------------------------------------
REVIEW_NEEDED_BAD = 3            # 검토요망(review_needed) 잔존 >= 3장 — 근거 미확보 콘텐츠 다수
LOW_SCORE_RATIO_BAD = 0.5        # review_badges 저점수(발산추천+밋밋) 비율 >= 50% — 덱 절반 이상이 얇음
BROWSER_WARN_BAD = 5             # design_checks.browser 실측 결함(repair_targets) >= 5건
IMAGEDECK_PROMPT_FLAG_BAD = 1    # 프롬프트 번들 단계 flags/missing_binds 보유 장 >= 1건(생산 전 경고)
IMAGEDECK_COLLECT_FAIL_BAD = 1   # 수거 검증 불합격(px/파일명/커버리지 미달) 장 >= 1건
# W31 γ패킷(리허설 마찰22): 분량 밴드 위반 장수 임계 — 실측 사례(장 3, 밴드 3~4배 초과)가 이미지
# 단계 오버플로로 실현된 뒤에야 발견됐다("경고와 파손의 거리" 문제). 3장 이상이면 국소 일탈이 아니라
# 구조적 위험으로 보고 08(imagedeck_prompt_ack) 관문을 조건부 재정지한다(신호는 render 단계 실측,
# gating_report.json.length_rhythm.band_violations — proposal_pipeline._compute_length_rhythm).
BAND_VIOLATION_BAD = 3


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _load_json(p: Path) -> Any | None:
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# gates.json — 정본(프로파일 + override)
# ---------------------------------------------------------------------------

def config_path(run: Path) -> Path:
    return Path(run) / GATES_NAME


def load_config(run: Path) -> dict[str, Any]:
    """gates.json 로드. 없으면 `standard`(기본값)로 조용히 폴백 — 파일 부재가 정상 상태다."""
    run = Path(run)
    data = _load_json(config_path(run))
    has_file = isinstance(data, dict)
    profile = (data or {}).get("profile") if has_file else None
    if profile not in PROFILES:
        profile = DEFAULT_PROFILE
    overrides = (data or {}).get("overrides") if has_file else None
    if not isinstance(overrides, dict):
        overrides = {}
    overrides = {k: v for k, v in overrides.items() if k in GATE_IDS and v in ("stop", "auto")}
    return {
        "profile": profile,
        "overrides": overrides,
        "source": "recorded" if config_path(run).is_file() else "default",
    }


def save_config(run: Path, *, profile: str | None = None,
                 overrides: dict[str, str] | None = None) -> Path:
    """`start --gates`/`go --gates`가 호출한다 — gates.json에 지속(중도 변경도 여기로)."""
    run = Path(run)
    if profile is not None and profile not in PROFILES:
        raise ValueError(f"profile must be one of {PROFILES}: {profile!r}")
    current = load_config(run)
    new_profile = profile or current["profile"]
    new_overrides = dict(current["overrides"])
    if overrides:
        for gate_id, mode in overrides.items():
            if gate_id not in GATE_IDS:
                raise ValueError(f"unknown gate id: {gate_id!r}")
            if mode not in ("stop", "auto"):
                raise ValueError(f"override must be stop/auto: {mode!r}")
            new_overrides[gate_id] = mode
    payload = {
        "schema_version": SCHEMA_VERSION,
        "profile": new_profile,
        "overrides": new_overrides,
        "updated_at": _now(),
    }
    p = config_path(run)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def effective_mode(run: Path, gate_id: str, config: dict[str, Any] | None = None) -> str:
    """프로파일 기본값에 override를 얹은 최종 모드 — 'stop'|'auto'. 다이얼 밖 관문은 항상 'stop'."""
    if gate_id not in GATE_IDS:
        return "stop"
    cfg = config or load_config(run)
    override = cfg["overrides"].get(gate_id)
    if override in ("stop", "auto"):
        return override
    return PROFILE_DEFAULTS[cfg["profile"]].get(gate_id, "stop")


# ---------------------------------------------------------------------------
# 신호 — 결정론 실측(0토큰). 파일이 없으면 available=False("모르는 걸 아는 척 안 함").
# ---------------------------------------------------------------------------

def _repair_target_count(gating: dict[str, Any]) -> int:
    """gating_report.design_checks.browser 실결함 flag 수(layout_probe.repair_targets 재사용)."""
    browser = ((gating or {}).get("design_checks") or {}).get("browser")
    if not browser:
        return 0
    render_dir = Path(__file__).resolve().parents[2] / "app" / "render"
    if str(render_dir) not in sys.path:
        sys.path.insert(0, str(render_dir))
    try:
        import layout_probe  # type: ignore
    except Exception:
        return 0
    try:
        return len(layout_probe.repair_targets(browser))
    except Exception:
        return 0


def _generic_signal(run: Path) -> dict[str, Any]:
    """gating_report.json 실측 — 검토요망 총수·저점수 비율·browser 결함.

    skeleton_review·wireframe_review·design_refs·theme_confirm 공용(전부 render 이후 시점이라
    gating_report.json이 있을 수 있다 — skeleton_review만 render 이전이라 파일이 없어 available=False).
    """
    gating = _load_json(Path(run) / "gating_report.json")
    if gating is None:
        return {"available": False, "bad": False, "reasons": [], "detail": {}}
    reasons: list[str] = []
    detail: dict[str, Any] = {}

    review_needed = gating.get("review_needed_total")
    if isinstance(review_needed, int):
        detail["review_needed_total"] = review_needed
        if review_needed >= REVIEW_NEEDED_BAD:
            reasons.append(f"검토요망 {review_needed}장(임계 {REVIEW_NEEDED_BAD}+)")

    counts = ((gating.get("review_badges") or {}).get("counts")) or {}
    total_badges = sum(v for v in counts.values() if isinstance(v, int))
    if total_badges:
        low = counts.get("발산추천", 0) + counts.get("밋밋", 0)
        ratio = low / total_badges
        detail["low_score_ratio"] = round(ratio, 2)
        detail["low_score_slides"] = low
        if ratio >= LOW_SCORE_RATIO_BAD:
            reasons.append(
                f"저점수(밋밋+발산추천) {low}/{total_badges}장"
                f"({ratio:.0%}, 임계 {LOW_SCORE_RATIO_BAD:.0%}+)"
            )

    warn_n = _repair_target_count(gating)
    if warn_n:
        detail["browser_warn"] = warn_n
        if warn_n >= BROWSER_WARN_BAD:
            reasons.append(f"디자인 실측 결함(browser) {warn_n}건(임계 {BROWSER_WARN_BAD}+)")

    return {"available": bool(detail), "bad": bool(reasons), "reasons": reasons, "detail": detail}


def _band_violation_signal(run: Path) -> dict[str, Any]:
    """W31 γ패킷(마찰22): gating_report.json.length_rhythm.band_violations 실측 — 분량 밴드 위반
    장수가 임계(BAND_VIOLATION_BAD) 이상이면 나쁜 신호. render 단계(04) 산출이라 imagedeck_manifest
    보다 이르게 존재할 수 있다 — 그래서 별도 함수로 분리해 두 신호(프롬프트 flag·밴드 위반)를
    독립적으로 계산한 뒤 `_imagedeck_prompt_signal`에서 합친다."""
    gating = _load_json(Path(run) / "gating_report.json")
    lr = (gating or {}).get("length_rhythm") if isinstance(gating, dict) else None
    if not isinstance(lr, dict):
        return {"available": False, "bad": False, "reasons": [], "detail": {}}
    viol = lr.get("band_violations") or []
    detail = {"band_violations": len(viol)}
    reasons: list[str] = []
    if len(viol) >= BAND_VIOLATION_BAD:
        ids = ", ".join(str(v.get("slide_id")) for v in viol[:6])
        more = " 등" if len(viol) > 6 else ""
        reasons.append(
            f"분량 밴드 위반 {len(viol)}장(임계 {BAND_VIOLATION_BAD}+, slide {ids}{more}) — "
            "이미지 단계에서 오버플로로 실현된 실측 사례가 있다(마찰22)."
        )
    return {"available": True, "bad": bool(reasons), "reasons": reasons, "detail": detail}


def _imagedeck_prompt_signal(run: Path) -> dict[str, Any]:
    """B2 프롬프트 확인 전 — imagedeck_manifest.json의 flags/missing_binds 보유 장(생산 전 경고)
    + gating_report.json의 분량 밴드 위반(마찰22, 이미지 단계 오버플로 전조 신호)을 합쳐서 본다."""
    band = _band_violation_signal(run)
    manifest = _load_json(Path(run) / "imagedeck_manifest.json")
    if manifest is None:
        # 매니페스트가 아직 없어도(번들 전) 밴드 신호는 render 단계 산출이라 먼저 있을 수 있다.
        if band["available"]:
            return band
        return {"available": False, "bad": False, "reasons": [], "detail": {}}
    slides = manifest.get("slides") or []
    flagged = [
        s for s in slides
        if isinstance(s, dict) and s.get("render") != "html" and (s.get("flags") or s.get("missing_binds"))
    ]
    detail = {"flagged_slides": len(flagged), **band["detail"]}
    reasons: list[str] = []
    if len(flagged) >= IMAGEDECK_PROMPT_FLAG_BAD:
        ids = ", ".join(str(s.get("n")) for s in flagged[:6])
        more = " 등" if len(flagged) > 6 else ""
        reasons.append(f"프롬프트 단계 flag/누락바인드 보유 장 {len(flagged)}건(n={ids}{more})")
    reasons.extend(band["reasons"])
    return {"available": True, "bad": bool(reasons), "reasons": reasons, "detail": detail}


def _imagedeck_collect_signal(run: Path) -> dict[str, Any]:
    """B5 장표 채택 전 — imagedeck_collect.json의 불합격(px/파일명/커버리지) 장 수."""
    collect = _load_json(Path(run) / "imagedeck_collect.json")
    if collect is None:
        return {"available": False, "bad": False, "reasons": [], "detail": {}}
    slides = collect.get("slides") or []
    fails = [s for s in slides if isinstance(s, dict) and s.get("status") not in ("ok", "html")]
    detail = {"collect_fail": len(fails)}
    reasons: list[str] = []
    if len(fails) >= IMAGEDECK_COLLECT_FAIL_BAD:
        ids = ", ".join(str(s.get("n")) for s in fails[:6])
        more = " 등" if len(fails) > 6 else ""
        reasons.append(f"수거 검증 불합격 {len(fails)}건(n={ids}{more})")
    return {"available": True, "bad": bool(reasons), "reasons": reasons, "detail": detail}


_SIGNAL_FUNCS = {
    "design_refs": _generic_signal,
    "skeleton_review": _generic_signal,
    "wireframe_review": _generic_signal,
    "theme_confirm": _generic_signal,
    "imagedeck_prompt_ack": _imagedeck_prompt_signal,
    "imagedeck_ack": _imagedeck_collect_signal,
}


def _knowledge_web_signal(run: Path, gate_id: str) -> dict[str, Any]:
    """ε패킷 안전장치②(2026-07-23 확정): 원장에 web 항목이 있으면 나쁜 신호 — 조건부 재정지.

    knowledge_ledger 모듈 부재/오류는 침묵(신호 없음 취급 — 이 파일의 다른 신호 함수와 동일하게
    "모듈 없으면 조용히 넘어간다"는 관례, _repair_target_count와 동형)."""
    try:
        import knowledge_ledger  # sibling, 지연 임포트(순환 방지 — 이 리포 전역 관례)
    except Exception:
        return {"available": False, "bad": False, "reasons": [], "detail": {}}
    try:
        return knowledge_ledger.web_signal_for_gate(run, gate_id)
    except Exception:
        return {"available": False, "bad": False, "reasons": [], "detail": {}}


def signal(run: Path, gate_id: str) -> dict[str, Any]:
    """gate_id의 결정론 신호 스냅샷 — {available, bad, reasons, detail}.

    기존 단계별 신호(_SIGNAL_FUNCS)에 ε패킷 지식 원장의 웹 사용 신호를 얹는다. web 신호가
    실제로 나쁠 때만(웹 항목 1건+) base를 덮어써 강제로 bad=True/available=True를 만든다 —
    web 신호가 깨끗하거나 원장이 아직 없으면 base를 그대로 반환해 기존 게이트 동작(신호 없을 때의
    보수적 정지/통과 분기 포함)을 전혀 바꾸지 않는다(회귀 방지).
    """
    fn = _SIGNAL_FUNCS.get(gate_id)
    base = fn(Path(run)) if fn is not None else {"available": False, "bad": False, "reasons": [], "detail": {}}
    web = _knowledge_web_signal(Path(run), gate_id)
    if not web.get("bad"):
        return base
    return {
        "available": True,
        "bad": True,
        "reasons": list(base.get("reasons") or []) + list(web.get("reasons") or []),
        "detail": {**(base.get("detail") or {}), "knowledge_web": web.get("detail") or {}},
    }


# ---------------------------------------------------------------------------
# 판정 — 프로파일(+override) + 조건부 승격을 종합한 최종 action.
# ---------------------------------------------------------------------------

def decide(run: Path, gate_id: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """gate_id의 최종 판정 — {gate, profile, mode, action, reason, signal}.

    action: "stop"(사람 대시보드 확인 필요) | "auto_pass"(신호 깨끗 — go가 조용히 통과시킨다).
    mode="auto"인데 action="stop"이면 조건부 승격(신호가 나빠 재정지)이 발동한 것이다.
    """
    run = Path(run)
    cfg = config or load_config(run)
    mode = effective_mode(run, gate_id, cfg)
    result: dict[str, Any] = {
        "gate": gate_id, "profile": cfg["profile"], "mode": mode,
        "action": "stop", "reason": "", "signal": None,
    }
    if mode == "stop":
        result["reason"] = f"프로파일={cfg['profile']} — 이 관문은 정지 대상(설정상 항상 사람 확인)."
        return result

    sig = signal(run, gate_id)
    result["signal"] = sig
    if sig["available"] and sig["bad"]:
        result["reason"] = (
            "자동 통과 대상이나 신호가 나쁘다(조건부 승격 - 재정지): " + "; ".join(sig["reasons"])
        )
        return result
    if not sig["available"]:
        if gate_id in NON_SKIPPABLE_GATE_IDS:
            result["action"] = "stop"
            result["reason"] = "신호 데이터 없음 — 비스킵 관문은 보수적으로 정지."
        else:
            result["action"] = "auto_pass"
            result["reason"] = "신호 데이터 없음 — 스킵 가능 관문은 기본 통과(보수적 정지 대상 아님)."
        return result

    result["action"] = "auto_pass"
    tail = f" ({'; '.join(sig['reasons'])})" if sig["reasons"] else ""
    result["reason"] = f"신호 깨끗 — 자동 통과.{tail}"
    return result


def write_auto_ack(run: Path, gate_id: str, decision_result: dict[str, Any]) -> Path:
    """자동 통과 기록 — `checkpoint_ack/<gate>.json`(via='auto', decision='auto' + 신호 요약).

    대시보드의 `write_checkpoint_ack`(via='dashboard')와 파일 경로는 같지만 `via`로 구분된다 —
    `pipeline_state.read_ack()`(대시보드 전용 필터, via=='dashboard'만 인정)는 이 기록을 사람 ack로
    인정하지 않는다. 표시 전용 조회는 `pipeline_state.read_any_ack()`를 쓴다(신뢰 판정과 분리).
    """
    import pipeline_state  # sibling, 지연 임포트(순환 방지 — message_map/design_contract와 동일 관례)
    payload = {
        "gate": gate_id,
        "decision": "auto",
        "via": "auto",
        "at": dt.datetime.now().isoformat(timespec="microseconds"),
        "profile": decision_result.get("profile"),
        "reason": decision_result.get("reason"),
        "signal": decision_result.get("signal"),
    }
    path = pipeline_state.ack_path(Path(run), gate_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def summary_line(run: Path, config: dict[str, Any] | None = None) -> str:
    """journey 매뉴얼/상태 출력에 붙이는 1줄 — 현재 프로파일 + override 유무."""
    cfg = config or load_config(run)
    line = f"관문 프로파일: {cfg['profile']}"
    if cfg["overrides"]:
        line += f" (개별 조정: {cfg['overrides']})"
    return line


def gate_note(run: Path, gate_id: str, config: dict[str, Any] | None = None) -> str:
    """해당 관문 1줄 안내(journey 매뉴얼용) — 자동 통과 대상인지, 정지 대상인지."""
    cfg = config or load_config(run)
    if gate_id not in GATE_IDS:
        return "이 관문은 프로파일 다이얼 밖(항상 정지 — 회의 관문)."
    mode = effective_mode(run, gate_id, cfg)
    if mode == "auto":
        return f"프로파일={cfg['profile']} — 자동 통과 대상(신호 나쁘면 정지로 재무장)."
    return f"프로파일={cfg['profile']} — 정지 관문(항상 사람 확인)."
