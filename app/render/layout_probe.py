# -*- coding: utf-8 -*-
"""W6-A1 브라우저 실측 계층 — `design_checks.browser` (LLM 0토큰).

`design_checks`(정적 파싱)의 원리적 맹점을 메운다: **절대배치·z-index·폰트 메트릭**은
마크업 문자열에 없다. 그래서 "overflow_risk=0"이라던 덱에서 슬롯이 차트를 덮고 있었다
(2026-07-08 정주행 마찰 로그). 여기서는 실제 브라우저에 띄워 **사각형을 잰다.**

**정직성 계약**
- 의존성은 `rasterize`와 동일(playwright+chromium). 없으면 `status="unmeasured"` —
  **가짜 pass 금지.** 미설치는 "결함 없음"이 아니라 "안 봤음"이다.
- 좌표계 = 래스터 뷰포트(1280×720). `html_to_slide_pngs`가 굽는 PNG의 좌표계와 같다 →
  리포트의 픽셀이 곧 사람이 보게 될 PNG의 픽셀이다. 다른 창 크기에서의 결과는 다를 수 있다
  (슬라이드가 `vw/vh` 기반이므로) — 그 한계를 `method`에 적는다.
- 오버플로는 두 프로브를 **둘 다** 잰다:
  * `scroll_overflow_px` = scrollHeight-clientHeight (마찰 로그가 쓴 프로브).
  * `content_overflow_px` = 자손 사각형이 슬라이드 경계 밖으로 나간 픽셀.
    `overflow:hidden`이 걸린 슬라이드에서는 scrollHeight가 자라지 않는다 → 이 프로브가 정본.
- 교차는 **두 신호로 분리**한다(하나로 뭉치면 오탐/미탐이 섞인다):
  * `slot_occlusion` = 슬롯이 본문 **위에** 그려진다(겹친 영역 중심의 히트테스트가 슬롯).
    이 조건이 없으면 커버의 배경 워시 슬롯(z-index 아래·의도된 장식)이 전부 오탐이 된다.
  * `slot_overlaps_content` = 페인트 순서와 무관하게 슬롯 사각형이 **본문 상자**(차트/그림 ∪
    테두리·배경이 실제로 칠해지는 카드/패널)를 침범한다. 차트 컨테이너는 배경이 투명해
    히트테스트가 슬롯을 못 보는 일이 흔하다 — 그래도 슬롯이 차트의 자리에 들어앉은 것은 충돌이다.
    투명 래퍼(`.slide__body`)와 렌더러 크롬(`.review`·`.pagenum`)은 본문이 아니라 세지 않는다.
    단 **전면 배경 슬롯**(슬라이드 면적의 25% 이상 = 커버/클로징의 무드 워시)은 겹치는 게
    설계이므로 이 신호에서 제외한다(그 경우에도 위 `slot_occlusion`은 그대로 감시한다).
- 임계값은 **잠정(미교정)**. 게이트는 여전히 차단하지 않는다(warn까지) — 숫자가 좋아지면 의심하라.
"""
from __future__ import annotations

import json
from pathlib import Path

SCHEMA_VERSION = 1

VIEWPORT_W = 1280
VIEWPORT_H = 720
TOLERANCE_PX = 4            # 서브픽셀·경계선 두께 잡음
MIN_OCCLUSION_RATIO = 0.05  # 대상 요소 면적의 5% 이상을 덮으면 신고(스침 제외)
MIN_OVERLAP_PX = 2000       # 또는 절대 면적 2000px²(≈45×45) 이상 — 작은 배지도 잡는다
BACKGROUND_AREA_RATIO = 0.25  # 슬라이드 면적의 이 비율 이상인 슬롯 = 전면 배경(무드 워시)
MIN_VOID_HEIGHT_PX = 240     # 이보다 작은 행/제목 블록은 영역 공허 판정에서 제외
MIN_VOID_RATIO = 0.5         # 블록 높이 중 가시 콘텐츠 bbox 합높이가 차지하지 못한 비율

# 차트/그림 "상자". `[class*=data]`가 이 저장소의 데이터 슬라이드 컨테이너(`.data.data-panel`)다.
FIGURE_SELECTOR = 'svg, canvas, img, table, [class*="chart"], [class*="data"], [class*="graph"]'
# 렌더러 크롬(본문이 아니다): 검토 배지·페이지번호·상단 바/메타. 슬롯이 여기 걸치는 건 별도 문제다.
CHROME_SELECTOR = '.review, .pagenum, .slide__bar, .slide__meta'

