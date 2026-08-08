# -*- coding: utf-8 -*-
"""stage9 이미지 슬롯 — 렌더(degrade) + 생성 배선(B-9).

계약(CONTEXT/DESIGN_DIRECTOR_PASS.md §7, W27 P2/D6 전환):
- 슬롯 role = mood | conceptual | evidence.
- **evidence 생성 허용 + 딱지(W27 D6, 결정 전환: 금지→허용+표시)** — 생성된 evidence 슬롯은
  slot dict에 `generated: true`가 영속되고, 렌더 시 "AI 생성 예시" 가시 딱지가 붙는다.
  딱지 제거는 사람이 `generated_resolved`(사유)를 명시했을 때만(검토요망 resolution 대칭).
- mood/conceptual/evidence 전부 생성 개방(러너: svg 마크업 반환 / 래스터는 파일 기록). tier≥2에서만 채움.
- tier 0(SOLO) 또는 러너 없음 → 전부 placeholder로 **degrade**(이미지 의존 0).
- 생성 자산은 run 디렉토리(`stage9_design/slots/`)에 커밋 → 재렌더 결정론.
- web_sample(웹 수급) 자산은 slot dict에 `source_url`을 기록한다(W27 D7) —
  `compute_image_provenance()`가 이 필드로 web_sample 카운트를 잰다.

렌더 경로(htmlgen):
- 슬롯은 append-only 장식이라 SSOT 안전(deck.json 본문 불변).
- 자산이 있으면 임베드: .svg 는 인라인, 래스터(.png/.jpg/.jpeg)는 상대경로 <img src>
  (base64 아님 — 스크린샷 갱신 시 파일만 덮어쓰도록. 발행 시 자산 폴더 동반 복사 필요).
- 슬롯 `path` 필드로 규약 경로 밖 자산(예: docs/assets/shots/…)을 직접 지정 가능.
- 자산 없으면 role별 placeholder.
- 배치(위치·크기)는 디렉터 override css(`#slide-N .dov-slot{...}`)가 결정 — 모듈은 배치 무관.
"""
from __future__ import annotations

import html as _html
import os
import re
from pathlib import Path
from typing import Any, Callable

# svg: 마크업 문자열 반환 / png: meta["target_path"]에 파일을 쓰고 경로 반환(자기보고 — 파일로 검증)
Runner = Callable[[str, dict], str]

_GENERATABLE = ("mood", "conceptual", "evidence")  # W27 D6: evidence도 생성 허용(생성물은 딱지로 표시)
_EMBEDDABLE = ("mood", "conceptual", "evidence")  # 임베드 게이트 — 실제 자산은 evidence 도 허용
_RASTER_EXTS = (".png", ".jpg", ".jpeg")
_ASSET_EXTS = (".svg",) + _RASTER_EXTS  # slot_asset_path 후보 탐색 순서
# 생성 포맷(결정 5, 2026-07-09): 내용이 정한다 — 벡터 svg / 래스터 png·jpg·jpeg.
# 엔진은 임베드(_ASSET_EXTS)를 이미 지원했으나 생성(_slot_format)은 png|svg만 알아
# jpg/jpeg를 svg로 강등시켜 "사진풍 배경 jpg 생성"이 원천 불가였다 — 그 강제를 푼다.
_VECTOR_FORMATS = ("svg",)
_RASTER_FORMATS = ("png", "jpg", "jpeg")
_GEN_FORMATS = _VECTOR_FORMATS + _RASTER_FORMATS
_ROLE_LABEL = {"mood": "MOOD", "conceptual": "CONCEPT", "evidence": "EVIDENCE"}

