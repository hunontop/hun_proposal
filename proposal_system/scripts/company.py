# -*- coding: utf-8 -*-
"""제안사(자사) 정보 창고 (W31 리허설 마찰6, 2026-07-21 사용자 확정 설계).

발주처 조사(`institution_research.py`)와 대칭인 **자사** 프로필 소스. 기관 조사는 문서 밖
발주처 정보를 run 단위로 수거하지만, 제안사 쪽(회사개요·특장점·수행실적·인력·조직)은
run이 아니라 **프로젝트 전역 창고**에 산다 — 여러 run이 같은 회사를 재사용하기 때문이다
(발주처는 공고마다 다르지만 우리 회사는 그대로다).

    proposal_system/companies/<회사id>/
        profile.json  — 정형 코어(항목별 source 필수). fictional:true/false.
        assets/       — 로고·증빙 실물 자리(빈 폴더+README).
        intake/       — 비정형 원본 드롭 폴더(회사소개서·이력서·수주목록 등).
        gaps.md       — 이 회사로 run을 돌리며 드러난 부족 목록 축적(사람 가독).

증분 인테이크: `company --bundle --id <id>`가 intake/ 원본 + 기존 profile 요약을 묶어
정형화 프롬프트를 만든다(LLM/사람이 수행 — 창작 금지·출처 필수). 결과 JSON은
`company --apply --id <id> --file <경로>`가 검증(스키마·출처 누락 = 오류) 후
profile.json에 **병합**한다(덮어쓰기 아님 — 항목 추가·갱신, id 키로 중복 방지).

run 투입: `start --company <id>`가 run에 선택을 기록한다(run/company_selection.json —
pipeline_state 스키마를 건드리지 않는 독립 파일. 설계 문서의 "pipeline_state 또는 run 파일"
중 run 파일 쪽을 택함 — 안정적인 상태머신 스키마에 손대지 않기 위해).

fictional 가드(중요): fictional=true인 회사 데이터로 채워진 슬라이드는 `app/enrich.py`가
slide.example=True + bind.EXAMPLE_REVIEW_TAG를 강제한다(가상 데이터가 실제 제출물에
섞이는 것을 구조로 차단 — 렌더러가 이미 "예시 데이터" 배지·워터마크를 그린다, W9 안전장치).
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
PROFILE_NAME = "profile.json"
GAPS_NAME = "gaps.md"
SELECTION_NAME = "company_selection.json"
ASSETS_DIRNAME = "assets"
INTAKE_DIRNAME = "intake"
BUNDLE_DIRNAME = "intake_prompt"

_COMPANIES_ROOT = Path(__file__).resolve().parents[1] / "companies"

LIST_SECTIONS = ("strengths", "track_records", "people", "certifications")


# ---------------------------------------------------------------------------
# 경로
# ---------------------------------------------------------------------------

def companies_root() -> Path:
    return _COMPANIES_ROOT


def company_dir(company_id: str) -> Path:
    return companies_root() / company_id


def profile_path(company_id: str) -> Path:
    return company_dir(company_id) / PROFILE_NAME


def gaps_path(company_id: str) -> Path:
    return company_dir(company_id) / GAPS_NAME


def assets_dir(company_id: str) -> Path:
    return company_dir(company_id) / ASSETS_DIRNAME


def intake_dir(company_id: str) -> Path:
    return company_dir(company_id) / INTAKE_DIRNAME


def bundle_prompt_path(company_id: str) -> Path:
    return company_dir(company_id) / BUNDLE_DIRNAME / "prompt.md"


def exists(company_id: str) -> bool:
    return profile_path(company_id).is_file()


# ---------------------------------------------------------------------------
# profile.json 로드/저장
# ---------------------------------------------------------------------------

def load(company_id: str) -> "dict | None":
    p = profile_path(company_id)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save(company_id: str, profile: dict) -> Path:
    p = profile_path(company_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# 창고 스캐폴딩(assets/·intake/ + README) — 신규/기존 회사 공통, 멱등
# ---------------------------------------------------------------------------

_ASSETS_README = """# assets/

로고·증빙 실물(로고 이미지, 인증서 스캔 등)을 여기 둔다. 파일명에서 무엇인지 바로 알아볼 수
있게 하라(예: `logo.png`, `iso27001_인증서.pdf`). profile.json의 각 항목이 이 폴더의 파일을
가리킬 수 있다(경로는 `assets/<파일명>`).
"""

_INTAKE_README = """# intake/

