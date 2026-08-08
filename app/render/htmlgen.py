# -*- coding: utf-8 -*-
"""정본 SlideModel → 자기완결 HTML 덱 (엔진 기본 렌더러).

베이크오프 결정(2026-06-27): 커스텀 자기완결 HTML/CSS = 기본. reveal export는 선택 타깃.
설계: 노하우 0. 색·폰트·치수는 **팩 tokens.json에서 CSS 변수로 주입**. per-template 레이아웃은
REGISTRY로 디스패치, 미지원 template_id → fallback + 🔴. 외부 의존 0(폰트는 시스템 폴백).

사용: python app/render/html.py <deck.json> <pack> <out.html>
"""
from __future__ import annotations

import base64
import html
import json
import re
from pathlib import Path
from typing import Any, Callable


def _image_slots_mod():
    """stage9 이미지 슬롯 모듈을 패키지/top-level 양쪽 임포트 경로에서 로드."""
    try:
        from . import image_slots  # 패키지 컨텍스트(app.render.htmlgen)
    except ImportError:
        import image_slots  # top-level(sys.path에 app/render)
    return image_slots


def _compose_mod():
    """W21-0 골격×조각 조합 렌더러(compose.py) — 패키지/top-level 양쪽 로드."""
    try:
        from . import compose  # 패키지 컨텍스트
    except ImportError:
        import compose  # top-level(sys.path에 app/render)
    return compose

ROOT = Path(__file__).resolve().parents[2]
PACKS = ROOT / "packs"
PACKS_EXCLUDED = ROOT / "packs_excluded"  # 배제 하우스 자산 — --pack 명시 로드만(결정 11·12). W31 E3: 실물은 <개발 원본 전용 경로> 격리, 이 경로는 상시 부재(is_dir() 폴백만 수행)
SKINS = ROOT / "skins"   # 독립 스킨 레지스트리(③축 자산). 이름→skins/<name>.json


def _pack_dir(name: str) -> Path:
    """활성 packs/ 우선, 격리 폴백. 자동 열거(iterdir)는 활성만 — 격리 팩은 명시 이름으로만 닿는다."""
    base = PACKS / str(name)
    return base if base.is_dir() else PACKS_EXCLUDED / str(name)


# W32 마찰28: 문자열을 기대하는 자리에 LLM이 {"name":..,"description":..} 같은 객체를 넣는 것은
# 구조화 필드에서 나오는 **자연스러운 오답**이다(shape 미문서 템플릿일수록 잦다). 종전에는 str(dict)가
# 그대로 조판돼 `{'name'` 같은 원시 dict가 장표에 노출됐고(시연 1차 장 4·13 실측) warnings=0이라
# 사람 정독 전까지 아무도 못 잡았다. → 관용 코어스(라벨: 상세로 접기) + 경고 표면화로 바꾼다.
# 코어스를 _esc 한 곳에 두어 전 렌더러가 자동으로 덮인다(str/숫자 입력은 종전과 바이트 동일).
# 로직·기록은 text_coerce 공용 — 렌더 경로 4개가 각자 _esc를 갖고 있어 한 곳만 고치면 나머지가 샌다.
try:
    from .text_coerce import as_text as _as_text, records as _coerced   # 패키지 컨텍스트
except ImportError:
    from text_coerce import as_text as _as_text, records as _coerced    # top-level(sys.path에 app/render)


def _esc(x: Any) -> str:
    return html.escape(_as_text(x))


# 본문 앞머리 열거 마커(①②·(1)·1.·1))를 뗀다 — 자동 번호 뱃지와의 '이중번호' 방지.
# 보수적: 원문자·괄호숫자·"n." / "n)"만 제거. 맨숫자("10건…")는 건드리지 않는다.
_ENUM_MARKER_RE = re.compile(r'^\s*(?:[①-⑳]️?|\(\d{1,2}\)|\d{1,2}[.)])\s*')


def _strip_enum_marker(s: Any) -> str:
    return _ENUM_MARKER_RE.sub("", str(s if s is not None else ""), count=1).lstrip()


# W31 γ패킷(리허설 마찰25): 크롬 헤더(제목) 글자수 기반 단계적 폰트 축소 — 긴 제목이 감싸며(wrap)
# 고정 100vh 슬라이드(`.slide{overflow:hidden}`)를 넘치는 문제 대응(사용자 발견: "크롬 상단 구조가
# 일부 페이지에서 넘친다"). 결정론(글자수만 기준) — 브라우저 실측 오버플로 감지는 layout_probe/
# design_checks 몫(별도, 이 함수와 독립). 임계는 실 코퍼스 관측으로 교정된 값이 아니라 사전
# 보수치다(app/render/design_checks.py의 실측 임계와 원리는 같되 값의 출처가 다르다) —
# 24자=한글 제목 한 줄 근사, 40자=두 줄 근사, 그 이상은 위험으로 본다.
TITLE_LEN_MD = 24    # 이 글자수 초과 → title--md(축소 1단계)
TITLE_LEN_SM = 40    # 이 글자수 초과 → title--sm(축소 2단계, md보다 더 축소)

_TITLE_FIT_CSS = """
    .slide__title.title--md { font-size: calc(var(--type-section) * .78); }
    .slide__title.title--sm { font-size: calc(var(--type-section) * .6); }
    .cover .slide__title.title--md { font-size: calc(var(--type-title) * .78); }
    .cover .slide__title.title--sm { font-size: calc(var(--type-title) * .6); }
"""


def _title_fit_class(title: Any) -> str:
    """긴 제목일수록 더 축소하는 CSS 모디파이어 클래스(없으면 빈 문자열 — 짧은 제목은 바이트 불변)."""
    n = len(str(title or ""))
    if n > TITLE_LEN_SM:
        return " title--sm"
    if n > TITLE_LEN_MD:
        return " title--md"
    return ""


def _effective_title(slide: dict) -> str:
    """r_cover와 동일한 제목 결정 규칙(title 우선, 없으면 fields.project_title) — auto-fit 판정용."""
    t = slide.get("title")
    if t:
        return str(t)
    fields = slide.get("fields") or {}
    return str(fields.get("project_title") or "")


def _load(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))


# W9 예시 데이터 라벨(안전장치 ①) CSS — 예시 슬라이드가 있을 때만 style에 얹는다(없는 덱은
# 바이트 불변). 주석에 라벨 문자열을 넣지 않는다(라벨 바이트 존재 검증이 마크업만 재도록).
_EXAMPLE_CSS = """
    .example-badge { position: absolute; top: 2.2vh; left: 4vw; z-index: 5;
              background: #fff3cd; color: #7a5b00; border: 1px solid #e0b400; border-radius: 4px;
              padding: .2em .6em; font-size: var(--type-caption); font-weight: 700; letter-spacing: .04em; }
    .example-watermark { position: absolute; top: 50%; left: 50%; z-index: 0; pointer-events: none;
              white-space: nowrap;
              font-size: 8vw; font-weight: 800; color: rgba(224,180,0,.10);
              transform: translate(-50%, -50%) rotate(-18deg); letter-spacing: .1em; }"""


