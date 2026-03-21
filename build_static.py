#!/usr/bin/env python
"""Build static web (docs/index.html) from dynamic web (templates/index.html).

동적 웹(Flask)의 templates/index.html을 원본으로 사용하여
정적 웹(GitHub Pages)의 docs/index.html을 자동 생성한다.

변환 내용:
1. API fetch URL → 정적 JSON 파일 경로
2. Flask 전용 기능 제거 (settings POST, SD toggle API, polling)
3. 절대 경로(/static/) → 상대 경로(static/)
4. 일러스트: API 기반 → 챕터별 정적 이미지
5. 설정: 읽기 전용 (current_session.json에서 로드)
"""
import re
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# === 정적 웹 전용 JavaScript ===
# templates/index.html의 <script> 블록 전체를 이 코드로 교체한다.
STATIC_SCRIPT = r"""    <script>
        let gameState = null;
        let rulesData = null;
        let itemsData = {};
        let skillsData = {};
        const playerDetailCache = {};
        const rarityEmoji = { common: '⬜', uncommon: '🟩', rare: '🟦', epic: '🟪', legendary: '🟧' };

        function statMod(val) {
            const m = Math.floor((val - 10) / 2);
            return m >= 0 ? '+' + m : '' + m;
        }

        // 아이템 정보를 items.json → rules.json 순으로 조회
        function getItemInfo(name) {
            if (itemsData[name]) {
                const info = itemsData[name];
                return { desc: info.desc || name, stat: info.stat || '', rarity: info.rarity || 'common' };
            }
            if (rulesData?.combat?.weapons?.[name]) {
                const w = rulesData.combat.weapons[name];
                return { desc: w.description, stat: 'DMG ' + w.dice, rarity: 'common' };
            }
            if (rulesData?.combat?.armor?.[name]) {
                const a = rulesData.combat.armor[name];
                return { desc: a.description || name, stat: a.bonus ? 'DEF +' + a.bonus : '', rarity: 'common' };
            }
            if (rulesData?.rest?.use_item?.[name]) {
                const u = rulesData.rest.use_item[name];
                return { desc: u.description, stat: u.heal_hp ? 'HP +' + u.heal_hp : u.heal_mp ? 'MP +' + u.heal_mp : '', rarity: 'common' };
            }
            return { desc: name, stat: '', rarity: 'common' };
        }

        async function loadScenarioTitle() {
            try {
                const res = await fetch('scenario.json');
                const data = await res.json();
                const title = data.scenario_info?.title || 'TRPG';
                document.getElementById('game-title').textContent = title;
                document.title = title + ' (Static)';
            } catch(e) {
                if (gameState?.game_info?.title) {
                    document.getElementById('game-title').textContent = gameState.game_info.title;
                }
            }
        }

        async function loadGame() {
            try {
                const [stateRes, rulesRes, itemsRes, skillsRes] = await Promise.all([
                    fetch('game_state.json'),
                    fetch('rules.json'),
                    fetch('items.json').catch(() => ({ json: () => ({}) })),
                    fetch('skills.json').catch(() => ({ json: () => ({}) }))
                ]);
                gameState = await stateRes.json();
                rulesData = await rulesRes.json();
                try { const d = await itemsRes.json(); itemsData = d.items || d; } catch(e) {}
                try { const d = await skillsRes.json(); skillsData = d.skills || d; } catch(e) {}

                loadScenarioTitle();
                renderGame();
                loadSettings();
            } catch (e) {
                document.getElementById('game-title').textContent = 'TRPG - 로딩 실패';
                console.error(e);
            }
        }

        function renderGame() {
            const info = gameState.game_info || {};

            document.getElementById('game-desc').textContent = info.scenario || '';
            document.getElementById('turn-count').textContent = gameState.turn_count || 0;
            document.getElementById('chapter-info').textContent = info.current_chapter || '-';

            const endingEl = document.getElementById('ending-info');
            if (info.ending) {
                const endings = { perfect: '완벽한 승리', bittersweet: '쓰라린 승리', retreat: '전략적 후퇴', defeat: '어둠 속으로' };
                endingEl.textContent = endings[info.ending] || info.ending;
                endingEl.style.display = 'inline';
            } else {
                endingEl.style.display = 'none';
            }

            buildOriginalImageMap();
            renderPlayers();
            renderEvents();
            renderIllustration(info.current_chapter);
            renderLegend();
        }

        // 플레이어 원본 이미지 매핑
        const playerOriginalImages = {};
        function buildOriginalImageMap() {
            if (!gameState) return;
            gameState.players.forEach(p => {
                if (p.original_image) {
                    playerOriginalImages[p.id] = p.original_image;
                }
            });
        }

        function filterNpcNames(text) {
            if (!gameState || !gameState.npcs) return text;
            gameState.npcs.forEach(npc => {
                if (!npc.known && npc.name) {
                    const regex = new RegExp(npc.name, 'g');
                    text = text.replace(regex, '???');
                }
            });
            return text;
        }

        // Track which detail panels are open
        const openDetails = {};

        function renderPlayers() {
            const container = document.getElementById('players-list');
            const classMap = { '전사': 'warrior', '마법사': 'mage', '도적': 'rogue' };
            const scenarioId = gameState.game_info?.scenario_id || 'lost_treasure';

            // Save open state before re-render
            container.querySelectorAll('.detail-content.open').forEach(el => {
                openDetails[el.id] = true;
            });

            container.innerHTML = gameState.players.map(p => {
                const cls = classMap[p.class] || 'warrior';
                const hpPct = (p.hp / p.max_hp * 100).toFixed(0);
                const mpPct = (p.mp / p.max_mp * 100).toFixed(0);
                const lv = p.level || 1;
                const xp = p.xp || 0;
                const xpTable = rulesData?.level_up?.xp_table || {};
                const xpNext = xpTable[String(lv + 1)] || 100;
                const xpPrev = xpTable[String(lv)] || 0;
                const xpPct = xpNext > xpPrev ? ((xp - xpPrev) / (xpNext - xpPrev) * 100).toFixed(0) : 100;
                const effects = (p.status_effects || []).length > 0
                    ? `<div style="font-size:0.75em;color:#ffd700;margin-top:4px">상태: ${p.status_effects.map(e => typeof e === 'string' ? e : e.name).join(', ')}</div>`
                    : '';
                const invItems = (p.inventory || []).map(item => {
                    const info = getItemInfo(item);
                    const rarityClass = info.rarity ? ' rarity-' + info.rarity : '';
                    return `<div class="detail-item"><span class="item-name${rarityClass}">${item}</span>${info.stat ? '<span class="item-stat">' + info.stat + '</span>' : ''}<div class="tooltip">${info.desc}</div></div>`;
                }).join('');
                return `
                <div class="player-card">
                    <img class="player-portrait" src="static/portraits/pixel/player_${p.id}.png" alt="${p.name}" onclick="openPortraitZoom('${p.original_image ? p.original_image.replace('/static/', 'static/') : 'static/portraits/pixel/player_' + p.id + '.png'}')" style="cursor:pointer">
                    <div class="player-info">
                        <div class="name">
                        ${p.name}
                        <span class="class-badge class-${cls}">${p.class}</span>
                        <span class="level-badge">LV ${lv}</span>
                        <span style="float:right;font-size:0.75em;color:#aaa">위치: [${p.position}]</span>
                    </div>
                    <div class="bar-container">
                        <div class="bar bar-hp" style="width:${hpPct}%"></div>
                        <div class="bar-label">HP ${p.hp}/${p.max_hp}</div>
                    </div>
                    <div class="bar-container">
                        <div class="bar bar-mp" style="width:${mpPct}%"></div>
                        <div class="bar-label">MP ${p.mp}/${p.max_mp}</div>
                    </div>
                    <div class="bar-container" style="height:10px">
                        <div class="bar bar-xp" style="width:${xpPct}%"></div>
                        <div class="bar-label" style="font-size:0.6em;line-height:10px">XP ${xp}/${xpNext}</div>
                    </div>
                    <div class="stats">
                        <span>STR ${p.stats.STR}<span class="stat-mod">(${statMod(p.stats.STR)})</span></span>
                        <span>DEX ${p.stats.DEX}<span class="stat-mod">(${statMod(p.stats.DEX)})</span></span>
                        <span>INT ${p.stats.INT}<span class="stat-mod">(${statMod(p.stats.INT)})</span></span>
                        <span>CON ${p.stats.CON}<span class="stat-mod">(${statMod(p.stats.CON)})</span></span>
                    </div>
                    ${effects}
                    <div class="detail-toggle">
                        <button onclick="toggleDetail(${p.id}, 'inv', this, '${scenarioId}')">소지품 (${(p.inventory||[]).length})</button>
                        <button onclick="toggleDetail(${p.id}, 'skill', this, '${scenarioId}')">스킬</button>
                        <button onclick="toggleDetail(${p.id}, 'equip', this, '${scenarioId}')">장비</button>
                    </div>
                    <div id="detail-inv-${p.id}" class="detail-content">
                        ${invItems || '<div class="detail-item" style="color:#666">없음</div>'}
                    </div>
                    <div id="detail-skill-${p.id}" class="detail-content">
                        <div class="detail-item" style="color:#666">...</div>
                    </div>
                    <div id="detail-equip-${p.id}" class="detail-content">
                        <div class="detail-item" style="color:#666">...</div>
                    </div>
                    </div>
                </div>`;
            }).join('');

            // Restore open state after re-render
            Object.keys(openDetails).forEach(id => {
                const el = document.getElementById(id);
                if (el) {
                    el.classList.add('open');
                    const type = id.split('-')[1];
                    const card = el.closest('.player-card');
                    if (card) {
                        const btn = card.querySelector(`button[onclick*="'${type}'"]`);
                        if (btn) btn.classList.add('active');
                    }
                }
            });
        }

        async function toggleDetail(playerId, type, btn, scenarioId) {
            const el = document.getElementById(`detail-${type}-${playerId}`);
            const isOpen = el.classList.contains('open');

            // Close all details for this player
            ['inv', 'skill', 'equip'].forEach(t => {
                const d = document.getElementById(`detail-${t}-${playerId}`);
                if (d) d.classList.remove('open');
                delete openDetails[`detail-${t}-${playerId}`];
            });
            btn.parentElement.querySelectorAll('button').forEach(b => b.classList.remove('active'));

            if (isOpen) return;

            el.classList.add('open');
            btn.classList.add('active');
            openDetails[`detail-${type}-${playerId}`] = true;

            // Lazy load from entity file
            if ((type === 'skill' || type === 'equip') && !playerDetailCache[playerId]) {
                try {
                    const res = await fetch(`entities/${scenarioId}/players/player_${playerId}.json`);
                    playerDetailCache[playerId] = await res.json();
                } catch(e) {
                    playerDetailCache[playerId] = {};
                }
            }

            if (type === 'skill') {
                const detail = playerDetailCache[playerId] || {};
                const available = detail.available_actions || [];
                let skills;
                if (available.length > 0) {
                    skills = available.map(name => {
                        const info = skillsData[name] || {};
                        const stat = info.stat || '';
                        const desc = info.desc || name;
                        const lvl = info.level_req ? 'Lv.' + info.level_req : '';
                        // rules.json 폴백
                        const rAction = rulesData?.actions?.[name];
                        const cost = rAction?.cost?.mp ? 'MP ' + rAction.cost.mp : (info.cost || '');
                        let dmgStr = '';
                        if (rAction?.damage) {
                            let dice = rAction.damage.split(' + ')[0];
                            if (dice.includes('weapon')) {
                                const wep = detail.equipment?.weapon;
                                const wName = typeof wep === 'object' ? wep?.name : wep;
                                const wDef = rulesData?.combat?.weapons?.[wName];
                                dice = wDef ? wDef.dice : '1d2';
                            }
                            dmgStr = ' / ' + dice;
                        }
                        return `<div class="detail-item"><span class="item-name">${name}</span><span class="item-stat">${cost || stat}${dmgStr}</span><div class="tooltip">${rAction?.description || desc}${lvl ? ' (' + lvl + ')' : ''}</div></div>`;
                    });
                } else {
                    // 클래스 기반 필터 폴백
                    const actions = rulesData?.actions || {};
                    const playerClass = gameState.players.find(p => p.id === playerId);
                    const className = playerClass ? playerClass.class : '';
                    const classSkills = Object.entries(actions).filter(([k,v]) =>
                        k !== '_설명' && (v.class === className || v.class === 'all'));
                    skills = classSkills.map(([name, info]) => {
                        const cost = info.cost?.mp ? 'MP ' + info.cost.mp : 'MP 0';
                        let dmgStr = '';
                        if (info.damage) {
                            let dmg = info.damage.split(' + ')[0];
                            if (dmg.includes('weapon')) {
                                const weaponName = playerDetailCache[playerId]?.equipment?.weapon;
                                const wn = typeof weaponName === 'object' ? weaponName?.name : weaponName;
                                const wDef = rulesData?.combat?.weapons?.[wn];
                                dmg = wDef ? wDef.dice : '1d2';
                            }
                            dmgStr = ' / ' + dmg;
                        }
                        return `<div class="detail-item"><span class="item-name">${name}</span><span class="item-stat">${cost}${dmgStr}</span><div class="tooltip">${info.description || name}</div></div>`;
                    });
                }
                el.innerHTML = skills.length ? skills.join('') : '<div class="detail-item" style="color:#666">없음</div>';
            }

            if (type === 'equip') {
                const detail = playerDetailCache[playerId] || {};
                const equip = detail.equipment || {};
                const slots = ['weapon', 'armor', 'accessory'];
                const slotNames = { weapon: '무기', armor: '방어구', accessory: '장신구' };
                el.innerHTML = slots.map(slot => {
                    const item = equip[slot];
                    if (!item) return `<div class="detail-item"><span class="item-name">${slotNames[slot]}: —</span></div>`;
                    if (typeof item === 'string') {
                        const info = getItemInfo(item);
                        return `<div class="detail-item"><span class="item-name">${slotNames[slot]}: ⬜ ${item}</span><span class="item-stat">${info.stat}</span><div class="tooltip">${info.desc}</div></div>`;
                    }
                    const rarity = item.rarity || 'common';
                    const emoji = rarityEmoji[rarity] || '⬜';
                    const props = item.properties || {};
                    const wDef = rulesData?.combat?.weapons?.[item.name];
                    let statStr = wDef ? 'DMG ' + wDef.dice : '';
                    const aDef = rulesData?.combat?.armor?.[item.name];
                    if (aDef) statStr = 'DEF +' + aDef.bonus;
                    let propParts = [];
                    if (props.attack_bonus) propParts.push('명중+' + props.attack_bonus);
                    if (props.damage_bonus) propParts.push('데미지+' + props.damage_bonus);
                    if (props.defense_bonus) propParts.push('방어+' + props.defense_bonus);
                    if (props.element) propParts.push('🔮' + props.element);
                    if (props.on_hit) propParts.push('⚡' + (props.on_hit.type || ''));
                    const propStr = propParts.length ? ' [' + propParts.join(', ') + ']' : '';
                    const desc = (wDef?.description || aDef?.description || item.name) + propStr;
                    return `<div class="detail-item"><span class="item-name rarity-${rarity}">${slotNames[slot]}: ${emoji} ${item.name}</span><span class="item-stat">${statStr}${propStr}</span><div class="tooltip">${desc}</div></div>`;
                }).join('');
            }
        }

        function renderEvents() {
            const container = document.getElementById('events-list');
            const events = gameState.events.slice(-10).reverse();
            container.innerHTML = events.map(e => {
                const message = filterNpcNames(e.message || '');
                const narrative = e.narrative ? `<span class="narrative">${filterNpcNames(e.narrative)}</span>` : '';
                return `
                <div class="event-item">
                    <span class="turn-badge">T${e.turn}</span>
                    ${message}
                    ${narrative}
                </div>`;
            }).join('');
        }

        function renderLegend() {
            const container = document.getElementById('map-legend');
            if (!container || !gameState) return;
            const playerColors = { '전사': '#e63946', '마법사': '#457be0', '도적': '#2ecc71' };
            const locColors = { 'grass': '#4a8c2a', 'dungeon': '#6b6b6b', 'treasure': '#c8a82a', 'village': '#8B7355', 'road': '#A0926B', 'house': '#6B4226' };
            let html = '';
            gameState.players.forEach(p => {
                html += `<div class="legend-item"><div class="legend-dot" style="background:${playerColors[p.class] || '#fff'}"></div> ${p.name}</div>`;
            });
            const seen = new Set();
            (gameState.map?.locations || []).forEach(loc => {
                if (!seen.has(loc.type)) {
                    seen.add(loc.type);
                    const color = locColors[loc.type] || '#888';
                    html += `<div class="legend-item"><div class="legend-dot" style="background:${color}"></div> ${loc.name.split(' ')[0]}</div>`;
                }
            });
            // NPC type별 범례 (fled 제외)
            const visibleNpcs = (gameState.npcs || []).filter(n => n.status !== 'fled');
            const aliveNpcs = visibleNpcs.filter(n => n.status !== 'dead');
            const deadNpcs = visibleNpcs.filter(n => n.status === 'dead');
            const npcTypes = new Set(aliveNpcs.map(n => n.type));
            if (npcTypes.has('monster')) html += '<div class="legend-item"><div class="legend-dot" style="background:#9b30ff"></div> 몬스터</div>';
            if (npcTypes.has('friendly')) html += '<div class="legend-item"><div class="legend-dot" style="background:#f1c40f"></div> NPC</div>';
            if (npcTypes.has('neutral')) html += '<div class="legend-item"><div class="legend-dot" style="background:#95a5a6"></div> 중립</div>';
            if (deadNpcs.length > 0) html += '<div class="legend-item"><div class="legend-dot" style="background:#555"></div> 시체</div>';
            container.innerHTML = html;
        }

        function renderIllustration(chapter) {
            const panel = document.getElementById('illustration-panel');
            const chapterBgs = {
                1: 'static/illustrations/sd/ch1_forest.png',
                2: 'static/illustrations/sd/ch2_dungeon.png',
                3: 'static/illustrations/sd/ch3_treasure.png',
                4: 'static/illustrations/sd/background_village_night.webp'
            };
            const pixelBgs = {
                1: 'static/illustrations/pixel/forest.png',
                2: 'static/illustrations/pixel/dungeon.png',
                3: 'static/illustrations/pixel/treasure.png',
                4: 'static/illustrations/pixel/forest.png'
            };
            const bg = chapterBgs[chapter];
            const fallback = pixelBgs[chapter] || pixelBgs[1];
            if (bg) {
                panel.innerHTML = `<img class="bg-layer" src="${bg}" alt="Chapter ${chapter}" onerror="this.src='${fallback}'">`;
            } else {
                panel.innerHTML = '<div class="illustration-placeholder">일러스트 없음</div>';
            }
        }

        function openMapZoom() {
            document.getElementById('map-overlay').classList.add('active');
            document.getElementById('map-zoom-img').src = 'static/map.png';
        }

        function openPortraitZoom(src) {
            document.getElementById('map-overlay').classList.add('active');
            document.getElementById('map-zoom-img').src = src;
        }

        // Tooltip: show/hide on mouse move using event delegation
        document.addEventListener('mouseover', function(e) {
            const item = e.target.closest('.detail-item');
            if (!item) return;
            const tip = item.querySelector('.tooltip');
            if (tip) tip.style.display = 'block';
        });
        document.addEventListener('mouseout', function(e) {
            const item = e.target.closest('.detail-item');
            if (!item) return;
            const tip = item.querySelector('.tooltip');
            if (tip) tip.style.display = 'none';
        });
        document.addEventListener('mousemove', function(e) {
            const item = e.target.closest('.detail-item');
            if (!item) return;
            const tip = item.querySelector('.tooltip');
            if (!tip || tip.style.display !== 'block') return;
            const tipRect = tip.getBoundingClientRect();
            const tipW = tipRect.width || 200;
            const tipH = tipRect.height || 40;
            let x = e.clientX + 15;
            let y = e.clientY + 15;
            if (x + tipW > window.innerWidth - 5) x = e.clientX - tipW - 10;
            if (y + tipH > window.innerHeight - 5) y = e.clientY - tipH - 10;
            if (y < 5) y = 5;
            if (x < 5) x = 5;
            tip.style.left = x + 'px';
            tip.style.top = y + 'px';
        });

        function toggleSettings() {
            document.getElementById('settings-panel').classList.toggle('open');
        }

        async function loadSettings() {
            try {
                const res = await fetch('current_session.json');
                const session = await res.json();
                const sdEl = document.getElementById('setting-sd');
                if (sdEl) sdEl.className = 'settings-toggle' + (session.sd_illustration ? ' active' : '');
                const diceEl = document.getElementById('setting-dice');
                if (diceEl) diceEl.className = 'settings-toggle' + (session.show_dice_result ? ' active' : '');
                const dispEl = document.getElementById('setting-display');
                if (dispEl) dispEl.value = session.display_mode || 'mobile';
                // SD badge in illustration header
                const sdBadge = document.getElementById('sd-badge');
                if (sdBadge) {
                    sdBadge.textContent = session.sd_illustration ? 'SD ON' : 'SD OFF';
                    sdBadge.style.color = session.sd_illustration ? '#2ecc71' : '#666';
                    sdBadge.style.borderColor = session.sd_illustration ? '#2ecc71' : '#555';
                }
            } catch(e) {}
            // difficulty from game_state
            try {
                if (gameState?.game_info?.difficulty) {
                    const diffEl = document.getElementById('setting-difficulty');
                    if (diffEl) diffEl.value = gameState.game_info.difficulty;
                }
            } catch(e) {}
        }

        loadGame();
    </script>"""


