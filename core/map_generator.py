import json
import os
from PIL import Image, ImageDraw, ImageFont
import cairo
import math


font_paths_global = [
    "C:/Windows/Fonts/malgun.ttf",
    "C:/Windows/Fonts/gulim.ttc",
    "C:/Windows/Fonts/batang.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "arial.ttf",
]


class MapGenerator:
    def __init__(self):
        self.tile_size = 40
        self.map_width = 20
        self.map_height = 15
        self.img_width = self.map_width * self.tile_size
        self.img_height = self.map_height * self.tile_size
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def load_game_state(self):
        path = os.path.join(self.base_dir, "data", "game_state.json")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def generate_map(self):
        state = self.load_game_state()

        # Try to load location-based map from worldbuilding
        current_loc = state.get("current_location", "")
        wb_map = None
        if current_loc:
            try:
                wb_path = os.path.join(self.base_dir, "data", "worldbuilding.json")
                with open(wb_path, "r", encoding="utf-8") as f:
                    wb = json.load(f)
                loc_data = wb.get("locations", {}).get(current_loc, {})
                wb_map = loc_data.get("map")
            except Exception:
                pass

        if wb_map:
            map_w = wb_map["width"]
            map_h = wb_map["height"]
            locations = wb_map["areas"]
        else:
            map_w = state["map"]["width"]
            map_h = state["map"]["height"]
            locations = state["map"]["locations"]

        margin_left = 22   # 세로 좌표 표시 여백
        margin_top = 16    # 가로 좌표 표시 여백
        grid_w = map_w * self.tile_size
        grid_h = map_h * self.tile_size
        img_w = grid_w + margin_left
        img_h = grid_h + margin_top
        img = Image.new("RGB", (img_w, img_h), "#1a1a1a")
        draw = ImageDraw.Draw(img)

        # 좌표 표시용 작은 폰트
        coord_font = ImageFont.load_default()
        for fp in font_paths_global:
            try:
                coord_font = ImageFont.truetype(fp, 10)
                break
            except (OSError, IOError):
                continue

        # Draw location areas
        location_colors = {
            "grass": "#4a8c2a",
            "dungeon": "#6b6b6b",
            "treasure": "#c8a82a",
            "village": "#8B7355",
            "road": "#A0926B",
            "house": "#6B4226",
        }
        # 배경 채우기 (그리드 영역)
        draw.rectangle([margin_left, margin_top, img_w, img_h], fill="#2d5a1e")

        for loc in locations:
            area = loc["area"]
            x1 = area["x1"] * self.tile_size + margin_left
            y1 = area["y1"] * self.tile_size + margin_top
            x2 = (area["x2"] + 1) * self.tile_size + margin_left
            y2 = (area["y2"] + 1) * self.tile_size + margin_top
            color = location_colors.get(loc["type"], "#4a8c2a")
            draw.rectangle([x1, y1, x2, y2], fill=color)

        # Draw grid + 좌표
        for i in range(map_w + 1):
            x = i * self.tile_size + margin_left
            draw.line([(x, margin_top), (x, img_h)], fill="#1a1a1a", width=2)
        for i in range(map_h + 1):
            y = i * self.tile_size + margin_top
            draw.line([(margin_left, y), (img_w, y)], fill="#1a1a1a", width=2)

        # 가로 좌표 (상단)
        for i in range(map_w):
            x = i * self.tile_size + margin_left + self.tile_size // 2 - 6
            draw.text((x, 4), str(i), fill="#888888", font=coord_font)

        # 세로 좌표 (좌측)
        for i in range(map_h):
            y = i * self.tile_size + margin_top + self.tile_size // 2 - 8
            draw.text((4, y), str(i), fill="#888888", font=coord_font)

        # Draw location labels
        font = font_small = font_name = ImageFont.load_default()
        bold_paths = ["C:/Windows/Fonts/malgunbd.ttf", "C:/Windows/Fonts/arialbd.ttf"] + font_paths_global
        for fp in font_paths_global:
            try:
                font = ImageFont.truetype(fp, 14)
                font_small = ImageFont.truetype(fp, 11)
                break
            except (OSError, IOError):
                continue
        # 이름 표시용 볼드 폰트
        for fp in bold_paths:
            try:
                font_name = ImageFont.truetype(fp, 14)
                break
            except (OSError, IOError):
                continue

        # Emoji font for entity icons
        emoji_font = None
        try:
            emoji_font = ImageFont.truetype("C:/Windows/Fonts/seguiemj.ttf", 20)
        except (OSError, IOError):
            pass

        # Emoji maps
        player_emojis = {"전사": "\u2694\ufe0f", "마법사": "\U0001f52e", "도적": "\U0001f5e1\ufe0f", "궁수": "\U0001f3f9", "성직자": "\u271d\ufe0f"}
        npc_emojis = {"friendly": "\U0001f60a", "monster": "\U0001f479", "neutral": "\U0001f464"}

        # === 충돌 회피 라벨 시스템 ===
        # 1) 모든 엔티티 아이콘 위치 수집
        entity_icons = []  # [(cx, cy, r)] 아이콘 중심과 반경

        # NPC 아이콘 그리기 + 위치 수집
        r = 12
        for npc in state["npcs"]:
            if npc.get("status") == "fled":
                continue  # 도주한 NPC만 제외, 시체는 표시
            px, py = npc["position"]
            if px < 0 or py < 0 or px >= map_w or py >= map_h:
                continue
            npc_location = npc.get("location", "")
            if current_loc and npc_location and npc_location != current_loc:
                continue
            cx = px * self.tile_size + self.tile_size // 2 + margin_left
            cy = py * self.tile_size + self.tile_size // 2 + margin_top
            npc_type = npc.get("type", "neutral")
            is_dead = npc.get("status") == "dead"

            if is_dead:
                # 시체: 회색 + 💀
                color = "#555555"
                emoji_char = "\U0001f480"  # 💀
            elif npc_type == "monster":
                color = "#9b30ff"
                emoji_char = npc_emojis.get("monster", "\U0001f479")
            elif npc_type == "friendly":
                color = "#f1c40f"
                emoji_char = npc_emojis.get("friendly", "\U0001f60a")
            else:
                color = "#95a5a6"
                emoji_char = npc_emojis.get("neutral", "\U0001f464")

            if emoji_font:
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color + "88", outline="white" if not is_dead else "#666", width=2)
                try:
                    draw.text((cx - 10, cy - 10), emoji_char, font=emoji_font, embedded_color=True)
                except TypeError:
                    draw.text((cx - 10, cy - 10), emoji_char, font=emoji_font)
            else:
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color, outline="white", width=2)

            label_color = "#666" if is_dead else (color if npc_type != "monster" else "white")
            # NPC name - show "???" if unknown
            npc_name = npc["name"][:4] if npc.get("known", False) else "???"
            entity_icons.append({"cx": cx, "cy": cy, "r": r, "name": npc_name, "color": label_color, "type": "npc"})

        # 플레이어 아이콘 그리기 + 위치 수집
        player_colors = {"전사": "#e63946", "마법사": "#457be0", "도적": "#2ecc71", "궁수": "#e67e22", "성직자": "#f1c40f"}
        for player in state["players"]:
            px, py = player["position"]
            cx = px * self.tile_size + self.tile_size // 2 + margin_left
            cy = py * self.tile_size + self.tile_size // 2 + margin_top
            color = player_colors.get(player["class"], "white")
            if emoji_font:
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color + "88", outline="white", width=2)
                try:
                    draw.text((cx - 10, cy - 10), player_emojis.get(player["class"], "\u2694\ufe0f"), font=emoji_font, embedded_color=True)
                except TypeError:
                    draw.text((cx - 10, cy - 10), player_emojis.get(player["class"], "\u2694\ufe0f"), font=emoji_font)
            else:
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color, outline="white", width=3)
            entity_icons.append({"cx": cx, "cy": cy, "r": r, "name": player["name"][:3], "color": "white", "type": "player"})

        # 2) 점유 영역 추적 (충돌 회피용)
        occupied = []  # [(x1, y1, x2, y2)] 이미 배치된 라벨/아이콘 영역
        for e in entity_icons:
            occupied.append((e["cx"] - e["r"], e["cy"] - e["r"], e["cx"] + e["r"], e["cy"] + e["r"]))

        def is_overlapping(x1, y1, x2, y2):
            for ox1, oy1, ox2, oy2 in occupied:
                if x1 < ox2 and x2 > ox1 and y1 < oy2 and y2 > oy1:
                    return True
            return False

        # 3) 장소 라벨 — 충돌 회피하며 배치
        label_font = font_name
        for loc in locations:
            area = loc["area"]
            text = loc["name"]
            tw = len(text) * 8 + 4
            label_cx = ((area["x1"] + area["x2"]) / 2) * self.tile_size + margin_left
            # 기본: 영역 상단
            label_y = area["y1"] * self.tile_size + margin_top + 3
            lx1, ly1 = label_cx - tw // 2, label_y - 1
            lx2, ly2 = label_cx + tw // 2, label_y + 16
            # 충돌 시 위로 이동
            if is_overlapping(lx1, ly1, lx2, ly2):
                label_y -= self.tile_size
                lx1, ly1 = label_cx - tw // 2, label_y - 1
                lx2, ly2 = label_cx + tw // 2, label_y + 16
            draw.rectangle([lx1, ly1, lx2, ly2], fill="#000000aa")
            draw.text((lx1 + 2, label_y), text, fill="white", font=label_font)
            occupied.append((lx1, ly1, lx2, ly2))

        # 4) 엔티티 이름 — 충돌 회피하며 배치
        for e in entity_icons:
            name = e["name"]
            fill = e["color"] if e["type"] == "npc" else "white"
            ntw = len(name) * 8 + 4
            # 기본: 아이콘 아래
            nx = e["cx"] - ntw // 2
            ny = e["cy"] + e["r"] + 2
            if is_overlapping(nx, ny, nx + ntw, ny + 16):
                # 아래 충돌 → 위로
                ny = e["cy"] - e["r"] - 16
                if is_overlapping(nx, ny, nx + ntw, ny + 16):
                    # 위도 충돌 → 오른쪽
                    nx = e["cx"] + e["r"] + 2
                    ny = e["cy"] - 7
            draw.text((nx, ny), name, fill=fill, font=font_name)
            occupied.append((nx, ny, nx + ntw, ny + 16))

        # Draw turn info and location name
        turn = state.get("turn_count", 0)
        loc_name = ""
        if wb_map and current_loc:
            try:
                loc_name = loc_data.get("name", current_loc)
            except Exception:
                loc_name = current_loc
        info_text = f"Turn: {turn}"
        if loc_name:
            info_text += f"  |  {loc_name}"
        draw.rectangle([0, 0, max(250, len(info_text) * 9), 22], fill="#00000088")
        draw.text((4, 3), info_text, fill="yellow", font=font)

        return img

    def save_map(self):
        img = self.generate_map()
        out_dir = os.path.join(self.base_dir, "static")
        os.makedirs(out_dir, exist_ok=True)

        # 전체 맵 (확대용)
        full_path = os.path.join(out_dir, "map.png")
        img.save(full_path, "PNG")

        # 플레이어 주변 크롭 (사이드바용)
        self._save_mini_map(img)

        self.generate_portraits()
        self.generate_pixel_backgrounds()
        return full_path

    def _save_mini_map(self, full_img):
        """플레이어 중심으로 크롭한 미니맵 생성."""
        state = self.load_game_state()
        players = state.get("players", [])
        if not players:
            return

        # 플레이어 중심 좌표 계산
        positions = [p.get("position", [0, 0]) for p in players]
        avg_x = sum(p[0] for p in positions) / len(positions)
        avg_y = sum(p[1] for p in positions) / len(positions)

        # 주변 반경 (타일 단위) — 가로세로 다르게
        radius_x = 7
        radius_y = 7
        margin_left = 22
        margin_top = 16

        # 픽셀 좌표로 변환 (margin 포함)
        center_px = int(avg_x * self.tile_size + self.tile_size // 2 + margin_left)
        center_py = int(avg_y * self.tile_size + self.tile_size // 2 + margin_top)
        crop_w = radius_x * self.tile_size * 2
        crop_h = radius_y * self.tile_size * 2

        left = max(0, center_px - crop_w // 2)
        top = max(0, center_py - crop_h // 2)
        right = min(full_img.width, left + crop_w)
        bottom = min(full_img.height, top + crop_h)

        if right - left < crop_w:
            left = max(0, right - crop_w)
        if bottom - top < crop_h:
            top = max(0, bottom - crop_h)

        cropped = full_img.crop((left, top, right, bottom))

        # 미니맵에 좌표 오버레이 추가 — 크고 굵게, 타일 한 칸 크기
        from PIL import ImageDraw, ImageFont
        draw_mini = ImageDraw.Draw(cropped)

        # 볼드 폰트 시도 (malgunbd = 맑은고딕 Bold)
        coord_font = ImageFont.load_default()
        bold_paths = [
            "C:/Windows/Fonts/malgunbd.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
        ] + font_paths_global
        for fp in bold_paths:
            try:
                coord_font = ImageFont.truetype(fp, 14)
                break
            except (OSError, IOError):
                continue

        # 크롭 영역의 타일 범위 계산
        tile_start_x = max(0, int((left - margin_left) / self.tile_size))
        tile_start_y = max(0, int((top - margin_top) / self.tile_size))
        tile_end_x = tile_start_x + int(crop_w / self.tile_size) + 1
        tile_end_y = tile_start_y + int(crop_h / self.tile_size) + 1

        # 가로 좌표 (상단) — 타일 중앙에 배치
        for i in range(tile_start_x, tile_end_x):
            tile_center_x = (i * self.tile_size + margin_left + self.tile_size // 2) - left
            text = str(i)
            tx = tile_center_x - 4 if i < 10 else tile_center_x - 8
            if 0 <= tx < cropped.width - 10:
                draw_mini.text((tx, 2), text, fill="#dddddd", font=coord_font)

        # 세로 좌표 (좌측) — 타일 중앙에 배치
        for i in range(tile_start_y, tile_end_y):
            tile_center_y = (i * self.tile_size + margin_top + self.tile_size // 2) - top
            text = str(i)
            ty = tile_center_y - 7
            if 0 <= ty < cropped.height - 10:
                draw_mini.text((2, ty), text, fill="#dddddd", font=coord_font)

        # 사이드바 너비(440px)에 맞게 리사이즈
        sidebar_width = 412  # 440 - padding 28
        if cropped.width > sidebar_width:
            ratio = sidebar_width / cropped.width
            new_h = int(cropped.height * ratio)
            cropped = cropped.resize((sidebar_width, new_h), Image.LANCZOS)

        mini_path = os.path.join(self.base_dir, "static", "map_mini.png")
        cropped.save(mini_path, "PNG")

    def generate_portraits(self, force=False):
        """Generate high-quality Cairo portraits for all players. Skip if file already exists (e.g. Gemini crop)."""
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
            filepath = os.path.join(portrait_dir, f"player_{player['id']}.png")
            if not force and os.path.exists(filepath):
                continue  # Skip if portrait already exists (e.g. Gemini crop)

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
            ctx.scale(4, 3)
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

    # ===== Scene background generation (dynamic, name-based) =====

    def generate_scene_background(self, scene_name):
        """Generate a Cairo background dynamically based on scene name."""
        W, H = 896, 512
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
        ctx = cairo.Context(surface)

        name_lower = scene_name.lower()

        # Determine scene type from name keywords
        if any(k in name_lower for k in ["forest", "숲", "나무", "woods"]):
            self._draw_forest_scene(ctx, W, H)
        elif any(k in name_lower for k in ["dungeon", "던전", "동굴", "cave", "underground"]):
            self._draw_dungeon_scene(ctx, W, H)
        elif any(k in name_lower for k in ["treasure", "보물", "gold", "황금"]):
            self._draw_treasure_scene(ctx, W, H)
        elif any(k in name_lower for k in ["village", "마을", "town", "home", "집", "cottage"]):
            self._draw_village_scene(ctx, W, H)
        elif any(k in name_lower for k in ["night", "밤", "evening", "석양", "sunset", "dusk"]):
            self._draw_night_scene(ctx, W, H)
        elif any(k in name_lower for k in ["market", "시장", "shop", "상점", "trade"]):
            self._draw_market_scene(ctx, W, H)
        elif any(k in name_lower for k in ["road", "길", "path", "여행", "travel"]):
            self._draw_road_scene(ctx, W, H)
        else:
            self._draw_default_scene(ctx, W, H, scene_name)

        # Save
        out_dir = os.path.join(self.base_dir, "static", "illustrations", "pixel")
        os.makedirs(out_dir, exist_ok=True)
        safe_name = scene_name.replace(" ", "_").lower()
        filepath = os.path.join(out_dir, f"{safe_name}.png")
        surface.write_to_png(filepath)
        return filepath

    def _draw_forest_scene(self, ctx, W, H):
        """Draw a forest scene - reuses the logic from generate_pixel_backgrounds."""
        # Sky gradient
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

        # Ground texture
        ctx.set_line_width(1.5)
        for gx in range(0, W, 18):
            for gy in range(310, H, 25):
                ctx.set_source_rgba(0.22, 0.50, 0.15, 0.3)
                ctx.move_to(gx, gy)
                ctx.curve_to(gx - 3, gy - 10, gx + 2, gy - 12, gx + 1, gy - 15)
                ctx.stroke()

        # Trees (back layer)
        x_scale = W / 768.0
        for tx, scale in [(int(60 * x_scale), 0.7), (int(180 * x_scale), 0.8),
                          (int(350 * x_scale), 0.65), (int(520 * x_scale), 0.75),
                          (int(680 * x_scale), 0.7), (int(800 * x_scale), 0.72)]:
            tw = 12 * scale
            th = 100 * scale
            trunk_grad = cairo.LinearGradient(tx - tw, 0, tx + tw, 0)
            trunk_grad.add_color_stop_rgb(0, 0.25, 0.14, 0.06)
            trunk_grad.add_color_stop_rgb(0.5, 0.35, 0.20, 0.08)
            trunk_grad.add_color_stop_rgb(1, 0.20, 0.12, 0.05)
            ctx.set_source(trunk_grad)
            ctx.rectangle(tx - tw / 2, 300 - th, tw, th + 10)
            ctx.fill()
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

        # Trees (front layer)
        for tx, scale in [(int(130 * x_scale), 1.1), (int(420 * x_scale), 1.2),
                          (int(600 * x_scale), 1.0), (int(780 * x_scale), 1.05)]:
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

        # Fog
        fog = cairo.LinearGradient(0, 250, 0, 350)
        fog.add_color_stop_rgba(0, 0.3, 0.4, 0.3, 0)
        fog.add_color_stop_rgba(0.5, 0.3, 0.4, 0.3, 0.15)
        fog.add_color_stop_rgba(1, 0.3, 0.4, 0.3, 0)
        ctx.set_source(fog)
        ctx.rectangle(0, 250, W, 100)
        ctx.fill()

        # Light rays
        for rx in [int(200 * W / 768), int(400 * W / 768), int(580 * W / 768), int(750 * W / 768)]:
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

    def _draw_dungeon_scene(self, ctx, W, H):
        """Draw a dungeon/cave scene."""
        x_scale = W / 768.0

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

        # Floor tiles
        ctx.set_line_width(1)
        for y in range(320, H, 30):
            offset = 20 if ((y - 320) // 30) % 2 else 0
            for x in range(-20 + offset, W + 20, 55):
                ctx.set_source_rgba(0.22, 0.21, 0.20, 0.5)
                ctx.rectangle(x, y, 50, 26)
                ctx.stroke()

        # Stone pillars
        pillar_positions = [int(p * x_scale) for p in [120, 380, 640]]
        if W > 800:
            pillar_positions.append(int(820 * x_scale))
        for px in pillar_positions:
            pillar = cairo.LinearGradient(px - 5, 0, px + 50, 0)
            pillar.add_color_stop_rgb(0, 0.20, 0.19, 0.18)
            pillar.add_color_stop_rgb(0.4, 0.32, 0.30, 0.28)
            pillar.add_color_stop_rgb(0.7, 0.28, 0.27, 0.25)
            pillar.add_color_stop_rgb(1, 0.16, 0.15, 0.14)
            ctx.set_source(pillar)
            ctx.rectangle(px, 80, 45, 240)
            ctx.fill()
            cap = cairo.LinearGradient(px - 8, 75, px + 55, 75)
            cap.add_color_stop_rgb(0, 0.24, 0.23, 0.22)
            cap.add_color_stop_rgb(0.5, 0.36, 0.34, 0.32)
            cap.add_color_stop_rgb(1, 0.20, 0.19, 0.18)
            ctx.set_source(cap)
            ctx.rectangle(px - 8, 72, 61, 18)
            ctx.fill()
            ctx.set_source(cap)
            ctx.rectangle(px - 5, 310, 55, 15)
            ctx.fill()
            ctx.set_source_rgba(0.12, 0.11, 0.10, 0.4)
            ctx.set_line_width(1)
            for sy in range(100, 310, 35):
                ctx.move_to(px, sy)
                ctx.line_to(px + 45, sy)
                ctx.stroke()

        # Torches
        torch_positions = [int(p * x_scale) for p in [250, 510]]
        if W > 800:
            torch_positions.append(int(730 * x_scale))
        for tx in torch_positions:
            ctx.set_source_rgb(0.35, 0.18, 0.06)
            ctx.rectangle(tx - 3, 160, 8, 45)
            ctx.fill()
            flame_glow = cairo.RadialGradient(tx + 1, 148, 5, tx + 1, 148, 80)
            flame_glow.add_color_stop_rgba(0, 1.0, 0.65, 0.1, 0.25)
            flame_glow.add_color_stop_rgba(0.4, 1.0, 0.40, 0.0, 0.10)
            flame_glow.add_color_stop_rgba(1, 0.8, 0.2, 0.0, 0)
            ctx.set_source(flame_glow)
            ctx.paint()
            ctx.set_source_rgba(1.0, 0.45, 0.0, 0.9)
            ctx.move_to(tx - 8, 160)
            ctx.curve_to(tx - 10, 145, tx + 1, 125, tx + 1, 118)
            ctx.curve_to(tx + 1, 125, tx + 12, 145, tx + 10, 160)
            ctx.close_path()
            ctx.fill()
            ctx.set_source_rgba(1.0, 0.75, 0.0, 0.9)
            ctx.move_to(tx - 4, 160)
            ctx.curve_to(tx - 5, 148, tx + 1, 132, tx + 1, 128)
            ctx.curve_to(tx + 1, 132, tx + 7, 148, tx + 6, 160)
            ctx.close_path()
            ctx.fill()
            ctx.set_source_rgba(1.0, 0.95, 0.6, 0.8)
            ctx.move_to(tx - 1, 158)
            ctx.curve_to(tx - 1, 150, tx + 1, 140, tx + 1, 136)
            ctx.curve_to(tx + 1, 140, tx + 3, 150, tx + 3, 158)
            ctx.close_path()
            ctx.fill()

        # Vignette
        vignette = cairo.RadialGradient(W / 2, H / 2, 100, W / 2, H / 2, 450)
        vignette.add_color_stop_rgba(0, 0, 0, 0, 0)
        vignette.add_color_stop_rgba(1, 0, 0, 0, 0.6)
        ctx.set_source(vignette)
        ctx.paint()

    def _draw_treasure_scene(self, ctx, W, H):
        """Draw a treasure room scene."""
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
        chest_body = cairo.LinearGradient(chest_x, chest_y, chest_x, chest_y + chest_h)
        chest_body.add_color_stop_rgb(0, 0.58, 0.42, 0.12)
        chest_body.add_color_stop_rgb(0.5, 0.50, 0.36, 0.10)
        chest_body.add_color_stop_rgb(1, 0.38, 0.26, 0.08)
        ctx.set_source(chest_body)
        ctx.rectangle(chest_x, chest_y, chest_w, chest_h)
        ctx.fill()

        # Chest lid
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

        # Gold glow
        gold_glow = cairo.RadialGradient(lock_cx, chest_y, 10, lock_cx, chest_y, 200)
        gold_glow.add_color_stop_rgba(0, 1.0, 0.85, 0.2, 0.3)
        gold_glow.add_color_stop_rgba(0.3, 1.0, 0.70, 0.1, 0.12)
        gold_glow.add_color_stop_rgba(1, 0.8, 0.5, 0.0, 0)
        ctx.set_source(gold_glow)
        ctx.paint()

        # Gold coins
        coin_positions = [
            (W * 0.38, 360), (W * 0.42, 375), (W * 0.46, 355), (W * 0.52, 365),
            (W * 0.56, 350), (W * 0.60, 370), (W * 0.50, 380), (W * 0.44, 345),
            (W * 0.40, 385), (W * 0.54, 385), (W * 0.48, 395), (W * 0.58, 390),
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

        # Gems
        gem_colors = [(0.9, 0.1, 0.1), (0.1, 0.5, 0.9), (0.1, 0.85, 0.3)]
        gem_positions = [(W * 0.46, 340), (W * 0.54, 348), (W * 0.49, 360)]
        for (gx, gy), (gr, gg, gb) in zip(gem_positions, gem_colors):
            gem = cairo.RadialGradient(gx - 1, gy - 1, 1, gx, gy, 6)
            gem.add_color_stop_rgb(0, min(gr + 0.4, 1), min(gg + 0.4, 1), min(gb + 0.4, 1))
            gem.add_color_stop_rgb(1, gr * 0.6, gg * 0.6, gb * 0.6)
            ctx.set_source(gem)
            ctx.move_to(gx, gy - 6)
            ctx.line_to(gx + 5, gy)
            ctx.line_to(gx, gy + 6)
            ctx.line_to(gx - 5, gy)
            ctx.close_path()
            ctx.fill()

        # Vignette
        vignette = cairo.RadialGradient(W / 2, H / 2 - 30, 120, W / 2, H / 2, 450)
        vignette.add_color_stop_rgba(0, 0, 0, 0, 0)
        vignette.add_color_stop_rgba(1, 0, 0, 0, 0.55)
        ctx.set_source(vignette)
        ctx.paint()

    def _draw_village_scene(self, ctx, W, H):
        """Draw a village scene with cottages, warm lights, chimney smoke, evening sky."""
        # Evening sky gradient
        sky = cairo.LinearGradient(0, 0, 0, H * 0.6)
        sky.add_color_stop_rgb(0, 0.12, 0.08, 0.22)
        sky.add_color_stop_rgb(0.3, 0.25, 0.12, 0.30)
        sky.add_color_stop_rgb(0.6, 0.55, 0.30, 0.18)
        sky.add_color_stop_rgb(1, 0.65, 0.42, 0.22)
        ctx.set_source(sky)
        ctx.rectangle(0, 0, W, H * 0.6)
        ctx.fill()

        # Ground
        ground = cairo.LinearGradient(0, H * 0.55, 0, H)
        ground.add_color_stop_rgb(0, 0.28, 0.22, 0.14)
        ground.add_color_stop_rgb(0.5, 0.22, 0.18, 0.10)
        ground.add_color_stop_rgb(1, 0.15, 0.12, 0.08)
        ctx.set_source(ground)
        ctx.rectangle(0, H * 0.55, W, H * 0.45)
        ctx.fill()

        # Dirt path
        ctx.set_source_rgba(0.35, 0.28, 0.18, 0.6)
        ctx.move_to(W * 0.3, H)
        ctx.curve_to(W * 0.35, H * 0.7, W * 0.55, H * 0.65, W * 0.7, H)
        ctx.line_to(W * 0.6, H)
        ctx.curve_to(W * 0.48, H * 0.7, W * 0.4, H * 0.75, W * 0.38, H)
        ctx.close_path()
        ctx.fill()

        # Cottages
        cottages = [
            (W * 0.08, H * 0.35, 120, 100),
            (W * 0.35, H * 0.30, 140, 110),
            (W * 0.65, H * 0.33, 130, 105),
        ]
        for cx, cy, cw, ch in cottages:
            # Wall
            wall_grad = cairo.LinearGradient(cx, cy, cx, cy + ch)
            wall_grad.add_color_stop_rgb(0, 0.55, 0.40, 0.25)
            wall_grad.add_color_stop_rgb(1, 0.42, 0.30, 0.18)
            ctx.set_source(wall_grad)
            ctx.rectangle(cx, cy, cw, ch)
            ctx.fill()

            # Roof
            ctx.set_source_rgb(0.45, 0.20, 0.10)
            ctx.move_to(cx - 10, cy)
            ctx.line_to(cx + cw / 2, cy - 50)
            ctx.line_to(cx + cw + 10, cy)
            ctx.close_path()
            ctx.fill()
            # Roof highlight
            ctx.set_source_rgba(0.55, 0.28, 0.12, 0.5)
            ctx.move_to(cx - 5, cy)
            ctx.line_to(cx + cw / 2, cy - 45)
            ctx.line_to(cx + cw / 2, cy)
            ctx.close_path()
            ctx.fill()

            # Window (warm glow)
            win_x = cx + cw * 0.3
            win_y = cy + ch * 0.3
            win_w, win_h = 22, 22
            # Glow around window
            glow = cairo.RadialGradient(win_x + win_w / 2, win_y + win_h / 2, 5,
                                        win_x + win_w / 2, win_y + win_h / 2, 50)
            glow.add_color_stop_rgba(0, 1.0, 0.85, 0.4, 0.3)
            glow.add_color_stop_rgba(1, 1.0, 0.7, 0.2, 0)
            ctx.set_source(glow)
            ctx.paint()
            # Window frame
            ctx.set_source_rgb(0.95, 0.85, 0.45)
            ctx.rectangle(win_x, win_y, win_w, win_h)
            ctx.fill()
            ctx.set_source_rgb(0.35, 0.22, 0.10)
            ctx.set_line_width(2)
            ctx.rectangle(win_x, win_y, win_w, win_h)
            ctx.stroke()
            ctx.move_to(win_x + win_w / 2, win_y)
            ctx.line_to(win_x + win_w / 2, win_y + win_h)
            ctx.stroke()

            # Door
            door_x = cx + cw * 0.6
            door_y = cy + ch * 0.45
            ctx.set_source_rgb(0.30, 0.18, 0.08)
            ctx.rectangle(door_x, door_y, 20, ch * 0.55)
            ctx.fill()

            # Chimney
            chim_x = cx + cw * 0.7
            ctx.set_source_rgb(0.40, 0.30, 0.25)
            ctx.rectangle(chim_x, cy - 40, 14, 45)
            ctx.fill()

            # Smoke
            ctx.set_line_width(2)
            for i in range(5):
                smoke_y = cy - 45 - i * 18
                ctx.set_source_rgba(0.6, 0.6, 0.6, 0.3 - i * 0.05)
                ctx.arc(chim_x + 7 + i * 3 * ((-1) ** i), smoke_y, 6 + i * 2, 0, 2 * math.pi)
                ctx.fill()

        # Stars in sky
        import hashlib
        seed = int(hashlib.md5(b"village").hexdigest()[:8], 16)
        for i in range(30):
            sx = ((seed * (i + 1) * 7) % W)
            sy = ((seed * (i + 1) * 13) % int(H * 0.3))
            brightness = 0.5 + (i % 5) * 0.1
            ctx.set_source_rgba(1, 1, brightness, 0.6)
            ctx.arc(sx, sy, 1.2, 0, 2 * math.pi)
            ctx.fill()

    def _draw_night_scene(self, ctx, W, H):
        """Draw a dark sky with stars, moon, and silhouette landscape."""
        # Dark sky
        sky = cairo.LinearGradient(0, 0, 0, H)
        sky.add_color_stop_rgb(0, 0.02, 0.02, 0.08)
        sky.add_color_stop_rgb(0.4, 0.04, 0.04, 0.14)
        sky.add_color_stop_rgb(0.7, 0.06, 0.06, 0.16)
        sky.add_color_stop_rgb(1, 0.03, 0.03, 0.06)
        ctx.set_source(sky)
        ctx.paint()

        # Moon
        moon_x, moon_y = W * 0.75, H * 0.15
        # Moon glow
        moon_glow = cairo.RadialGradient(moon_x, moon_y, 20, moon_x, moon_y, 120)
        moon_glow.add_color_stop_rgba(0, 0.7, 0.75, 0.9, 0.3)
        moon_glow.add_color_stop_rgba(0.5, 0.4, 0.45, 0.7, 0.1)
        moon_glow.add_color_stop_rgba(1, 0.1, 0.1, 0.3, 0)
        ctx.set_source(moon_glow)
        ctx.paint()
        # Moon body
        moon_grad = cairo.RadialGradient(moon_x - 5, moon_y - 5, 5, moon_x, moon_y, 30)
        moon_grad.add_color_stop_rgb(0, 0.95, 0.95, 1.0)
        moon_grad.add_color_stop_rgb(1, 0.80, 0.82, 0.90)
        ctx.set_source(moon_grad)
        ctx.arc(moon_x, moon_y, 30, 0, 2 * math.pi)
        ctx.fill()
        # Craters
        ctx.set_source_rgba(0.7, 0.72, 0.80, 0.3)
        ctx.arc(moon_x - 8, moon_y - 5, 5, 0, 2 * math.pi)
        ctx.fill()
        ctx.arc(moon_x + 10, moon_y + 8, 3, 0, 2 * math.pi)
        ctx.fill()
        ctx.arc(moon_x + 3, moon_y - 12, 4, 0, 2 * math.pi)
        ctx.fill()

        # Stars
        import hashlib
        seed = int(hashlib.md5(b"nightsky").hexdigest()[:8], 16)
        for i in range(80):
            sx = ((seed * (i + 1) * 7) % W)
            sy = ((seed * (i + 1) * 13) % int(H * 0.6))
            size = 0.8 + (i % 4) * 0.4
            brightness = 0.5 + (i % 6) * 0.08
            ctx.set_source_rgba(1, 1, brightness, 0.7)
            ctx.arc(sx, sy, size, 0, 2 * math.pi)
            ctx.fill()
            # Twinkle cross on brightest stars
            if i % 7 == 0:
                ctx.set_source_rgba(1, 1, 1, 0.4)
                ctx.set_line_width(0.5)
                ctx.move_to(sx - 4, sy)
                ctx.line_to(sx + 4, sy)
                ctx.stroke()
                ctx.move_to(sx, sy - 4)
                ctx.line_to(sx, sy + 4)
                ctx.stroke()

        # Silhouette hills
        ctx.set_source_rgb(0.03, 0.03, 0.06)
        ctx.move_to(0, H * 0.7)
        ctx.curve_to(W * 0.15, H * 0.55, W * 0.25, H * 0.62, W * 0.4, H * 0.58)
        ctx.curve_to(W * 0.55, H * 0.54, W * 0.7, H * 0.60, W * 0.85, H * 0.56)
        ctx.curve_to(W * 0.95, H * 0.53, W, H * 0.58, W, H * 0.65)
        ctx.line_to(W, H)
        ctx.line_to(0, H)
        ctx.close_path()
        ctx.fill()

        # Silhouette trees on hills
        tree_positions = [W * 0.1, W * 0.2, W * 0.38, W * 0.55, W * 0.72, W * 0.88]
        for tx in tree_positions:
            ty = H * 0.58 + abs(math.sin(tx * 0.01)) * 30
            ctx.set_source_rgb(0.02, 0.02, 0.05)
            # Trunk
            ctx.rectangle(tx - 3, ty - 40, 6, 45)
            ctx.fill()
            # Canopy
            ctx.move_to(tx, ty - 70)
            ctx.line_to(tx - 20, ty - 30)
            ctx.line_to(tx + 20, ty - 30)
            ctx.close_path()
            ctx.fill()
            ctx.move_to(tx, ty - 55)
            ctx.line_to(tx - 16, ty - 20)
            ctx.line_to(tx + 16, ty - 20)
            ctx.close_path()
            ctx.fill()

        # Foreground ground with subtle grass
        ground = cairo.LinearGradient(0, H * 0.7, 0, H)
        ground.add_color_stop_rgb(0, 0.03, 0.05, 0.03)
        ground.add_color_stop_rgb(1, 0.02, 0.03, 0.02)
        ctx.set_source(ground)
        ctx.rectangle(0, H * 0.7, W, H * 0.3)
        ctx.fill()

    def _draw_market_scene(self, ctx, W, H):
        """Draw a market scene with stalls, awnings, and crates."""
        # Daytime sky
        sky = cairo.LinearGradient(0, 0, 0, H * 0.5)
        sky.add_color_stop_rgb(0, 0.35, 0.55, 0.85)
        sky.add_color_stop_rgb(0.7, 0.55, 0.70, 0.90)
        sky.add_color_stop_rgb(1, 0.70, 0.78, 0.88)
        ctx.set_source(sky)
        ctx.rectangle(0, 0, W, H * 0.5)
        ctx.fill()

        # Ground (cobblestone)
        ground = cairo.LinearGradient(0, H * 0.45, 0, H)
        ground.add_color_stop_rgb(0, 0.45, 0.40, 0.35)
        ground.add_color_stop_rgb(1, 0.35, 0.30, 0.25)
        ctx.set_source(ground)
        ctx.rectangle(0, H * 0.45, W, H * 0.55)
        ctx.fill()

        # Cobblestone pattern
        ctx.set_line_width(0.8)
        for y in range(int(H * 0.45), H, 18):
            offset = 10 if ((y - int(H * 0.45)) // 18) % 2 else 0
            for x in range(-10 + offset, W + 10, 22):
                ctx.set_source_rgba(0.38, 0.33, 0.28, 0.4)
                ctx.save()
                ctx.translate(x + 10, y + 8)
                ctx.scale(10, 7)
                ctx.arc(0, 0, 1, 0, 2 * math.pi)
                ctx.restore()
                ctx.stroke()

        # Market stalls
        stall_colors = [
            (0.75, 0.20, 0.15),  # Red awning
            (0.20, 0.55, 0.20),  # Green awning
            (0.20, 0.30, 0.70),  # Blue awning
            (0.70, 0.55, 0.15),  # Yellow awning
        ]
        stall_positions = [W * 0.05, W * 0.28, W * 0.52, W * 0.76]
        stall_w = W * 0.20

        for i, (sx, (ar, ag, ab)) in enumerate(zip(stall_positions, stall_colors)):
            table_y = H * 0.52
            table_h = H * 0.12

            # Table/counter
            ctx.set_source_rgb(0.45, 0.30, 0.15)
            ctx.rectangle(sx, table_y, stall_w, table_h)
            ctx.fill()

            # Awning (striped)
            awning_top = table_y - 70
            for stripe in range(6):
                stripe_x = sx + stripe * (stall_w / 6)
                if stripe % 2 == 0:
                    ctx.set_source_rgb(ar, ag, ab)
                else:
                    ctx.set_source_rgb(min(ar + 0.2, 1), min(ag + 0.2, 1), min(ab + 0.2, 1))
                ctx.move_to(stripe_x, awning_top)
                ctx.line_to(stripe_x + stall_w / 6, awning_top)
                ctx.line_to(stripe_x + stall_w / 6 + 5, table_y - 5)
                ctx.line_to(stripe_x + 5, table_y - 5)
                ctx.close_path()
                ctx.fill()

            # Poles
            ctx.set_source_rgb(0.35, 0.22, 0.10)
            ctx.rectangle(sx + 2, awning_top, 4, table_y + table_h - awning_top)
            ctx.fill()
            ctx.rectangle(sx + stall_w - 6, awning_top, 4, table_y + table_h - awning_top)
            ctx.fill()

            # Items on counter (simple colored circles/rectangles)
            for j in range(4):
                ix = sx + 12 + j * (stall_w / 5)
                iy = table_y + 5
                ctx.set_source_rgb(0.6 + j * 0.1, 0.4 + (j % 2) * 0.2, 0.2)
                ctx.arc(ix, iy, 6, 0, 2 * math.pi)
                ctx.fill()

        # Crates in foreground
        crate_positions = [(W * 0.15, H * 0.75), (W * 0.45, H * 0.78), (W * 0.8, H * 0.72)]
        for crx, cry in crate_positions:
            crate_w, crate_h = 30, 25
            ctx.set_source_rgb(0.50, 0.35, 0.18)
            ctx.rectangle(crx, cry, crate_w, crate_h)
            ctx.fill()
            # Crate lines
            ctx.set_source_rgb(0.38, 0.25, 0.12)
            ctx.set_line_width(1.5)
            ctx.move_to(crx, cry + crate_h / 2)
            ctx.line_to(crx + crate_w, cry + crate_h / 2)
            ctx.stroke()
            ctx.move_to(crx + crate_w / 2, cry)
            ctx.line_to(crx + crate_w / 2, cry + crate_h)
            ctx.stroke()

        # Warm sunlight overlay
        sun_glow = cairo.RadialGradient(W * 0.8, H * 0.1, 30, W * 0.8, H * 0.1, 400)
        sun_glow.add_color_stop_rgba(0, 1.0, 0.95, 0.7, 0.15)
        sun_glow.add_color_stop_rgba(1, 1.0, 0.85, 0.5, 0)
        ctx.set_source(sun_glow)
        ctx.paint()

    def _draw_road_scene(self, ctx, W, H):
        """Draw a path through countryside with rolling hills."""
        # Sky gradient
        sky = cairo.LinearGradient(0, 0, 0, H * 0.55)
        sky.add_color_stop_rgb(0, 0.40, 0.60, 0.90)
        sky.add_color_stop_rgb(0.6, 0.55, 0.72, 0.92)
        sky.add_color_stop_rgb(1, 0.70, 0.80, 0.85)
        ctx.set_source(sky)
        ctx.rectangle(0, 0, W, H * 0.55)
        ctx.fill()

        # Clouds
        cloud_positions = [(W * 0.15, H * 0.1), (W * 0.5, H * 0.08), (W * 0.8, H * 0.15)]
        for clx, cly in cloud_positions:
            ctx.set_source_rgba(1, 1, 1, 0.6)
            for dx, dy, r in [(-15, 0, 18), (0, -5, 22), (15, 0, 18), (25, 5, 14)]:
                ctx.arc(clx + dx, cly + dy, r, 0, 2 * math.pi)
                ctx.fill()

        # Far hills (distant, lighter green)
        ctx.set_source_rgb(0.45, 0.60, 0.40)
        ctx.move_to(0, H * 0.45)
        ctx.curve_to(W * 0.1, H * 0.35, W * 0.2, H * 0.40, W * 0.35, H * 0.38)
        ctx.curve_to(W * 0.5, H * 0.35, W * 0.6, H * 0.42, W * 0.75, H * 0.37)
        ctx.curve_to(W * 0.9, H * 0.33, W * 0.95, H * 0.40, W, H * 0.42)
        ctx.line_to(W, H * 0.55)
        ctx.line_to(0, H * 0.55)
        ctx.close_path()
        ctx.fill()

        # Near hills (closer, darker green)
        ground = cairo.LinearGradient(0, H * 0.45, 0, H)
        ground.add_color_stop_rgb(0, 0.30, 0.50, 0.22)
        ground.add_color_stop_rgb(0.5, 0.25, 0.42, 0.18)
        ground.add_color_stop_rgb(1, 0.18, 0.32, 0.12)
        ctx.set_source(ground)
        ctx.move_to(0, H * 0.5)
        ctx.curve_to(W * 0.15, H * 0.45, W * 0.3, H * 0.52, W * 0.5, H * 0.48)
        ctx.curve_to(W * 0.7, H * 0.44, W * 0.85, H * 0.50, W, H * 0.47)
        ctx.line_to(W, H)
        ctx.line_to(0, H)
        ctx.close_path()
        ctx.fill()

        # Dirt road (perspective path)
        road_grad = cairo.LinearGradient(0, H * 0.5, 0, H)
        road_grad.add_color_stop_rgb(0, 0.55, 0.45, 0.30)
        road_grad.add_color_stop_rgb(1, 0.40, 0.32, 0.20)
        ctx.set_source(road_grad)
        # Road narrows into distance
        ctx.move_to(W * 0.35, H)
        ctx.curve_to(W * 0.38, H * 0.75, W * 0.42, H * 0.6, W * 0.48, H * 0.48)
        ctx.line_to(W * 0.52, H * 0.48)
        ctx.curve_to(W * 0.58, H * 0.6, W * 0.62, H * 0.75, W * 0.65, H)
        ctx.close_path()
        ctx.fill()

        # Road edge lines
        ctx.set_source_rgba(0.35, 0.28, 0.18, 0.5)
        ctx.set_line_width(2)
        ctx.move_to(W * 0.35, H)
        ctx.curve_to(W * 0.38, H * 0.75, W * 0.42, H * 0.6, W * 0.48, H * 0.48)
        ctx.stroke()
        ctx.move_to(W * 0.65, H)
        ctx.curve_to(W * 0.62, H * 0.75, W * 0.58, H * 0.6, W * 0.52, H * 0.48)
        ctx.stroke()

        # Grass tufts along road
        ctx.set_line_width(1.5)
        for gx in range(0, W, 25):
            for gy in range(int(H * 0.55), H, 30):
                ctx.set_source_rgba(0.28, 0.55, 0.20, 0.3)
                ctx.move_to(gx, gy)
                ctx.curve_to(gx - 2, gy - 8, gx + 1, gy - 10, gx, gy - 12)
                ctx.stroke()

        # Distant trees along road
        for tx, s in [(W * 0.42, 0.5), (W * 0.55, 0.45), (W * 0.38, 0.55),
                      (W * 0.58, 0.4), (W * 0.15, 0.7), (W * 0.85, 0.65)]:
            ty = H * 0.48 + (1 - s) * 40
            ctx.set_source_rgb(0.15, 0.35, 0.12)
            ctx.arc(tx, ty - 12 * s, 10 * s, 0, 2 * math.pi)
            ctx.fill()
            ctx.set_source_rgb(0.25, 0.15, 0.05)
            ctx.rectangle(tx - 2 * s, ty - 5 * s, 4 * s, 12 * s)
            ctx.fill()

        # Sun glow
        sun_glow = cairo.RadialGradient(W * 0.5, H * 0.35, 10, W * 0.5, H * 0.35, 200)
        sun_glow.add_color_stop_rgba(0, 1.0, 0.95, 0.8, 0.2)
        sun_glow.add_color_stop_rgba(1, 1.0, 0.9, 0.7, 0)
        ctx.set_source(sun_glow)
        ctx.paint()

    def _draw_default_scene(self, ctx, W, H, name):
        """Draw a generic atmospheric scene with the name as text overlay."""
        # Moody gradient background
        bg = cairo.LinearGradient(0, 0, 0, H)
        bg.add_color_stop_rgb(0, 0.10, 0.12, 0.22)
        bg.add_color_stop_rgb(0.4, 0.15, 0.18, 0.28)
        bg.add_color_stop_rgb(0.7, 0.18, 0.15, 0.20)
        bg.add_color_stop_rgb(1, 0.08, 0.08, 0.12)
        ctx.set_source(bg)
        ctx.paint()

        # Subtle ground
        ground = cairo.LinearGradient(0, H * 0.6, 0, H)
        ground.add_color_stop_rgb(0, 0.14, 0.14, 0.16)
        ground.add_color_stop_rgb(1, 0.08, 0.08, 0.10)
        ctx.set_source(ground)
        ctx.rectangle(0, H * 0.6, W, H * 0.4)
        ctx.fill()

        # Atmospheric particles
        import hashlib
        seed = int(hashlib.md5(name.encode("utf-8")).hexdigest()[:8], 16)
        for i in range(40):
            px = (seed * (i + 1) * 7) % W
            py = (seed * (i + 1) * 13) % H
            r = 1 + (i % 3)
            alpha = 0.05 + (i % 5) * 0.02
            ctx.set_source_rgba(0.6, 0.65, 0.8, alpha)
            ctx.arc(px, py, r, 0, 2 * math.pi)
            ctx.fill()

        # Central glow
        center_glow = cairo.RadialGradient(W / 2, H / 2, 30, W / 2, H / 2, 250)
        center_glow.add_color_stop_rgba(0, 0.3, 0.35, 0.5, 0.15)
        center_glow.add_color_stop_rgba(1, 0.1, 0.1, 0.2, 0)
        ctx.set_source(center_glow)
        ctx.paint()

        # Scene name text
        ctx.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(36)
        extents = ctx.text_extents(name)
        tx = (W - extents.width) / 2 - extents.x_bearing
        ty = H / 2 + extents.height / 2

        # Text shadow
        ctx.set_source_rgba(0, 0, 0, 0.5)
        ctx.move_to(tx + 2, ty + 2)
        ctx.show_text(name)

        # Text body
        ctx.set_source_rgba(0.85, 0.85, 0.90, 0.9)
        ctx.move_to(tx, ty)
        ctx.show_text(name)

        # Decorative line under text
        ctx.set_source_rgba(0.6, 0.65, 0.8, 0.4)
        ctx.set_line_width(1.5)
        line_w = min(extents.width + 40, W * 0.6)
        ctx.move_to((W - line_w) / 2, ty + 15)
        ctx.line_to((W + line_w) / 2, ty + 15)
        ctx.stroke()

        # Vignette
        vignette = cairo.RadialGradient(W / 2, H / 2, 150, W / 2, H / 2, 500)
        vignette.add_color_stop_rgba(0, 0, 0, 0, 0)
        vignette.add_color_stop_rgba(1, 0, 0, 0, 0.5)
        ctx.set_source(vignette)
        ctx.paint()

    # ===== Scene element generation (characters / objects) =====

    def generate_scene_element(self, element_type, name):
        """Generate a Cairo character silhouette or object icon."""
        if element_type == "portrait":
            W, H = 384, 512
        else:
            W, H = 256, 256

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
        ctx = cairo.Context(surface)

        # Transparent background
        ctx.set_source_rgba(0, 0, 0, 0)
        ctx.paint()

        if element_type == "portrait":
            self._draw_character_silhouette(ctx, W, H, name)
        else:
            self._draw_object_icon(ctx, W, H, name)

        if element_type == "portrait":
            out_dir = os.path.join(self.base_dir, "static", "portraits", "pixel")
        else:
            out_dir = os.path.join(self.base_dir, "static", "illustrations", "pixel")
        os.makedirs(out_dir, exist_ok=True)
        safe_name = name.replace(" ", "_").lower()
        filepath = os.path.join(out_dir, f"{element_type}_{safe_name}.png")
        surface.write_to_png(filepath)
        return filepath

    def _draw_character_silhouette(self, ctx, W, H, name):
        """Draw a character silhouette with color tint based on name hash."""
        import hashlib
        name_hash = int(hashlib.md5(name.encode("utf-8")).hexdigest()[:8], 16)
        # Generate a hue from name hash
        hue = (name_hash % 360) / 360.0
        # Convert HSV to RGB (saturation=0.5, value=0.6)
        s, v = 0.5, 0.6
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
        r += m
        g += m
        b += m

        cx, cy = W / 2, H / 2

        # Full body silhouette gradient
        body_grad = cairo.LinearGradient(cx, 0, cx, H)
        body_grad.add_color_stop_rgba(0, r * 0.8, g * 0.8, b * 0.8, 0.85)
        body_grad.add_color_stop_rgba(0.5, r * 0.5, g * 0.5, b * 0.5, 0.90)
        body_grad.add_color_stop_rgba(1, r * 0.3, g * 0.3, b * 0.3, 0.85)

        # Head
        head_y = H * 0.12
        head_r = W * 0.12
        ctx.set_source(body_grad)
        ctx.arc(cx, head_y + head_r, head_r, 0, 2 * math.pi)
        ctx.fill()

        # Neck
        neck_w = W * 0.06
        ctx.rectangle(cx - neck_w, head_y + head_r * 2 - 5, neck_w * 2, H * 0.04)
        ctx.fill()

        # Torso (trapezoid)
        torso_top = head_y + head_r * 2 + H * 0.03
        torso_bottom = H * 0.55
        shoulder_w = W * 0.28
        waist_w = W * 0.18
        ctx.move_to(cx - shoulder_w, torso_top)
        ctx.line_to(cx + shoulder_w, torso_top)
        ctx.line_to(cx + waist_w, torso_bottom)
        ctx.line_to(cx - waist_w, torso_bottom)
        ctx.close_path()
        ctx.fill()

        # Arms
        arm_w = W * 0.06
        # Left arm
        ctx.move_to(cx - shoulder_w, torso_top + 5)
        ctx.line_to(cx - shoulder_w - arm_w, torso_top + 5)
        ctx.line_to(cx - shoulder_w - arm_w * 1.5, torso_bottom + 20)
        ctx.line_to(cx - shoulder_w - arm_w * 0.5, torso_bottom + 20)
        ctx.close_path()
        ctx.fill()
        # Right arm
        ctx.move_to(cx + shoulder_w, torso_top + 5)
        ctx.line_to(cx + shoulder_w + arm_w, torso_top + 5)
        ctx.line_to(cx + shoulder_w + arm_w * 1.5, torso_bottom + 20)
        ctx.line_to(cx + shoulder_w + arm_w * 0.5, torso_bottom + 20)
        ctx.close_path()
        ctx.fill()

        # Legs
        leg_top = torso_bottom
        leg_bottom = H * 0.88
        leg_w = W * 0.09
        gap = W * 0.02
        # Left leg
        ctx.move_to(cx - waist_w, leg_top)
        ctx.line_to(cx - gap, leg_top)
        ctx.line_to(cx - gap - leg_w * 0.3, leg_bottom)
        ctx.line_to(cx - waist_w - leg_w * 0.2, leg_bottom)
        ctx.close_path()
        ctx.fill()
        # Right leg
        ctx.move_to(cx + gap, leg_top)
        ctx.line_to(cx + waist_w, leg_top)
        ctx.line_to(cx + waist_w + leg_w * 0.2, leg_bottom)
        ctx.line_to(cx + gap + leg_w * 0.3, leg_bottom)
        ctx.close_path()
        ctx.fill()

        # Feet
        ctx.set_source_rgba(r * 0.3, g * 0.3, b * 0.3, 0.85)
        foot_w = W * 0.08
        foot_h = H * 0.03
        ctx.save()
        ctx.translate(cx - gap - leg_w * 0.3 - foot_w * 0.3, leg_bottom)
        ctx.scale(foot_w, foot_h)
        ctx.arc(1, 0, 1, 0, math.pi)
        ctx.restore()
        ctx.fill()
        ctx.save()
        ctx.translate(cx + gap + leg_w * 0.3 + foot_w * 0.3, leg_bottom)
        ctx.scale(foot_w, foot_h)
        ctx.arc(1, 0, 1, 0, math.pi)
        ctx.restore()
        ctx.fill()

        # Subtle rim light on one side
        rim = cairo.LinearGradient(cx + W * 0.2, 0, cx + W * 0.35, 0)
        rim.add_color_stop_rgba(0, r, g, b, 0.2)
        rim.add_color_stop_rgba(1, r, g, b, 0)
        ctx.set_source(rim)
        ctx.rectangle(0, 0, W, H)
        ctx.fill()

        # Name label at bottom
        ctx.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(20)
        extents = ctx.text_extents(name)
        tx = (W - extents.width) / 2 - extents.x_bearing
        ty = H * 0.95

        # Label background
        pad = 6
        ctx.set_source_rgba(0, 0, 0, 0.6)
        label_w = extents.width + pad * 2
        label_h = extents.height + pad * 2
        label_x = (W - label_w) / 2
        label_y = ty - extents.height - pad
        # Rounded rect
        radius = 4
        ctx.move_to(label_x + radius, label_y)
        ctx.line_to(label_x + label_w - radius, label_y)
        ctx.arc(label_x + label_w - radius, label_y + radius, radius, -math.pi / 2, 0)
        ctx.line_to(label_x + label_w, label_y + label_h - radius)
        ctx.arc(label_x + label_w - radius, label_y + label_h - radius, radius, 0, math.pi / 2)
        ctx.line_to(label_x + radius, label_y + label_h)
        ctx.arc(label_x + radius, label_y + label_h - radius, radius, math.pi / 2, math.pi)
        ctx.line_to(label_x, label_y + radius)
        ctx.arc(label_x + radius, label_y + radius, radius, math.pi, 3 * math.pi / 2)
        ctx.close_path()
        ctx.fill()

        # Text
        ctx.set_source_rgba(1, 1, 1, 0.95)
        ctx.move_to(tx, ty)
        ctx.show_text(name)

    def _draw_object_icon(self, ctx, W, H, name):
        """Draw a simple object icon based on name keywords."""
        cx, cy = W / 2, H / 2
        name_lower = name.lower()

        if any(k in name_lower for k in ["chest", "상자", "보물"]):
            self._draw_chest_icon(ctx, cx, cy, W, H)
        elif any(k in name_lower for k in ["key", "열쇠", "키"]):
            self._draw_key_icon(ctx, cx, cy, W, H)
        elif any(k in name_lower for k in ["potion", "물약", "포션"]):
            self._draw_potion_icon(ctx, cx, cy, W, H)
        elif any(k in name_lower for k in ["scroll", "두루마리", "스크롤"]):
            self._draw_scroll_icon(ctx, cx, cy, W, H)
        elif any(k in name_lower for k in ["sword", "검", "칼", "blade"]):
            self._draw_sword_icon(ctx, cx, cy, W, H)
        elif any(k in name_lower for k in ["shield", "방패"]):
            self._draw_shield_icon(ctx, cx, cy, W, H)
        else:
            self._draw_orb_icon(ctx, cx, cy, W, H, name)

        # Name label at bottom
        ctx.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(14)
        extents = ctx.text_extents(name)
        tx = (W - extents.width) / 2 - extents.x_bearing
        ty = H * 0.92

        # Shadow
        ctx.set_source_rgba(0, 0, 0, 0.7)
        ctx.move_to(tx + 1, ty + 1)
        ctx.show_text(name)
        # Text
        ctx.set_source_rgba(1, 1, 1, 0.9)
        ctx.move_to(tx, ty)
        ctx.show_text(name)

    def _draw_chest_icon(self, ctx, cx, cy, W, H):
        """Draw a treasure chest icon."""
        cw, ch = W * 0.5, H * 0.3
        # Body
        body_grad = cairo.LinearGradient(cx - cw / 2, cy, cx - cw / 2, cy + ch)
        body_grad.add_color_stop_rgb(0, 0.58, 0.42, 0.12)
        body_grad.add_color_stop_rgb(1, 0.38, 0.26, 0.08)
        ctx.set_source(body_grad)
        ctx.rectangle(cx - cw / 2, cy, cw, ch)
        ctx.fill()
        # Lid
        lid_grad = cairo.LinearGradient(cx, cy - ch * 0.5, cx, cy)
        lid_grad.add_color_stop_rgb(0, 0.62, 0.48, 0.16)
        lid_grad.add_color_stop_rgb(1, 0.52, 0.38, 0.12)
        ctx.set_source(lid_grad)
        ctx.move_to(cx - cw / 2, cy)
        ctx.curve_to(cx - cw / 2, cy - ch * 0.7, cx + cw / 2, cy - ch * 0.7, cx + cw / 2, cy)
        ctx.close_path()
        ctx.fill()
        # Metal bands
        ctx.set_source_rgb(0.45, 0.35, 0.15)
        ctx.set_line_width(2)
        ctx.move_to(cx, cy - ch * 0.4)
        ctx.line_to(cx, cy + ch)
        ctx.stroke()
        # Lock
        ctx.set_source_rgb(0.75, 0.65, 0.20)
        ctx.arc(cx, cy + 3, 6, 0, 2 * math.pi)
        ctx.fill()
        # Glow
        glow = cairo.RadialGradient(cx, cy, 10, cx, cy, 80)
        glow.add_color_stop_rgba(0, 1.0, 0.85, 0.3, 0.25)
        glow.add_color_stop_rgba(1, 1.0, 0.7, 0.1, 0)
        ctx.set_source(glow)
        ctx.paint()

    def _draw_key_icon(self, ctx, cx, cy, W, H):
        """Draw a key icon."""
        # Key glow
        glow = cairo.RadialGradient(cx, cy, 10, cx, cy, 80)
        glow.add_color_stop_rgba(0, 1.0, 0.85, 0.3, 0.2)
        glow.add_color_stop_rgba(1, 0.8, 0.6, 0.1, 0)
        ctx.set_source(glow)
        ctx.paint()
        # Key body
        ctx.set_source_rgb(0.85, 0.75, 0.25)
        ctx.set_line_width(6)
        # Shaft
        ctx.move_to(cx - W * 0.15, cy)
        ctx.line_to(cx + W * 0.15, cy)
        ctx.stroke()
        # Teeth
        ctx.set_line_width(4)
        for i in range(3):
            tx = cx + W * 0.08 + i * 10
            ctx.move_to(tx, cy)
            ctx.line_to(tx, cy + 12)
            ctx.stroke()
        # Bow (ring)
        ctx.set_line_width(5)
        ctx.arc(cx - W * 0.2, cy, 15, 0, 2 * math.pi)
        ctx.stroke()
        # Highlight
        ctx.set_source_rgba(1, 0.95, 0.5, 0.5)
        ctx.set_line_width(2)
        ctx.arc(cx - W * 0.2, cy - 3, 10, math.pi, 2 * math.pi)
        ctx.stroke()

    def _draw_potion_icon(self, ctx, cx, cy, W, H):
        """Draw a potion bottle icon."""
        # Bottle body (rounded)
        bottle_w = W * 0.2
        bottle_h = H * 0.35
        bottle_top = cy - bottle_h * 0.3

        # Liquid glow
        glow = cairo.RadialGradient(cx, cy + 10, 10, cx, cy + 10, 70)
        glow.add_color_stop_rgba(0, 0.2, 0.8, 0.3, 0.3)
        glow.add_color_stop_rgba(1, 0.1, 0.5, 0.2, 0)
        ctx.set_source(glow)
        ctx.paint()

        # Bottle
        bottle_grad = cairo.LinearGradient(cx - bottle_w, cy, cx + bottle_w, cy)
        bottle_grad.add_color_stop_rgba(0, 0.15, 0.60, 0.25, 0.8)
        bottle_grad.add_color_stop_rgba(0.3, 0.20, 0.75, 0.30, 0.85)
        bottle_grad.add_color_stop_rgba(0.7, 0.15, 0.65, 0.25, 0.85)
        bottle_grad.add_color_stop_rgba(1, 0.10, 0.50, 0.20, 0.8)
        ctx.set_source(bottle_grad)
        # Round bottom
        ctx.move_to(cx - bottle_w, bottle_top + bottle_h * 0.3)
        ctx.curve_to(cx - bottle_w, bottle_top + bottle_h,
                     cx + bottle_w, bottle_top + bottle_h,
                     cx + bottle_w, bottle_top + bottle_h * 0.3)
        # Neck
        ctx.line_to(cx + bottle_w * 0.35, bottle_top + bottle_h * 0.3)
        ctx.line_to(cx + bottle_w * 0.35, bottle_top)
        ctx.line_to(cx - bottle_w * 0.35, bottle_top)
        ctx.line_to(cx - bottle_w * 0.35, bottle_top + bottle_h * 0.3)
        ctx.close_path()
        ctx.fill()

        # Cork
        ctx.set_source_rgb(0.55, 0.38, 0.18)
        ctx.rectangle(cx - bottle_w * 0.3, bottle_top - 8, bottle_w * 0.6, 10)
        ctx.fill()

        # Highlight
        ctx.set_source_rgba(1, 1, 1, 0.25)
        ctx.move_to(cx - bottle_w * 0.5, bottle_top + bottle_h * 0.35)
        ctx.curve_to(cx - bottle_w * 0.5, bottle_top + bottle_h * 0.8,
                     cx - bottle_w * 0.1, bottle_top + bottle_h * 0.8,
                     cx - bottle_w * 0.1, bottle_top + bottle_h * 0.35)
        ctx.close_path()
        ctx.fill()

    def _draw_scroll_icon(self, ctx, cx, cy, W, H):
        """Draw a scroll icon."""
        scroll_w = W * 0.35
        scroll_h = H * 0.4
        sx = cx - scroll_w / 2
        sy = cy - scroll_h / 2

        # Parchment body
        parch = cairo.LinearGradient(sx, sy, sx + scroll_w, sy + scroll_h)
        parch.add_color_stop_rgb(0, 0.90, 0.82, 0.65)
        parch.add_color_stop_rgb(0.5, 0.95, 0.88, 0.72)
        parch.add_color_stop_rgb(1, 0.85, 0.78, 0.60)
        ctx.set_source(parch)
        ctx.rectangle(sx + 10, sy + 8, scroll_w - 20, scroll_h - 16)
        ctx.fill()

        # Top roll
        roll_grad = cairo.LinearGradient(sx, sy, sx, sy + 16)
        roll_grad.add_color_stop_rgb(0, 0.80, 0.72, 0.55)
        roll_grad.add_color_stop_rgb(0.5, 0.92, 0.85, 0.68)
        roll_grad.add_color_stop_rgb(1, 0.82, 0.74, 0.56)
        ctx.set_source(roll_grad)
        ctx.save()
        ctx.translate(cx, sy + 8)
        ctx.scale(scroll_w / 2, 8)
        ctx.arc(0, 0, 1, 0, 2 * math.pi)
        ctx.restore()
        ctx.fill()

        # Bottom roll
        ctx.set_source(roll_grad)
        ctx.save()
        ctx.translate(cx, sy + scroll_h - 8)
        ctx.scale(scroll_w / 2, 8)
        ctx.arc(0, 0, 1, 0, 2 * math.pi)
        ctx.restore()
        ctx.fill()

        # Text lines
        ctx.set_source_rgba(0.35, 0.28, 0.15, 0.5)
        ctx.set_line_width(1.5)
        for i in range(5):
            ly = sy + 22 + i * 14
            lw = scroll_w * (0.5 + (i % 3) * 0.1)
            ctx.move_to(cx - lw / 2, ly)
            ctx.line_to(cx + lw / 2, ly)
            ctx.stroke()

        # Seal/ribbon
        ctx.set_source_rgb(0.75, 0.15, 0.10)
        ctx.arc(cx, sy + scroll_h + 5, 8, 0, 2 * math.pi)
        ctx.fill()

    def _draw_sword_icon(self, ctx, cx, cy, W, H):
        """Draw a sword icon."""
        # Glow
        glow = cairo.RadialGradient(cx, cy, 10, cx, cy, 80)
        glow.add_color_stop_rgba(0, 0.7, 0.75, 0.9, 0.2)
        glow.add_color_stop_rgba(1, 0.4, 0.45, 0.7, 0)
        ctx.set_source(glow)
        ctx.paint()

        # Blade
        blade_grad = cairo.LinearGradient(cx - 8, cy, cx + 8, cy)
        blade_grad.add_color_stop_rgb(0, 0.70, 0.72, 0.78)
        blade_grad.add_color_stop_rgb(0.3, 0.90, 0.92, 0.96)
        blade_grad.add_color_stop_rgb(0.7, 0.85, 0.87, 0.92)
        blade_grad.add_color_stop_rgb(1, 0.65, 0.67, 0.72)
        ctx.set_source(blade_grad)
        ctx.move_to(cx, cy - H * 0.35)  # Tip
        ctx.line_to(cx - 8, cy + H * 0.05)
        ctx.line_to(cx + 8, cy + H * 0.05)
        ctx.close_path()
        ctx.fill()

        # Guard
        ctx.set_source_rgb(0.55, 0.45, 0.15)
        ctx.rectangle(cx - 25, cy + H * 0.05, 50, 8)
        ctx.fill()

        # Grip
        grip_grad = cairo.LinearGradient(cx - 5, cy + H * 0.05, cx + 5, cy + H * 0.05)
        grip_grad.add_color_stop_rgb(0, 0.35, 0.20, 0.08)
        grip_grad.add_color_stop_rgb(0.5, 0.45, 0.28, 0.12)
        grip_grad.add_color_stop_rgb(1, 0.30, 0.18, 0.06)
        ctx.set_source(grip_grad)
        ctx.rectangle(cx - 5, cy + H * 0.06, 10, H * 0.15)
        ctx.fill()

        # Pommel
        ctx.set_source_rgb(0.65, 0.55, 0.20)
        ctx.arc(cx, cy + H * 0.22, 7, 0, 2 * math.pi)
        ctx.fill()

        # Blade highlight
        ctx.set_source_rgba(1, 1, 1, 0.3)
        ctx.set_line_width(1)
        ctx.move_to(cx - 2, cy - H * 0.3)
        ctx.line_to(cx - 5, cy + H * 0.04)
        ctx.stroke()

    def _draw_shield_icon(self, ctx, cx, cy, W, H):
        """Draw a shield icon."""
        # Shield shape
        sw, sh = W * 0.35, H * 0.4
        shield_grad = cairo.LinearGradient(cx - sw, cy - sh / 2, cx + sw, cy + sh / 2)
        shield_grad.add_color_stop_rgb(0, 0.20, 0.30, 0.55)
        shield_grad.add_color_stop_rgb(0.5, 0.28, 0.40, 0.65)
        shield_grad.add_color_stop_rgb(1, 0.15, 0.25, 0.48)
        ctx.set_source(shield_grad)
        ctx.move_to(cx, cy - sh / 2)
        ctx.curve_to(cx + sw, cy - sh / 2, cx + sw, cy, cx + sw * 0.7, cy + sh * 0.3)
        ctx.line_to(cx, cy + sh / 2)
        ctx.line_to(cx - sw * 0.7, cy + sh * 0.3)
        ctx.curve_to(cx - sw, cy, cx - sw, cy - sh / 2, cx, cy - sh / 2)
        ctx.close_path()
        ctx.fill()

        # Border
        ctx.set_source_rgb(0.55, 0.50, 0.20)
        ctx.set_line_width(3)
        ctx.move_to(cx, cy - sh / 2)
        ctx.curve_to(cx + sw, cy - sh / 2, cx + sw, cy, cx + sw * 0.7, cy + sh * 0.3)
        ctx.line_to(cx, cy + sh / 2)
        ctx.line_to(cx - sw * 0.7, cy + sh * 0.3)
        ctx.curve_to(cx - sw, cy, cx - sw, cy - sh / 2, cx, cy - sh / 2)
        ctx.close_path()
        ctx.stroke()

        # Central emblem (cross)
        ctx.set_source_rgb(0.65, 0.60, 0.25)
        ctx.set_line_width(4)
        ctx.move_to(cx, cy - sh * 0.25)
        ctx.line_to(cx, cy + sh * 0.15)
        ctx.stroke()
        ctx.move_to(cx - sw * 0.2, cy - sh * 0.05)
        ctx.line_to(cx + sw * 0.2, cy - sh * 0.05)
        ctx.stroke()

        # Highlight
        ctx.set_source_rgba(1, 1, 1, 0.15)
        ctx.move_to(cx, cy - sh / 2)
        ctx.curve_to(cx - sw * 0.5, cy - sh / 2, cx - sw * 0.5, cy, cx - sw * 0.3, cy + sh * 0.1)
        ctx.line_to(cx, cy + sh * 0.1)
        ctx.line_to(cx, cy - sh / 2)
        ctx.close_path()
        ctx.fill()

    def _draw_orb_icon(self, ctx, cx, cy, W, H, name):
        """Draw a generic glowing orb with name."""
        import hashlib
        name_hash = int(hashlib.md5(name.encode("utf-8")).hexdigest()[:8], 16)
        hue = (name_hash % 360) / 360.0
        # HSV to RGB
        s, v = 0.7, 0.8
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
        r += m
        g += m
        b += m

        orb_r = min(W, H) * 0.25

        # Outer glow
        glow = cairo.RadialGradient(cx, cy, orb_r * 0.5, cx, cy, orb_r * 2.5)
        glow.add_color_stop_rgba(0, r, g, b, 0.3)
        glow.add_color_stop_rgba(0.5, r * 0.5, g * 0.5, b * 0.5, 0.1)
        glow.add_color_stop_rgba(1, r * 0.2, g * 0.2, b * 0.2, 0)
        ctx.set_source(glow)
        ctx.paint()

        # Orb body
        orb = cairo.RadialGradient(cx - orb_r * 0.3, cy - orb_r * 0.3, orb_r * 0.1,
                                   cx, cy, orb_r)
        orb.add_color_stop_rgb(0, min(r + 0.3, 1), min(g + 0.3, 1), min(b + 0.3, 1))
        orb.add_color_stop_rgb(0.7, r, g, b)
        orb.add_color_stop_rgb(1, r * 0.5, g * 0.5, b * 0.5)
        ctx.set_source(orb)
        ctx.arc(cx, cy, orb_r, 0, 2 * math.pi)
        ctx.fill()

        # Specular highlight
        ctx.set_source_rgba(1, 1, 1, 0.4)
        ctx.arc(cx - orb_r * 0.25, cy - orb_r * 0.25, orb_r * 0.25, 0, 2 * math.pi)
        ctx.fill()

        # Small secondary highlight
        ctx.set_source_rgba(1, 1, 1, 0.2)
        ctx.arc(cx + orb_r * 0.3, cy + orb_r * 0.3, orb_r * 0.1, 0, 2 * math.pi)
        ctx.fill()


def generate_world_map():
    """worldbuilding.json 기반 Cairo 헥스 판타지 세계 지도 생성."""
    import math as _math

    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    wb_path = os.path.join(BASE_DIR, "data", "worldbuilding.json")
    if not os.path.exists(wb_path):
        return None

    with open(wb_path, "r", encoding="utf-8") as f:
        wb = json.load(f)

    locations = wb.get("locations", {})
    terrain = wb.get("terrain", {})
    if not locations:
        return None

    # world_pos가 있는 지역만
    placed = {}
    for loc_id, loc_data in locations.items():
        wp = loc_data.get("world_pos")
        if wp:
            placed[loc_id] = {
                "name": loc_data.get("name", loc_id),
                "type": loc_data.get("type", ""),
                "x": wp[0], "y": wp[1],
                "connections": loc_data.get("connections", {}),
            }
    if not placed:
        return None

    # 좌표 범위 (지형 포함)
    all_xs, all_ys = [], []
    for v in placed.values():
        all_xs.append(v["x"]); all_ys.append(v["y"])
    for feat in terrain.get("features", []):
        for c in feat.get("coords", []) + feat.get("path", []):
            all_xs.append(c[0]); all_ys.append(c[1])

    padding = 2
    min_x, max_x = min(all_xs) - padding, max(all_xs) + padding
    min_y, max_y = min(all_ys) - padding, max(all_ys) + padding

    # 헥스 크기
    hex_size = 50  # 헥스 반지름
    hex_w = hex_size * 2
    hex_h = _math.sqrt(3) * hex_size
    cols = max_x - min_x + 1
    rows = max_y - min_y + 1
    img_w = int(cols * hex_w * 0.75 + hex_w * 0.25 + 60)
    img_h = int(rows * hex_h + hex_h * 0.5 + 80)

    # Cairo surface
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, img_w, img_h)
    ctx = cairo.Context(surface)
    ctx.set_antialias(cairo.ANTIALIAS_BEST)

    # ─── 양피지 배경 ───
    ctx.set_source_rgb(0.82, 0.75, 0.60)
    ctx.rectangle(0, 0, img_w, img_h)
    ctx.fill()
    # 질감 노이즈 (간단한 점)
    import random as _rng
    _rng.seed(42)
    for _ in range(img_w * img_h // 40):
        nx = _rng.randint(0, img_w - 1)
        ny = _rng.randint(0, img_h - 1)
        v = _rng.uniform(-0.04, 0.04)
        ctx.set_source_rgba(0.82 + v, 0.75 + v, 0.60 + v, 0.5)
        ctx.rectangle(nx, ny, 2, 2)
        ctx.fill()

    def hex_center(wx, wy):
        """world 좌표 → 픽셀 중심"""
        col = wx - min_x
        row = wy - min_y
        cx = 30 + col * hex_w * 0.75 + hex_size
        cy = 50 + row * hex_h + (hex_h * 0.5 if col % 2 == 1 else 0) + hex_h * 0.5
        return cx, cy

    def draw_hex(ctx, cx, cy, size, fill=None, stroke=None, line_width=1):
        """정육각형 그리기"""
        for i in range(6):
            angle = _math.pi / 180 * (60 * i - 30)
            hx = cx + size * _math.cos(angle)
            hy = cy + size * _math.sin(angle)
            if i == 0:
                ctx.move_to(hx, hy)
            else:
                ctx.line_to(hx, hy)
        ctx.close_path()
        if fill:
            ctx.set_source_rgba(*fill)
            ctx.fill_preserve()
        if stroke:
            ctx.set_source_rgba(*stroke)
            ctx.set_line_width(line_width)
            ctx.stroke()
        else:
            ctx.new_path()

    # ─── 헥스 그리드 (기본 타일) ───
    for gy in range(min_y, max_y + 1):
        for gx in range(min_x, max_x + 1):
            cx, cy = hex_center(gx, gy)
            draw_hex(ctx, cx, cy, hex_size - 1,
                     fill=(0.80, 0.73, 0.58, 0.3),
                     stroke=(0.65, 0.58, 0.45, 0.4), line_width=0.5)

    # ─── 지형 헥스 채우기 ───
    terrain_hex_colors = {
        "forest": (0.30, 0.50, 0.20, 0.6),
        "mountain": (0.55, 0.48, 0.40, 0.7),
        "sea": (0.25, 0.42, 0.65, 0.75),
        "plains": (0.68, 0.72, 0.48, 0.4),
        "swamp": (0.38, 0.45, 0.30, 0.5),
    }

    for feat in terrain.get("features", []):
        ftype = feat.get("type", "")
        hex_color = terrain_hex_colors.get(ftype)

        if ftype == "river" and "path" in feat:
            # 강: 부드러운 곡선
            path_pts = [hex_center(c[0], c[1]) for c in feat["path"]]
            if len(path_pts) >= 2:
                ctx.set_source_rgba(0.22, 0.40, 0.65, 0.8)
                ctx.set_line_width(4)
                ctx.set_line_cap(cairo.LINE_CAP_ROUND)
                ctx.set_line_join(cairo.LINE_JOIN_ROUND)
                ctx.move_to(*path_pts[0])
                for pt in path_pts[1:]:
                    ctx.line_to(*pt)
                ctx.stroke()
                # 강 이름
                mid = path_pts[len(path_pts) // 2]
                ctx.set_source_rgba(0.15, 0.30, 0.55, 0.9)
                ctx.select_font_face("Malgun Gothic", cairo.FONT_SLANT_ITALIC, cairo.FONT_WEIGHT_BOLD)
                ctx.set_font_size(13)
                ctx.move_to(mid[0] + 8, mid[1] - 6)
                ctx.show_text(feat.get("name", ""))

        elif hex_color and "coords" in feat:
            for coord in feat["coords"]:
                cx, cy = hex_center(coord[0], coord[1])
                draw_hex(ctx, cx, cy, hex_size - 1, fill=hex_color)

                # 지형 장식
                if ftype == "forest":
                    for _ in range(3):
                        ox = _rng.uniform(-20, 20)
                        oy = _rng.uniform(-15, 15)
                        sz = _rng.uniform(6, 12)
                        ctx.set_source_rgba(0.22, 0.42, 0.15, 0.7)
                        ctx.move_to(cx + ox, cy + oy - sz)
                        ctx.line_to(cx + ox - sz * 0.5, cy + oy + sz * 0.3)
                        ctx.line_to(cx + ox + sz * 0.5, cy + oy + sz * 0.3)
                        ctx.close_path()
                        ctx.fill()
                        ctx.set_source_rgba(0.40, 0.32, 0.20, 0.6)
                        ctx.rectangle(cx + ox - 1, cy + oy + sz * 0.3, 2, 4)
                        ctx.fill()

                elif ftype == "mountain":
                    for _ in range(2):
                        ox = _rng.uniform(-15, 15)
                        oy = _rng.uniform(-10, 5)
                        mh = _rng.uniform(16, 26)
                        mw = _rng.uniform(12, 20)
                        # 산체
                        ctx.set_source_rgba(0.48, 0.42, 0.35, 0.8)
                        ctx.move_to(cx + ox, cy + oy - mh)
                        ctx.line_to(cx + ox - mw, cy + oy)
                        ctx.line_to(cx + ox + mw, cy + oy)
                        ctx.close_path()
                        ctx.fill()
                        # 눈
                        ctx.set_source_rgba(0.92, 0.92, 0.95, 0.8)
                        ctx.move_to(cx + ox, cy + oy - mh)
                        ctx.line_to(cx + ox - mw * 0.3, cy + oy - mh + 8)
                        ctx.line_to(cx + ox + mw * 0.3, cy + oy - mh + 8)
                        ctx.close_path()
                        ctx.fill()

                elif ftype == "sea":
                    # 물결 패턴
                    for wy in range(int(cy - 18), int(cy + 18), 10):
                        for wx in range(int(cx - 18), int(cx + 18), 14):
                            ctx.set_source_rgba(0.30, 0.48, 0.70, 0.4)
                            ctx.arc(wx, wy, 5, 0, _math.pi)
                            ctx.stroke()

            # 지형 이름
            if feat.get("name") and feat.get("coords"):
                avg_x = sum(c[0] for c in feat["coords"]) / len(feat["coords"])
                avg_y = sum(c[1] for c in feat["coords"]) / len(feat["coords"])
                tx, ty = hex_center(avg_x, avg_y)
                name_colors = {
                    "forest": (0.15, 0.30, 0.10, 0.9),
                    "mountain": (0.35, 0.25, 0.15, 0.9),
                    "sea": (0.10, 0.20, 0.50, 0.95),
                    "plains": (0.40, 0.42, 0.25, 0.8),
                    "swamp": (0.25, 0.32, 0.18, 0.8),
                }
                nc = name_colors.get(ftype, (0.4, 0.4, 0.4, 0.8))
                ctx.select_font_face("Malgun Gothic", cairo.FONT_SLANT_ITALIC, cairo.FONT_WEIGHT_BOLD)
                ctx.set_font_size(14)
                te = ctx.text_extents(feat["name"])
                # 배경
                ctx.set_source_rgba(0.82, 0.75, 0.60, 0.7)
                ctx.rectangle(tx - te.width / 2 - 4, ty - 8, te.width + 8, 18)
                ctx.fill()
                ctx.set_source_rgba(*nc)
                ctx.move_to(tx - te.width / 2, ty + 5)
                ctx.show_text(feat["name"])

    # ─── 도로 연결선 (점선) ───
    drawn_connections = set()
    for loc_id, loc in placed.items():
        for target_name, conn in loc["connections"].items():
            target_id = None
            for tid, tdata in placed.items():
                if tdata["name"] == target_name:
                    target_id = tid
                    break
            if not target_id:
                continue
            pair = tuple(sorted([loc_id, target_id]))
            if pair in drawn_connections:
                continue
            drawn_connections.add(pair)

            x1, y1 = hex_center(loc["x"], loc["y"])
            x2, y2 = hex_center(placed[target_id]["x"], placed[target_id]["y"])
            ctx.set_source_rgba(0.45, 0.38, 0.28, 0.7)
            ctx.set_line_width(2)
            ctx.set_dash([6, 4])
            ctx.move_to(x1, y1)
            ctx.line_to(x2, y2)
            ctx.stroke()
            ctx.set_dash([])

    # ─── 지역 마커 ───
    # 겹침 방지용
    label_rects = []

    def find_label_pos(cx, cy, tw, th):
        offsets = [(cx - tw/2, cy + 28), (cx - tw/2, cy - th - 28),
                   (cx + 32, cy - th/2), (cx - tw - 32, cy - th/2),
                   (cx - tw/2, cy + 44), (cx - tw/2, cy - th - 44)]
        for lx, ly in offsets:
            rect = (lx - 2, ly - 2, lx + tw + 4, ly + th + 4)
            overlap = any(not (rect[2] < r[0] or rect[0] > r[2] or rect[3] < r[1] or rect[1] > r[3]) for r in label_rects)
            if not overlap:
                label_rects.append(rect)
                return lx, ly
        label_rects.append((offsets[0][0]-2, offsets[0][1]-2, offsets[0][0]+tw+4, offsets[0][1]+th+4))
        return offsets[0]

    type_colors = {
        "village": (0.63, 0.47, 0.24),
        "trade_city": (0.72, 0.55, 0.18),
        "road": (0.55, 0.47, 0.32),
        "dungeon": (0.47, 0.32, 0.40),
        "rest_area": (0.52, 0.56, 0.36),
        "port_village": (0.32, 0.47, 0.60),
    }

    for loc_id, loc in placed.items():
        cx, cy = hex_center(loc["x"], loc["y"])
        color = type_colors.get(loc["type"], (0.6, 0.5, 0.4))

        if loc["type"] == "trade_city":
            # 성벽 + 탑
            r = 20
            ctx.set_source_rgb(*color)
            ctx.rectangle(cx-r, cy-r, r*2, r*2)
            ctx.fill()
            ctx.set_source_rgb(0.32, 0.24, 0.12)
            ctx.set_line_width(2)
            ctx.rectangle(cx-r, cy-r, r*2, r*2)
            ctx.stroke()
            # 탑
            for tx_off in [-r, r-6]:
                ctx.rectangle(cx+tx_off, cy-r-10, 6, 10)
                ctx.fill()
        elif loc["type"] in ("village", "port_village"):
            r = 14
            ctx.set_source_rgb(*color)
            ctx.rectangle(cx-r, cy-3, r*2, r+3)
            ctx.fill()
            ctx.set_source_rgb(0.63, 0.40, 0.20)
            ctx.move_to(cx-r-2, cy-3)
            ctx.line_to(cx, cy-r-6)
            ctx.line_to(cx+r+2, cy-3)
            ctx.close_path()
            ctx.fill()
            ctx.set_source_rgb(0.32, 0.24, 0.12)
            ctx.set_line_width(1.5)
            ctx.rectangle(cx-r, cy-3, r*2, r+3)
            ctx.stroke()
        elif loc["type"] == "dungeon":
            r = 16
            ctx.set_source_rgba(0.24, 0.20, 0.24, 0.9)
            ctx.arc(cx, cy, r, 0, 2 * _math.pi)
            ctx.fill()
            ctx.set_source_rgb(0.40, 0.32, 0.32)
            ctx.set_line_width(2)
            ctx.arc(cx, cy, r, 0, 2 * _math.pi)
            ctx.stroke()
            # 해골
            ctx.set_source_rgba(0.80, 0.72, 0.60, 0.9)
            ctx.set_font_size(18)
            te = ctx.text_extents("\u2620")
            ctx.move_to(cx - te.width/2, cy + te.height/2)
            ctx.show_text("\u2620")
        elif loc["type"] == "rest_area":
            r = 12
            ctx.set_source_rgb(*color)
            ctx.move_to(cx, cy - r - 5)
            ctx.line_to(cx - r - 5, cy + r)
            ctx.line_to(cx + r + 5, cy + r)
            ctx.close_path()
            ctx.fill()
            ctx.set_source_rgb(0.32, 0.24, 0.12)
            ctx.set_line_width(1.5)
            ctx.move_to(cx, cy - r - 5)
            ctx.line_to(cx - r - 5, cy + r)
            ctx.line_to(cx + r + 5, cy + r)
            ctx.close_path()
            ctx.stroke()
        else:
            r = 14
            ctx.set_source_rgb(*color)
            ctx.arc(cx, cy, r, 0, 2 * _math.pi)
            ctx.fill()
            ctx.set_source_rgb(0.32, 0.24, 0.12)
            ctx.set_line_width(1.5)
            ctx.arc(cx, cy, r, 0, 2 * _math.pi)
            ctx.stroke()

        # 이름 라벨
        ctx.select_font_face("Malgun Gothic", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(15)
        te = ctx.text_extents(loc["name"])
        lx, ly = find_label_pos(cx, cy, te.width + 8, 20)
        # 배경 박스
        ctx.set_source_rgba(0.75, 0.68, 0.52, 0.85)
        ctx.rectangle(lx, ly, te.width + 8, 20)
        ctx.fill()
        ctx.set_source_rgba(0.45, 0.38, 0.25, 0.8)
        ctx.set_line_width(1)
        ctx.rectangle(lx, ly, te.width + 8, 20)
        ctx.stroke()
        # 텍스트
        ctx.set_source_rgb(0.20, 0.12, 0.05)
        ctx.move_to(lx + 4, ly + 15)
        ctx.show_text(loc["name"])

    # ─── 현재 위치 ───
    try:
        gs_path = os.path.join(BASE_DIR, "data", "game_state.json")
        if os.path.exists(gs_path):
            with open(gs_path, "r", encoding="utf-8") as f:
                gs = json.load(f)
            cur_loc = gs.get("current_location", "")
            if cur_loc in placed:
                px, py = hex_center(placed[cur_loc]["x"], placed[cur_loc]["y"])
                # 빨간 깃발
                ctx.set_source_rgb(0.72, 0.15, 0.15)
                ctx.set_line_width(2.5)
                ctx.move_to(px + 22, py - 2)
                ctx.line_to(px + 22, py - 30)
                ctx.stroke()
                ctx.set_source_rgba(0.82, 0.20, 0.20, 0.9)
                ctx.move_to(px + 22, py - 30)
                ctx.line_to(px + 38, py - 24)
                ctx.line_to(px + 22, py - 18)
                ctx.close_path()
                ctx.fill()
                # 라벨
                ctx.select_font_face("Malgun Gothic", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
                ctx.set_font_size(13)
                ctx.set_source_rgb(0.72, 0.15, 0.15)
                ctx.move_to(px + 40, py - 22)
                ctx.show_text("\ud604\uc7ac \uc704\uce58")
    except Exception:
        pass

    # ─── 장식 테두리 ───
    ctx.set_source_rgb(0.45, 0.35, 0.20)
    ctx.set_line_width(4)
    ctx.rectangle(6, 6, img_w - 12, img_h - 12)
    ctx.stroke()
    ctx.set_line_width(1)
    ctx.rectangle(12, 12, img_w - 24, img_h - 24)
    ctx.stroke()

    # 제목 배너
    ctx.set_source_rgba(0.68, 0.60, 0.45, 0.9)
    ctx.rectangle(20, 14, 180, 38)
    ctx.fill()
    ctx.set_source_rgb(0.45, 0.35, 0.20)
    ctx.set_line_width(2)
    ctx.rectangle(20, 14, 180, 38)
    ctx.stroke()
    ctx.select_font_face("Malgun Gothic", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(24)
    ctx.set_source_rgb(0.22, 0.14, 0.06)
    ctx.move_to(35, 42)
    ctx.show_text("\uc138\uacc4 \uc9c0\ub3c4")

    # ─── 나침반 ───
    ncx, ncy = img_w - 55, img_h - 55
    nr = 28
    ctx.set_source_rgba(0.75, 0.68, 0.52, 0.9)
    ctx.arc(ncx, ncy, nr, 0, 2 * _math.pi)
    ctx.fill()
    ctx.set_source_rgb(0.45, 0.35, 0.20)
    ctx.set_line_width(2)
    ctx.arc(ncx, ncy, nr, 0, 2 * _math.pi)
    ctx.stroke()
    ctx.set_font_size(14)
    ctx.set_source_rgb(0.72, 0.15, 0.15)
    te = ctx.text_extents("N")
    ctx.move_to(ncx - te.width/2, ncy - nr + 14)
    ctx.show_text("N")
    ctx.set_source_rgb(0.22, 0.14, 0.06)
    for label, angle in [("E", 0), ("S", _math.pi/2), ("W", _math.pi)]:
        te = ctx.text_extents(label)
        lx = ncx + (nr - 14) * _math.cos(angle - _math.pi/2) - te.width/2
        ly = ncy + (nr - 14) * _math.sin(angle - _math.pi/2) + te.height/2
        ctx.move_to(lx, ly)
        ctx.show_text(label)
    # 십자선
    ctx.set_line_width(0.8)
    ctx.move_to(ncx, ncy - nr + 16)
    ctx.line_to(ncx, ncy + nr - 16)
    ctx.stroke()
    ctx.move_to(ncx - nr + 16, ncy)
    ctx.line_to(ncx + nr - 16, ncy)
    ctx.stroke()

    # ─── 저장 ───
    output_path = os.path.join(BASE_DIR, "static", "world_map.png")
    surface.write_to_png(output_path)
    return output_path


if __name__ == "__main__":
    gen = MapGenerator()
    path = gen.save_map()
    print(f"Map saved to {path}")