# W22 브랜드 크롬(통찰 14): 제안사(좌하단, 전 장 기본) + 클라이언트(하단 중앙, cover 기본) 마크.
# brand 마크업이 실제로 생성될 때만 style에 얹는다(_EXAMPLE_CSS와 동일 패턴 — 무브랜드 덱 바이트 불변).
_BRAND_CSS = """
    .slide__brand { position: absolute; display: flex; align-items: center; gap: .5em; z-index: 5; }
    .slide__brand img { height: 3.2vh; width: auto; display: block; }
    .slide__brand span { font-size: var(--type-footer); }
    .slide__brand--proposer { left: 4vw; bottom: 3vh; color: var(--muted); }
    .slide__brand--client { left: 50%; bottom: 3vh; transform: translateX(-50%); color: rgba(255,255,255,.85); }
    .slide__brand--client img { height: 4vh; }"""


# --- 토큰 → CSS 변수 -------------------------------------------------------

def _css_vars(tokens: dict) -> str:
    lines = []
    for k, v in (tokens.get("colors") or {}).items():
        lines.append(f"--c-{k.replace('_','-')}: #{v.lstrip('#')};")
    fonts = tokens.get("fonts") or {}
    fam = fonts.get("family", "Pretendard")
    lines.append(f'--font-family: "{fam}";')
    for k, v in (fonts.get("sizes") or {}).items():
        lines.append(f"--type-{k}: {v}pt;")
    return "\n      ".join(lines)


def _base_css(tokens: dict) -> str:
    # 첫 색을 강조/네이비 후보로 추정(팩 무관 동작): navy 키 우선, 없으면 첫 색
    colors = tokens.get("colors") or {}
    primary = "navy" if "navy" in colors else (next(iter(colors), "navy"))
    accent = "orange" if "orange" in colors else primary
    return f"""
    :root {{
      {_css_vars(tokens)}
      --primary: var(--c-{primary.replace('_','-')});
      --accent: var(--c-{accent.replace('_','-')}, var(--primary));
      --ink: var(--c-black, #111);
      --paper: var(--c-white, #fff);
      --muted: var(--c-gray-text, #595959);
      --line: var(--c-gray-line, #d5d5d5);
      /* B4 시맨틱 토큰(폴백 안전 — 미정의 스킨은 기존 값으로 degrade):
         --conclude=결론/리스크 강조(orange_deep 제한 배선) · --label=카드/KPI 라벨·서브헤더 */
      --conclude: var(--c-orange-deep, var(--accent));
      --label: var(--type-label, var(--type-small));
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-snap-type: y mandatory; scroll-behavior: smooth; }}
    body {{
      margin: 0; color: var(--ink);
      font-family: var(--font-family), "Noto Sans KR", "Apple SD Gothic Neo", "Malgun Gothic", system-ui, sans-serif;
      background: #0d1f3a;
    }}
    .slide {{
      position: relative; width: 100vw; height: 100vh;
      scroll-snap-align: start; overflow: hidden;
      display: flex; flex-direction: column;
      padding: 5vh 6vw; background: var(--paper);
    }}
    .slide__bar {{ position: absolute; top: 0; left: 0; width: 36vw; height: .7vh; background: var(--accent); }}
    .slide__eyebrow {{ color: var(--accent); font-weight: 700; font-size: var(--type-small); letter-spacing: .04em; }}
    .slide__title {{ font-size: var(--type-section); font-weight: 800; color: var(--primary); margin: .3em 0 .1em; }}
    .slide__msg {{ font-size: var(--type-body); color: var(--muted); margin-bottom: 1em; }}
    .slide__body {{ font-size: var(--type-body); line-height: 1.6; }}
    .slide__body li {{ margin: .35em 0; }}
    .pagenum {{ position: absolute; right: 4vw; bottom: 3vh; color: var(--muted); font-size: var(--type-footer); }}
    /* 우측 상단 메타 라인(상단 크롬) — 팩 무관 기본 배치. 팩이 세부 조정. */
    .slide__meta {{ position: absolute; top: 2.2vh; right: 4vw; white-space: nowrap;
                    color: var(--muted); font-size: var(--type-caption); letter-spacing: .05em; }}
    .review {{ margin-top: auto; background: #fff4f4; border-left: 4px solid var(--c-red, #c00);
              padding: .6em .9em; font-size: var(--type-small); color: #a00; border-radius: 4px; }}
    .review b {{ color: #c00; }}
    /* 표지 */
    .cover {{ justify-content: center; background:
      linear-gradient(135deg, var(--c-section-cover, #1f3864), var(--primary)); color: #fff; }}
    .cover .slide__title {{ color: #fff; font-size: var(--type-title); }}
    .cover .slide__msg {{ color: #d6dce5; }}
    /* 카드 그리드 */
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(0,1fr)); gap: 1.2vw; margin-top: .6em; }}
    .card {{ border: 1px solid var(--line); border-radius: 8px; padding: 1em; background: #fafafa; }}
    .card h4 {{ margin: 0 0 .4em; color: var(--accent); font-size: var(--label); }}   /* B4: 카드 라벨 = label(14pt) */
    /* 데이터 장표 */
    .data {{ display: grid; grid-template-columns: 1.1fr 1fr; gap: 3vw; align-items: center; flex: 1; margin-top: .4em; }}
    .data .metric {{ color: var(--muted); font-size: var(--label); font-weight: 700; letter-spacing: .03em; margin-bottom: .3em; }}   /* B4: KPI 지표 라벨 = label */
    .bars {{ display: flex; gap: 4vw; align-items: flex-end; height: 44vh; padding: 0 2vw; border-bottom: 2px solid var(--line); }}
    .bar {{ flex: 1; max-width: 14vw; display: flex; flex-direction: column; justify-content: flex-end; text-align: center; }}
    .bar .val {{ font-size: 2.4vw; font-weight: 800; color: var(--primary); margin-bottom: .15em; }}
    .bar .fill {{ background: linear-gradient(var(--accent), color-mix(in srgb, var(--accent) 65%, var(--paper)));
                  border-radius: 8px 8px 0 0; min-height: 8px; }}
    .bar:first-child .fill {{ background: var(--c-gray-line, #ccc); }}
    .bar .lab {{ margin-top: .5em; font-size: var(--type-body); font-weight: 600; }}
    .interp {{ list-style: none; padding: 0; margin: 0; }}
    .interp li {{ border-left: 4px solid var(--accent); padding: .3em 0 .3em .8em; margin: .7em 0; }}
    /* 우선순위 매트릭스 */
    .matrix {{ display: grid; grid-template-columns: auto 1fr; gap: .5em; flex: 1; margin-top: .4em; }}
    .ytitle {{ writing-mode: vertical-rl; transform: rotate(180deg); text-align: center; color: var(--accent); font-weight: 700; }}
    .mgrid {{ display: grid; grid-template-columns: repeat(3, 1fr); grid-template-rows: repeat(3, 1fr); gap: .5em; }}
    .mcell {{ border: 1px dashed var(--line); border-radius: 8px; padding: .6em; display: flex; flex-wrap: wrap;
              gap: .4em; align-content: flex-start; }}
    .mcell.hot {{ background: color-mix(in srgb, var(--accent) 12%, var(--paper)); border-style: solid; border-color: var(--accent); }}
    .chip {{ background: var(--primary); color: #fff; border-radius: 999px; padding: .25em .7em; font-size: var(--type-caption, var(--type-small)); height: fit-content; }}
    .xtitle {{ grid-column: 2; text-align: center; color: var(--accent); font-weight: 700; margin-top: .2em; }}
    .axlab {{ display: flex; justify-content: space-around; color: var(--muted); font-size: var(--type-small); margin-top: .2em; }}
    /* 대비 */
    .twocol {{ display: grid; grid-template-columns: 1fr auto 1fr; gap: 1.5vw; align-items: center; margin-top: 1em; }}
    .twocol .col {{ border: 1px solid var(--line); border-radius: 8px; padding: 1em; }}
    .twocol .arrow {{ font-size: 3vw; color: var(--accent); }}
    /* 퍼널(전환 단계) — SVG 다이어그램 렌더러 */
    .funnel-layout {{ display: flex; flex-direction: column; gap: .8em; flex: 1; margin-top: .4em; min-height: 0; }}
    .funnel-svg {{ width: 100%; height: 20vh; flex: none; }}   /* flex 컬럼서 height:auto SVG가 0으로 붕괴 → 명시 height(viewBox+meet가 비율 유지) */
    .funnel-svg .fn-lab {{ fill: #fff; font-weight: 800; font-size: 26px; }}
    .funnel-svg .fn-metric {{ fill: #fff; opacity: .85; font-size: 15px; font-weight: 600; }}
    .funnel-details {{ list-style: none; padding: 0; margin: 0; display: grid; gap: .45em; }}
    .funnel-details li {{ border-left: 4px solid var(--accent); padding: .25em 0 .25em .8em; line-height: 1.5; }}
    .funnel-details b {{ color: var(--primary); }}
    .funnel-loop {{ border: 1px dashed var(--accent); border-radius: 8px; padding: .5em .8em; color: var(--conclude); font-weight: 700; }}
    /* 조직도 — SVG 계층 다이어그램 */
    .org-layout {{ display: flex; flex-direction: column; gap: .7em; flex: 1; margin-top: .4em; min-height: 0; }}
    .org-svg {{ width: 100%; height: auto; max-height: 34vh; }}
    .org-svg .org-top {{ fill: var(--primary); }}
    .org-svg .org-node {{ fill: var(--accent); }}
    .org-svg .org-line {{ stroke: var(--line); stroke-width: 2; fill: none; }}
    .org-svg .org-lab {{ fill: #fff; font-weight: 700; font-size: 22px; }}
    .org-svg .org-lab--top {{ font-size: 24px; font-weight: 800; }}
    .org-details {{ list-style: none; padding: 0; margin: 0; display: grid; gap: .4em; }}
    .org-details li {{ border-left: 4px solid var(--accent); padding: .2em 0 .2em .8em; line-height: 1.5; }}
    .org-details b {{ color: var(--primary); }}
    /* 케이스(사례) 카드 */
    .case-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(0,1fr)); gap: 1em; margin-top: .6em; flex: 1; align-content: start; }}
    .case-card {{ display: flex; gap: .7em; align-items: flex-start; border: 1px solid var(--line);
                  border-left: 5px solid var(--accent); border-radius: 8px; padding: 1em; background: #fafafa; line-height: 1.55; }}
    .case-mark {{ color: var(--accent); font-weight: 900; font-size: 1.3em; line-height: 1; }}
    .case-txt b {{ color: var(--primary); }}
    /* 정량 목표/지표 그리드 */
    .target-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(0,1fr)); gap: 1em; margin-top: .6em; flex: 1; align-content: start; }}
    .target-card {{ border: 1px solid var(--line); border-top: 4px solid var(--accent); border-radius: 8px; padding: 1em; background: #fff; }}
    .target-lab {{ color: var(--muted); font-size: var(--type-label); font-weight: 700; margin-bottom: .35em; }}
    .target-val {{ color: var(--primary); font-weight: 800; font-size: calc(var(--type-body) * 1.12); line-height: 1.4; }}
    /* 구 하우스 팩 전용 콘텐츠 위계 CSS는 별도 렌더러 플러그인 모듈로 이관(2026-07-12, W21-0 §7.5 — 하우스 스타일은 플러그인 소유) */
    .dump {{ white-space: pre-wrap; font-size: var(--type-small); color: var(--muted); }}
    .navhint {{ position: fixed; left: 1vw; bottom: 1vh; color: #8aa; font-size: 10px; z-index: 9; }}

    """


