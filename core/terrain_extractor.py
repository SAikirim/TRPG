"""
세계 지도 이미지에서 지형 데이터를 자동 추출한다.
색상 분석으로 바다/숲/산/평원/강 등을 식별하고 좌표 데이터로 변환.
"""

from PIL import Image
from collections import deque
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
    rivers = extract_rivers(img, world_range)
    features.extend(rivers)

    return {
        "description": "이미지에서 자동 추출된 지형 데이터",
        "features": features
    }


def classify_color(r, g, b):
    """RGB 색상으로 지형 타입 분류 (SD dreamshaper 출력에 맞게 튜닝)"""

    brightness = r + g + b

    # 바다: 파란색 계열 — 더 관대하게 (dreamshaper는 채도 낮은 파랑도 생성)
    if b > 100 and b > r * 1.1 and b > g * 1.0:
        return "sea"

    # 숲: 초록 계열 — 짙은 초록 + 중간 초록 모두 포함
    if g > 70 and g > r * 1.2 and g > b:
        return "forest"

    # 산: 어두운 갈색/회색 (전체적으로 어두움)
    if brightness < 300 and r > 50:
        # 회색조 (r≈g≈b, 어두움) → 산
        if abs(r - g) < 30 and abs(g - b) < 30:
            return "mountain"
        # 어두운 갈색 (r > g 약간, b 낮음) → 산
        if r >= g and b < r * 0.8:
            return "mountain"

    # 건조지대: 황갈색 (r 높고, g 중간, b 낮음)
    if r > 150 and g > 100 and g < r and b < 100:
        return "swamp"  # 건조지대 (swamp 타입 재사용)

    # 평원: 연두~황금 (r/g 높고, b 낮음)
    if r > 120 and g > 120 and b < 120:
        return "plains"

    # 양피지 배경 (세피아톤: r/g/b 모두 높고, 따뜻한 톤)
    # 양피지는 보통 r>g>b이고 전체적으로 밝음
    if brightness > 450 and r > 150 and g > 130 and b > 100:
        # 뚜렷한 지형 색상이 아닌 배경 → unclassified (나중에 주변으로 채움)
        return "unclassified"

    # 밝은 영역 중 따뜻한 톤 → 평원
    if brightness > 350 and r > g and g > b:
        return "plains"

    return "unclassified"  # 분류 불가 → 후처리에서 주변 지형으로 채움


def _fill_unclassified(terrain_map, world_range):
    """unclassified 셀을 주변 지형 중 가장 많은 타입으로 채운다."""
    x_min = world_range["x_min"]
    x_max = world_range["x_max"]
    y_min = world_range["y_min"]
    y_max = world_range["y_max"]

    unclassified = {k for k, v in terrain_map.items() if v == "unclassified"}
    if not unclassified:
        return

    # 반복적으로 채움 (최대 10회)
    for _ in range(10):
        filled = set()
        for (x, y) in unclassified:
            neighbors = {}
            for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0),
                           (1, 1), (1, -1), (-1, 1), (-1, -1)]:
                nx, ny = x + dx, y + dy
                if (nx, ny) in terrain_map and terrain_map[(nx, ny)] != "unclassified":
                    t = terrain_map[(nx, ny)]
                    neighbors[t] = neighbors.get(t, 0) + 1
            if neighbors:
                best = max(neighbors, key=neighbors.get)
                terrain_map[(x, y)] = best
                filled.add((x, y))
        unclassified -= filled
        if not unclassified:
            break

    # 남은 unclassified → plains 처리
    for k in unclassified:
        terrain_map[k] = "plains"