# 슬롯 컨테이너 스킨(1회 주입). 배치는 디렉터 css가 덮는다 — 여기선 기본 룩만.
SLOT_CSS = """
/* stage9 이미지 슬롯(장식) — 배치는 #slide-N .dov-slot 오버라이드가 덮음 */
.dov-slot{position:relative;overflow:hidden;border-radius:.8vw;display:flex;align-items:flex-end}
.dov-slot svg{width:100%;height:100%;display:block}
.dov-slot img{width:100%;height:100%;display:block;object-fit:cover}
.dov-slot--ph{padding:1.2vw;min-height:14vh}
.dov-slot--mood{background:radial-gradient(120% 90% at 75% 15%,#171717,#050505);color:#cbb8a7}
.dov-slot--conceptual{background:var(--c-white,#fff);border:1.5px solid var(--c-gray-line,#e8e8e8)}
.dov-slot--evidence{background:repeating-linear-gradient(135deg,#f4f6f9,#f4f6f9 8px,#eceff3 8px,#eceff3 16px);border:1.5px dashed var(--c-gray-line,#cfd6df)}
.dov-slot__tag{position:absolute;top:.9vw;left:1vw;font-size:var(--type-caption,10px);letter-spacing:.16em;font-weight:800}
.dov-slot--mood .dov-slot__tag{color:var(--c-orange,#F37321)}
.dov-slot--conceptual .dov-slot__tag{color:var(--c-navy,#1E4A8C)}
.dov-slot--evidence .dov-slot__tag{color:#6b7684}
/* W27 D6: 생성된 evidence 위 가시 딱지("AI 생성 예시") — 기존 tag 문법 재사용, 우상단으로 구분. */
.dov-slot__tag--gen{left:auto;right:1vw;background:rgba(180,40,30,.92);color:#fff;
  padding:.15em .5em;border-radius:.3em;letter-spacing:.08em}
.dov-slot__cap{position:relative;font-size:var(--type-caption,10px);line-height:1.4;opacity:.9}
.dov-slot--conceptual .dov-slot__cap{color:var(--c-gray-text,#555)}
.dov-slot--evidence .dov-slot__cap{color:#6b7684}
/* 결정 6: 배경 레이어 — 풀블리드 기본 배치(디렉터 css가 덮음) + 가독성 스크림(treatment 실체) */
.dov-slot--bg{position:absolute;inset:0;z-index:0;border-radius:0}
/* W12(D2): 상단(메타·eyebrow 정보영역)과 하단(제목·메시지) 양끝을 보호하고 중앙은 이미지가
   읽히게 비운다 — 종전 하단 편중(0.15→0.55)이 상단 텍스트를 약하게 덮던 문제 보강. */
.dov-slot__scrim{position:absolute;inset:0;z-index:1;pointer-events:none;
  background:linear-gradient(180deg,rgba(5,5,5,.5) 0%,rgba(5,5,5,.22) 24%,rgba(5,5,5,.28) 60%,rgba(5,5,5,.62) 100%)}
/* 결정 6(가독성 계약): 배경 슬롯이 있으면 슬라이드 전경 콘텐츠(제목·본문·배지)를
   배경+스크림(z0/z1) 위로 올린다. 안 그러면 배경 이미지가 텍스트를 덮어 hero 제목이 사라진다. */
.slide:has(.dov-slot--bg) > *:not(.dov-slot--bg){position:relative;z-index:2}
.slide:has(.dov-slot--bg) .slide__title,
.slide:has(.dov-slot--bg) .slide__msg,
.slide:has(.dov-slot--bg) .slide__eyebrow,
.slide:has(.dov-slot--bg) .slide__meta{color:#fff;text-shadow:0 2px 14px rgba(0,0,0,.62)}
""".strip()


def slot_asset_path(run_dir: "str | Path", slide_key: "str | int", slot_id: str,
                    fmt: str = "svg") -> Path:
    """자산 규약 경로: <run>/stage9_design/slots/slide<key>_<slot_id>.<ext>.

    확장자 후보(_ASSET_EXTS: .svg→.png→.jpg→.jpeg) 중 **첫 존재 파일**을 반환.
    아무것도 없으면 fmt 확장자의 (미존재) 경로를 반환 — 생성 목적지로 쓰인다.
    """
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(slot_id))
    base = Path(run_dir) / "stage9_design" / "slots" / f"slide{slide_key}_{safe}"
    for ext in _ASSET_EXTS:
        p = base.with_name(base.name + ext)
        if p.exists():
            return p
    return base.with_name(base.name + "." + str(fmt).lstrip("."))


def extract_svg(text: str) -> "str | None":
    """러너 출력에서 <svg>…</svg> 1개를 추출(코드펜스·배너 무시). 없으면 None."""
    if not text:
        return None
    m = re.search(r"<svg\b[^>]*>.*?</svg>", text, flags=re.S | re.I)
    return m.group(0) if m else None


def _slot_layer(slot: "dict | None") -> str:
    """슬롯 레이어(결정 6): "background" 선언만 배경으로, 그 외 전부 foreground(기본)."""
    return "background" if str((slot or {}).get("layer", "")).lower() == "background" else "foreground"


