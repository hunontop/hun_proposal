# -*- coding: utf-8 -*-
"""
HWP 5.0 (구형 .hwp / OLE) 텍스트 추출기 — 인라인 제어문자 정확 처리

HWP 본문(PARA_TEXT, tag=67)은 WCHAR 스트림에 본문 글자와 제어문자가 섞여 있다.
제어문자 종류별로 차지하는 WCHAR 수가 달라, 이를 정확히 건너뛰지 않으면
제어 레코드의 바이너리가 한자처럼 깨져 본문에 새어든다.

규칙 (한글 파일 형식 5.0, hwp.js/pyhwp 공통):
  - char control   (1 WCHAR): 0, 10(줄바꿈), 13(문단끝)
  - inline control (8 WCHAR): 4,5,6,7,8,9,19,20
  - extend control (8 WCHAR): 1,2,3,11,12,14,15,16,17,18,21,22,23
  - 그 외(24~31): 무시(1 WCHAR)
"""
import io
import zlib
import struct
import zipfile
import xml.etree.ElementTree as ET
import olefile

CTRL_CHAR = {0, 10, 13}
CTRL_8WCHAR = {1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23}


def _decode_para_text(body: bytes) -> str:
    """PARA_TEXT 레코드 바이트 → 본문 문자열 (제어문자 정확 스킵)"""
    out = []
    i, n = 0, len(body)
    while i + 2 <= n:
        code = struct.unpack_from("<H", body, i)[0]
        if code in CTRL_CHAR:
            if code in (10, 13):
                out.append("\n")
            i += 2
        elif code in CTRL_8WCHAR:
            if code == 9:        # 탭
                out.append("\t")
            i += 16              # 8 WCHAR = 16 bytes
        elif code < 32:
            i += 2               # 기타 제어(무시)
        else:
            out.append(chr(code))
            i += 2
    return "".join(out)


def extract_text(path: str) -> str:
    """HWP 파일 → 전체 본문 텍스트 (섹션 순서 보존)"""
    ole = olefile.OleFileIO(path)
    try:
        header = ole.openstream("FileHeader").read()
        compressed = bool(header[36] & 1)

        # BodyText/Section0,1,2... 를 번호 순으로
        sections = []
        for entry in ole.listdir():
            if len(entry) == 2 and entry[0] == "BodyText" and entry[1].startswith("Section"):
                try:
                    num = int(entry[1].replace("Section", ""))
                except ValueError:
                    num = 0
                sections.append((num, entry))
        sections.sort()

        parts = []
        for _, entry in sections:
            data = ole.openstream(entry).read()
            if compressed:
                data = zlib.decompress(data, -15)
            parts.append(_parse_section(data))
        return "\n".join(parts)
    finally:
        ole.close()


def _parse_section(data: bytes) -> str:
    """섹션 레코드 스트림에서 PARA_TEXT(67)만 모아 본문 구성"""
    texts = []
    i, n = 0, len(data)
    while i + 4 <= n:
        hdr = struct.unpack_from("<I", data, i)[0]
        tag_id = hdr & 0x3FF
        size = (hdr >> 20) & 0xFFF
        i += 4
        if size == 0xFFF:
            size = struct.unpack_from("<I", data, i)[0]
            i += 4
        body = data[i:i + size]
        i += size
        if tag_id == 67:  # HWPTAG_PARA_TEXT
            texts.append(_decode_para_text(body))
    return "\n".join(texts)


# ──────────────────────────────────────────────────────────────
# HWPX (신형, zip+xml) 파서
# ──────────────────────────────────────────────────────────────
def extract_text_hwpx(path: str) -> str:
    """HWPX 파일 → 본문 텍스트.

    구조: Contents/section0.xml, section1.xml ... 에 본문이 XML로.
    본문 글자는 <hp:t> 요소, 문단은 <hp:p>, 표 셀은 <hp:tc>(내부에 다시 hp:p/hp:t).
    네임스페이스는 버전마다 달라 localname(tag의 '}' 뒤)으로 매칭한다.
    """
    z = zipfile.ZipFile(path)
    try:
        secs = sorted(
            n for n in z.namelist()
            if n.startswith("Contents/section") and n.endswith(".xml")
        )
        out = []
        for sec in secs:
            data = z.read(sec)
            for event, elem in ET.iterparse(io.BytesIO(data), events=("end",)):
                tag = elem.tag.rsplit("}", 1)[-1]
                if tag == "t":                      # 글자 런
                    out.append("".join(elem.itertext()))
                elif tag == "tc":                   # 표 셀 경계 → 탭
                    out.append("\t")
                elif tag == "p":                    # 문단 경계 → 줄바꿈
                    out.append("\n")
        return "".join(out)
    finally:
        z.close()


def extract_any(path: str) -> str:
    """확장자에 따라 hwp/hwpx 자동 분기."""
    return extract_text_hwpx(path) if path.lower().endswith(".hwpx") else extract_text(path)


if __name__ == "__main__":
    import sys, os
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(__file__), "data", "R26BK01573755-000", "제안요청서.hwp")
    txt = extract_any(path)
    print(f"[추출 길이] {len(txt):,}자\n")
    # 배점/평가 섹션 찾아 출력
    idx = txt.find("평가 및 선정")
    if idx < 0:
        idx = txt.find("평가")
    print("[평가/배점 섹션 발췌]")
    print(txt[idx:idx + 1500] if idx >= 0 else txt[:1500])