_JS = r"""
(cfg) => {
  const {minRatio, minArea, figureSelector, chromeSelector, bgRatio} = cfg;
  const isLeafText = (e) => e.children.length === 0 && (e.textContent || '').trim().length > 0;
  const cls = (e) => (typeof e.className === 'string' ? e.className : (e.className?.baseVal || ''));
  const rectOf = (e) => e.getBoundingClientRect();
  const overlap = (a, r) => {
    const ox = Math.max(0, Math.min(a.right, r.right) - Math.max(a.left, r.left));
    const oy = Math.max(0, Math.min(a.bottom, r.bottom) - Math.max(a.top, r.top));
    return {ox, oy, area: ox * oy};
  };
  const label = (e) => e.tagName.toLowerCase() + (cls(e) ? '.' + cls(e).trim().split(/\s+/)[0] : '');
  const out = [];
  // 덱 CSS는 `scroll-behavior: smooth`를 쓴다 → 스크롤이 비동기라 즉시 측정하면 좌표가 안 맞는다.
  // 히트테스트(elementFromPoint)는 **뷰포트 좌표**만 받으므로 스크롤이 실제로 끝나야 한다.
  const prevBehavior = document.documentElement.style.scrollBehavior;
  document.documentElement.style.scrollBehavior = 'auto';
  const sections = [...document.querySelectorAll('section.slide')];
  sections.forEach((s, i) => {
    window.scrollTo(0, s.offsetTop);  // 히트테스트는 뷰포트 좌표계다
    const sr = s.getBoundingClientRect();
    let maxBottom = -1e9, maxRight = -1e9;
    s.querySelectorAll('*').forEach(e => {
      const r = e.getBoundingClientRect();
      if (!r.width || !r.height) return;
      const st = getComputedStyle(e);
      if (st.visibility === 'hidden' || parseFloat(st.opacity) === 0) return;
      if (r.bottom > maxBottom) maxBottom = r.bottom;
      if (r.right > maxRight) maxRight = r.right;
    });

    const slots = [...s.querySelectorAll('.dov-slot')];
    const targets = [...s.querySelectorAll('*')].filter(e => {
      if (e.closest('.dov-slot')) return false;          // 슬롯 자신의 자식(SVG 등)은 대상 아님
      if (e.getAttribute('aria-hidden') === 'true') return false;  // 장식(워시·룰)
      const st = getComputedStyle(e);
      if (st.visibility === 'hidden' || parseFloat(st.opacity) === 0) return false;
      const t = e.tagName.toLowerCase();
      return ['svg', 'canvas', 'img', 'table'].includes(t) || isLeafText(e);
    });
    const textTargets = targets.filter(isLeafText);      // 가림·가독성 판정은 텍스트만 본다

    // 본문 상자 = 차트/그림 ∪ **실제로 칠해지는 상자**(테두리·배경이 있는 카드/패널).
    // 투명 래퍼(`.slide__body` 같은 레이아웃 컨테이너)는 그 안의 빈 자리에 슬롯이 놓여도
    // 충돌이 아니다 → 칠해지는 상자만 센다. 렌더러 크롬(검토 배지·페이지번호·상단 바)은 본문이 아니다.
    const visible = (e) => {
      const st = getComputedStyle(e);
      return st.visibility !== 'hidden' && parseFloat(st.opacity) !== 0
             && e.getAttribute('aria-hidden') !== 'true';
    };
    const painted = (e) => {
      const st = getComputedStyle(e);
      if (st.backgroundImage !== 'none') return true;
      const bg = st.backgroundColor;
      if (bg && !/rgba\(0,\s*0,\s*0,\s*0\)|transparent/.test(bg)) return true;
      return ['Top', 'Right', 'Bottom', 'Left'].some(
        d => parseFloat(st['border' + d + 'Width']) > 0 && st['border' + d + 'Style'] !== 'none');
    };
    const boxes = [...new Set([
      ...s.querySelectorAll(figureSelector),
      ...[...s.querySelectorAll('*')].filter(painted),
    ])].filter(e => !e.closest('.dov-slot') && !e.closest(chromeSelector) && visible(e));

    const slideArea = Math.max(1, sr.width * sr.height);
    const isBackground = (e, r) => {
      const declared = e.getAttribute('data-layer') === 'background';
      const legacyWash = e.classList && e.classList.contains('dov-slot')
                         && (r.width * r.height) / slideArea >= bgRatio;
      return declared || legacyWash;
    };
    // 가독성 treatment 후보 = 배경 위에 얹히는 페인트 요소(스크림/반투명 패널·솔리드 패널).
    //   포함: `.dov-slot__scrim`(슬롯 내부지만 명시적 오버레이) · 슬롯 밖의 painted 요소.
    //   제외: 슬롯 컨테이너 자체·자산(img/svg) — 그건 배경이지 가독성 처리가 아니다.
    // 스크림·오버레이는 대개 aria-hidden(순수 장식)이지만 그게 곧 가독성 처리다 →
    //   여기선 aria-hidden을 제외하지 않는다(visible 대신 표시상태만 본다).
    const shown = (e) => {
      const st = getComputedStyle(e);
      return st.visibility !== 'hidden' && parseFloat(st.opacity) !== 0 && st.display !== 'none';
    };
    const treatments = [...s.querySelectorAll('*')].filter(e => {
      if (e.classList && e.classList.contains('dov-slot')) return false;
      if (e.closest('.dov-slot') && !(e.classList && e.classList.contains('dov-slot__scrim'))) return false;
      return shown(e) && painted(e);
    });
    const occlusions = [], contentOverlaps = [], readability = [];
    slots.forEach(slot => {
      const a = rectOf(slot);
      if (!a.width || !a.height) return;
      if (slot.getAttribute('aria-hidden') === 'true') return;
      const declaredBg = slot.getAttribute('data-layer') === 'background';   // 결정 6: 선언된 배경
      const backgroundSlot = isBackground(slot, a);  // 선언 배경 + 면적 기반 레거시 워시
      const pe = slot.style.pointerEvents;
      slot.style.pointerEvents = 'auto';  // 페인트는 하는데 히트테스트에 안 잡히는 슬롯을 보이게
      targets.forEach(t => {
        const r = rectOf(t);
        if (!r.width || !r.height) return;
        const {ox, oy, area} = overlap(a, r);
        if (area <= 0) return;
        const ratio = area / (r.width * r.height);
        if (ratio < minRatio && area < minArea) return;
        const cx = Math.max(a.left, r.left) + ox / 2;
        const cy = Math.max(a.top, r.top) + oy / 2;
        const hit = document.elementFromPoint(cx, cy);
        if (!hit || !(hit === slot || slot.contains(hit))) return;  // 슬롯이 아래 = 의도된 배경
        occlusions.push({
          slot: cls(slot), target: label(t),
          target_text: (t.textContent || '').trim().slice(0, 40),
          overlap_px: Math.round(area), ratio: Math.round(ratio * 1000) / 1000,
        });
      });
      if (!backgroundSlot) boxes.forEach(f => {        // 전면/선언 배경 = 겹침이 설계 → 제외
        if (f.contains(slot) || slot.contains(f)) return;
        const r = rectOf(f);
        if (!r.width || !r.height) return;
        const {area} = overlap(a, r);
        if (area < minArea) return;  // 페인트 순서 무관 — 본문 상자 침범 자체가 충돌
        contentOverlaps.push({
          slot: cls(slot), box: label(f),
          overlap_px: Math.round(area),
          ratio: Math.round(area / (r.width * r.height) * 1000) / 1000,
        });
      });
      else if (declaredBg) {
        // 선언된 배경은 겹침 결함 대신 **가독성 실측**: 배경과 겹치는 텍스트가 오버레이/패널로
        //   덮여 있는가. 자기보고(data-treatment)를 믿지 않고 실제 오버레이 DOM을 잰다 —
        //   덮는 treatment가 없으면 background_no_treatment(선언만으로 pass 금지).
        textTargets.forEach(t => {
          const r = rectOf(t);
          if (!r.width || !r.height) return;
          const {area} = overlap(a, r);
          if (area < minArea) return;                    // 배경과 겹치는 텍스트만 대상
          const tarea = Math.max(1, r.width * r.height);
          const covered = treatments.some(ov => {
            if (ov === t || ov.contains(t) || t.contains(ov)) return false;
            const {area: oa} = overlap(rectOf(ov), r);
            return oa >= 0.6 * tarea;                     // 텍스트의 60%↑를 덮는 오버레이/패널
          });
          if (!covered) readability.push({
            slot: cls(slot), target: label(t),
            target_text: (t.textContent || '').trim().slice(0, 40),
          });
        });
      }
      slot.style.pointerEvents = pe;
    });

    // 디렉터 장식(dov-* 중 슬롯이 아닌 것)의 텍스트 가림 — 실측 사례: slide5 오렌지 화살표가
    //   전환 문구를 덮었으나 현 probe 미검출(슬롯만 봤다). 슬롯과 같은 히트테스트로 확장한다.
    const decos = [...s.querySelectorAll('[class*="dov-"]')].filter(e =>
      !(e.classList && e.classList.contains('dov-slot')) && !e.closest('.dov-slot'));
    const decoOcclusions = [];
    decos.forEach(d => {
      const a = rectOf(d);
      if (!a.width || !a.height) return;
      const pe = d.style.pointerEvents;
      d.style.pointerEvents = 'auto';
      textTargets.forEach(t => {
        const r = rectOf(t);
        if (!r.width || !r.height) return;
        const {ox, oy, area} = overlap(a, r);
        if (area <= 0) return;
        const ratio = area / (r.width * r.height);
        if (ratio < minRatio && area < minArea) return;
        const cx = Math.max(a.left, r.left) + ox / 2;
        const cy = Math.max(a.top, r.top) + oy / 2;
        const hit = document.elementFromPoint(cx, cy);
        if (!hit || !(hit === d || d.contains(hit))) return;   // 장식이 텍스트 위 = 가림
        decoOcclusions.push({
          deco: cls(d), target: label(t),
          target_text: (t.textContent || '').trim().slice(0, 40),
          overlap_px: Math.round(area), ratio: Math.round(ratio * 1000) / 1000,
        });
      });
      d.style.pointerEvents = pe;
    });

    // 영역 공허: 슬라이드 직계 블록과 그 직계 grid/flex 항목을 잰다. 장식/선언 배경은
    // 후보 데이터에 남기되 Python 임계 판정에서 제외해 브라우저 없는 테스트도 같은 경로를 탄다.
    const blockSet = new Set([...s.children]);
    [...s.children].forEach(parent => {
      const display = getComputedStyle(parent).display || '';
      if (display.includes('grid') || display.includes('flex')) {
        [...parent.children].forEach(child => blockSet.add(child));
      }
    });
    const voidCandidates = [...blockSet].map((b, bi) => {
      const r = rectOf(b);
      const height = b.clientHeight;
      if (b.matches(chromeSelector) || b.closest(chromeSelector)
          || b.getAttribute('aria-hidden') === 'true' || !visible(b)
          || !r.width || !r.height || !height) return null;
      const content = targets.filter(t => b.contains(t));
      const contentHeight = content.reduce((sum, e) => sum + rectOf(e).height, 0);
      return {
        selector: label(b) || `block[${bi}]`,
        height_px: Math.round(height),
        void_ratio: Math.round(Math.max(0, Math.min(1, 1 - contentHeight / height)) * 1000) / 1000,
        has_visible_text: textTargets.some(t => b.contains(t)),
        is_background: isBackground(b, r),
      };
    }).filter(Boolean);

    out.push({
      slide_id: s.id ? s.id.replace(/^slide-/, '') : String(i + 1),
      scroll_height: s.scrollHeight,
      client_height: s.clientHeight,
      scroll_overflow_px: Math.max(0, s.scrollHeight - s.clientHeight),
      content_overflow_px: Math.max(0, Math.round(maxBottom - sr.bottom)),
      content_overflow_x_px: Math.max(0, Math.round(maxRight - sr.right)),
      slots: slots.length,
      occlusions,
      content_overlaps: contentOverlaps,
      decoration_occlusions: decoOcclusions,
      readability,
      void_candidates: voidCandidates,
    });
  });
  document.documentElement.style.scrollBehavior = prevBehavior;
  return out;
}
"""