회사소개서·이력서·수주목록 같은 **비정형 원본**을 여기 드롭한다.

`python proposal_system/scripts/proposal_pipeline.py company --bundle --id <이 회사 id>` 가
이 폴더의 파일 목록 + 기존 profile.json 요약을 묶어 정형화 프롬프트를 만든다. 그 프롬프트를
LLM(또는 사람)에게 주면 profile.json 스키마에 맞는 병합 패치 JSON을 작성할 수 있다
(창작 금지 — 이 폴더의 문서에 없는 사실은 절대 만들지 않는다. 항목마다 source에 파일명을
남겨라). 결과를 저장한 뒤:

    python proposal_system/scripts/proposal_pipeline.py company --apply --id <id> --file <결과.json>

검증(스키마·출처 누락) 후 profile.json에 병합된다(덮어쓰기 아님 — 기존 항목은 보존·갱신).
"""


def ensure_scaffold(company_id: str) -> Path:
    """assets/·intake/ + README를 멱등하게 만든다. 이미 있으면 손대지 않는다."""
    d = company_dir(company_id)
    (d / ASSETS_DIRNAME).mkdir(parents=True, exist_ok=True)
    (d / INTAKE_DIRNAME).mkdir(parents=True, exist_ok=True)
    _write_if_absent(d / ASSETS_DIRNAME / "README.md", _ASSETS_README)
    _write_if_absent(d / INTAKE_DIRNAME / "README.md", _INTAKE_README)
    return d


def _write_if_absent(path: Path, text: str) -> None:
    if not path.is_file():
        path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# 검증 — 오류(계약 위반·병합 중단) / 경고(표면화)
# ---------------------------------------------------------------------------

def _check_source(item: Any, label: str, errors: list[str]) -> None:
    if isinstance(item, dict) and not item.get("source"):
        errors.append(f"{label}: source 없음 — 항목별 출처 필수(창작 방지)")


def validate(profile: dict) -> dict:
    """profile.json(또는 병합 패치) 계약 검증 → {"errors": [...], "warnings": [...]}.

    부분 패치(일부 섹션만 있는 문서)도 검증 가능 — 없는 섹션은 건너뛴다. 다만 **최종 병합
    결과**에는 overview.name.value가 있어야 한다(회사명 없이는 식별 불가) — 이 검사는
    apply 쪽(merge 후)에서 별도로 강제한다(이 함수 자체는 부분 문서에 통일 적용).
    """
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(profile, dict):
        return {"errors": ["profile이 객체가 아님"], "warnings": []}

    if "fictional" in profile and not isinstance(profile["fictional"], bool):
        errors.append("fictional 필드는 true/false여야 한다")

    overview = profile.get("overview")
    if overview is not None:
        if not isinstance(overview, dict):
            errors.append("overview가 객체가 아님")
        else:
            name = overview.get("name")
            if isinstance(name, dict):
                if not name.get("value"):
                    errors.append("overview.name.value 없음 — 회사명 없이는 식별 불가")
                _check_source(name, "overview.name", errors)
            elif name is not None:
                errors.append("overview.name은 {value, source} 객체여야 한다")
            for key in ("founded", "scale", "intro"):
                v = overview.get(key)
                if isinstance(v, dict):
                    _check_source(v, f"overview.{key}", errors)

    for section in LIST_SECTIONS:
        items = profile.get(section)
        if items is None:
            continue
        if not isinstance(items, list):
            errors.append(f"{section}가 배열이 아님")
            continue
        for i, item in enumerate(items):
            _check_source(item, f"{section}[{i}]", errors)

    org = profile.get("organization")
    if org is not None:
        if not isinstance(org, dict):
            errors.append("organization이 객체가 아님")
        else:
            lead = org.get("lead")
            if isinstance(lead, dict):
                _check_source(lead, "organization.lead", errors)
            teams = org.get("teams")
            if isinstance(teams, list):
                for i, t in enumerate(teams):
                    _check_source(t, f"organization.teams[{i}]", errors)
            elif teams is not None:
                errors.append("organization.teams가 배열이 아님")

    return {"errors": errors, "warnings": warnings}


# ---------------------------------------------------------------------------
# 병합(덮어쓰기 아님 — 항목 추가·갱신)
# ---------------------------------------------------------------------------

def _item_key(section: str, item: dict) -> str:
    if section in ("strengths", "certifications"):
        return str(item.get("value") or "")
    if section == "track_records":
        return f"{item.get('client')}|{item.get('description')}"
    if section in ("people",):
        return str(item.get("name") or "")
    if section == "teams":
        return str(item.get("name") or "")
    return json.dumps(item, ensure_ascii=False, sort_keys=True)


def _merge_list(existing: "list | None", incoming: "list | None", section: str) -> tuple[list, int, int]:
    out = list(existing or [])
    index = {_item_key(section, it): i for i, it in enumerate(out) if isinstance(it, dict)}
    added = 0
    updated = 0
    for item in incoming or []:
        if not isinstance(item, dict):
            continue
        key = _item_key(section, item)
        if key in index:
            out[index[key]] = {**out[index[key]], **item}
            updated += 1
        else:
            out.append(item)
            index[key] = len(out) - 1
            added += 1
    return out, added, updated


def merge_profile(existing: "dict | None", incoming: dict) -> tuple[dict, dict]:
    """existing(없으면 빈 뼈대) + incoming(수거물) → (병합 결과, diff 요약)."""
    base: dict[str, Any] = dict(existing or {})
    diff: dict[str, Any] = {"overview_updated": [], "added": {}, "updated": {}}

    if "company_id" in incoming:
        base["company_id"] = incoming["company_id"]
    if "fictional" in incoming:
        base["fictional"] = incoming["fictional"]
    elif "fictional" not in base:
        base["fictional"] = False

    if "overview" in incoming and isinstance(incoming["overview"], dict):
        merged_overview = dict(base.get("overview") or {})
        for k, v in incoming["overview"].items():
            merged_overview[k] = v
        base["overview"] = merged_overview
        diff["overview_updated"] = sorted(incoming["overview"].keys())

    for section in LIST_SECTIONS:
        if section in incoming:
            merged, added, updated = _merge_list(base.get(section), incoming.get(section), section)
            base[section] = merged
            if added:
                diff["added"][section] = added
            if updated:
                diff["updated"][section] = updated

    if "organization" in incoming and isinstance(incoming["organization"], dict):
        org_in = incoming["organization"]
        org_base = dict(base.get("organization") or {})
        if "lead" in org_in and isinstance(org_in["lead"], dict):
            org_base["lead"] = {**(org_base.get("lead") or {}), **org_in["lead"]}
            diff["updated"]["organization.lead"] = 1
        if "teams" in org_in:
            merged_teams, added, updated = _merge_list(org_base.get("teams"), org_in.get("teams"), "teams")
            org_base["teams"] = merged_teams
            if added:
                diff["added"]["organization.teams"] = added
            if updated:
                diff["updated"]["organization.teams"] = updated
        base["organization"] = org_base

    base["schema_version"] = SCHEMA_VERSION
    return base, diff


def structural_gaps(profile: dict) -> list[str]:
    """스키마 섹션이 비어있으면 구조적 부족으로 표면화(사람이 다음 인테이크에서 채울 목록)."""
    gaps: list[str] = []
    if not profile.get("strengths"):
        gaps.append("특장점(strengths) 없음")
    if not profile.get("track_records"):
        gaps.append("수행실적(track_records) 없음")
    if not profile.get("people"):
        gaps.append("인력 풀(people) 없음")
    org = profile.get("organization") or {}
    if not org.get("lead") and not org.get("teams"):
        gaps.append("조직(organization) 정보 없음")
    if not profile.get("certifications"):
        gaps.append("인증(certifications) 없음")
    return gaps


# ---------------------------------------------------------------------------
# 창고 표(--list)
# ---------------------------------------------------------------------------

def list_companies() -> list[dict]:
    root = companies_root()
    if not root.is_dir():
        return []
    rows: list[dict] = []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        p = d / PROFILE_NAME
        if not p.is_file():
            continue
        profile = load(d.name) or {}
        overview = profile.get("overview") or {}
        name = (overview.get("name") or {}).get("value") or d.name
        rows.append({
            "id": d.name,
            "name": name,
            "fictional": bool(profile.get("fictional")),
            "track_records": len(profile.get("track_records") or []),
            "updated_at": dt.datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"),
        })
    return rows


def format_list(rows: list[dict]) -> str:
    if not rows:
        return "(창고에 등록된 회사가 없다 — `company --bundle --id <id>`로 인테이크를 시작하라)"
    header = f"{'id':<22} {'명칭':<28} {'fictional':<10} {'실적':<6} 최근 갱신"
    lines = [header, "-" * len(header)]
    for r in rows:
        lines.append(
            f"{r['id']:<22} {r['name']:<28} {str(r['fictional']):<10} {r['track_records']:<6} {r['updated_at']}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 프롬프트 요약(다른 번들에 동봉 — institution_research.render_for_prompt 대칭)
# ---------------------------------------------------------------------------

def render_for_prompt(profile: dict) -> str:
    """message_map/storyline 핸드오프 번들에 동봉할 자사 프로필 요약."""
    overview = profile.get("overview") or {}
    fictional = bool(profile.get("fictional"))
    name = (overview.get("name") or {}).get("value") or "(회사명 미기재)"
    lines = ["# 입력: 제안사(자사) 프로필"]
    if fictional:
        lines.append(
            "⚠️ fictional=true(가상 회사) — 이 정보로 채운 내용은 산출물에서 [예시] 표시가 "
            "유지되어야 한다(실제 제출물에 그대로 쓰지 말 것)."
        )
    lines.append(f"- 회사명: {name}" + ("  [가상]" if fictional and "가상" not in name else ""))
    if (overview.get("founded") or {}).get("value"):
        lines.append(f"- 설립: {overview['founded']['value']}")
    if (overview.get("scale") or {}).get("value"):
        lines.append(f"- 규모: {overview['scale']['value']}")
    if (overview.get("intro") or {}).get("value"):
        lines.append(f"- 소개: {overview['intro']['value']}")
    strengths = [s for s in (profile.get("strengths") or []) if isinstance(s, dict) and s.get("value")]
    if strengths:
        lines.append("- 특장점:")
        lines.extend(f"  - {s['value']}" for s in strengths)
    records = [r for r in (profile.get("track_records") or []) if isinstance(r, dict)]
    if records:
        lines.append("- 수행실적:")
        for r in records:
            bits = " · ".join(str(x) for x in (r.get("client"), r.get("description"), r.get("metric")) if x)
            lines.append(f"  - {bits}")
    people = [p for p in (profile.get("people") or []) if isinstance(p, dict)]
    if people:
        lines.append("- 인력 풀:")
        for p in people:
            lines.append(f"  - {p.get('name')}({p.get('role') or '?'}) — {p.get('expertise') or ''}")
    org = profile.get("organization") or {}
    if org.get("lead"):
        lead = org["lead"]
        lines.append(f"- 조직 책임자: {lead.get('name')} — {lead.get('description') or ''}")
    for t in org.get("teams") or []:
        if isinstance(t, dict):
            lines.append(f"  - 팀: {t.get('name')} ({', '.join(t.get('roles') or [])})")
    certs = [c.get("value") for c in (profile.get("certifications") or []) if isinstance(c, dict) and c.get("value")]
    if certs:
        lines.append("- 인증: " + ", ".join(certs))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 인테이크 정형화 프롬프트(--bundle)
# ---------------------------------------------------------------------------

_SCHEMA_EXAMPLE = """{
  "fictional": false,
  "overview": {
    "name": {"value": "회사명", "source": "회사소개서.pdf"},
    "founded": {"value": "20xx년", "source": "..."},
    "scale": {"value": "임직원 n명, 연매출 n억원", "source": "..."},
    "intro": {"value": "한 단락 소개", "source": "..."}
  },
  "strengths": [
    {"value": "특장점 한 줄", "source": "..."}
  ],
  "track_records": [
    {"client": "발주처/고객명(비공개 필요시 익명 표기)", "description": "수행 내용",
     "metric": "성과 수치(있으면)", "period": "20xx", "source": "..."}
  ],
  "people": [
    {"name": "이름 또는 직책", "role": "PM/기술리더 등", "expertise": "전문분야", "source": "..."}
  ],
  "organization": {
    "lead": {"name": "총괄 책임자", "description": "역할", "source": "..."},
    "teams": [{"name": "팀명", "roles": ["역할1", "역할2"], "source": "..."}]
  },
  "certifications": [
    {"value": "ISO 27001 등", "source": "..."}
  ]
}"""


def build_bundle_prompt(company_id: str) -> str:
    """intake/ 원본 목록 + 기존 profile 요약을 동봉한 정형화 프롬프트(결정론·0토큰)."""
    profile = load(company_id) or {}
    idir = intake_dir(company_id)
    intake_files = (
        sorted(p.name for p in idir.glob("*") if p.is_file() and p.name.lower() != "readme.md")
        if idir.is_dir() else []
    )
    parts = [
        f"# 제안사 프로필 인테이크 — {company_id} (창작 금지 · 출처 필수)",
        "",
        "너는 **회사 프로필 정형화 담당자**다. 아래 intake/ 원본 자료만 근거로 profile.json에",
        "병합할 패치 JSON을 작성한다. 자료에 없는 사실은 절대 지어내지 마라 — 모르면 비워두고,",
        "채운 항목마다 source(문서명·파일명 등)를 반드시 남겨라. 출력은 스키마의 JSON",
        "객체 하나뿐(설명·코드펜스 밖 텍스트 금지).",
        "",
        "## intake/ 원본 목록",
    ]
    if intake_files:
        parts.extend(f"- {name}" for name in intake_files)
    else:
        parts.append(f"- (비어있음 — {idir}/ 에 회사소개서·이력서·수주목록 등을 먼저 드롭하라)")
    parts.append("")
    parts.append("## 기존 profile.json 요약 (있으면 — 병합 대상이지 백지 재작성이 아니다)")
    parts.append(render_for_prompt(profile) if profile else "(없음 — 신규 회사)")
    parts.append("")
    parts.append("## 규칙")
    parts.append("1. 이미 있는 항목과 같은 내용은 중복으로 넣지 말고, 새 사실만 추가하거나 바뀐 값만 갱신하라.")
    parts.append("2. 회사가 비공개를 원하는 고객명은 client_safe_names 관례대로 익명 표기(예: 'A기관')하고 그 사실을 source에 남겨라.")
    parts.append("3. 이 회사가 리허설/예시용 가상 회사라면 fictional을 true로 유지하라(임의로 false로 바꾸지 말 것).")
    parts.append("")
    parts.append("## 출력 스키마 (profile.json 병합 패치 — 있는 섹션만 채워도 된다)")
    parts.append("```json")
    parts.append(_SCHEMA_EXAMPLE)
    parts.append("```")
    parts.append("")
    parts.append("## 저장 후 적용")
    parts.append(
        f"결과 JSON을 파일로 저장한 뒤: `python proposal_system/scripts/proposal_pipeline.py "
        f"company --apply --id {company_id} --file <경로>`"
    )
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# run 선택 기록 (`start --company`) — run 파일(독립, pipeline_state 스키마 불변)
# ---------------------------------------------------------------------------

def selection_path(run: "str | Path") -> Path:
    return Path(run) / SELECTION_NAME


def save_selection(run: "str | Path", company_id: str) -> Path:
    p = selection_path(run)
    p.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema_version": SCHEMA_VERSION,
        "company_id": company_id,
        "selected_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def load_selection(run: "str | Path") -> "dict | None":
    p = selection_path(run)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# gaps.md 축적(결정론 append, 중복 방지)
# ---------------------------------------------------------------------------

def _gaps_header(company_id: str) -> str:
    return (
        f"# gaps — {company_id}\n\n"
        "이 회사로 run을 돌리며 드러난 부족한 정보를 축적한다(사람 가독 — 시스템이 자동으로 "
        "해소하지 않는다). 다음 인테이크(`company --bundle`) 때 이 목록을 보고 무엇을 구해와야 "
        "하는지 판단하라.\n"
    )


_GAP_LINE_RE = re.compile(r"^- (?:\[[^\]]+\]\s*)?(.*)$")


def append_gaps(company_id: str, entries: list[str]) -> int:
    """gaps.md에 새 항목만 append(내용 동일 항목은 건너뜀 — 결정론·중복 방지). 반환=추가 건수."""
    entries = [e.strip() for e in entries if e and e.strip()]
    if not entries:
        return 0
    path = gaps_path(company_id)
    existing_bodies: set[str] = set()
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        for ln in lines:
            m = _GAP_LINE_RE.match(ln)
            if m:
                existing_bodies.add(m.group(1).strip())
    else:
        lines = _gaps_header(company_id).splitlines()
    stamp = dt.date.today().isoformat()
    added = 0
    for body in entries:
        if body in existing_bodies:
            continue
        lines.append(f"- [{stamp}] {body}")
        existing_bodies.add(body)
        added += 1
    if added:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return added
