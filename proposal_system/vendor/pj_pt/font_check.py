"""
PPTX 폰트 점검 모듈 (로컬 처리)

PPTX가 참조하는 폰트를 모두 추출하고, 로컬에 설치되지 않은 폰트를 식별한다.
누락 폰트는 렌더링 시 대체 폰트로 폴백되어 줄바꿈/레이아웃을 깨뜨리므로
익명화/편집 작업 전에 미리 점검하는 용도.

폰트명은 한글명/영문명을 함께 병기한다:
  - 설치된 폰트: 폰트 파일 name 테이블에서 한/영 이름을 모두 읽어 정확히 병기
  - 누락된 폰트: 파일이 없으므로 자주 쓰는 한글 폰트의 한↔영 대응표로 보완

GUI에서 import 해서 재사용할 수 있도록 순수 함수로 구성:
    from font_check import check_fonts
    report = check_fonts("deck.pptx")
"""
import os
import glob
import functools
from lxml import etree
from pptx import Presentation

# 테마 참조 placeholder (실제 폰트명이 아님)
THEME_PLACEHOLDERS = {
    '+mj-lt', '+mj-ea', '+mj-cs', '+mn-lt', '+mn-ea', '+mn-cs',
}

# 누락(미설치) 폰트용 한↔영 대응표. 파일을 읽을 수 없을 때 보완.
# 고신뢰 매핑만 수록 (key는 정규화된 이름).
KNOWN_ALIASES = {
    '나눔고딕': 'NanumGothic',
    '나눔명조': 'NanumMyeongjo',
    '나눔바른고딕': 'NanumBarunGothic',
    '나눔스퀘어': 'NanumSquare',
    '맑은 고딕': 'Malgun Gothic',
    '굴림': 'Gulim', '굴림체': 'GulimChe',
    '돋움': 'Dotum', '돋움체': 'DotumChe',
    '바탕': 'Batang', '바탕체': 'BatangChe',
    '궁서': 'Gungsuh', '궁서체': 'GungsuhChe',
    '한컴바탕': 'HCR Batang', '한컴돋움': 'HCR Dotum',
    '함초롬바탕': 'HCR Batang', '함초롬돋움': 'HCR Dotum',
    '조선일보명조': 'Chosunilbo_myungjo',
    '산돌고딕': 'Sandoll Gothic',
    '윤고딕': 'Yoon Gothic', '윤명조': 'Yoon Myeongjo',
}
# 역방향(영문 -> 한글)도 자동 구성
_KNOWN_ALIASES_REV = {}
for _k, _v in KNOWN_ALIASES.items():
    _KNOWN_ALIASES_REV.setdefault(_v.strip().lower(), _k)


def _normalize(name):
    return name.strip().lower()


def _has_hangul(s):
    for ch in s:
        o = ord(ch)
        if 0xAC00 <= o <= 0xD7A3 or 0x1100 <= o <= 0x11FF or 0x3130 <= o <= 0x318F:
            return True
    return False


def _pair_names(names):
    """이름 집합을 (한글명, 영문명) 으로 분리. 없으면 빈 문자열.

    같은 분류 안에서는 가장 짧은(대표) 이름을 고른다.
    """
    korean = [n for n in names if _has_hangul(n)]
    latin = [n for n in names if not _has_hangul(n)]
    ko = min(korean, key=len) if korean else ''
    en = min(latin, key=len) if latin else ''
    return ko, en


@functools.lru_cache(maxsize=1)
def _load_installed():
    """설치된 폰트 파일을 읽어 패밀리 그룹을 구성.

    반환:
      norm_set : 정규화된 모든 패밀리명 set (설치 여부 판정용)
      groups   : [ set(원본 패밀리명들) ]  — 한 파일/패밀리의 한·영 이름이 한 그룹
    """
    from fontTools.ttLib import TTFont, TTCollection

    norm_set = set()
    groups = []
    font_dirs = [
        os.path.join(os.environ.get('WINDIR', r'<개발 원본 전용 경로>'), 'Fonts'),
        os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Microsoft', 'Windows', 'Fonts'),
    ]
    files = []
    for d in font_dirs:
        if d and os.path.isdir(d):
            for ext in ('*.ttf', '*.otf', '*.ttc'):
                files += glob.glob(os.path.join(d, ext))

    for path in files:
        try:
            if path.lower().endswith('.ttc'):
                fonts = TTCollection(path, lazy=True).fonts
            else:
                fonts = [TTFont(path, lazy=True, fontNumber=0)]
            for f in fonts:
                try:
                    recs = f['name'].names
                except Exception:
                    continue
                fam = set()
                for rec in recs:
                    if rec.nameID in (1, 16):  # Family / Typographic Family (모든 언어)
                        try:
                            s = rec.toUnicode()
                        except Exception:
                            continue
                        if s and s.strip():
                            fam.add(s.strip())
                if fam:
                    groups.append(fam)
                    for n in fam:
                        norm_set.add(_normalize(n))
        except Exception:
            continue
    return norm_set, groups


def get_installed_font_families():
    """정규화된 설치 폰트 패밀리명 set (하위호환용)."""
    return _load_installed()[0]


