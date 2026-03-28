import json
import os
import sys
sys.stdout.reconfigure(encoding='utf-8')
from PIL import Image, ImageDraw, ImageFont

# 호환성 re-export (기존 import 안 깨뜨리기)
from core.world_map import generate_world_map
from core.scene_renderer import SceneRenderer
from core.portrait_generator import PortraitGenerator


# ─── 이모지 지원 검증 ───
_EMOJI_SUPPORT_CACHE = {}

def _is_emoji_supported(emoji_char, font, threshold=150):
    """seguiemj.ttf에서 이모지가 컬러 글리프로 렌더링되는지 검증.
    윤곽선만 있는 이모지(pixels < threshold)는 미지원으로 판정."""
    if emoji_char in _EMOJI_SUPPORT_CACHE:
        return _EMOJI_SUPPORT_CACHE[emoji_char]
    try:
        from PIL import Image as _Img, ImageDraw as _Draw
        import numpy as _np
        img = _Img.new('RGBA', (30, 30), (0,0,0,0))
        draw = _Draw.Draw(img)
        try:
            draw.text((2, 2), emoji_char, font=font, embedded_color=True)
        except TypeError:
            draw.text((2, 2), emoji_char, font=font)
        arr = _np.array(img)
        pixels = int(_np.count_nonzero(arr[:,:,3]))
        supported = pixels >= threshold
        _EMOJI_SUPPORT_CACHE[emoji_char] = supported
        return supported
    except Exception:
        _EMOJI_SUPPORT_CACHE[emoji_char] = False
        return False


# 미지원 이모지 → 지원 이모지 폴백 매핑
EMOJI_FALLBACK = {
    '🪧': '📌',  # 이정표 → pushpin
    '🪣': '💦',  # 물통 → droplets
    '🪵': '🔶',  # 장작 → orange diamond
    '🫙': '📦',  # 항아리 → package
    '🫗': '💧',  # 붓기 → water
    '🧱': '🟫',  # 벽돌 → brown square
}


