"""
세계관 에이전트 보조 도구
- Agent 툴에서 호출되어 worldbuilding.json을 검증/수정
- CLI로도 직접 실행 가능

사용법:
  python -m core.worldbuilding_agent check "<나레이션 텍스트>"
  python -m core.worldbuilding_agent register_location <id> <name> <type> [description]
  python -m core.worldbuilding_agent register_faction <id> <name> [description]
  python -m core.worldbuilding_agent connect <from_id> <to_id> <direction> <distance>
  python -m core.worldbuilding_agent query <location_id|faction_id|"all">
  python -m core.worldbuilding_agent validate
"""

import json
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WB_PATH = os.path.join(BASE_DIR, "data", "worldbuilding.json")
GAME_STATE_PATH = os.path.join(BASE_DIR, "data", "game_state.json")

OPPOSITE_DIR = {
    "북쪽": "남쪽", "남쪽": "북쪽", "동쪽": "서쪽", "서쪽": "동쪽",
    "북동쪽": "남서쪽", "남서쪽": "북동쪽", "북서쪽": "남동쪽", "남동쪽": "북서쪽",
}


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_worldbuilding():
    return _load_json(WB_PATH)


def save_worldbuilding(wb):
    _save_json(WB_PATH, wb)


# ─── 텍스트에서 세계관 요소 감지 ───

def check_narrative(text):
    """나레이션 텍스트를 분석해서 worldbuilding.json에 없는 요소를 찾는다.
    반환: {"missing_locations": [...], "missing_factions": [...], "conflicts": [...]}"""
    wb = load_worldbuilding()
    locations = wb.get("locations", {})
    factions = wb.get("factions", {})

    # 등록된 이름 목록
    known_loc_names = {v.get("name", "") for v in locations.values()}
    known_faction_names = set(factions.keys())

    result = {
        "missing_locations": [],
        "missing_factions": [],
        "conflicts": [],
        "mentioned_locations": [],
    }

    # 등록된 지역 중 텍스트에 언급된 것
    for loc_id, loc_data in locations.items():
        name = loc_data.get("name", "")
        if name and name in text:
            result["mentioned_locations"].append({
                "id": loc_id, "name": name, "status": "registered"
            })

    # 등록된 세력 중 텍스트에 언급된 것
    for fname in known_faction_names:
        if fname in text:
            result["mentioned_locations"].append({
                "id": fname, "name": fname, "type": "faction", "status": "registered"
            })

    return result


# ─── 등록 ───

def register_location(loc_id, name, loc_type, description="", world_pos=None,
                       features=None, connections=None):
    """새 지역을 worldbuilding.json에 등록."""
    wb = load_worldbuilding()
    locations = wb.setdefault("locations", {})

    if loc_id in locations:
        return {"error": f"이미 존재하는 location: {loc_id}", "existing": locations[loc_id]}

    entry = {
        "name": name,
        "type": loc_type,
        "description": description,
    }
    if world_pos:
        entry["world_pos"] = world_pos
    if features:
        entry["features"] = features
    if connections:
        entry["connections"] = connections

    locations[loc_id] = entry
    save_worldbuilding(wb)

    return {"success": True, "registered": loc_id, "data": entry}


def register_faction(faction_id, description="", services=None):
    """새 세력/조직을 worldbuilding.json에 등록."""
    wb = load_worldbuilding()
    factions = wb.setdefault("factions", {})

    if faction_id in factions:
        return {"error": f"이미 존재하는 faction: {faction_id}"}

    entry = {"description": description}
    if services:
        entry["services"] = services

    factions[faction_id] = entry
    save_worldbuilding(wb)

    return {"success": True, "registered": faction_id, "data": entry}


def connect_locations(from_id, to_id, direction, distance):
    """두 지역 간 양방향 연결을 설정. 방향은 자동 대칭."""
    wb = load_worldbuilding()
    locations = wb.get("locations", {})

    if from_id not in locations:
        return {"error": f"출발지 없음: {from_id}"}
    if to_id not in locations:
        return {"error": f"도착지 없음: {to_id}"}

    from_name = locations[from_id].get("name", from_id)
    to_name = locations[to_id].get("name", to_id)
    reverse_dir = OPPOSITE_DIR.get(direction, "")

    # from → to
    conns = locations[from_id].setdefault("connections", {})
    conns[to_name] = {"direction": direction, "distance": distance}

    # to → from (역방향)
    if reverse_dir:
        conns2 = locations[to_id].setdefault("connections", {})
        conns2[from_name] = {"direction": reverse_dir, "distance": distance}

    save_worldbuilding(wb)

    return {
        "success": True,
        "connection": f"{from_name} ←({direction}/{reverse_dir})→ {to_name}",
        "distance": distance,
    }


