"""
게임 메카닉 자동화 엔진
- 주사위, 판정, 전투, 회복, 아이템, 상태이상 처리
- CLI에서 직접 호출 가능 (python game_mechanics.py <command>)
- app.py gm-update에서도 연동 가능
"""

import json
import math
import os
import random
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GAME_STATE_PATH = os.path.join(BASE_DIR, "game_state.json")
RULES_PATH = os.path.join(BASE_DIR, "rules.json")


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_rules():
    return _load_json(RULES_PATH)


def load_game_state():
    return _load_json(GAME_STATE_PATH)


def save_game_state(state):
    _save_json(GAME_STATE_PATH, state)


# ─── 엔티티 파일 동기화 ───

def _entity_dir(state):
    sid = state.get("game_info", {}).get("scenario_id", "default")
    return os.path.join(BASE_DIR, "entities", sid, "players")


def sync_player_to_entity(state, player):
    """game_state의 플레이어 데이터를 entities/ 파일에 반영"""
    edir = _entity_dir(state)
    path = os.path.join(edir, f"player_{player['id']}.json")
    if not os.path.exists(path):
        return
    entity = _load_json(path)
    entity["stats"]["hp"] = player["hp"]
    entity["stats"]["max_hp"] = player["max_hp"]
    entity["stats"]["mp"] = player["mp"]
    entity["stats"]["max_mp"] = player["max_mp"]
    entity["position"] = player.get("position", entity.get("position"))
    entity["status_effects"] = player.get("status_effects", [])
    entity["inventory"] = player.get("inventory", entity.get("inventory", []))
    _save_json(path, entity)


def sync_all_players(state):
    """모든 플레이어를 엔티티 파일에 동기화"""
    for p in state.get("players", []):
        sync_player_to_entity(state, p)


# ─── 주사위 ───

def roll_dice(dice_str):
    """'NdM' 형식 파싱 후 굴림. 예: '2d6' → [3, 5]"""
    count, sides = dice_str.lower().split("d")
    count = int(count) if count else 1
    sides = int(sides)
    return [random.randint(1, sides) for _ in range(count)]


def roll(dice_str):
    """주사위 합계 반환"""
    return sum(roll_dice(dice_str))


# ─── 능력치 보정값 ───

def stat_modifier(stat_value):
    """(능력치 - 10) / 2 내림"""
    return math.floor((stat_value - 10) / 2)


def get_player_modifier(player, stat_name):
    """플레이어의 특정 능력치 보정값"""
    stats = player.get("stats", player)
    val = stats.get(stat_name, 10)
    return stat_modifier(val)


# ─── 방어력 계산 ───

ARMOR_BONUS = {
    "가죽 방패": 2,
    "철 방패": 3,
    "판금 갑옷": 4,
}


def calculate_ac(player):
    """방어력 = 10 + DEX 보정 + 장비 보너스"""
    dex_mod = get_player_modifier(player, "DEX")
    armor = 0
    for item in player.get("inventory", []):
        armor = max(armor, ARMOR_BONUS.get(item, 0))
    # 상태이상 방어강화 체크
    for eff in player.get("status_effects", []):
        if isinstance(eff, dict) and eff.get("name") == "방어 강화":
            armor += 4
        elif eff == "방어 강화":
            armor += 4
    return 10 + dex_mod + armor


# ─── 휴식 & 회복 ───

def long_rest(state=None):
    """긴 휴식 — HP/MP 전부 회복. state 없으면 파일에서 로드."""
    owned = state is None
    if owned:
        state = load_game_state()
    results = []
    for p in state["players"]:
        old_hp, old_mp = p["hp"], p["mp"]
        p["hp"] = p["max_hp"]
        p["mp"] = p["max_mp"]
        results.append({
            "id": p["id"], "name": p["name"],
            "hp": f"{old_hp}→{p['hp']}/{p['max_hp']}",
            "mp": f"{old_mp}→{p['mp']}/{p['max_mp']}",
        })
    if owned:
        save_game_state(state)
        sync_all_players(state)
    return {"action": "long_rest", "results": results}


