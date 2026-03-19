import json
import os
from PIL import Image, ImageDraw, ImageFont


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
        return out_path


if __name__ == "__main__":
    gen = MapGenerator()
    path = gen.save_map()
    print(f"Map saved to {path}")