def available() -> bool:
    """rasterize와 동일 의존성(playwright+chromium)을 그대로 재사용한다 — 두 번째 판정 금지."""
    try:
        import rasterize  # type: ignore
        return bool(rasterize.available())
    except Exception:
        return False


def unavailable_reason() -> str:
    """미가용 사유를 사람 말로(rasterize 판정 재사용). 가용하면 빈 문자열."""
    try:
        import rasterize  # type: ignore
        return str(rasterize.unavailable_reason())
    except Exception as exc:
        return f"래스터라이저 모듈 로드 실패 — {type(exc).__name__}"


_METHOD = (
    "헤드리스 브라우저(playwright/chromium) 실측. 뷰포트 {w}×{h}(= html_to_slide_pngs의 래스터 "
    "좌표계 — 리포트의 픽셀이 곧 PNG의 픽셀). 오버플로 = scrollHeight-clientHeight **및** "
    "자손 사각형이 슬라이드 경계를 넘은 px(overflow:hidden 슬라이드는 후자만 잡힌다). "
    "교차 = (a) slot_occlusion: 면적비 ≥ {r} 또는 겹침 ≥ {a}px² **그리고** 히트테스트가 슬롯 → "
    "배경 워시 슬롯(z-index 아래)은 오탐으로 세지 않는다; (b) slot_overlaps_content: 본문 상자"
    "(슬라이드 직계 자식·차트/그림)와 {a}px² 이상 겹침(페인트 순서 무관 — 투명 컨테이너 탓에 "
    "히트테스트가 못 보는 침범). 단 슬라이드 면적의 {bg:.0%} 이상인 전면 배경 슬롯 또는 "
    "layer=background 선언 슬롯은 (b)에서 제외; (c) decoration_occlusion: 디렉터 장식(dov-* 중 "
    "슬롯 아닌 것)이 텍스트 위에 그려짐(히트테스트); (d) background_no_treatment: layer=background "
    "선언 슬롯 위 텍스트를 덮는 오버레이/패널(가독성 처리)이 실재하지 않음(자기보고 data-treatment "
    "불신 — 실제 오버레이 DOM을 잰다). 영역 공허 = 높이 ≥ {vh}px인 직계 콘텐츠 블록/grid·flex "
    "항목에서 가시 콘텐츠 bbox 합높이 대비 공허율 ≥ {vr:.0%}(가시 텍스트 필수, 배경 제외). "
    "슬라이드가 vw/vh 기반이므로 다른 창 크기에서는 값이 달라질 수 있다."
)