# --- per-template 레이아웃 (정본 slide → HTML) ----------------------------

def _frame(inner: str, *, n: int, total: int, slide: dict, cls: str = "", meta: str = "",
           override: "dict | None" = None, slots_html: str = "", brand_html: str = "") -> str:
    review = ""
    rn = slide.get("review_needed") or []
    oq = slide.get("open_questions") or []
    if rn or oq:
        items = "".join(f"<div>🔴 <b>검토요망:</b> {_esc(x)}</div>" for x in rn)
        items += "".join(f"<div>🔴 <b>미결:</b> {_esc(x)}</div>" for x in oq)
        review = f'<div class="review">{items}</div>'
    # W9 예시 데이터 라벨(안전장치 ①): 배지 + 워터마크. 근거 없는 데모임을 사실처럼 보이지 않게.
    example_el = ""
    if slide.get("example"):
        example_el = ('<div class="example-badge">⚠ 예시 데이터</div>'
                      '<div class="example-watermark">예시 데이터</div>')
    # 좌상단 컬러 탭(.slide__bar) + 우측 메타 라인(.slide__meta) = 가이드 상단 크롬.
    meta_el = f'<div class="slide__meta">{meta}</div>' if meta else ""
    # stage9 디자인 디렉터 override: 섹션 id(css 스코프 앵커) + 추가 class + append-only HTML(장식/이미지 슬롯).
    # append-only라 deck.json 본문 텍스트는 구조적으로 불변(SSOT 안전).
    ov = override or {}
    extra_cls = f' {_esc(ov.get("class", ""))}' if ov.get("class") else ""
    append_html = ov.get("append_html", "") or ""
    # 이미지 슬롯(§7·B-9): append-only 장식 → SSOT 안전. 자산 있으면 인라인, 없으면 role placeholder.
    return (f'<section id="slide-{n}" class="slide {cls}{extra_cls}"><div class="slide__bar"></div>{example_el}{meta_el}'
            f'{inner}{append_html}{slots_html}{review}{brand_html}<div class="pagenum">{n:02d} / {total:02d}</div></section>')


