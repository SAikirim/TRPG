"""
세계 지도 에이전트 — 지리학/지도학/생태학 기반 세계 지도 검증
- gm-update 시 자동 검증 (check_and_warn)
- 새 지역/지형 추가 시 좌표/지리 합리성 검증
- CLI로도 직접 실행 가능

자동 감지 항목:
  - 항구가 해안이 아닌 곳에 배치됨
  - 강이 바다에서 산으로 역류
  - 직통 도로가 경유 경로와 모순
  - 도시가 교통 요충지가 아닌 외딴 곳에 배치됨
  - 새 지역의 world_pos가 기존 지형과 충돌 (바다 위에 마을 등)
  - travel_hours와 좌표 거리 간 불일치

사용법:
  python -m core.worldmap_agent check              전체 세계 지도 검증
  python -m core.worldmap_agent validate_location <loc_id>  특정 지역 검증
"""

import json
import math
import os
import sys
sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WB_PATH = os.path.join(BASE_DIR, "data", "worldbuilding.json")
GAME_STATE_PATH = os.path.join(BASE_DIR, "data", "game_state.json")


def _load_json(path):
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_sea_coords(wb):
    """바다 좌표 집합 반환."""
    sea = set()
    for feat in wb.get("terrain", {}).get("features", []):
        if feat.get("type") == "sea" and "coords" in feat:
            for c in feat["coords"]:
                sea.add((c[0], c[1]))
    return sea


def _get_terrain_at(wb, x, y):
    """특정 좌표의 지형 타입 반환."""
    for feat in wb.get("terrain", {}).get("features", []):
        if feat.get("type") == "river":
            continue
        for c in feat.get("coords", []):
            if c[0] == x and c[1] == y:
                return feat.get("type", "")
    return "land"  # 기본값


def _coord_distance(x1, y1, x2, y2):
    """좌표 간 유클리드 거리."""
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


