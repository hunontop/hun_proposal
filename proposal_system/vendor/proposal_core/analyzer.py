# -*- coding: utf-8 -*-
"""
M2 analyzer — 분석카드 생성 '프롬프트 빌더' (LLM 직접호출 X)

pj_pt의 agent_prompt.py 패턴과 동일:
  LLM을 코드에서 부르지 않고, **클로드 코드 세션에 붙여넣을 프롬프트 + 원문 텍스트**를
  하나로 묶어 출력한다. 세션(에이전트)이 그걸 읽고 분석카드(.md)를 생성한다.

2-레이어 설계(양식 독립):
  - 레이어 A(결정적): API 메타 필드(항상 같은 JSON 키) + 첨부 본문 텍스트 전체(레이아웃 무관)
  - 레이어 B(LLM): 아래 8섹션을 고정 출력 스키마로, 의미 기반 추출. 양식 차이는 LLM이 흡수.
  - 안전장치: 금액·평가비율·일정은 레이어 A로 교차검증. 못 찾으면 지어내지 말고 '검토요망' 플래그.

사용:
  python analyzer.py <공고번호 또는 공고명일부>
    → analysis/<공고번호>_프롬프트.txt 저장 + stdout 출력
    → 이 텍스트를 클로드 코드 세션에 주면 analysis/<공고번호>_분석카드.md 생성
"""
import os
import sys
import io
import json
import sqlite3

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from hwp_parser import extract_any  # noqa: E402

DB_PATH = os.path.join(ROOT, "bids.db")
DATA_DIR = os.path.join(ROOT, "data")
# NORTHSTAR 결정 13(W25): 산출물 위치를 workspace/analysis로 통합 — run들과 나란히 두어
# "vendor=라이브러리처럼 보이는" 경로 혼란을 없앤다. ROOT는 vendor/proposal_core이므로
# 상위 2단계(vendor, proposal_core)를 벗어나 proposal_system/workspace/analysis로 해석한다.
ANALYSIS_DIR = os.path.normpath(os.path.join(ROOT, "..", "..", "workspace", "analysis"))
# 레거시 폴백(과거 산출물 읽기 전용) — 새 위치에 없으면 여기를 본다.
ANALYSIS_DIR_LEGACY = os.path.join(ROOT, "analysis")


# ──────────────────────────────────────────────────────────────
# 첨부 파싱 (레이어 A: 본문 텍스트)
# ──────────────────────────────────────────────────────────────
def _parse_pdf(path):
    import fitz
    doc = fitz.open(path)
    t = "\n".join(p.get_text() for p in doc)
    doc.close()
    return t


def parse_file(path):
    low = path.lower()
    if low.endswith((".hwp", ".hwpx")):
        return extract_any(path)
    if low.endswith(".pdf"):
        return _parse_pdf(path)
    return ""


def combined_text(bid_no, raw):
    """첨부가 없으면 다운로드, 있으면 재사용 → 통합 텍스트"""
    import requests
    safe = bid_no.replace("/", "_")
    outdir = os.path.join(DATA_DIR, safe)
    os.makedirs(outdir, exist_ok=True)

    # 다운로드(없는 것만)
    headers = {"User-Agent": "Mozilla/5.0"}
    names = []
    for i in range(1, 11):
        url = raw.get(f"ntceSpecDocUrl{i}")
        fnm = raw.get(f"ntceSpecFileNm{i}")
        if not url or not fnm:
            continue
        path = os.path.join(outdir, fnm)
        if not os.path.exists(path):
            try:
                r = requests.get(url, headers=headers, timeout=60)
                with open(path, "wb") as f:
                    f.write(r.content)
            except Exception as e:
                print(f"[다운로드 실패] {fnm}: {e}", file=sys.stderr)
                continue
        names.append(fnm)

    parts, manifest = [], []
    for fn in names:
        p = os.path.join(outdir, fn)
        if not os.path.exists(p):
            continue
        try:
            t = parse_file(p)
        except Exception as e:
            t = f"(파싱 실패: {e})"
        if len(t.strip()) < 20:        # zip 등 파싱 대상 아님 → 본문 제외
            manifest.append(f"{fn} (텍스트 없음·제외)")
            continue
        manifest.append(f"{fn} ({len(t):,}자)")
        parts.append(f"\n\n{'='*68}\n■ 첨부: {fn}\n{'='*68}\n{t}")
    return "\n".join(parts), manifest


# ──────────────────────────────────────────────────────────────
# 결정적 메타 추출 (레이어 A: API 필드)
# ──────────────────────────────────────────────────────────────
def deterministic_facts(raw):
    def g(k):
        v = raw.get(k)
        return v if v not in (None, "") else "-"

    def won(k):
        v = raw.get(k)
        try:
            return f"{int(float(v)):,}원"
        except (TypeError, ValueError):
            return "-"

    return [
        ("공고명", g("bidNtceNm")),
        ("공고번호", f'{g("bidNtceNo")}-{g("bidNtceOrd")}'),
        ("공고기관", g("ntceInsttNm")),
        ("수요기관", g("dminsttNm")),
        ("사업금액", won("asignBdgtAmt")),
        ("추정가격", won("presmptPrce")),
        ("입찰공고일시", g("bidNtceDt")),
        ("입찰개시일시", g("bidBeginDt")),
        ("입찰마감일시", g("bidClseDt")),
        ("개찰일시", g("opengDt")),
        ("계약방법", g("cntrctCnclsMthdNm")),
        ("입찰방식", g("bidMethdNm")),
        ("낙찰방법", g("sucsfbidMthdNm")),
        ("용역구분", g("srvceDivNm")),
        ("기술능력평가비율(%)", g("techAbltEvlRt")),
        ("입찰가격평가비율(%)", g("bidPrceEvlRt")),
        ("업종제한여부", g("indstrytyLmtYn")),
        ("공동수급방식", g("cmmnSpldmdMethdNm")),
        ("조달분류(대/중/세)", f'{g("pubPrcrmntLrgClsfcNm")} / {g("pubPrcrmntMidClsfcNm")} / {g("pubPrcrmntClsfcNm")}'),
        ("공고상세URL", g("bidNtceDtlUrl")),
    ]