def _unmeasured(reason: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "unmeasured",  # 미측정은 pass 가 아니다
        "reason": reason,
        "method": "미실행 — " + reason,
        "viewport": {"width": VIEWPORT_W, "height": VIEWPORT_H},
        "thresholds": {
            "min_void_height_px": MIN_VOID_HEIGHT_PX,
            "min_void_ratio": MIN_VOID_RATIO,
            "calibration": "잠정(사람 평가와 대조 전)",
        },
        "summary": {"slides": 0, "overflow": 0, "occlusion": 0,
                    "content_overlap": 0, "void": 0},
        "slides": [],
    }


def _summarize_rows(rows: list[dict], *, tolerance_px: int = TOLERANCE_PX,
                    min_void_height_px: int = MIN_VOID_HEIGHT_PX,
                    min_void_ratio: float = MIN_VOID_RATIO) -> tuple[list[dict], dict]:
    """JS 원시 행에 임계·플래그·집계를 적용한다(브라우저 없는 회귀 테스트의 단일 경로)."""
    slides: list[dict] = []
    for raw in rows:
        row = dict(raw)
        flags: list[str] = []
        over = max(row.get("scroll_overflow_px", 0), row.get("content_overflow_px", 0))
        if over > tolerance_px:
            flags.append("overflow_measured")
        if row.get("content_overflow_x_px", 0) > tolerance_px:
            flags.append("overflow_measured_x")
        if row.get("occlusions"):
            flags.append("slot_occlusion")
        if row.get("content_overlaps"):
            flags.append("slot_overlaps_content")
        if row.get("decoration_occlusions"):
            flags.append("decoration_occlusion")
        if row.get("readability"):
            flags.append("background_no_treatment")

        void_blocks = []
        for i, block in enumerate(row.pop("void_candidates", []) or []):
            height_px = float(block.get("height_px", 0) or 0)
            void_ratio = float(block.get("void_ratio", 0) or 0)
            if (height_px < min_void_height_px or void_ratio < min_void_ratio
                    or not block.get("has_visible_text") or block.get("is_background")):
                continue
            void_blocks.append({
                "selector": block.get("selector") or f"block[{i}]",
                "height_px": round(height_px),
                "void_ratio": round(void_ratio, 3),
            })
        if void_blocks:
            flags.append("void_measured")
        row["void_blocks"] = void_blocks
        row["overflow_px"] = over
        row["flags"] = flags
        slides.append(row)

    summary = {
        "slides": len(slides),
        "overflow": sum(1 for s in slides if "overflow_measured" in s["flags"]
                        or "overflow_measured_x" in s["flags"]),
        "occlusion": sum(1 for s in slides if "slot_occlusion" in s["flags"]),
        "content_overlap": sum(1 for s in slides if "slot_overlaps_content" in s["flags"]),
        "decoration_occlusion": sum(
            1 for s in slides if "decoration_occlusion" in s["flags"]),
        "background_no_treatment": sum(
            1 for s in slides if "background_no_treatment" in s["flags"]),
        "void": sum(1 for s in slides if "void_measured" in s["flags"]),
    }
    return slides, summary