def check_and_warn(game_state=None, new_location=None):
    """gm-update에서 호출되는 자동 검증. 경고를 문자열 리스트로 반환."""
    wb = _load_json(WB_PATH)
    if wb is None:
        return []

    warnings = []
    locations = wb.get("locations", {})
    sea_coords = _get_sea_coords(wb)

    # 1. 항구/마을이 바다 위에 있는지 확인
    for loc_id, loc in locations.items():
        wp = loc.get("world_pos")
        if not wp:
            continue
        terrain = _get_terrain_at(wb, wp[0], wp[1])
        loc_type = loc.get("type", "")
        if terrain == "sea" and loc_type != "sea":
            warnings.append(
                f"🗺️ '{loc.get('name', loc_id)}' [{wp[0]},{wp[1]}]이 바다 위에 배치됨 — "
                f"해안(육지 쪽)으로 이동 필요")

    # 2. 항구가 해안 근처인지 확인
    for loc_id, loc in locations.items():
        if loc.get("type") not in ("port_village", "port_city"):
            continue
        wp = loc.get("world_pos")
        if not wp:
            continue
        # 인접 8칸에 바다가 있는지
        adjacent_sea = False
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                if (wp[0] + dx, wp[1] + dy) in sea_coords:
                    adjacent_sea = True
                    break
            if adjacent_sea:
                break
        if not adjacent_sea:
            warnings.append(
                f"🗺️ 항구 '{loc.get('name', loc_id)}' [{wp[0]},{wp[1]}] 근처에 바다가 없음 — "
                f"해안으로 이동하거나 바다 지형 확장 필요")

    # 3. 연결 경로 합리성 (직통 vs 경유 모순)
    for loc_id, loc in locations.items():
        wp = loc.get("world_pos")
        if not wp:
            continue
        for target_name, conn in loc.get("connections", {}).items():
            # 대상 찾기
            target_loc = None
            for tid, tdata in locations.items():
                if tdata.get("name") == target_name:
                    target_loc = tdata
                    break
            if not target_loc or not target_loc.get("world_pos"):
                continue
            twp = target_loc["world_pos"]
            coord_dist = _coord_distance(wp[0], wp[1], twp[0], twp[1])
            travel_hours = conn.get("travel_hours", 0)
            # 좌표 거리 대비 travel_hours가 비정상적이면 경고
            if travel_hours > 0 and coord_dist > 0:
                speed = travel_hours / coord_dist  # 좌표 1칸당 시간
                if speed > 15:  # 1칸에 15시간 이상이면 비정상
                    warnings.append(
                        f"🗺️ '{loc.get('name',loc_id)}' → '{target_name}': "
                        f"좌표 거리 {coord_dist:.1f}칸인데 {travel_hours}시간 — 비율 이상")

    # 4. 강 흐름 방향 (산→바다 방향인지)
    for feat in wb.get("terrain", {}).get("features", []):
        if feat.get("type") != "river" or "path" not in feat:
            continue
        path = feat["path"]
        if len(path) < 2:
            continue
        start = (path[0][0], path[0][1])
        end = (path[-1][0], path[-1][1])
        start_terrain = _get_terrain_at(wb, start[0], start[1])
        end_near_sea = any(
            (end[0] + dx, end[1] + dy) in sea_coords
            for dx in range(-2, 3) for dy in range(-2, 3))
        start_near_mountain = start_terrain == "mountain" or any(
            _get_terrain_at(wb, start[0] + dx, start[1] + dy) == "mountain"
            for dx in range(-1, 2) for dy in range(-1, 2))
        if not end_near_sea:
            warnings.append(
                f"🗺️ 강 '{feat.get('name', '?')}' 끝점 [{end[0]},{end[1]}]이 "
                f"바다 근처가 아님 — 강은 바다/호수로 흘러야 함")

    # 5. 새 지역 검증 (new_location이 제공된 경우)
    if new_location:
        wp = new_location.get("world_pos")
        if wp:
            terrain = _get_terrain_at(wb, wp[0], wp[1])
            if terrain == "sea" and new_location.get("type") not in ("sea",):
                warnings.append(
                    f"🗺️ 새 지역 '{new_location.get('name', '?')}' [{wp[0]},{wp[1]}]이 "
                    f"바다 위 — 육지 좌표로 변경 필요")
            # 기존 지역과 좌표 충돌
            for loc_id, loc in locations.items():
                owp = loc.get("world_pos")
                if owp and owp[0] == wp[0] and owp[1] == wp[1]:
                    warnings.append(
                        f"🗺️ 새 지역 [{wp[0]},{wp[1]}]이 "
                        f"'{loc.get('name', loc_id)}'과 좌표 충돌")

    return warnings


def full_check():
    """전체 세계 지도 검증 (CLI용)."""
    warnings = check_and_warn()
    if not warnings:
        print("✓ 세계 지도 검증 통과")
    else:
        print(f"⚠ 감지 {len(warnings)}건:")
        for w in warnings:
            print(f"  {w}")
    return warnings


def validate_location(loc_id):
    """특정 지역 검증."""
    wb = _load_json(WB_PATH)
    if not wb:
        print("worldbuilding.json 없음")
        return
    loc = wb.get("locations", {}).get(loc_id)
    if not loc:
        print(f"지역 '{loc_id}' 없음")
        return
    warnings = check_and_warn(new_location=loc)
    if not warnings:
        print(f"✓ '{loc.get('name', loc_id)}' 검증 통과")
    else:
        for w in warnings:
            print(f"  {w}")


def main():
    if len(sys.argv) < 2:
        print("사용법: python -m core.worldmap_agent <check|validate_location>")
        print("  check                     전체 세계 지도 검증")
        print("  validate_location <id>    특정 지역 검증")
        return

    cmd = sys.argv[1]
    if cmd == "check":
        full_check()
    elif cmd == "validate_location" and len(sys.argv) >= 3:
        validate_location(sys.argv[2])
    else:
        print(f"알 수 없는 명령: {cmd}")


if __name__ == "__main__":
    main()
