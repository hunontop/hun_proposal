"""
연산 재생(Operation-replay) 엔진 — 복원 가능한 익명화 워크플로의 핵심.

워크플로:
  1. anonymize_pptx.py 로 원본 → 익명화본 생성 (도형 ID는 그대로 보존됨)
  2. 익명화본을 외부 에이전트에 전달 → 에이전트가 '편집 지시 목록(ops.json)' 출력
  3. 이 모듈로 지시 목록을 *로컬 원본* 에 그대로 재생 → 원본 내용은 유출/변경 없이 디자인만 반영

핵심 전제: 익명화본은 원본에서 파생되므로 (슬라이드 번호, 도형 ID cNvPr)가 양쪽에서 동일.
           따라서 익명화본 기준으로 작성된 연산을 원본에 그대로 적용할 수 있다.

GUI/에이전트 연동:
    from op_replay import export_inventory, apply_operations
    inv = export_inventory("anon.pptx")          # 에이전트에게 줄 도형 목록
    report = apply_operations("orig.pptx", ops, "out.pptx")

좌표 단위는 사람이/에이전트가 다루기 쉽게 cm, 글자 크기는 pt 사용.
"""
import io
import os
import json
from pptx import Presentation
from pptx.util import Cm, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.oxml.ns import qn

EMU_PER_CM = 360000


# ----------------------------------------------------------------------------
# 도형 탐색
# ----------------------------------------------------------------------------
def iter_shapes(container):
    """그룹 내부까지 재귀적으로 모든 도형을 순회."""
    for shape in container.shapes:
        yield shape
        if shape.shape_type == 6:  # GROUP
            yield from iter_shapes(shape)


def find_shape(prs, slide_no, shape_id):
    """(슬라이드 번호 1-base, 도형 ID)로 도형을 찾는다. 없으면 None."""
    if slide_no < 1 or slide_no > len(prs.slides):
        return None
    slide = prs.slides[slide_no - 1]
    for shape in iter_shapes(slide):
        if shape.shape_id == shape_id:
            return shape
    return None


# ----------------------------------------------------------------------------
# 인벤토리 — 에이전트가 무엇을 편집할지 알 수 있도록 도형 목록을 내보냄
# ----------------------------------------------------------------------------
def _shape_text(shape):
    if shape.has_text_frame:
        t = shape.text_frame.text.strip().replace("\n", " ")
        return t[:40]
    return ""


def export_inventory(pptx_path, out_json=None):
    """슬라이드별 도형 목록(ID/이름/종류/위치/크기/텍스트미리보기)을 구조화해 반환."""
    prs = Presentation(pptx_path)
    slides = []
    for i, slide in enumerate(prs.slides, 1):
        shapes = []
        for shape in iter_shapes(slide):
            try:
                shapes.append({
                    "shape_id": shape.shape_id,
                    "name": shape.name,
                    "type": str(shape.shape_type),
                    "left_cm": round(shape.left / EMU_PER_CM, 2) if shape.left is not None else None,
                    "top_cm": round(shape.top / EMU_PER_CM, 2) if shape.top is not None else None,
                    "width_cm": round(shape.width / EMU_PER_CM, 2) if shape.width is not None else None,
                    "height_cm": round(shape.height / EMU_PER_CM, 2) if shape.height is not None else None,
                    "text": _shape_text(shape),
                })
            except Exception:
                continue
        slides.append({"slide": i, "shapes": shapes})
    inv = {
        "file": os.path.basename(pptx_path),
        "slide_count": len(prs.slides),
        "slide_width_cm": round(prs.slide_width / EMU_PER_CM, 2),
        "slide_height_cm": round(prs.slide_height / EMU_PER_CM, 2),
        "slides": slides,
    }
    if out_json:
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(inv, f, ensure_ascii=False, indent=2)
    return inv


# ----------------------------------------------------------------------------
# 개별 연산
# ----------------------------------------------------------------------------
def _color(v):
    return RGBColor.from_string(v.lstrip("#").upper())


def _op_move(shape, op):
    if "left_cm" in op:
        shape.left = Cm(op["left_cm"])
    if "top_cm" in op:
        shape.top = Cm(op["top_cm"])


