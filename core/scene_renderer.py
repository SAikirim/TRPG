"""씬 배경 및 씬 엘리먼트 생성 모듈 (Skia 기반).
map_generator.py에서 분리, Cairo -> Skia 전환."""

import os
import math
import hashlib
import skia

from core.skia_utils import skia_rgba, skia_paint


def _draw_linear_gradient_rect(canvas, x, y, w, h, pt0, pt1, stops):
    """Skia linear gradient on a rect.
    stops: list of (position, (r, g, b[, a]))
    """
    colors = []
    positions = []
    for pos, col in stops:
        if len(col) == 3:
            colors.append(skia_rgba(*col))
        else:
            colors.append(skia_rgba(*col))
        positions.append(pos)
    p = skia.Paint()
    p.setAntiAlias(True)
    p.setShader(skia.GradientShader.MakeLinear(
        points=[pt0, pt1], colors=colors, positions=positions))
    canvas.drawRect(skia.Rect(x, y, x + w, y + h), p)


def _draw_radial_gradient_circle(canvas, cx, cy, radius, stops):
    """Skia radial gradient circle.
    stops: list of (position, (r, g, b, a))
    """
    colors = []
    positions = []
    for pos, col in stops:
        colors.append(skia_rgba(*col))
        positions.append(pos)
    p = skia.Paint()
    p.setAntiAlias(True)
    p.setShader(skia.GradientShader.MakeRadial(
        center=(cx, cy), radius=radius, colors=colors, positions=positions))
    canvas.drawCircle(cx, cy, radius, p)


