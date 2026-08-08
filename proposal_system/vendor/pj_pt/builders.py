"""
PPT 자동화 표준셋 — 버전 A · python-pptx 빌더 (form B 전체 적용).

제안서 슬라이드 17개 유형 + 공통 헤더 바를 코드로 생성한다. spec.json 토큰을 따른다.
새 제안서 덱을 코드로 조립할 때 사용. 텍스트만 바꿔 끼우면 된다.

사용:
    from builders import new_deck, blank, cover, section_cover, contrast_diagram, ...
    prs = new_deck()
    cover(blank(prs), title="...", question="...", client="...")
    prs.save("out.pptx")

데모:  python builders.py  →  _demo_setA.pptx (유형별 1장씩)
"""
import json, os
from pptx import Presentation
from pptx.util import Cm, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = json.load(open(os.path.join(HERE, "spec.json"), encoding="utf-8"))
C = SPEC["colors"]; F = SPEC["fonts"]; TS = SPEC["type_scale_pt"]; L = SPEC["layout"]
CW, CH = SPEC["canvas"]["width_cm"], SPEC["canvas"]["height_cm"]
M = L["margin_cm"]


def _rgb(key):
    return RGBColor.from_string(C[key]) if key in C else RGBColor.from_string(key)


def box(slide, l, t, w, h, fill=None, line=None, line_w=None, shape=MSO_SHAPE.RECTANGLE):
    sp = slide.shapes.add_shape(shape, Cm(l), Cm(t), Cm(w), Cm(h))
    sp.shadow.inherit = False
    if fill is None:
        sp.fill.background()
    else:
        sp.fill.solid(); sp.fill.fore_color.rgb = _rgb(fill)
    if line is None:
        sp.line.fill.background()
    else:
        sp.line.color.rgb = _rgb(line); sp.line.width = Pt(line_w or 1)
    return sp


def text(slide, l, t, w, h, runs, align="left", anchor="top", wrap=True):
    """runs: [(text, font_key, size_pt, color_key, bold?), ...] 또는 단일 문자열 도우미."""
    tb = slide.shapes.add_textbox(Cm(l), Cm(t), Cm(w), Cm(h))
    tf = tb.text_frame; tf.word_wrap = wrap
    tf.vertical_anchor = {"top": MSO_ANCHOR.TOP, "middle": MSO_ANCHOR.MIDDLE,
                          "bottom": MSO_ANCHOR.BOTTOM}[anchor]
    p = tf.paragraphs[0]
    p.alignment = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER,
                   "right": PP_ALIGN.RIGHT}[align]
    for run in runs:
        txt, fk, sz, ck = run[0], run[1], run[2], run[3]
        bold = bool(run[4]) if len(run) > 4 else False
        r = p.add_run(); r.text = txt
        r.font.name = F[fk]; r.font.size = Pt(sz)
        r.font.color.rgb = _rgb(ck); r.font.bold = bold
    return tb


def t1(s, l, t, w, h, txt, fk, sz, ck, bold=False, align="left", anchor="top"):
    return text(s, l, t, w, h, [(txt, fk, sz, ck, bold)], align=align, anchor=anchor)


# ===========================================================================
# 공통: 헤더 바 + 페이지 번호
# ===========================================================================
def header_bar(s, chapter_no, chapter_name, section, page_no=None, breadcrumb=""):
    box(s, 0, 0, 2.08, L["header_height_cm"], fill="orange")
    t1(s, 0, 0, 2.08, L["header_height_cm"], str(chapter_no), "heading", 16, "white", True, "center", "middle")
    t1(s, 2.44, 0.08, 3.6, 0.64, chapter_name, "subhead", 12, "navy", True, anchor="middle")
    t1(s, 6.2, 0.08, 9.0, 0.64, section, "body", 12, "black", anchor="middle")
    if breadcrumb:
        t1(s, 15.77, 0.08, 11.2, 0.64, breadcrumb, "caption", 11, "gray_text", align="right", anchor="middle")
    if page_no is not None:
        t1(s, CW - 3.0, L["page_number_top_cm"], 2.7, 0.8, str(page_no), "caption", 12, "gray_text", align="right")


def title_block(s, title, sub=None):
    t1(s, M, L["title_top_cm"], CW - 2 * M, 1.4, title, "heading", 28, "navy", True)
    if sub:
        t1(s, M, L["title_top_cm"] + 1.4, CW - 2 * M, 0.9, sub, "body", 16, "gray_text")


