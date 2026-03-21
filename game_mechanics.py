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


# ─── 경험치 & 레벨업 ───

def _load_entity(state, player_id):
    """엔티티 파일에서 growth 포함 전체 데이터 로드"""
    edir = _entity_dir(state)
    path = os.path.join(edir, f"player_{player_id}.json")
    if os.path.exists(path):
        return _load_json(path), path
    return None, None


def _xp_table():
    """레벨별 필요 XP 테이블"""
    rules = load_rules()
    table = rules.get("level_up", {}).get("xp_table", {})
    return {int(k): v for k, v in table.items()}


def _class_growth(class_name):
    """클래스별 성장 데이터"""
    rules = load_rules()
    return rules.get("level_up", {}).get("class_growth", {}).get(class_name, {})


def grant_xp(player_id, amount, source="", state=None):
    """XP 부여 + 레벨업 자동 체크. 전체 파티에게 줄 때는 grant_xp_party 사용."""
    owned = state is None
    if owned:
        state = load_game_state()

    entity, epath = _load_entity(state, player_id)
    if not entity:
        return {"error": f"엔티티 {player_id} 없음"}

    growth = entity.setdefault("growth", {"level": 1, "xp": 0, "xp_to_next": 100,
                                           "stat_points_available": 0, "learned_skills": [], "xp_log": []})
    growth["xp"] += amount
    growth["xp_log"].append({"source": source, "amount": amount})

    # 레벨업 체크
    leveled = _check_level_up(entity, growth, state)

    if epath:
        _save_json(epath, entity)

    result = {
        "action": "grant_xp", "player": entity["name"],
        "xp_gained": amount, "source": source,
        "total_xp": growth["xp"], "level": growth["level"],
        "xp_to_next": growth["xp_to_next"],
    }
    if leveled:
        result["level_up"] = leveled

    if owned:
        # game_state에도 level 반영
        _sync_level_to_state(state, player_id, growth)
        save_game_state(state)
    return result


def grant_xp_party(amount, source="", state=None):
    """파티 전원에게 동일 XP 부여"""
    owned = state is None
    if owned:
        state = load_game_state()
    results = []
    for p in state["players"]:
        r = grant_xp(p["id"], amount, source, state)
        results.append(r)
    if owned:
        save_game_state(state)
    return {"action": "grant_xp_party", "amount": amount, "source": source, "results": results}


def _check_level_up(entity, growth, state):
    """XP 확인 후 레벨업 처리. 다중 레벨업도 지원."""
    xp_table = _xp_table()
    class_name = entity.get("class", "")
    cg = _class_growth(class_name)
    rules = load_rules()
    stat_points_per_level = rules.get("level_up", {}).get("per_level", {}).get("stat_points", 2)
    leveled_info = []

    while True:
        next_level = growth["level"] + 1
        xp_needed = xp_table.get(next_level)
        if xp_needed is None or growth["xp"] < xp_needed:
            break

        growth["level"] = next_level
        growth["stat_points_available"] += stat_points_per_level

        # HP/MP 증가
        hp_gain = cg.get("hp_per_level", 3)
        mp_gain = cg.get("mp_per_level", 2)
        entity["stats"]["max_hp"] += hp_gain
        entity["stats"]["hp"] += hp_gain  # 레벨업 시 증가분만큼 현재 HP도 회복
        entity["stats"]["max_mp"] += mp_gain
        entity["stats"]["mp"] += mp_gain

        # 신규 스킬 해금 체크
        new_skill = cg.get("skills", {}).get(str(next_level))
        skill_name = None
        if new_skill:
            skill_name = new_skill["name"]
            growth["learned_skills"].append(skill_name)
            # available_actions에도 추가
            actions = entity.get("available_actions", [])
            if skill_name not in actions:
                actions.append(skill_name)
                entity["available_actions"] = actions

        leveled_info.append({
            "new_level": next_level,
            "hp_gain": hp_gain, "mp_gain": mp_gain,
            "stat_points": stat_points_per_level,
            "new_skill": skill_name,
        })

    # 다음 레벨 XP 갱신
    next_next = growth["level"] + 1
    growth["xp_to_next"] = xp_table.get(next_next, 99999)

    return leveled_info if leveled_info else None