# ──────────────────────────────────────────────────────────────
# 프롬프트 조립 (레이어 B 지시 + 양식 + 원문)
# ──────────────────────────────────────────────────────────────
INSTRUCTION = """\
너는 나라장터 입찰공고를 분석해 **입찰 분석카드(.md)** 한 장을 작성하는 분석 에이전트다.

[목표]
아래 [원문 첨부 텍스트]와 [결정적 메타]를 근거로, 정확히 아래 **8개 섹션**의 분석카드를 작성한다.
입찰 담당자가 이 한 장만 읽고 Go/No-Go를 결정하고 제안 준비에 착수할 수 있어야 한다.

[절대 규칙 — 정확성]
1. 모든 수치·요건은 원문/메타에 **근거가 있을 때만** 적는다. **지어내지 마라.**
2. 원문에서 못 찾은 항목은 비우고 🔴 '검토요망 — (무엇이 없는지/어디서 확인할지)' 로 표기한다.
   (예: 세부 배점표가 공고서에 없고 과업내용서에 있는 경우 → 검토요망으로 명시)
3. **교차검증**: 금액·평가비율(기술:가격)·마감일은 [결정적 메타](API 필드)와 원문을 대조한다.
   불일치하면 🔴 표기하고 메타 값을 우선 신뢰한다.
4. '~할 수 있다/가능하다' 류 모호표현 금지 사유, 방문/전자 제출 구분, 무효·실격 조건 같은
   **실수하면 입찰 자체가 무산되는 함정**을 7번 섹션에 반드시 끌어올린다.

[출력 양식 — 이 8개 섹션 고정]
# 📋 입찰 분석카드 — <사업명>
> 공고번호 · 분석일 · 출처 / ⚠️ 최종 제출 전 원문 재확인

## 1. 한눈에 (Executive Summary)   — 발주처/금액/기간/계약·낙찰방식/핵심과업 표
## 2. ⏰ 일정 (마감 역산)            — 단계별 일시 표 + 🔴 방문/전자 등 함정 강조
## 3. 🎯 평가 배점표                 — 부문·항목·배점 표(없으면 비율만+검토요망) + 💡전략 시사점
## 4. ✅ 입찰참가자격                 — 체크박스 목록(업종/자격/규모/공동수급)
## 5. 📑 필수 제출서류               — 서식/증빙 목록
## 6. 📐 제안서 작성 규격            — 형식·금지표현·익명화 등 감점·실격 방지
## 7. ⚠️ 리스크 / 독소조항          — 구분·내용·대응 표
## 8. 🤖 Go/No-Go 자동 판정         — 자격충족/예산매력도/전략적합도/일정여유/정보완전성 → 보류 시 ★사람결정 명시

[저장]
결과는 `analysis/<공고번호>_분석카드.md` 로 저장한다.
"""


def build_prompt(raw, body_text, manifest):
    facts = deterministic_facts(raw)
    facts_tbl = "\n".join(f"| {k} | {v} |" for k, v in facts)
    files = ", ".join(manifest) if manifest else "(첨부 없음)"
    return f"""{INSTRUCTION}

[결정적 메타 — API 필드, 교차검증 기준]
| 필드 | 값 |
|---|---|
{facts_tbl}

[첨부 파일 목록] {files}

[원문 첨부 텍스트]
{body_text}
"""


# ──────────────────────────────────────────────────────────────
def find_bid(needle):
    con = sqlite3.connect(DB_PATH)
    row = con.execute(
        "SELECT bid_no, raw FROM bids WHERE bid_no=? OR bid_name LIKE ? LIMIT 1",
        (needle, f"%{needle}%"),
    ).fetchone()
    con.close()
    return row


def main():
    if len(sys.argv) < 2:
        print("사용: python analyzer.py <공고번호 또는 공고명일부>", file=sys.stderr)
        sys.exit(1)
    needle = " ".join(sys.argv[1:])
    row = find_bid(needle)
    if not row:
        print(f"[없음] '{needle}' 매칭 공고 없음", file=sys.stderr)
        sys.exit(1)

    bid_no, raw_json = row
    raw = json.loads(raw_json)
    body, manifest = combined_text(bid_no, raw)
    prompt = build_prompt(raw, body, manifest)

    os.makedirs(ANALYSIS_DIR, exist_ok=True)
    safe = bid_no.replace("/", "_")
    out = os.path.join(ANALYSIS_DIR, f"{safe}_프롬프트.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(prompt)

    print(f"[공고] {raw.get('bidNtceNm')} ({bid_no})", file=sys.stderr)
    print(f"[첨부] {', '.join(manifest) if manifest else '없음'}", file=sys.stderr)
    print(f"[프롬프트] {out} ({len(prompt):,}자)", file=sys.stderr)
    print(f"\n→ 이 파일 내용을 클로드 코드 세션에 주면 분석카드(.md)가 생성됩니다.", file=sys.stderr)


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    main()
