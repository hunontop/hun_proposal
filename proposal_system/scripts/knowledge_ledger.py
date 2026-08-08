# -*- coding: utf-8 -*-
"""ε패킷 — 지식 소비 체계(2026-07-23 사용자 확정): config 1점화·원장·지시 오버레이·안전장치.

배경: KC 패킷(§9.9, 2026-07-24)이 기획 입구(①)·산출 출구(③) 두 지점에 지식 pull 문구를 심었지만
(a) 조회 폴더 경로가 각 모듈에 하드코딩돼 있었고(새 지식 도메인 추가 = 코드 수정), (b) "반영했다"는
주장이 세션 자기보고일 뿐 원장으로 남지 않았으며, (c) 웹 검색을 썼는지 여부가 전혀 추적되지 않았다.
이 모듈이 세 가지를 한 자리로 모은다:

  1. **config 1점화** — `pipeline.config.json`의 `knowledge_stages` 표(단계 -> pull 폴더 목록 +
     web_search 허용 여부)가 유일한 소재지다. 이 모듈은 그 표를 읽어 pull 지시문을 조립할 뿐,
     폴더 경로를 다시 하드코딩하지 않는다.
  2. **지식 원장** — 핸드오프 산출 JSON에 `knowledge_used: {cards: [...], web: [...]}` 블록을
     의무화하고(보고 의무), 수거 시 검증·`run/knowledge_ledger.json`에 단계별 누적 기록 +
     journey 단계 폴더 `지식_사용.md` 파생 뷰를 만든다.
  3. **지식 지시 오버레이** — 각 지식 단계 journey 폴더에 `지식_지시.md`(사람 편집물, 최초 1회
     발급 — 시스템 불가침)를 두고, 다음 번들/핸드오프가 그 내용을 프롬프트에 동봉한다.

**안전장치 3중**(사용자 확정: 자동 모드에서도 보고 없이 진행 금지):
  ① knowledge_used 블록이 없는 산출물은 수거 검증 실패(validate_knowledge_used가 error 반환).
  ② 원장에 web 항목이 1건+ 있으면 그 단계의 사람 관문이 gates.py 조건부 승격으로 재정지된다
     (web_signal_for_gate — gates.py가 소비).
  ③ status/go 출력에 단계별 "지식: 카드 N · 웹 M건" 1줄이 상시 표면화된다(surface_lines).

이 모듈은 vault를 파일시스템으로 읽지 않는다(KC 패킷과 같은 제약) — pull은 세션이
obsidian_search로 능동 조회하는 프로토콜이고, 이 모듈은 "어느 폴더를 조회하라"는 지시문 조립
+ "무엇을 썼는지" 수거·기록만 한다. 결정론·0토큰.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
LEDGER_NAME = "knowledge_ledger.json"
OVERLAY_NAME = "지식_지시.md"
LEDGER_VIEW_NAME = "지식_사용.md"

# 이 패킷이 다루는 지식 단계 6종(사용자 확정 config 표와 동형).
STAGES = ("research", "message_map", "storyline", "wireframe", "master_design", "imagedeck_review")

STAGE_LABEL: dict[str, str] = {
    "research": "발주처 조사",
    "message_map": "메시지맵(기획 입구)",
    "storyline": "스토리라인",
    "wireframe": "뼈대(와이어프레임)",
    "master_design": "마스터 디자인 시안",
    "imagedeck_review": "이미지 장표 검수(산출 출구)",
}

# 단계 -> 그 단계를 확인하는 사람 관문(안전장치②가 조건부 승격을 거는 대상).
# research·message_map·storyline은 전부 `decision`(내용동결) 관문에서 함께 확인된다
# (pipeline_state.HUMAN_CHECKPOINT_WATCH["decision"] = storyline.json·message_map.json 감시와 동형
#  — MANUAL §2 "②의사결정 게이트(message_map+스토리라인 확정)"). decision·design은 gates.py
# 다이얼 밖(항상 정지)이라 이 매핑은 표시·집계용이고, 실제 조건부 재정지는 wireframe_review·
# theme_confirm·imagedeck_ack 3곳(gates.GATE_IDS 소속)에서 작동한다.
STAGE_GATE: dict[str, str] = {
    "research": "decision",
    "message_map": "decision",
    "storyline": "decision",
    "wireframe": "wireframe_review",
    "master_design": "theme_confirm",
    "imagedeck_review": "imagedeck_ack",
}

# 단계 -> journey 폴더 키(journey_folders.FOLDERS). journey_check.GATE_FOLDER_KEY와 같은 값을
# 쓰되, message_map·storyline은 함께 "05 내용동결"에 둔다(둘 다 decision 관문 대상이라 지식
# 원장·지시 오버레이도 그 자리에서 같이 보는 편이 자연스럽다 — 해석 지점, 보고서 참고).
STAGE_FOLDER_KEY: dict[str, str] = {
    "research": "03",
    "message_map": "05",
    "storyline": "05",
    "wireframe": "06",
    "master_design": "07",
    "imagedeck_review": "11",
}


# ---------------------------------------------------------------------------
# config 1점화 — pipeline.config.json의 knowledge_stages 표
# ---------------------------------------------------------------------------

def _pipeline_config_path() -> Path:
    return Path(__file__).resolve().parents[1] / "config" / "pipeline.config.json"


def load_stage_table(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """`knowledge_stages` 절. 없거나 파일이 없으면 빈 dict(안전 폴백 — 배포판/픽스처 무의존).

    `config`를 직접 넘기면(테스트 픽스처) 실제 pipeline.config.json을 읽지 않는다.
    """
    if config is not None:
        return dict(config.get("knowledge_stages") or {})
    try:
        raw = json.loads(_pipeline_config_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(raw.get("knowledge_stages") or {})


def stage_config(stage: str, table: dict[str, Any] | None = None) -> dict[str, Any]:
    table = table if table is not None else load_stage_table()
    entry = table.get(stage) or {}
    return {
        "pull": [str(f) for f in (entry.get("pull") or []) if str(f).strip()],
        "web_search": bool(entry.get("web_search")),
    }


def pull_folders(stage: str, table: dict[str, Any] | None = None) -> list[str]:
    return stage_config(stage, table)["pull"]


def web_allowed(stage: str, table: dict[str, Any] | None = None) -> bool:
    return stage_config(stage, table)["web_search"]


# ---------------------------------------------------------------------------
# 지식 지시 오버레이 (`지식_지시.md`) — 사람 편집물, 최초 1회 발급·시스템 불가침
# ---------------------------------------------------------------------------

_OVERLAY_HEADER = (
    "> ✍️ 사람 편집물 — 최초 1회만 발급된다. 이후 이 파일은 시스템이 다시 쓰지 않는다"
    "(자유롭게 채워도 유실되지 않음 — journey_folders.py의 회의록_메모.md와 같은 계열).\n\n"
)


def _overlay_template(stage: str) -> str:
    label = STAGE_LABEL.get(stage, stage)
    return (
        _OVERLAY_HEADER
        + f"# 지식 지시 — {label}\n\n"
        "다음 번들/핸드오프 생성 시 이 내용이 프롬프트에 '사용자 지식 지시' 절로 동봉된다.\n\n"
        "## [추가로 참고]\n(추가로 조회했으면 하는 지식 카드·주제를 한 줄씩 적어라. 없으면 비워둔다.)\n\n"
        "## [제외]\n(이번엔 참고하지 않았으면 하는 카드·주제. 없으면 비워둔다.)\n\n"
        "## [일회성 자료]\n(URL·파일 경로·자유 텍스트 — 이번 단계 한정 참고 자료. 없으면 비워둔다.)\n"
    )


def _stage_folder(run: "str | Path", stage: str) -> Path | None:
    key = STAGE_FOLDER_KEY.get(stage)
    if key is None:
        return None
    import journey_folders  # sibling, 지연 임포트(순환 방지 — 이 리포 전역 관례)

    return journey_folders.folder_path(Path(run), key)


def overlay_path(run: "str | Path", stage: str) -> Path | None:
    folder = _stage_folder(run, stage)
    return None if folder is None else folder / OVERLAY_NAME


def ensure_overlay(run: "str | Path", stage: str) -> Path | None:
    """최초 1회 발급 — 이미 있으면 절대 손대지 않는다(사람 편집물 불가침).

    폴더가 아직 열리지 않았으면(그 단계에 도달 전) None(조용히 생략 — journey 폴더는
    "산출물이 생겼을 때" 열리는 선개방 원칙, journey_folders.py 상단 docstring 참고). 이 함수
    자신은 폴더를 새로 만들지 않는다(임의 문자열 run으로 호출돼도 부작용으로 디렉터리를
    만들면 안 된다 — 오직 다른 산출물이 이미 그 폴더를 열어둔 경우에만 파일을 얹는다).
    """
    path = overlay_path(run, stage)
    if path is None or not path.parent.is_dir():
        return None
    if path.is_file():
        return path
    path.write_text(_overlay_template(stage), encoding="utf-8")
    return path


_OVERLAY_SECTION_RE = None  # regex는 지연 컴파일(모듈 임포트 비용 최소화 — 이 리포 관례와 동형)


def read_overlay(run: "str | Path", stage: str) -> dict[str, list[str]] | None:
    """지식_지시.md의 3섹션을 파싱 — {"추가로 참고": [...], "제외": [...], "일회성 자료": [...]}.

    파일이 없으면 None. 섹션 안의 안내 문구(괄호로 시작하는 줄)는 내용으로 치지 않는다.
    """
    import re

    path = overlay_path(run, stage)
    if path is None or not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    sections = {"추가로 참고": [], "제외": [], "일회성 자료": []}
    pattern = re.compile(r"^##\s*\[(추가로 참고|제외|일회성 자료)\]\s*$", re.MULTILINE)
    matches = list(pattern.finditer(text))
    for i, m in enumerate(matches):
        name = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end]
        lines: list[str] = []
        for raw_line in body.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("(") and line.endswith(")"):
                continue  # 안내 문구(플레이스홀더) — 내용 아님
            line = line.lstrip("-•").strip()
            if line:
                lines.append(line)
        sections[name] = lines
    return sections


def overlay_prompt_block(run: "str | Path", stage: str) -> str:
    """핸드오프 프롬프트에 동봉할 '사용자 지식 지시' 절. 폴더가 없어도(발급 전) 안내는 낸다."""
    ensure_overlay(run, stage)
    sections = read_overlay(run, stage)
    lines = ["[사용자 지식 지시 — 사람 편집물, R6 오버레이 문법]"]
    path = overlay_path(run, stage)
    if sections is None:
        lines.append(f"(아직 지시 파일이 없다 — {path if path else '(이 단계는 journey 폴더가 없음)'})")
        return "\n".join(lines)
    any_content = any(sections.values())
    if not any_content:
        lines.append(f"(사용자 지시 없음 — 필요하면 {path}를 채워라. 기본대로 진행한다.)")
        return "\n".join(lines)
    if sections["추가로 참고"]:
        lines.append("- 추가로 참고: " + "; ".join(sections["추가로 참고"]))
    if sections["제외"]:
        lines.append("- 제외(참고하지 말 것): " + "; ".join(sections["제외"]))
    if sections["일회성 자료"]:
        lines.append("- 일회성 자료: " + "; ".join(sections["일회성 자료"]))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 핸드오프 프롬프트 조립 — pull 지시(config 표 소비) + 보고 의무(항상 동봉) + 오버레이
# ---------------------------------------------------------------------------

def pull_instruction_block(run: "str | Path", stage: str, profile: "str | None",
                            table: dict[str, Any] | None = None) -> "str | None":
    """능동 조회(pull) 지시 — KC 패킷 선례와 동형으로 express 프로파일은 생략(None).

    express가 생략하는 것은 "vault를 조회하라"는 넛지뿐이다 — 보고 의무(report_instruction_block)는
    별도로 항상 붙는다(안전장치①이 프로파일과 무관하게 걸려야 하므로).
    """
    if profile == "express":
        return None
    folders = pull_folders(stage, table)
    # 2026-07-23 사용자 확정: "읽기는 자유, 기록은 의무, 적용은 층 규율" — 층 프리픽스는 통제가
    # 아니라 효율적 1차 범위(추천)다. 원장(안전장치①)이 사용 흔적을 잡으므로 열람은 묶지 않는다.
    # 누수 차단의 본질(형태 산출물에 색 결정값 금지)은 산출물 게이트가 지킨다 — 읽기 제한 아님.
    lines = [f"[지식 pull — {STAGE_LABEL.get(stage, stage)} 단계, config 표 소비]",
             "공유뇌 지식을 능동 조회(obsidian_search)해 반영하라(자동 주입이 아니다 "
             "— 세션이 직접 검색해 당겨오는 pull 프로토콜, 경로 하드코딩 없음):"]
    if folders:
        lines.append("이 단계의 1차 검색 범위(여기서 시작하라):")
        for f in folders:
            lines.append(f"- `ref/{f}/`")
        lines.append("- **열람은 자유다**: 필요하면 vault 전체 검색·카드의 [[관련]] 링크 추적·"
                     "의미 검색까지 써도 된다. 단 **산출에 반영한 카드는 출처 폴더가 어디든 전부 "
                     "knowledge_used.cards에 기록하라** — 1차 범위 밖 카드는 원장이 표기해 감사된다. "
                     "적용 규율은 별개다(예: 형태 단계 산출물에 색 결정값 금지 — 읽는 건 자유, 새는 건 금지).")
    else:
        lines.append("(이 단계에는 설정된 pull 폴더가 없다 — config knowledge_stages 참고)")
    if web_allowed(stage, table):
        # 2026-07-23 사용자 확정: 웹 사용은 "사용자가 알아서 요청"이 아니라 시스템이 먼저 추천하는
        # 흐름이다 — 추천 → 동의 → 수행 → 기록(knowledge_used.web) → 관문 확인(안전장치②).
        lines.append("- 웹 검색이 허용된 단계다(config web_search=true). **무단 수행 금지** — "
                     "산출 품질에 도움이 될 실측·사례·최신 정보가 있으면 먼저 **사용자에게 웹 조사를 "
                     "추천하라**(무엇을 왜 찾을지 1줄). 동의 후 수행하고 knowledge_used.web에 "
                     "출처·용도를 기록하라(웹 사용 시 관문이 자동으로 서서 사람이 출처를 확인한다).")
    else:
        lines.append("- 이 단계는 웹 검색이 허용되지 않는다(config web_search=false) — "
                      "웹 자료를 썼다면 knowledge_used.web을 채우지 말고 vault 지식으로 대체하라.")
    overlay = overlay_prompt_block(run, stage)
    if overlay:
        lines.append("")
        lines.append(overlay)
    return "\n".join(lines)


def report_instruction_block(stage: str, table: dict[str, Any] | None = None) -> str:
    """보고 의무 — 안전장치①(2026-07-23 확정: 자동 모드에서도 보고 없이 진행 금지).

    profile과 무관하게 항상 동봉한다(express가 pull 넛지는 생략해도 보고 의무는 남는다).
    """
    allowed = web_allowed(stage, table)
    lines = [
        "[지식 사용 보고 — 안전장치① 완료 조건(2026-07-23 확정, 생략 금지)]",
        "이 산출 JSON에 `knowledge_used` 블록을 반드시 포함하라(최상위 키):",
        '  "knowledge_used": {"cards": ["실제 반영한 카드 슬러그", ...], '
        '"web": [{"url": "https://...", "purpose": "이 URL을 어디에 썼는지 한 줄"}, ...]}',
        "카드/웹 자료를 하나도 안 썼다면 **빈 배열로 명시**하라 — 필드 자체를 생략하면 "
        "수거 단계에서 검증 오류로 막힌다(\"조용한 생략\" 방지가 목적, 자동/수동 모드 무관).",
    ]
    if allowed:
        lines.append(
            "이 단계는 web_search=true다 — web을 채우면 다음 사람 관문이 조건부로 재정지된다"
            "(안전장치②, 출처 확인 목적). 정당한 사용이면 걱정 말고 정직하게 기록하라."
        )
    else:
        lines.append(
            "이 단계는 web_search=false다 — web 배열에 항목을 채우면 검증 오류로 수거가 막힌다"
            "(웹이 필요하면 vault 지식으로 대체하거나, 이 단계에서는 사용하지 마라)."
        )
    return "\n".join(lines)


def handoff_block(run: "str | Path", stage: str, profile: "str | None",
                   table: dict[str, Any] | None = None) -> str:
    """번들 프롬프트에 동봉할 최종 블록 — pull 지시(있으면) + 보고 의무(항상). 절대 빈 문자열이 아니다."""
    parts = []
    pull = pull_instruction_block(run, stage, profile, table)
    if pull:
        parts.append(pull)
    parts.append(report_instruction_block(stage, table))
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# 검증 — 안전장치①(보고 누락=차단) + web_search=false인데 web 항목(=차단)
# ---------------------------------------------------------------------------

def _is_web_item(item: Any) -> bool:
    return isinstance(item, dict) and isinstance(item.get("url"), str) and item.get("url").strip()


def validate_knowledge_used(doc: dict[str, Any], stage: str,
                             table: dict[str, Any] | None = None) -> tuple[list[str], list[str]]:
    """(errors, warnings). doc은 그 단계 산출 JSON 전체(knowledge_used를 최상위 키로 기대)."""
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(doc, dict):
        return [f"{stage}: 산출물이 객체가 아니다 — knowledge_used 검증 불가"], []
    ku = doc.get("knowledge_used")
    if ku is None:
        errors.append(
            f"{stage}: knowledge_used 블록 없음 — 안전장치①(2026-07-23 확정) 완료 조건 위반. "
            "cards/web을 빈 배열로라도 명시하라(조용한 생략 금지)."
        )
        return errors, warnings
    if not isinstance(ku, dict):
        errors.append(f"{stage}: knowledge_used가 객체가 아니다")
        return errors, warnings
    cards = ku.get("cards", [])
    if not isinstance(cards, list) or not all(isinstance(c, str) for c in cards):
        errors.append(f"{stage}: knowledge_used.cards는 문자열 배열이어야 한다")
        cards = []
    web = ku.get("web", [])
    if not isinstance(web, list):
        errors.append(f"{stage}: knowledge_used.web은 배열이어야 한다")
        web = []
    else:
        for i, item in enumerate(web):
            if not _is_web_item(item):
                errors.append(f"{stage}: knowledge_used.web[{i}]는 {{url, purpose}} 객체여야 한다")
    if web and not web_allowed(stage, table):
        errors.append(
            f"{stage}: web_search=false 단계인데 knowledge_used.web에 {len(web)}건 있다 — "
            "이 단계는 웹 사용이 config로 허용되지 않는다(config knowledge_stages 참고)."
        )
    if not cards and not web:
        warnings.append(f"{stage}: 지식 카드·웹 자료를 하나도 인용하지 않았다(빈 원장 — 정상일 수 있음).")
    return errors, warnings


# ---------------------------------------------------------------------------
# 원장 — run/knowledge_ledger.json(단계별 누적) + journey 폴더 지식_사용.md 파생 뷰
# ---------------------------------------------------------------------------

def ledger_path(run: "str | Path") -> Path:
    return Path(run) / LEDGER_NAME


def load_ledger(run: "str | Path") -> dict[str, Any]:
    p = ledger_path(run)
    if not p.is_file():
        return {"schema_version": SCHEMA_VERSION, "stages": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": SCHEMA_VERSION, "stages": {}}
    if not isinstance(data, dict) or not isinstance(data.get("stages"), dict):
        return {"schema_version": SCHEMA_VERSION, "stages": {}}
    return data


def record(run: "str | Path", stage: str, knowledge_used: dict[str, Any] | None, *,
           source_file: str | None = None) -> Path:
    """단계별 누적 기록(카드·웹 항목을 합집합으로 병합 — 재수거해도 이전 기록을 잃지 않는다).

    journey 단계 폴더가 열려 있으면 지식_사용.md 파생 뷰도 함께 갱신한다(부가 — 실패해도
    원장 기록 자체는 성공으로 취급, journey_folders 소비의 기존 관례와 동형).
    """
    run = Path(run)
    ku = knowledge_used if isinstance(knowledge_used, dict) else {}
    cards = [c for c in (ku.get("cards") or []) if isinstance(c, str) and c.strip()]
    web = [w for w in (ku.get("web") or []) if _is_web_item(w)]

    ledger = load_ledger(run)
    stages = ledger.setdefault("stages", {})
    entry = stages.setdefault(stage, {"cards": [], "web": [], "history": []})
    existing_cards = list(dict.fromkeys(entry.get("cards") or []))
    for c in cards:
        if c not in existing_cards:
            existing_cards.append(c)
    entry["cards"] = existing_cards
    # 2026-07-23 "읽기는 자유, 기록은 의무": 카드의 실제 출처 폴더를 vault에서 찾아 1차 범위
    # 안/밖을 표기한다 — 범위 밖 열람은 오류가 아니라 감사 대상(막지 않고 보이게 한다).
    origins = entry.setdefault("card_origins", {})
    for c in cards:
        if c not in origins:
            origins[c] = _resolve_card_origin(c, stage)
    existing_web = list(entry.get("web") or [])
    seen_urls = {w.get("url") for w in existing_web if isinstance(w, dict)}
    for w in web:
        if w.get("url") not in seen_urls:
            existing_web.append({"url": w.get("url"), "purpose": w.get("purpose") or ""})
            seen_urls.add(w.get("url"))
    entry["web"] = existing_web
    entry.setdefault("history", []).append({
        "at": dt.datetime.now().isoformat(timespec="seconds"),
        "cards_added": cards,
        "web_added": [w.get("url") for w in web],
        "source_file": source_file,
    })
    ledger["schema_version"] = SCHEMA_VERSION
    p = ledger_path(run)
    p.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        _sync_ledger_view(run, stage, ledger)
    except Exception:
        pass  # 파생 뷰는 부가 — 실패해도 원장 기록은 유효
    return p


def _vault_ref_dir() -> "Path | None":
    """vault의 ref/ 온디스크 루트 — design_knowledge.vault_dir(= <vault>/ref/디자인지식) 설정에서
    유도(경로 config 1점화 유지 — 새 키를 늘리지 않는다). 미설정·부재 시 None(우아 생략)."""
    try:
        cfg = json.loads(_pipeline_config_path().read_text(encoding="utf-8"))
        vd = ((cfg.get("design_knowledge") or {}).get("vault_dir") or "").strip()
        if not vd:
            return None
        ref_dir = Path(vd).expanduser().parent
        return ref_dir if ref_dir.is_dir() else None
    except Exception:
        return None


def _resolve_card_origin(name: str, stage: str) -> dict[str, Any]:
    """카드 이름 → vault ref/ 아래 실제 폴더 탐색 + 이 단계 1차 범위(in_scope) 판정.

    vault 부재·미발견은 오류가 아니다 — {"folder": None, "in_scope": None}으로 남겨 감사만 가능하게.
    """
    ref_dir = _vault_ref_dir()
    if ref_dir is None:
        return {"folder": None, "in_scope": None}
    safe = name.strip()
    if not safe or any(ch in safe for ch in ("/", "\\", "..")):
        return {"folder": None, "in_scope": None}
    try:
        hit = next(ref_dir.rglob(f"{safe}.md"), None)
    except OSError:
        hit = None
    if hit is None:
        return {"folder": None, "in_scope": None}
    folder = hit.parent.relative_to(ref_dir).as_posix()  # 예: 기획지식/메시지설계
    scope = pull_folders(stage)
    in_scope = any(folder == f or folder.startswith(f + "/") for f in scope)
    return {"folder": folder, "in_scope": in_scope}


def _knowledge_carried_summary(run: Path) -> list[str]:
    """δ패킷 합류(imagedeck_manifest.json의 slides[].knowledge_carried) — 있으면 정보용으로 붙인다."""
    manifest_path = run / "imagedeck_manifest.json"
    if not manifest_path.is_file():
        return []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    lines: list[str] = []
    for s in manifest.get("slides") or []:
        if not isinstance(s, dict):
            continue
        kc = s.get("knowledge_carried")
        if not kc:
            continue
        if kc.get("cards") or kc.get("images"):
            lines.append(f"- 장 {s.get('n')}: 카드 {kc.get('cards', 0)}건 · 이미지 {kc.get('images', 0)}건"
                         + (f" · 미발견 {', '.join(kc['missing'])}" if kc.get("missing") else ""))
    return lines


_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def _baked_knowledge_summary(run: Path) -> list[str]:
    """W32 마찰30: 덱에 반영된 지식의 절반(=코드에 구워진 원전 원칙)을 원장 뷰에 병기한다.

    조각(piece) 카탈로그의 `source`는 그 조각에 **이미 구워진** 원전 원칙이다 — 세션이 vault를
    조회한 적이 없으니 pull 이벤트가 없고, 따라서 종전 원장에는 한 줄도 안 남았다. 그런데 장표에는
    분명히 반영돼 있다(예: 목차 조각의 해소 근거 배지 슬롯 = [[목차는-상대의-두려움-목록이다]]).
    관문 검토자가 "이 표기 왜 붙었지"의 출처를 여기서 찾을 수 있어야 한다.

    **pull과 구분해 표기한다** — 채널 분리 자체는 설계다(원장 목적 = LLM의 조용한 생략 방지).
    여기 나오는 건 세션의 신고물이 아니라 사용 조각에서 **자동 도출**한 것이라 성격이 다르다.
    실패(덱·카탈로그 부재·형식 이상)는 조용히 빈 목록 — 파생 뷰는 부가다.
    """
    try:
        deck = json.loads((Path(run) / "deck.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    used: dict[str, int] = {}
    for s in deck.get("slides") or []:
        if not isinstance(s, dict):
            continue
        for slot in s.get("slots") or []:
            if isinstance(slot, dict) and slot.get("piece"):
                used[str(slot["piece"])] = used.get(str(slot["piece"]), 0) + 1
    if not used:
        return []   # 조각 조합 덱이 아니면(레거시 template 경로) 구운 지식 절도 없다
    pack = ((deck.get("meta") or {}).get("pack")) or "core"
    try:
        catalog = json.loads(
            (_repo_root() / "packs" / str(pack) / "pieces.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    by_id = {p.get("id"): p for p in (catalog.get("pieces") or []) if isinstance(p, dict)}
    lines: list[str] = []
    for pid, n in sorted(used.items(), key=lambda kv: (-kv[1], kv[0])):
        src = (by_id.get(pid) or {}).get("source")
        if not src:
            continue
        cards = _WIKILINK_RE.findall(str(src))
        tail = f" · 카드: {', '.join(cards)}" if cards else ""
        lines.append(f"- `{pid}` ({n}개 슬롯): {src}{tail}")
    return lines


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def render_ledger_view(run: Path, ledger: dict[str, Any]) -> str:
    lines = ["# 지식 사용 (원장 파생 뷰 — 자동 생성, 편집 금지)", "",
              "> 정본은 run 루트의 `knowledge_ledger.json`. 이 파일은 그 파생 뷰다.",
              ">",
              "> **읽는 법**: 아래 단계별 기록은 **세션이 공유뇌를 조회해 쓰고 신고한 것**(pull)이다."
              " ⚠️ 표시는 그 단계에 지정된 폴더 밖에서 가져왔다는 뜻인데 **열람은 자유이므로 잘못이 아니다**"
              "(감사 표시일 뿐 — 범위는 config에서 조정한다). ⛔ 표시는 vault에서 실물을 못 찾았다는 뜻이고"
              " **지식으로 인정하지 않는다**(파일이 없는 유령노트 의심 — vault를 고쳐야 한다)."
              " 맨 아래 '구운 지식' 절이 있으면 그건 신고물이 아니라 **조각에 이미 구워진 원칙**을 자동으로"
              " 도출한 것이다. 상세 = `MANUAL.md` §9.9.1."]
    stages = ledger.get("stages") or {}
    if not stages:
        # W32 마찰30: 여기서 반환하지 않는다 — pull 기록이 0건일 때야말로 '구운 지식'이 유일한
        # 반영 흔적이라, 조기 반환하면 가장 필요한 자리에서 정보가 사라진다.
        lines.append("\n(pull 기록 없음)")
    for stage in STAGES:
        entry = stages.get(stage)
        if not entry:
            continue
        lines.append(f"\n## {STAGE_LABEL.get(stage, stage)} (`{stage}`)")
        cards = entry.get("cards") or []
        web = entry.get("web") or []
        lines.append(f"- 카드 {len(cards)}건 · 웹 {len(web)}건")
        origins = entry.get("card_origins") or {}
        for c in cards:
            o = origins.get(c) or {}
            if o.get("in_scope") is False:
                mark = f" ⚠️ 1차 범위 밖(출처: {o.get('folder')})"
            elif o.get("folder"):
                mark = f" ({o.get('folder')})"
            else:
                # W32 마찰30: 강등 — vault에 실물이 없으면 지식으로 인정하지 않는다(유령노트 등).
                mark = " ⛔ 강등: vault 실물 미확인(파일 없음 — 인덱스에만 있는 유령노트 의심)"
            lines.append(f"  - 카드: {c}{mark}")
        for w in web:
            purpose = f" — {w.get('purpose')}" if w.get("purpose") else ""
            lines.append(f"  - 웹: {w.get('url')}{purpose}")
    carried = _knowledge_carried_summary(run)
    if carried:
        lines.append("\n## δ 운반분 (imagedeck_manifest.json knowledge_carried 합류)")
        lines.extend(carried)
    baked = _baked_knowledge_summary(run)
    if baked:
        lines.append("\n## 구운 지식 (코드 상수 — pull 아님 · 자동 도출)")
        lines.append("> 위 단계별 기록은 **세션이 조회해 쓴 것**(pull, 자기 신고)이고, 아래는 이 덱이 쓴 "
                     "조각(piece)에 **이미 구워져 있는** 원전 원칙이다 — 조회 이벤트가 없어 pull 채널로는 "
                     "안 잡히지만 장표에는 반영돼 있다. 사용 조각에서 자동 도출한다(신고물 아님).")
        lines.extend(baked)
    return "\n".join(lines) + "\n"


def _sync_ledger_view(run: Path, stage: str, ledger: dict[str, Any]) -> None:
    folder = _stage_folder(run, stage)
    if folder is None or not folder.is_dir():
        return
    path = folder / LEDGER_VIEW_NAME
    path.write_text(render_ledger_view(run, ledger), encoding="utf-8")


def stage_counts(run: "str | Path", stage: str) -> dict[str, int]:
    ledger = load_ledger(run)
    entry = (ledger.get("stages") or {}).get(stage) or {}
    return {"cards": len(entry.get("cards") or []), "web": len(entry.get("web") or [])}


# ---------------------------------------------------------------------------
# 안전장치② — gates.py가 소비하는 웹 사용 신호(조건부 승격)
# ---------------------------------------------------------------------------

def web_signal_for_gate(run: "str | Path", gate_id: str) -> dict[str, Any]:
    """gate_id를 지키는 지식 단계(들)의 web 사용량을 합산 — gates.py.signal()이 병합해 소비한다.

    ledger 파일 자체가 없으면 available=False("모르는 걸 아는 척 안 함" — gates.py 기존 관례).
    """
    run = Path(run)
    stages = [s for s, g in STAGE_GATE.items() if g == gate_id]
    if not stages or not ledger_path(run).is_file():
        return {"available": False, "bad": False, "reasons": [], "detail": {}}
    ledger = load_ledger(run)
    total = 0
    parts: list[str] = []
    for s in stages:
        n = len((ledger.get("stages") or {}).get(s, {}).get("web") or [])
        if n:
            total += n
            parts.append(f"{STAGE_LABEL.get(s, s)}:{n}건")
    reasons = []
    if total:
        reasons.append("외부 웹 자원 사용 — 출처 확인 필요 (" + ", ".join(parts) + ")")
    return {"available": True, "bad": bool(total), "reasons": reasons,
            "detail": {"web_total": total, "stages": parts}}


# ---------------------------------------------------------------------------
# 안전장치③ — status/go 표면화 1줄
# ---------------------------------------------------------------------------

def surface_lines(run: "str | Path") -> list[str]:
    """각 단계 "지식: 카드 N · 웹 M건" — 기록이 있는 단계만(없는 단계는 침묵, 강제 아님)."""
    ledger = load_ledger(run)
    stages = ledger.get("stages") or {}
    lines: list[str] = []
    for stage in STAGES:
        entry = stages.get(stage)
        if not entry:
            continue
        cards = len(entry.get("cards") or [])
        web = len(entry.get("web") or [])
        line = f"- {STAGE_LABEL.get(stage, stage)}: 지식: 카드 {cards} · 웹 {web}건"
        # W32 마찰30(2026-08-02 사용자 확정 "일단 강등"): vault에서 실물을 못 찾은 카드는 지식으로
        # 인정하지 않는다 — 조용한 "(출처 미확인)" 표기에 그치지 않고 카운트와 함께 표면화한다.
        # 실측 원인 1위는 유령노트(Obsidian 인덱스에는 있고 디스크에 파일이 없음)다.
        unverified = _unverified_cards(entry)
        if unverified:
            line += f" · ⛔강등 {len(unverified)}건(vault 실물 미확인: {', '.join(unverified)})"
        lines.append(line)
    return lines


def _unverified_cards(entry: dict[str, Any]) -> list[str]:
    """원장 단계 항목에서 출처를 디스크로 확인하지 못한 카드 목록(마찰30 강등 대상)."""
    origins = entry.get("card_origins") or {}
    return [c for c in (entry.get("cards") or []) if not (origins.get(c) or {}).get("folder")]


def summary_line(run: "str | Path") -> "str | None":
    lines = surface_lines(run)
    return None if not lines else "\n".join(lines)
