# -*- coding: utf-8 -*-
"""
M4 make_pptx — 스토리라인(JSON) → 제안서 PPTX 초안 생성 (inkline 룩, W30)

설계:
  - 디자인 풀재현(X). 슬라이드 구조 초안(O): 제목·핵심메시지·본문 불릿.
  - W30(2026-07-20): 초안도 정본 디자인 규칙(inkline 하이브리드 크롬)을 입는다 —
    표지(라벨·제목·accent 선)·목차(넘버 배지 그리드)·본문(배지·제목·부제 헤더 +
    푸터 프로젝트명·페이지). 최종 덱(imagedeck compose_pptx)과 같은 토큰이라
    초안→최종의 시각 연속성이 생긴다. **자체 완결**(외부 모듈 임포트 금지 - 배포판 독립).
  - 발표노트에 [근거 출처]·[시각화 지시]·[검토요망] 을 넣어 사람 검토를 돕는다.
  - 모든 본문 텍스트는 storyline(=분석카드=RFP 원문 근거)에서만 옴 → 환각 차단.

사용:
  python make_pptx.py draft/<공고번호>_storyline.json
"""
import os
import sys
import json

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

# inkline 토큰 (skins/inkline.json과 정합 - 자체 완결을 위해 상수 복제)
INK = "16324C"
INK_DEEP = "0F2438"
ACCENT = "E8590C"
BG = "F8F7F4"
PAPER = "FFFFFF"
GRAY = "5C6470"
LINE_STRONG = "C9D1DA"
LINE = "DDE1E6"
FLAG_BG, FLAG_TX = "FFF1E6", "C4441C"
FAMILY = "Pretendard"

EMU_W = Inches(13.333)   # 16:9
EMU_H = Inches(7.5)


def _rgb(hexstr):
    return RGBColor.from_string(hexstr)


def _rect(slide, x, y, w, h, fill=None, shape=MSO_SHAPE.RECTANGLE):
    s = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    if fill is None:
        s.fill.background()
    else:
        s.fill.solid(); s.fill.fore_color.rgb = _rgb(fill)
    s.line.fill.background()
    try:
        s.shadow.inherit = False
    except Exception:
        pass
    return s


def _line(slide, x, y, w, color=LINE_STRONG, pt=1.5):
    ln = slide.shapes.add_connector(1, Inches(x), Inches(y), Inches(x + w), Inches(y))
    ln.line.color.rgb = _rgb(color); ln.line.width = Pt(pt)
    return ln


def _text(slide, x, y, w, h, text, size, color, bold=False, italic=False,
          align="left", anchor="top"):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame; tf.word_wrap = True
    tf.margin_left = 0; tf.margin_right = 0; tf.margin_top = 0; tf.margin_bottom = 0
    tf.vertical_anchor = {"top": MSO_ANCHOR.TOP, "middle": MSO_ANCHOR.MIDDLE,
                          "bottom": MSO_ANCHOR.BOTTOM}[anchor]
    p = tf.paragraphs[0]
    p.alignment = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER,
                   "right": PP_ALIGN.RIGHT}[align]
    p.text = text or ""
    f = p.runs[0].font if p.runs else p.font
    f.size = Pt(size); f.bold = bold; f.italic = italic
    f.name = FAMILY; f.color.rgb = _rgb(color)
    return tb


def _badge(slide, x, y, label, fill=INK):
    w = max(0.82, 0.36 + len(str(label)) * 0.155)
    _rect(slide, x, y, w, 0.31, fill=fill, shape=MSO_SHAPE.ROUNDED_RECTANGLE)
    _text(slide, x, y, w, 0.31, str(label), 12, PAPER, bold=True,
          align="center", anchor="middle")
    return w


def _flag_pill(slide, label):
    w = max(1.0, 0.3 + len(str(label)) * 0.12)
    x = 13.333 - 0.44 - w
    _rect(slide, x, 0.67, w, 0.22, fill=FLAG_BG, shape=MSO_SHAPE.ROUNDED_RECTANGLE)
    _text(slide, x, 0.67, w, 0.22, str(label), 9, FLAG_TX, bold=True,
          align="center", anchor="middle")


def _chrome_footer(slide, project, page):
    _line(slide, 0, 7.06, 13.333)
    _text(slide, 0.44, 7.06, 9.5, 0.44, project, 12, INK, bold=True, anchor="middle")
    _text(slide, 11.3, 7.06, 1.6, 0.44, page, 12, INK, bold=True,
          align="right", anchor="middle")


def add_title_slide(prs, slide_data, meta):
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
    _rect(slide, 0, 0, 13.333, 7.5, fill=INK_DEEP)
    bid_no = meta.get("bid_no") or ""
    label = "PROPOSAL" + (f" · {bid_no}" if bid_no else "")
    _text(slide, 0.76, 4.62, 11.8, 0.3, label, 16, ACCENT, bold=True)
    _text(slide, 0.76, 5.05, 11.8, 1.2, slide_data["title"], 40, PAPER, bold=True)
    _rect(slide, 0.76, 6.35, 0.83, 0.03, fill=ACCENT)
    meta_line = " · ".join(x for x in (meta.get("client"), meta.get("concept")) if x)
    if meta_line:
        _text(slide, 0.76, 6.62, 11.8, 0.3, meta_line, 15, "E7EBF0")
    _set_notes(slide, slide_data)
    return slide