def short_rest(state=None):
    """짧은 휴식 — HP +5, MP +3"""
    owned = state is None
    if owned:
        state = load_game_state()
    rules = load_rules()
    heal_hp = rules["rest"]["short_rest"]["heal_hp"]
    heal_mp = rules["rest"]["short_rest"]["heal_mp"]
    results = []
    for p in state["players"]:
        old_hp, old_mp = p["hp"], p["mp"]
        p["hp"] = min(p["hp"] + heal_hp, p["max_hp"])
        p["mp"] = min(p["mp"] + heal_mp, p["max_mp"])
        results.append({
            "id": p["id"], "name": p["name"],
            "hp": f"{old_hp}→{p['hp']}/{p['max_hp']}",
            "mp": f"{old_mp}→{p['mp']}/{p['max_mp']}",
        })
    if owned:
        save_game_state(state)
        sync_all_players(state)
    return {"action": "short_rest", "results": results}


# ─── 아이템 사용 ───

def use_item(player_id, item_name, state=None):
    """아이템 사용 — 인벤토리에서 제거 + 효과 적용"""
    owned = state is None
    if owned:
        state = load_game_state()
    rules = load_rules()
    item_defs = rules["rest"]["use_item"]

    player = _find_player(state, player_id)
    if not player:
        return {"error": f"플레이어 {player_id} 없음"}

    if item_name not in player.get("inventory", []):
        return {"error": f"'{item_name}' 소지하지 않음"}

    if item_name not in item_defs:
        return {"error": f"'{item_name}' 사용 효과 미정의"}

    effect = item_defs[item_name]
    old_hp, old_mp = player["hp"], player["mp"]

    if "heal_hp" in effect:
        player["hp"] = min(player["hp"] + effect["heal_hp"], player["max_hp"])
    if "heal_mp" in effect:
        player["mp"] = min(player["mp"] + effect["heal_mp"], player["max_mp"])

    player["inventory"].remove(item_name)

    result = {
        "action": "use_item", "player": player["name"], "item": item_name,
        "effect": effect.get("description", ""),
        "hp": f"{old_hp}→{player['hp']}/{player['max_hp']}",
        "mp": f"{old_mp}→{player['mp']}/{player['max_mp']}",
    }
    if owned:
        save_game_state(state)
        sync_player_to_entity(state, player)
    return result


# ─── 전투: 공격 판정 ───

def attack_roll(attacker_id, target_id, action_name="공격", state=None):
    """
    공격 판정 자동 처리.
    반환: {hit, critical, fumble, attack_total, ac, damage, rolls, ...}
    """
    owned = state is None
    if owned:
        state = load_game_state()
    rules = load_rules()

    attacker = _find_entity(state, attacker_id)
    target = _find_entity(state, target_id)
    if not attacker or not target:
        return {"error": "공격자 또는 대상 없음"}

    action_def = rules["actions"].get(action_name)
    if not action_def:
        return {"error": f"액션 '{action_name}' 미정의"}

    # 명중 판정
    d20 = roll("1d20")
    critical = d20 == 20
    fumble = d20 == 1

    # 공격 보정값 결정
    stat_name = _attack_stat(action_def)
    atk_mod = _get_modifier(attacker, stat_name)
    attack_total = d20 + atk_mod

    # 대상 AC
    ac = calculate_ac(target) if _is_player(state, target_id) else _npc_ac(target)

    result = {
        "action": action_name,
        "attacker": attacker.get("name", str(attacker_id)),
        "target": target.get("name", str(target_id)),
        "d20": d20, "modifier": atk_mod, "attack_total": attack_total,
        "ac": ac, "critical": critical, "fumble": fumble,
        "hit": False, "damage": 0, "damage_rolls": [],
    }

    if fumble:
        result["hit"] = False
        result["note"] = "펌블! 자동 실패 + 다음 턴 -2"
        # 펌블 패널티 적용
        _apply_status(attacker, "펌블", 1)
    elif critical or attack_total >= ac:
        result["hit"] = True
        # 데미지 굴림
        dmg_dice = _damage_dice(action_def)
        dmg_rolls = roll_dice(dmg_dice)
        dmg_mod = atk_mod
        damage = sum(dmg_rolls) + dmg_mod
        if critical:
            damage *= 2
            result["note"] = "크리티컬! 데미지 2배"
        damage = max(1, damage)
        result["damage"] = damage
        result["damage_rolls"] = dmg_rolls

        # MP 소모
        mp_cost = action_def.get("cost", {}).get("mp", 0)
        if mp_cost > 0 and _is_player(state, attacker_id):
            attacker["mp"] = max(0, attacker["mp"] - mp_cost)
            result["mp_cost"] = mp_cost

        # 데미지 적용
        target["hp"] = max(0, target.get("hp", 0) - damage)
        if target["hp"] <= 0:
            target["status"] = "dead"
            result["target_dead"] = True

    if owned:
        save_game_state(state)
        sync_all_players(state)
    return result