def _slot_open(slot: "dict | None", role: str, *, placeholder: bool = False) -> str:
    """슬롯 div 여는 태그 — role/layer 클래스 + data 속성(probe가 읽는 계약 표면).

    결정 6: layer="background" 선언 시 `dov-slot--bg` 클래스 + `data-layer="background"`를
    실어 layout_probe가 (a) slot_overlaps_content에서 제외하고 (b) 가독성(treatment 오버레이
    실존)을 대신 실측하게 한다. `data-treatment`는 선언 텍스트(자기보고) — probe는 이를
    믿지 않고 실제 오버레이 DOM을 잰다.
    """
    layer = _slot_layer(slot)
    classes = ["dov-slot"]
    if placeholder:
        classes.append("dov-slot--ph")
    classes.append(f"dov-slot--{role}")
    if layer == "background":
        classes.append("dov-slot--bg")
    attrs = [f'class="{" ".join(classes)}"', f'data-role="{role}"']
    if layer == "background":
        attrs.append('data-layer="background"')
        tr = str((slot or {}).get("treatment", "")).strip()
        if tr:
            attrs.append(f'data-treatment="{_html.escape(tr, quote=True)}"')
    return f'<div {" ".join(attrs)}>'


def _scrim_html(slot: "dict | None") -> str:
    """배경 슬롯의 가독성 처리(treatment)를 **실제 DOM 오버레이**로 렌더한다(결정 6).

    선언만으로 pass 시키지 않기 위해, 배경 슬롯은 자산 위에 스크림(그라디언트 오버레이)을
    실제로 깐다 — probe가 이 오버레이가 텍스트 영역을 덮는지 잰다. 디렉터 css가 이 스크림을
    덮어써(더 강하게/약하게) 조정할 수 있고, 투명하게 죽이면 probe가 background_no_treatment로
    잡는다(자기보고 불신 유지).
    """
    if _slot_layer(slot) != "background":
        return ""
    return '<div class="dov-slot__scrim" aria-hidden="true"></div>'


def _placeholder_html(slot_or_role: "dict | str") -> str:
    slot = slot_or_role if isinstance(slot_or_role, dict) else {"role": slot_or_role}
    role = slot.get("role", "conceptual")
    r = role if role in _ROLE_LABEL else "conceptual"
    tag = _ROLE_LABEL[r]
    if r == "evidence":
        cap = "근거 자산 필요 · 자동생성 금지"
    elif r == "mood":
        cap = "무드 비주얼 슬롯"
    else:
        cap = "개념 비주얼 슬롯"
    return (f'{_slot_open(slot, r, placeholder=True)}{_scrim_html(slot)}'
            f'<span class="dov-slot__tag">{tag}</span>'
            f'<span class="dov-slot__cap">{cap}</span></div>')


def _generated_badge_html(slot: "dict | None") -> str:
    """W27 D6: 생성된 evidence 슬롯 위 가시 딱지("AI 생성 예시").

    mood/conceptual 생성물은 딱지 없음(장식이라 기만 소지 없음) — evidence만 대상.
    제거는 사람이 명시 `generated_resolved`(사유)를 적었을 때만(코드는 임의로 안 지운다,
    검토요망 resolution 문법 대칭).
    """
    s = slot or {}
    if s.get("role") != "evidence" or not s.get("generated"):
        return ""
    if s.get("generated_resolved"):
        return ""
    return '<span class="dov-slot__tag dov-slot__tag--gen">AI 생성 예시</span>'