# ===========================================================================
# 1. 표지
# ===========================================================================
def cover(s, title, question="", client=""):
    box(s, 0, 0, CW, CH, fill="black")
    box(s, 0, CH * 0.34, CW, 0.12, fill="orange")
    if question:
        t1(s, M, CH * 0.30, CW - 2 * M, 1.2, question, "subhead", 18, "orange", True)
    t1(s, M, CH * 0.36, CW - 2 * M, 4.0, title, "title", 44, "white", True)
    if client:
        t1(s, M, CH - 2.0, CW - 2 * M, 1.2, client, "caption", 13, "white")


# ===========================================================================
# 2. 목차
# ===========================================================================
def toc(s, items, eyebrow="TABLE OF CONTENT"):
    """items: [(번호, 섹션명), ...]"""
    box(s, 0, 0, CW, CH, fill="black")
    t1(s, M, 1.6, CW - 2 * M, 1.0, eyebrow, "subhead", 16, "orange", True)
    cols = 2
    rows = (len(items) + cols - 1) // cols
    cw = (CW - 2 * M) / cols
    for i, (no, name) in enumerate(items):
        r, cI = i % rows, i // rows
        x = M + cI * cw
        y = 3.4 + r * ((CH - 5.0) / max(rows, 1))
        t1(s, x, y, 1.6, 0.9, str(no), "heading", 22, "orange", True)
        t1(s, x + 1.7, y + 0.1, cw - 2.0, 0.9, name, "body", 15, "white", anchor="middle")


# ===========================================================================
# 3 / 4. 챕터 섹션표지 · 하위섹션 표지
# ===========================================================================
def section_cover(s, number, label_en, title_ko, subtitle_en="", accent="navy"):
    box(s, 0, 0, CW, CH, fill="black")
    box(s, 3.36, 0, 9.38, CH, fill=accent)
    t1(s, 4.54, 2.3, 6.0, 0.7, label_en, "caption", 12, "white")
    t1(s, 4.46, 3.0, 5.0, 2.76, str(number), "title", 54, "white", True)
    if subtitle_en:
        t1(s, 4.73, 5.9, 7.0, 1.0, subtitle_en, "subhead", 22, "white", True)
    t1(s, 4.46, 8.2, 8.0, 2.0, title_ko, "heading", 24, "white", True)


def subsection_cover(s, label_en, title_ko, accent="orange"):
    box(s, 0, 0, CW, CH, fill="black")
    box(s, 3.36, 0, 9.38, CH, fill=accent)
    t1(s, 4.54, 7.0, 6.0, 0.7, label_en, "caption", 12, "white")
    t1(s, 4.46, 7.9, 8.0, 2.0, title_ko, "heading", 28, "white", True)


# ===========================================================================
# 5. 도입 · 문제제기
# ===========================================================================
def problem_intro(s, hdr, title, lead, body):
    header_bar(s, *hdr)
    box(s, M, L["title_top_cm"], 0.5, 1.4, fill="orange")
    t1(s, M + 0.8, L["title_top_cm"], CW - 2 * M, 1.4, title, "heading", 30, "navy", True)
    t1(s, M, 5.0, CW - 2 * M, 2.0, lead, "subhead", 20, "orange", True)
    t1(s, M, 7.2, CW - 2 * M, 6.0, body, "body", 17, "black")


# ===========================================================================
# 6. 현황분석 · 데이터 차트 (막대 수동 작도)
# ===========================================================================
def data_chart(s, hdr, title, bars, source="", highlight_idx=None):
    """bars: [(label, value0to100), ...]"""
    header_bar(s, *hdr)
    title_block(s, title, source)
    base_y, base_h = 14.0, 8.0
    n = len(bars); area_w = CW - 2 * M
    bw = area_w / n * 0.5
    gap = area_w / n
    for i, (lab, val) in enumerate(bars):
        x = M + i * gap + (gap - bw) / 2
        h = base_h * (val / 100.0)
        col = "orange" if (highlight_idx == i) else "navy"
        box(s, x, base_y - h, bw, h, fill=col)
        t1(s, x - 0.5, base_y - h - 0.9, bw + 1.0, 0.8, f"{val}%", "subhead", 14, col, True, "center")
        t1(s, x - 0.5, base_y + 0.2, bw + 1.0, 1.4, lab, "caption", 12, "gray_text", align="center")


