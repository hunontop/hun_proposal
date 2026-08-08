"""
PPTX 익명화 — 텍스트 더미화 + 이미지 난독화 (이미지별 방법 자동 분류 + 사용자 검토).

흐름 (사용자 사전 선택형):
  1) plan  : 이미지를 분석해 이미지별 추천 방법을 계획파일(CSV)로 출력
  2) (사람) 계획파일의 method 열을 검토·수정
  3) apply : 계획파일대로 텍스트 더미화 + 이미지 난독화 적용

빠른 경로:
  auto  : 검토 없이 추천 방법 그대로 적용

도형 ID는 보존되어, 이후 op_replay 재생/inventory 와 호환된다.
"""
import random
import io
import os
import sys
import csv
from pptx import Presentation
from pptx.oxml.ns import qn

import image_obfuscate
from op_replay import iter_shapes

try:
    import font_check
except Exception:
    font_check = None

HANGUL_START = 0xAC00
HANGUL_END = 0xD7A3
LOREM_VOWELS = 'aeiou'
LOREM_CONSONANTS = 'bcdfghjklmnpqrstvwxyz'


# ---------------------------------------------------------------- 텍스트 더미화
def anonymize_char(char):
    code = ord(char)
    if HANGUL_START <= code <= HANGUL_END:
        return chr(random.randint(HANGUL_START, HANGUL_END))
    elif char.isalpha() and code < 128:
        pool = LOREM_VOWELS if char.lower() in LOREM_VOWELS else LOREM_CONSONANTS
        c = random.choice(pool)
        return c.upper() if char.isupper() else c
    elif char.isdigit():
        return str(random.randint(0, 9))
    return char


def anonymize_text(text):
    return ''.join(anonymize_char(c) for c in text)


def _process_text_frame(tf):
    for para in tf.paragraphs:
        for run in para.runs:
            if run.text:
                run.text = anonymize_text(run.text)


def _anonymize_all_text(prs):
    for slide in prs.slides:
        for shape in iter_shapes(slide):
            if shape.has_text_frame:
                _process_text_frame(shape.text_frame)
            if shape.has_table:
                for row in shape.table.rows:
                    for cell in row.cells:
                        _process_text_frame(cell.text_frame)


# ---------------------------------------------------------------- 이미지 수집/분석
def collect_image_parts(prs):
    """고유 이미지 part 수집. 같은 이미지를 여러 번 처리하지 않도록 partname으로 중복 제거.

    반환: dict partname -> {"part": ImagePart, "occurrences": [(slide_no, shape_id), ...]}
    """
    parts = {}
    for sno, slide in enumerate(prs.slides, 1):
        for shape in iter_shapes(slide):
            for blip in shape._element.findall('.//' + qn('a:blip')):
                rId = blip.get(qn('r:embed'))
                if not rId:
                    continue
                try:
                    part = slide.part.related_part(rId)
                except Exception:
                    continue
                pn = str(part.partname)
                entry = parts.setdefault(pn, {"part": part, "occurrences": []})
                entry["occurrences"].append((sno, shape.shape_id))
    return parts


def analyze_images(prs):
    """이미지별 분석 + 추천 방법. 반환: list of row dict (partname 기준)."""
    parts = collect_image_parts(prs)
    rows = []
    for pn, info in parts.items():
        img = None
        try:
            img = image_obfuscate._open(info["part"].blob)
            c = image_obfuscate.classify(img)
        except Exception as e:
            c = {"edge": -1, "colors": -1, "long_edge": -1,
                 "suggested": "fill", "review": True}  # 분석 실패 → 안전쪽
        finally:
            if img is not None:
                try:
                    img.close()   # 장수명 GUI에서 PIL 메모리 누적 방지
                except Exception:
                    pass
        occ = info["occurrences"]
        rows.append({
            "partname": pn,
            "file": pn.split("/")[-1],
            "slides": ";".join(str(s) for s, _ in occ),
            "count": len(occ),
            "long_px": c["long_edge"],
            "edge": c["edge"],
            "colors": c["colors"],
            "suggested": c["suggested"],
            "method": c["suggested"],     # 사용자가 수정할 열 (기본=추천)
            "review": "검토요망" if c["review"] else "",
        })
    rows.sort(key=lambda r: (-r["edge"]))
    return rows


# ---------------------------------------------------------------- 계획파일 입출력
PLAN_FIELDS = ["partname", "file", "slides", "count", "long_px",
               "edge", "colors", "suggested", "method", "review"]


def write_plan(rows, path):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=PLAN_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in PLAN_FIELDS})


def read_plan(path):
    """계획파일 → dict partname -> method. method 비면 suggested 사용."""
    methods = {}
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            m = (r.get("method") or "").strip() or (r.get("suggested") or "").strip()
            if r.get("partname"):
                methods[r["partname"]] = m
    return methods


