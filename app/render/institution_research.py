# -*- coding: utf-8 -*-
"""기관 공개 조사(문서 밖 근거) → 직인용 훅 + 브랜드 스킨 경로 (W26, 목표조정 8·9).

공정 위치: 분석 단계([1])의 선택 서브스텝 — RFP 첨부 파싱과 별개로, 발주기관 공식 홈페이지·
보도·공시 같은 "문서 밖" 자료를 조사한다(P1.3: 발주처의 숨은 관심사는 문서 밖에서 수집해
도입에 직인용). 같은 조사 1소스에서 두 가지가 함께 나온다:

  (a) 내용 — 미션·건학이념·특성화·최근 맥락 + 직인용 가능한 문장(content_hooks).
      message_map/storyline 핸드오프에 요약이 동봉되어 도입 직인용·홍보 축 정합에 쓰인다.
  (b) 형태 — 브랜드 토큰(대표색 hex·서체·로고/공식 사진 — 다운로드 허용, W27 D5)을
      렌더러 스킨으로 변환(to_skin).

이 모듈은 app/render/wireframe.py·design_spec.py의 자매다 — 같은 문법(오류=계약 위반·SSOT
안전 / 경고=표면화, 지어내지 말고 비워라)을 기관 조사 축에 적용한다. 웹 조사 자체는
LLM/사람 몫이다 — 이 모듈은 프롬프트 번들과 수거·검증·스킨 생성만(결정론·0토큰) 한다.

institution_research.json 스키마(run 루트, 조사자 LLM/사람 작성):
    {"schema_version": 1, "institution": "...", "researched_by": "조사자 식별",
     "sources": ["https://..."],
     "identity": {"mission": "...", "founding_philosophy": "...",
                  "specialization": [...], "recent_context": [...]},
     "content_hooks": [{"claim": "...", "use_in": "도입 직인용|홍보 축 정합|기대효과",
                        "source": "https://..."}],
     "brand_tokens": {"colors": {"primary": "#004388", "accent": null},
                      "fonts": {"family": null},
                      "logo": {"path": null, "note": "..."}}}
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
RESEARCH_NAME = "institution_research.json"

_HEX_RE = re.compile(r"^#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})$")

USE_IN_VOCAB = ("도입 직인용", "홍보 축 정합", "기대효과")


# --- run 산출물 모듈 관례(design_spec.py 패턴) -------------------------------

def research_path(run: "str | Path") -> Path:
    return Path(run) / RESEARCH_NAME


def exists(run: "str | Path") -> bool:
    return research_path(run).is_file()


def load(run: "str | Path") -> "dict | None":
    p = research_path(run)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save(run: "str | Path", res: dict) -> Path:
    p = research_path(run)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


# --- 검증 --------------------------------------------------------------------

def validate(res: dict) -> dict:
    """계약 검증 → {"errors": [...], "warnings": [...]}.

    오류=계약 위반(적용 중단·SSOT 안전) / 경고=표면화 대상(지어내지 말고 비워라, R4 대칭).
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(res, dict):
        return {"errors": ["institution_research.json이 객체가 아님"], "warnings": []}

    institution = res.get("institution")
    if not institution or not str(institution).strip():
        errors.append("institution 없음 — 출처 없는 조사는 직인용 불가")

    sources = res.get("sources")
    if not isinstance(sources, list) or not sources:
        errors.append("sources 없음 — 출처 없는 조사는 직인용 불가")

    for i, hook in enumerate(res.get("content_hooks") or []):
        if not isinstance(hook, dict):
            continue
        if not hook.get("source"):
            claim = hook.get("claim") or f"#{i}"
            warnings.append(f"content_hooks[{claim}]: source 없음 — 출처요망(R4 대칭)")

    primary = ((res.get("brand_tokens") or {}).get("colors") or {}).get("primary")
    if primary and not _HEX_RE.match(str(primary)):
        errors.append(f"brand_tokens.colors.primary '{primary}' — hex 형식(#RGB/#RRGGBB)이 아님")

    return {"errors": errors, "warnings": warnings}


# --- 스킨 변환(결정론) --------------------------------------------------------

