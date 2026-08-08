"""
이미지 난독화 방법 + 자동 분류 (로컬·경량).

방법(method):
  - keep     : 그대로 둠 (단색 블록 등 숨길 내용 없음)
  - pixelate : 다운스케일(모자이크) — 가볍고 색·대략 구도 유지. 일반 사진/그림용
  - fill     : 평균색 단색 채움 — 비가역·최대 안전. 읽을 수 있는 텍스트/도표용
  - blur     : 가우시안 블러(다운스케일 후) — 레거시 호환

자동 분류(classify):
  - 엣지 밀도(텍스트·도표=높음) + 색상 다양성(사진=많음) + 크기로 method 제안
  - 휴리스틱이므로 '검토요망(review)' 플래그를 함께 내어 사람이 최종 확인하게 함
"""
import io
from PIL import Image, ImageFilter, ImageStat

# 자동 분류 임계값 (덱 이미지 분포로 보정)
# 6개 덱·40장 표본 평가(2026-06-05): 기존 70/350은 텍스트 recall 21%로 낮았음
# (텍스트 이미지 colors가 2473까지, edge가 17~161로 사진과 겹침). 33/800으로 완화해
# recall≈50%·과보호≈15%로 개선. edge+colors만으론 한계가 있어 실사용하며 재조정 예정.
EDGE_TEXT = 33      # 이 이상이면 텍스트/도표 의심
COLORS_TEXT = 800   # 이 이하면 텍스트/도표 의심 (사진은 색이 많음)
SOLID_COLORS = 2    # 이 이하면 단색 블록 (숨길 내용 없음)
# 경계 부근 → 검토요망 (완화된 컷오프 주변으로 조정)
EDGE_REVIEW = (25, 50)
COLORS_REVIEW = (500, 1500)

PIXELATE_PX = {"light": 64, "medium": 40, "strong": 24}


def _open(blob):
    return Image.open(io.BytesIO(blob))


def classify(img):
    """이미지 특성으로 method 제안. img: PIL Image.

    반환: {edge, colors, long_edge, suggested, review}
    """
    rgb = img.convert("RGB")
    long_edge = max(rgb.size)

    g = rgb.convert("L")
    g.thumbnail((160, 160))
    edge = ImageStat.Stat(g.filter(ImageFilter.FIND_EDGES)).mean[0]

    t = rgb.copy()
    t.thumbnail((64, 64))
    cols = t.getcolors(maxcolors=100000)
    colors = len(cols) if cols else 100000

    if colors <= SOLID_COLORS:
        suggested = "keep"
    elif edge >= EDGE_TEXT and colors <= COLORS_TEXT:
        suggested = "fill"        # 텍스트/도표 → 비가역 안전
    else:
        suggested = "pixelate"    # 사진/그림 → 경량, 구도 유지

    review = (suggested != "keep" and
              (EDGE_REVIEW[0] <= edge <= EDGE_REVIEW[1] or
               COLORS_REVIEW[0] <= colors <= COLORS_REVIEW[1]))

    return {
        "edge": round(edge, 1), "colors": colors,
        "long_edge": long_edge, "suggested": suggested, "review": review,
    }


def _save(img, fmt):
    out = io.BytesIO()
    if fmt.upper() in ("JPEG", "JPG"):
        img = img.convert("RGB")
    img.save(out, format=fmt)
    return out.getvalue()


def obfuscate_blob(blob, method, pixelate_strength="medium",
                   blur_ratio=0.02, blur_cap=800):
    """blob에 method를 적용해 새 bytes 반환. 실패 시 안전하게 원본 유지하지 않고 예외."""
    if method == "keep":
        return blob

    img = _open(blob)
    fmt = img.format or "PNG"

    if method == "pixelate":
        target = PIXELATE_PX.get(pixelate_strength, 40)
        small = img.convert("RGB")
        small.thumbnail((target, target))   # 다운스케일 = 모자이크, 저장도 작음
        return _save(small, fmt)

    if method == "fill":
        rgb = img.convert("RGB")
        avg = rgb.resize((1, 1)).getpixel((0, 0))   # 평균색
        solid = Image.new("RGB", (8, 8), avg)
        return _save(solid, fmt)

    if method == "blur":
        rgb = img
        le = max(rgb.size)
        if le > blur_cap:                            # 블러 전 다운스케일로 경량화
            rgb = rgb.copy()
            rgb.thumbnail((blur_cap, blur_cap))
            le = max(rgb.size)
        radius = max(2.0, le * blur_ratio)
        blurred = rgb.filter(ImageFilter.GaussianBlur(radius=radius))
        return _save(blurred, fmt)

    raise ValueError(f"알 수 없는 method: {method}")