def render_slot_html(slot: dict, asset_svg: "str | None" = None,
                     asset_src: "str | None" = None) -> str:
    """단일 슬롯 → HTML(결정론·순수). 자산 있으면 임베드, 없으면 role placeholder.

    임베드 게이트는 _EMBEDDABLE(evidence 포함) — 생성 게이트(_GENERATABLE)와 별개.
    evidence 생성은 W27 D6로 허용됐다 — 생성물은 `slot["generated"]=true`를 달고 오며,
    이 함수는 그 표시를 가시 딱지로 렌더한다(_generated_badge_html).
    asset_svg = svg 마크업(인라인) / asset_src = 래스터 상대경로(<img src>, base64 아님).
    """
    role = (slot or {}).get("role", "conceptual")
    # 배경 레이어(풀블리드 사진)는 역할 라벨(MOOD/CONCEPT)을 노출하지 않는다 —
    # 그 라벨은 placeholder/foreground 슬롯의 주석이지 최종 배경 이미지의 워터마크가 아니다.
    tag = "" if _slot_layer(slot) == "background" else f'<span class="dov-slot__tag">{_ROLE_LABEL[role]}</span>'
    gen_badge = _generated_badge_html(slot)
    if role in _EMBEDDABLE:
        if asset_svg:
            svg = extract_svg(asset_svg) or ""
            if svg:
                return (f'{_slot_open(slot, role)}'
                        f'{tag}{gen_badge}{svg}'
                        f'{_scrim_html(slot)}</div>')
        if asset_src:
            src = _html.escape(str(asset_src).replace("\\", "/"), quote=True)
            alt = _html.escape(str(slot.get("prompt") or slot.get("id") or role))
            return (f'{_slot_open(slot, role)}'
                    f'{tag}{gen_badge}'
                    f'<img src="{src}" alt="{alt}"/>{_scrim_html(slot)}</div>')
    return _placeholder_html(slot if isinstance(slot, dict) else role)


def _find_slot_asset(slot: dict, slide_key: "str | int",
                     run_dir: "str | Path | None") -> "tuple[Path | None, str | None]":
    """슬롯 자산 탐색 → (파일 Path, html src 문자열). 없으면 (None, None).

    ① slot["path"] 명시 시(규약 밖 자산 — 예: docs/assets/shots/…): 절대경로 그대로,
       상대경로는 run_dir 기준 → cwd 기준 순으로 존재 확인. src 는 준 문자열 그대로
       (발행 시 자산을 html 옆으로 복사하는 건 발행 단계의 책임).
    ② 없으면 규약 경로(slot_asset_path 확장자 후보 탐색). src 는 run_dir 상대.
    """
    explicit = str((slot or {}).get("path") or "").strip()
    if explicit:
        cand = Path(explicit)
        tries = [cand] if cand.is_absolute() else (
            ([Path(run_dir) / cand] if run_dir is not None else []) + [cand])
        for t in tries:
            if t.exists():
                if cand.is_absolute() and run_dir is not None:
                    try:
                        src = os.path.relpath(t, run_dir).replace("\\", "/")
                    except ValueError:  # Windows 드라이브 상이
                        src = t.as_uri()
                    return t, src
                return t, explicit.replace("\\", "/")
        return None, None
    if run_dir is None:
        return None, None
    p = slot_asset_path(run_dir, slide_key, slot.get("id", "slot"))
    if p.exists():
        return p, f"stage9_design/slots/{p.name}"
    return None, None


def resolve_slots_html(image_slots: "list | None", slide_key: "str | int",
                       run_dir: "str | Path | None") -> str:
    """슬라이드의 image_slots → append용 HTML(결정론). 자산 존재 시 임베드, 아니면 placeholder.

    임베드 게이트 = _EMBEDDABLE(evidence 포함). .svg → 인라인 / 래스터 → <img src>.
    """
    if not image_slots:
        return ""
    parts: list[str] = []
    for slot in image_slots:
        if not isinstance(slot, dict):
            continue
        asset_svg = None
        asset_src = None
        role = slot.get("role", "conceptual")
        if role in _EMBEDDABLE:
            p, src = _find_slot_asset(slot, slide_key, run_dir)
            if p is not None:
                if p.suffix.lower() == ".svg":
                    try:
                        asset_svg = p.read_text(encoding="utf-8")
                    except OSError:
                        asset_svg = None
                else:
                    asset_src = src
        parts.append(render_slot_html(slot, asset_svg, asset_src))
    return "".join(parts)


def has_any_slots(overrides: "dict | None") -> bool:
    for ov in ((overrides or {}).get("slides") or {}).values():
        if isinstance(ov, dict) and ov.get("image_slots"):
            return True
    return False