def skill_check(player_id, stat_name, dc, state=None):
    """
    능력치 판정 (비전투). 예: INT DC 14
    반환: {success, d20, modifier, total, dc, critical, fumble}
    """
    owned = state is None
    if owned:
        state = load_game_state()

    player = _find_player(state, player_id)
    if not player:
        return {"error": f"플레이어 {player_id} 없음"}

    d20 = roll("1d20")
    mod = get_player_modifier(player, stat_name)
    total = d20 + mod

    return {
        "action": "skill_check",
        "player": player["name"],
        "stat": stat_name, "dc": dc,
        "d20": d20, "modifier": mod, "total": total,
        "success": d20 == 20 or (d20 != 1 and total >= dc),
        "critical": d20 == 20,
        "fumble": d20 == 1,
    }


# ─── 데미지 & 힐 직접 적용 ───

def apply_damage(target_id, damage, source="", state=None):
    """대상에게 직접 데미지 적용"""
    owned = state is None
    if owned:
        state = load_game_state()
    target = _find_entity(state, target_id)
    if not target:
        return {"error": f"대상 {target_id} 없음"}
    old_hp = target["hp"]
    target["hp"] = max(0, target["hp"] - damage)
    dead = target["hp"] <= 0
    if dead and "status" in target:
        target["status"] = "dead"
    result = {
        "target": target.get("name", str(target_id)),
        "damage": damage, "source": source,
        "hp": f"{old_hp}→{target['hp']}/{target.get('max_hp', '?')}",
        "dead": dead,
    }
    if owned:
        save_game_state(state)
        sync_all_players(state)
    return result


def apply_heal(player_id, amount, source="", state=None):
    """대상 HP 회복"""
    owned = state is None
    if owned:
        state = load_game_state()
    player = _find_player(state, player_id)
    if not player:
        return {"error": f"플레이어 {player_id} 없음"}
    old_hp = player["hp"]
    player["hp"] = min(player["hp"] + amount, player["max_hp"])
    result = {
        "player": player["name"], "heal": amount, "source": source,
        "hp": f"{old_hp}→{player['hp']}/{player['max_hp']}",
    }
    if owned:
        save_game_state(state)
        sync_player_to_entity(state, player)
    return result


def cast_heal(caster_id, target_id, state=None):
    """힐 마법 시전 — MP 소모 + 1d8+INT 회복"""
    owned = state is None
    if owned:
        state = load_game_state()
    rules = load_rules()
    action_def = rules["actions"]["힐"]
    mp_cost = action_def["cost"]["mp"]

    caster = _find_player(state, caster_id)
    if not caster:
        return {"error": f"시전자 {caster_id} 없음"}
    if caster["mp"] < mp_cost:
        return {"error": f"MP 부족 ({caster['mp']}/{mp_cost})"}

    target = _find_player(state, target_id)
    if not target:
        return {"error": f"대상 {target_id} 없음"}

    heal_roll = roll_dice("1d8")
    int_mod = get_player_modifier(caster, "INT")
    amount = sum(heal_roll) + int_mod
    amount = max(1, amount)

    caster["mp"] -= mp_cost
    old_hp = target["hp"]
    target["hp"] = min(target["hp"] + amount, target["max_hp"])

    result = {
        "action": "힐", "caster": caster["name"], "target": target["name"],
        "roll": heal_roll, "modifier": int_mod, "amount": amount,
        "mp_cost": mp_cost, "caster_mp": f"{caster['mp']}/{caster['max_mp']}",
        "hp": f"{old_hp}→{target['hp']}/{target['max_hp']}",
    }
    if owned:
        save_game_state(state)
        sync_all_players(state)
    return result


