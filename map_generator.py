import json
import os
from PIL import Image, ImageDraw, ImageFont
import cairo
import math


class MapGenerator:
    def __init__(self):
        self.tile_size = 40
        self.map_width = 20
        self.map_height = 15
        self.img_width = self.map_width * self.tile_size
        self.img_height = self.map_height * self.tile_size
        self.base_dir = os.path.dirname(os.path.abspath(__file__))

    def load_game_state(self):
        path = os.path.join(self.base_dir, "game_state.json")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def generate_map(self):
        state = self.load_game_state()
        img = Image.new("RGB", (self.img_width, self.img_height), "#2d5a1e")
        draw = ImageDraw.Draw(img)

        # Draw location areas
        location_colors = {
            "grass": "#4a8c2a",
            "dungeon": "#6b6b6b",
            "treasure": "#c8a82a",
        }
        for loc in state["map"]["locations"]:
            area = loc["area"]
            x1 = area["x1"] * self.tile_size
            y1 = area["y1"] * self.tile_size
            x2 = (area["x2"] + 1) * self.tile_size
            y2 = (area["y2"] + 1) * self.tile_size
            color = location_colors.get(loc["type"], "#4a8c2a")
            draw.rectangle([x1, y1, x2, y2], fill=color)

        # Draw grid
        for x in range(0, self.img_width + 1, self.tile_size):
            draw.line([(x, 0), (x, self.img_height)], fill="#1a1a1a", width=1)
        for y in range(0, self.img_height + 1, self.tile_size):
            draw.line([(0, y), (self.img_width, y)], fill="#1a1a1a", width=1)

        # Draw location labels
        try:
            font = ImageFont.truetype("arial.ttf", 14)
            font_small = ImageFont.truetype("arial.ttf", 11)
        except (OSError, IOError):
            font = ImageFont.load_default()
            font_small = font

        for loc in state["map"]["locations"]:
            area = loc["area"]
            cx = ((area["x1"] + area["x2"]) / 2) * self.tile_size
            cy = area["y1"] * self.tile_size + 5
            draw.text((cx - 20, cy), loc["name"], fill="white", font=font_small)

        # Draw NPCs as triangles (purple)
        for npc in state["npcs"]:
            if npc.get("status") == "dead":
                continue
            px, py = npc["position"]
            cx = px * self.tile_size + self.tile_size // 2
            cy = py * self.tile_size + self.tile_size // 2
            size = 14
            triangle = [
                (cx, cy - size),
                (cx - size, cy + size),
                (cx + size, cy + size),
            ]
            draw.polygon(triangle, fill="#9b30ff", outline="white")
            draw.text(
                (cx - 15, cy + size + 2), npc["name"][:4], fill="white", font=font_small
            )

        # Draw players as circles
        player_colors = {
            "전사": "#e63946",
            "마법사": "#457be0",
            "도적": "#2ecc71",
        }
        for player in state["players"]:
            px, py = player["position"]
            cx = px * self.tile_size + self.tile_size // 2
            cy = py * self.tile_size + self.tile_size // 2
            color = player_colors.get(player["class"], "white")
            r = 12
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color, outline="white", width=2)
            draw.text(
                (cx - 8, cy + r + 2),
                player["name"][:3],
                fill="white",
                font=font_small,
            )

        # Draw turn info
        turn = state.get("turn_count", 0)
        draw.rectangle([0, 0, 150, 25], fill="#00000088")
        draw.text((5, 5), f"Turn: {turn}", fill="yellow", font=font)

        return img

    def save_map(self):
        img = self.generate_map()
        out_path = os.path.join(self.base_dir, "static", "map.png")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        img.save(out_path, "PNG")
        self.generate_portraits()
        self.generate_pixel_backgrounds()
        return out_path

    def generate_portraits(self):
        """Generate high-quality Cairo portraits for all players."""
        state = self.load_game_state()
        portrait_dir = os.path.join(self.base_dir, "static", "portraits", "pixel")
        os.makedirs(portrait_dir, exist_ok=True)

        class_configs = {
            "전사": {
                "primary": (0.90, 0.22, 0.27),     # #e63946
                "secondary": (0.75, 0.22, 0.17),    # #c0392b
                "hair": (0.35, 0.20, 0.10),
                "emblem": "swords",
                "detail": "scar",
            },
            "마법사": {
                "primary": (0.27, 0.48, 0.88),     # #457be0
                "secondary": (0.17, 0.24, 0.62),    # #2c3e9e
                "hair": (0.15, 0.15, 0.20),
                "emblem": "star",
                "detail": "glow",
            },
            "도적": {
                "primary": (0.18, 0.80, 0.44),     # #2ecc71
                "secondary": (0.15, 0.68, 0.38),    # #27ae60
                "hair": (0.30, 0.22, 0.12),
                "emblem": "dagger",
                "detail": "hood",
            },
        }

        SIZE = 200
        for player in state.get("players", []):
            config = class_configs.get(player["class"], class_configs["전사"])
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, SIZE, SIZE)
            ctx = cairo.Context(surface)
            cx, cy = SIZE / 2, SIZE / 2

            # Clip to circle
            ctx.arc(cx, cy, 95, 0, 2 * math.pi)
            ctx.clip()

            # Background gradient
            bg = cairo.RadialGradient(cx, cy - 20, 10, cx, cy, 100)
            bg.add_color_stop_rgb(0, 0.12, 0.08, 0.20)
            bg.add_color_stop_rgb(1, 0.04, 0.02, 0.08)
            ctx.set_source(bg)
            ctx.paint()

            # --- Head ---
            head_cx, head_cy = cx, 72
            head_rx, head_ry = 38, 44

            # Hair (behind head)
            ctx.save()
            r, g, b = config["hair"]
            ctx.set_source_rgb(r, g, b)
            ctx.move_to(head_cx - 42, head_cy - 5)
            ctx.curve_to(head_cx - 45, head_cy - 50, head_cx + 45, head_cy - 50, head_cx + 42, head_cy - 5)
            ctx.curve_to(head_cx + 45, head_cy + 15, head_cx + 40, head_cy + 30, head_cx + 35, head_cy + 40)
            ctx.line_to(head_cx - 35, head_cy + 40)
            ctx.curve_to(head_cx - 40, head_cy + 30, head_cx - 45, head_cy + 15, head_cx - 42, head_cy - 5)
            ctx.fill()
            ctx.restore()

            # Face
            skin = cairo.RadialGradient(head_cx - 5, head_cy - 10, 5, head_cx, head_cy, 45)
            skin.add_color_stop_rgb(0, 0.98, 0.85, 0.72)
            skin.add_color_stop_rgb(1, 0.90, 0.72, 0.55)
            ctx.set_source(skin)
            ctx.save()
            ctx.translate(head_cx, head_cy)
            ctx.scale(head_rx, head_ry)
            ctx.arc(0, 0, 1, 0, 2 * math.pi)
            ctx.restore()
            ctx.fill()

            # Eyes
            for eye_x in [head_cx - 14, head_cx + 14]:
                # White
                ctx.set_source_rgb(0.95, 0.95, 0.97)
                ctx.save()
                ctx.translate(eye_x, head_cy + 2)
                ctx.scale(8, 5)
                ctx.arc(0, 0, 1, 0, 2 * math.pi)
                ctx.restore()
                ctx.fill()
                # Iris
                iris = cairo.RadialGradient(eye_x - 1, head_cy + 1, 1, eye_x, head_cy + 2, 5)
                iris.add_color_stop_rgb(0, 0.45, 0.30, 0.15)
                iris.add_color_stop_rgb(1, 0.25, 0.15, 0.05)
                ctx.set_source(iris)
                ctx.arc(eye_x, head_cy + 2, 4, 0, 2 * math.pi)
                ctx.fill()
                # Pupil
                ctx.set_source_rgb(0.05, 0.05, 0.08)
                ctx.arc(eye_x, head_cy + 2, 2, 0, 2 * math.pi)
                ctx.fill()
                # Highlight
                ctx.set_source_rgba(1, 1, 1, 0.8)
                ctx.arc(eye_x + 1.5, head_cy + 0.5, 1.2, 0, 2 * math.pi)
                ctx.fill()

            # Eyebrows
            ctx.set_source_rgb(config["hair"][0] * 0.7, config["hair"][1] * 0.7, config["hair"][2] * 0.7)
            ctx.set_line_width(2.5)
            for bx, direction in [(head_cx - 14, 1), (head_cx + 14, -1)]:
                ctx.move_to(bx - 9 * direction, head_cy - 8)
                ctx.curve_to(bx - 5 * direction, head_cy - 12, bx + 5 * direction, head_cy - 12, bx + 9 * direction, head_cy - 9)
                ctx.stroke()

            # Nose
            ctx.set_source_rgba(0.70, 0.50, 0.38, 0.5)
            ctx.set_line_width(1.5)
            ctx.move_to(head_cx, head_cy + 5)
            ctx.line_to(head_cx - 3, head_cy + 16)
            ctx.curve_to(head_cx - 2, head_cy + 18, head_cx + 2, head_cy + 18, head_cx + 3, head_cy + 16)
            ctx.stroke()

            # Mouth
            ctx.set_source_rgb(0.78, 0.45, 0.40)
            ctx.set_line_width(1.8)
            ctx.move_to(head_cx - 10, head_cy + 24)
            ctx.curve_to(head_cx - 5, head_cy + 27, head_cx + 5, head_cy + 27, head_cx + 10, head_cy + 24)
            ctx.stroke()
            # Upper lip line
            ctx.set_source_rgba(0.55, 0.30, 0.25, 0.6)
            ctx.set_line_width(1)
            ctx.move_to(head_cx - 8, head_cy + 24)
            ctx.curve_to(head_cx - 3, head_cy + 22, head_cx + 3, head_cy + 22, head_cx + 8, head_cy + 24)
            ctx.stroke()

            # Class-specific face detail
            if config["detail"] == "scar":
                ctx.set_source_rgba(0.65, 0.35, 0.30, 0.6)
                ctx.set_line_width(1.5)
                ctx.move_to(head_cx + 20, head_cy - 5)
                ctx.line_to(head_cx + 15, head_cy + 15)
                ctx.stroke()
            elif config["detail"] == "glow":
                glow = cairo.RadialGradient(head_cx, head_cy - 30, 5, head_cx, head_cy - 30, 25)
                glow.add_color_stop_rgba(0, 0.4, 0.6, 1.0, 0.3)
                glow.add_color_stop_rgba(1, 0.2, 0.3, 0.8, 0)
                ctx.set_source(glow)
                ctx.paint()

            # --- Body/Armor ---
            r, g, b = config["primary"]
            body = cairo.LinearGradient(cx - 60, 130, cx + 60, 200)
            body.add_color_stop_rgb(0, r * 1.1, g * 1.1, b * 1.1)
            body.add_color_stop_rgb(1, config["secondary"][0], config["secondary"][1], config["secondary"][2])
            ctx.set_source(body)
            ctx.move_to(cx - 55, 130)
            ctx.curve_to(cx - 65, 145, cx - 70, 190, cx - 60, 210)
            ctx.line_to(cx + 60, 210)
            ctx.curve_to(cx + 70, 190, cx + 65, 145, cx + 55, 130)
            ctx.close_path()
            ctx.fill()

            # Collar / neckline
            sr, sg, sb = config["secondary"]
            ctx.set_source_rgb(sr * 0.8, sg * 0.8, sb * 0.8)
            ctx.move_to(cx - 25, 125)
            ctx.curve_to(cx - 15, 140, cx + 15, 140, cx + 25, 125)
            ctx.curve_to(cx + 15, 135, cx - 15, 135, cx - 25, 125)
            ctx.fill()

            # Emblem on chest
            if config["emblem"] == "swords":
                # Crossed swords
                ctx.set_source_rgba(0.85, 0.85, 0.80, 0.8)
                ctx.set_line_width(2.5)
                ctx.move_to(cx - 10, 150)
                ctx.line_to(cx + 10, 175)
                ctx.stroke()
                ctx.move_to(cx + 10, 150)
                ctx.line_to(cx - 10, 175)
                ctx.stroke()
                # Guards
                ctx.set_source_rgba(r, g, b, 0.9)
                ctx.set_line_width(3)
                ctx.move_to(cx - 14, 155)
                ctx.line_to(cx - 6, 155)
                ctx.stroke()
                ctx.move_to(cx + 6, 155)
                ctx.line_to(cx + 14, 155)
                ctx.stroke()
            elif config["emblem"] == "star":
                ctx.set_source_rgba(1, 0.85, 0.0, 0.8)
                for i in range(5):
                    angle = -math.pi / 2 + i * 2 * math.pi / 5
                    x = cx + 10 * math.cos(angle)
                    y = 162 + 10 * math.sin(angle)
                    if i == 0:
                        ctx.move_to(x, y)
                    else:
                        ctx.line_to(x, y)
                    inner_angle = angle + math.pi / 5
                    ix = cx + 4 * math.cos(inner_angle)
                    iy = 162 + 4 * math.sin(inner_angle)
                    ctx.line_to(ix, iy)
                ctx.close_path()
                ctx.fill()
            elif config["emblem"] == "dagger":
                ctx.set_source_rgba(0.85, 0.85, 0.80, 0.8)
                ctx.set_line_width(2)
                ctx.move_to(cx, 148)
                ctx.line_to(cx, 178)
                ctx.stroke()
                ctx.set_line_width(3)
                ctx.move_to(cx - 6, 155)
                ctx.line_to(cx + 6, 155)
                ctx.stroke()

            # Hood for rogue
            if config["detail"] == "hood":
                ctx.set_source_rgba(0.12, 0.55, 0.30, 0.35)
                ctx.move_to(head_cx - 45, head_cy - 15)
                ctx.curve_to(head_cx - 48, head_cy - 55, head_cx + 48, head_cy - 55, head_cx + 45, head_cy - 15)
                ctx.curve_to(head_cx + 50, head_cy - 5, head_cx + 48, head_cy + 5, head_cx + 43, head_cy + 10)
                ctx.line_to(head_cx - 43, head_cy + 10)
                ctx.curve_to(head_cx - 48, head_cy + 5, head_cx - 50, head_cy - 5, head_cx - 45, head_cy - 15)
                ctx.fill()

            # Vignette
            ctx.reset_clip()
            vignette = cairo.RadialGradient(cx, cy, 50, cx, cy, 100)
            vignette.add_color_stop_rgba(0, 0, 0, 0, 0)
            vignette.add_color_stop_rgba(1, 0, 0, 0, 0.4)
            ctx.set_source(vignette)
            ctx.arc(cx, cy, 95, 0, 2 * math.pi)
            ctx.fill()

            # Border ring
            ctx.set_source_rgb(r * 0.6, g * 0.6, b * 0.6)
            ctx.set_line_width(3)
            ctx.arc(cx, cy, 95, 0, 2 * math.pi)
            ctx.stroke()

            filepath = os.path.join(portrait_dir, f"player_{player['id']}.png")
            surface.write_to_png(filepath)

        return portrait_dir

    def generate_pixel_backgrounds(self):
        """Generate high-quality Cairo backgrounds for each scene type."""
        bg_dir = os.path.join(self.base_dir, "static", "illustrations", "pixel")
        os.makedirs(bg_dir, exist_ok=True)

        W, H = 768, 512

        # --- Forest ---
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
        ctx = cairo.Context(surface)

        # Sky gradient (deep blue to warm horizon)
        sky = cairo.LinearGradient(0, 0, 0, 320)
        sky.add_color_stop_rgb(0, 0.05, 0.05, 0.18)
        sky.add_color_stop_rgb(0.6, 0.10, 0.15, 0.30)
        sky.add_color_stop_rgb(1, 0.20, 0.30, 0.20)
        ctx.set_source(sky)
        ctx.rectangle(0, 0, W, 320)
        ctx.fill()

        # Ground gradient
        ground = cairo.LinearGradient(0, 300, 0, H)
        ground.add_color_stop_rgb(0, 0.18, 0.38, 0.12)
        ground.add_color_stop_rgb(0.4, 0.14, 0.30, 0.08)
        ground.add_color_stop_rgb(1, 0.08, 0.18, 0.04)
        ctx.set_source(ground)
        ctx.rectangle(0, 300, W, H - 300)
        ctx.fill()

        # Ground texture (subtle grass tufts)
        ctx.set_line_width(1.5)
        for gx in range(0, W, 18):
            for gy in range(310, H, 25):
                ctx.set_source_rgba(0.22, 0.50, 0.15, 0.3)
                ctx.move_to(gx, gy)
                ctx.curve_to(gx - 3, gy - 10, gx + 2, gy - 12, gx + 1, gy - 15)
                ctx.stroke()

        # Trees (back layer, smaller)
        for tx, scale in [(60, 0.7), (180, 0.8), (350, 0.65), (520, 0.75), (680, 0.7)]:
            # Trunk
            tw = 12 * scale
            th = 100 * scale
            trunk_grad = cairo.LinearGradient(tx - tw, 0, tx + tw, 0)
            trunk_grad.add_color_stop_rgb(0, 0.25, 0.14, 0.06)
            trunk_grad.add_color_stop_rgb(0.5, 0.35, 0.20, 0.08)
            trunk_grad.add_color_stop_rgb(1, 0.20, 0.12, 0.05)
            ctx.set_source(trunk_grad)
            ctx.rectangle(tx - tw / 2, 300 - th, tw, th + 10)
            ctx.fill()

            # Canopy layers (multiple overlapping ellipses with gradients)
            for layer in range(3):
                ly = 300 - th - 20 + layer * 15
                lr = (50 - layer * 8) * scale
                leaf = cairo.RadialGradient(tx, ly, lr * 0.2, tx, ly, lr)
                leaf.add_color_stop_rgb(0, 0.20, 0.55, 0.18)
                leaf.add_color_stop_rgb(0.6, 0.15, 0.42, 0.12)
                leaf.add_color_stop_rgb(1, 0.10, 0.30, 0.08)
                ctx.set_source(leaf)
                ctx.save()
                ctx.translate(tx, ly)
                ctx.scale(1, 0.75)
                ctx.arc(0, 0, lr, 0, 2 * math.pi)
                ctx.restore()
                ctx.fill()

        # Trees (front layer, larger)
        for tx, scale in [(130, 1.1), (420, 1.2), (600, 1.0)]:
            tw = 16 * scale
            th = 140 * scale
            trunk_grad = cairo.LinearGradient(tx - tw, 0, tx + tw, 0)
            trunk_grad.add_color_stop_rgb(0, 0.30, 0.16, 0.06)
            trunk_grad.add_color_stop_rgb(0.5, 0.42, 0.24, 0.10)
            trunk_grad.add_color_stop_rgb(1, 0.22, 0.13, 0.05)
            ctx.set_source(trunk_grad)
            ctx.rectangle(tx - tw / 2, 300 - th, tw, th + 20)
            ctx.fill()

            for layer in range(4):
                ly = 300 - th - 30 + layer * 20
                lr = (65 - layer * 10) * scale
                leaf = cairo.RadialGradient(tx, ly, lr * 0.15, tx, ly, lr)
                leaf.add_color_stop_rgb(0, 0.25, 0.62, 0.22)
                leaf.add_color_stop_rgb(0.5, 0.18, 0.48, 0.14)
                leaf.add_color_stop_rgb(1, 0.10, 0.32, 0.08)
                ctx.set_source(leaf)
                ctx.save()
                ctx.translate(tx, ly)
                ctx.scale(1, 0.7)
                ctx.arc(0, 0, lr, 0, 2 * math.pi)
                ctx.restore()
                ctx.fill()

        # Fog / atmospheric haze
        fog = cairo.LinearGradient(0, 250, 0, 350)
        fog.add_color_stop_rgba(0, 0.3, 0.4, 0.3, 0)
        fog.add_color_stop_rgba(0.5, 0.3, 0.4, 0.3, 0.15)
        fog.add_color_stop_rgba(1, 0.3, 0.4, 0.3, 0)
        ctx.set_source(fog)
        ctx.rectangle(0, 250, W, 100)
        ctx.fill()

        # Light rays from top
        for rx in [200, 400, 580]:
            ray = cairo.LinearGradient(rx, 0, rx + 30, 320)
            ray.add_color_stop_rgba(0, 0.9, 0.9, 0.6, 0.08)
            ray.add_color_stop_rgba(1, 0.9, 0.9, 0.6, 0)
            ctx.set_source(ray)
            ctx.move_to(rx, 0)
            ctx.line_to(rx + 50, 0)
            ctx.line_to(rx + 80, 320)
            ctx.line_to(rx - 10, 320)
            ctx.close_path()
            ctx.fill()

        surface.write_to_png(os.path.join(bg_dir, "forest.png"))

        # --- Dungeon ---
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
        ctx = cairo.Context(surface)

        # Ceiling/wall gradient
        wall = cairo.LinearGradient(0, 0, 0, H)
        wall.add_color_stop_rgb(0, 0.04, 0.04, 0.06)
        wall.add_color_stop_rgb(0.3, 0.10, 0.10, 0.12)
        wall.add_color_stop_rgb(0.6, 0.14, 0.13, 0.14)
        wall.add_color_stop_rgb(1, 0.08, 0.07, 0.08)
        ctx.set_source(wall)
        ctx.paint()

        # Stone floor
        floor_grad = cairo.LinearGradient(0, 320, 0, H)
        floor_grad.add_color_stop_rgb(0, 0.18, 0.17, 0.16)
        floor_grad.add_color_stop_rgb(1, 0.10, 0.09, 0.09)
        ctx.set_source(floor_grad)
        ctx.rectangle(0, 320, W, H - 320)
        ctx.fill()

        # Floor stone tiles
        ctx.set_line_width(1)
        for y in range(320, H, 30):
            offset = 20 if ((y - 320) // 30) % 2 else 0
            for x in range(-20 + offset, W + 20, 55):
                ctx.set_source_rgba(0.22, 0.21, 0.20, 0.5)
                ctx.rectangle(x, y, 50, 26)
                ctx.stroke()

        # Stone pillars with lighting
        for px in [120, 380, 640]:
            # Pillar body gradient (lit from center torch)
            pillar = cairo.LinearGradient(px - 5, 0, px + 50, 0)
            pillar.add_color_stop_rgb(0, 0.20, 0.19, 0.18)
            pillar.add_color_stop_rgb(0.4, 0.32, 0.30, 0.28)
            pillar.add_color_stop_rgb(0.7, 0.28, 0.27, 0.25)
            pillar.add_color_stop_rgb(1, 0.16, 0.15, 0.14)
            ctx.set_source(pillar)
            ctx.rectangle(px, 80, 45, 240)
            ctx.fill()

            # Pillar cap
            cap = cairo.LinearGradient(px - 8, 75, px + 55, 75)
            cap.add_color_stop_rgb(0, 0.24, 0.23, 0.22)
            cap.add_color_stop_rgb(0.5, 0.36, 0.34, 0.32)
            cap.add_color_stop_rgb(1, 0.20, 0.19, 0.18)
            ctx.set_source(cap)
            ctx.rectangle(px - 8, 72, 61, 18)
            ctx.fill()

            # Pillar base
            ctx.set_source(cap)
            ctx.rectangle(px - 5, 310, 55, 15)
            ctx.fill()

            # Stone line details on pillar
            ctx.set_source_rgba(0.12, 0.11, 0.10, 0.4)
            ctx.set_line_width(1)
            for sy in range(100, 310, 35):
                ctx.move_to(px, sy)
                ctx.line_to(px + 45, sy)
                ctx.stroke()

        # Torches on walls (between pillars)
        for tx in [250, 510]:
            # Torch handle
            ctx.set_source_rgb(0.35, 0.18, 0.06)
            ctx.rectangle(tx - 3, 160, 8, 45)
            ctx.fill()

            # Flame glow (large radial)
            flame_glow = cairo.RadialGradient(tx + 1, 148, 5, tx + 1, 148, 80)
            flame_glow.add_color_stop_rgba(0, 1.0, 0.65, 0.1, 0.25)
            flame_glow.add_color_stop_rgba(0.4, 1.0, 0.40, 0.0, 0.10)
            flame_glow.add_color_stop_rgba(1, 0.8, 0.2, 0.0, 0)
            ctx.set_source(flame_glow)
            ctx.paint()

            # Outer flame
            ctx.set_source_rgba(1.0, 0.45, 0.0, 0.9)
            ctx.move_to(tx - 8, 160)
            ctx.curve_to(tx - 10, 145, tx + 1, 125, tx + 1, 118)
            ctx.curve_to(tx + 1, 125, tx + 12, 145, tx + 10, 160)
            ctx.close_path()
            ctx.fill()

            # Inner flame
            ctx.set_source_rgba(1.0, 0.75, 0.0, 0.9)
            ctx.move_to(tx - 4, 160)
            ctx.curve_to(tx - 5, 148, tx + 1, 132, tx + 1, 128)
            ctx.curve_to(tx + 1, 132, tx + 7, 148, tx + 6, 160)
            ctx.close_path()
            ctx.fill()

            # Bright core
            ctx.set_source_rgba(1.0, 0.95, 0.6, 0.8)
            ctx.move_to(tx - 1, 158)
            ctx.curve_to(tx - 1, 150, tx + 1, 140, tx + 1, 136)
            ctx.curve_to(tx + 1, 140, tx + 3, 150, tx + 3, 158)
            ctx.close_path()
            ctx.fill()

        # Overall darkness vignette
        vignette = cairo.RadialGradient(W / 2, H / 2, 100, W / 2, H / 2, 450)
        vignette.add_color_stop_rgba(0, 0, 0, 0, 0)
        vignette.add_color_stop_rgba(1, 0, 0, 0, 0.6)
        ctx.set_source(vignette)
        ctx.paint()

        surface.write_to_png(os.path.join(bg_dir, "dungeon.png"))

        # --- Treasure ---
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
        ctx = cairo.Context(surface)

        # Background warm tones
        bg_grad = cairo.LinearGradient(0, 0, 0, H)
        bg_grad.add_color_stop_rgb(0, 0.12, 0.08, 0.04)
        bg_grad.add_color_stop_rgb(0.4, 0.18, 0.12, 0.06)
        bg_grad.add_color_stop_rgb(1, 0.10, 0.06, 0.03)
        ctx.set_source(bg_grad)
        ctx.paint()

        # Stone floor
        floor_grad = cairo.LinearGradient(0, 340, 0, H)
        floor_grad.add_color_stop_rgb(0, 0.32, 0.26, 0.18)
        floor_grad.add_color_stop_rgb(1, 0.20, 0.15, 0.10)
        ctx.set_source(floor_grad)
        ctx.rectangle(0, 340, W, H - 340)
        ctx.fill()

        # Floor tiles
        ctx.set_line_width(1)
        for y in range(340, H, 28):
            offset = 15 if ((y - 340) // 28) % 2 else 0
            for x in range(-15 + offset, W + 15, 50):
                ctx.set_source_rgba(0.38, 0.30, 0.22, 0.4)
                ctx.rectangle(x, y, 46, 24)
                ctx.stroke()

        # Treasure chest
        chest_x, chest_y = W / 2 - 70, 290
        chest_w, chest_h = 140, 80

        # Chest body
        chest_body = cairo.LinearGradient(chest_x, chest_y, chest_x, chest_y + chest_h)
        chest_body.add_color_stop_rgb(0, 0.58, 0.42, 0.12)
        chest_body.add_color_stop_rgb(0.5, 0.50, 0.36, 0.10)
        chest_body.add_color_stop_rgb(1, 0.38, 0.26, 0.08)
        ctx.set_source(chest_body)
        ctx.rectangle(chest_x, chest_y, chest_w, chest_h)
        ctx.fill()

        # Chest lid (arc)
        lid_grad = cairo.LinearGradient(chest_x, chest_y - 40, chest_x, chest_y)
        lid_grad.add_color_stop_rgb(0, 0.62, 0.48, 0.16)
        lid_grad.add_color_stop_rgb(1, 0.52, 0.38, 0.12)
        ctx.set_source(lid_grad)
        ctx.move_to(chest_x, chest_y)
        ctx.curve_to(chest_x, chest_y - 50, chest_x + chest_w, chest_y - 50, chest_x + chest_w, chest_y)
        ctx.close_path()
        ctx.fill()

        # Chest metal bands
        ctx.set_source_rgb(0.45, 0.35, 0.15)
        ctx.set_line_width(3)
        for bx_offset in [0.25, 0.5, 0.75]:
            bx = chest_x + chest_w * bx_offset
            ctx.move_to(bx, chest_y - 30)
            ctx.line_to(bx, chest_y + chest_h)
            ctx.stroke()

        # Chest lock
        lock_cx = chest_x + chest_w / 2
        lock_cy = chest_y + 5
        ctx.set_source_rgb(0.75, 0.65, 0.20)
        ctx.arc(lock_cx, lock_cy, 8, 0, 2 * math.pi)
        ctx.fill()
        ctx.set_source_rgb(0.55, 0.45, 0.10)
        ctx.arc(lock_cx, lock_cy, 4, 0, 2 * math.pi)
        ctx.fill()

        # Gold glow from chest
        gold_glow = cairo.RadialGradient(lock_cx, chest_y, 10, lock_cx, chest_y, 200)
        gold_glow.add_color_stop_rgba(0, 1.0, 0.85, 0.2, 0.3)
        gold_glow.add_color_stop_rgba(0.3, 1.0, 0.70, 0.1, 0.12)
        gold_glow.add_color_stop_rgba(1, 0.8, 0.5, 0.0, 0)
        ctx.set_source(gold_glow)
        ctx.paint()

        # Gold coins scattered
        coin_positions = [
            (290, 360), (320, 375), (350, 355), (400, 365),
            (430, 350), (460, 370), (380, 380), (340, 345),
            (310, 385), (410, 385), (370, 395), (450, 390),
        ]
        for gx, gy in coin_positions:
            coin = cairo.RadialGradient(gx + 3, gy + 3, 1, gx + 5, gy + 5, 9)
            coin.add_color_stop_rgb(0, 1.0, 0.92, 0.45)
            coin.add_color_stop_rgb(0.6, 0.95, 0.80, 0.20)
            coin.add_color_stop_rgb(1, 0.75, 0.60, 0.10)
            ctx.set_source(coin)
            ctx.save()
            ctx.translate(gx + 5, gy + 5)
            ctx.scale(8, 6)
            ctx.arc(0, 0, 1, 0, 2 * math.pi)
            ctx.restore()
            ctx.fill()
            # Coin edge highlight
            ctx.set_source_rgba(1, 0.95, 0.5, 0.5)
            ctx.save()
            ctx.translate(gx + 4, gy + 4)
            ctx.scale(6, 4)
            ctx.arc(0, 0, 1, 0, 2 * math.pi)
            ctx.restore()
            ctx.stroke()

        # Gem accents
        gem_colors = [
            (0.9, 0.1, 0.1),  # ruby
            (0.1, 0.5, 0.9),  # sapphire
            (0.1, 0.85, 0.3), # emerald
        ]
        gem_positions = [(350, 340), (410, 348), (375, 360)]
        for (gx, gy), (gr, gg, gb) in zip(gem_positions, gem_colors):
            gem = cairo.RadialGradient(gx - 1, gy - 1, 1, gx, gy, 6)
            gem.add_color_stop_rgb(0, min(gr + 0.4, 1), min(gg + 0.4, 1), min(gb + 0.4, 1))
            gem.add_color_stop_rgb(1, gr * 0.6, gg * 0.6, gb * 0.6)
            ctx.set_source(gem)
            # Diamond shape
            ctx.move_to(gx, gy - 6)
            ctx.line_to(gx + 5, gy)
            ctx.line_to(gx, gy + 6)
            ctx.line_to(gx - 5, gy)
            ctx.close_path()
            ctx.fill()
            # Sparkle highlight
            ctx.set_source_rgba(1, 1, 1, 0.7)
            ctx.arc(gx - 1, gy - 2, 1.5, 0, 2 * math.pi)
            ctx.fill()

        # Warm vignette
        vignette = cairo.RadialGradient(W / 2, H / 2 - 30, 120, W / 2, H / 2, 450)
        vignette.add_color_stop_rgba(0, 0, 0, 0, 0)
        vignette.add_color_stop_rgba(1, 0, 0, 0, 0.55)
        ctx.set_source(vignette)
        ctx.paint()

        surface.write_to_png(os.path.join(bg_dir, "treasure.png"))

        return bg_dir


if __name__ == "__main__":
    gen = MapGenerator()
    path = gen.save_map()
    print(f"Map saved to {path}")
