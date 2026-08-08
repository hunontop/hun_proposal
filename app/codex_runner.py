"""공용 Codex CLI subprocess 러너 (엔진-무관, 발산과 무관).

`make_codex_runner()`는 codex CLI(exec)를 subprocess로 호출하는 러너 팩토리다.
원래 `app/divergence_run.py`에 있었으나, 발산(Assisted 브레인스토밍)과 무관하게
존치 기능 두 곳이 공용으로 재사용하고 있어(W31 E2b) 이 중립 모듈로 추출했다:

  · `proposal_system/scripts/proposal_pipeline.py::fill_images_stage9`
    (stage9 `--fill-images` 경로)
  · `proposal_system/scripts/proposal_pipeline.py::imagedeck_cmd`의 `--produce` 분기

`divergence_run.py`·`app/brainstorm.py`는 W31 E2b에서 `<개발 원본 전용 경로>
divergence\\`로 격리됐다(경위는 그쪽 README.md 참고). 이 모듈은 그 이동의 유일한
예외 — 러너 로직 자체는 발산과 무관하므로 리포에 존치한다.

이동 시 동작은 한 글자도 바꾸지 않았다(Windows 처리 포함, 아래 docstring 참고).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parents[1]

# runner(prompt, meta) -> 에이전트 원문 텍스트(fenced json 계약을 담은).
Runner = Callable[[str, dict], str]


# ── codex-deep 러너(테스트 경로, 실 subprocess) ──────────────────────────────
def make_codex_runner(
    *,
    model: str = "gpt-5.5",
    effort: str = "high",
    cwd: str | Path | None = None,
    timeout: int = 600,
    codex_exe: str = "codex",
) -> Runner:
    """codex CLI(exec)를 subprocess로 호출하는 러너. CONTROL.md 실호출 규약 준수.

    `--ignore-user-config`(service_tier 거부 우회) + ephemeral + full-access.
    실패(비정상 종료/타임아웃)면 빈 문자열 반환 → parse_candidates가 안전 스킵.

    ⚠️ Windows: npm 전역 codex는 `codex.CMD`라 subprocess(CreateProcess)가 PATHEXT를
    적용 못 해 이름만으론 못 찾는다 → shutil.which로 실행가능 경로를 해석한다.
    ⚠️ 프롬프트는 **stdin으로 전달**한다(`exec -` = stdin에서 읽기). npm codex.CMD는
    cmd.exe 셔임이라 argv로 넘기면 명령줄 8191자 한계에 걸린다(judge 프롬프트처럼 후보를
    주입하면 쉽게 초과). stdin 경로는 이 한계를 전면 우회한다.
    최종 에이전트 메시지(fenced json 포함)는 stdout, 배너·전사는 stderr로 나온다.
    ⚠️ codex stderr(배너)는 Windows ANSI(cp949)로 나올 수 있어 엄격 utf-8 디코딩이
    리더 스레드에서 크래시한다 → errors="replace"로 무해화(stdout JSON은 전체읽기
    후 1회 디코딩이라 멀티바이트 안전).
    """
    root = str(cwd or REPO_ROOT)
    exe = shutil.which(codex_exe) or codex_exe

    def _run(prompt: str, meta: dict) -> str:
        cmd = [
            exe, "exec", "--ignore-user-config",
            "-c", f'model="{model}"', "-c", f'model_reasoning_effort="{effort}"',
            "--skip-git-repo-check", "--ephemeral",
            "--sandbox", "danger-full-access", "--cd", root, "-",
        ]
        try:
            proc = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=timeout,
            )
        except (subprocess.TimeoutExpired, OSError):
            return ""
        if proc.returncode != 0:
            return ""
        return proc.stdout or ""

    return _run