def _head(slide: dict, claim: Any = None) -> str:
    """공통 머리(eyebrow+title+msg). claim이 주어지고 key_message와 동일하면
    msg를 생략한다 — hero claim으로 승격한 렌더러(problem/summary)의 동어 반복 방지."""
    eye = _esc(slide.get("role", ""))
    title_raw = slide.get("title", "")
    title = _esc(title_raw)
    fit_cls = _title_fit_class(title_raw)
    raw_msg = slide.get("key_message", "") or ""
    dup = claim is not None and str(claim).strip() == str(raw_msg).strip()
    msg = _esc(raw_msg)
    return (f'<div class="slide__eyebrow">{eye}</div>'
            f'<h2 class="slide__title{fit_cls}">{title}</h2>'
            + (f'<div class="slide__msg">{msg}</div>' if raw_msg and not dup else ""))


def r_cover(slide, f):
    title_raw = slide.get("title") or f.get("project_title", "")
    return (f'<div class="slide__eyebrow">{_esc(f.get("visual_subject",""))}</div>'
            f'<h1 class="slide__title{_title_fit_class(title_raw)}">{_esc(title_raw)}</h1>'
            f'<div class="slide__msg">{_esc(slide.get("key_message") or f.get("concept_message",""))}</div>')


def _body(slide):
    return slide.get("body") or []


def r_problem(slide, f):
    subs_src = f.get("sub_questions") or _body(slide)
    subs = "".join(f"<li>{_esc(q)}</li>" for q in subs_src)
    core_raw = f.get("core_question") or slide.get("key_message", "")
    core = _esc(core_raw)
    return _head(slide, core_raw) + (
        f'<div class="slide__body problem-layout">'
        f'<p class="problem-layout__claim">{core}</p>'
        f'<ul class="problem-layout__questions">{subs}</ul></div>'
    )


def r_summary(slide, f):
    pts = f.get("supporting_points") or _body(slide)
    # 자동 뱃지(i+1)와 본문 선두 마커(①②…)의 이중번호 방지 — 본문 마커는 뗀다.
    cards = "".join(f'<div class="card"><h4>{i+1}</h4>{_esc(_strip_enum_marker(p))}</div>' for i, p in enumerate(pts))
    claim_raw = f.get("main_claim") or slide.get("key_message", "")
    claim = _esc(claim_raw)
    return _head(slide, claim_raw) + (
        f'<div class="slide__body summary-layout">'
        f'<p class="summary-layout__claim"><b>{claim}</b></p>'
        f'<div class="cards">{cards}</div></div>'
    )


def r_pillars(slide, f):
    pillars = f.get("pillars") or _body(slide)
    lines = f.get("one_line_per_pillar", [])
    cards = "".join(f'<div class="card"><h4>{_esc(p)}</h4>{_esc(lines[i] if i < len(lines) else "")}</div>' for i, p in enumerate(pillars))
    return _head(slide) + f'<div class="cards">{cards}</div>'


def _body_fallback(slide):
    items = "".join(f"<li>{_esc(b)}</li>" for b in _body(slide))
    return f'<div class="slide__body"><ul>{items}</ul></div>' if items else ""


def r_content(slide, f):
    """Generic canonical content when no stage7 template has been selected."""
    return _head(slide) + _body_fallback(slide)


def r_data(slide, f):
    comp = f.get("comparison", [])
    # comparison은 dict 원소 리스트 규약이다 — LLM이 문자열 요약("70% vs 30%")을 넣는 실측
    # 사례가 있다(D1). 리스트가 아니거나 원소가 dict가 아니면 아래 컴프리헨션에서
    # AttributeError가 나는데, 여기서 조용히 삼키지 않는다 — 호출부(render())의 try/except가
    # 잡아서 fallback 렌더 + warnings 보고로 표면화한다("조용한 폴백 금지").
    vals = [c.get("value", 0) for c in comp] or [1]
    mx = max(vals) or 1
    bars = "".join(
        f'<div class="bar"><div class="val">{_esc(c.get("value",""))}</div>'
        f'<div class="fill" style="height:{int(92*c.get("value",0)/mx)}%"></div>'
        f'<div class="lab">{_esc(c.get("label",""))}</div></div>'
        for c in comp)
    interp = "".join(f"<li>{_esc(x)}</li>" for x in (f.get("interpretation") or _body(slide)))
    metric = _esc(f.get("metric", ""))
    if not comp:   # 차트 데이터 없으면 본문만
        return _head(slide) + f'<div class="slide__body data-panel--text"><ul class="interp">{interp}</ul></div>'
    return _head(slide) + (
        f'<div class="data data-panel">'
        f'<div><div class="metric data-panel__caption">지표 · {metric}</div><div class="bars">{bars}</div></div>'
        f'<ul class="interp">{interp}</ul></div>')


def r_matrix(slide, f):
    if not f.get("items"):
        return _head(slide) + _body_fallback(slide)
    xa, ya = _esc(f.get("x_axis", "")), _esc(f.get("y_axis", ""))
    bands = ["low", "mid", "high"]
    cells: dict[tuple, list] = {}
    for it in f.get("items", []):
        cells.setdefault((it.get("y_band"), it.get("x_band")), []).append(it.get("name"))
    grid = ""
    for yb in ["high", "mid", "low"]:          # 위→아래 = 효과 높음→낮음
        for xb in bands:                        # 좌→우 = 난이도 낮음→높음
            names = cells.get((yb, xb), [])
            chips = "".join(f'<span class="chip">{_esc(n)}</span>' for n in names)
            hot = " hot" if (yb == "high" and xb == "low") else ""   # 효과↑·난이도↓ = 최우선
            grid += f'<div class="mcell{hot}">{chips}</div>'
    return _head(slide) + (
        f'<div class="matrix"><div class="ytitle">{ya} ↑</div>'
        f'<div><div class="mgrid">{grid}</div>'
        f'<div class="axlab"><span>{xa} 낮음</span><span>높음 →</span></div></div></div>')


def r_contrast(slide, f):
    if not (f.get("as_is") or f.get("to_be")):
        # 대비 데이터 없음 — body가 정량 목표('라벨: 값') 목록이면 지표 그리드로, 아니면 generic
        return _head(slide) + (_targets_grid(_body(slide)) or _body_fallback(slide))
    return _head(slide) + (f'<div class="twocol"><div class="col"><b>AS-IS</b><div>{_esc(f.get("as_is",""))}</div></div>'
            f'<div class="arrow">→</div><div class="col"><b>TO-BE</b><div>{_esc(f.get("to_be",""))}</div></div></div>'
            f'<p class="slide__msg">{_esc(f.get("transition_message",""))}</p>')


