# checker.py — OGQ 공식 스펙 기준으로 스티커 이미지를 검사하는 로직
# 공식 가이드 출처: https://creators.ogq.me/guides/contents/sticker
from PIL import Image  # Pillow: 파이썬에서 이미지를 다루는 대표 라이브러리
import io

# OGQ 공식 규격 (가로px, 세로px)
SPECS = {
    "메인 이미지": (240, 240),   # 1개 필요
    "스티커 이미지": (740, 640),  # 24개 필요
    "탭 이미지": (96, 74),       # 1개 필요
}

MAX_BYTES = 1 * 1024 * 1024  # 1MB (공식 기준: 각 이미지 1MB 이하)


def classify_type(width, height):
    """이미지 크기를 보고 어떤 종류(메인/스티커/탭)인지 알아낸다.
    규격에 안 맞으면 None을 돌려준다."""
    for name, (w, h) in SPECS.items():
        if width == w and height == h:
            return name
    return None


def check_transparency(img):
    """배경이 투명인지 검사한다.
    방법: 알파 채널(투명도 정보)이 있는지 + 네 모서리 픽셀이 투명한지 확인."""
    if img.mode != "RGBA":
        return False, "알파 채널(투명도 정보)이 없는 이미지예요."
    w, h = img.size
    corners = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    # 모서리 픽셀의 알파값이 0이면 완전 투명
    opaque_corners = sum(1 for c in corners if img.getpixel(c)[3] > 10)
    if opaque_corners >= 3:
        return False, "모서리가 불투명해요. 배경이 투명이 아닐 가능성이 높아요."
    return True, "배경이 투명으로 보여요."


def check_margin(img):
    """여백이 과한지 검사한다.
    방법: 실제 그림이 있는 영역(알파값 존재 영역)이 전체 캔버스에서
    차지하는 비율을 계산한다. 공식 가이드: '여백이 가급적 없도록 최대한 크게'."""
    if img.mode != "RGBA":
        return None, "투명도 정보가 없어 여백을 측정할 수 없어요."
    bbox = img.getchannel("A").getbbox()  # 그림이 존재하는 최소 사각형
    if bbox is None:
        return None, "이미지가 완전히 비어 있어요."
    content_w = bbox[2] - bbox[0]
    content_h = bbox[3] - bbox[1]
    ratio = (content_w * content_h) / (img.size[0] * img.size[1])
    return ratio, f"그림이 캔버스의 {ratio:.0%}를 차지해요."


def check_image(file_bytes, filename, expected_type=None):
    """이미지 1장을 검사한다. expected_type이 지정되면 사용자가 지정한 종류의 규격과 비교한다.
    결과 형식: (등급, 검사항목, 설명) — 등급은 pass / warn / fail"""
    results = []
    img = Image.open(io.BytesIO(file_bytes))
    w, h = img.size

    if expected_type not in SPECS:
        expected_type = None

    # 검사 1: 파일 형식 (스티커는 투명 배경이 필요하므로 PNG가 표준)
    if img.format == "PNG":
        results.append(("pass", "파일 형식", "PNG 형식이에요."))
    else:
        results.append(("fail", "파일 형식",
                        f"{img.format} 형식이에요. 투명 배경을 지원하는 PNG로 저장해주세요. "
                        "(확장자만 바꾸면 심사에서 거절돼요 — 원본부터 PNG로 내보내야 해요)"))

    # 검사 2: 크기 규격
    detected_type = classify_type(w, h)
    if expected_type:
        ew, eh = SPECS[expected_type]
        if (w, h) == (ew, eh):
            img_type = expected_type
            results.append(("pass", "크기 규격", f"{w}x{h}px — 지정한 '{expected_type}' 규격에 맞아요."))
        else:
            img_type = None
            detected_note = f" 현재 크기만 보면 '{detected_type}' 규격으로 보입니다." if detected_type else " 현재 크기로는 다른 OGQ 규격과도 일치하지 않습니다."
            results.append(("fail", "크기 규격",
                            f"'{expected_type}'로 지정했지만 현재 {w}x{h}px입니다. "
                            f"'{expected_type}' 규격은 {ew}x{eh}px입니다.{detected_note}"))
    elif detected_type:
        img_type = detected_type
        results.append(("pass", "크기 규격", f"{w}x{h}px — '{img_type}' 규격에 맞아요."))
    else:
        img_type = None
        spec_text = ", ".join(f"{n} {spec[0]}x{spec[1]}" for n, spec in SPECS.items())
        results.append(("fail", "크기 규격",
                        f"{w}x{h}px — OGQ 규격({spec_text})에 맞지 않아요."))

    # 검사 3: 용량
    size = len(file_bytes)
    if size <= MAX_BYTES:
        results.append(("pass", "용량", f"{size / 1024:.0f}KB — 1MB 이하 통과."))
    else:
        results.append(("fail", "용량", f"{size / 1024 / 1024:.2f}MB — 1MB를 넘어요. 압축이 필요해요."))

    # 검사 4: 컬러 모드 (공식 기준: RGB. RGBA는 RGB+투명도이므로 통과)
    if img.mode in ("RGB", "RGBA"):
        results.append(("pass", "컬러 모드", f"{img.mode} — RGB 계열 통과."))
    else:
        results.append(("fail", "컬러 모드",
                        f"{img.mode} 모드예요. RGB로 변환해서 저장해주세요."))

    # 검사 5: 투명 배경
    ok, msg = check_transparency(img)
    results.append(("pass" if ok else "fail", "투명 배경", msg))

    # 검사 6: 여백 (fail은 아니고 개선 제안 수준)
    ratio, msg = check_margin(img)
    if ratio is None:
        results.append(("warn", "여백", msg))
    elif ratio >= 0.6:
        results.append(("pass", "여백", msg + " 캔버스를 잘 활용하고 있어요."))
    else:
        results.append(("warn", "여백",
                        msg + " 공식 가이드는 '여백 없이 최대한 크게'를 권장해요."))

    return img_type, results
