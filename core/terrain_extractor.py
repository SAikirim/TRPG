"""
세계 지도 이미지에서 지형 데이터를 자동 추출한다.
색상 분석으로 바다/숲/산/평원/강 등을 식별하고 좌표 데이터로 변환.
"""

from PIL import Image
import json, os, math


def extract_terrain_from_image(image_path, grid_size=120, world_range=None):
    """
    이미지에서 지형 데이터를 추출.

    Args:
        image_path: 백지도 이미지 경로
        grid_size: 좌표 격자 크기 (기본 120 = 120x120)
        world_range: {"x_min":0, "x_max":150, "y_min":0, "y_max":120} 등

    Returns:
        terrain dict (worldbuilding.json의 terrain 형태)
    """
    img = Image.open(image_path).convert("RGB")
    w, h = img.size

    if world_range is None:
        world_range = {"x_min": 0, "x_max": grid_size, "y_min": 0, "y_max": grid_size}

    x_range = world_range["x_max"] - world_range["x_min"]
    y_range = world_range["y_max"] - world_range["y_min"]

    # 각 그리드 셀의 주요 색상을 분석
    cell_w = w / x_range
    cell_h = h / y_range

    terrain_map = {}  # (x, y) -> terrain_type

    for gx in range(x_range):
        for gy in range(y_range):
            # 셀 중심 픽셀 샘플링 (여러 점 평균)
            px_center = int((gx + 0.5) * cell_w)
            py_center = int((gy + 0.5) * cell_h)

            # 3x3 샘플링으로 안정적 색상 판별
            samples = []
            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    sx = max(0, min(w - 1, px_center + int(dx * cell_w * 0.2)))
                    sy = max(0, min(h - 1, py_center + int(dy * cell_h * 0.2)))
                    samples.append(img.getpixel((sx, sy)))

            avg_r = sum(s[0] for s in samples) / len(samples)
            avg_g = sum(s[1] for s in samples) / len(samples)
            avg_b = sum(s[2] for s in samples) / len(samples)

            terrain_type = classify_color(avg_r, avg_g, avg_b)
            wx = world_range["x_min"] + gx
            wy = world_range["y_min"] + gy
            terrain_map[(wx, wy)] = terrain_type

    # 같은 terrain_type의 인접 좌표를 그룹화하여 features로 변환
    features = group_terrain_features(terrain_map, world_range)

    # 해안선 추출 (바다/육지 경계)
    coastline = extract_coastline(terrain_map, world_range)
    if coastline:
        features.append(coastline)

    # 강 추출 (선형 수계)
    rivers = extract_rivers(terrain_map, world_range)
    features.extend(rivers)

    return {
        "description": "이미지에서 자동 추출된 지형 데이터",
        "features": features
    }


def classify_color(r, g, b):
    """RGB 색상으로 지형 타입 분류"""
    # HSV 변환 없이 간단한 규칙 기반

    # 바다: 파란색 계열 (b가 높고, r/g가 낮음)
    if b > 120 and b > r * 1.3 and b > g * 1.2:
        return "sea"

    # 숲: 짙은 초록 (g가 높고, r이 낮음)
    if g > 80 and g > r * 1.3 and g > b:
        if r < 100:  # 짙은 초록
            return "forest"
        else:  # 연한 초록
            return "plains"

    # 산: 갈색~회색 (r/g 비슷, b 낮음, 전체적으로 어두움)
    if r > 80 and abs(r - g) < 40 and b < r * 0.8:
        if r + g + b < 350:  # 어두우면 산
            return "mountain"

    # 평원: 연두~황금 (r/g 높고 비슷, b 낮음)
    if r > 120 and g > 120 and b < 120:
        return "plains"

    # 사막/건조: 베이지 (r>g>b, 밝음)
    if r > 150 and g > 120 and b < g and r + g + b > 400:
        return "swamp"  # 건조지대 (swamp 타입 재사용)

    # 양피지 배경 (세피아톤) → 기본 평원 처리
    if r > 150 and g > 130 and b > 100:
        return "plains"

    return "plains"  # 기본값


def group_terrain_features(terrain_map, world_range):
    """같은 타입의 인접 좌표를 그룹화하여 terrain features 생성"""
    features = []
    visited = set()

    types_to_group = ["sea", "forest", "mountain", "plains", "swamp"]

    for terrain_type in types_to_group:
        # 해당 타입의 모든 좌표
        type_coords = {k for k, v in terrain_map.items() if v == terrain_type}

        while type_coords - visited:
            # BFS로 연결된 영역 찾기
            start = next(iter(type_coords - visited))
            region = set()
            queue = [start]

            while queue:
                curr = queue.pop(0)
                if curr in region or curr in visited or curr not in type_coords:
                    continue
                region.add(curr)
                visited.add(curr)
                x, y = curr
                for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
                    neighbor = (x + dx, y + dy)
                    if neighbor in type_coords and neighbor not in visited:
                        queue.append(neighbor)

            if len(region) >= 3:  # 최소 3칸 이상만
                # 좌표를 10단위로 샘플링 (데이터 크기 줄이기)
                sampled = sorted(region)
                step = max(1, len(sampled) // 30)  # 최대 30개 좌표
                coords = [[c[0], c[1]] for i, c in enumerate(sampled) if i % step == 0]

                features.append({
                    "type": terrain_type,
                    "name": "",  # 이름은 세계관 에이전트가 나중에 부여
                    "description": "",
                    "coords": coords
                })

    return features


def extract_coastline(terrain_map, world_range):
    """바다/육지 경계에서 해안선 path 추출"""
    sea_coords = {k for k, v in terrain_map.items() if v == "sea"}
    land_coords = {k for k, v in terrain_map.items() if v != "sea"}

    if not sea_coords or not land_coords:
        return None

    # 바다와 육지가 인접한 좌표 쌍에서 경계점 추출
    boundary = []
    for sx, sy in sea_coords:
        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            neighbor = (sx + dx, sy + dy)
            if neighbor in land_coords:
                mid = ((sx + neighbor[0]) / 2, (sy + neighbor[1]) / 2)
                boundary.append(mid)

    if len(boundary) < 4:
        return None

    # 경계점을 y좌표로 정렬하여 path 생성
    boundary.sort(key=lambda p: (p[1], p[0]))

    # 샘플링
    step = max(1, len(boundary) // 20)
    path = [[int(p[0]), int(p[1])] for i, p in enumerate(boundary) if i % step == 0]

    return {
        "type": "coastline",
        "name": "해안선",
        "description": "자동 추출된 해안선",
        "path": path
    }


def extract_rivers(terrain_map, world_range):
    """강 추출 (선형 수계 — 간단 버전: 색상 기반)
    향후 개선: 산에서 바다로의 경로 탐색
    """
    # 현재는 빈 리스트 반환 (강은 수동 추가 또는 향후 구현)
    return []