def allocate_stats(player_id, stat_increases, state=None):
    """
    레벨업 시 능력치 포인트 배분.
    stat_increases: {"STR": 1, "INT": 1} 같은 딕셔너리
    """
    owned = state is None
    if owned:
        state = load_game_state()

    entity, epath = _load_entity(state, player_id)
    if not entity:
        return {"error": f"엔티티 {player_id} 없음"}

    growth = entity.get("growth", {})
    available = growth.get("stat_points_available", 0)
    total_spend = sum(stat_increases.values())

    if total_spend > available:
        return {"error": f"포인트 부족 (사용: {total_spend}, 보유: {available})"}
    if total_spend <= 0:
        return {"error": "배분할 포인트 없음"}

    # 적용
    old_stats = {}
    for stat, inc in stat_increases.items():
        if stat not in ("STR", "DEX", "INT", "CON"):
            return {"error": f"잘못된 능력치: {stat}"}
        old_stats[stat] = entity["stats"][stat]
        entity["stats"][stat] += inc

    growth["stat_points_available"] -= total_spend

    # HP/MP 재계산 (CON/INT 변동 시)
    hp_mp_changes = _recalc_hp_mp(entity)

    if epath:
        _save_json(epath, entity)

    # game_state 동기화
    player = _find_player(state, player_id)
    if player:
        for stat in ("STR", "DEX", "INT", "CON"):
            player["stats"][stat] = entity["stats"][stat]
        player["max_hp"] = entity["stats"]["max_hp"]
        player["hp"] = entity["stats"]["hp"]
        player["max_mp"] = entity["stats"]["max_mp"]
        player["mp"] = entity["stats"]["mp"]

    if owned:
        save_game_state(state)
        sync_player_to_entity(state, player)

    result = {
        "action": "allocate_stats", "player": entity["name"],
        "allocated": stat_increases,
        "remaining_points": growth["stat_points_available"],
    }
    for stat, inc in stat_increases.items():
        result[f"{stat}"] = f"{old_stats[stat]}→{entity['stats'][stat]}"
    if hp_mp_changes:
        result["hp_mp_recalc"] = hp_mp_changes
    return result


def _recalc_hp_mp(entity):
    """CON/INT 변동 시 max_hp/max_mp 재계산 (클래스 공식 기반)"""
    # character_classes.json에서 공식 로드
    templates_path = os.path.join(BASE_DIR, "templates", "character_classes.json")
    if not os.path.exists(templates_path):
        return None
    templates = _load_json(templates_path)
    class_name = entity.get("class", "")
    class_def = templates.get("classes", {}).get(class_name)
    if not class_def:
        return None

    stats = entity["stats"]
    growth = entity.get("growth", {})
    level = growth.get("level", 1)

    # 기본 공식: base + stat * multiplier + (level-1) * per_level
    cg = _class_growth(class_name)
    hp_base = class_def.get("hp_base", 10)
    hp_per_con = class_def.get("hp_per_con", 0.5)
    mp_base = class_def.get("mp_base", 5)
    mp_per_int = class_def.get("mp_per_int", 0.5)
    hp_per_level = cg.get("hp_per_level", 3)
    mp_per_level = cg.get("mp_per_level", 2)

    new_max_hp = int(hp_base + stats["CON"] * hp_per_con) + (level - 1) * hp_per_level
    new_max_mp = int(mp_base + stats["INT"] * mp_per_int) + (level - 1) * mp_per_level

    changes = {}
    if new_max_hp != stats["max_hp"]:
        diff = new_max_hp - stats["max_hp"]
        stats["max_hp"] = new_max_hp
        stats["hp"] = min(stats["hp"] + max(0, diff), new_max_hp)
        changes["max_hp"] = new_max_hp
    if new_max_mp != stats["max_mp"]:
        diff = new_max_mp - stats["max_mp"]
        stats["max_mp"] = new_max_mp
        stats["mp"] = min(stats["mp"] + max(0, diff), new_max_mp)
        changes["max_mp"] = new_max_mp

    return changes if changes else None