def group_terrain_features(terrain_map, world_range):
    """같은 타입의 인접 좌표를 그룹화하여 terrain features 생성.
    최소 면적 10칸, 인접 같은 타입 feature를 거리 5 이내면 병합,
    최종 feature 수 20개 이하 목표."""

    # 먼저 unclassified 채우기
    _fill_unclassified(terrain_map, world_range)

    features = []
    visited = set()

    types_to_group = ["sea", "forest", "mountain", "plains", "swamp"]

    for terrain_type in types_to_group:
        # 해당 타입의 모든 좌표
        type_coords = {k for k, v in terrain_map.items() if v == terrain_type}

        type_regions = []  # 이 타입의 모든 region

        while type_coords - visited:
            # BFS로 연결된 영역 찾기
            start = next(iter(type_coords - visited))
            region = set()
            queue = deque([start])

            while queue:
                curr = queue.popleft()
                if curr in region or curr in visited or curr not in type_coords:
                    continue
                region.add(curr)
                visited.add(curr)
                x, y = curr
                for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
                    neighbor = (x + dx, y + dy)
                    if neighbor in type_coords and neighbor not in visited:
                        queue.append(neighbor)

            if len(region) >= 10:  # 최소 10칸 이상만
                type_regions.append(region)

        # 인접한 같은 타입 region 병합 (거리 40칸 이내 — 매우 공격적 병합)
        type_regions = _merge_nearby_regions(type_regions, max_dist=40)

        for region in type_regions:
            # 좌표 샘플링 — 최대 20개 좌표
            sampled = sorted(region)
            step = max(1, len(sampled) // 20)
            coords = [[c[0], c[1]] for i, c in enumerate(sampled) if i % step == 0]
            if len(coords) > 20:
                coords = coords[:20]

            features.append({
                "type": terrain_type,
                "name": "",
                "description": "",
                "area_cells": len(region),  # 디버깅용 면적 정보
                "coords": coords
            })

    # feature 수가 20 초과면 면적 기준으로 상위 20개만
    if len(features) > 20:
        features.sort(key=lambda f: f.get("area_cells", 0), reverse=True)
        features = features[:20]

    return features


def _merge_nearby_regions(regions, max_dist=5):
    """같은 타입의 region 리스트에서, 중심 간 거리가 max_dist 이내인 것을 병합."""
    if len(regions) <= 1:
        return regions

    def region_center(region):
        xs = [c[0] for c in region]
        ys = [c[1] for c in region]
        return (sum(xs) / len(xs), sum(ys) / len(ys))

    def min_distance(r1, r2):
        """두 region 간 최소 좌표 거리 (맨해튼)."""
        # 성능을 위해 중심 간 거리로 근사
        c1 = region_center(r1)
        c2 = region_center(r2)
        return abs(c1[0] - c2[0]) + abs(c1[1] - c2[1])

    merged = True
    while merged:
        merged = False
        new_regions = []
        used = set()
        for i in range(len(regions)):
            if i in used:
                continue
            current = regions[i]
            for j in range(i + 1, len(regions)):
                if j in used:
                    continue
                if min_distance(current, regions[j]) <= max_dist * 2:
                    current = current | regions[j]
                    used.add(j)
                    merged = True
            new_regions.append(current)
            used.add(i)
        regions = new_regions

    return regions


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


def extract_rivers(img, world_range):
    """강 추출: 이미지에서 좁은 폭(1-5px)의 파란색/청록색 선형 패턴 감지.

    접근: 각 행에서 좁은 폭의 파란 영역을 찾고, 연속된 행의 파란 위치를
    연결하여 강 path를 생성한다.

    Args:
        img: PIL Image (RGB)
        world_range: 좌표 범위

    Returns:
        river feature 리스트 (각각 {"type":"river", "path":[[x,y],...]} 형태)
    """
    w, h = img.size
    x_range = world_range["x_max"] - world_range["x_min"]
    y_range = world_range["y_max"] - world_range["y_min"]
    cell_w = w / x_range
    cell_h = h / y_range

    # 1단계: 이미지에서 파란 픽셀 마스크 생성 (그리드 단위)
    blue_mask = set()  # (gx, gy) 중 파란색인 셀

    for gy in range(y_range):
        for gx in range(x_range):
            px = int((gx + 0.5) * cell_w)
            py = int((gy + 0.5) * cell_h)
            px = max(0, min(w - 1, px))
            py = max(0, min(h - 1, py))
            r, g, b = img.getpixel((px, py))
            # 파란/청록 판정 (강은 바다보다 좁으므로 별도 기준)
            if b > 90 and b > r * 1.1 and b > g * 0.9:
                blue_mask.add((gx, gy))

    if not blue_mask:
        return []

    # 2단계: 파란 셀 중 '좁은' 것만 (강). 넓은 영역(바다)은 제외.
    # 각 파란 셀의 행(row)에서 연속된 파란 셀 폭 계산
    river_cells = set()
    for gy in range(y_range):
        row_blues = sorted([gx for (gx, y) in blue_mask if y == gy])
        if not row_blues:
            continue
        # 연속 구간 분리
        runs = []
        run_start = row_blues[0]
        run_end = row_blues[0]
        for gx in row_blues[1:]:
            if gx == run_end + 1:
                run_end = gx
            else:
                runs.append((run_start, run_end))
                run_start = gx
                run_end = gx
        runs.append((run_start, run_end))

        for rs, re in runs:
            width = re - rs + 1
            if width <= 5:  # 폭 5칸 이하만 강으로 취급
                for gx in range(rs, re + 1):
                    river_cells.add((gx, gy))

    if len(river_cells) < 5:
        return []

    # 3단계: BFS로 연결된 river_cells를 path로 변환
    rivers = []
    visited = set()

    while river_cells - visited:
        start = next(iter(river_cells - visited))
        path_set = set()
        queue = deque([start])
        while queue:
            curr = queue.popleft()
            if curr in path_set or curr in visited or curr not in river_cells:
                continue
            path_set.add(curr)
            visited.add(curr)
            x, y = curr
            for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0),
                           (1, 1), (1, -1), (-1, 1), (-1, -1)]:
                nb = (x + dx, y + dy)
                if nb in river_cells and nb not in visited:
                    queue.append(nb)

        if len(path_set) < 15:
            continue

        # path를 y 기준 정렬 (상류→하류)
        sorted_path = sorted(path_set, key=lambda p: (p[1], p[0]))

        # 좌표를 world 좌표로 변환 + 샘플링 (최대 20개)
        step = max(1, len(sorted_path) // 20)
        path = [
            [world_range["x_min"] + p[0], world_range["y_min"] + p[1]]
            for i, p in enumerate(sorted_path) if i % step == 0
        ]

        rivers.append({
            "type": "river",
            "name": "",
            "description": "자동 추출된 강",
            "path": path,
            "_length": len(path_set),  # 정렬용
        })

    # 강이 너무 많으면 길이 순으로 상위 3개만
    if len(rivers) > 3:
        rivers.sort(key=lambda r: r["_length"], reverse=True)
        rivers = rivers[:3]

    # 정렬용 임시 키 제거
    for r in rivers:
        r.pop("_length", None)

    return rivers