def build():
    """templates/index.html을 읽어서 정적 웹용 docs/index.html을 생성한다."""
    src_path = os.path.join(BASE_DIR, "templates", "index.html")
    dst_path = os.path.join(BASE_DIR, "docs", "index.html")

    with open(src_path, "r", encoding="utf-8") as f:
        html = f.read()

    # === 1. CSS 뒤에 정적 전용 스타일 추가 ===
    static_css = """        .settings-note {
            font-size: 0.75em;
            color: #666;
            text-align: center;
            padding: 4px 0;
        }"""
    html = html.replace("    </style>", static_css + "\n    </style>")

    # === 2. 절대 경로 → 상대 경로 ===
    html = html.replace('src="/static/', 'src="static/')
    html = html.replace("src='/static/", "src='static/")
    html = html.replace("'/static/", "'static/")
    html = html.replace('"/static/', '"static/')

    # === 3. 타이틀에 (Static) 표시 ===
    html = html.replace("<title>TRPG</title>", "<title>TRPG (Static)</title>")

    # === 4. 설정 패널: toggleSetting/changeSetting → 읽기 전용 ===
    # settings toggle onclick 제거
    html = html.replace(
        ' onclick="toggleSetting(\'sd_illustration\')"',
        ""
    )
    html = html.replace(
        ' onclick="toggleSetting(\'show_dice_result\')"',
        ""
    )
    # display_mode select → disabled
    html = html.replace(
        " onchange=\"changeSetting('display_mode', this.value)\">",
        " disabled>"
    )
    # difficulty select → disabled
    html = html.replace(
        " onchange=\"changeSetting('difficulty', this.value)\">",
        " disabled>"
    )
    # 설정 패널에 안내 메시지 추가
    html = html.replace(
        "        </div>\n    </header>",
        '            <div class="settings-note">설정 변경은 동적 웹에서만 가능합니다</div>\n        </div>\n    </header>'
    )

    # === 5. 일러스트 헤더에 SD badge 추가 ===
    html = html.replace(
        '<h3>일러스트</h3>',
        '<h3>\n                    일러스트\n                    <span id="sd-badge" class="sd-toggle">SD OFF</span>\n                </h3>'
    )

    # === 6. 일러스트 placeholder 텍스트 변경 ===
    html = html.replace(
        '<div class="illustration-placeholder">대기 중...</div>',
        '<div class="illustration-placeholder">로딩 중...</div>'
    )

    # === 7. <script> 블록 전체 교체 ===
    # templates의 <script>...</script> 블록을 정적 웹 전용 JS로 교체
    script_start = html.find("    <script>")
    script_end = html.find("    </script>") + len("    </script>")
    if script_start >= 0 and script_end > script_start:
        html = html[:script_start] + STATIC_SCRIPT + html[script_end:]

    # === 8. map-overlay를 script 앞으로 이동 (이미 되어있으면 건너뜀) ===
    # 동적 버전은 script 뒤에 map-overlay가 있지만, 정적 버전은 script 앞에 있어야 함
    overlay_block = '\n    <div id="map-overlay" class="map-overlay" onclick="this.classList.remove(\'active\')">\n        <img id="map-zoom-img" src="" alt="Map Zoom">\n    </div>\n'
    # 기존 위치에서 제거
    html = html.replace(overlay_block, "")
    # </div> (container 닫기) 뒤, script 앞에 삽입
    html = html.replace(
        "    </div>\n\n    <script>",
        "    </div>\n" + overlay_block + "\n    <script>"
    )

    # === 최종 출력 ===
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    with open(dst_path, "w", encoding="utf-8") as f:
        f.write(html)

    src_size = os.path.getsize(src_path)
    dst_size = os.path.getsize(dst_path)
    print(f"Built docs/index.html from templates/index.html")
    print(f"  Source: {src_size:,} bytes ({sum(1 for _ in open(src_path, encoding='utf-8'))} lines)")
    print(f"  Output: {dst_size:,} bytes ({sum(1 for _ in open(dst_path, encoding='utf-8'))} lines)")


if __name__ == "__main__":
    build()