def _op_nudge(shape, op):
    shape.left = Emu(int(shape.left) + int(Cm(op.get("dx_cm", 0))))
    shape.top = Emu(int(shape.top) + int(Cm(op.get("dy_cm", 0))))


def _op_resize(shape, op):
    if "width_cm" in op:
        shape.width = Cm(op["width_cm"])
    if "height_cm" in op:
        shape.height = Cm(op["height_cm"])


def _op_scale(shape, op):
    f = float(op["factor"])
    shape.width = Emu(int(int(shape.width) * f))
    shape.height = Emu(int(int(shape.height) * f))


def _op_delete(shape, op):
    shape._element.getparent().remove(shape._element)


def _op_set_fill(shape, op):
    shape.fill.solid()
    shape.fill.fore_color.rgb = _color(op["color"])


def _op_set_line(shape, op):
    if "color" in op:
        shape.line.color.rgb = _color(op["color"])
    if "width_pt" in op:
        shape.line.width = Pt(op["width_pt"])


_ALIGN = {
    "left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER,
    "right": PP_ALIGN.RIGHT, "justify": PP_ALIGN.JUSTIFY,
}


def _op_set_font(shape, op):
    if not shape.has_text_frame:
        raise ValueError("text_frame 없음")
    for para in shape.text_frame.paragraphs:
        if "align" in op:
            para.alignment = _ALIGN.get(op["align"], para.alignment)
        for run in para.runs:
            if "size_pt" in op:
                run.font.size = Pt(op["size_pt"])
            if "bold" in op:
                run.font.bold = bool(op["bold"])
            if "italic" in op:
                run.font.italic = bool(op["italic"])
            if "color" in op:
                run.font.color.rgb = _color(op["color"])


def _op_set_zorder(shape, op):
    el = shape._element
    spTree = el.getparent()
    spTree.remove(el)
    if op.get("to", "front") == "front":
        spTree.append(el)
    else:  # back: 도형류 첫 자식 앞에 삽입
        insert_idx = 0
        for i, child in enumerate(spTree):
            tag = child.tag.split("}")[-1]
            if tag in ("sp", "pic", "graphicFrame", "grpSp", "cxnSp"):
                insert_idx = i
                break
        spTree.insert(insert_idx, el)


SHAPE_OPS = {
    "move": _op_move,
    "nudge": _op_nudge,
    "resize": _op_resize,
    "scale": _op_scale,
    "delete": _op_delete,
    "set_fill": _op_set_fill,
    "set_line": _op_set_line,
    "set_font": _op_set_font,
    "set_zorder": _op_set_zorder,
}


# ----------------------------------------------------------------------------
# 슬라이드 단위 연산 (도형 ID 불필요)
# ----------------------------------------------------------------------------
def _op_reorder_slides(prs, op):
    """order: 1-base 원본 위치의 새 순서 리스트. 예) [1,3,2,4]"""
    order = op["order"]
    sldIdLst = prs.slides._sldIdLst
    ids = list(sldIdLst)
    if sorted(order) != list(range(1, len(ids) + 1)):
        raise ValueError(f"order는 1..{len(ids)} 순열이어야 함")
    new = [ids[i - 1] for i in order]
    for el in ids:
        sldIdLst.remove(el)
    for el in new:
        sldIdLst.append(el)


PRES_OPS = {
    "reorder_slides": _op_reorder_slides,
}


# ----------------------------------------------------------------------------
# 검증 — 재생 전에 ops.json 이 유효한지(스키마 + 도형 존재) 점검
# ----------------------------------------------------------------------------
# 연산별 필수/허용 키
_REQUIRED = {
    "move": [], "nudge": [], "resize": [], "scale": ["factor"],
    "delete": [], "set_fill": ["color"], "set_line": [],
    "set_font": [], "set_zorder": [], "reorder_slides": ["order"],
}