def probe_html(html_path: str | Path, *, width_px: int = VIEWPORT_W,
               height_px: int = VIEWPORT_H, tolerance_px: int = TOLERANCE_PX,
               min_ratio: float = MIN_OCCLUSION_RATIO,
               min_overlap_px: int = MIN_OVERLAP_PX) -> dict:
    """병합된 deck.html → 브라우저 실측 블록. 실패는 예외가 아니라 `unmeasured`로 말한다."""
    src = Path(html_path)
    if not src.exists():
        return _unmeasured(f"HTML 없음: {src}")
    if not available():
        return _unmeasured(
            unavailable_reason()
            or "playwright 미설치(pip install playwright && playwright install chromium)"
        )
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": width_px, "height": height_px})
            page.goto(src.resolve().as_uri())
            page.wait_for_load_state("networkidle")
            rows = page.evaluate(_JS, {"minRatio": min_ratio, "minArea": min_overlap_px,
                                       "figureSelector": FIGURE_SELECTOR,
                                       "chromeSelector": CHROME_SELECTOR,
                                       "bgRatio": BACKGROUND_AREA_RATIO})
            browser.close()
    except Exception as exc:  # pragma: no cover - 브라우저 환경 사고
        return _unmeasured(f"브라우저 실측 실패: {type(exc).__name__}: {exc}")

    if not rows:
        return _unmeasured(f"슬라이드 셀렉터(section.slide) 0건 매치: {src}")

    slides, summary = _summarize_rows(rows, tolerance_px=tolerance_px)
    flagged = any(row["flags"] for row in slides)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "warn" if flagged else "pass",
        "measured_from": f"{src.name} (헤드리스 브라우저 레이아웃 실측)",
        "method": _METHOD.format(w=width_px, h=height_px, r=min_ratio, a=min_overlap_px,
                                 bg=BACKGROUND_AREA_RATIO, vh=MIN_VOID_HEIGHT_PX,
                                 vr=MIN_VOID_RATIO),
        "viewport": {"width": width_px, "height": height_px},
        "tolerance_px": tolerance_px,
        "min_occlusion_ratio": min_ratio,
        "min_overlap_px": min_overlap_px,
        "background_area_ratio": BACKGROUND_AREA_RATIO,
        "thresholds": {
            "min_void_height_px": MIN_VOID_HEIGHT_PX,
            "min_void_ratio": MIN_VOID_RATIO,
            "calibration": "잠정(사람 평가와 대조 전)",
        },
        "summary": summary,
        "slides": slides,
    }