def _resolve_names(used_name, installed_norm, groups):
    """주어진 폰트명에 대해 (한글명, 영문명, installed) 산출.

    설치된 경우: 같은 그룹의 모든 이름에서 한/영 병기.
    미설치인 경우: 원본 + 큐레이션 대응표로 보완.
    """
    norm = _normalize(used_name)
    installed = norm in installed_norm

    if installed:
        # used_name이 속한 그룹 찾기
        for g in groups:
            if norm in {_normalize(n) for n in g}:
                ko, en = _pair_names(g)
                return ko, en, True
        # 그룹은 못 찾았지만 설치로 판정된 경우(이론상 드묾)
        if _has_hangul(used_name):
            return used_name, '', True
        return '', used_name, True

    # 미설치: 원본 + 대응표
    if _has_hangul(used_name):
        ko = used_name
        en = KNOWN_ALIASES.get(norm, '')
    else:
        en = used_name
        ko = _KNOWN_ALIASES_REV.get(norm, '')
    return ko, en, False


def _display(ko, en, fallback):
    """한글명/영문명 병기 표시 문자열."""
    if ko and en:
        return f"{ko} ({en})"
    return ko or en or fallback


def extract_used_fonts(pptx_path=None, prs=None):
    """PPTX의 모든 파트에서 typeface 속성을 수집.

    pptx_path 또는 이미 로드한 prs(Presentation) 중 하나를 받는다.
    prs를 주면 파일을 다시 파싱하지 않는다(단일 로드 재사용).

    반환: { 원본_폰트명: {'in_content': bool, 'parts': set([...])} }
      - in_content: 슬라이드 본문(slide#.xml)에서 사용 → 레이아웃에 직접 영향(중요)
    """
    if prs is None:
        prs = Presentation(pptx_path)
    pkg = prs.part.package

    used = {}
    for part in pkg.iter_parts():
        pn = str(part.partname)
        if not pn.endswith('.xml'):
            continue
        try:
            root = etree.fromstring(part.blob)
        except Exception:
            continue

        is_content = '/slides/slide' in pn
        for el in root.iter():
            for attr, val in el.attrib.items():
                if not attr.endswith('typeface'):
                    continue
                if not val or val in THEME_PLACEHOLDERS:
                    continue
                entry = used.setdefault(val, {'in_content': False, 'parts': set()})
                entry['parts'].add(pn)
                if is_content:
                    entry['in_content'] = True
    return used


def check_fonts(pptx_path=None, prs=None):
    """폰트 점검 종합 리포트.

    pptx_path 또는 이미 로드한 prs 중 하나를 받는다(prs 우선, 재파싱 방지).

    반환 dict:
      {
        'all': [ {raw, korean, english, display, installed, in_content, parts} ... ],
        'missing':        [display ...]   설치 안 된 모든 폰트,
        'missing_content':[display ...]   누락 + 본문 사용(레이아웃 직접 영향, 가장 중요),
        'installed':      [display ...],
        'installed_families_count': int,
      }
    """
    installed_norm, groups = _load_installed()
    used = extract_used_fonts(pptx_path, prs=prs)

    rows = []
    missing, missing_content, installed_list = [], [], []

    for raw in sorted(used.keys(), key=lambda s: s.lower()):
        info = used[raw]
        ko, en, is_installed = _resolve_names(raw, installed_norm, groups)
        disp = _display(ko, en, raw)
        row = {
            'raw': raw,
            'korean': ko,
            'english': en,
            'display': disp,
            'installed': is_installed,
            'in_content': info['in_content'],
            'parts': sorted(info['parts']),
        }
        rows.append(row)
        if is_installed:
            installed_list.append(disp)
        else:
            missing.append(disp)
            if info['in_content']:
                missing_content.append(disp)

    return {
        'all': rows,
        'missing': missing,
        'missing_content': missing_content,
        'installed': installed_list,
        'installed_families_count': len(installed_norm),
    }


def format_report(report):
    """check_fonts() 결과를 사람이 읽기 좋은 문자열로 (한/영 병기)."""
    lines = []
    total = len(report['all'])
    n_missing = len(report['missing'])
    n_crit = len(report['missing_content'])

    lines.append(f"참조 폰트 {total}종 | 설치 {total - n_missing} | 누락 {n_missing} "
                 f"(이 중 본문 사용 {n_crit})")
    lines.append(f"로컬 설치 폰트 패밀리: {report['installed_families_count']}종")
    lines.append("")

    crit_rows = [r for r in report['all'] if not r['installed'] and r['in_content']]
    if crit_rows:
        lines.append("■ 누락 + 본문 사용 (레이아웃 깨짐 위험 — 설치 권장):")
        for r in crit_rows:
            note = "" if (r['korean'] and r['english']) else "   (대응 영문/한글명 미확인)"
            lines.append(f"   ✗ {r['display']}{note}")
        lines.append("")

    other = [r for r in report['all'] if not r['installed'] and not r['in_content']]
    if other:
        lines.append("□ 누락 (테마/마스터 등 비본문 — 영향 낮음):")
        for r in other:
            lines.append(f"   - {r['display']}")
        lines.append("")

    lines.append("전체 폰트 사용 현황 (한글명 / 영문명):")
    for r in report['all']:
        mark = "O" if r['installed'] else "X"
        tag = " [본문]" if r['in_content'] else ""
        lines.append(f"   [{mark}] {r['display']}{tag}")

    return "\n".join(lines)


if __name__ == '__main__':
    import sys
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    path = sys.argv[1] if len(sys.argv) > 1 else \
        r"<개발 원본 전용 경로> 기획홍보 제안서(PT본).pptx"
    print(f"점검 대상: {path}\n")
    print(format_report(check_fonts(path)))
