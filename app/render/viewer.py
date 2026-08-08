# -*- coding: utf-8 -*-
"""검토·발표 표면 공용 뷰어 (W32 마찰35 → 2026-08-02 deck-stage 채택).

**왜 있나**: 같은 run이 사람에게 내미는 검토 표면이 둘인데(정본 `deck.html` = htmlgen,
이미지 장표 `deck.images.html` = imagedeck compose) 뷰어 기능이 서로 달랐다 — deck.html에는
키보드 페이지 넘김이 있는데 deck.images.html에는 0건이었고, 후자는 `width:1920px` 고정이라
전체화면에서도 장이 화면을 넘쳐 사람이 브라우저 축소로 우회해야 정독할 수 있었다.
이미지 장표 승인 관문의 **공식 검토물**이라 이 불편이 곧 공정 마찰이다.

**계약**: 뷰어 동작은 여기 한 곳에만 둔다(이중 구현 방지). 두 표면의 화면 모델이 달라
쓰는 부품이 다를 뿐이다:
  · `deck.html` = 뷰포트 단위(100vw/100vh) 슬라이드 → 맞춤 불필요, `NAV_JS`만.
  · `deck.images.html` = 고정 px 슬라이드(PNG 계약이라 px를 줄일 수 없다) → `<deck-stage>`
    (맞춤 축소 + 화면 단위 페이징 + 두 창 동기화). 덱 실물·pptx는 건드리지 않는다.
"""
from __future__ import annotations

from pathlib import Path

# deck.html 전용(이 파일의 .navhint CSS는 htmlgen 본문 CSS에 이미 있다 — 바이트 불변 유지를 위해
# 문자열을 한 글자도 바꾸지 않는다).
NAV_JS = """
<div class="navhint">← → 이동 · 현재 슬라이드 자동 스냅</div>
<script>
  const slides = [...document.querySelectorAll('.slide')];
  let i = 0;
  function go(d){ i = Math.max(0, Math.min(slides.length-1, i+d)); slides[i].scrollIntoView({behavior:'smooth'}); }
  addEventListener('keydown', e => {
    if (['ArrowRight','ArrowDown','PageDown',' '].includes(e.key)){ e.preventDefault(); go(1); }
    if (['ArrowLeft','ArrowUp','PageUp'].includes(e.key)){ e.preventDefault(); go(-1); }
  });
</script>
"""


# ---------------------------------------------------------------------------
# 고정 px 검토·발표 표면 = <deck-stage> 웹 컴포넌트 (2026-08-02 사용자 채택)
# ---------------------------------------------------------------------------
# 종전에는 여기 `zoom` 한 줄짜리 자체 구현이 있었다(마찰35 최소 수리). 화면 맞춤은 됐지만
# **스크롤 문서**라 장 단위로 딱 넘어가지 않았다. 사용자 자산에 이미 검증된 컴포넌트가 있어
# 그대로 채택한다 — 원본은 app/render/vendor/(수정 금지, 반입 경위는 그쪽 README).
#
# 무서버 실증(2026-08-02, file://): 컴포넌트 등록 · transform:scale 화면 맞춤(레터박스) ·
# 화살표/End 키 페이징(활성 장만 visible) · **두 창 동기화**(BroadcastChannel·localStorage 양쪽
# 수신 확인). 즉 이 표면에 서버가 필요 없다 — 파일을 더블클릭해서 연다.

_VENDOR = Path(__file__).resolve().parent / "vendor" / "deck-stage.js"
_script_cache: "str | None" = None

# ⚠️ 인라인 필수 처리: 원본 주석(61행)에 닫는 script 토큰이 있다. HTML 파서는 JS 주석을 모르므로
# 그대로 넣으면 스크립트가 거기서 끊겨 **조용히** 깨진다(실제로 한 번 밟았다).
_CLOSE_TOKEN = "</" + "script"
_CLOSE_ESCAPED = "<\\/" + "script"