def _parse_funnel_body(body) -> list[dict]:
    """구조화 stages가 없을 때 body에서 'X 구간: 상세' 패턴을 단계로 복원(안전 폴백)."""
    stages = []
    for b in body or []:
        b = str(b)
        head, sep, rest = b.partition(":")
        if not sep:
            head, sep, rest = b.partition("：")
        if sep and "구간" in head:
            label = head.replace("구간", "").strip(" ·-—")
            if label:
                stages.append({"label": label, "detail": rest.strip()})
    return stages


def r_funnel(slide, f):
    """전환 퍼널 = N단계 SVG 다이어그램(스킨 토큰 구동). 데이터 없으면 generic로 우아하게 폴백."""
    stages = f.get("stages") or _parse_funnel_body(_body(slide))
    stages = [s for s in stages if isinstance(s, dict) and (s.get("label") or s.get("detail"))]
    if not stages:
        return r_content(slide, f)
    n = len(stages)
    W, H, gap, tip = 1000.0, 260.0, 12.0, 26.0
    seg_w = (W - gap * (n - 1)) / n
    h_max, h_min = 210.0, 120.0
    parts = []
    for i, st in enumerate(stages):
        x = i * (seg_w + gap)
        frac = (i / (n - 1)) if n > 1 else 0.0
        h = h_max - (h_max - h_min) * frac
        y = (H - h) / 2
        notch = tip if i > 0 else 0.0     # 왼쪽 노치로 앞 단계와 맞물림
        pts = (f"{x:.0f},{y:.0f} {x + seg_w - tip:.0f},{y:.0f} {x + seg_w:.0f},{H/2:.0f} "
               f"{x + seg_w - tip:.0f},{y + h:.0f} {x:.0f},{y + h:.0f} {x + notch:.0f},{H/2:.0f}")
        pct = 100 - int(45 * frac)         # 앞→뒤로 accent→primary 심화 = 깔때기 수렴감
        fill = f"color-mix(in srgb, var(--accent) {pct}%, var(--primary))"
        cx = x + (seg_w + notch - tip) / 2
        label = _esc(st.get("label", ""))
        metric = _esc(st.get("metric", ""))
        parts.append(f'<polygon points="{pts}" fill="{fill}"></polygon>'
                     f'<text x="{cx:.0f}" y="{H/2-4:.0f}" text-anchor="middle" class="fn-lab">{label}</text>'
                     + (f'<text x="{cx:.0f}" y="{H/2+22:.0f}" text-anchor="middle" class="fn-metric">{metric}</text>' if metric else ""))
    svg = (f'<svg class="funnel-svg" viewBox="0 0 {int(W)} {int(H)}" preserveAspectRatio="xMidYMid meet" '
           f'role="img" aria-label="전환 퍼널">' + "".join(parts) + "</svg>")
    details = "".join(f'<li><b>{_esc(st.get("label",""))}</b> {_esc(st.get("detail",""))}</li>'
                      for st in stages if st.get("detail"))
    loop = _esc(f.get("loop", ""))
    loop_html = f'<div class="funnel-loop">↻ {loop}</div>' if loop else ""
    return _head(slide) + (f'<div class="slide__body funnel-layout">{svg}'
                           f'<ul class="funnel-details">{details}</ul>{loop_html}</div>')


def _split_label(s) -> tuple[str, str]:
    """'라벨: 상세' → (라벨, 상세). 구분자 없으면 (원문, '').

    W32 마찰28: 객체가 들어오면 _as_text가 '라벨: 상세'로 접어 주므로 분리가 그대로 성립한다
    (종전에는 str(dict)를 콜론 분리해 `{'name'`이 볼드 라벨로 조판됐다).
    """
    s = _as_text(s)
    head, sep, rest = s.partition(":")
    if not sep:
        head, sep, rest = s.partition("：")
    return (head.strip(" ·-—"), rest.strip()) if sep else (s.strip(), "")


def r_org(slide, f):
    """조직도 = 총괄(top) + 하위 팀(children) SVG 계층 다이어그램. 데이터 없으면 generic 폴백."""
    pairs = [_split_label(r) for r in (f.get("roles") or _body(slide))]
    pairs = [p for p in pairs if p[0]]
    if not pairs:
        return r_content(slide, f)
    top, kids = pairs[0], pairs[1:]
    W, H, bw, bh = 1000.0, 240.0, 260.0, 64.0
    ty, ky = 12.0, 150.0
    parts = [f'<svg class="org-svg" viewBox="0 0 {int(W)} {int(H)}" role="img" aria-label="조직도">',
             f'<rect x="{(W-bw)/2:.0f}" y="{ty:.0f}" width="{bw:.0f}" height="{bh:.0f}" rx="10" class="org-top"></rect>',
             f'<text x="{W/2:.0f}" y="{ty+bh/2+7:.0f}" text-anchor="middle" class="org-lab org-lab--top">{_esc(top[0])}</text>']
    if kids:
        n = len(kids)
        cxs = [W * (i + 0.5) / n for i in range(n)]
        mid_y = ty + bh + 30
        parts.append(f'<line x1="{W/2:.0f}" y1="{ty+bh:.0f}" x2="{W/2:.0f}" y2="{mid_y:.0f}" class="org-line"></line>')
        parts.append(f'<line x1="{min(cxs):.0f}" y1="{mid_y:.0f}" x2="{max(cxs):.0f}" y2="{mid_y:.0f}" class="org-line"></line>')
        for cx, (lab, _det) in zip(cxs, kids):
            parts.append(f'<line x1="{cx:.0f}" y1="{mid_y:.0f}" x2="{cx:.0f}" y2="{ky:.0f}" class="org-line"></line>')
            parts.append(f'<rect x="{cx-bw/2:.0f}" y="{ky:.0f}" width="{bw:.0f}" height="{bh:.0f}" rx="10" class="org-node"></rect>'
                         f'<text x="{cx:.0f}" y="{ky+bh/2+7:.0f}" text-anchor="middle" class="org-lab">{_esc(lab)}</text>')
    parts.append("</svg>")
    details = "".join(f'<li><b>{_esc(l)}</b> {_esc(d)}</li>' for l, d in pairs if d)
    return _head(slide) + f'<div class="slide__body org-layout">{"".join(parts)}<ul class="org-details">{details}</ul></div>'


def r_portfolio(slide, f):
    """유사 수행 사례 = 체크 마크 케이스 카드. 얇은 서술도 안전(수치 조작 없음)."""
    items = [_split_label(c) for c in (f.get("cases") or _body(slide)) if c]
    items = [p for p in items if p[0]]
    if not items:
        return r_content(slide, f)
    cards = "".join('<div class="case-card"><span class="case-mark">✓</span>'
                    f'<div class="case-txt">{("<b>"+_esc(l)+"</b> "+_esc(d)) if d else _esc(l)}</div></div>'
                    for l, d in items)
    return _head(slide) + f'<div class="slide__body case-grid">{cards}</div>'