# ===========================================================================
# 7. 대비형 다이어그램
# ===========================================================================
def contrast_diagram(s, hdr, title, left, right, left_label="AS-IS", right_label="TO-BE"):
    """left/right: (head, body)"""
    header_bar(s, *hdr)
    title_block(s, title)
    boxes = [(M, "navy", left_label, left), (14.5, "orange", right_label, right)]
    bw, by, bh = 12.0, 5.7, 9.0
    for x, acc, label, (head, body) in boxes:
        box(s, x, by, 3.2, 0.9, fill=acc)
        t1(s, x, by, 3.2, 0.9, label, "subhead", 13, "white", True, "center", "middle")
        box(s, x, by + 1.1, bw, bh, fill="gray_bg", line="gray_line", line_w=1)
        t1(s, x + 0.5, by + 1.6, bw - 1.0, 1.4, head, "subhead", 20, acc, True)
        t1(s, x + 0.5, by + 3.4, bw - 1.0, bh - 2.0, body, "body", 16, "black")
    ar = box(s, 13.0, by + 3.4, 1.5, 1.2, fill="orange", shape=MSO_SHAPE.RIGHT_ARROW)


# ===========================================================================
# 8. 카드형 상세 (2~4열)
# ===========================================================================
def card_grid(s, hdr, title, cards):
    """cards: [(head, body), ...]  2~4개 권장"""
    header_bar(s, *hdr)
    title_block(s, title)
    n = len(cards); gap = 0.5
    cw = (CW - 2 * M - gap * (n - 1)) / n
    cy, ch = L["content_top_cm"], 9.5
    for i, (head, body) in enumerate(cards):
        x = M + i * (cw + gap)
        box(s, x, cy, cw, 1.2, fill="navy")
        t1(s, x + 0.3, cy, cw - 0.6, 1.2, head, "subhead", 16, "white", True, anchor="middle")
        box(s, x, cy + 1.2, cw, ch - 1.2, fill="white", line="gray_line", line_w=1)
        t1(s, x + 0.4, cy + 1.6, cw - 0.8, ch - 2.0, body, "body", 14, "black")


# ===========================================================================
# 9. 스토리보드 씬 (1씬)
# ===========================================================================
def storyboard(s, hdr, scene_no, caption, note="", total=None):
    header_bar(s, *hdr)
    label = f"SCENE {scene_no}" + (f" / {total}" if total else "")
    t1(s, M, L["title_top_cm"], 8, 0.9, label, "subhead", 18, "orange", True)
    box(s, M, 3.4, CW - 2 * M, 9.5, fill="gray_bg", line="gray_line", line_w=1)
    t1(s, M, 6.5, CW - 2 * M, 1.0, "[ 비주얼 / 씬 이미지 ]", "caption", 14, "gray_text", align="center")
    t1(s, M, 13.4, CW - 2 * M, 1.2, caption, "subhead", 18, "navy", True)
    if note:
        t1(s, M, 14.8, CW - 2 * M, 2.0, note, "body", 15, "gray_text")


# ===========================================================================
# 10. 타임라인 · 매트릭스
# ===========================================================================
def timeline_matrix(s, hdr, title, phases, rows):
    """phases: [열머리...]  rows: [(행라벨, [구간:bool 또는 'navy'/'orange'/None ...]), ...]"""
    header_bar(s, *hdr)
    title_block(s, title)
    x0, y0 = M + 3.0, L["content_top_cm"] + 0.5
    col_w = (CW - x0 - M) / len(phases)
    for j, ph in enumerate(phases):
        t1(s, x0 + j * col_w, y0 - 0.9, col_w, 0.8, ph, "caption", 12, "navy", True, "center")
    row_h = min(1.4, (CH - y0 - 1.0) / max(len(rows), 1))
    for i, (lab, cells) in enumerate(rows):
        y = y0 + i * row_h
        t1(s, M, y, 3.0, row_h, lab, "subhead", 13, "navy", True, anchor="middle")
        for j, cell in enumerate(cells):
            if not cell:
                continue
            col = cell if isinstance(cell, str) else "orange"
            box(s, x0 + j * col_w + 0.1, y + 0.15, col_w - 0.2, row_h - 0.3, fill=col)


