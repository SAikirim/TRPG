"""Skia 공통 유틸리티 — world_map, scene_renderer, portrait_generator에서 공유."""
import skia


def skia_rgba(r, g, b, a=1.0):
    """Skia Color4f -> Color (0~1 범위 RGBA)"""
    return skia.Color4f(r, g, b, a).toColor()


def skia_paint(r=0, g=0, b=0, a=1.0, style=None, stroke_width=None, anti_alias=True):
    """편의 함수: Skia Paint 생성"""
    p = skia.Paint()
    p.setAntiAlias(anti_alias)
    p.setColor(skia_rgba(r, g, b, a))
    if style is not None:
        p.setStyle(style)
    else:
        p.setStyle(skia.Paint.kFill_Style)
    if stroke_width is not None:
        p.setStrokeWidth(stroke_width)
    return p


def pil_to_skia_image(pil_img):
    """PIL Image → Skia Image 변환 (RGBA→BGRA 채널 스왑)"""
    import numpy
    arr = numpy.array(pil_img.convert("RGBA"))
    arr = arr[:, :, [2, 1, 0, 3]].copy()  # RGBA → BGRA
    return skia.Image.fromarray(arr)