def validate_operations(in_path, ops):
    """ops 를 in_path 기준으로 사전 검증. 재생은 하지 않는다.

    반환: {"ok": bool, "errors": [...], "warnings": [...], "count": n}
      - errors: 적용 불가(알 수 없는 연산, 필수키 누락, 도형/슬라이드 없음 등)
      - warnings: 적용은 되나 주의(예: 텍스트 내용 변경 시도 흔적 등)
    """
    if isinstance(ops, str):
        with open(ops, "r", encoding="utf-8") as f:
            ops = json.load(f)
    if isinstance(ops, dict):
        ops = ops.get("operations", [])

    prs = Presentation(in_path)
    n_slides = len(prs.slides)
    errors, warnings = [], []

    for i, op in enumerate(ops):
        name = op.get("op")
        if name not in SHAPE_OPS and name not in PRES_OPS:
            errors.append(f"#{i}: 알 수 없는 연산 '{name}'")
            continue
        for key in _REQUIRED.get(name, []):
            if key not in op:
                errors.append(f"#{i} {name}: 필수 키 '{key}' 누락")
        if name in PRES_OPS:
            if name == "reorder_slides":
                order = op.get("order", [])
                if sorted(order) != list(range(1, n_slides + 1)):
                    errors.append(f"#{i} reorder_slides: order는 1..{n_slides} 순열이어야 함")
            continue
        # 도형 연산: 슬라이드/도형 존재 확인
        slide = op.get("slide")
        sid = op.get("shape_id")
        if not isinstance(slide, int) or not isinstance(sid, int):
            errors.append(f"#{i} {name}: 'slide','shape_id'(정수) 필요")
            continue
        if find_shape(prs, slide, sid) is None:
            errors.append(f"#{i} {name}: 도형 없음 (slide={slide}, id={sid})")

    return {"ok": len(errors) == 0, "errors": errors, "warnings": warnings, "count": len(ops)}


# ----------------------------------------------------------------------------
# 재생 엔진
# ----------------------------------------------------------------------------
def apply_operations(in_path, ops, out_path):
    """원본(in_path)에 연산 목록을 재생해 out_path로 저장.

    ops: dict({"operations": [...]}) 또는 list([...]) 또는 ops.json 경로(str)
    반환: {applied, failed, details:[...]}  — 각 연산의 성공/실패 리포트
    """
    if isinstance(ops, str):
        with open(ops, "r", encoding="utf-8") as f:
            ops = json.load(f)
    if isinstance(ops, dict):
        ops = ops.get("operations", [])

    prs = Presentation(in_path)
    applied, failed, details = 0, 0, []

    for idx, op in enumerate(ops):
        name = op.get("op")
        try:
            if name in PRES_OPS:
                PRES_OPS[name](prs, op)
            elif name in SHAPE_OPS:
                shape = find_shape(prs, op["slide"], op["shape_id"])
                if shape is None:
                    raise LookupError(
                        f"도형 없음 (slide={op.get('slide')}, id={op.get('shape_id')})")
                SHAPE_OPS[name](shape, op)
            else:
                raise ValueError(f"알 수 없는 연산: {name}")
            applied += 1
            details.append({"i": idx, "op": name, "ok": True})
        except Exception as e:
            failed += 1
            details.append({"i": idx, "op": name, "ok": False, "error": str(e)})

    prs.save(out_path)
    return {"applied": applied, "failed": failed, "details": details, "output": out_path}


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    args = sys.argv[1:]
    if not args or args[0] not in ("inventory", "apply", "validate"):
        print("사용법:")
        print("  python op_replay.py inventory <pptx> [out.json]")
        print("  python op_replay.py validate <원본.pptx> <ops.json>")
        print("  python op_replay.py apply <원본.pptx> <ops.json> <출력.pptx>")
        sys.exit(0)

    if args[0] == "validate":
        rep = validate_operations(args[1], args[2])
        print(f"연산 {rep['count']}개 | " +
              ("검증 OK" if rep['ok'] else f"오류 {len(rep['errors'])}건"))
        for e in rep["errors"]:
            print(f"  [오류] {e}")
        for w in rep["warnings"]:
            print(f"  [주의] {w}")
        sys.exit(0 if rep["ok"] else 1)

    if args[0] == "inventory":
        out = args[2] if len(args) > 2 else None
        inv = export_inventory(args[1], out)
        if out:
            print(f"인벤토리 저장: {out} (슬라이드 {inv['slide_count']}개)")
        else:
            print(json.dumps(inv, ensure_ascii=False, indent=2))
    else:
        rep = apply_operations(args[1], args[2], args[3])
        print(f"적용 {rep['applied']} / 실패 {rep['failed']} → {rep['output']}")
        for d in rep["details"]:
            if not d["ok"]:
                print(f"  [실패] #{d['i']} {d['op']}: {d['error']}")