# ─── 상태이상 틱 처리 ───

def tick_status_effects(state=None):
    """턴 종료 시 상태이상 처리 — 지속 데미지, 지속시간 감소, 만료 제거"""
    owned = state is None
    if owned:
        state = load_game_state()
    rules = load_rules()
    effect_defs = rules.get("status_effects", {})
    results = []

    for p in state["players"]:
        remaining = []
        for eff in p.get("status_effects", []):
            name = eff if isinstance(eff, str) else eff.get("name", "")
            duration = 1 if isinstance(eff, str) else eff.get("duration", 1)
            edef = effect_defs.get(name, {})

            # 지속 데미지
            dot = edef.get("damage_per_turn", 0)
            if dot > 0:
                p["hp"] = max(0, p["hp"] - dot)
                results.append({"player": p["name"], "effect": name, "damage": dot, "hp": p["hp"]})

            # 지속시간 감소
            new_dur = duration - 1
            if new_dur > 0:
                remaining.append({"name": name, "duration": new_dur})
            else:
                results.append({"player": p["name"], "effect": name, "expired": True})

        p["status_effects"] = remaining

    if owned:
        save_game_state(state)
        sync_all_players(state)
    return {"action": "tick_status", "results": results}


# ─── 이니셔티브 (턴 순서) ───

def roll_initiative(state=None):
    """DEX 기반 이니셔티브 굴림. 동률 시 플레이어 우선."""
    if state is None:
        state = load_game_state()

    entries = []
    for p in state["players"]:
        dex_mod = get_player_modifier(p, "DEX")
        init = roll("1d20") + dex_mod
        entries.append({"id": p["id"], "name": p["name"], "type": "player", "initiative": init})

    for n in state.get("npcs", []):
        if n.get("status") == "dead" or n.get("hp", 0) <= 0:
            continue
        dex = n.get("stats", {}).get("DEX", 10) if "stats" in n else 10
        init = roll("1d20") + stat_modifier(dex)
        entries.append({"id": n["id"], "name": n["name"], "type": "npc", "initiative": init})

    # 정렬: 이니셔티브 높은 순, 동률 시 플레이어 우선
    entries.sort(key=lambda e: (-e["initiative"], 0 if e["type"] == "player" else 1))
    return {"action": "initiative", "order": entries}


# ─── MP 소모 검증 ───

def check_mp(player_id, action_name, state=None):
    """액션 MP 비용 확인 + 충분한지 체크"""
    if state is None:
        state = load_game_state()
    rules = load_rules()
    action_def = rules["actions"].get(action_name)
    if not action_def:
        return {"error": f"액션 '{action_name}' 미정의"}
    mp_cost = action_def.get("cost", {}).get("mp", 0)
    player = _find_player(state, player_id)
    if not player:
        return {"error": f"플레이어 {player_id} 없음"}
    return {
        "action": action_name, "player": player["name"],
        "mp_cost": mp_cost, "current_mp": player["mp"],
        "can_use": player["mp"] >= mp_cost,
    }


# ─── 파티 상태 요약 ───

def party_status(state=None):
    """파티 전원 HP/MP/상태이상 요약"""
    if state is None:
        state = load_game_state()
    summary = []
    for p in state["players"]:
        summary.append({
            "id": p["id"], "name": p["name"], "class": p["class"],
            "hp": f"{p['hp']}/{p['max_hp']}",
            "mp": f"{p['mp']}/{p['max_mp']}",
            "ac": calculate_ac(p),
            "status_effects": p.get("status_effects", []),
            "inventory": p.get("inventory", []),
        })
    return summary


