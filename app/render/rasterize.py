# -*- coding: utf-8 -*-
"""HTML→PNG 래스터라이저 (Phase 2, C 모드용) — 선택 의존성.

§8.2 결정: PPTX는 A(네이티브) 기본 + C(HTML→이미지)를 옵션/폴백으로. C 모드는
슬라이드 HTML 조각을 PNG로 구워 `pptx_primitives.add_picture`로 임베드한다.

브라우저 엔진(playwright/chromium)이 필요하므로 **선택 의존성**으로 둔다:
- 미설치 시 `available()` → False. dispatch가 native로 폴백(경고 기록, 무음 실패 금지).
- 설치 시(`pip install playwright && playwright install chromium`) 활성화.

의존성 추가는 사용자 결정 사항(네이티브 A는 의존성 0). 이 모듈은 그 결정 전까지
inert하게 존재하며, 결정되면 여기 `html_to_png`만 채우면 배선이 닫힌다.

결정 완료(2026-07-24, CONTEXT/DECK_FIRST_DESIGN.md §4-1): playwright를 정식 의존성으로 채택.
DF4(덱 프리뷰 렌더, `imagedeck.render_deck_preview`)가 `html_to_png`를 정식 가동한다.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


CHROMIUM_INSTALL_HINT = "python -m playwright install chromium"

_BROWSER_PROBE: "tuple[bool, str] | None" = None

# 별도 프로세스에서 playwright 자신에게 chromium 실행 파일 위치를 묻는다(경로 규칙을
# 우리가 다시 구현하지 않는다 = 두 번째 판정 금지). 자식 프로세스인 이유는 소음이다:
# playwright 드라이버는 종료할 때 stderr에 asyncio 잔여 로그("Task was destroyed …")를
# 결정론적으로 뱉는데, 그게 스모크 화면에 찍히면 통과인데도 실패처럼 보인다. 자식의
# stderr는 여기서 삼키고 stdout 한 글자만 받는다.
_PROBE_SNIPPET = (
    "import pathlib, sys\n"
    "from playwright.sync_api import sync_playwright\n"
    "with sync_playwright() as p:\n"
    "    exe = p.chromium.executable_path\n"
    "sys.stdout.write('1' if exe and pathlib.Path(exe).exists() else '0')\n"
)


def probe() -> "tuple[bool, str]":
    """(사용가능, 사람이 읽는 사유). 프로세스당 1회만 실측하고 캐시한다.

    W32 마찰37: `requirements.txt`가 playwright **패키지**를 설치하므로 `import playwright`
    만으로 판정하면, 브라우저 바이너리를 안 받은 사람(`playwright install chromium` 생략 —
    README가 '선택'이라 적어 둔 그대로)에게 available()=True를 돌려주고 launch에서 터진다.
    패키지가 아니라 **chromium 실행 파일 실재**를 판정 기준으로 삼는다.
    """
    global _BROWSER_PROBE
    if _BROWSER_PROBE is not None:
        return _BROWSER_PROBE
    try:
        import playwright  # noqa: F401
    except Exception:
        _BROWSER_PROBE = (False, "playwright 미설치 — pip install -r requirements.txt")
        return _BROWSER_PROBE
    try:
        done = subprocess.run(
            [sys.executable, "-c", _PROBE_SNIPPET],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=120,
        )
        ok = done.returncode == 0 and done.stdout.strip() == b"1"
        crashed = done.returncode != 0
    except Exception as exc:  # 드라이버 자체가 못 뜨는 경우도 '미설치'로 본다
        _BROWSER_PROBE = (False, f"playwright 드라이버 기동 실패 — {type(exc).__name__}")
        return _BROWSER_PROBE
    if crashed:
        _BROWSER_PROBE = (False, "playwright 드라이버 기동 실패 — 브라우저 계층 미측정")
    elif not ok:
        _BROWSER_PROBE = (
            False,
            "chromium 미설치 — playwright 패키지는 있으나 브라우저 바이너리가 없다. "
            f"설치: {CHROMIUM_INSTALL_HINT}",
        )
    else:
        _BROWSER_PROBE = (True, "playwright + chromium 사용 가능")
    return _BROWSER_PROBE


def available() -> bool:
    """HTML→PNG 래스터라이저 사용 가능 여부(playwright 설치 **+ chromium 바이너리 실재**)."""
    return probe()[0]


def unavailable_reason() -> str:
    """available()이 False인 이유를 사람 말로. 가용하면 빈 문자열."""
    ok, reason = probe()
    return "" if ok else reason


def html_to_png(html: str, out_png: str | Path, *, width_px: int = 1280,
                height_px: int = 720) -> Path:
    """HTML 문자열 → PNG 파일. playwright(chromium) 사용. 미설치 시 RuntimeError.

    C 모드가 슬라이드 조각 HTML을 렌더할 때 호출. 호출 전 `available()`로 가드할 것.
    """
    if not available():
        raise RuntimeError(
            "html_to_png requires playwright. Install: "
            "pip install playwright && playwright install chromium"
        )
    from playwright.sync_api import sync_playwright

    out = Path(out_png)
    out.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": width_px, "height": height_px})
        page.set_content(html, wait_until="networkidle")
        page.screenshot(path=str(out), clip={"x": 0, "y": 0, "width": width_px, "height": height_px})
        browser.close()
    return out


def html_to_slide_pngs(html_path: str | Path, out_dir: str | Path, *,
                        selector: str = "section.slide",
                        width_px: int = 1280, height_px: int = 720) -> list[Path]:
    """승인된 병합 HTML(`deck.html`/`manual_layer.html`) → 슬라이드 요소별 PNG.

    W4(S6-2 본체): "HTML을 진실로 삼고 PPTX는 그 사진"의 카메라. `add_specs`처럼
    deck.json에서 HTML을 다시 만들지 않는다 — 디스크의 승인된 HTML 파일을 그대로
    열어(`file://`, 상대경로 자산·override CSS 보존) 슬라이드 경계(요소 캡처)로 분할한다.
    슬라이드는 `.slide { width:100vw; height:100vh }`(vw/vh)라 뷰포트 크기가 곧 출력 해상도다.
    """
    if not available():
        raise RuntimeError(
            "html_to_slide_pngs requires playwright. Install: "
            "pip install playwright && playwright install chromium"
        )
    from playwright.sync_api import sync_playwright

    src = Path(html_path).resolve()
    if not src.exists():
        raise FileNotFoundError(str(src))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    paths: list[Path] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": width_px, "height": height_px})
        page.goto(src.as_uri())
        page.wait_for_load_state("networkidle")
        locator = page.locator(selector)
        count = locator.count()
        if count == 0:
            browser.close()
            raise RuntimeError(f"슬라이드 셀렉터({selector!r})가 {src}에서 0건 매치 — 병합 HTML이 맞는지 확인")
        for i in range(count):
            png = out / f"slide-{i + 1:02d}.png"
            locator.nth(i).screenshot(path=str(png))
            paths.append(png)
        browser.close()
    return paths
