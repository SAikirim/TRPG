"""초상화 생성 모듈 (Skia 기반).
map_generator.py에서 분리, Cairo -> Skia 전환."""

import json
import os
import math
import skia

from core.skia_utils import skia_rgba, skia_paint


class PortraitGenerator:
    def __init__(self, base_dir):
        self.base_dir = base_dir

    def generate_portraits(self, game_state, force=False):
        """Generate high-quality Skia portraits for all players. Skip if file already exists."""
        portrait_dir = os.path.join(self.base_dir, "static", "portraits", "pixel")
        os.makedirs(portrait_dir, exist_ok=True)

        class_configs = {
            "전사": {
                "primary": (0.90, 0.22, 0.27),
                "secondary": (0.75, 0.22, 0.17),
                "hair": (0.35, 0.20, 0.10),
                "emblem": "swords",
                "detail": "scar",
            },
            "마법사": {
                "primary": (0.27, 0.48, 0.88),
                "secondary": (0.17, 0.24, 0.62),
                "hair": (0.15, 0.15, 0.20),
                "emblem": "star",
                "detail": "glow",
            },
            "도적": {
                "primary": (0.18, 0.80, 0.44),
                "secondary": (0.15, 0.68, 0.38),
                "hair": (0.30, 0.22, 0.12),
                "emblem": "dagger",
                "detail": "hood",
            },
        }

        SIZE = 200
        for player in game_state.get("players", []):
            filepath = os.path.join(portrait_dir, f"player_{player['id']}.png")
            if not force and os.path.exists(filepath):
                continue

            config = class_configs.get(player["class"], class_configs["전사"])
            surface = skia.Surface(SIZE, SIZE)
            canvas = surface.getCanvas()
            cx, cy = SIZE / 2, SIZE / 2

            # Clip to circle
            clip_path = skia.Path()
            clip_path.addCircle(cx, cy, 95)
            canvas.clipPath(clip_path)

            # Background gradient (radial)
            bg_p = skia.Paint()
            bg_p.setAntiAlias(True)
            bg_p.setShader(skia.GradientShader.MakeRadial(
                center=(cx, cy - 20), radius=100,
                colors=[skia_rgba(0.12, 0.08, 0.20), skia_rgba(0.04, 0.02, 0.08)],
                positions=[10/100, 1.0]))
            canvas.drawRect(skia.Rect(0, 0, SIZE, SIZE), bg_p)

            # --- Head ---
            head_cx, head_cy = cx, 72
            head_rx, head_ry = 38, 44

            # Hair (behind head)
            hr, hg, hb = config["hair"]
            hair_path = skia.Path()
            hair_path.moveTo(head_cx - 42, head_cy - 5)
            hair_path.cubicTo(head_cx - 45, head_cy - 50, head_cx + 45, head_cy - 50, head_cx + 42, head_cy - 5)
            hair_path.cubicTo(head_cx + 45, head_cy + 15, head_cx + 40, head_cy + 30, head_cx + 35, head_cy + 40)
            hair_path.lineTo(head_cx - 35, head_cy + 40)
            hair_path.cubicTo(head_cx - 40, head_cy + 30, head_cx - 45, head_cy + 15, head_cx - 42, head_cy - 5)
            canvas.drawPath(hair_path, skia_paint(hr, hg, hb))

            # Face (ellipse with radial gradient)
            face_p = skia.Paint()
            face_p.setAntiAlias(True)
            face_p.setShader(skia.GradientShader.MakeRadial(
                center=(head_cx - 5, head_cy - 10), radius=45,
                colors=[skia_rgba(0.98, 0.85, 0.72), skia_rgba(0.90, 0.72, 0.55)],
                positions=[5/45, 1.0]))
            canvas.save()
            canvas.translate(head_cx, head_cy)
            canvas.scale(head_rx, head_ry)
            canvas.drawCircle(0, 0, 1, face_p)
            canvas.restore()

            # Eyes
            for eye_x in [head_cx - 14, head_cx + 14]:
                # White
                canvas.save()
                canvas.translate(eye_x, head_cy + 2)
                canvas.scale(8, 5)
                canvas.drawCircle(0, 0, 1, skia_paint(0.95, 0.95, 0.97))
                canvas.restore()
                # Iris
                iris_p = skia.Paint()
                iris_p.setAntiAlias(True)
                iris_p.setShader(skia.GradientShader.MakeRadial(
                    center=(eye_x - 1, head_cy + 1), radius=5,
                    colors=[skia_rgba(0.45, 0.30, 0.15), skia_rgba(0.25, 0.15, 0.05)],
                    positions=[1/5, 1.0]))
                canvas.drawCircle(eye_x, head_cy + 2, 4, iris_p)
                # Pupil
                canvas.drawCircle(eye_x, head_cy + 2, 2, skia_paint(0.05, 0.05, 0.08))
                # Highlight
                canvas.drawCircle(eye_x + 1.5, head_cy + 0.5, 1.2, skia_paint(1, 1, 1, 0.8))

            # Eyebrows
            ebr = config["hair"][0] * 0.7
            ebg = config["hair"][1] * 0.7
            ebb = config["hair"][2] * 0.7
            for bx, direction in [(head_cx - 14, 1), (head_cx + 14, -1)]:
                brow = skia.Path()
                brow.moveTo(bx - 9 * direction, head_cy - 8)
                brow.cubicTo(bx - 5 * direction, head_cy - 12, bx + 5 * direction, head_cy - 12, bx + 9 * direction, head_cy - 9)
                canvas.drawPath(brow, skia_paint(ebr, ebg, ebb,
                    style=skia.Paint.kStroke_Style, stroke_width=2.5))

            # Nose
            nose = skia.Path()
            nose.moveTo(head_cx, head_cy + 5)
            nose.lineTo(head_cx - 3, head_cy + 16)
            nose.cubicTo(head_cx - 2, head_cy + 18, head_cx + 2, head_cy + 18, head_cx + 3, head_cy + 16)
            canvas.drawPath(nose, skia_paint(0.70, 0.50, 0.38, 0.5,
                style=skia.Paint.kStroke_Style, stroke_width=1.5))

            # Mouth
            mouth = skia.Path()
            mouth.moveTo(head_cx - 10, head_cy + 24)
            mouth.cubicTo(head_cx - 5, head_cy + 27, head_cx + 5, head_cy + 27, head_cx + 10, head_cy + 24)
            canvas.drawPath(mouth, skia_paint(0.78, 0.45, 0.40,
                style=skia.Paint.kStroke_Style, stroke_width=1.8))
            # Upper lip
            ulip = skia.Path()
            ulip.moveTo(head_cx - 8, head_cy + 24)
            ulip.cubicTo(head_cx - 3, head_cy + 22, head_cx + 3, head_cy + 22, head_cx + 8, head_cy + 24)
            canvas.drawPath(ulip, skia_paint(0.55, 0.30, 0.25, 0.6,
                style=skia.Paint.kStroke_Style, stroke_width=1))

            # Class-specific face detail
            if config["detail"] == "scar":
                scar = skia.Path()
                scar.moveTo(head_cx + 20, head_cy - 5)
                scar.lineTo(head_cx + 15, head_cy + 15)
                canvas.drawPath(scar, skia_paint(0.65, 0.35, 0.30, 0.6,
                    style=skia.Paint.kStroke_Style, stroke_width=1.5))
            elif config["detail"] == "glow":
                glow_p = skia.Paint()
                glow_p.setAntiAlias(True)
                glow_p.setShader(skia.GradientShader.MakeRadial(
                    center=(head_cx, head_cy - 30), radius=25,
                    colors=[skia_rgba(0.4, 0.6, 1.0, 0.3), skia_rgba(0.2, 0.3, 0.8, 0)],
                    positions=[5/25, 1.0]))
                canvas.drawRect(skia.Rect(0, 0, SIZE, SIZE), glow_p)

            # --- Body/Armor ---
            pr, pg, pb = config["primary"]
            body_p = skia.Paint()
            body_p.setAntiAlias(True)
            body_p.setShader(skia.GradientShader.MakeLinear(
                points=[(cx - 60, 130), (cx + 60, 200)],
                colors=[skia_rgba(pr * 1.1, pg * 1.1, pb * 1.1),
                        skia_rgba(*config["secondary"])]))
            body_path = skia.Path()
            body_path.moveTo(cx - 55, 130)
            body_path.cubicTo(cx - 65, 145, cx - 70, 190, cx - 60, 210)
            body_path.lineTo(cx + 60, 210)
            body_path.cubicTo(cx + 70, 190, cx + 65, 145, cx + 55, 130)
            body_path.close()
            canvas.drawPath(body_path, body_p)

            # Collar
            sr, sg, sb = config["secondary"]
            collar = skia.Path()
            collar.moveTo(cx - 25, 125)
            collar.cubicTo(cx - 15, 140, cx + 15, 140, cx + 25, 125)
            collar.cubicTo(cx + 15, 135, cx - 15, 135, cx - 25, 125)
            canvas.drawPath(collar, skia_paint(sr * 0.8, sg * 0.8, sb * 0.8))

            # Emblem
            if config["emblem"] == "swords":
                sp = skia_paint(0.85, 0.85, 0.80, 0.8, style=skia.Paint.kStroke_Style, stroke_width=2.5)
                canvas.drawLine(cx - 10, 150, cx + 10, 175, sp)
                canvas.drawLine(cx + 10, 150, cx - 10, 175, sp)
                gp = skia_paint(pr, pg, pb, 0.9, style=skia.Paint.kStroke_Style, stroke_width=3)
                canvas.drawLine(cx - 14, 155, cx - 6, 155, gp)
                canvas.drawLine(cx + 6, 155, cx + 14, 155, gp)
            elif config["emblem"] == "star":
                star = skia.Path()
                for i in range(5):
                    angle = -math.pi / 2 + i * 2 * math.pi / 5
                    x = cx + 10 * math.cos(angle)
                    y = 162 + 10 * math.sin(angle)
                    if i == 0:
                        star.moveTo(x, y)
                    else:
                        star.lineTo(x, y)
                    inner_angle = angle + math.pi / 5
                    ix = cx + 4 * math.cos(inner_angle)
                    iy = 162 + 4 * math.sin(inner_angle)
                    star.lineTo(ix, iy)
                star.close()
                canvas.drawPath(star, skia_paint(1, 0.85, 0.0, 0.8))
            elif config["emblem"] == "dagger":
                canvas.drawLine(cx, 148, cx, 178,
                    skia_paint(0.85, 0.85, 0.80, 0.8, style=skia.Paint.kStroke_Style, stroke_width=2))
                canvas.drawLine(cx - 6, 155, cx + 6, 155,
                    skia_paint(0.85, 0.85, 0.80, 0.8, style=skia.Paint.kStroke_Style, stroke_width=3))

            # Hood for rogue
            if config["detail"] == "hood":
                hood = skia.Path()
                hood.moveTo(head_cx - 45, head_cy - 15)
                hood.cubicTo(head_cx - 48, head_cy - 55, head_cx + 48, head_cy - 55, head_cx + 45, head_cy - 15)
                hood.cubicTo(head_cx + 50, head_cy - 5, head_cx + 48, head_cy + 5, head_cx + 43, head_cy + 10)
                hood.lineTo(head_cx - 43, head_cy + 10)
                hood.cubicTo(head_cx - 48, head_cy + 5, head_cx - 50, head_cy - 5, head_cx - 45, head_cy - 15)
                canvas.drawPath(hood, skia_paint(0.12, 0.55, 0.30, 0.35))

            # Vignette — reset clip first
            canvas.restore()
            canvas.save()
            vig_p = skia.Paint()
            vig_p.setAntiAlias(True)
            vig_p.setShader(skia.GradientShader.MakeRadial(
                center=(cx, cy), radius=100,
                colors=[skia_rgba(0, 0, 0, 0), skia_rgba(0, 0, 0, 0.4)],
                positions=[50/100, 1.0]))
            # Draw vignette inside circle only
            vp = skia.Path()
            vp.addCircle(cx, cy, 95)
            canvas.clipPath(vp)
            canvas.drawRect(skia.Rect(0, 0, SIZE, SIZE), vig_p)
            canvas.restore()

            # Border ring (outside clip)
            canvas.drawCircle(cx, cy, 95,
                skia_paint(pr * 0.6, pg * 0.6, pb * 0.6,
                    style=skia.Paint.kStroke_Style, stroke_width=3))

            filepath = os.path.join(portrait_dir, f"player_{player['id']}.png")
            surface.makeImageSnapshot().save(filepath, skia.kPNG)

        return portrait_dir
