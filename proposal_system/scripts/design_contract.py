"""W31 R-B(R2·R5) — run별 디자인 계약 `run/design_contract.json`.

CONTEXT/JOURNEY.md 정본(2026-07-21 확정) 근거:

  - **R2. run별 디자인 계약 동결**: B1(테마 확정)에서 [전역 스킨+design_brief+run 조정]을 병합해
    `design_contract.json`(run 루트의 flat 정본)을 만든다. bundle/compose가 소비하는 유일한
    디자인 정본(lecture `quartz_infographic.json` 역할의 run판).
  - **R5. 스킨 2계약 분리 + 중립 템플릿**: ①`chrome_contract`(HTML/pptx 조립 전용: canvas/export·
    chrome·slide_classes·variants + 공용 토큰 colors·typography) / `image_contract`(이미지 생성
    프롬프트 주입 전용: colors·color_roles·typography·layout·components·content_limits·
    overflow_policy·generation_rules·contract) — **canvas/chrome은 image_contract에서 뺀다**
    (종전 `imagedeck._skin_summary`가 chrome 정보까지 프롬프트에 얹던 혼입의 해소). ②전역
    `skins/*.json`은 그대로 두고(창고 보관 스킨), 결정값 없는 `skins/_neutral.json`을 신설해
    "차용 없음"의 초안으로 쓴다.
  - **용어 정의**: design_contract=run별 1회성 정본. skin=졸업본(창고, 자동 적용 안 함).
    차용=design_brief.skin.value가 있으면 그 스킨을 초안으로 삼는 것. 없으면 중립 템플릿.
    ⚠️ `skin.value`(이 계약이 읽는 차용 소스)와 `skin.skins`(W22, render/htmlgen 스킨 체인)는
    **다른 키다** — 서로 대체하지 않는다. 자세한 역할 차이는 design_brief.py의 skin 필드
    주석 참고(마찰14, 2026-07-22).
    ⚠️ 이행 과제: W29 "기본 스킨=inkline" 자동 폴백을 폐기한다 — inkline도 이제 차용 가능한
    보관 스킨 중 하나일 뿐(자동 승격 없음). 호출부(imagedeck 커맨드)가 이 폐기를 반영한다.
  - **마찰15 수리(2026-07-22)**: 차용은 **중립 위 딥머지**다(대체가 아니다) — `research --apply`가
    만드는 부분 스킨(colors/brand/_meta뿐인 기관 스킨 등)을 차용해도 canvas·export·typography
    등 구조 키는 중립에서 상속돼 계약이 항상 완전한 구조를 갖춘다(`build()`·`validate_structure()`
    참고). 이전에는 부분 스킨을 통째로 대체 삼아 구조 키가 통째로 사라졌고, 그 결과가
    `imagedeck.canvas_dims`의 처리 안 된 traceback이었다(CONTEXT/REHEARSAL_FRICTIONS_W31.md #15).

결정론·0토큰 — 이 모듈은 LLM을 호출하지 않는다(design_brief.py·pipeline_state.py와 같은 계열).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
CONTRACT_NAME = "design_contract.json"
NEUTRAL_SKIN_NAME = "_neutral"

# 조립(chrome) 전용 — 캔버스·크롬 밴드·장 클래스·구간 변형 + 조립이 필요로 하는 공용 토큰
# (colors·typography는 헤더/푸터 텍스트·프레임 색 등 크롬 렌더링에도 쓰이므로 함께 담는다 —
# "혼입"은 chrome 구조 정보가 이미지 프롬프트로 새는 것이지, 색·폰트 공용 토큰의 중복이 아니다).
# decor_slots(DF2, 2026-07-24): 배경 외 장식 자산 슬롯(코너 장식 등) 계약 — HTML/PPTX 조립
# 전용이라 chrome 쪽이다(이미지 생성 프롬프트에 주입되면 안 됨 — IMAGE_KEYS에 넣지 말 것).
CHROME_KEYS = ("canvas", "export", "chrome", "slide_classes", "variants", "colors", "typography",
               "decor_slots")

# 이미지 생성 프롬프트 주입 전용 — 종전 imagedeck._skin_summary와 동일 목적의 키 집합에서
# canvas/chrome을 뺐다(R5 혼입 제거). 생성 캔버스 px는 프롬프트 상단에 이미 명시되므로
# (bundle이 별도로 gen_w/gen_h를 계산해 넣는다) 크롬 구조를 다시 요약해 줄 필요가 없다.
IMAGE_KEYS = ("colors", "color_roles", "typography", "layout", "components",
              "content_limits", "overflow_policy", "generation_rules", "contract")

# 미래 확장용 run 조정 채널(현재는 image 라우트 전용 override 채널이 없다 — 있으면 활용,
# 없으면 조용히 건너뛴다. 설계 결정 "run 조정(기존 override 채널 있으면 활용)"의 자리만 잡아둔다).
RUN_OVERRIDES_NAME = "design_contract_overrides.json"

# 마찰15 ⓒ: 계약 동결 시 검증할 필수 구조 키 — imagedeck.canvas_dims(D12)가 요구하는 것과 동일.
# 중립 템플릿(_neutral.json)은 항상 이 키들을 갖추고 있으므로, 딱히 이 검증에 걸리는 경우는
# "중립 병합이 누락된 구 계약"(마찰15 이전에 만들어진 대체-방식 계약)뿐이어야 한다.
REQUIRED_STRUCTURE_KEYS = ("canvas", "export")


class DesignContractError(Exception):
    """계약 동결·검증 실패 — 사람 말 오류(마찰15 ⓒ, traceback 대신 원인·조치 안내)."""


def path(run: Path) -> Path:
    return Path(run) / CONTRACT_NAME


def exists(run: Path) -> bool:
    return path(run).is_file()


def load(run: Path) -> dict[str, Any] | None:
    p = path(Path(run))
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def save(run: Path, contract: dict[str, Any]) -> Path:
    p = path(Path(run))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _load_json(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))


def _split(skin: dict[str, Any]) -> tuple[dict, dict]:
    chrome = {k: skin[k] for k in CHROME_KEYS if k in skin}
    image = {k: skin[k] for k in IMAGE_KEYS if k in skin}
    return chrome, image


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """재귀 병합(마찰15) — dict는 키별로 재귀 병합, 리스트·스칼라는 `overlay`(차용) 쪽이 우선.

    `base`를 직접 변형하지 않는다(새 dict 반환) — 호출부가 이미 깊은 복사한 중립 초안을
    넘기더라도 안전하게 중첩 병합할 수 있게 한다.
    """
    out = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def validate_structure(contract: dict[str, Any]) -> None:
    """계약 동결 시 필수 구조 키 검증(마찰15 ⓒ) — 부재 시 traceback 대신 사람 말 오류로 막는다.

    중립 템플릿을 항상 밑그림으로 삼는 `build()`를 거쳤다면 이 키들은 절대 빠질 수 없다 —
    걸린다면 `run/design_contract_overrides.json`이 구조 키를 지웠거나, 이 검증 이전에
    (중립 병합 없이) 만들어진 낡은 계약 파일을 그대로 불러온 경우다.
    """
    chrome = contract.get("chrome_contract") or {}
    missing = [k for k in REQUIRED_STRUCTURE_KEYS if not chrome.get(k)]
    if missing:
        raise DesignContractError(
            f"계약(design_contract.json)에 {'/'.join(missing)}가 없다 — 중립 병합이 누락된 "
            "구 계약인지 확인하라. 조치: design_contract.json을 지우고 `go`로 재생성하거나, "
            "`go --refreeze-contract`로 재동결하라(마찰15)."
        )


def resolve_source(brief: dict[str, Any] | None) -> str:
    """design_brief.skin.value 재해석(용어 정의: 차용 신호). 값 없으면 "neutral"(중립 템플릿).

    ⚠️ 여기가 W29 "기본값=inkline" 자동 폴백을 대체하는 지점이다 — 값이 없다고 inkline을
    승격하지 않는다. inkline은 값으로 명시했을 때만(사용자가 그 스킨을 차용하기로 결정했을
    때만) 초안이 된다.
    """
    value = ((brief or {}).get("skin") or {}).get("value")
    return str(value).strip() if value else "neutral"


def _run_overrides(run: Path) -> dict[str, Any]:
    p = Path(run) / RUN_OVERRIDES_NAME
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def build(run: Path, *, brief: dict[str, Any] | None, skins_dir: Path) -> dict[str, Any]:
    """[중립 템플릿 초안] <- [차용 스킨 딥머지] <- design_brief 결정(차용 소스) <- run 조정,
    병합해 계약 동결(마찰15 수리 — 차용은 항상 중립 위 병합이지 대체가 아니다).

    - **밑그림은 항상 중립**: `skins/_neutral.json`을 먼저 초안으로 깐다(canvas·export·
      typography 등 구조 키의 보증처).
    - **차용**: `brief.skin.value`가 실재하는 `skins/<value>.json`을 가리키면 그 내용을 중립
      위에 **재귀 딥머지**한다(dict는 키별로 재귀, 리스트·스칼라는 차용 쪽 우선) — `_deep_merge`
      참고. 완전 스킨(inkline 등)을 얹으면 사실상 결과가 완전 스킨과 동일(중립에만 있는 키가
      있다면 그 키만 추가로 상속 — 무해). 부분 스킨(research --apply의 colors/brand뿐인 기관
      스킨)은 있는 키만 덮고 나머지 구조는 중립에서 상속되어 완전한 계약이 된다.
      inkline도 차용 대상 중 하나일 뿐 — 자동 폴백 아님.
    - **중립**: 차용이 없거나(값 없음) 대상 파일이 없으면 딥머지 없이 중립 그대로가 초안이다.
    - **run 조정**: `run/design_contract_overrides.json`이 있으면 최후승으로 얕게 병합한다(현재
      image 라우트에 이 채널을 쓰는 공정은 없다 — 있으면 반영, 없으면 조용히 생략).
    - **구조 검증**: 병합 결과가 여전히 필수 구조 키(canvas/export)를 갖추지 못하면
      `DesignContractError`로 동결을 막는다(`validate_structure` — 마찰15 ⓒ).
    """
    run = Path(run)
    brief = brief or {}
    source = resolve_source(brief)

    neutral_path = Path(skins_dir) / f"{NEUTRAL_SKIN_NAME}.json"
    neutral = _load_json(neutral_path)
    # 깊은 복사(밑그림 오염 방지 — neutral은 skins/ 창고 파일, 절대 되돌아가 변형하지 않는다).
    merged: dict[str, Any] = json.loads(json.dumps(neutral, ensure_ascii=False))

    borrowed_path: Path | None = None
    borrowed: dict[str, Any] = {}
    if source != "neutral":
        cand = Path(skins_dir) / f"{source}.json"
        if cand.is_file():
            borrowed_path = cand
    if borrowed_path is not None:
        borrowed = _load_json(borrowed_path)
        merged = _deep_merge(merged, borrowed)
    else:
        source = "neutral"
    draft_path = borrowed_path or neutral_path

    # W31 마찰19: 완전 스킨(자기완결 스타일 선언, _meta.self_contained=true) 차용이면 그 스킨의
    # 세부 스펙을 프롬프트에 그대로 유지한다("제약 수준 = 차용 수준" — 사용자 확정). 중립이거나
    # 부분 스킨(research --apply의 colors/brand뿐인 기관 스킨 등, self_contained=false/누락)이면
    # imagedeck이 축소판(크롬 이웃 브리핑 + 자유) 프롬프트를 쓴다 — is_full_skin() 참고.
    full_skin = bool(borrowed_path is not None and (borrowed.get("_meta") or {}).get("self_contained"))

    # run 조정(있으면 최후승 — 얕은 병합, 현재는 대개 빈 채널).
    overrides = _run_overrides(run)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value

    chrome_contract, image_contract = _split(merged)

    digest = hashlib.sha256(
        json.dumps(brief, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:12]

    contract = {
        "schema_version": SCHEMA_VERSION,
        "meta": {
            "source": source,
            "frozen_at": _now(),
            "brief_digest": digest,
            "draft_path": str(draft_path),
            "neutral_path": str(neutral_path),
            "merged_with_neutral": borrowed_path is not None,
            "run_overrides_applied": bool(overrides),
            "full_skin": full_skin,
        },
        "chrome_contract": chrome_contract,
        "image_contract": image_contract,
    }
    validate_structure(contract)
    return contract


def is_full_skin(contract: dict[str, Any] | None) -> bool:
    """W31 마찰19: 완전 스킨(자기완결 스타일 선언) 차용이면 True.

    True면 imagedeck이 그 스킨의 세부 스펙(색·타이포·카드·금지 스타일 전량)을 프롬프트에 그대로
    주입한다(종전 동작 불변 — "제약 수준 = 차용 수준", 사용자 확정 2026-07-21). False(중립 또는
    부분 스킨)면 축소판(크롬 이웃 브리핑 + 브랜드 고지 + 자유 명시 + 하드 제약 축소판)을 쓴다.
    """
    if not contract:
        return False
    return bool((contract.get("meta") or {}).get("full_skin"))


def summary(contract: dict[str, Any]) -> str:
    """콘솔 1줄 요약(cp949-안전 문자만 — em-dash 금지, 프로젝트 콘솔 규율)."""
    meta = contract.get("meta") or {}
    chrome = contract.get("chrome_contract") or {}
    image = contract.get("image_contract") or {}
    colors = chrome.get("colors") or {}
    typo = (chrome.get("typography") or {}).get("family")
    spec_mode = "완전 스킨(세부 스펙 유지)" if meta.get("full_skin") else "중립/부분(프롬프트 축소판)"
    line = (f"출처={meta.get('source')} 폰트={typo or '(없음)'} "
            f"accent={colors.get('accent') or '(없음)'} "
            f"chrome_contract 키={list(chrome.keys())} image_contract 키={list(image.keys())} "
            f"프롬프트={spec_mode}")
    # W31 R10(β2): 마스터 시안(imagedeck --master-apply)이 기록한 룩·밀도 — 있을 때만 덧붙인다.
    art = contract.get("art_direction") or {}
    if art.get("look") or contract.get("density"):
        line += f" | art_direction={'있음' if art.get('look') else '(없음)'} density={contract.get('density') or '(없음)'}"
    return line


def describe_for_view(contract: dict[str, Any]) -> dict[str, Any]:
    """journey_folders(07_테마확정 파생 뷰)가 읽기 좋은 형태로 계약을 요약."""
    meta = contract.get("meta") or {}
    chrome = contract.get("chrome_contract") or {}
    image = contract.get("image_contract") or {}
    colors = chrome.get("colors") or {}
    ch = chrome.get("chrome") or {}
    art = contract.get("art_direction") or {}
    return {
        "source": meta.get("source"),
        "frozen_at": meta.get("frozen_at"),
        "font_family": (chrome.get("typography") or {}).get("family"),
        "primary_color": colors.get("ink") or colors.get("primary"),
        "accent_color": colors.get("accent"),
        "header_h": ch.get("header_h"),
        "footer_h": ch.get("footer_h"),
        "chrome_contract_keys": list(chrome.keys()),
        "image_contract_keys": list(image.keys()),
        "full_skin": bool(meta.get("full_skin")),
        # W31 R10(β2): 마스터 시안 확정본 — art_direction.look/density(imagedeck --master-apply).
        "art_direction_look": art.get("look"),
        "density": contract.get("density"),
    }