# ── 생성 배선(fill) — tier≥2, mood/conceptual만. evidence 는 포맷 무관 생성 금지 ──
# 기본 팔레트(스킨 토큰 미전달 시 폴백). 결정 5: 스킨 토큰(팔레트)을 전달해 테마와 정합.
_DEFAULT_PALETTE = "네이비 #1E4A8C · 틸 #156082 · 오렌지 #F37321(강조 10% 이내) · 그레이 #E8E8E8 · 블랙 #050505"
# 결정 5: 아이콘은 **이모지 금지** — 생성 벡터/래스터 도형으로 테마(스킨 토큰)와 어울리게.
_NO_EMOJI = "이모지(emoji)·유니코드 픽토그램·폰트 아이콘 금지 — 순수 도형/이미지로만 그린다."

_FILL_INSTRUCTION_SVG = (
    "너는 제안서 슬라이드의 **장식용 비주얼**을 SVG로 그리는 아트 디렉터다.\n"
    "규칙(엄수):\n"
    "1) 출력은 **오직 하나의 <svg>…</svg>** 마크업. 설명·코드펜스·다른 텍스트 금지.\n"
    "2) viewBox=\"0 0 800 600\", 반응형(width/height 미지정 또는 100%).\n"
    "3) **문자(text) 요소 금지** — 순수 도형·그라데이션·라인만(슬라이드 본문 텍스트를 재생하지 말 것, SSOT).\n"
    "   " + _NO_EMOJI + "\n"
    "4) 팔레트(스킨 토큰): {palette}.\n"
    "5) 연출(treatment)을 반영: 무드=어둡게·흐릿·저대비 / 개념=밝고 선명한 다이어그램형.\n"
)

_FILL_INSTRUCTION_RASTER = (
    "너는 제안서 슬라이드의 **장식용 비주얼**을 {fmt_up} 이미지로 만드는 아트 디렉터다.\n"
    "규칙(엄수):\n"
    "1) **내장 image generation 도구를 사용하라. 스크립트 드로잉(System.Drawing, PIL, matplotlib 등) 금지.**\n"
    "2) 결과 이미지를 **{fmt_up}** 포맷으로 [저장 경로]에 파일로 저장하라. 다른 출력은 저장한 경로 한 줄만.\n"
    "   (사진풍·풀블리드 배경은 jpg 가 용량상 유리하다 — 지정된 포맷을 그대로 지켜라.)\n"
    "3) **이미지 안에 문자(텍스트) 금지** — 슬라이드 본문을 재생하지 말 것(SSOT). " + _NO_EMOJI + "\n"
    "4) 팔레트 기조(스킨 토큰): {palette}.\n"
    "5) 연출(treatment)을 반영: 무드=어둡게·흐릿·저대비 / 개념=밝고 선명한 다이어그램형.\n"
)


def _palette_text(palette: "dict | str | None") -> str:
    """스킨 토큰 → 프롬프트용 팔레트 문자열. dict면 name #hex 나열, str면 그대로, 없으면 기본값."""
    if isinstance(palette, str) and palette.strip():
        return palette.strip()
    if isinstance(palette, dict) and palette:
        parts = [f"{k} {v}" for k, v in palette.items() if v]
        if parts:
            return " · ".join(parts)
    return _DEFAULT_PALETTE


def _slot_format(slot: dict) -> str:
    """생성 포맷: slot["format"] 명시값(svg|png|jpg|jpeg)만 신뢰. 미지정/그 외 → "svg".

    러너 반환값 스니핑(<svg 로 시작하나?) 금지 — 포맷은 입력이 결정한다(자기보고 불신).
    결정 5: jpg/jpeg를 1급으로 인정(사진풍·풀블리드 배경 = jpg 우선, 용량). 예전엔 png|svg만
    알아 jpg가 조용히 svg로 강등됐다(사진 배경 생성 불가) — 그 강제를 제거.
    """
    fmt = str((slot or {}).get("format", "")).lower().lstrip(".")
    return fmt if fmt in _GEN_FORMATS else "svg"


def _is_raster(fmt: str) -> bool:
    return fmt in _RASTER_FORMATS


