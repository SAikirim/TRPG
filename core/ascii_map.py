import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import json
import os
import math

# ─────────────────────────────────────────
#  ANSI 색상 코드
# ─────────────────────────────────────────
BOLD   = "\033[1m"
RED    = "\033[31m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
BLUE   = "\033[34m"
PURPLE = "\033[35m"
CYAN   = "\033[36m"
GRAY   = "\033[90m"
RESET  = "\033[0m"

# ─────────────────────────────────────────
#  헬퍼
# ─────────────────────────────────────────

def _bar(current, maximum, width=10, fill_ch='█', empty_ch='░'):
    """HP/MP 막대 생성."""
    if maximum <= 0:
        ratio = 0.0
    else:
        ratio = max(0.0, min(1.0, current / maximum))
    filled = round(ratio * width)
    return fill_ch * filled + empty_ch * (width - filled)


def _section(title, color=CYAN):
    """구분선 + 제목 출력."""
    line = '═' * 60
    print(f"{color}{BOLD}╔{line}╗{RESET}")
    pad = (60 - len(title)) // 2
    print(f"{color}{BOLD}║{' ' * pad}{title}{' ' * (60 - pad - len(title))}║{RESET}")
    print(f"{color}{BOLD}╚{line}╝{RESET}")


def _hline(color=GRAY):
    print(f"{color}{'─' * 62}{RESET}")


# ─────────────────────────────────────────
#  1. show_map(state)
# ─────────────────────────────────────────

# 지형 타입 → (색상, 문자)
TERRAIN_STYLE = {
    'grass':    (GREEN,  '::'),
    'dungeon':  (GRAY,   '##'),
    'treasure': (YELLOW, '$$'),
    'default':  (RESET,  '..'),
}

# 클래스 → (색상, 기호)
PLAYER_STYLE = {
    '마법사': (BLUE,   'Mg'),
    '도적':   (GREEN,  'Rg'),
    '전사':   (RED,    'Wr'),
    'default':(CYAN,   'Pl'),
}