def _sync_level_to_state(state, player_id, growth):
    """game_state 플레이어에 level/xp 필드 반영"""
    player = _find_player(state, player_id)
    if player:
        player["level"] = growth["level"]
        player["xp"] = growth["xp"]
        # 엔티티에서 max_hp/max_mp도 동기화
        entity, _ = _load_entity(state, player_id)
        if entity:
            player["max_hp"] = entity["stats"]["max_hp"]
            player["hp"] = min(player["hp"], player["max_hp"])
            player["max_mp"] = entity["stats"]["max_mp"]
            player["mp"] = min(player["mp"], player["max_mp"])


def growth_status(state=None):
    """파티 전원 성장 상태 요약"""
    if state is None:
        state = load_game_state()
    results = []
    for p in state["players"]:
        entity, _ = _load_entity(state, p["id"])
        if not entity:
            continue
        growth = entity.get("growth", {})
        cg = _class_growth(entity.get("class", ""))
        skills_at = {int(k): v["name"] for k, v in cg.get("skills", {}).items()}
        next_skill_level = None
        next_skill_name = None
        for lv in sorted(skills_at.keys()):
            if lv > growth.get("level", 1):
                next_skill_level = lv
                next_skill_name = skills_at[lv]
                break
        results.append({
            "name": entity["name"], "class": entity.get("class"),
            "level": growth.get("level", 1),
            "xp": growth.get("xp", 0),
            "xp_to_next": growth.get("xp_to_next", 100),
            "stat_points": growth.get("stat_points_available", 0),
            "learned_skills": growth.get("learned_skills", []),
            "next_skill": f"Lv{next_skill_level}: {next_skill_name}" if next_skill_name else "—",
        })
    return results


# ─── 파티 상태 요약 ───

def party_status(state=None):
    """파티 전원 HP/MP/상태이상 요약"""
    if state is None:
        state = load_game_state()
    summary = []
    for p in state["players"]:
        summary.append({
            "id": p["id"], "name": p["name"], "class": p["class"],
            "level": p.get("level", 1),
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
        print()
        print("  [성장 시스템]")
        print("  growth                 파티 성장 상태")
        print("  xp <pid> <amount> [source]  XP 부여")
        print("  xp_party <amount> [source]  파티 전원 XP")
        print("  alloc <pid> <STAT> <n>  능력치 배분 (예: alloc 1 INT 2)")
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

    elif cmd == "growth":
        for g in growth_status():
            pts = f" [배분 가능: {g['stat_points']}pt]" if g['stat_points'] > 0 else ""
            skills = f" 습득: {', '.join(g['learned_skills'])}" if g['learned_skills'] else ""
            print(f"  {g['name']}({g['class']}) Lv{g['level']} XP:{g['xp']}/{g['xp_to_next']}{pts}{skills}")
            print(f"    다음 스킬: {g['next_skill']}")

    elif cmd == "xp" and len(sys.argv) >= 4:
        source = sys.argv[4] if len(sys.argv) >= 5 else ""
        _print_result(grant_xp(int(sys.argv[2]), int(sys.argv[3]), source))

    elif cmd == "xp_party" and len(sys.argv) >= 3:
        source = sys.argv[3] if len(sys.argv) >= 4 else ""
        _print_result(grant_xp_party(int(sys.argv[2]), source))

    elif cmd == "alloc" and len(sys.argv) >= 5:
        _print_result(allocate_stats(int(sys.argv[2]), {sys.argv[3]: int(sys.argv[4])}))

    else:
        print(f"알 수 없는 명령: {cmd}")
        print("python game_mechanics.py --help 로 사용법 확인")


if __name__ == "__main__":
    main()