# ---------------------------------------------------------------- 적용
def apply_images(prs, methods, default_method="pixelate",
                 pixelate_strength="medium", blur_ratio=0.02):
    """이미지별 method 적용 (고유 part 1회). 반환: 적용 카운트 dict."""
    parts = collect_image_parts(prs)
    counts = {}
    for pn, info in parts.items():
        method = methods.get(pn, default_method)
        try:
            info["part"]._blob = image_obfuscate.obfuscate_blob(
                info["part"].blob, method,
                pixelate_strength=pixelate_strength, blur_ratio=blur_ratio)
            counts[method] = counts.get(method, 0) + 1
        except Exception as e:
            print(f"  [warn] {pn} ({method}) 실패: {e}")
    return counts


def anonymize(prs_path, out_path, methods=None, default_method="pixelate",
              do_text=True, pixelate_strength="medium", blur_ratio=0.02, prs=None):
    if prs is None:
        prs = Presentation(prs_path)
    if do_text:
        _anonymize_all_text(prs)
    counts = apply_images(prs, methods or {}, default_method,
                          pixelate_strength, blur_ratio)
    prs.save(out_path)
    return counts


# ---------------------------------------------------------------- 폰트 경고
def warn_missing_fonts(input_path, prs=None):
    if font_check is None:
        return
    try:
        rep = font_check.check_fonts(input_path, prs=prs)
    except Exception:
        return
    crit = rep['missing_content']
    if crit:
        print(f"[폰트 경고] 본문 사용·미설치 폰트 {len(crit)}종 → 레이아웃 깨질 수 있음 "
              f"(상세: python anonymize_pptx.py check-fonts \"{input_path}\")")


# ---------------------------------------------------------------- CLI
def _default_out(pptx):
    base, ext = os.path.splitext(pptx)
    return f"{base}_익명화{ext}"


def _print_plan_summary(rows):
    from collections import Counter
    c = Counter(r["suggested"] for r in rows)
    n_review = sum(1 for r in rows if r["review"])
    print(f"이미지 {len(rows)}개 | 추천: " +
          ", ".join(f"{k}={v}" for k, v in c.items()) +
          (f" | 검토요망 {n_review}개" if n_review else ""))


def main():
    sys.stdout.reconfigure(encoding="utf-8") if hasattr(sys.stdout, "reconfigure") else None
    args = sys.argv[1:]
    cmds = ("plan", "apply", "auto", "check-fonts")
    if not args or args[0] not in cmds:
        print("사용법:")
        print("  python anonymize_pptx.py plan  <pptx> [plan.csv]      이미지 분석→계획파일")
        print("  python anonymize_pptx.py apply <pptx> <plan.csv> [out]  계획대로 적용")
        print("  python anonymize_pptx.py auto  <pptx> [out]           검토없이 추천대로 적용")
        print("  python anonymize_pptx.py check-fonts <pptx>           폰트 점검")
        return

    random.seed()
    cmd = args[0]

    if cmd == "check-fonts":
        if font_check is None:
            print("font_check 모듈 없음"); return
        print(font_check.format_report(font_check.check_fonts(args[1])))
        return

    if cmd == "plan":
        pptx = args[1]
        out_csv = args[2] if len(args) > 2 else os.path.splitext(pptx)[0] + "_계획.csv"
        prs = Presentation(pptx)
        rows = analyze_images(prs)
        write_plan(rows, out_csv)
        _print_plan_summary(rows)
        warn_missing_fonts(pptx, prs=prs)
        print(f"계획파일 저장 → {out_csv}")
        print("  method 열을 검토·수정한 뒤:  python anonymize_pptx.py apply \""
              f"{pptx}\" \"{out_csv}\"")
        return

    if cmd == "apply":
        pptx, plan = args[1], args[2]
        out = args[3] if len(args) > 3 else _default_out(pptx)
        methods = read_plan(plan)
        prs = Presentation(pptx)
        warn_missing_fonts(pptx, prs=prs)
        counts = anonymize(pptx, out, methods=methods, prs=prs)
        print("적용: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
        print(f"완료 → {out}")
        return

    if cmd == "auto":
        pptx = args[1]
        out = args[2] if len(args) > 2 else _default_out(pptx)
        prs = Presentation(pptx)
        rows = analyze_images(prs)
        methods = {r["partname"]: r["suggested"] for r in rows}
        _print_plan_summary(rows)
        warn_missing_fonts(pptx, prs=prs)
        counts = anonymize(pptx, out, methods=methods, prs=prs)
        print("적용: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
        print(f"완료 → {out}")
        return


if __name__ == "__main__":
    main()