def _targets_grid(body) -> str:
    """body가 '라벨: 값' 목록이면 정량 목표 카드 그리드, 아니면 ''(비대비 콘텐츠 안전 처리)."""
    pairs = [_split_label(b) for b in (body or [])]
    pairs = [p for p in pairs if p[0] and p[1]]
    if len(pairs) < 2:
        return ""
    cards = "".join(f'<div class="target-card"><div class="target-lab">{_esc(l)}</div>'
                    f'<div class="target-val">{_esc(v)}</div></div>' for l, v in pairs)
    return f'<div class="slide__body target-grid">{cards}</div>'


def r_closing(slide, f):
    com = f.get("commitments") or _body(slide)
    proof = f.get("proof_points", [])
    cards = "".join(f'<div class="card"><h4>{_esc(c)}</h4>{_esc(proof[i] if i < len(proof) else "")}</div>' for i, c in enumerate(com))
    return _head(slide) + f'<div class="cards">{cards}</div>'


def r_fallback(slide, f):
    body = "\n".join(_esc(b) for b in (slide.get("body") or []))
    return (_head(slide) +
            f'<div class="review">🔴 <b>미지원 템플릿:</b> {_esc(slide.get("template_id"))} (fallback)</div>'
            f'<div class="slide__body dump">{body}\n\n{_esc(json.dumps(f, ensure_ascii=False, indent=2))}</div>')


REGISTRY: dict[str, Callable] = {
    "cover": r_cover, "problem_intro": r_problem, "card_grid": r_summary,
    "data_chart": r_data, "contrast_diagram": r_contrast, "closing_matrix": r_closing,
    "funnel": r_funnel, "funnel_3stage": r_funnel,
    "org_roles": r_org, "org_chart": r_org,
    "portfolio_cases": r_portfolio, "portfolio_case": r_portfolio,
    "content": r_content,
    # matrix_priority: 팩에선 renderer=null이지만 엔진이 generic 매트릭스 제공
    "matrix_priority": r_matrix, "decision": r_matrix,
    # role 별칭(정본 role로도 디스패치 가능)
    "summary": r_summary, "strategy": r_pillars, "data": r_data,
    "contrast": r_contrast, "closing": r_closing, "problem_questions": r_problem,
}

def _load_plugin_layouts(pack_names: "list[str] | None" = None) -> "tuple[dict, str]":
    """레이아웃 모듈(layouts_<pack>.py) 흡수 — **카탈로그 조건부**(오염 차단, 결정 11·12).

    각 모듈은 `LAYOUTS = {renderer_name: fn(slide, f)->str}` 와 선택 `CSS = "..."`를 export.
    - 로드 순서 = 카탈로그 역순(타깃 팩 우선 — 하우스 덱의 레거시 재현성) → `layouts_core`(중립 구현).
    - 반환 = (per-call 렌더러 맵, 누적 CSS). 전역 REGISTRY는 변형하지 않고 엔진 내장이 항상 최우선.
    - 카탈로그에 없는 하우스 모듈(layouts_house_a 등)은 **로드 자체를 안 한다** —
      core 덱에 하우스 코드·CSS가 흡수되던 구멍 봉쇄.
    """
    import importlib
    import sys
    here = str(Path(__file__).resolve().parent)   # app/render — 스크립트·패키지 양쪽서 import 가능하게
    if here not in sys.path:
        sys.path.insert(0, here)
    reg = dict(REGISTRY)
    extra_css = ""
    mod_names = [f"layouts_{n}" for n in reversed(pack_names or [])] + ["layouts_core"]
    seen: set[str] = set()
    for mod_name in mod_names:
        if mod_name in seen:
            continue
        seen.add(mod_name)
        mod = None
        for cand in (mod_name, f"render.{mod_name}"):
            try:
                mod = importlib.import_module(cand)
                break
            except Exception:
                continue
        if mod is None:
            continue
        # W32 마찰28: 레이아웃 모듈은 bare name으로 로드되지만 htmlgen 자신은 패키지 컨텍스트일 수도
        # 있다 — 그러면 text_coerce가 서로 다른 인스턴스가 되고 코어스 **기록만** 조용히 유실된다
        # (출력은 정상). 같은 인스턴스로 묶어 경고 유실을 막는다.
        if hasattr(mod, "_as_text"):
            mod._as_text = _as_text
        for name, fn in (getattr(mod, "LAYOUTS", {}) or {}).items():
            reg.setdefault(name, fn)   # 엔진 기본 우선, 빈 자리만 채움
        extra_css += getattr(mod, "CSS", "") or ""
    return reg, extra_css


# W32 마찰35: 뷰어 동작은 viewer 모듈 한 곳 — 같은 run의 두 검토 표면(deck.html·deck.images.html)이
# 서로 다른 뷰어를 갖던 이중 구현을 없앤다(문자열은 불변이라 deck.html 바이트도 그대로).
try:
    from .viewer import NAV_JS as _NAV_JS   # 패키지 컨텍스트
except ImportError:
    from viewer import NAV_JS as _NAV_JS    # top-level(sys.path에 app/render)


# --- 3축 분리: 카탈로그(②) / 스킨(③) 로더 -------------------------------

def _catalog_names(catalog: "str | list[str] | None") -> list[str]:
    """카탈로그 인자 → 팩 이름 리스트. None = 활성 packs/ 전체(격리 packs_excluded/는 열거 제외)."""
    if catalog is None:
        return sorted(p.name for p in PACKS.iterdir() if p.is_dir())
    if isinstance(catalog, str):
        return [catalog]
    return list(catalog)


def _load_catalog(catalog: "str | list[str] | None") -> dict[str, dict]:
    """②카탈로그 = template_id→정의 맵. 여러 팩의 templates.json을 캐스케이드 병합.

    catalog:
      - None      → 모든 팩을 이름순 병합(공유 어휘 전체).
      - str       → 그 팩 하나.
      - list[str] → 나열 순서대로 병합(**뒤가 앞을 덮음** = id 충돌 시 뒤 팩 우선).
    한 덱이 여러 팩의 template_id를 섞어 써도(예: house_a 스킨 + house_b 레이아웃)
    tdef/renderer가 정상 해석된다. 스킨(tokens)과는 독립.
    """
    names = _catalog_names(catalog)
    tmap: dict[str, dict] = {}
    for name in names:
        templates = _load(_pack_dir(name) / "templates.json")
        items = templates.get("templates", templates) if isinstance(templates, dict) else templates
        for t in (items or []):
            if isinstance(t, dict) and t.get("id"):
                tmap[t["id"]] = t
    return tmap