# ─── 내부 헬퍼 ───

def _find_player(state, pid):
    for p in state["players"]:
        if p["id"] == pid:
            return p
    return None


def _find_npc(state, nid):
    for n in state.get("npcs", []):
        if n["id"] == nid:
            return n
    return None


def _find_entity(state, eid):
    return _find_player(state, eid) or _find_npc(state, eid)


def _is_player(state, eid):
    return _find_player(state, eid) is not None


def _get_modifier(entity, stat_name):
    stats = entity.get("stats", entity)
    val = stats.get(stat_name, 10)
    return stat_modifier(val)


def _attack_stat(action_def):
    atype = action_def.get("type", "")
    if "magic" in atype:
        return "INT"
    roll_str = action_def.get("roll", "")
    if "INT" in roll_str:
        return "INT"
    if "DEX" in roll_str:
        return "DEX"
    return "STR"


def _damage_dice(action_def):
    dmg = action_def.get("damage", "1d6")
    return dmg.split("+")[0].strip()


def _npc_ac(npc):
    defense = npc.get("defense", 0)
    if defense > 0:
        return defense + 10
    return 10


def _apply_status(entity, name, duration):
    effects = entity.get("status_effects", [])
    effects.append({"name": name, "duration": duration})
    entity["status_effects"] = effects


# ─── CLI 인터페이스 ───

def _print_result(result):
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    if len(sys.argv) < 2:
        print("사용법: python game_mechanics.py <command> [args]")
        print()
        print("명령어:")
        print("  long_rest              하룻밤 수면 (HP/MP 전부 회복)")
        print("  short_rest             짧은 휴식 (HP +5, MP +3)")
        print("  status                 파티 상태 요약")
        print("  use_item <pid> <item>  아이템 사용")
        print("  roll <NdM>             주사위 굴림")
        print("  check <pid> <stat> <dc>  능력치 판정")
        print("  attack <atk> <tgt> [action]  공격 판정")
        print("  heal <caster> <target>  힐 마법")
        print("  damage <tid> <amount>   직접 데미지")
        print("  initiative             이니셔티브 굴림")
        print("  tick                   상태이상 턴 처리")
        return

    cmd = sys.argv[1]

    if cmd == "long_rest":
        _print_result(long_rest())

    elif cmd == "short_rest":
        _print_result(short_rest())

    elif cmd == "status":
        for p in party_status():
            print(f"  {p['name']}({p['class']}) HP:{p['hp']} MP:{p['mp']} AC:{p['ac']} {p['status_effects'] or ''}")

    elif cmd == "use_item" and len(sys.argv) >= 4:
        _print_result(use_item(int(sys.argv[2]), sys.argv[3]))

    elif cmd == "roll" and len(sys.argv) >= 3:
        dice = sys.argv[2]
        rolls = roll_dice(dice)
        print(f"🎲 {dice} → {rolls} = {sum(rolls)}")

    elif cmd == "check" and len(sys.argv) >= 5:
        _print_result(skill_check(int(sys.argv[2]), sys.argv[3], int(sys.argv[4])))

    elif cmd == "attack" and len(sys.argv) >= 4:
        action = sys.argv[4] if len(sys.argv) >= 5 else "공격"
        _print_result(attack_roll(int(sys.argv[2]), int(sys.argv[3]), action))

    elif cmd == "heal" and len(sys.argv) >= 4:
        _print_result(cast_heal(int(sys.argv[2]), int(sys.argv[3])))

    elif cmd == "damage" and len(sys.argv) >= 4:
        _print_result(apply_damage(int(sys.argv[2]), int(sys.argv[3])))

    elif cmd == "initiative":
        result = roll_initiative()
        for i, e in enumerate(result["order"], 1):
            print(f"  {i}. {e['name']} ({e['type']}) — 이니셔티브 {e['initiative']}")

    elif cmd == "tick":
        _print_result(tick_status_effects())

    else:
        print(f"알 수 없는 명령: {cmd}")
        print("python game_mechanics.py --help 로 사용법 확인")


if __name__ == "__main__":
    main()
