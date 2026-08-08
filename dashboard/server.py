# -*- coding: utf-8 -*-
"""실공고 선별 대시보드 — 로컬 서버 (Python stdlib, 무의존).

기능: 수집된 실공고를 표시(A0 모니터링 요원 층) → 사용자가 Go/Hold/Skip + 메모를 남긴다
(이 결정은 실행 트리거가 아니라 **메모**로만 저장됨, feedback.json). 착수(A1)는 클릭이 아니라
공고 카드의 고유번호 복사 버튼 → Claude 채팅에 붙여넣기가 실행 통로다(R8, 2026-07-21).
실행:  python dashboard/server.py   (기본 http://127.0.0.1:8754)
       python dashboard/server.py --port 9000

피드백 스키마(feedback.json):
  { "<bid_no>": {"decision": "go|hold|skip", "memo": "...", "updated_at": "ISO"}, ... }
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
LAST_SEARCH = HERE / "last_search.json"

from build_data import load_bids, items_to_bids, CORE  # noqa: E402  (path 보강 후 import)

# app/ 엔진 모듈(전부 stdlib만 사용 — 대시보드 무의존 원칙 유지).
sys.path.insert(0, str(HERE.parent / "app"))

sys.path.insert(0, str(HERE.parent / "proposal_system" / "scripts"))
import pipeline_state  # noqa: E402  (현황 표시 — 상태머신 resolve로 다음 단계/이어가기 CLI 노출)
import imagedeck  # noqa: E402  (W28 이미지 라우트 — imagedeck_ack 카드의 검수 scaffold 생성)

INDEX = HERE / "index.html"
FEEDBACK = HERE / "feedback.json"
VALID_DECISIONS = {"go", "hold", "skip", ""}
VALID_ACK_DECISIONS = {"confirm", "skip"}
SKIPPABLE_ACK_GATES = ("design_refs", "skeleton_review", "wireframe_review", "theme_confirm")
ROOT = HERE.parent
RUNS = ROOT / "proposal_system" / "workspace" / "runs"
# NORTHSTAR 결정 13(W25): 분석카드/프롬프트 산출물을 workspace/analysis로 통합(run들과 나란히).
# 쓰기는 새 위치만(az.ANALYSIS_DIR도 동일하게 이전됨). 읽기는 새 위치 우선 + 레거시(vendor) 폴백.
ANALYSIS = ROOT / "proposal_system" / "workspace" / "analysis"
ANALYSIS_LEGACY = CORE / "analysis"
SAFE_BID = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_feedback() -> dict:
    if FEEDBACK.exists():
        try:
            data = json.loads(FEEDBACK.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return {}
            for entry in data.values():
                if isinstance(entry, dict):
                    entry.setdefault("reviewed", False)
            return data
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_feedback(data: dict) -> None:
    FEEDBACK.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def current_bids() -> tuple[list, dict]:
    """마지막 검색 결과가 있으면 그것을, 없으면 digest 기반 기본 목록을 반환."""
    if LAST_SEARCH.exists():
        try:
            d = json.loads(LAST_SEARCH.read_text(encoding="utf-8"))
            return _attach_pipeline_status(d.get("bids", [])), {
                "query": d.get("query"), "days": d.get("days"), "ts": d.get("ts")
            }
        except (json.JSONDecodeError, OSError):
            pass
    return _attach_pipeline_status(load_bids()), {"query": None}


def run_search(query: str) -> dict:
    """AND/OR 불리언 쿼리로 라이브 수집 → DB 적재 → 대시보드 bid 목록 반환."""
    import datetime as _dt
    import importlib.util

    spec = importlib.util.spec_from_file_location("_collector_run", CORE / "collector.py")
    col = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(col)  # type: ignore

    env = col.load_env(str(CORE / ".env"))
    key = env.get("DATA_GO_KR_API_KEY", "")
    if not key or "여기에" in key:
        return {"error": "API 키 미설정 (.env DATA_GO_KR_API_KEY)"}

    days, merged = col.collect_query(key, query)
    con = col.init_db()
    try:
        new_rows = col.upsert(con, merged)
        col.write_digest(days, new_rows, len(merged), keyword_label=query)
    finally:
        con.close()
    bids = _attach_pipeline_status(items_to_bids(merged))
    out = {"query": query, "days": days, "count": len(bids),
           "ts": _now(), "bids": bids}
    LAST_SEARCH.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def _load_analyzer():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_analyzer", CORE / "analyzer.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore
    return mod


def _clean(s):
    """surrogate(과거 인코딩 손실 적재분)·인코딩 불가 문자 제거 — UTF-8 안전화."""
    if not isinstance(s, str):
        return s
    return s.encode("utf-8", "ignore").decode("utf-8")


def run_analyze(bid_no: str) -> dict:
    """stage 2(첨부 다운/파싱) + stage 3(분석 프롬프트 조립). 분석카드(있으면) 동봉.

    카드(.md)는 LLM 세션이 생성 — 여기서는 결정적 백본만 돌리고 카드 존재 여부를 알린다.
    """
    import json as _json
    az = _load_analyzer()
    row = az.find_bid(bid_no)
    if not row:
        return {"error": f"공고 '{bid_no}' 를 DB에서 찾지 못함(검색으로 먼저 수집 필요)"}
    bno, raw_json = row
    raw = _json.loads(raw_json)
    body, manifest = az.combined_text(bno, raw)            # stage 2: 다운로드+파싱(네트워크)
    prompt = _clean(az.build_prompt(raw, body, manifest))  # stage 3: 프롬프트
    safe = bno.replace("/", "_")
    az.os.makedirs(az.ANALYSIS_DIR, exist_ok=True)
    prompt_path = Path(az.ANALYSIS_DIR) / f"{safe}_프롬프트.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    card_path = Path(az.ANALYSIS_DIR) / f"{safe}_분석카드.md"
    card = card_path.read_text(encoding="utf-8") if card_path.exists() else None
    facts = az.deterministic_facts(raw)
    return {
        "bid_no": bno,
        "bid_name": _clean(raw.get("bidNtceNm")),
        "facts": [{"k": k, "v": _clean(v)} for k, v in facts],
        "manifest": [_clean(m) for m in manifest],
        "attachments": len(manifest),
        "prompt_path": str(prompt_path),
        "prompt_chars": len(prompt),
        "prompt": prompt,                 # 사람이 LLM에 붙여넣을 프롬프트 전문
        "card_exists": card is not None,
        "card_md": card,
    }


def save_card(bid_no: str, card_md: str) -> dict:
    """사람이 LLM에서 받은 분석카드(.md)를 저장."""
    az = _load_analyzer()
    safe = bid_no.replace("/", "_")
    az.os.makedirs(az.ANALYSIS_DIR, exist_ok=True)
    path = Path(az.ANALYSIS_DIR) / f"{safe}_분석카드.md"
    path.write_text(_clean(card_md), encoding="utf-8")
    return {"ok": True, "bid_no": bid_no, "path": str(path), "chars": len(card_md)}


class RequestError(ValueError):
    pass


def _validated_bid_no(value) -> str:
    bid_no = str(value or "").strip()
    safe = bid_no.replace("/", "_").replace("\\", "_")
    if not bid_no or not SAFE_BID.fullmatch(safe) or ".." in safe:
        raise RequestError("bid_no는 영문, 숫자, 점, 밑줄, 하이픈만 사용할 수 있습니다")
    return safe


def _validated_run_dir(value) -> Path:
    run_id = str(value or "").strip()
    if not run_id or not SAFE_BID.fullmatch(run_id) or ".." in run_id:
        raise RequestError("run_id는 영문, 숫자, 점, 밑줄, 하이픈만 사용할 수 있습니다")
    run = (RUNS / run_id).resolve()
    if run.parent != RUNS.resolve():
        raise RequestError("안전하지 않은 run 경로입니다")
    if not run.is_dir():
        raise FileNotFoundError(f"run을 찾지 못했습니다: {run_id}")
    return run


def write_checkpoint_ack(run_id, gate, decision) -> dict:
    """사람 전속 관문 ack 기록 — **대시보드만 쓴다**(파이프라인·세션은 생성 금지, W27 D4)."""
    run = _validated_run_dir(run_id)
    gate = str(gate or "").strip()
    decision = str(decision or "").strip().lower()
    if gate not in pipeline_state.HUMAN_CHECKPOINTS:
        raise RequestError("gate는 사람 전속 관문이어야 합니다")
    if decision not in VALID_ACK_DECISIONS:
        raise RequestError("decision은 confirm 또는 skip이어야 합니다")
    if decision == "skip" and gate not in SKIPPABLE_ACK_GATES:
        raise RequestError("이 관문은 건너뛸 수 없습니다")
    ack_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="microseconds")
    ack = {"gate": gate, "decision": decision, "at": ack_at, "via": "dashboard"}
    path = pipeline_state.ack_path(run, gate)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "run_id": run.name, "ack": ack, "path": str(path)}


def request_imagedeck_review(run_id) -> dict:
    """W28 Q2 [Claude 검수 요청] — 장별 정본 대조표(imagedeck_review.md)를 결정론 생성한다.

    대시보드는 LLM을 부르지 않는다 — scaffold만 만든다(세션 Claude가 이미지 Read 후 채움).
    사람이 '바로 정독'을 택하면 이 버튼을 안 누르고 검토 완료(imagedeck_ack)로 직행하면 된다.
    """
    run = _validated_run_dir(run_id)
    try:
        rep = imagedeck.review_scaffold(run)
    except imagedeck.ImagedeckError as exc:
        raise RequestError(str(exc))
    return {"ok": True, "run_id": run.name, "review_md": rep["out"], "slides": rep["slides"]}


def _find_analysis_file(filename: str) -> Path:
    """분석카드/프롬프트 읽기: 새 위치(workspace/analysis) 우선, 없으면 레거시(vendor) 폴백.

    쓰기는 항상 새 위치(ANALYSIS)만 사용한다 — 이 함수는 읽기 전용 조회다.
    """
    new_path = ANALYSIS / filename
    if new_path.is_file():
        return new_path
    legacy_path = ANALYSIS_LEGACY / filename
    if legacy_path.is_file():
        return legacy_path
    return new_path


def _image_workorder(run: Path) -> "dict | None":
    """design_spec.json → 이미지 분업 지시서 요약 (W27 P2 — 검토 대기 카드에 표면화).

    사람이 검토 시점에 봐야 할 수급 분담: user_asset(사람 제공)·client_asset(발주처 자산)·
    web_sample(웹 검색)·codex_gen(생성 큐)·none(사유 있는 생략). 실패는 삼킨다(부가 정보).
    """
    try:
        spec = json.loads((run / "design_spec.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    default_route = {"evidence": "user_asset", "mood": "codex_gen", "conceptual": "codex_gen"}
    routes: dict[str, list[str]] = {}
    none_n = 0
    for ent in spec.get("slides") or []:
        if not isinstance(ent, dict):
            continue
        kind = ent.get("image_kind")
        sid = str(ent.get("slide_id") or "?")
        if kind == "none":
            none_n += 1
            continue
        if kind not in ("evidence", "mood", "conceptual"):
            continue
        route = ent.get("source_route") or default_route[kind]
        routes.setdefault(route, []).append(sid)
    if not routes and not none_n:
        return None
    return {
        "user_asset": routes.get("user_asset", []),
        "client_asset": routes.get("client_asset", []),
        "web_sample": routes.get("web_sample", []),
        "codex_gen": routes.get("codex_gen", []),
        "none": none_n,
    }


def _run_status_summary(run: Path) -> "dict | None":
    """run의 상태머신 현황 한 줄 + 이어가기 CLI (대시보드→CLI 핸드오프 · 이후엔 현황 표시).

    엔진 신규 로직 없음 — pipeline_state.resolve의 next를 사람이 읽는 라벨로 옮기기만 한다.
    실패는 삼킨다(현황은 부가 정보 — bids 목록을 막지 않는다).
    """
    try:
        nxt = pipeline_state.resolve(run).get("next") or {}
    except Exception:
        return None
    kind = nxt.get("kind")
    human_gate = None
    human_label = None
    human_acked = False
    human_skippable = False
    if kind == "done":
        label = "완료 · ship 단계"
    elif kind == "checkpoint":
        cp = nxt.get("checkpoint")
        human = pipeline_state.is_human(cp)
        ack = pipeline_state.read_ack(run, cp) if human else None
        if human:
            human_label = pipeline_state.CHECKPOINT_LABEL.get(cp, cp or "관문")
            if str(nxt.get("why") or "").startswith("[재무장]"):
                human_label = "[재무장] " + human_label
            ack_stale = pipeline_state.is_stale(run, cp, ack["at"]) if ack is not None else None
            human_acked = ack is not None and ack_stale is None
            human_gate = None if human_acked else cp
            human_skippable = human_gate in SKIPPABLE_ACK_GATES
            label = ("검토 기록됨: " if human_acked else "검토 대기: ") + human_label
        else:
            opt = cp in getattr(pipeline_state, "OPTIONAL_CHECKPOINTS", ())
            label = ("선택 관문 대기: " if opt else "관문 대기: ") + pipeline_state.CHECKPOINT_LABEL.get(cp, cp or "관문")
    elif kind == "llm":
        label = "LLM 산출 대기 (핸드오프)"
    elif kind == "command":
        stg = nxt.get("stage")
        label = "진행 중 · 다음: " + pipeline_state.STAGE_LABEL.get(stg, stg or "다음 단계")
    else:
        label = "상태 미상"
    workorder = _image_workorder(run) if human_gate == "design_refs" else None
    return {
        "label": label, "cli": nxt.get("command"), "kind": kind,
        "human_gate": human_gate, "human_label": human_label, "human_acked": human_acked,
        "human_skippable": human_skippable,
        "image_workorder": workorder,
    }


def _attach_pipeline_status(bids: list) -> list:
    """공고 경로를 allowlist 문자로 제한해 분석카드/생성덱 존재 상태를 붙인다.

    run이 시작됐으면 상태머신 현황(다음 단계 라벨)과 **이어가기 CLI 명령**도 붙인다 —
    대시보드에서 시작해 자연스럽게 CLI로 넘어가고, 이후 대시보드는 현황을 보여주는 흐름."""
    enriched = []
    for source in bids:
        bid = dict(source)
        raw_bid = str(bid.get("bid_no") or bid.get("id") or "").strip()
        safe_bid = raw_bid.replace("/", "_").replace("\\", "_")
        if SAFE_BID.fullmatch(safe_bid) and ".." not in safe_bid:
            card = _find_analysis_file(f"{safe_bid}_분석카드.md").resolve()
            deck = (RUNS / f"gen_{safe_bid}" / "deck.html").resolve()
            bid["has_card"] = (
                card.parent in (ANALYSIS.resolve(), ANALYSIS_LEGACY.resolve())
                and card.is_file()
            )
            expected_run = (RUNS / f"gen_{safe_bid}").resolve()
            bid["has_deck"] = (
                deck.parent == expected_run
                and expected_run.parent == RUNS.resolve()
                and deck.is_file()
            )
            bid["deck_url"] = f"/generated/gen_{safe_bid}/deck.html" if bid["has_deck"] else None
            # 현황 + 이어가기 CLI (run이 시작된 공고만). 실패해도 목록은 그대로.
            bid["run_name"] = None
            bid["stage_label"] = None
            bid["next_cli"] = None
            bid["human_gate"] = None
            bid["human_label"] = None
            bid["human_acked"] = False
            if expected_run.is_dir() and expected_run.parent == RUNS.resolve():
                bid["run_name"] = f"gen_{safe_bid}"
                summ = _run_status_summary(expected_run)
                if summ:
                    bid["stage_label"] = summ["label"]
                    bid["next_cli"] = summ["cli"]
                    bid["human_gate"] = summ["human_gate"]
                    bid["human_label"] = summ["human_label"]
                    bid["human_acked"] = summ["human_acked"]
                    bid["image_workorder"] = summ.get("image_workorder")
        else:
            bid["has_card"] = False
            bid["has_deck"] = False
            bid["deck_url"] = None
            bid["run_name"] = None
            bid["stage_label"] = None
            bid["next_cli"] = None
            bid["human_gate"] = None
            bid["human_label"] = None
            bid["human_acked"] = False
        enriched.append(bid)
    return enriched


def open_output_folder(bid_no) -> dict:
    """검증된 공고의 기존 run 디렉터리를 호스트 파일 탐색기로 연다."""
    safe_bid = _validated_bid_no(bid_no)
    run_dir = (RUNS / f"gen_{safe_bid}").resolve()
    if run_dir.parent != RUNS.resolve():
        raise RequestError("안전하지 않은 run 경로입니다")
    if not run_dir.is_dir():
        raise FileNotFoundError(f"출력 폴더를 찾지 못했습니다: gen_{safe_bid}")

    if sys.platform == "win32":
        try:
            # explorer.exe는 폴더를 정상적으로 열고도 1로 끝날 수 있어 기다리거나
            # 종료코드를 성공 판정에 사용하지 않고 프로세스 시작만 확인한다.
            subprocess.Popen(
                ["explorer.exe", str(run_dir)],
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as explorer_error:
            startfile = getattr(os, "startfile", None)
            if startfile is None:
                raise RuntimeError(f"Windows 파일 탐색기를 시작할 수 없습니다: {explorer_error}") from explorer_error
            try:
                startfile(str(run_dir))
            except OSError as startfile_error:
                raise RuntimeError(
                    f"Windows 파일 탐색기를 시작할 수 없습니다: {startfile_error}"
                ) from startfile_error
        return {"ok": True, "path": str(run_dir)}

    commands = ("open", "xdg-open") if sys.platform == "darwin" else ("xdg-open", "open")
    launch_errors = []
    for command in commands:
        executable = shutil.which(command)
        if not executable:
            continue
        try:
            subprocess.Popen(
                [executable, str(run_dir)],
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return {"ok": True, "path": str(run_dir)}
        except OSError as exc:
            launch_errors.append(f"{command}: {exc}")
    detail = "; ".join(launch_errors) or "xdg-open/open 실행 파일 없음"
    raise RuntimeError(f"파일 탐색기를 시작할 수 없습니다: {detail}")


class Handler(BaseHTTPRequestHandler):
    def _send(
        self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8",
        headers: dict | None = None,
    ) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):  # noqa: N802
        path = unquote(urlparse(self.path).path)
        if path in ("/", "/index.html"):
            self._send(200, INDEX.read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/bids":
            bids, meta = current_bids()
            self._json(200, {"bids": bids, "feedback": load_feedback(), "meta": meta})
        elif path == "/api/feedback":
            self._json(200, load_feedback())
        elif re.fullmatch(
            r"/generated/gen_[A-Za-z0-9._-]{1,100}/deck\.(?:html|pptx)", path
        ):
            run_name = path.split("/")[2]
            artifact_name = path.rsplit("/", 1)[-1]
            deck = (RUNS / run_name / artifact_name).resolve()
            expected_parent = (RUNS / run_name).resolve()
            if deck.parent != expected_parent or expected_parent.parent != RUNS.resolve():
                self._json(403, {"error": "unsafe path"})
            elif deck.is_file():
                if artifact_name == "deck.pptx":
                    self._send(
                        200, deck.read_bytes(),
                        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        {"Content-Disposition": f'attachment; filename="{run_name}_deck.pptx"'},
                    )
                else:
                    self._send(200, deck.read_bytes(), "text/html; charset=utf-8")
            else:
                self._json(404, {"error": "generated deck not found"})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if self.path not in (
            "/api/feedback", "/api/search", "/api/analyze", "/api/card",
            "/api/open-folder", "/api/ack", "/api/imagedeck-review",
        ):
            self._json(404, {"error": "not found"})
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
        except (ValueError, json.JSONDecodeError):
            self._json(400, {"error": "bad json"})
            return
        if self.path == "/api/ack":
            try:
                self._json(200, write_checkpoint_ack(
                    payload.get("run_id"), payload.get("gate"), payload.get("decision"),
                ))
            except RequestError as e:
                self._json(400, {"error": str(e)})
            except FileNotFoundError as e:
                self._json(404, {"error": str(e)})
            except Exception as e:
                self._json(500, {"error": f"ack 기록 실패: {type(e).__name__}: {e}"})
            return
        if self.path == "/api/imagedeck-review":
            try:
                self._json(200, request_imagedeck_review(payload.get("run_id")))
            except RequestError as e:
                self._json(400, {"error": str(e)})
            except FileNotFoundError as e:
                self._json(404, {"error": str(e)})
            except Exception as e:
                self._json(500, {"error": f"검수 scaffold 생성 실패: {type(e).__name__}: {e}"})
            return
        if self.path == "/api/open-folder":
            try:
                self._json(200, open_output_folder(payload.get("bid_no")))
            except RequestError as e:
                self._json(400, {"error": str(e)})
            except FileNotFoundError as e:
                self._json(404, {"error": str(e)})
            except Exception as e:
                self._json(500, {"error": f"출력 폴더 열기 실패: {type(e).__name__}: {e}"})
            return
        if self.path == "/api/search":
            query = (payload.get("q") or "").strip()
            if not query:
                self._json(400, {"error": "검색어(q)가 필요합니다"})
                return
            try:
                result = run_search(query)
            except Exception as e:  # 네트워크/파싱 오류를 사용자에게 전달
                self._json(502, {"error": f"수집 실패: {type(e).__name__}: {e}"})
                return
            code = 200 if "error" not in result else 400
            result["feedback"] = load_feedback()
            self._json(code, result)
            return
        if self.path == "/api/analyze":
            bid_no = (payload.get("bid_no") or "").strip()
            if not bid_no:
                self._json(400, {"error": "bid_no가 필요합니다"})
                return
            try:
                result = run_analyze(bid_no)
            except Exception as e:
                self._json(502, {"error": f"분석 실패: {type(e).__name__}: {e}"})
                return
            self._json(200 if "error" not in result else 400, result)
            return
        if self.path == "/api/card":
            bid_no = (payload.get("bid_no") or "").strip()
            card_md = payload.get("card_md")
            if not bid_no or not (card_md or "").strip():
                self._json(400, {"error": "bid_no와 card_md(붙여넣은 분석카드)가 필요합니다"})
                return
            try:
                self._json(200, save_card(bid_no, card_md))
            except Exception as e:
                self._json(500, {"error": f"카드 저장 실패: {type(e).__name__}: {e}"})
            return
        bid_no = (payload.get("bid_no") or "").strip()
        decision = (payload.get("decision") or "").strip().lower()
        memo = payload.get("memo")
        reviewed = payload.get("reviewed")
        if not bid_no or decision not in VALID_DECISIONS:
            self._json(400, {"error": "bid_no required; decision must be go/hold/skip/''"})
            return
        if "reviewed" in payload and not isinstance(reviewed, bool):
            self._json(400, {"error": "reviewed must be boolean"})
            return
        fb = load_feedback()
        entry = fb.get(bid_no, {})
        if not isinstance(entry, dict):
            entry = {}
        if "decision" in payload:
            entry["decision"] = decision
        if memo is not None:
            entry["memo"] = str(memo)
        if "reviewed" in payload:
            entry["reviewed"] = reviewed
        else:
            entry.setdefault("reviewed", False)
        entry["updated_at"] = _now()
        fb[bid_no] = entry
        save_feedback(fb)
        self._json(200, {"ok": True, "bid_no": bid_no, "entry": entry})

    def log_message(self, *a):  # quiet
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8754)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    n = len(load_bids())
    print(f"[dashboard] {n} bids · http://{args.host}:{args.port}  (feedback → {FEEDBACK})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[dashboard] stopped")


if __name__ == "__main__":
    main()