def _deep_merge(base: dict, over: dict) -> dict:
    """중첩 dict 캐스케이드 병합(in place). over가 base를 덮되, 양쪽이 dict면 재귀."""
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def _resolve_skin(src: "dict | str | Path") -> dict:
    """스킨 소스 1개 → tokens dict.

    src:
      - dict          → 그대로(인라인 tokens).
      - .json 경로    → 그 파일 로드.
      - 스킨 이름(str) → skins/<name>.json 우선(독립 스킨 레지스트리).
      - 팩 이름(str)   → packs/<name>/tokens.json(레거시 폴백).
    """
    if isinstance(src, dict):
        return src
    p = Path(src)
    if p.suffix == ".json" and p.exists():
        return _load(p)
    skin_file = SKINS / f"{src}.json"
    if skin_file.exists():
        return _load(skin_file)
    return _load(_pack_dir(src) / "tokens.json")


def _cascade_skins(skins: "list | None") -> dict:
    """③스킨 = tokens. 리스트를 순서대로 **캐스케이드 병합**(뒤가 앞을 덮음, CSS처럼).

    부분(partial) 스킨 허용 → `[base, 예시스튜디오, 고객]`처럼 겹치면
    "A의 색 + B의 폰트" 조합이 자연스럽다.
    """
    merged: dict = {}
    for src in (skins or []):
        _deep_merge(merged, _resolve_skin(src))
    return merged