def build_fill_prompt(slot: dict, target_path: "str | Path | None" = None,
                      palette: "dict | str | None" = None) -> str:
    role = slot.get("role", "conceptual")
    fmt = _slot_format(slot)
    raster = _is_raster(fmt)
    subject = str(slot.get("prompt", "")).strip() or "추상 개념 비주얼"
    treatment = str(slot.get("treatment", "")).strip()
    is_bg = str((slot or {}).get("layer", "")).lower() == "background"
    pal = _palette_text(palette)
    if is_bg:
        mode = ("배경(background): 텍스트가 위에 올라갈 풀블리드 배경 — 중앙·하단(제목/메시지)은 "
                "저대비·여백감 있게, **상단(메타·eyebrow 정보영역)도 저대비로 비워 둔다**(가독성 확보)")
    elif role == "mood":
        mode = "무드(mood): 어두운 배경, 흐릿·저대비, 분위기"
    else:
        mode = "개념(conceptual): 밝은 배경, 선명한 개념 다이어그램/도형"
    base = (_FILL_INSTRUCTION_RASTER.format(fmt_up=fmt.upper(), palette=pal) if raster
            else _FILL_INSTRUCTION_SVG.format(palette=pal))
    lines = [base, f"\n[역할] {mode}", f"[주제] {subject}"]
    if treatment:
        lines.append(f"[연출] {treatment}")
    if raster:
        if target_path is not None:
            lines.append(f"[저장 경로] {target_path}")
        lines.append(f"\n이제 {fmt.upper()} 파일을 [저장 경로]에 저장하고 경로만 출력하라.")
    else:
        lines.append("\n이제 <svg>만 출력하라.")
    return "\n".join(lines)


def fill_images(overrides: dict, run_dir: "str | Path", *, tier: int,
                runner: "Runner | None" = None,
                allow_generate: "bool | None" = None,
                palette: "dict | str | None" = None) -> dict:
    """override의 image_slots를 채운다(생성 자산을 run에 커밋).

    - W27 D6(결정 전환: 금지→허용+표시): evidence도 mood/conceptual과 동일하게 생성 개방.
      생성된 evidence 슬롯은 `slot["generated"]=True`가 override dict에 영속된다(재렌더
      결정론 + render_slot_html이 "AI 생성 예시" 딱지를 붙이는 근거). `skipped_evidence`는
      하위호환을 위해 report 키로 남지만 이제 채워지지 않는다(항상 빈 리스트).
    - 생성 허용 = `allow_generate`(명시 시) else `tier>=2`. W3b/N3-4: 사용자가 `--fill-images`를
      직접 친 것은 **단발 위임**이라 협업 tier 다이얼과 무관하다("Codex 이미지 생성은 tier 다이얼과
      무관하게 가능" — NORTHSTAR §N3-4). 기본값 None 은 기존 tier 게이트 그대로.
    - 생성 불허 또는 runner 없음 → 전부 degrade(placeholder, 생성 안 함).
    - **빈 프롬프트(주제 없음) → skip + 경고**(skipped_no_prompt, 결정 2026-07-15): 프롬프트가
      비면 제네릭 이미지(다크 플렉서스 등)가 나온다. 계약(§7)상 프롬프트는 사람/디렉터가 채운다 —
      비어 있으면 "미준비"로 보고 생성하지 않고 placeholder로 degrade한다(조용한 제네릭 방지).
    - 이미 자산 있으면 skip(cached, 재렌더 결정론).
    - slot["format"]=="svg"(기본): runner(prompt)→<svg> 추출 성공 시 자산 저장, 실패 시 degrade.
    - slot["format"] in (png|jpg|jpeg): 래스터 계약 — runner 가 meta["target_path"]에 파일을 쓴다.
      반환값(자기보고)은 믿지 않고 목적지 파일 존재+크기>0 으로 검증, 실패 시 degrade.
      (결정 5: 포맷은 내용이 정한다 — 사진풍·풀블리드 배경은 jpg 우선. png/jpg/jpeg 모두 이 경로.)
    - palette: 스킨 토큰(팔레트) — 생성 프롬프트에 실어 테마와 정합(이모지 금지·색 정합).
    반환: {generated, cached, skipped_evidence, skipped_no_prompt, degraded} 각 슬롯 식별자 리스트.
    """
    report = {"generated": [], "cached": [], "skipped_evidence": [],
              "skipped_no_prompt": [], "degraded": []}
    can_generate = (tier >= 2) if allow_generate is None else bool(allow_generate)
    slides = (overrides or {}).get("slides") or {}
    for key, ov in slides.items():
        if not isinstance(ov, dict):
            continue
        for slot in ov.get("image_slots") or []:
            if not isinstance(slot, dict):
                continue
            sid = f"slide{key}:{slot.get('id', 'slot')}"
            role = slot.get("role", "conceptual")
            if role not in _GENERATABLE:
                report["degraded"].append(sid)
                continue
            fmt = _slot_format(slot)
            path = slot_asset_path(run_dir, key, slot.get("id", "slot"), fmt=fmt)
            if path.exists():
                report["cached"].append(sid)
                continue
            # 빈 프롬프트(주제 없음) → 생성 금지(결정 2026-07-15). 제네릭 이미지 방지 —
            # 캐시된 자산이 없고 프롬프트도 비면 "미준비"로 보고 placeholder로 degrade + 경고.
            if not str(slot.get("prompt", "")).strip():
                report["skipped_no_prompt"].append(sid)
                continue
            if not can_generate or runner is None:
                report["degraded"].append(sid)
                continue
            meta = {"slot": sid, "role": role, "format": fmt, "target_path": str(path)}
            if _is_raster(fmt):
                path.parent.mkdir(parents=True, exist_ok=True)
                runner(build_fill_prompt(slot, target_path=path, palette=palette), meta)
                # 래스터 계약(png/jpg/jpeg): 러너가 target_path 에 파일을 쓴다. 반환값은 검증에 쓰지 않는다.
                if path.exists() and path.stat().st_size > 0:
                    report["generated"].append(sid)
                    slot["generated"] = True  # W27 D6: 재렌더 결정론 + 딱지 렌더 근거(override에 영속)
                else:
                    report["degraded"].append(sid)
                continue
            out = runner(build_fill_prompt(slot, palette=palette), meta)
            svg = extract_svg(out or "")
            if not svg:
                report["degraded"].append(sid)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(svg, encoding="utf-8")
            report["generated"].append(sid)
            slot["generated"] = True  # W27 D6: 재렌더 결정론 + 딱지 렌더 근거(override에 영속)
    return report