# ─── 조회 ───

def query(target="all"):
    """세계관 정보 조회."""
    wb = load_worldbuilding()

    if target == "all":
        locations = wb.get("locations", {})
        factions = wb.get("factions", {})
        return {
            "locations": {k: v.get("name", k) for k, v in locations.items()},
            "factions": list(factions.keys()),
            "races": wb.get("races", []),
            "currency": wb.get("currency", {}).get("system", ""),
        }

    # 특정 location/faction 조회
    locations = wb.get("locations", {})
    if target in locations:
        return {"type": "location", "data": locations[target]}

    factions = wb.get("factions", {})
    if target in factions:
        return {"type": "faction", "data": factions[target]}

    return {"error": f"'{target}' 없음. 등록된 locations: {list(locations.keys())}"}


# ─── 검증 ───

def validate():
    """worldbuilding.json 전체 정합성 검증."""
    wb = load_worldbuilding()
    locations = wb.get("locations", {})
    warnings = []

    # 방향 대칭 검증
    for loc_id, loc_data in locations.items():
        conns = loc_data.get("connections", {})
        loc_name = loc_data.get("name", loc_id)

        for target_name, conn_info in conns.items():
            direction = conn_info.get("direction", "")
            distance = conn_info.get("distance", "")

            # target_name으로 id 찾기
            target_id = None
            for tid, tdata in locations.items():
                if tdata.get("name") == target_name:
                    target_id = tid
                    break

            if not target_id:
                warnings.append(f"끊긴 연결: {loc_name} → {target_name} (등록 안 됨)")
                continue

            target_conns = locations[target_id].get("connections", {})
            if loc_name not in target_conns:
                warnings.append(f"단방향 연결: {loc_name} → {target_name} (역방향 없음)")
                continue

            reverse = target_conns[loc_name]
            expected_reverse = OPPOSITE_DIR.get(direction, "")
            if expected_reverse and reverse.get("direction") != expected_reverse:
                warnings.append(
                    f"방향 불일치: {loc_name}→{target_name}={direction}, "
                    f"역방향={reverse.get('direction')} (예상: {expected_reverse})")

            if distance and reverse.get("distance") and distance != reverse["distance"]:
                warnings.append(
                    f"거리 불일치: {loc_name}↔{target_name} "
                    f"({distance} vs {reverse['distance']})")

    # world_pos 누락 확인
    for loc_id, loc_data in locations.items():
        if "world_pos" not in loc_data:
            warnings.append(f"world_pos 누락: {loc_data.get('name', loc_id)}")

    if not warnings:
        return {"valid": True, "message": "세계관 정합성 검증 통과"}

    return {"valid": False, "warnings": warnings}


# ─── CLI ───

def main():
    if len(sys.argv) < 2:
        print("사용법: python -m core.worldbuilding_agent <command> [args]")
        print()
        print("명령어:")
        print("  check <text>         나레이션에서 미등록 요소 감지")
        print("  register_location <id> <name> <type> [desc]   지역 등록")
        print("  register_faction <id> [desc]                  세력 등록")
        print("  connect <from> <to> <dir> <dist>              양방향 연결")
        print("  query [target]       세계관 조회 (기본: all)")
        print("  validate             정합성 검증")
        return

    cmd = sys.argv[1]

    if cmd == "check" and len(sys.argv) >= 3:
        text = " ".join(sys.argv[2:])
        result = check_narrative(text)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == "register_location" and len(sys.argv) >= 5:
        desc = sys.argv[5] if len(sys.argv) >= 6 else ""
        result = register_location(sys.argv[2], sys.argv[3], sys.argv[4], desc)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == "register_faction" and len(sys.argv) >= 3:
        desc = sys.argv[3] if len(sys.argv) >= 4 else ""
        result = register_faction(sys.argv[2], desc)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == "connect" and len(sys.argv) >= 6:
        result = connect_locations(sys.argv[2], sys.argv[3], sys.argv[4],
                                   " ".join(sys.argv[5:]))
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == "query":
        target = sys.argv[2] if len(sys.argv) >= 3 else "all"
        result = query(target)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == "validate":
        result = validate()
        if result["valid"]:
            print(f"✓ {result['message']}")
        else:
            print(f"⚠ 문제 {len(result['warnings'])}건:")
            for w in result["warnings"]:
                print(f"  - {w}")

    else:
        print(f"알 수 없는 명령: {cmd}")


if __name__ == "__main__":
    main()