def to_skin(res: dict, skin_id: str) -> dict:
    """brand_tokens → 렌더러 어휘 스킨 dict.

    colors.primary → colors.navy (htmlgen._base_css가 navy 키를 --primary로 승격하는
    규약 — 팩 무관 동작, "navy 키 우선, 없으면 첫 색"). colors.accent → colors.orange
    (같은 규약: orange 키 우선, 없으면 primary).
    """
    brand = res.get("brand_tokens") or {}
    colors_in = brand.get("colors") or {}
    colors: dict[str, str] = {}
    primary = colors_in.get("primary")
    if primary:
        colors["navy"] = str(primary).lstrip("#")
    accent = colors_in.get("accent")
    if accent:
        colors["orange"] = str(accent).lstrip("#")

    skin: dict[str, Any] = {}
    if colors:
        skin["colors"] = colors

    family = (brand.get("fonts") or {}).get("family")
    if family:
        skin["fonts"] = {"family": family}

    institution = res.get("institution")
    logo_path = (brand.get("logo") or {}).get("path")
    if institution or logo_path:
        skin["brand"] = {
            "client_name": institution,
            "client_logo": logo_path or None,
            "placement": {"client": "cover", "proposer": "all"},
        }

    sources = res.get("sources") or []
    skin["_meta"] = {
        "name": skin_id,
        "provenance": sources[0] if sources else None,
        "derivation": "institution_research --apply (W26) — brand_tokens.colors.primary/accent → "
                      "colors.navy/orange(htmlgen._base_css 네이비/오렌지 승격 규약)",
        "self_contained": False,
    }
    return skin


# --- 프롬프트에 동봉할 요약(다른 번들 동봉용) --------------------------------

def render_for_prompt(res: dict) -> str:
    """message_map/storyline 등 다른 핸드오프 번들에 동봉할 직인용 훅 요약."""
    lines = [f"- 기관: {res.get('institution')}"]
    identity = res.get("identity") or {}
    if identity.get("mission"):
        lines.append(f"- 미션: {identity['mission']}")
    if identity.get("founding_philosophy"):
        lines.append(f"- 건학이념/설립정신: {identity['founding_philosophy']}")
    if identity.get("specialization"):
        lines.append(f"- 특성화: {', '.join(identity['specialization'])}")
    if identity.get("recent_context"):
        lines.append(f"- 최근 맥락: {', '.join(identity['recent_context'])}")
    hooks = res.get("content_hooks") or []
    if hooks:
        lines.append("- 직인용 후보(기관의 실제 표현 — 창작 금지, 그대로 인용):")
        for h in hooks:
            if not isinstance(h, dict):
                continue
            src = f" [출처: {h.get('source')}]" if h.get("source") else " [출처요망]"
            lines.append(f"  - ({h.get('use_in') or '?'}) \"{h.get('claim')}\"{src}")
    return "\n".join(lines)


# --- 조사자(LLM) 프롬프트 번들 ------------------------------------------------

_SCHEMA_EXAMPLE = """{
  "schema_version": 1,
  "institution": "기관명",
  "researched_by": "조사자 식별(모델/사람)을 여기에",
  "sources": ["https://..."],
  "identity": {
    "mission": "...", "founding_philosophy": "...",
    "specialization": ["..."], "recent_context": ["..."]
  },
  "content_hooks": [
    {"claim": "직인용 가능한 한 줄(기관의 언어 그대로)", "use_in": "도입 직인용", "source": "https://..."}
  ],
  "brand_tokens": {
    "colors": {"primary": "#004388", "accent": null},
    "fonts": {"family": null},
    "logo": {"path": null,
             "note": "다운로드해 run/assets/client/에 저장 가능(W27 D5: 발주처 자산 사용은 표준 관행 — 자동 생성은 여전히 금지). 다운로드 시 출처 URL을 함께 기록"}
  },
  "knowledge_used": {"cards": ["반영한 지식 카드 슬러그(vault pull, 있으면)", "..."],
                      "web": [{"url": "https://...", "purpose": "용도 한 줄"}]}
}"""