def deck_stage_script() -> str:
    """벤더 컴포넌트를 인라인 가능한 형태로 반환(캐시). 파일이 없으면 빈 문자열(우아 강등)."""
    global _script_cache
    if _script_cache is None:
        try:
            raw = _VENDOR.read_text(encoding="utf-8")
        except OSError:
            _script_cache = ""
        else:
            _script_cache = raw.replace(_CLOSE_TOKEN, _CLOSE_ESCAPED)
    return _script_cache


# 두 창 동기화 — 발표자 창(?present)이 보내고 전면 창(?clean)이 따라간다. 원본 호스트 앱의
# 배선을 같은 문법으로 옮기되 **채널을 이중화**했다: BroadcastChannel이 주, localStorage 이벤트가
# 폴백이다(file://에서 둘 다 전달됨을 실측 — 브라우저 편차 보험). 단, 어느 쪽이든 **같은 브라우저**
# 안에서만 오간다. 서로 다른 브라우저 둘을 잇는 것은 원리상 불가능하고 서버가 필요하다.
# 파라미터가 없으면 아무 것도 하지 않는다(기본 검토 모드는 종전과 동일).
_SYNC_JS = """
<script>
(function () {
  var P = new URLSearchParams(location.search);
  var CLEAN = P.has('clean') || P.has('front');
  var PRESENT = P.has('present') || P.has('control');
  if (!CLEAN && !PRESENT) return;
  var KEY = 'deck-sync-hun_proposal';
  var bc = null;
  try { bc = new BroadcastChannel(KEY); } catch (e) {}
  function recv(i) {
    var ds = document.querySelector('deck-stage');
    if (ds && typeof i === 'number' && ds._go) ds._go(i, 'sync');
  }
  function send(i) {
    var msg = { i: i, t: Date.now() };
    if (bc) { try { bc.postMessage(msg); } catch (e) {} }
    try { localStorage.setItem(KEY, JSON.stringify(msg)); } catch (e) {}
  }
  function start() {
    var ds = document.querySelector('deck-stage');
    if (!ds) { return setTimeout(start, 100); }
    if (CLEAN) {
      ds.setAttribute('no-rail', '');
      if (bc) bc.onmessage = function (e) { recv((e.data || {}).i); };
      addEventListener('storage', function (e) {
        if (e.key !== KEY || !e.newValue) return;
        try { recv(JSON.parse(e.newValue).i); } catch (err) {}
      });
    } else {
      ds.addEventListener('slidechange', function (e) {
        send((e.detail && typeof e.detail.index === 'number') ? e.detail.index : (ds._index || 0));
      });
      send(ds._index || 0);
    }
  }
  if (document.readyState === 'loading') addEventListener('DOMContentLoaded', start); else start();
})();
</script>
"""

# 컴포넌트가 :host{position:fixed;inset:0}로 화면을 덮고 ::slotted(*)에 position:absolute를
# !important로 강제하므로, 셸이 슬라이드에 준 width/height/margin은 자동으로 무력화된다.
# 남는 건 정의 전 깜빡임(FOUC) 차단뿐이다.
STAGE_CSS = "  deck-stage:not(:defined){visibility:hidden}"


def stage_open(width: int, height: int) -> str:
    """슬라이드를 감싸는 여는 태그."""
    return f'<deck-stage width="{int(width)}" height="{int(height)}">'


def stage_close() -> str:
    """닫는 태그 + 인라인 컴포넌트 + 동기화 배선.

    컴포넌트를 못 읽으면 태그만 남는데, 그때도 내용은 그대로 보인다(정의되지 않은 커스텀
    엘리먼트는 그냥 투명한 컨테이너다) — 우아 강등.
    """
    script = deck_stage_script()
    if not script:
        return "</deck-stage>"
    return "</deck-stage>\n<script>\n" + script + "\n</script>\n" + _SYNC_JS