def safe_emoji(emoji_char, font):
    """지원되는 이모지를 반환. 미지원이면 폴백."""
    if _is_emoji_supported(emoji_char, font):
        return emoji_char
    return EMOJI_FALLBACK.get(emoji_char, '❓')


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
        self._scene_renderer = SceneRenderer(self.base_dir)
        self._portrait_generator = PortraitGenerator(self.base_dir)

    def load_game_state(self):
        path = os.path.join(self.base_dir, "data", "game_state.json")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def generate_map(self):
        state = self.load_game_state()

        # ko.json 로드 (맵 전체에서 번역 사용)
        self._ko = {}
        try:
            ko_path = os.path.join(self.base_dir, "lang", "ko.json")
            with open(ko_path, "r", encoding="utf-8") as f:
                self._ko = json.load(f)
        except Exception:
            pass

        def _t_name(en_name, *categories):
            for cat in categories:
                v = self._ko.get(cat, {}).get(en_name)
                if v:
                    return v
            return en_name
        self._t_name = _t_name

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

        # === 단일 타일 랜드마크 아이콘 ===
        landmark_positions = set()  # 아이콘으로 표시된 단일 타일 위치
        LANDMARK_EMOJI = {
            '우물': '\U0001f4a7',     # 💧
            '모닥불': '\U0001f525',    # 🔥
            '이정표': '\U0001f4cc',    # 📌
            '제단': '\u26e9\ufe0f',    # ⛩️
            '샘': '\U0001f4a7',       # 💧
        }
        for loc in locations:
            area = loc["area"] if isinstance(loc.get("area"), dict) else loc
            if area.get("x1") == area.get("x2") and area.get("y1") == area.get("y2"):
                name = loc.get("name", "")
                for keyword, emoji_char in LANDMARK_EMOJI.items():
                    if keyword in name:
                        lx, ly = area["x1"], area["y1"]
                        if 0 <= lx < map_w and 0 <= ly < map_h:
                            cx = lx * self.tile_size + self.tile_size // 2 + margin_left
                            cy = ly * self.tile_size + self.tile_size // 2 + margin_top
                            landmark_positions.add((lx, ly))
                            # 배경 원
                            draw.ellipse([cx - 10, cy - 10, cx + 10, cy + 10], fill="#00000066")
                            if emoji_font:
                                safe = safe_emoji(emoji_char, emoji_font)
                                try:
                                    draw.text((cx - 10, cy - 10), safe, font=emoji_font, embedded_color=True)
                                except TypeError:
                                    draw.text((cx - 10, cy - 10), safe, font=emoji_font)
                            entity_icons.append({"cx": cx, "cy": cy, "r": 10, "name": "", "color": "#aaaaaa", "type": "landmark"})
                        break

        # === 오브젝트 엔티티 아이콘 ===
        OBJ_EMOJI = {
            'vehicle': '\U0001f6d2',    # 🛒
            'container': '\U0001f4a6',   # 💦
            'resource': '\U0001f536',    # 🔶
            'shelter': '\u26fa',         # ⛺
        }
        scenario_id = state.get("game_info", {}).get("scenario_id", "")
        if scenario_id:
            obj_dir = os.path.join(self.base_dir, "entities", scenario_id, "objects")
            if os.path.isdir(obj_dir):
                for fname in sorted(os.listdir(obj_dir)):
                    if not fname.endswith(".json"):
                        continue
                    try:
                        with open(os.path.join(obj_dir, fname), "r", encoding="utf-8") as f:
                            obj = json.load(f)
                        pos = obj.get("position")
                        if not (pos and len(pos) == 2):
                            continue
                        # 같은 위치(current_location)에 있는 오브젝트만 표시
                        obj_loc = obj.get("location", "")
                        if current_loc and obj_loc and obj_loc != current_loc:
                            continue
                        ox, oy = int(pos[0]), int(pos[1])
                        if not (0 <= ox < map_w and 0 <= oy < map_h):
                            continue
                        obj_type = obj.get("type", "")
                        # 오브젝트 JSON에 icon 필드가 있으면 그걸 사용
                        emoji_char = obj.get("icon", OBJ_EMOJI.get(obj_type, "\U0001f4e6"))  # 📦 fallback
                        obj_size = obj.get("size", [1, 1])
                        for dy in range(obj_size[1]):
                            for dx in range(obj_size[0]):
                                tx, ty = ox + dx, oy + dy
                                if not (0 <= tx < map_w and 0 <= ty < map_h):
                                    continue
                                cx = tx * self.tile_size + self.tile_size // 2 + margin_left
                                cy = ty * self.tile_size + self.tile_size // 2 + margin_top
                                draw.ellipse([cx - 9, cy - 9, cx + 9, cy + 9], fill="#33333388")
                                if emoji_font:
                                    safe = safe_emoji(emoji_char, emoji_font)
                                    try:
                                        draw.text((cx - 10, cy - 10), safe, font=emoji_font, embedded_color=True)
                                    except TypeError:
                                        draw.text((cx - 10, cy - 10), safe, font=emoji_font)
                        # entity_icons는 기준 위치(좌상단)에만 등록
                        cx0 = ox * self.tile_size + self.tile_size // 2 + margin_left
                        cy0 = oy * self.tile_size + self.tile_size // 2 + margin_top
                        entity_icons.append({"cx": cx0, "cy": cy0, "r": 9, "name": "", "color": "#888888", "type": "object"})
                    except Exception:
                        pass

        # NPC 아이콘 그리기 + 위치 수집
        r = 12
        for npc in state["npcs"]:
            if npc.get("status") in ("fled", "gone", "separated"):
                continue  # 도주/퇴장/헤어진 NPC는 맵에서 제외
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
                safe = safe_emoji(emoji_char, emoji_font)
                try:
                    draw.text((cx - 10, cy - 10), safe, font=emoji_font, embedded_color=True)
                except TypeError:
                    draw.text((cx - 10, cy - 10), safe, font=emoji_font)
            else:
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color, outline="white", width=2)

            label_color = "#666" if is_dead else (color if npc_type != "monster" else "white")
            # NPC name - always show name (translated via ko.json)
            npc_name = self._t_name(npc["name"], "npcs", "creatures")[:4]
            entity_icons.append({"cx": cx, "cy": cy, "r": r, "name": npc_name, "color": label_color, "type": "npc"})

        # 플레이어 아이콘 그리기 + 위치 수집
        player_colors = {
            "전사": "#e63946", "warrior": "#e63946",
            "마법사": "#457be0", "mage": "#457be0",
            "도적": "#2ecc71", "rogue": "#2ecc71",
            "궁수": "#e67e22", "ranger": "#e67e22",
            "성직자": "#f1c40f", "cleric": "#f1c40f",
        }
        for player in state["players"]:
            px, py = player["position"]
            cx = px * self.tile_size + self.tile_size // 2 + margin_left
            cy = py * self.tile_size + self.tile_size // 2 + margin_top
            color = player_colors.get(player["class"], "#ffffff")
            if emoji_font:
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color + "88", outline="white", width=2)
                player_emoji = player_emojis.get(player["class"], "\u2694\ufe0f")
                safe = safe_emoji(player_emoji, emoji_font)
                try:
                    draw.text((cx - 10, cy - 10), safe, font=emoji_font, embedded_color=True)
                except TypeError:
                    draw.text((cx - 10, cy - 10), safe, font=emoji_font)
            else:
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color, outline="white", width=3)
            entity_icons.append({"cx": cx, "cy": cy, "r": r, "name": self._t_name(player["name"], "npcs")[:3], "color": "white", "type": "player"})

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
            # 단일 타일이고 랜드마크 아이콘으로 이미 표시된 경우 라벨 스킵
            if (area["x1"] == area["x2"] and area["y1"] == area["y2"] and
                (area["x1"], area["y1"]) in landmark_positions):
                continue
            text = self._t_name(loc["name"], "area_names", "locations")
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
                raw_name = loc_data.get("name", current_loc)
                loc_name = self._t_name(current_loc, "locations") if self._t_name(current_loc, "locations") != current_loc else raw_name
            except Exception:
                loc_name = self._t_name(current_loc, "locations")
        info_text = f"Turn: {turn}"
        if loc_name:
            info_text += f"  |  {loc_name}"
        draw.rectangle([0, 0, max(250, len(info_text) * 9), 22], fill="#00000088")
        draw.text((4, 3), info_text, fill="yellow", font=font)

        # === 범례 (하단) — ko.json 번역 적용 ===
        legend_items = []
        _t_name = self._t_name

        # 현재 맵에 존재하는 플레이어 클래스
        for p in state["players"]:
            cls = p.get("class", "")
            emoji = player_emojis.get(cls, "")
            if emoji:
                legend_items.append((emoji, _t_name(p["name"], "npcs")))

        # 현재 맵에 존재하는 NPC
        for npc in state["npcs"]:
            if npc.get("status") in ("fled", "gone", "separated"):
                continue
            npc_loc = npc.get("location", "")
            if current_loc and npc_loc and npc_loc != current_loc:
                continue
            npc_type = npc.get("type", "neutral")
            emoji = npc_emojis.get(npc_type, "\U0001f464")
            npc_name = _t_name(npc["name"], "npcs", "creatures")[:4]
            legend_items.append((emoji, npc_name))

        # 랜드마크
        for pos_tuple in landmark_positions:
            for loc in locations:
                area = loc["area"]
                if (area["x1"], area["y1"]) == pos_tuple:
                    name = loc.get("name", "")
                    disp_name = _t_name(name, "area_names", "locations")[:6]
                    for kw, em in LANDMARK_EMOJI.items():
                        if kw in name or kw in disp_name:
                            legend_items.append((em, disp_name))
                            break
                    break

        # 오브젝트
        if scenario_id:
            obj_dir_leg = os.path.join(self.base_dir, "entities", scenario_id, "objects")
            if os.path.isdir(obj_dir_leg):
                for fname in sorted(os.listdir(obj_dir_leg)):
                    if not fname.endswith(".json"):
                        continue
                    try:
                        with open(os.path.join(obj_dir_leg, fname), "r", encoding="utf-8") as f:
                            obj_leg = json.load(f)
                        obj_loc = obj_leg.get("location", "")
                        if current_loc and obj_loc and obj_loc != current_loc:
                            continue
                        obj_type = obj_leg.get("type", "")
                        emoji = obj_leg.get("icon", OBJ_EMOJI.get(obj_type, ""))
                        if emoji:
                            obj_name = _t_name(obj_leg.get("name", "?"), "objects")[:6]
                            legend_items.append((emoji, obj_name))
                    except Exception:
                        pass

        if legend_items:
            legend_h = 28
            # 이미지 하단에 범례 공간 확장
            from PIL import Image as PILImage
            new_img = PILImage.new("RGB", (img_w, img_h + legend_h), "#1a1a1a")
            new_img.paste(img, (0, 0))
            img = new_img
            draw = ImageDraw.Draw(img)

            legend_y = img_h  # 원래 이미지 하단부터
            draw.rectangle([0, legend_y, img_w, img_h + legend_h], fill="#000000cc")

            # 아이템 배치
            lx = 8
            for emoji_char, label in legend_items:
                # 이모지
                if emoji_font:
                    safe = safe_emoji(emoji_char, emoji_font)
                    try:
                        draw.text((lx, legend_y + 3), safe, font=emoji_font, embedded_color=True)
                    except TypeError:
                        draw.text((lx, legend_y + 3), safe, font=emoji_font)
                lx += 22
                # 라벨
                draw.text((lx, legend_y + 7), label, fill="#cccccc", font=font_small)
                lx += len(label) * 8 + 12

        return img

    def save_map(self):
        img = self.generate_map()
        out_dir = os.path.join(self.base_dir, "static", "maps", "local")
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

        mini_path = os.path.join(self.base_dir, "static", "maps", "local", "map_mini.png")
        cropped.save(mini_path, "PNG")

    # ─── 위임 메서드 (기존 외부 호출 인터페이스 유지) ───

    def generate_portraits(self, force=False):
        """Generate portraits — delegates to PortraitGenerator."""
        state = self.load_game_state()
        return self._portrait_generator.generate_portraits(state, force)

    def generate_pixel_backgrounds(self):
        """Generate pixel backgrounds — delegates to SceneRenderer."""
        return self._scene_renderer.generate_pixel_backgrounds()

    def generate_scene_background(self, scene_name):
        """Generate scene background — delegates to SceneRenderer."""
        return self._scene_renderer.generate_scene_background(scene_name)

    def generate_scene_element(self, element_type, name):
        """Generate scene element — delegates to SceneRenderer."""
        return self._scene_renderer.generate_scene_element(element_type, name)


if __name__ == "__main__":
    gen = MapGenerator()
    path = gen.save_map()
    print(f"Map saved to {path}")