def show_map(state):
    """game_state의 map + players + npcs 기반 ASCII 맵 출력."""
    _section('[ ASCII 맵 ]', CYAN)

    map_info   = state.get('map', {})
    width      = map_info.get('width', 20)
    height     = map_info.get('height', 15)
    locations  = map_info.get('locations', [])
    players    = state.get('players', [])
    npcs       = state.get('npcs', [])

    # 격자 초기화: 각 셀 (color, char)
    grid_color = [[RESET] * width for _ in range(height)]
    grid_char  = [['..'] * width for _ in range(height)]

    # 지형 칠하기 (위에 올라오는 순서: locations 순)
    for loc in locations:
        area = loc.get('area', {})
        x1, y1 = area.get('x1', 0), area.get('y1', 0)
        x2, y2 = area.get('x2', width - 1), area.get('y2', height - 1)
        ltype  = loc.get('type', 'default')
        col, ch = TERRAIN_STYLE.get(ltype, TERRAIN_STYLE['default'])
        for row in range(y1, min(y2 + 1, height)):
            for col_i in range(x1, min(x2 + 1, width)):
                grid_color[row][col_i] = col
                grid_char[row][col_i]  = ch

    # 단일 타일 랜드마크 표시
    LANDMARK_STYLE = {
        '우물': (CYAN, '💧'),
        '모닥불': (RED, '🔥'),
        '이정표': (YELLOW, '📌'),
        '제단': (PURPLE, '⛩️'),
        '샘': (CYAN, '💧'),
        '화톳불': (RED, '🔥'),
        '표지판': (YELLOW, '📌'),
    }
    for loc in locations:
        area = loc.get('area', {})
        if area.get('x1') == area.get('x2') and area.get('y1') == area.get('y2'):
            name = loc.get('name', '')
            for keyword, (col, sym) in LANDMARK_STYLE.items():
                if keyword in name:
                    x, y = area['x1'], area['y1']
                    if 0 <= x < width and 0 <= y < height:
                        grid_color[y][x] = col
                        grid_char[y][x] = sym
                    break

    # NPC 배치
    for npc in npcs:
        pos = npc.get('position')
        if not pos or len(pos) < 2:
            continue
        px, py = int(pos[0]), int(pos[1])
        if 0 <= px < width and 0 <= py < height:
            if npc.get('status') == 'dead':
                grid_color[py][px] = GRAY
                grid_char[py][px]  = 'XX'
            else:
                grid_color[py][px] = RED
                grid_char[py][px]  = '!!'

    # 플레이어 배치
    for pl in players:
        pos = pl.get('position')
        if not pos or len(pos) < 2:
            continue
        px, py = int(pos[0]), int(pos[1])
        if 0 <= px < width and 0 <= py < height:
            cls = pl.get('class', 'default')
            col, sym = PLAYER_STYLE.get(cls, PLAYER_STYLE['default'])
            grid_color[py][px] = col
            grid_char[py][px]  = sym

    # X축 헤더
    header_tens = '   '
    header_ones = '   '
    for x in range(width):
        header_tens += ' ' if x < 10 else str(x // 10)
        header_tens += ' '
        header_ones += str(x % 10)
        header_ones += ' '
    print(f"{GRAY}{header_tens}{RESET}")
    print(f"{GRAY}{header_ones}{RESET}")

    # 테두리 위
    print(f"{GRAY}  ┌{'──' * width}┐{RESET}")

    # 맵 본체
    for row in range(height):
        line = f"{GRAY}{row:2d}│{RESET}"
        for col_i in range(width):
            col = grid_color[row][col_i]
            ch  = grid_char[row][col_i]
            line += f"{col}{BOLD}{ch}{RESET}"
        line += f"{GRAY}│{row:<2d}{RESET}"
        print(line)

    # 테두리 아래
    print(f"{GRAY}  └{'──' * width}┘{RESET}")

    # 범례
    print()
    print(f"  {BOLD}범례:{RESET}")
    print(f"  {BLUE}{BOLD}Mg{RESET}=마법사  {GREEN}{BOLD}Rg{RESET}=도적  {RED}{BOLD}Wr{RESET}=전사")
    print(f"  {RED}{BOLD}!!{RESET}=NPC(생존)  {GRAY}{BOLD}XX{RESET}=NPC(사망)")
    print(f"  {GREEN}{BOLD}::{RESET}=숲  {GRAY}{BOLD}##{RESET}=던전  {YELLOW}{BOLD}$${RESET}=보물실  {RESET}..=기타")
    print(f"  💧=우물  🔥=모닥불  🪧=이정표")

    # 지역명 표시
    if locations:
        print()
        print(f"  {BOLD}지역:{RESET}")
        for loc in locations:
            area  = loc.get('area', {})
            ltype = loc.get('type', 'default')
            col, ch = TERRAIN_STYLE.get(ltype, TERRAIN_STYLE['default'])
            name  = loc.get('name', '?')
            print(f"  {col}{BOLD}{ch}{RESET} {name}  "
                  f"({GRAY}x{area.get('x1')}-{area.get('x2')}, "
                  f"y{area.get('y1')}-{area.get('y2')}{RESET})")
    print()


# ─────────────────────────────────────────
#  2. show_dice_roll(...)
# ─────────────────────────────────────────

_D20_ART = [
    "      /\\      ",
    "     /  \\     ",
    "    / {v:2} \\    ",
    "   /______\\   ",
    "   \\      /   ",
    "    \\    /    ",
    "     \\  /     ",
    "      \\/      ",
]


def show_dice_roll(name, roll, modifier, modifier_label, ac, dice_type='d20'):
    """주사위 판정 결과 출력."""
    _section(f'[ {dice_type} 판정 — {name} ]', PURPLE)

    total = roll + modifier
    is_crit = (dice_type == 'd20' and roll == 20)
    is_fail = (dice_type == 'd20' and roll == 1)
    hit     = total >= ac

    # 색상 선택
    if is_crit:
        color = YELLOW
        result_str = f"{YELLOW}{BOLD}★ 크리티컬! ★{RESET}"
    elif is_fail:
        color = RED
        result_str = f"{RED}{BOLD}✗ 대실패!{RESET}"
    elif hit:
        color = GREEN
        result_str = f"{GREEN}{BOLD}명중!{RESET}"
    else:
        color = GRAY
        result_str = f"{GRAY}빗나감{RESET}"

    # d20 ASCII 아트 (값 삽입)
    print()
    for i, row_tmpl in enumerate(_D20_ART):
        row = row_tmpl.format(v=roll) if '{v' in row_tmpl else row_tmpl
        print(f"  {color}{BOLD}{row}{RESET}")

    print()
    # 계산식
    mod_sign = '+' if modifier >= 0 else '-'
    print(f"  {BOLD}주사위{RESET} : {color}{BOLD}{roll:2d}{RESET}  "
          f"({dice_type})")
    print(f"  {BOLD}수정치{RESET} : {mod_sign}{abs(modifier):2d}  "
          f"({modifier_label})")
    print(f"  {'─' * 28}")
    print(f"  {BOLD}합 계 {RESET} : {color}{BOLD}{total:2d}{RESET}  "
          f"vs  AC {BOLD}{ac}{RESET}")
    print()
    print(f"  결과 → {result_str}")
    print()


# ─────────────────────────────────────────
#  3. show_damage(dice_results, modifier, crit=False)
# ─────────────────────────────────────────

# d6 눈금 아트: 인덱스 1~6
_D6_FACES = {
    1: ["┌─────┐",
        "│     │",
        "│  ●  │",
        "│     │",
        "└─────┘"],
    2: ["┌─────┐",
        "│ ●   │",
        "│     │",
        "│   ● │",
        "└─────┘"],
    3: ["┌─────┐",
        "│ ●   │",
        "│  ●  │",
        "│   ● │",
        "└─────┘"],
    4: ["┌─────┐",
        "│ ● ● │",
        "│     │",
        "│ ● ● │",
        "└─────┘"],
    5: ["┌─────┐",
        "│ ● ● │",
        "│  ●  │",
        "│ ● ● │",
        "└─────┘"],
    6: ["┌─────┐",
        "│ ● ● │",
        "│ ● ● │",
        "│ ● ● │",
        "└─────┘"],
}


def show_damage(dice_results, modifier, crit=False):
    """피해 굴림 출력 (d6 눈금 아트 포함)."""
    _section('[ 피해 굴림 ]', RED)

    base_sum = sum(dice_results)
    total    = (base_sum + modifier) * (2 if crit else 1)

    # d6 아트 가로 배치
    faces = [_D6_FACES.get(max(1, min(6, v)), _D6_FACES[1]) for v in dice_results]
    if faces:
        rows = len(faces[0])
        print()
        for r in range(rows):
            line = '  '
            for face in faces:
                line += f"{RED}{BOLD}{face[r]}{RESET}  "
            print(line)
        print()

    # 주사위 값 나열
    dice_str = ' + '.join(str(v) for v in dice_results)
    mod_sign = '+' if modifier >= 0 else '-'
    print(f"  주사위  : {RED}{BOLD}{dice_str}{RESET}  = {base_sum}")
    print(f"  수정치  : {mod_sign}{abs(modifier)}")
    if crit:
        print(f"  {YELLOW}{BOLD}크리티컬! × 2배{RESET}")
    print(f"  {'─' * 30}")
    crit_mark = f"  {YELLOW}{BOLD}[크리!]{RESET} " if crit else "  "
    print(f"{crit_mark}{BOLD}총 피해 : {RED}{BOLD}{total}{RESET}")
    print()


# ─────────────────────────────────────────
#  4. show_party(state)
# ─────────────────────────────────────────

def show_party(state):
    """파티 전원 상태 출력."""
    _section('[ 파티 상태 ]', GREEN)

    players = state.get('players', [])
    if not players:
        print(f"  {GRAY}파티원 없음{RESET}\n")
        return

    for pl in players:
        cls   = pl.get('class', '?')
        col, sym = PLAYER_STYLE.get(cls, PLAYER_STYLE['default'])
        name  = pl.get('name', '?')
        pos   = pl.get('position', ['?', '?'])

        hp     = pl.get('hp', 0)
        max_hp = pl.get('max_hp', 1)
        mp     = pl.get('mp', 0)
        max_mp = pl.get('max_mp', 1)

        inventory     = pl.get('inventory', [])
        status_effects = pl.get('status_effects', [])
        controlled    = pl.get('controlled_by', '?')

        # 헤더
        print(f"  {col}{BOLD}[{sym}] {name}{RESET}  "
              f"({cls})  위치: ({pos[0]},{pos[1]})  "
              f"{GRAY}조작: {controlled}{RESET}")

        # HP 바
        hp_pct  = hp / max_hp if max_hp > 0 else 0
        hp_col  = RED if hp_pct <= 0.3 else (YELLOW if hp_pct <= 0.6 else GREEN)
        hp_bar  = _bar(hp, max_hp, width=12)
        print(f"    HP : {hp_col}{BOLD}{hp_bar}{RESET}  {hp}/{max_hp}")

        # MP 바 (MP가 있는 경우만)
        if max_mp > 0:
            mp_bar = _bar(mp, max_mp, width=12)
            print(f"    MP : {BLUE}{BOLD}{mp_bar}{RESET}  {mp}/{max_mp}")

        # 소지품
        if inventory:
            inv_str = ', '.join(inventory)
            print(f"    소지: {CYAN}{inv_str}{RESET}")
        else:
            print(f"    소지: {GRAY}없음{RESET}")

        # 상태이상
        if status_effects:
            eff_str = ', '.join(str(e) for e in status_effects)
            print(f"    상태: {RED}{BOLD}{eff_str}{RESET}")

        _hline()

    print()


# ─────────────────────────────────────────
#  5. show_event_log(state, n=5)
# ─────────────────────────────────────────

def show_event_log(state, n=5):
    """최근 이벤트 n개 출력."""
    _section(f'[ 이벤트 로그 (최근 {n}턴) ]', YELLOW)

    events = state.get('events', [])
    recent = events[-n:] if len(events) >= n else events

    if not recent:
        print(f"  {GRAY}이벤트 없음{RESET}\n")
        return

    for ev in recent:
        turn      = ev.get('turn', '?')
        msg       = ev.get('message', '')
        timestamp = ev.get('timestamp', '')
        narrative = ev.get('narrative', '')

        print(f"  {YELLOW}{BOLD}[턴 {turn}]{RESET}  {GRAY}{timestamp}{RESET}")
        print(f"    {msg}")
        if narrative:
            # 나레이션: 금색 이탤릭 효과 (ANSI \033[3m = 이탤릭)
            print(f"    {YELLOW}\033[3m❝ {narrative} ❞{RESET}")
        _hline()

    print()


# ─────────────────────────────────────────
#  6. show_all(state)
# ─────────────────────────────────────────

def show_emoji_map(state):
    """이모지 기반 맵 출력 — ANSI 컬러 없이 정렬 보장."""
    # 각 셀: 이모지 1개(2열폭) 또는 '··'(2열폭) → 셀 너비 통일
    EMPTY    = '··'
    TERRAIN  = {'grass': '🌲', 'dungeon': '🪨', 'treasure': '🟡'}
    P_ICON   = {'마법사': '🔵', '도적': '🟢', '전사': '🔴'}
    NPC_LIVE = '👾'
    NPC_DEAD = '💀'

    map_info  = state.get('map', {})
    width     = map_info.get('width', 20)
    height    = map_info.get('height', 15)
    locations = map_info.get('locations', [])

    grid = [[EMPTY] * width for _ in range(height)]

    for loc in locations:
        a = loc.get('area', {})
        tile = TERRAIN.get(loc.get('type', ''), EMPTY)
        for y in range(a.get('y1', 0), min(a.get('y2', 0) + 1, height)):
            for x in range(a.get('x1', 0), min(a.get('x2', 0) + 1, width)):
                grid[y][x] = tile

    # 단일 타일 랜드마크 아이콘 (우물, 모닥불, 이정표 등)
    LANDMARK_ICON = {
        '우물': '💧',
        '모닥불': '🔥',
        '이정표': '📌',
        '제단': '⛩️',
        '샘': '💧',
        '화톳불': '🔥',
        '표지판': '📌',
    }
    for loc in locations:
        a = loc.get('area', {})
        if a.get('x1') == a.get('x2') and a.get('y1') == a.get('y2'):
            name = loc.get('name', '')
            for keyword, icon in LANDMARK_ICON.items():
                if keyword in name:
                    x, y = a['x1'], a['y1']
                    if 0 <= x < width and 0 <= y < height:
                        grid[y][x] = icon
                    break

    # 오브젝트 렌더링 (entities/{scenario_id}/objects/ 로드)
    OBJ_ICON = {
        ('puzzle',        'unsolved'  ): '📋',
        ('puzzle',        'solved'    ): '📜',
        ('treasure_chest','locked'    ): '🔒',
        ('treasure_chest','unlocked'  ): '📦',
        ('treasure_chest','opened'    ): '📦',
        ('rest_spot',     'available' ): '🛌',
        ('rest_spot',     'used'      ): '💤',
        ('trap',          'active'    ): '⚠️',
        ('trap',          'disarmed'  ): '✅',
        ('vehicle',       'parked'    ): '🛒',
        ('container',     'full'      ): '💦',
        ('container',     'sealed'    ): '🛢️',
        ('container',     'empty'     ): '📦',
        ('resource',      'available' ): '🔶',
        ('shelter',       'set_up'    ): '⛺',
    }
    scenario_id = state.get('game_info', {}).get('scenario_id', '')
    if scenario_id:
        script_dir  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        obj_dir     = os.path.join(script_dir, 'entities', scenario_id, 'objects')
        if os.path.isdir(obj_dir):
            for fname in sorted(os.listdir(obj_dir)):
                if not fname.endswith('.json'):
                    continue
                try:
                    with open(os.path.join(obj_dir, fname), encoding='utf-8') as f:
                        obj = json.load(f)
                    pos = obj.get('position')
                    if not (pos and len(pos) == 2):
                        continue
                    ox, oy = int(pos[0]), int(pos[1])
                    if not (0 <= ox < width and 0 <= oy < height):
                        continue
                    otype  = obj.get('type', '')
                    ostatus = obj.get('status', '')
                    icon = OBJ_ICON.get((otype, ostatus))
                    if icon:
                        obj_size = obj.get('size', [1, 1])
                        for dy in range(obj_size[1]):
                            for dx in range(obj_size[0]):
                                tx, ty = ox + dx, oy + dy
                                if 0 <= tx < width and 0 <= ty < height:
                                    grid[ty][tx] = icon
                except Exception:
                    pass

    for npc in state.get('npcs', []):
        pos = npc.get('position')
        if pos and len(pos) == 2:
            x, y = int(pos[0]), int(pos[1])
            if 0 <= x < width and 0 <= y < height:
                grid[y][x] = NPC_DEAD if npc.get('status') == 'dead' else NPC_LIVE

    for pl in state.get('players', []):
        pos = pl.get('position')
        if pos and len(pos) == 2:
            x, y = int(pos[0]), int(pos[1])
            if 0 <= x < width and 0 <= y < height:
                grid[y][x] = P_ICON.get(pl.get('class', ''), '🔵')

    # 열 번호 헤더 (각 셀 2폭 기준)
    print('    ' + ''.join(f'{x:2d}' for x in range(width)))
    print('  ┌' + '──' * width + '┐')
    for y in range(height):
        row_str = ''.join(grid[y])
        print(f'{y:2d}│{row_str}│')
    print('  └' + '──' * width + '┘')
    print()
    print('  🔵사이키(마법사)  🟢루체나(도적)  🔴노을(전사)')
    print('  💀처치됨   🌲숲   🪨던전   🟡보물실')
    print('  📋퍼즐(미해결)  📜퍼즐(해결)  🔒보물상자  🛌안식처  ⚠️함정  ✅함정(해제)')
    print()


def show_all(state):
    """맵 / 파티 / 이벤트 로그를 순서대로 모두 출력."""
    game_info = state.get('game_info', {})
    title     = game_info.get('title', 'TRPG')
    turn      = state.get('turn_count', 0)
    chapter   = game_info.get('current_chapter', 1)
    status    = game_info.get('status', '')

    print()
    print(f"{BOLD}{'═' * 62}{RESET}")
    print(f"{BOLD}  {title}{RESET}")
    print(f"  {GRAY}챕터 {chapter}  |  턴 {turn}  |  상태: {status}{RESET}")
    print(f"{BOLD}{'═' * 62}{RESET}")
    print()

    show_emoji_map(state)
    show_party(state)
    show_event_log(state)


# ─────────────────────────────────────────
#  7. __main__ 블록
# ─────────────────────────────────────────

if __name__ == '__main__':
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    json_path  = os.path.join(script_dir, 'data', 'game_state.json')

    if not os.path.exists(json_path):
        print(f"{RED}오류: {json_path} 파일을 찾을 수 없습니다.{RESET}")
        sys.exit(1)

    with open(json_path, 'r', encoding='utf-8') as f:
        state = json.load(f)

    show_all(state)