# W12: 실측 게이트 승격 — "실결함 계열" flag. 이 flag가 붙은 슬라이드는 조용한 warn이 아니라
#   **수리 대상**으로 1급 표시한다(stage9 --apply·status/go·평가 번들 3곳). ship은 여전히
#   막지 않는다(기존 게이트 정책) — 다만 조용히 지나갈 수 없게 한다. slot_overlaps_content는
#   더 보수적 신호(투명 컨테이너 오탐 여지)라 여기서 제외한다 — 마찰 로그가 지목한 4계열만.
REPAIR_FLAGS = (
    "overflow_measured", "overflow_measured_x", "void_measured",
    "slot_occlusion", "decoration_occlusion", "background_no_treatment",
)


def repair_targets(browser: "dict | None") -> list[dict]:
    """browser 실측 블록 → 슬라이드별 수리 대상(실결함 flag만). 미측정/pass면 빈 목록.

    반환 원소 = {"slide_id", "flags"}. 미측정(unmeasured)은 "안 봤음"이지 "결함 없음"이
    아니므로 여기서도 빈 목록이지만, 호출부는 browser.status로 그 사실을 별도 표면화한다.
    """
    if not isinstance(browser, dict):
        return []
    out: list[dict] = []
    for row in browser.get("slides") or []:
        flags = [fl for fl in (row.get("flags") or []) if fl in REPAIR_FLAGS]
        if flags:
            target = {"slide_id": row.get("slide_id"), "flags": flags}
            if "void_measured" in flags:
                target["kind"] = "void"
                target["void_blocks"] = list(row.get("void_blocks") or [])
            out.append(target)
    return out


if __name__ == "__main__":  # 수동 재현용: python layout_probe.py <deck.html>
    import sys
    print(json.dumps(probe_html(sys.argv[1]), ensure_ascii=False, indent=2))