# ===========================================================================
# 11. 표 · 타임테이블
# ===========================================================================
def table_block(s, hdr, title, headers, data_rows):
    """headers: [열...]  data_rows: [[셀...], ...]"""
    header_bar(s, *hdr)
    title_block(s, title)
    nr, nc = len(data_rows) + 1, len(headers)
    gx, gy = Cm(M), Cm(L["content_top_cm"])
    gw, gh = Cm(CW - 2 * M), Cm(min(11.0, 0.9 * nr + 0.5))
    tbl = s.shapes.add_table(nr, nc, gx, gy, gw, gh).table
    for j, htxt in enumerate(headers):
        cell = tbl.cell(0, j)
        cell.fill.solid(); cell.fill.fore_color.rgb = _rgb("navy")
        _set_cell(cell, htxt, "white", 13, True)
    for i, row in enumerate(data_rows, 1):
        for j, val in enumerate(row):
            cell = tbl.cell(i, j)
            cell.fill.solid()
            cell.fill.fore_color.rgb = _rgb("gray_bg" if i % 2 else "white")
            _set_cell(cell, str(val), "black", 12, j == 0)


def _set_cell(cell, txt, ck, sz, bold):
    cell.text = txt
    p = cell.text_frame.paragraphs[0]
    for r in p.runs:
        r.font.name = F["body"]; r.font.size = Pt(sz)
        r.font.color.rgb = _rgb(ck); r.font.bold = bold


# ===========================================================================
# 12. STEP · 프로세스
# ===========================================================================
def process_steps(s, hdr, title, steps):
    """steps: [(라벨, 설명), ...]  3~5개"""
    header_bar(s, *hdr)
    title_block(s, title)
    n = len(steps); gap = 0.6
    bw = (CW - 2 * M - gap * (n - 1)) / n
    by, bh = 6.5, 5.5
    for i, (lab, desc) in enumerate(steps):
        x = M + i * (bw + gap)
        circ = box(s, x + bw / 2 - 0.7, by - 1.6, 1.4, 1.4, fill="orange", shape=MSO_SHAPE.OVAL)
        t1(s, x + bw / 2 - 0.7, by - 1.6, 1.4, 1.4, str(i + 1), "heading", 18, "white", True, "center", "middle")
        box(s, x, by, bw, bh, fill="gray_bg", line="gray_line", line_w=1)
        t1(s, x + 0.3, by + 0.4, bw - 0.6, 1.2, lab, "subhead", 16, "navy", True, "center")
        t1(s, x + 0.3, by + 1.8, bw - 0.6, bh - 2.0, desc, "body", 13, "black", "center")
        if i < n - 1:
            box(s, x + bw + 0.05, by + bh / 2 - 0.3, gap - 0.1, 0.6, fill="orange", shape=MSO_SHAPE.RIGHT_ARROW)