def add_toc_slide(prs, slide_data, project, page):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _rect(slide, 0, 0, 13.333, 7.5, fill=BG)
    _badge(slide, 0.44, 0.18, slide_data["section"])
    _text(slide, 0.44, 0.56, 10.0, 0.55, slide_data["title"], 26, INK_DEEP, bold=True)
    _line(slide, 0, 1.28, 13.333)
    items = slide_data.get("bullets", [])
    col_w, x0, gap = 5.6, 0.76, 0.6
    y0, row_h = 1.9, 0.86
    for i, it in enumerate(items):
        cx = x0 + (i % 2) * (col_w + gap)
        cy = y0 + (i // 2) * row_h
        _rect(slide, cx, cy, 0.39, 0.39, fill=INK, shape=MSO_SHAPE.ROUNDED_RECTANGLE)
        _text(slide, cx, cy, 0.39, 0.39, f"{i + 1:02d}", 13, PAPER, bold=True,
              align="center", anchor="middle")
        _text(slide, cx + 0.56, cy + 0.02, col_w - 0.56, 0.4, str(it), 15,
              INK_DEEP, bold=True)
        _line(slide, cx, cy + row_h - 0.18, col_w, color=LINE, pt=0.75)
    _chrome_footer(slide, project, page)
    _set_notes(slide, slide_data)
    return slide


def add_content_slide(prs, slide_data, project, page):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _rect(slide, 0, 0, 13.333, 7.5, fill=BG)

    # 크롬 헤더: 섹션 배지(고민=accent 강조) - 제목 - 부제(핵심 메시지)
    section = slide_data["section"]
    _badge(slide, 0.44, 0.18, section, fill=(ACCENT if section == "고민" else INK))
    title = slide_data["title"]
    tsize = 26 if len(title) <= 42 else 20
    _text(slide, 0.44, 0.54, 11.0, 0.46, title, tsize, INK_DEEP, bold=True)
    msg = slide_data.get("message", "")
    if msg:
        _text(slide, 0.44, 1.0, 12.0, 0.26, msg, 13, GRAY)
    if slide_data.get("flag"):
        _flag_pill(slide, slide_data["flag"])
    _line(slide, 0, 1.28, 13.333)

    # 본문 불릿 (초안 본체 - 최종 덱에서는 이 자리가 생성 이미지)
    bullets = slide_data.get("bullets", [])
    if bullets:
        tb = slide.shapes.add_textbox(Inches(0.7), Inches(1.62), Inches(11.9), Inches(4.7))
        tf = tb.text_frame; tf.word_wrap = True
        for i, b in enumerate(bullets):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.text = "•  " + str(b)
            f = p.runs[0].font if p.runs else p.font
            f.size = Pt(15); f.name = FAMILY; f.color.rgb = _rgb("2A3542")
            p.space_after = Pt(9)

    # 시각화 지시 (제작자 참고용 - 최종 덱의 이미지 프롬프트 씨앗)
    visual = slide_data.get("visual", "")
    if visual:
        _text(slide, 0.7, 6.55, 12.0, 0.35, "시각화: " + visual, 10, "8B95A1", italic=True)

    _chrome_footer(slide, project, page)
    _set_notes(slide, slide_data)
    return slide


def _set_notes(slide, slide_data):
    notes = slide.notes_slide.notes_text_frame
    lines = [
        f"[근거] {slide_data.get('evidence', '-')}",
        f"[시각화] {slide_data.get('visual', '-')}",
    ]
    if slide_data.get("flag"):
        lines.append(f"[🔴 검토요망] {slide_data['flag']}")
    notes.text = "\n".join(lines)


def build(storyline_path):
    with open(storyline_path, encoding="utf-8") as f:
        data = json.load(f)
    meta = data["meta"]
    slides = data["slides"]
    project = meta.get("project") or meta.get("bid_no") or ""

    prs = Presentation()
    prs.slide_width = EMU_W
    prs.slide_height = EMU_H

    total = len(slides)
    for idx, sd in enumerate(slides, start=1):
        page = f"{idx:02d} / {total:02d}"
        if sd["section"] == "표지":
            add_title_slide(prs, sd, meta)
        elif sd["section"] == "목차":
            add_toc_slide(prs, sd, project, page)
        else:
            add_content_slide(prs, sd, project, page)

    out = storyline_path.replace("_storyline.json", "_초안.pptx")
    # 출력 디렉터리 재지정(선택): DRAFT_OUT_DIR 가 있으면 그 폴더에 파일명만 떨군다.
    # (미설정 시 기존 동작 = storyline 옆에 생성. 원본 파이프라인 standalone 보존.)
    out_dir = os.environ.get("DRAFT_OUT_DIR")
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, os.path.basename(out))
    prs.save(out)
    n_flags = sum(1 for s in slides if s.get("flag"))
    print(f"[완료] {len(slides)}장 생성 → {out}")
    print(f"[검토요망] {n_flags}건 (제안사 실데이터·컨셉 확정 필요 슬라이드)")
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용: python make_pptx.py draft/<공고번호>_storyline.json")
        sys.exit(1)
    build(sys.argv[1])