# --- 이미지 수급 표면화(W27 D6·D7) — gating_report.image_provenance -----------

def compute_image_provenance(overrides: dict, run_dir: "str | Path | None" = None) -> dict:
    """전 슬롯 전수 카운트 → gating_report.image_provenance 블록.

    - generated / generated_evidence / generated_evidence_unresolved: `fill_images()`가
      영속한 `slot["generated"]`(+evidence 미해소 `generated_resolved` 부재) 기준.
    - web_sample / web_sample_sourced: `slot["source_route"]=="web_sample"`(명시) 또는
      route 미지정인데 `source_url`만 있는 경우(암묵 web_sample)를 N으로, 그중 실제
      `source_url`이 기록된 것을 M(web_sample_sourced)으로 잰다(D7: 출처 기록 여부 분리).
    - real_asset / placeholder: run_dir이 있으면 실제 자산 파일 존재를 실측(자기보고 불신).
      run_dir이 없으면 명시 `slot["path"]` 유무로만 보수적으로 판정(placeholder 과다청구 방지
      — 판정 불가 슬롯은 어느 쪽에도 넣지 않는다).
    """
    counts = {
        "total": 0, "generated": 0, "generated_evidence": 0,
        "generated_evidence_unresolved": 0, "web_sample": 0, "web_sample_sourced": 0,
        "real_asset": 0, "placeholder": 0,
    }
    slides = (overrides or {}).get("slides") or {}
    for key, ov in slides.items():
        if not isinstance(ov, dict):
            continue
        for slot in ov.get("image_slots") or []:
            if not isinstance(slot, dict):
                continue
            counts["total"] += 1
            role = slot.get("role", "conceptual")
            generated = bool(slot.get("generated"))
            if generated:
                counts["generated"] += 1
                if role == "evidence":
                    counts["generated_evidence"] += 1
                    if not slot.get("generated_resolved"):
                        counts["generated_evidence_unresolved"] += 1

            route = str(slot.get("source_route") or "").strip()
            has_url = bool(str(slot.get("source_url") or "").strip())
            if route == "web_sample" or (not route and has_url):
                counts["web_sample"] += 1
                if has_url:
                    counts["web_sample_sourced"] += 1

            if generated:
                continue  # 생성물은 real_asset/placeholder 집계 대상이 아니다(별도 카운트).
            has_asset = False
            if run_dir is not None:
                p, _src = _find_slot_asset(slot, key, run_dir)
                has_asset = p is not None
            elif str(slot.get("path") or "").strip():
                has_asset = True
            if has_asset:
                counts["real_asset"] += 1
            elif run_dir is not None:
                counts["placeholder"] += 1
    return counts