# ===========================================================================
# 13. 지도형 (플레이스홀더 + 핀 라벨)
# ===========================================================================
def map_block(s, hdr, title, regions):
    """regions: [라벨, ...]"""
    header_bar(s, *hdr)
    title_block(s, title)
    box(s, M, L["content_top_cm"], CW - 2 * M, 9.5, fill="gray_bg", line="gray_line", line_w=1)
    t1(s, M, 8.3, CW - 2 * M, 1.0, "[ 지도 / 권역 비주얼 ]", "caption", 14, "gray_text", align="center")
    y = L["content_top_cm"] + 0.3
    for i, lab in enumerate(regions):
        bx = M + 0.4 + (i % 4) * ((CW - 2 * M - 0.8) / 4)
        by = y + (i // 4) * 1.1
        box(s, bx, by, 0.3, 0.3, fill="orange", shape=MSO_SHAPE.OVAL)
        t1(s, bx + 0.45, by - 0.15, 5.0, 0.6, lab, "body", 13, "navy", True, anchor="middle")


# ===========================================================================
# 14. 인물 카드
# ===========================================================================
def person_cards(s, hdr, title, people):
    """people: [(이름, 역할/경력), ...]"""
    header_bar(s, *hdr)
    title_block(s, title)
    n = len(people); gap = 0.5
    cw = (CW - 2 * M - gap * (n - 1)) / n
    cy, ch = L["content_top_cm"], 9.0
    for i, (name, role) in enumerate(people):
        x = M + i * (cw + gap)
        box(s, x, cy, cw, ch, fill="white", line="gray_line", line_w=1)
        box(s, x + cw / 2 - 1.2, cy + 0.6, 2.4, 2.4, fill="navy", shape=MSO_SHAPE.OVAL)
        t1(s, x + 0.2, cy + 3.4, cw - 0.4, 1.0, name, "subhead", 18, "navy", True, "center")
        t1(s, x + 0.2, cy + 4.5, cw - 0.4, ch - 4.7, role, "body", 13, "gray_text", "center")


# ===========================================================================
# 15. 조직도
# ===========================================================================
def org_chart(s, hdr, title, root, children):
    """root: 문자열, children: [라벨, ...]"""
    header_bar(s, *hdr)
    title_block(s, title)
    rx, rw = CW / 2 - 3.0, 6.0
    box(s, rx, 4.6, rw, 1.4, fill="navy")
    t1(s, rx, 4.6, rw, 1.4, root, "subhead", 18, "white", True, "center", "middle")
    n = len(children); gap = 0.5
    cw = (CW - 2 * M - gap * (n - 1)) / n
    cy = 9.0
    box(s, CW / 2 - 0.02, 6.0, 0.04, 2.4, fill="gray_line")
    for i, lab in enumerate(children):
        x = M + i * (cw + gap)
        box(s, x, cy, cw, 2.2, fill="white", line="navy", line_w=1.5)
        t1(s, x + 0.3, cy, cw - 0.6, 2.2, lab, "body", 14, "navy", True, "center", "middle")


# ===========================================================================
# 16. 실적 · 포트폴리오
# ===========================================================================
def portfolio_case(s, hdr, title, cases):
    """cases: [(라벨, 한줄설명), ...]  2~3열 그리드"""
    header_bar(s, *hdr)
    title_block(s, title)
    cols = 3; n = len(cases); gap = 0.5
    cw = (CW - 2 * M - gap * (cols - 1)) / cols
    rows = (n + cols - 1) // cols
    ch = (CH - L["content_top_cm"] - 1.0 - gap * (rows - 1)) / rows
    for i, (lab, desc) in enumerate(cases):
        r, cI = i // cols, i % cols
        x = M + cI * (cw + gap)
        y = L["content_top_cm"] + r * (ch + gap)
        box(s, x, y, cw, ch * 0.45, fill="gray_bg", line="gray_line", line_w=1)
        box(s, x, y + ch * 0.45, cw, 0.5, fill="orange")
        t1(s, x + 0.3, y + ch * 0.45, cw - 0.6, 0.5, lab, "caption", 11, "white", True, anchor="middle")
        t1(s, x + 0.3, y + ch * 0.45 + 0.6, cw - 0.6, ch * 0.45, desc, "body", 13, "black")


# ===========================================================================
# 17. 마무리 매트릭스
# ===========================================================================
def closing_matrix(s, hdr, title, columns):
    """columns: [(단계명, [킬링포인트...]), ...]"""
    header_bar(s, *hdr)
    title_block(s, title)
    n = len(columns); gap = 0.4
    cw = (CW - 2 * M - gap * (n - 1)) / n
    cy, ch = L["content_top_cm"], 9.5
    for i, (stage, points) in enumerate(columns):
        x = M + i * (cw + gap)
        box(s, x, cy, cw, 1.1, fill="orange" if i % 2 else "navy")
        t1(s, x + 0.2, cy, cw - 0.4, 1.1, stage, "subhead", 14, "white", True, "center", "middle")
        box(s, x, cy + 1.1, cw, ch - 1.1, fill="gray_bg", line="gray_line", line_w=1)
        body = "\n".join(f"• {p}" for p in points)
        t1(s, x + 0.3, cy + 1.5, cw - 0.6, ch - 1.8, body, "body", 13, "black")


# ===========================================================================
# 덱 도우미
# ===========================================================================
def new_deck():
    prs = Presentation()
    prs.slide_width = Cm(CW); prs.slide_height = Cm(CH)
    return prs


def blank(prs):
    return prs.slides.add_slide(prs.slide_layouts[6])


def _demo():
    prs = new_deck()
    H = ("2", "본론", "데모 섹션")  # 공통 헤더 인자 (챕터번호, 챕터명, 섹션명)

    cover(blank(prs), title="프레젠테이션 제목을 입력하세요", question="핵심 메시지 한 줄",
          client="조직명 / 작성자")
    toc(blank(prs), [(f"{i:02d}", n) for i, n in enumerate(
        ["개요", "배경", "현황 분석", "핵심 과제", "전략 방향",
         "실행 계획", "일정", "기대 효과", "조직·역할", "마무리"], 1)])
    section_cover(blank(prs), "02", "CHAPTER 02", "섹션 제목", "Section Title", "orange")
    subsection_cover(blank(prs), "SUB SECTION", "하위 섹션 제목", "navy")
    problem_intro(blank(prs), H, "핵심 질문 또는 문제 정의",
                  "한 문장으로 압축한 인사이트",
                  "여기에 배경과 문제의식을 서술한다. 현재 상황을 설명하고, 왜 변화가 필요한지 근거를 제시하는 본문 영역이다.")
    data_chart(blank(prs), H, "데이터 근거 — 지표 비교",
               [("항목 A", 34), ("항목 B", 30), ("항목 C", 45), ("항목 D", 31), ("항목 E", 6)],
               source="출처: 데이터 출처 표기", highlight_idx=2)
    contrast_diagram(blank(prs), H, "현재와 목표 — 방향 전환",
                     ("현재 상태(As-Is)", "현재의 한계와 문제점을 요약한다. 무엇이 부족하고 어떤 리스크가 있는지 정리한다."),
                     ("목표 상태(To-Be)", "전환 후의 모습을 제시한다. 어떤 가치를 더하고 어떻게 개선되는지 서술한다."))
    card_grid(blank(prs), H, "주요 항목 비교",
              [("항목 1", "항목 1에 대한 설명"), ("항목 2", "항목 2에 대한 설명"),
               ("항목 3", "항목 3에 대한 설명"), ("항목 4", "항목 4에 대한 설명")])
    storyboard(blank(prs), H, 3, "장면 제목 또는 캡션", "장면에 대한 부연 설명을 적는다.", total=12)
    timeline_matrix(blank(prs), H, "기간별 실행 계획",
                    ["1분기", "2분기", "3분기", "4분기", "5분기"],
                    [("트랙 A", [None, "orange", "orange", "navy", None]),
                     ("트랙 B", ["navy", "navy", None, None, "orange"]),
                     ("트랙 C", [None, None, "navy", "navy", "navy"])])
    table_block(blank(prs), H, "세부 일정표",
                ["구분", "1단계", "2단계", "3단계"],
                [["항목 A", "내용", "내용", "내용"],
                 ["항목 B", "내용", "내용", "내용"],
                 ["항목 C", "내용", "내용", "내용"]])
    process_steps(blank(prs), H, "실행 프로세스",
                  [("1단계", "단계 설명"), ("2단계", "단계 설명"),
                   ("3단계", "단계 설명"), ("4단계", "단계 설명")])
    map_block(blank(prs), H, "권역별 현황",
              ["권역 1", "권역 2", "권역 3", "권역 4", "권역 5", "권역 6"])
    person_cards(blank(prs), H, "핵심 인력",
                 [("이름 / 직책", "주요 경력 한 줄"), ("이름 / 직책", "주요 경력 한 줄"),
                  ("이름 / 직책", "주요 경력 한 줄")])
    org_chart(blank(prs), H, "조직 구성", "총괄 조직",
              ["팀 A", "팀 B", "팀 C", "팀 D"])
    portfolio_case(blank(prs), H, "주요 사례",
                   [("사례 1", "한 줄 설명"), ("사례 2", "한 줄 설명"),
                    ("사례 3", "한 줄 설명"), ("사례 4", "한 줄 설명"),
                    ("사례 5", "한 줄 설명"), ("사례 6", "한 줄 설명")])
    closing_matrix(blank(prs), H, "핵심 포인트 종합",
                   [("단계 1", ["포인트 A", "포인트 B"]), ("단계 2", ["포인트 A", "포인트 B"]),
                    ("단계 3", ["포인트 A", "포인트 B"]), ("단계 4", ["포인트 A", "포인트 B"])])

    out = os.path.join(HERE, "_demo_setA.pptx")
    prs.save(out)
    print("저장:", out, "| 슬라이드", len(prs.slides._sldIdLst))


if __name__ == "__main__":
    _demo()