_LOGO_MIME = {".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def _brand_logo_data_uri(path: str, run_dir: "Path | None", warnings: list, label: str) -> "str | None":
    """로고 경로 해석: 절대경로 그대로 / 상대경로는 repo 루트→run 디렉토리 순 탐색.

    실자산이 없으면 절대 placeholder를 만들지 않는다 — warnings에 표면화하고 None을 돌려준다.
    """
    p = Path(path)
    candidates = [p] if p.is_absolute() else [ROOT / p]
    if not p.is_absolute() and run_dir is not None:
        candidates.append(run_dir / p)
    for cand in candidates:
        if cand.is_file():
            mime = _LOGO_MIME.get(cand.suffix.lower(), "image/png")
            data = base64.b64encode(cand.read_bytes()).decode("ascii")
            return f"data:{mime};base64,{data}"
    warnings.append(f"brand: {label} 파일 없음: {path} (로고=실자산 필수, 생성 금지 - 이름 텍스트로만 표기)")
    return None


def _brand_mark_html(name: "str | None", logo_path: "str | None", css_cls: str,
                      run_dir: "Path | None", warnings: list, label: str) -> str:
    """제안사/클라이언트 마크 1개 조립. name·logo 둘 다 없으면 빈 문자열."""
    if not name and not logo_path:
        return ""
    img_html = ""
    if logo_path:
        src = _brand_logo_data_uri(logo_path, run_dir, warnings, label)
        if src:
            img_html = f'<img src="{src}" alt="{_esc(name or "")}">'
    name_html = f"<span>{_esc(name)}</span>" if name else ""
    return f'<div class="slide__brand {css_cls}">{img_html}{name_html}</div>'


def _brand_applies(placement_value: "str | None", cls: str) -> bool:
    if placement_value == "all":
        return True
    if placement_value == "cover":
        return cls == "cover"
    return False   # "none" 또는 미인식 값


def render(deck: dict, catalog: "str | list[str] | None" = None,
           skins: "list | None" = None, out_path: "str | Path | None" = None,
           *, body_class: "str | None" = None, overrides: "dict | None" = None) -> dict:
    """3축 분리 렌더 진입점: 덱 + 카탈로그(②) + 스킨(③, 캐스케이드) → HTML.

    - skins: tokens 소스 리스트(dict/경로/팩이름). 순서대로 캐스케이드 병합 후 CSS 변수 주입.
    - catalog: template_id 어휘(팩 이름/리스트/None=전체). 스킨과 독립.
    - body_class: <body class="pack-…"> 스코프(팩별 CSS 격리용). 없으면 미부여.
    하위호환은 render_html()이 이 함수로 위임.
    """
    tokens = _cascade_skins(skins)
    _names = _catalog_names(catalog)
    tmap = _load_catalog(catalog)

    reg, plugin_css = _load_plugin_layouts(_names)   # 레이아웃 모듈 흡수 — 카탈로그 조건부(결정 11·12)
    slides = deck.get("slides", [])
    total = len(slides)
    _coerced.clear()   # W32 마찰28: 렌더 경계에서 초기화(슬라이드 0개인 덱도 누수 없음)
    review_notes: list[str] = []   # W32 마찰31: 장표에 안 그리는 검수 신호(warnings와 등급이 다르다)
    meta_line = _esc((deck.get("meta") or {}).get("project", ""))   # 우측 메타 라인(상단 크롬)
    warnings: list[str] = []
    out_sections = []
    # stage9 override(디자인 디렉터): 슬라이드별 css/class/append_html + global_css. append-only·css만 → SSOT 안전.
    ov_all = overrides or {}
    ov_slides = ov_all.get("slides") or {}
    ov_css_parts: list[str] = []
    if ov_all.get("global_css"):
        ov_css_parts.append(str(ov_all["global_css"]))
    # 이미지 슬롯(B-9): run_dir = 출력 위치(자산 stage9_design/slots/ 탐색용). 슬롯 있으면 스킨 css 1회 주입.
    _run_dir = Path(out_path).parent if out_path else None
    _img_mod = _image_slots_mod()
    if _img_mod.has_any_slots(ov_all):
        ov_css_parts.append(_img_mod.SLOT_CSS)
    # W22 브랜드 크롬(통찰 14): 4개 필드 중 하나라도 truthy일 때만 마크 조립(무브랜드 덱은 완전 불변).
    brand = tokens.get("brand") or {}
    brand_used = False
    proposer_mark_html = client_mark_html = ""
    placement_client = placement_proposer = None
    if any(brand.get(k) for k in ("client_name", "client_logo", "proposer_name", "proposer_logo")):
        placement = brand.get("placement") or {}
        placement_client = placement.get("client", "cover")
        placement_proposer = placement.get("proposer", "all")
        proposer_mark_html = _brand_mark_html(
            brand.get("proposer_name"), brand.get("proposer_logo"), "slide__brand--proposer",
            _run_dir, warnings, "proposer_logo")
        client_mark_html = _brand_mark_html(
            brand.get("client_name"), brand.get("client_logo"), "slide__brand--client",
            _run_dir, warnings, "client_logo")
    for n, s in enumerate(slides, 1):
        fields = dict(s.get("fields") or {})
        _coerced.clear()   # W32 마찰28: 이 슬라이드가 만든 코어스만 수거한다
        if s.get("frame") or s.get("preset"):
            # W21-0 조합 엔진: frame 또는 preset 선언 슬라이드는 template_id 대신 골격×조각으로
            # 렌더(결정 12). preset 확장(§6 동급 참여)은 compose.render_slide 내부에서 처리한다.
            cls = ""
            try:
                inner = _compose_mod().render_slide(s, warnings)
            except Exception as exc:
                warnings.append(
                    f"slide {s.get('slide_id')}: compose 렌더 실패({type(exc).__name__}: {exc}) → fallback"
                )
                inner = r_fallback(s, fields)
        else:
            tid = s.get("template_id")
            tdef = tmap.get(tid) if tid else None
            # 렌더러 선택 우선순위: 팩 templates의 renderer → 명시 template_id → role → fallback.
            # (명시 template_id가 실제 렌더러명이면 generic role 폴백보다 우선해야 한다.
            #  안 그러면 role=summary/strategy/data 슬라이드가 house_b tid 렌더러를 가로챈다.)
            rname = (tdef or {}).get("renderer")
            fn = reg.get(rname) or reg.get(tid or "") or reg.get(s.get("role", ""))
            if fn is None and not tid:
                # stage5 storyline처럼 아직 레이아웃 선택 전인 정본은 안전한 generic 본문.
                fn = reg["content"]
            cls = "cover" if (s.get("role") == "cover" or rname == "cover") else ""
            if fn is None:
                warnings.append(f"slide {s.get('slide_id')}: '{tid}' 미지원 → fallback")
                inner = r_fallback(s, fields)
            else:
                try:
                    inner = fn(s, fields)
                except Exception as exc:  # fields 값 오형식(예: comparison이 문자열) — 조용한 폴백 금지, 경고로 표면화.
                    warnings.append(
                        f"slide {s.get('slide_id')}: '{rname or tid}' 렌더 실패({type(exc).__name__}: {exc}) → fallback"
                    )
                    inner = r_fallback(s, fields)
        # W32 마찰28: 문자열 자리에 들어온 객체·배열은 코어스로 살렸지만 조용히 넘기지 않는다 —
        # 원인은 상류 storyline의 shape 오답이므로 고칠 곳도 거기다(중복 메시지는 접어서 1건).
        for msg in dict.fromkeys(_coerced):
            warnings.append(f"slide {s.get('slide_id')}: fields shape 불일치 — {msg}")
        _coerced.clear()
        review_notes.extend(_compose_mod().drain_notes())   # W32 마찰31: 검수 채널(결함 아님)
        # override 매칭 키(자산 경로는 fill과 동일 키를 써야 함): slide_id 우선, 없으면 1-기반 n.
        sid_key = str(s.get("slide_id", ""))
        matched_key = sid_key if sid_key in ov_slides else (str(n) if str(n) in ov_slides else sid_key)
        ov = ov_slides.get(sid_key) or ov_slides.get(str(n)) or {}
        if ov.get("css"):
            ov_css_parts.append(f"/* slide-{n} */\n{ov['css']}")
        slots_html = ""
        if ov.get("image_slots"):
            slots_html = _img_mod.resolve_slots_html(ov.get("image_slots"), matched_key, _run_dir)
        brand_html = ""
        if proposer_mark_html and _brand_applies(placement_proposer, cls):
            brand_html += proposer_mark_html
        if client_mark_html and _brand_applies(placement_client, cls):
            brand_html += client_mark_html
        if brand_html:
            brand_used = True
        out_sections.append(_frame(inner, n=n, total=total, slide=s, cls=cls, meta=meta_line,
                                   override=ov, slots_html=slots_html, brand_html=brand_html))

    title = _esc((deck.get("meta") or {}).get("project", "제안 덱"))
    body_attr = f' class="pack-{body_class}"' if body_class else ""
    ov_css = ("\n" + "\n".join(ov_css_parts)) if ov_css_parts else ""
    # W9: 예시 라벨 CSS는 예시 슬라이드가 있을 때만 얹는다(없는 덱은 style 바이트 불변).
    example_css = _EXAMPLE_CSS if any(s.get("example") for s in slides) else ""
    # W21-0: 조합 CSS도 frame 슬라이드가 있을 때만(무프레임 덱은 style 바이트 불변).
    compose_css = _compose_mod().CSS if any(s.get("frame") for s in slides) else ""
    # W22: 브랜드 CSS도 실제로 마크업이 생성됐을 때만(무브랜드 덱은 style 바이트 불변).
    brand_css = _BRAND_CSS if brand_used else ""
    # W31 γ패킷(마찰25): 제목 auto-fit CSS도 실제로 축소 클래스가 붙은 장이 있을 때만(짧은
    # 제목뿐인 덱은 style 바이트 불변 — _EXAMPLE_CSS/_BRAND_CSS와 동일한 조건부 주입 패턴).
    title_fit_used = any(_title_fit_class(_effective_title(s)) for s in slides)
    title_fit_css = _TITLE_FIT_CSS if title_fit_used else ""
    doc = (f'<!doctype html><html lang="ko"><head><meta charset="utf-8">'
           f'<meta name="viewport" content="width=device-width, initial-scale=1">'
           f'<title>{title}</title><style>{_base_css(tokens)}{plugin_css}{compose_css}{ov_css}{example_css}{brand_css}{title_fit_css}</style></head><body{body_attr}>'
           + "".join(out_sections) + _NAV_JS + "</body></html>")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    report = {"out": str(out), "slides": total, "warnings": warnings, "bytes": len(doc.encode("utf-8"))}
    if review_notes:   # 있을 때만 실어 기존 리포트 소비자에 영향 없음(마찰31 검수 채널)
        report["review_notes"] = review_notes
    return report


def render_html(deck: dict, pack_name: str, out_path: str | Path,
                overrides: "dict | None" = None, skins: "list | None" = None) -> dict:
    """하위호환 래퍼: (deck, pack) → render(). 팩=스킨+카탈로그가 한 폴더인 레거시 경로.

    카탈로그는 기존 동작 유지 = 모든 팩 병합 + 활성 팩을 마지막에 둬 id 충돌 시 우선.
    스킨은 활성 팩 tokens를 base로 깔고, skins= 를 주면 그 위에 캐스케이드(뒤가 앞을 덮음).
    (skins 미지정 시 기존 동작과 완전히 동일 — pptx의 dispatch._cascade_tokens와 같은 규칙.)
    body_class는 기존대로 house_a만 스코프.
    overrides: stage9 디자인 디렉터 override(dict) — 있으면 병합.
    """
    others = sorted(p.name for p in PACKS.iterdir() if p.is_dir() and p.name != pack_name)
    return render(
        deck,
        catalog=others + [pack_name],
        skins=[pack_name] + list(skins or []),
        out_path=out_path,
        body_class=pack_name if pack_name == "house_a" else None,
        overrides=overrides,
    )


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 4:
        print("사용: python app/render/htmlgen.py <deck.json> <pack> <out.html> [design_overrides.json]")
        raise SystemExit(1)
    _ov = _load(Path(sys.argv[4])) if len(sys.argv) > 4 else None
    rep = render_html(_load(Path(sys.argv[1])), sys.argv[2], sys.argv[3], overrides=_ov)
    print(json.dumps(rep, ensure_ascii=False, indent=2))