def build_prompt(
    run: "str | Path", *, institution: "str | None" = None, analysis_md: "str | None" = None,
    profile: "str | None" = None,
) -> str:
    """조사자(LLM)에게 줄 자기완결 프롬프트.

    `profile`(ε패킷, 2026-07-23): knowledge_ledger의 pull 지시+보고 의무(안전장치①)를 말미에
    동봉한다. `knowledge_used.web`은 이 조사 자체의 출처(`sources`/`content_hooks[].source` —
    기관 사실 인용)와는 다른 개념이다 — vault 지식 카드 pull과 함께 참고한 **일반** 웹 자료
    (예: 업계 관행·경쟁 제안 사례)만 여기 적으라고 프롬프트에서 구분해 안내한다.
    """
    run = Path(run)
    parts = [
        "# 발주기관 공개 조사 (문서 밖 근거 · P1.3 · W26)",
        "",
        "너는 **발주기관 공개 조사자**다. RFP 첨부 문서 안이 아니라 밖에서 — 공식 홈페이지·",
        "보도자료·공시·공고 등 공개 정보에서 기관의 정체성과 브랜드를 수집한다.",
        "",
        "## 조사 항목",
        "1. 미션 / 건학이념·설립정신 / 특성화 / 최근 맥락(뉴스·계획)",
        "2. 직인용 후보 — 기관이 스스로 쓰는 문장(P1.3: 발주처의 숨은 관심사는 문서 밖에서",
        "   수집해 도입에 직인용한다). 창작 금지 — 기관의 실제 표현을 그대로 옮겨라.",
        "3. 브랜드 토큰 — 대표색(hex) · 서체 · 로고·공식 사진은 다운로드해 run/assets/client/에",
        "   저장 가능(발주처 제출물에 발주처 자산 사용은 표준 관행 — W27 D5). 출처 URL을 함께 기록하라.",
        "",
        "## 조사 방법 — 소스 계단 (봇 차단 전제 · W31 리허설 반영)",
        "대부분의 기관 사이트는 서버형 수집(WebFetch 등)을 차단한다. 차단을 예외가 아니라",
        "기본 환경으로 두고, 아래 계단을 위에서부터 밟아라(같은 계단 재시도 반복 금지 — 1회",
        "시도 후 다음 계단으로):",
        "1. **브라우저 열람(기본)** — 브라우저 도구(브라우저 페인·사용자 크롬)로 기관 홈페이지를",
        "   직접 열어 내용·대표색·로고를 확인하라. 실제 브라우저의 정상 열람이라 대부분 열린다.",
        "2. 검색엔진 스니펫 · 보도자료 · 뉴스 기사.",
        "3. 공공 공시(알리오·나라장터 기관정보 등).",
        "4. **RFP 첨부 문서 안의 기관 CI**(공고문·과업지시서의 로고·색 — 차단이 아예 없는 소스).",
        "5. 캡차·사람 확인 화면이 뜨면 그 화면 처리만 사용자에게 요청하라(협업 단계).",
        "   캡차 자동 풀기·봇 감지 회피는 금지 — 정상 열람과 사람 협업으로만 간다.",
        "끝까지 못 구한 항목만 비워둔다 — 조사 공란은 정상이며 여정을 멈추지 않는다(중립 진행).",
        "",
        "## 규칙",
        "1. 모든 항목에 출처 URL을 남겨라 — 추측 금지, 못 찾으면 비워두라(지어내지 말 것).",
        "2. 직인용(content_hooks) claim은 기관의 실제 표현을 유지한다(창작·의역 금지).",
        "3. 로고·공식 사진은 다운로드해 run/assets/client/에 저장할 수 있다(W27 D5: 저작권",
        "   동기 완화 — 정직성 동기의 금지와는 별개 체제다). 다운로드하면 출처 URL을",
        "   brand_tokens.logo.note에 함께 기록하라. 자동 생성은 여전히 금지(실자산만).",
        "4. 출력은 아래 스키마의 JSON 하나뿐 — 설명·코드펜스 밖 텍스트 금지. "
        f"run 루트({run})에 institution_research.json으로 저장한다.",
        "",
        "## 출력 스키마 (institution_research.json)",
        "```json", _SCHEMA_EXAMPLE, "```",
        "",
        "## 입력 컨텍스트",
    ]
    if institution:
        parts.append(f"- 기관명(지정): {institution}")
    else:
        parts.append("- 기관명이 지정되지 않았다 — 아래 분석카드 발췌에서 발주처를 확인하라.")
    if analysis_md:
        parts.append("")
        parts.append("### 분석카드 발췌(앞 2000자)")
        parts.append(analysis_md[:2000])
    import sys as _sys
    scripts_dir = Path(__file__).resolve().parents[2] / "proposal_system" / "scripts"
    if str(scripts_dir) not in _sys.path:
        _sys.path.insert(0, str(scripts_dir))
    import knowledge_ledger  # sibling of proposal_pipeline — 지연 임포트(순환 방지)
    parts.append("")
    parts.append(knowledge_ledger.handoff_block(run, "research", profile))
    parts.append(
        "\n※ 위 knowledge_used.web은 이 조사의 sources/content_hooks[].source(기관 사실 출처)와 "
        "다르다 — vault 지식 카드와 함께 참고한 **일반** 웹 자료(업계 관행 등)만 여기 적어라."
    )
    return "\n".join(parts)