class SceneRenderer:
    def __init__(self, base_dir):
        self.base_dir = base_dir

    def generate_pixel_backgrounds(self):
        """Generate high-quality Skia backgrounds for each scene type."""
        bg_dir = os.path.join(self.base_dir, "static", "illustrations", "pixel")
        os.makedirs(bg_dir, exist_ok=True)

        W, H = 768, 512

        # --- Forest ---
        self._render_and_save(W, H, self._draw_forest_scene, os.path.join(bg_dir, "forest.png"))

        # --- Dungeon ---
        self._render_and_save(W, H, self._draw_dungeon_scene, os.path.join(bg_dir, "dungeon.png"))

        # --- Treasure ---
        self._render_and_save(W, H, self._draw_treasure_scene, os.path.join(bg_dir, "treasure.png"))

        return bg_dir

    def _render_and_save(self, W, H, draw_fn, filepath):
        surface = skia.Surface(W, H)
        canvas = surface.getCanvas()
        draw_fn(canvas, W, H)
        surface.makeImageSnapshot().save(filepath, skia.kPNG)

    def generate_scene_background(self, scene_name):
        """Generate a Skia background dynamically based on scene name."""
        W, H = 896, 512
        surface = skia.Surface(W, H)
        canvas = surface.getCanvas()

        name_lower = scene_name.lower()

        if any(k in name_lower for k in ["forest", "숲", "나무", "woods"]):
            self._draw_forest_scene(canvas, W, H)
        elif any(k in name_lower for k in ["dungeon", "던전", "동굴", "cave", "underground"]):
            self._draw_dungeon_scene(canvas, W, H)
        elif any(k in name_lower for k in ["treasure", "보물", "gold", "황금"]):
            self._draw_treasure_scene(canvas, W, H)
        elif any(k in name_lower for k in ["village", "마을", "town", "home", "집", "cottage"]):
            self._draw_village_scene(canvas, W, H)
        elif any(k in name_lower for k in ["night", "밤", "evening", "석양", "sunset", "dusk"]):
            self._draw_night_scene(canvas, W, H)
        elif any(k in name_lower for k in ["market", "시장", "shop", "상점"]):
            self._draw_market_scene(canvas, W, H)
        elif any(k in name_lower for k in ["camp", "야영", "rest", "쉼터", "crossroads", "bonfire"]):
            self._draw_camp_scene(canvas, W, H)
        elif any(k in name_lower for k in ["inn", "여관", "tavern", "chimney", "숙소"]):
            self._draw_inn_scene(canvas, W, H)
        elif any(k in name_lower for k in ["city", "도시", "karendel", "gate", "성문", "성벽"]):
            self._draw_city_scene(canvas, W, H)
        elif any(k in name_lower for k in ["road", "길", "path", "여행", "travel", "trade"]):
            self._draw_road_scene(canvas, W, H)
        else:
            self._draw_default_scene(canvas, W, H, scene_name)

        out_dir = os.path.join(self.base_dir, "static", "illustrations", "pixel")
        os.makedirs(out_dir, exist_ok=True)
        safe_name = scene_name.replace(" ", "_").lower()
        filepath = os.path.join(out_dir, f"{safe_name}.png")
        surface.makeImageSnapshot().save(filepath, skia.kPNG)
        return filepath

    # ===== Scene drawing methods (Cairo -> Skia) =====

    def _draw_forest_scene(self, canvas, W, H):
        """Draw a forest scene."""
        # Sky gradient
        _draw_linear_gradient_rect(canvas, 0, 0, W, 320,
            (0, 0), (0, 320),
            [(0, (0.05, 0.05, 0.18)), (0.6, (0.10, 0.15, 0.30)), (1, (0.20, 0.30, 0.20))])

        # Ground gradient
        _draw_linear_gradient_rect(canvas, 0, 300, W, H - 300,
            (0, 300), (0, H),
            [(0, (0.18, 0.38, 0.12)), (0.4, (0.14, 0.30, 0.08)), (1, (0.08, 0.18, 0.04))])

        # Ground texture (grass tufts)
        for gx in range(0, W, 18):
            for gy in range(310, H, 25):
                path = skia.Path()
                path.moveTo(gx, gy)
                path.cubicTo(gx - 3, gy - 10, gx + 2, gy - 12, gx + 1, gy - 15)
                canvas.drawPath(path, skia_paint(0.22, 0.50, 0.15, 0.3,
                    style=skia.Paint.kStroke_Style, stroke_width=1.5))

        x_scale = W / 768.0
        # Trees (back layer)
        for tx, scale in [(int(60 * x_scale), 0.7), (int(180 * x_scale), 0.8),
                          (int(350 * x_scale), 0.65), (int(520 * x_scale), 0.75),
                          (int(680 * x_scale), 0.7), (int(800 * x_scale), 0.72)]:
            self._draw_tree(canvas, tx, scale, 300, back=True)

        # Trees (front layer)
        for tx, scale in [(int(130 * x_scale), 1.1), (int(420 * x_scale), 1.2),
                          (int(600 * x_scale), 1.0), (int(780 * x_scale), 1.05)]:
            self._draw_tree(canvas, tx, scale, 300, back=False)

        # Fog
        p = skia.Paint()
        p.setAntiAlias(True)
        p.setShader(skia.GradientShader.MakeLinear(
            points=[(0, 250), (0, 350)],
            colors=[skia_rgba(0.3, 0.4, 0.3, 0), skia_rgba(0.3, 0.4, 0.3, 0.15), skia_rgba(0.3, 0.4, 0.3, 0)],
            positions=[0, 0.5, 1.0]))
        canvas.drawRect(skia.Rect(0, 250, W, 350), p)

        # Light rays
        for rx in [int(200 * W / 768), int(400 * W / 768), int(580 * W / 768), int(750 * W / 768)]:
            p = skia.Paint()
            p.setAntiAlias(True)
            p.setShader(skia.GradientShader.MakeLinear(
                points=[(rx, 0), (rx + 30, 320)],
                colors=[skia_rgba(0.9, 0.9, 0.6, 0.08), skia_rgba(0.9, 0.9, 0.6, 0)]))
            path = skia.Path()
            path.moveTo(rx, 0); path.lineTo(rx + 50, 0)
            path.lineTo(rx + 80, 320); path.lineTo(rx - 10, 320)
            path.close()
            canvas.drawPath(path, p)

    def _draw_tree(self, canvas, tx, scale, ground_y, back=True):
        if back:
            tw = 12 * scale
            th = 100 * scale
            trunk_colors = [(0, (0.25, 0.14, 0.06)), (0.5, (0.35, 0.20, 0.08)), (1, (0.20, 0.12, 0.05))]
            canopy_layers = 3
            canopy_base_r = 50
            canopy_step = 8
            canopy_offset = 15
            leaf_colors = [(0, (0.20, 0.55, 0.18)), (0.6, (0.15, 0.42, 0.12)), (1, (0.10, 0.30, 0.08))]
            y_scale = 0.75
        else:
            tw = 16 * scale
            th = 140 * scale
            trunk_colors = [(0, (0.30, 0.16, 0.06)), (0.5, (0.42, 0.24, 0.10)), (1, (0.22, 0.13, 0.05))]
            canopy_layers = 4
            canopy_base_r = 65
            canopy_step = 10
            canopy_offset = 20
            leaf_colors = [(0, (0.25, 0.62, 0.22)), (0.5, (0.18, 0.48, 0.14)), (1, (0.10, 0.32, 0.08))]
            y_scale = 0.7

        # Trunk
        colors = [skia_rgba(*c) for _, c in trunk_colors]
        positions = [pos for pos, _ in trunk_colors]
        p = skia.Paint()
        p.setAntiAlias(True)
        p.setShader(skia.GradientShader.MakeLinear(
            points=[(tx - tw, 0), (tx + tw, 0)], colors=colors, positions=positions))
        extra = 10 if back else 20
        canvas.drawRect(skia.Rect(tx - tw / 2, ground_y - th, tx + tw / 2, ground_y + extra), p)

        # Canopy
        for layer in range(canopy_layers):
            ly = ground_y - th - (30 if not back else 20) + layer * canopy_offset
            lr = (canopy_base_r - layer * canopy_step) * scale
            colors_c = [skia_rgba(*c) for _, c in leaf_colors]
            positions_c = [pos for pos, _ in leaf_colors]
            p = skia.Paint()
            p.setAntiAlias(True)
            inner_r = lr * (0.2 if back else 0.15)
            p.setShader(skia.GradientShader.MakeRadial(
                center=(tx, ly), radius=lr, colors=colors_c, positions=positions_c))
            canvas.save()
            canvas.translate(tx, ly)
            canvas.scale(1, y_scale)
            canvas.drawCircle(0, 0, lr, p)
            canvas.restore()

    def _draw_dungeon_scene(self, canvas, W, H):
        x_scale = W / 768.0

        # Wall gradient
        _draw_linear_gradient_rect(canvas, 0, 0, W, H,
            (0, 0), (0, H),
            [(0, (0.04, 0.04, 0.06)), (0.3, (0.10, 0.10, 0.12)),
             (0.6, (0.14, 0.13, 0.14)), (1, (0.08, 0.07, 0.08))])

        # Stone floor
        _draw_linear_gradient_rect(canvas, 0, 320, W, H - 320,
            (0, 320), (0, H),
            [(0, (0.18, 0.17, 0.16)), (1, (0.10, 0.09, 0.09))])

        # Floor tiles
        for y in range(320, H, 30):
            offset = 20 if ((y - 320) // 30) % 2 else 0
            for x in range(-20 + offset, W + 20, 55):
                canvas.drawRect(skia.Rect(x, y, x + 50, y + 26),
                    skia_paint(0.22, 0.21, 0.20, 0.5, style=skia.Paint.kStroke_Style, stroke_width=1))

        # Stone pillars
        pillar_positions = [int(p * x_scale) for p in [120, 380, 640]]
        if W > 800:
            pillar_positions.append(int(820 * x_scale))
        for px in pillar_positions:
            # Pillar body
            colors = [skia_rgba(0.20, 0.19, 0.18), skia_rgba(0.32, 0.30, 0.28),
                      skia_rgba(0.28, 0.27, 0.25), skia_rgba(0.16, 0.15, 0.14)]
            p = skia.Paint()
            p.setAntiAlias(True)
            p.setShader(skia.GradientShader.MakeLinear(
                points=[(px - 5, 0), (px + 50, 0)], colors=colors,
                positions=[0, 0.4, 0.7, 1.0]))
            canvas.drawRect(skia.Rect(px, 80, px + 45, 320), p)
            # Cap
            cap_colors = [skia_rgba(0.24, 0.23, 0.22), skia_rgba(0.36, 0.34, 0.32), skia_rgba(0.20, 0.19, 0.18)]
            cp = skia.Paint()
            cp.setAntiAlias(True)
            cp.setShader(skia.GradientShader.MakeLinear(
                points=[(px - 8, 75), (px + 55, 75)], colors=cap_colors, positions=[0, 0.5, 1.0]))
            canvas.drawRect(skia.Rect(px - 8, 72, px + 53, 90), cp)
            canvas.drawRect(skia.Rect(px - 5, 310, px + 50, 325), cp)
            # Stone lines
            for sy in range(100, 310, 35):
                canvas.drawLine(px, sy, px + 45, sy,
                    skia_paint(0.12, 0.11, 0.10, 0.4, style=skia.Paint.kStroke_Style, stroke_width=1))

        # Torches
        torch_positions = [int(p * x_scale) for p in [250, 510]]
        if W > 800:
            torch_positions.append(int(730 * x_scale))
        for tx in torch_positions:
            self._draw_torch(canvas, tx, W, H)

        # Vignette
        _draw_radial_gradient_circle(canvas, W / 2, H / 2, 450,
            [(100 / 450, (0, 0, 0, 0)), (1, (0, 0, 0, 0.6))])

    def _draw_torch(self, canvas, tx, W, H):
        # Handle
        canvas.drawRect(skia.Rect(tx - 3, 160, tx + 5, 205), skia_paint(0.35, 0.18, 0.06))
        # Flame glow
        _draw_radial_gradient_circle(canvas, tx + 1, 148, 80,
            [(5/80, (1.0, 0.65, 0.1, 0.25)), (0.4, (1.0, 0.40, 0.0, 0.10)), (1, (0.8, 0.2, 0.0, 0))])
        # Outer flame
        path = skia.Path()
        path.moveTo(tx - 8, 160)
        path.cubicTo(tx - 10, 145, tx + 1, 125, tx + 1, 118)
        path.cubicTo(tx + 1, 125, tx + 12, 145, tx + 10, 160)
        path.close()
        canvas.drawPath(path, skia_paint(1.0, 0.45, 0.0, 0.9))
        # Inner flame
        path2 = skia.Path()
        path2.moveTo(tx - 4, 160)
        path2.cubicTo(tx - 5, 148, tx + 1, 132, tx + 1, 128)
        path2.cubicTo(tx + 1, 132, tx + 7, 148, tx + 6, 160)
        path2.close()
        canvas.drawPath(path2, skia_paint(1.0, 0.75, 0.0, 0.9))
        # Bright core
        path3 = skia.Path()
        path3.moveTo(tx - 1, 158)
        path3.cubicTo(tx - 1, 150, tx + 1, 140, tx + 1, 136)
        path3.cubicTo(tx + 1, 140, tx + 3, 150, tx + 3, 158)
        path3.close()
        canvas.drawPath(path3, skia_paint(1.0, 0.95, 0.6, 0.8))

    def _draw_treasure_scene(self, canvas, W, H):
        # Background
        _draw_linear_gradient_rect(canvas, 0, 0, W, H,
            (0, 0), (0, H),
            [(0, (0.12, 0.08, 0.04)), (0.4, (0.18, 0.12, 0.06)), (1, (0.10, 0.06, 0.03))])

        # Stone floor
        _draw_linear_gradient_rect(canvas, 0, 340, W, H - 340,
            (0, 340), (0, H),
            [(0, (0.32, 0.26, 0.18)), (1, (0.20, 0.15, 0.10))])

        # Floor tiles
        for y in range(340, H, 28):
            offset = 15 if ((y - 340) // 28) % 2 else 0
            for x in range(-15 + offset, W + 15, 50):
                canvas.drawRect(skia.Rect(x, y, x + 46, y + 24),
                    skia_paint(0.38, 0.30, 0.22, 0.4, style=skia.Paint.kStroke_Style, stroke_width=1))

        # Treasure chest
        chest_x, chest_y = W / 2 - 70, 290
        chest_w, chest_h = 140, 80

        # Chest body
        _draw_linear_gradient_rect(canvas, chest_x, chest_y, chest_w, chest_h,
            (chest_x, chest_y), (chest_x, chest_y + chest_h),
            [(0, (0.58, 0.42, 0.12)), (0.5, (0.50, 0.36, 0.10)), (1, (0.38, 0.26, 0.08))])

        # Chest lid
        p = skia.Paint()
        p.setAntiAlias(True)
        p.setShader(skia.GradientShader.MakeLinear(
            points=[(chest_x, chest_y - 40), (chest_x, chest_y)],
            colors=[skia_rgba(0.62, 0.48, 0.16), skia_rgba(0.52, 0.38, 0.12)]))
        path = skia.Path()
        path.moveTo(chest_x, chest_y)
        path.cubicTo(chest_x, chest_y - 50, chest_x + chest_w, chest_y - 50, chest_x + chest_w, chest_y)
        path.close()
        canvas.drawPath(path, p)

        # Metal bands
        for bx_offset in [0.25, 0.5, 0.75]:
            bx = chest_x + chest_w * bx_offset
            canvas.drawLine(bx, chest_y - 30, bx, chest_y + chest_h,
                skia_paint(0.45, 0.35, 0.15, style=skia.Paint.kStroke_Style, stroke_width=3))

        # Lock
        lock_cx = chest_x + chest_w / 2
        lock_cy = chest_y + 5
        canvas.drawCircle(lock_cx, lock_cy, 8, skia_paint(0.75, 0.65, 0.20))
        canvas.drawCircle(lock_cx, lock_cy, 4, skia_paint(0.55, 0.45, 0.10))

        # Gold glow
        _draw_radial_gradient_circle(canvas, lock_cx, chest_y, 200,
            [(10/200, (1.0, 0.85, 0.2, 0.3)), (0.3, (1.0, 0.70, 0.1, 0.12)), (1, (0.8, 0.5, 0.0, 0))])

        # Gold coins
        coin_positions = [
            (W * 0.38, 360), (W * 0.42, 375), (W * 0.46, 355), (W * 0.52, 365),
            (W * 0.56, 350), (W * 0.60, 370), (W * 0.50, 380), (W * 0.44, 345),
            (W * 0.40, 385), (W * 0.54, 385), (W * 0.48, 395), (W * 0.58, 390),
        ]
        for gx, gy in coin_positions:
            p = skia.Paint()
            p.setAntiAlias(True)
            p.setShader(skia.GradientShader.MakeRadial(
                center=(gx + 5, gy + 5), radius=9,
                colors=[skia_rgba(1.0, 0.92, 0.45), skia_rgba(0.95, 0.80, 0.20), skia_rgba(0.75, 0.60, 0.10)],
                positions=[0, 0.6, 1.0]))
            canvas.save()
            canvas.translate(gx + 5, gy + 5)
            canvas.scale(8, 6)
            canvas.drawCircle(0, 0, 1, p)
            canvas.restore()

        # Gems
        gem_colors = [(0.9, 0.1, 0.1), (0.1, 0.5, 0.9), (0.1, 0.85, 0.3)]
        gem_positions = [(W * 0.46, 340), (W * 0.54, 348), (W * 0.49, 360)]
        for (gx, gy), (gr, gg, gb) in zip(gem_positions, gem_colors):
            p = skia.Paint()
            p.setAntiAlias(True)
            p.setShader(skia.GradientShader.MakeRadial(
                center=(gx, gy), radius=6,
                colors=[skia_rgba(min(gr + 0.4, 1), min(gg + 0.4, 1), min(gb + 0.4, 1)),
                        skia_rgba(gr * 0.6, gg * 0.6, gb * 0.6)]))
            path = skia.Path()
            path.moveTo(gx, gy - 6); path.lineTo(gx + 5, gy)
            path.lineTo(gx, gy + 6); path.lineTo(gx - 5, gy); path.close()
            canvas.drawPath(path, p)
            canvas.drawCircle(gx - 1, gy - 2, 1.5, skia_paint(1, 1, 1, 0.7))

        # Vignette
        _draw_radial_gradient_circle(canvas, W / 2, H / 2 - 30, 450,
            [(120/450, (0, 0, 0, 0)), (1, (0, 0, 0, 0.55))])

    def _draw_village_scene(self, canvas, W, H):
        # Evening sky
        _draw_linear_gradient_rect(canvas, 0, 0, W, int(H * 0.6),
            (0, 0), (0, H * 0.6),
            [(0, (0.12, 0.08, 0.22)), (0.3, (0.25, 0.12, 0.30)),
             (0.6, (0.55, 0.30, 0.18)), (1, (0.65, 0.42, 0.22))])

        # Ground
        _draw_linear_gradient_rect(canvas, 0, int(H * 0.55), W, int(H * 0.45),
            (0, H * 0.55), (0, H),
            [(0, (0.28, 0.22, 0.14)), (0.5, (0.22, 0.18, 0.10)), (1, (0.15, 0.12, 0.08))])

        # Dirt path
        path = skia.Path()
        path.moveTo(W * 0.3, H)
        path.cubicTo(W * 0.35, H * 0.7, W * 0.55, H * 0.65, W * 0.7, H)
        path.lineTo(W * 0.6, H)
        path.cubicTo(W * 0.48, H * 0.7, W * 0.4, H * 0.75, W * 0.38, H)
        path.close()
        canvas.drawPath(path, skia_paint(0.35, 0.28, 0.18, 0.6))

        # Cottages
        cottages = [
            (W * 0.08, H * 0.35, 120, 100),
            (W * 0.35, H * 0.30, 140, 110),
            (W * 0.65, H * 0.33, 130, 105),
        ]
        for cx, cy, cw, ch in cottages:
            # Wall
            _draw_linear_gradient_rect(canvas, cx, cy, cw, ch,
                (cx, cy), (cx, cy + ch),
                [(0, (0.55, 0.40, 0.25)), (1, (0.42, 0.30, 0.18))])
            # Roof
            roof = skia.Path()
            roof.moveTo(cx - 10, cy); roof.lineTo(cx + cw / 2, cy - 50); roof.lineTo(cx + cw + 10, cy)
            roof.close()
            canvas.drawPath(roof, skia_paint(0.45, 0.20, 0.10))
            # Roof highlight
            rh = skia.Path()
            rh.moveTo(cx - 5, cy); rh.lineTo(cx + cw / 2, cy - 45); rh.lineTo(cx + cw / 2, cy)
            rh.close()
            canvas.drawPath(rh, skia_paint(0.55, 0.28, 0.12, 0.5))

            # Window (warm glow)
            win_x = cx + cw * 0.3
            win_y = cy + ch * 0.3
            win_w, win_h = 22, 22
            _draw_radial_gradient_circle(canvas, win_x + win_w / 2, win_y + win_h / 2, 50,
                [(0, (1.0, 0.85, 0.4, 0.3)), (1, (1.0, 0.7, 0.2, 0))])
            canvas.drawRect(skia.Rect(win_x, win_y, win_x + win_w, win_y + win_h),
                skia_paint(0.95, 0.85, 0.45))
            canvas.drawRect(skia.Rect(win_x, win_y, win_x + win_w, win_y + win_h),
                skia_paint(0.35, 0.22, 0.10, style=skia.Paint.kStroke_Style, stroke_width=2))
            canvas.drawLine(win_x + win_w / 2, win_y, win_x + win_w / 2, win_y + win_h,
                skia_paint(0.35, 0.22, 0.10, style=skia.Paint.kStroke_Style, stroke_width=2))

            # Door
            door_x = cx + cw * 0.6
            door_y = cy + ch * 0.45
            canvas.drawRect(skia.Rect(door_x, door_y, door_x + 20, door_y + ch * 0.55),
                skia_paint(0.30, 0.18, 0.08))

            # Chimney
            chim_x = cx + cw * 0.7
            canvas.drawRect(skia.Rect(chim_x, cy - 40, chim_x + 14, cy + 5),
                skia_paint(0.40, 0.30, 0.25))

            # Smoke
            for i in range(5):
                smoke_y = cy - 45 - i * 18
                canvas.drawCircle(chim_x + 7 + i * 3 * ((-1) ** i), smoke_y, 6 + i * 2,
                    skia_paint(0.6, 0.6, 0.6, 0.3 - i * 0.05))

        # Stars
        seed = int(hashlib.md5(b"village").hexdigest()[:8], 16)
        for i in range(30):
            sx = ((seed * (i + 1) * 7) % W)
            sy = ((seed * (i + 1) * 13) % int(H * 0.3))
            brightness = 0.5 + (i % 5) * 0.1
            canvas.drawCircle(sx, sy, 1.2, skia_paint(1, 1, brightness, 0.6))

    def _draw_night_scene(self, canvas, W, H):
        # Dark sky
        _draw_linear_gradient_rect(canvas, 0, 0, W, H,
            (0, 0), (0, H),
            [(0, (0.02, 0.02, 0.08)), (0.4, (0.04, 0.04, 0.14)),
             (0.7, (0.06, 0.06, 0.16)), (1, (0.03, 0.03, 0.06))])

        # Moon
        moon_x, moon_y = W * 0.75, H * 0.15
        _draw_radial_gradient_circle(canvas, moon_x, moon_y, 120,
            [(20/120, (0.7, 0.75, 0.9, 0.3)), (0.5, (0.4, 0.45, 0.7, 0.1)), (1, (0.1, 0.1, 0.3, 0))])
        # Moon body
        p = skia.Paint()
        p.setAntiAlias(True)
        p.setShader(skia.GradientShader.MakeRadial(
            center=(moon_x - 5, moon_y - 5), radius=30,
            colors=[skia_rgba(0.95, 0.95, 1.0), skia_rgba(0.80, 0.82, 0.90)],
            positions=[5/30, 1.0]))
        canvas.drawCircle(moon_x, moon_y, 30, p)
        # Craters
        for cx, cy, cr in [(moon_x - 8, moon_y - 5, 5), (moon_x + 10, moon_y + 8, 3), (moon_x + 3, moon_y - 12, 4)]:
            canvas.drawCircle(cx, cy, cr, skia_paint(0.7, 0.72, 0.80, 0.3))

        # Stars
        seed = int(hashlib.md5(b"nightsky").hexdigest()[:8], 16)
        for i in range(80):
            sx = ((seed * (i + 1) * 7) % W)
            sy = ((seed * (i + 1) * 13) % int(H * 0.6))
            size = 0.8 + (i % 4) * 0.4
            brightness = 0.5 + (i % 6) * 0.08
            canvas.drawCircle(sx, sy, size, skia_paint(1, 1, brightness, 0.7))
            if i % 7 == 0:
                canvas.drawLine(sx - 4, sy, sx + 4, sy,
                    skia_paint(1, 1, 1, 0.4, style=skia.Paint.kStroke_Style, stroke_width=0.5))
                canvas.drawLine(sx, sy - 4, sx, sy + 4,
                    skia_paint(1, 1, 1, 0.4, style=skia.Paint.kStroke_Style, stroke_width=0.5))

        # Silhouette hills
        path = skia.Path()
        path.moveTo(0, H * 0.7)
        path.cubicTo(W * 0.15, H * 0.55, W * 0.25, H * 0.62, W * 0.4, H * 0.58)
        path.cubicTo(W * 0.55, H * 0.54, W * 0.7, H * 0.60, W * 0.85, H * 0.56)
        path.cubicTo(W * 0.95, H * 0.53, W, H * 0.58, W, H * 0.65)
        path.lineTo(W, H); path.lineTo(0, H); path.close()
        canvas.drawPath(path, skia_paint(0.03, 0.03, 0.06))

        # Silhouette trees
        tree_positions = [W * 0.1, W * 0.2, W * 0.38, W * 0.55, W * 0.72, W * 0.88]
        for tx in tree_positions:
            ty = H * 0.58 + abs(math.sin(tx * 0.01)) * 30
            canvas.drawRect(skia.Rect(tx - 3, ty - 40, tx + 3, ty + 5), skia_paint(0.02, 0.02, 0.05))
            tri1 = skia.Path()
            tri1.moveTo(tx, ty - 70); tri1.lineTo(tx - 20, ty - 30); tri1.lineTo(tx + 20, ty - 30); tri1.close()
            canvas.drawPath(tri1, skia_paint(0.02, 0.02, 0.05))
            tri2 = skia.Path()
            tri2.moveTo(tx, ty - 55); tri2.lineTo(tx - 16, ty - 20); tri2.lineTo(tx + 16, ty - 20); tri2.close()
            canvas.drawPath(tri2, skia_paint(0.02, 0.02, 0.05))

        # Foreground ground
        _draw_linear_gradient_rect(canvas, 0, int(H * 0.7), W, int(H * 0.3),
            (0, H * 0.7), (0, H),
            [(0, (0.03, 0.05, 0.03)), (1, (0.02, 0.03, 0.02))])

    def _draw_market_scene(self, canvas, W, H):
        # Sky
        _draw_linear_gradient_rect(canvas, 0, 0, W, int(H * 0.5),
            (0, 0), (0, H * 0.5),
            [(0, (0.35, 0.55, 0.85)), (0.7, (0.55, 0.70, 0.90)), (1, (0.70, 0.78, 0.88))])

        # Ground
        _draw_linear_gradient_rect(canvas, 0, int(H * 0.45), W, int(H * 0.55),
            (0, H * 0.45), (0, H),
            [(0, (0.45, 0.40, 0.35)), (1, (0.35, 0.30, 0.25))])

        # Cobblestone
        for y in range(int(H * 0.45), H, 18):
            offset = 10 if ((y - int(H * 0.45)) // 18) % 2 else 0
            for x in range(-10 + offset, W + 10, 22):
                canvas.save()
                canvas.translate(x + 10, y + 8)
                canvas.scale(10, 7)
                canvas.drawCircle(0, 0, 1,
                    skia_paint(0.38, 0.33, 0.28, 0.4, style=skia.Paint.kStroke_Style, stroke_width=0.08))
                canvas.restore()

        # Market stalls
        stall_colors = [
            (0.75, 0.20, 0.15), (0.20, 0.55, 0.20),
            (0.20, 0.30, 0.70), (0.70, 0.55, 0.15),
        ]
        stall_positions = [W * 0.05, W * 0.28, W * 0.52, W * 0.76]
        stall_w = W * 0.20

        for i, (sx, (ar, ag, ab)) in enumerate(zip(stall_positions, stall_colors)):
            table_y = H * 0.52
            table_h = H * 0.12

            # Table
            canvas.drawRect(skia.Rect(sx, table_y, sx + stall_w, table_y + table_h),
                skia_paint(0.45, 0.30, 0.15))

            # Awning
            awning_top = table_y - 70
            for stripe in range(6):
                stripe_x = sx + stripe * (stall_w / 6)
                if stripe % 2 == 0:
                    color = (ar, ag, ab)
                else:
                    color = (min(ar + 0.2, 1), min(ag + 0.2, 1), min(ab + 0.2, 1))
                path = skia.Path()
                path.moveTo(stripe_x, awning_top)
                path.lineTo(stripe_x + stall_w / 6, awning_top)
                path.lineTo(stripe_x + stall_w / 6 + 5, table_y - 5)
                path.lineTo(stripe_x + 5, table_y - 5)
                path.close()
                canvas.drawPath(path, skia_paint(*color))

            # Poles
            canvas.drawRect(skia.Rect(sx + 2, awning_top, sx + 6, table_y + table_h), skia_paint(0.35, 0.22, 0.10))
            canvas.drawRect(skia.Rect(sx + stall_w - 6, awning_top, sx + stall_w - 2, table_y + table_h),
                skia_paint(0.35, 0.22, 0.10))

            # Items
            for j in range(4):
                ix = sx + 12 + j * (stall_w / 5)
                iy = table_y + 5
                canvas.drawCircle(ix, iy, 6, skia_paint(0.6 + j * 0.1, 0.4 + (j % 2) * 0.2, 0.2))

        # Crates
        crate_positions = [(W * 0.15, H * 0.75), (W * 0.45, H * 0.78), (W * 0.8, H * 0.72)]
        for crx, cry in crate_positions:
            crate_w, crate_h = 30, 25
            canvas.drawRect(skia.Rect(crx, cry, crx + crate_w, cry + crate_h), skia_paint(0.50, 0.35, 0.18))
            canvas.drawLine(crx, cry + crate_h / 2, crx + crate_w, cry + crate_h / 2,
                skia_paint(0.38, 0.25, 0.12, style=skia.Paint.kStroke_Style, stroke_width=1.5))
            canvas.drawLine(crx + crate_w / 2, cry, crx + crate_w / 2, cry + crate_h,
                skia_paint(0.38, 0.25, 0.12, style=skia.Paint.kStroke_Style, stroke_width=1.5))

        # Sun glow
        _draw_radial_gradient_circle(canvas, W * 0.8, H * 0.1, 400,
            [(30/400, (1.0, 0.95, 0.7, 0.15)), (1, (1.0, 0.85, 0.5, 0))])

    def _draw_road_scene(self, canvas, W, H):
        # Sky
        _draw_linear_gradient_rect(canvas, 0, 0, W, int(H * 0.55),
            (0, 0), (0, H * 0.55),
            [(0, (0.40, 0.60, 0.90)), (0.6, (0.55, 0.72, 0.92)), (1, (0.70, 0.80, 0.85))])

        # Clouds
        cloud_positions = [(W * 0.15, H * 0.1), (W * 0.5, H * 0.08), (W * 0.8, H * 0.15)]
        for clx, cly in cloud_positions:
            for dx, dy, r in [(-15, 0, 18), (0, -5, 22), (15, 0, 18), (25, 5, 14)]:
                canvas.drawCircle(clx + dx, cly + dy, r, skia_paint(1, 1, 1, 0.6))

        # Far hills
        path = skia.Path()
        path.moveTo(0, H * 0.45)
        path.cubicTo(W * 0.1, H * 0.35, W * 0.2, H * 0.40, W * 0.35, H * 0.38)
        path.cubicTo(W * 0.5, H * 0.35, W * 0.6, H * 0.42, W * 0.75, H * 0.37)
        path.cubicTo(W * 0.9, H * 0.33, W * 0.95, H * 0.40, W, H * 0.42)
        path.lineTo(W, H * 0.55); path.lineTo(0, H * 0.55); path.close()
        canvas.drawPath(path, skia_paint(0.45, 0.60, 0.40))

        # Near hills
        p = skia.Paint()
        p.setAntiAlias(True)
        p.setShader(skia.GradientShader.MakeLinear(
            points=[(0, H * 0.45), (0, H)],
            colors=[skia_rgba(0.30, 0.50, 0.22), skia_rgba(0.25, 0.42, 0.18), skia_rgba(0.18, 0.32, 0.12)],
            positions=[0, 0.5, 1.0]))
        path2 = skia.Path()
        path2.moveTo(0, H * 0.5)
        path2.cubicTo(W * 0.15, H * 0.45, W * 0.3, H * 0.52, W * 0.5, H * 0.48)
        path2.cubicTo(W * 0.7, H * 0.44, W * 0.85, H * 0.50, W, H * 0.47)
        path2.lineTo(W, H); path2.lineTo(0, H); path2.close()
        canvas.drawPath(path2, p)

        # Road
        rp = skia.Paint()
        rp.setAntiAlias(True)
        rp.setShader(skia.GradientShader.MakeLinear(
            points=[(0, H * 0.5), (0, H)],
            colors=[skia_rgba(0.55, 0.45, 0.30), skia_rgba(0.40, 0.32, 0.20)]))
        road_path = skia.Path()
        road_path.moveTo(W * 0.35, H)
        road_path.cubicTo(W * 0.38, H * 0.75, W * 0.42, H * 0.6, W * 0.48, H * 0.48)
        road_path.lineTo(W * 0.52, H * 0.48)
        road_path.cubicTo(W * 0.58, H * 0.6, W * 0.62, H * 0.75, W * 0.65, H)
        road_path.close()
        canvas.drawPath(road_path, rp)

        # Road edges
        for pts in [((W * 0.35, H), (W * 0.38, H * 0.75), (W * 0.42, H * 0.6), (W * 0.48, H * 0.48)),
                    ((W * 0.65, H), (W * 0.62, H * 0.75), (W * 0.58, H * 0.6), (W * 0.52, H * 0.48))]:
            ep = skia.Path()
            ep.moveTo(pts[0][0], pts[0][1])
            ep.cubicTo(pts[1][0], pts[1][1], pts[2][0], pts[2][1], pts[3][0], pts[3][1])
            canvas.drawPath(ep, skia_paint(0.35, 0.28, 0.18, 0.5,
                style=skia.Paint.kStroke_Style, stroke_width=2))

        # Grass tufts
        for gx in range(0, W, 25):
            for gy in range(int(H * 0.55), H, 30):
                gp = skia.Path()
                gp.moveTo(gx, gy)
                gp.cubicTo(gx - 2, gy - 8, gx + 1, gy - 10, gx, gy - 12)
                canvas.drawPath(gp, skia_paint(0.28, 0.55, 0.20, 0.3,
                    style=skia.Paint.kStroke_Style, stroke_width=1.5))

        # Distant trees
        for tx, s in [(W * 0.42, 0.5), (W * 0.55, 0.45), (W * 0.38, 0.55),
                      (W * 0.58, 0.4), (W * 0.15, 0.7), (W * 0.85, 0.65)]:
            ty = H * 0.48 + (1 - s) * 40
            canvas.drawCircle(tx, ty - 12 * s, 10 * s, skia_paint(0.15, 0.35, 0.12))
            canvas.drawRect(skia.Rect(tx - 2 * s, ty - 5 * s, tx + 2 * s, ty + 7 * s),
                skia_paint(0.25, 0.15, 0.05))

        # Sun glow
        _draw_radial_gradient_circle(canvas, W * 0.5, H * 0.35, 200,
            [(10/200, (1.0, 0.95, 0.8, 0.2)), (1, (1.0, 0.9, 0.7, 0))])

    def _draw_city_scene(self, canvas, W, H):
        """Draw a medieval city/gate scene."""
        # Sky
        _draw_linear_gradient_rect(canvas, 0, 0, W, int(H * 0.5),
            (0, 0), (0, H * 0.5),
            [(0, (0.45, 0.60, 0.80)), (0.5, (0.55, 0.70, 0.85)), (1, (0.65, 0.75, 0.80))])
        # City wall
        _draw_linear_gradient_rect(canvas, 0, int(H * 0.3), W, int(H * 0.7),
            (0, H * 0.3), (0, H),
            [(0, (0.45, 0.40, 0.35)), (0.3, (0.40, 0.35, 0.28)), (1, (0.30, 0.25, 0.18))])
        # Gate arch
        gate_cx, gate_w, gate_h = W * 0.5, 180, 220
        arch = skia.Path()
        arch.moveTo(gate_cx - gate_w / 2, H * 0.75)
        arch.lineTo(gate_cx - gate_w / 2, H * 0.35)
        arch.arcTo(skia.Rect(gate_cx - gate_w / 2, H * 0.2, gate_cx + gate_w / 2, H * 0.5), 180, 180, False)
        arch.lineTo(gate_cx + gate_w / 2, H * 0.75)
        arch.close()
        canvas.drawPath(arch, skia_paint(0.18, 0.15, 0.12))
        # Gate inside (bright)
        inner = skia.Path()
        inner.moveTo(gate_cx - 70, H * 0.75)
        inner.lineTo(gate_cx - 70, H * 0.4)
        inner.arcTo(skia.Rect(gate_cx - 70, H * 0.28, gate_cx + 70, H * 0.52), 180, 180, False)
        inner.lineTo(gate_cx + 70, H * 0.75)
        inner.close()
        canvas.drawPath(inner, skia_paint(0.65, 0.60, 0.50, 0.7))
        # Towers
        for tx in [W * 0.25, W * 0.75]:
            canvas.drawRect(skia.Rect(tx - 30, H * 0.15, tx + 30, H * 0.75),
                skia_paint(0.38, 0.33, 0.28))
            # Battlement
            for bx in range(int(tx - 30), int(tx + 30), 15):
                canvas.drawRect(skia.Rect(bx, H * 0.12, bx + 8, H * 0.18),
                    skia_paint(0.38, 0.33, 0.28))
            # Window
            canvas.drawRect(skia.Rect(tx - 8, H * 0.30, tx + 8, H * 0.38),
                skia_paint(0.85, 0.75, 0.45))
        # Flags
        for tx in [W * 0.25, W * 0.75]:
            pole_x = tx
            canvas.drawLine(pole_x, H * 0.05, pole_x, H * 0.15,
                skia_paint(0.3, 0.25, 0.2, style=skia.Paint.kStroke_Style, stroke_width=3))
            flag = skia.Path()
            flag.moveTo(pole_x, H * 0.05); flag.lineTo(pole_x + 30, H * 0.08); flag.lineTo(pole_x, H * 0.11)
            flag.close()
            canvas.drawPath(flag, skia_paint(0.8, 0.2, 0.2))
        # Ground (cobblestone hint)
        for gx in range(0, W, 25):
            for gy in range(int(H * 0.72), H, 18):
                canvas.drawRect(skia.Rect(gx, gy, gx + 20, gy + 14),
                    skia_paint(0.35, 0.30, 0.22, 0.4))
                canvas.drawRect(skia.Rect(gx, gy, gx + 20, gy + 14),
                    skia_paint(0.25, 0.20, 0.15, 0.3, style=skia.Paint.kStroke_Style, stroke_width=1))

    def _draw_inn_scene(self, canvas, W, H):
        """Draw an inn/tavern interior scene."""
        # Wall background
        _draw_linear_gradient_rect(canvas, 0, 0, W, H,
            (0, 0), (0, H),
            [(0, (0.28, 0.20, 0.12)), (0.4, (0.32, 0.24, 0.15)), (1, (0.22, 0.16, 0.10))])
        # Wooden floor
        _draw_linear_gradient_rect(canvas, 0, int(H * 0.6), W, int(H * 0.4),
            (0, H * 0.6), (0, H),
            [(0, (0.35, 0.25, 0.15)), (0.5, (0.30, 0.22, 0.12)), (1, (0.25, 0.18, 0.10))])
        # Floor planks
        for fy in range(int(H * 0.6), H, 20):
            canvas.drawLine(0, fy, W, fy,
                skia_paint(0.20, 0.15, 0.08, 0.3, style=skia.Paint.kStroke_Style, stroke_width=1))
        # Fireplace
        fp_x, fp_w, fp_h = W * 0.5, 160, 140
        canvas.drawRect(skia.Rect(fp_x - fp_w / 2, H * 0.15, fp_x + fp_w / 2, H * 0.15 + fp_h),
            skia_paint(0.35, 0.30, 0.25))
        # Fire opening
        canvas.drawRect(skia.Rect(fp_x - 50, H * 0.25, fp_x + 50, H * 0.15 + fp_h),
            skia_paint(0.12, 0.08, 0.05))
        # Fire glow
        _draw_radial_gradient_circle(canvas, fp_x, H * 0.35, 120,
            [(0, (1.0, 0.6, 0.1, 0.6)), (0.5, (1.0, 0.4, 0.05, 0.2)), (1, (0.8, 0.3, 0.0, 0))])
        # Flames
        for i, (fx, fscale) in enumerate([(-20, 1.0), (0, 1.3), (20, 0.9), (-10, 0.7), (15, 1.1)]):
            flame = skia.Path()
            base_y = H * 0.15 + fp_h - 5
            flame.moveTo(fp_x + fx - 8 * fscale, base_y)
            flame.cubicTo(fp_x + fx - 5, base_y - 30 * fscale, fp_x + fx + 5, base_y - 40 * fscale, fp_x + fx, base_y - 50 * fscale)
            flame.cubicTo(fp_x + fx + 8, base_y - 35 * fscale, fp_x + fx + 10, base_y - 20 * fscale, fp_x + fx + 8 * fscale, base_y)
            flame.close()
            alpha = 0.7 - i * 0.08
            canvas.drawPath(flame, skia_paint(1.0, 0.5 + i * 0.05, 0.1, alpha))
        # Chimney above
        canvas.drawRect(skia.Rect(fp_x - 25, 0, fp_x + 25, H * 0.15),
            skia_paint(0.30, 0.22, 0.15))
        # Tables
        for tx, tw in [(W * 0.15, 120), (W * 0.75, 130)]:
            # Table top
            canvas.drawRect(skia.Rect(tx, H * 0.55, tx + tw, H * 0.58),
                skia_paint(0.40, 0.28, 0.15))
            # Table legs
            canvas.drawRect(skia.Rect(tx + 10, H * 0.58, tx + 16, H * 0.72),
                skia_paint(0.35, 0.24, 0.12))
            canvas.drawRect(skia.Rect(tx + tw - 16, H * 0.58, tx + tw - 10, H * 0.72),
                skia_paint(0.35, 0.24, 0.12))
        # Warm ambient glow
        _draw_radial_gradient_circle(canvas, W * 0.5, H * 0.4, 400,
            [(0, (1.0, 0.7, 0.3, 0.08)), (1, (0.5, 0.3, 0.1, 0))])
        # Ceiling beams
        for bx in range(0, W, int(W / 5)):
            canvas.drawRect(skia.Rect(bx, 0, bx + 18, H * 0.04),
                skia_paint(0.25, 0.18, 0.10))

    def _draw_camp_scene(self, canvas, W, H):
        """Draw a campsite/rest area at night."""
        # Night sky
        _draw_linear_gradient_rect(canvas, 0, 0, W, int(H * 0.55),
            (0, 0), (0, H * 0.55),
            [(0, (0.02, 0.02, 0.08)), (0.5, (0.05, 0.05, 0.15)), (1, (0.08, 0.10, 0.18))])
        # Ground
        _draw_linear_gradient_rect(canvas, 0, int(H * 0.5), W, int(H * 0.5),
            (0, H * 0.5), (0, H),
            [(0, (0.12, 0.15, 0.08)), (0.5, (0.10, 0.12, 0.06)), (1, (0.06, 0.08, 0.04))])
        # Stars
        seed = int(hashlib.md5(b"camp").hexdigest()[:8], 16)
        for i in range(50):
            sx = (seed * (i + 1) * 7) % W
            sy = (seed * (i + 1) * 13) % int(H * 0.4)
            brightness = 0.5 + (i % 5) * 0.1
            canvas.drawCircle(sx, sy, 1 + (i % 3) * 0.3, skia_paint(1, 1, brightness, 0.7))
        # Campfire glow
        fire_x, fire_y = W * 0.5, H * 0.6
        _draw_radial_gradient_circle(canvas, fire_x, fire_y, 200,
            [(0, (1.0, 0.6, 0.15, 0.35)), (0.4, (1.0, 0.4, 0.05, 0.15)), (1, (0.5, 0.2, 0.0, 0))])
        # Fire logs
        canvas.drawRect(skia.Rect(fire_x - 25, fire_y + 5, fire_x + 25, fire_y + 12),
            skia_paint(0.3, 0.15, 0.05))
        canvas.drawRect(skia.Rect(fire_x - 18, fire_y, fire_x + 20, fire_y + 7),
            skia_paint(0.25, 0.12, 0.04))
        # Flames
        for fx, fh in [(-12, 45), (0, 60), (12, 40), (-6, 35), (8, 50)]:
            flame = skia.Path()
            flame.moveTo(fire_x + fx - 6, fire_y)
            flame.cubicTo(fire_x + fx - 3, fire_y - fh * 0.6, fire_x + fx + 3, fire_y - fh * 0.8, fire_x + fx, fire_y - fh)
            flame.cubicTo(fire_x + fx + 5, fire_y - fh * 0.5, fire_x + fx + 8, fire_y - fh * 0.3, fire_x + fx + 6, fire_y)
            flame.close()
            canvas.drawPath(flame, skia_paint(1.0, 0.5, 0.1, 0.7))
        # Tent
        tent_x = W * 0.75
        tent = skia.Path()
        tent.moveTo(tent_x - 60, H * 0.55); tent.lineTo(tent_x, H * 0.30); tent.lineTo(tent_x + 60, H * 0.55)
        tent.close()
        canvas.drawPath(tent, skia_paint(0.45, 0.35, 0.20))
        # Tent opening
        tent_open = skia.Path()
        tent_open.moveTo(tent_x - 15, H * 0.55); tent_open.lineTo(tent_x, H * 0.38); tent_open.lineTo(tent_x + 15, H * 0.55)
        tent_open.close()
        canvas.drawPath(tent_open, skia_paint(0.25, 0.18, 0.10))
        # Tent glow from fire
        _draw_radial_gradient_circle(canvas, tent_x, H * 0.45, 80,
            [(0, (1.0, 0.6, 0.2, 0.1)), (1, (0.5, 0.3, 0.1, 0))])
        # Tree silhouettes
        for tx, th in [(W * 0.05, 200), (W * 0.15, 180), (W * 0.88, 190), (W * 0.95, 170)]:
            trunk = skia.Path()
            trunk.moveTo(tx - 4, H * 0.5); trunk.lineTo(tx + 4, H * 0.5)
            trunk.lineTo(tx + 3, H * 0.5 - th * 0.4); trunk.lineTo(tx - 3, H * 0.5 - th * 0.4)
            trunk.close()
            canvas.drawPath(trunk, skia_paint(0.05, 0.05, 0.08))
            # Canopy
            canvas.drawCircle(tx, H * 0.5 - th * 0.5, th * 0.25,
                skia_paint(0.04, 0.06, 0.08))
            canvas.drawCircle(tx - 15, H * 0.5 - th * 0.4, th * 0.18,
                skia_paint(0.04, 0.06, 0.08))
            canvas.drawCircle(tx + 15, H * 0.5 - th * 0.4, th * 0.18,
                skia_paint(0.04, 0.06, 0.08))

    def _draw_default_scene(self, canvas, W, H, name):
        # Moody gradient
        _draw_linear_gradient_rect(canvas, 0, 0, W, H,
            (0, 0), (0, H),
            [(0, (0.10, 0.12, 0.22)), (0.4, (0.15, 0.18, 0.28)),
             (0.7, (0.18, 0.15, 0.20)), (1, (0.08, 0.08, 0.12))])

        # Ground
        _draw_linear_gradient_rect(canvas, 0, int(H * 0.6), W, int(H * 0.4),
            (0, H * 0.6), (0, H),
            [(0, (0.14, 0.14, 0.16)), (1, (0.08, 0.08, 0.10))])

        # Particles
        seed = int(hashlib.md5(name.encode("utf-8")).hexdigest()[:8], 16)
        for i in range(40):
            px = (seed * (i + 1) * 7) % W
            py = (seed * (i + 1) * 13) % H
            r = 1 + (i % 3)
            alpha = 0.05 + (i % 5) * 0.02
            canvas.drawCircle(px, py, r, skia_paint(0.6, 0.65, 0.8, alpha))

        # Center glow
        _draw_radial_gradient_circle(canvas, W / 2, H / 2, 250,
            [(30/250, (0.3, 0.35, 0.5, 0.15)), (1, (0.1, 0.1, 0.2, 0))])

        # Scene name text
        typeface = skia.Typeface.MakeFromName('Malgun Gothic', skia.FontStyle.Bold())
        font = skia.Font(typeface, 36)
        text_w = font.measureText(name)
        tx = (W - text_w) / 2
        ty = H / 2 + 12

        # Shadow
        canvas.drawString(name, tx + 2, ty + 2, font, skia_paint(0, 0, 0, 0.5))
        # Text
        canvas.drawString(name, tx, ty, font, skia_paint(0.85, 0.85, 0.90, 0.9))

        # Decorative line
        line_w = min(text_w + 40, W * 0.6)
        canvas.drawLine((W - line_w) / 2, ty + 15, (W + line_w) / 2, ty + 15,
            skia_paint(0.6, 0.65, 0.8, 0.4, style=skia.Paint.kStroke_Style, stroke_width=1.5))

        # Vignette
        _draw_radial_gradient_circle(canvas, W / 2, H / 2, 500,
            [(150/500, (0, 0, 0, 0)), (1, (0, 0, 0, 0.5))])

    # ===== Scene element generation (characters / objects) =====

    def generate_scene_element(self, element_type, name):
        """Generate a Skia character silhouette or object icon."""
        if element_type == "portrait":
            W, H = 384, 512
        else:
            W, H = 256, 256

        surface = skia.Surface(W, H)
        canvas = surface.getCanvas()
        canvas.clear(skia.ColorTRANSPARENT)

        if element_type == "portrait":
            self._draw_character_silhouette(canvas, W, H, name)
        else:
            self._draw_object_icon(canvas, W, H, name)

        if element_type == "portrait":
            out_dir = os.path.join(self.base_dir, "static", "portraits", "pixel")
        else:
            out_dir = os.path.join(self.base_dir, "static", "illustrations", "pixel")
        os.makedirs(out_dir, exist_ok=True)
        safe_name = name.replace(" ", "_").lower()
        filepath = os.path.join(out_dir, f"{element_type}_{safe_name}.png")
        surface.makeImageSnapshot().save(filepath, skia.kPNG)
        return filepath

    def _hsv_to_rgb(self, hue, s, v):
        c = v * s
        x = c * (1 - abs((hue * 6) % 2 - 1))
        m = v - c
        if hue < 1 / 6:
            r, g, b = c, x, 0
        elif hue < 2 / 6:
            r, g, b = x, c, 0
        elif hue < 3 / 6:
            r, g, b = 0, c, x
        elif hue < 4 / 6:
            r, g, b = 0, x, c
        elif hue < 5 / 6:
            r, g, b = x, 0, c
        else:
            r, g, b = c, 0, x
        return r + m, g + m, b + m

    def _draw_character_silhouette(self, canvas, W, H, name):
        name_hash = int(hashlib.md5(name.encode("utf-8")).hexdigest()[:8], 16)
        hue = (name_hash % 360) / 360.0
        r, g, b = self._hsv_to_rgb(hue, 0.5, 0.6)

        cx, cy = W / 2, H / 2

        # Body gradient via shader
        p_body = skia.Paint()
        p_body.setAntiAlias(True)
        p_body.setShader(skia.GradientShader.MakeLinear(
            points=[(cx, 0), (cx, H)],
            colors=[skia_rgba(r * 0.8, g * 0.8, b * 0.8, 0.85),
                    skia_rgba(r * 0.5, g * 0.5, b * 0.5, 0.90),
                    skia_rgba(r * 0.3, g * 0.3, b * 0.3, 0.85)],
            positions=[0, 0.5, 1.0]))

        # Head
        head_y = H * 0.12
        head_r = W * 0.12
        canvas.drawCircle(cx, head_y + head_r, head_r, p_body)

        # Neck
        neck_w = W * 0.06
        canvas.drawRect(skia.Rect(cx - neck_w, head_y + head_r * 2 - 5,
                                   cx + neck_w, head_y + head_r * 2 - 5 + H * 0.04), p_body)

        # Torso
        torso_top = head_y + head_r * 2 + H * 0.03
        torso_bottom = H * 0.55
        shoulder_w = W * 0.28
        waist_w = W * 0.18
        path = skia.Path()
        path.moveTo(cx - shoulder_w, torso_top)
        path.lineTo(cx + shoulder_w, torso_top)
        path.lineTo(cx + waist_w, torso_bottom)
        path.lineTo(cx - waist_w, torso_bottom)
        path.close()
        canvas.drawPath(path, p_body)

        # Arms
        arm_w = W * 0.06
        for side in [-1, 1]:
            sw = shoulder_w * side
            aw = arm_w * side
            path = skia.Path()
            path.moveTo(cx + sw, torso_top + 5)
            path.lineTo(cx + sw + aw, torso_top + 5)
            path.lineTo(cx + sw + aw * 1.5, torso_bottom + 20)
            path.lineTo(cx + sw + aw * 0.5, torso_bottom + 20)
            path.close()
            canvas.drawPath(path, p_body)

        # Legs
        leg_top = torso_bottom
        leg_bottom = H * 0.88
        leg_w = W * 0.09
        gap = W * 0.02
        for side in [-1, 1]:
            ww = waist_w * side if side > 0 else -waist_w
            gp = gap * side if side > 0 else -gap
            if side < 0:
                path = skia.Path()
                path.moveTo(cx + ww, leg_top)
                path.lineTo(cx - gap, leg_top)
                path.lineTo(cx - gap - leg_w * 0.3, leg_bottom)
                path.lineTo(cx + ww - leg_w * 0.2, leg_bottom)
                path.close()
            else:
                path = skia.Path()
                path.moveTo(cx + gap, leg_top)
                path.lineTo(cx + waist_w, leg_top)
                path.lineTo(cx + waist_w + leg_w * 0.2, leg_bottom)
                path.lineTo(cx + gap + leg_w * 0.3, leg_bottom)
                path.close()
            canvas.drawPath(path, p_body)

        # Feet
        foot_w = W * 0.08
        foot_h = H * 0.03
        foot_paint = skia_paint(r * 0.3, g * 0.3, b * 0.3, 0.85)
        for foot_x in [cx - gap - leg_w * 0.3 - foot_w * 0.3, cx + gap + leg_w * 0.3 + foot_w * 0.3]:
            canvas.save()
            canvas.translate(foot_x, leg_bottom)
            canvas.scale(foot_w, foot_h)
            canvas.drawArc(skia.Rect(-1, -1, 3, 1), 0, 180, False, foot_paint)
            canvas.restore()

        # Rim light
        rim_p = skia.Paint()
        rim_p.setAntiAlias(True)
        rim_p.setShader(skia.GradientShader.MakeLinear(
            points=[(cx + W * 0.2, 0), (cx + W * 0.35, 0)],
            colors=[skia_rgba(r, g, b, 0.2), skia_rgba(r, g, b, 0)]))
        canvas.drawRect(skia.Rect(0, 0, W, H), rim_p)

        # Name label
        typeface = skia.Typeface.MakeFromName('Malgun Gothic', skia.FontStyle.Bold())
        font = skia.Font(typeface, 20)
        text_w = font.measureText(name)
        tx = (W - text_w) / 2
        ty = H * 0.95

        # Label background
        pad = 6
        label_w = text_w + pad * 2
        label_h = 20 + pad * 2
        label_x = (W - label_w) / 2
        label_y = ty - 20 - pad
        rrect = skia.RRect.MakeRectXY(skia.Rect(label_x, label_y, label_x + label_w, label_y + label_h), 4, 4)
        canvas.drawRRect(rrect, skia_paint(0, 0, 0, 0.6))
        canvas.drawString(name, tx, ty, font, skia_paint(1, 1, 1, 0.95))

    def _draw_object_icon(self, canvas, W, H, name):
        cx, cy = W / 2, H / 2
        name_lower = name.lower()

        if any(k in name_lower for k in ["chest", "상자", "보물"]):
            self._draw_chest_icon(canvas, cx, cy, W, H)
        elif any(k in name_lower for k in ["key", "열쇠", "키"]):
            self._draw_key_icon(canvas, cx, cy, W, H)
        elif any(k in name_lower for k in ["potion", "물약", "포션"]):
            self._draw_potion_icon(canvas, cx, cy, W, H)
        elif any(k in name_lower for k in ["scroll", "두루마리", "스크롤"]):
            self._draw_scroll_icon(canvas, cx, cy, W, H)
        elif any(k in name_lower for k in ["sword", "검", "칼", "blade"]):
            self._draw_sword_icon(canvas, cx, cy, W, H)
        elif any(k in name_lower for k in ["shield", "방패"]):
            self._draw_shield_icon(canvas, cx, cy, W, H)
        else:
            self._draw_orb_icon(canvas, cx, cy, W, H, name)

        # Name label
        typeface = skia.Typeface.MakeFromName('Malgun Gothic', skia.FontStyle.Bold())
        font = skia.Font(typeface, 14)
        text_w = font.measureText(name)
        tx = (W - text_w) / 2
        ty = H * 0.92

        canvas.drawString(name, tx + 1, ty + 1, font, skia_paint(0, 0, 0, 0.7))
        canvas.drawString(name, tx, ty, font, skia_paint(1, 1, 1, 0.9))

    def _draw_chest_icon(self, canvas, cx, cy, W, H):
        cw, ch = W * 0.5, H * 0.3
        # Body
        _draw_linear_gradient_rect(canvas, cx - cw / 2, cy, cw, ch,
            (cx - cw / 2, cy), (cx - cw / 2, cy + ch),
            [(0, (0.58, 0.42, 0.12)), (1, (0.38, 0.26, 0.08))])
        # Lid
        p = skia.Paint()
        p.setAntiAlias(True)
        p.setShader(skia.GradientShader.MakeLinear(
            points=[(cx, cy - ch * 0.5), (cx, cy)],
            colors=[skia_rgba(0.62, 0.48, 0.16), skia_rgba(0.52, 0.38, 0.12)]))
        path = skia.Path()
        path.moveTo(cx - cw / 2, cy)
        path.cubicTo(cx - cw / 2, cy - ch * 0.7, cx + cw / 2, cy - ch * 0.7, cx + cw / 2, cy)
        path.close()
        canvas.drawPath(path, p)
        # Band
        canvas.drawLine(cx, cy - ch * 0.4, cx, cy + ch,
            skia_paint(0.45, 0.35, 0.15, style=skia.Paint.kStroke_Style, stroke_width=2))
        # Lock
        canvas.drawCircle(cx, cy + 3, 6, skia_paint(0.75, 0.65, 0.20))
        # Glow
        _draw_radial_gradient_circle(canvas, cx, cy, 80,
            [(10/80, (1.0, 0.85, 0.3, 0.25)), (1, (1.0, 0.7, 0.1, 0))])

    def _draw_key_icon(self, canvas, cx, cy, W, H):
        _draw_radial_gradient_circle(canvas, cx, cy, 80,
            [(10/80, (1.0, 0.85, 0.3, 0.2)), (1, (0.8, 0.6, 0.1, 0))])
        # Shaft
        canvas.drawLine(cx - W * 0.15, cy, cx + W * 0.15, cy,
            skia_paint(0.85, 0.75, 0.25, style=skia.Paint.kStroke_Style, stroke_width=6))
        # Teeth
        for i in range(3):
            t = cx + W * 0.08 + i * 10
            canvas.drawLine(t, cy, t, cy + 12,
                skia_paint(0.85, 0.75, 0.25, style=skia.Paint.kStroke_Style, stroke_width=4))
        # Bow
        canvas.drawCircle(cx - W * 0.2, cy, 15,
            skia_paint(0.85, 0.75, 0.25, style=skia.Paint.kStroke_Style, stroke_width=5))
        # Highlight
        canvas.drawArc(skia.Rect(cx - W * 0.2 - 10, cy - 13, cx - W * 0.2 + 10, cy + 7),
            180, 180, False,
            skia_paint(1, 0.95, 0.5, 0.5, style=skia.Paint.kStroke_Style, stroke_width=2))

    def _draw_potion_icon(self, canvas, cx, cy, W, H):
        bottle_w = W * 0.2
        bottle_h = H * 0.35
        bottle_top = cy - bottle_h * 0.3

        _draw_radial_gradient_circle(canvas, cx, cy + 10, 70,
            [(10/70, (0.2, 0.8, 0.3, 0.3)), (1, (0.1, 0.5, 0.2, 0))])

        # Bottle
        p = skia.Paint()
        p.setAntiAlias(True)
        p.setShader(skia.GradientShader.MakeLinear(
            points=[(cx - bottle_w, cy), (cx + bottle_w, cy)],
            colors=[skia_rgba(0.15, 0.60, 0.25, 0.8), skia_rgba(0.20, 0.75, 0.30, 0.85),
                    skia_rgba(0.15, 0.65, 0.25, 0.85), skia_rgba(0.10, 0.50, 0.20, 0.8)],
            positions=[0, 0.3, 0.7, 1.0]))
        path = skia.Path()
        path.moveTo(cx - bottle_w, bottle_top + bottle_h * 0.3)
        path.cubicTo(cx - bottle_w, bottle_top + bottle_h, cx + bottle_w, bottle_top + bottle_h,
                     cx + bottle_w, bottle_top + bottle_h * 0.3)
        path.lineTo(cx + bottle_w * 0.35, bottle_top + bottle_h * 0.3)
        path.lineTo(cx + bottle_w * 0.35, bottle_top)
        path.lineTo(cx - bottle_w * 0.35, bottle_top)
        path.lineTo(cx - bottle_w * 0.35, bottle_top + bottle_h * 0.3)
        path.close()
        canvas.drawPath(path, p)

        # Cork
        canvas.drawRect(skia.Rect(cx - bottle_w * 0.3, bottle_top - 8,
                                   cx + bottle_w * 0.3, bottle_top + 2), skia_paint(0.55, 0.38, 0.18))

        # Highlight
        hp = skia.Path()
        hp.moveTo(cx - bottle_w * 0.5, bottle_top + bottle_h * 0.35)
        hp.cubicTo(cx - bottle_w * 0.5, bottle_top + bottle_h * 0.8,
                   cx - bottle_w * 0.1, bottle_top + bottle_h * 0.8,
                   cx - bottle_w * 0.1, bottle_top + bottle_h * 0.35)
        hp.close()
        canvas.drawPath(hp, skia_paint(1, 1, 1, 0.25))

    def _draw_scroll_icon(self, canvas, cx, cy, W, H):
        scroll_w = W * 0.35
        scroll_h = H * 0.4
        sx = cx - scroll_w / 2
        sy = cy - scroll_h / 2

        # Parchment body
        p = skia.Paint()
        p.setAntiAlias(True)
        p.setShader(skia.GradientShader.MakeLinear(
            points=[(sx, sy), (sx + scroll_w, sy + scroll_h)],
            colors=[skia_rgba(0.90, 0.82, 0.65), skia_rgba(0.95, 0.88, 0.72), skia_rgba(0.85, 0.78, 0.60)],
            positions=[0, 0.5, 1.0]))
        canvas.drawRect(skia.Rect(sx + 10, sy + 8, sx + scroll_w - 10, sy + scroll_h - 8), p)

        # Top roll
        rp = skia.Paint()
        rp.setAntiAlias(True)
        rp.setShader(skia.GradientShader.MakeLinear(
            points=[(sx, sy), (sx, sy + 16)],
            colors=[skia_rgba(0.80, 0.72, 0.55), skia_rgba(0.92, 0.85, 0.68), skia_rgba(0.82, 0.74, 0.56)],
            positions=[0, 0.5, 1.0]))
        canvas.save()
        canvas.translate(cx, sy + 8)
        canvas.scale(scroll_w / 2, 8)
        canvas.drawCircle(0, 0, 1, rp)
        canvas.restore()

        # Bottom roll
        canvas.save()
        canvas.translate(cx, sy + scroll_h - 8)
        canvas.scale(scroll_w / 2, 8)
        canvas.drawCircle(0, 0, 1, rp)
        canvas.restore()

        # Text lines
        for i in range(5):
            ly = sy + 22 + i * 14
            lw = scroll_w * (0.5 + (i % 3) * 0.1)
            canvas.drawLine(cx - lw / 2, ly, cx + lw / 2, ly,
                skia_paint(0.35, 0.28, 0.15, 0.5, style=skia.Paint.kStroke_Style, stroke_width=1.5))

        # Seal
        canvas.drawCircle(cx, sy + scroll_h + 5, 8, skia_paint(0.75, 0.15, 0.10))

    def _draw_sword_icon(self, canvas, cx, cy, W, H):
        _draw_radial_gradient_circle(canvas, cx, cy, 80,
            [(10/80, (0.7, 0.75, 0.9, 0.2)), (1, (0.4, 0.45, 0.7, 0))])

        # Blade
        p = skia.Paint()
        p.setAntiAlias(True)
        p.setShader(skia.GradientShader.MakeLinear(
            points=[(cx - 8, cy), (cx + 8, cy)],
            colors=[skia_rgba(0.70, 0.72, 0.78), skia_rgba(0.90, 0.92, 0.96),
                    skia_rgba(0.85, 0.87, 0.92), skia_rgba(0.65, 0.67, 0.72)],
            positions=[0, 0.3, 0.7, 1.0]))
        path = skia.Path()
        path.moveTo(cx, cy - H * 0.35); path.lineTo(cx - 8, cy + H * 0.05)
        path.lineTo(cx + 8, cy + H * 0.05); path.close()
        canvas.drawPath(path, p)

        # Guard
        canvas.drawRect(skia.Rect(cx - 25, cy + H * 0.05, cx + 25, cy + H * 0.05 + 8),
            skia_paint(0.55, 0.45, 0.15))

        # Grip
        gp = skia.Paint()
        gp.setAntiAlias(True)
        gp.setShader(skia.GradientShader.MakeLinear(
            points=[(cx - 5, cy + H * 0.05), (cx + 5, cy + H * 0.05)],
            colors=[skia_rgba(0.35, 0.20, 0.08), skia_rgba(0.45, 0.28, 0.12), skia_rgba(0.30, 0.18, 0.06)],
            positions=[0, 0.5, 1.0]))
        canvas.drawRect(skia.Rect(cx - 5, cy + H * 0.06, cx + 5, cy + H * 0.21), gp)

        # Pommel
        canvas.drawCircle(cx, cy + H * 0.22, 7, skia_paint(0.65, 0.55, 0.20))

        # Blade highlight
        canvas.drawLine(cx - 2, cy - H * 0.3, cx - 5, cy + H * 0.04,
            skia_paint(1, 1, 1, 0.3, style=skia.Paint.kStroke_Style, stroke_width=1))

    def _draw_shield_icon(self, canvas, cx, cy, W, H):
        sw, sh = W * 0.35, H * 0.4

        # Shield shape
        p = skia.Paint()
        p.setAntiAlias(True)
        p.setShader(skia.GradientShader.MakeLinear(
            points=[(cx - sw, cy - sh / 2), (cx + sw, cy + sh / 2)],
            colors=[skia_rgba(0.20, 0.30, 0.55), skia_rgba(0.28, 0.40, 0.65), skia_rgba(0.15, 0.25, 0.48)],
            positions=[0, 0.5, 1.0]))

        def _shield_path():
            path = skia.Path()
            path.moveTo(cx, cy - sh / 2)
            path.cubicTo(cx + sw, cy - sh / 2, cx + sw, cy, cx + sw * 0.7, cy + sh * 0.3)
            path.lineTo(cx, cy + sh / 2)
            path.lineTo(cx - sw * 0.7, cy + sh * 0.3)
            path.cubicTo(cx - sw, cy, cx - sw, cy - sh / 2, cx, cy - sh / 2)
            path.close()
            return path

        canvas.drawPath(_shield_path(), p)

        # Border
        canvas.drawPath(_shield_path(),
            skia_paint(0.55, 0.50, 0.20, style=skia.Paint.kStroke_Style, stroke_width=3))

        # Cross emblem
        canvas.drawLine(cx, cy - sh * 0.25, cx, cy + sh * 0.15,
            skia_paint(0.65, 0.60, 0.25, style=skia.Paint.kStroke_Style, stroke_width=4))
        canvas.drawLine(cx - sw * 0.2, cy - sh * 0.05, cx + sw * 0.2, cy - sh * 0.05,
            skia_paint(0.65, 0.60, 0.25, style=skia.Paint.kStroke_Style, stroke_width=4))

        # Highlight
        hp = skia.Path()
        hp.moveTo(cx, cy - sh / 2)
        hp.cubicTo(cx - sw * 0.5, cy - sh / 2, cx - sw * 0.5, cy, cx - sw * 0.3, cy + sh * 0.1)
        hp.lineTo(cx, cy + sh * 0.1); hp.lineTo(cx, cy - sh / 2); hp.close()
        canvas.drawPath(hp, skia_paint(1, 1, 1, 0.15))

    def _draw_orb_icon(self, canvas, cx, cy, W, H, name):
        name_hash = int(hashlib.md5(name.encode("utf-8")).hexdigest()[:8], 16)
        hue = (name_hash % 360) / 360.0
        r, g, b = self._hsv_to_rgb(hue, 0.7, 0.8)

        orb_r = min(W, H) * 0.25

        # Outer glow
        _draw_radial_gradient_circle(canvas, cx, cy, orb_r * 2.5, [
            (orb_r * 0.5 / (orb_r * 2.5), (r, g, b, 0.3)),
            (0.5, (r * 0.5, g * 0.5, b * 0.5, 0.1)),
            (1, (r * 0.2, g * 0.2, b * 0.2, 0))])

        # Orb body
        p = skia.Paint()
        p.setAntiAlias(True)
        p.setShader(skia.GradientShader.MakeRadial(
            center=(cx - orb_r * 0.3, cy - orb_r * 0.3), radius=orb_r,
            colors=[skia_rgba(min(r + 0.3, 1), min(g + 0.3, 1), min(b + 0.3, 1)),
                    skia_rgba(r, g, b), skia_rgba(r * 0.5, g * 0.5, b * 0.5)],
            positions=[0, 0.7, 1.0]))
        canvas.drawCircle(cx, cy, orb_r, p)

        # Highlights
        canvas.drawCircle(cx - orb_r * 0.25, cy - orb_r * 0.25, orb_r * 0.25,
            skia_paint(1, 1, 1, 0.4))
        canvas.drawCircle(cx + orb_r * 0.3, cy + orb_r * 0.3, orb_r * 0.1,
            skia_paint(1, 1, 1, 0.2))
