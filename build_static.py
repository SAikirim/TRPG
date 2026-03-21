#!/usr/bin/env python
"""Build static web (docs/index.html) from dynamic web (templates/index.html).
Only replaces API URLs and disables write operations. All JS logic is preserved."""
import os
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def build():
    with open(os.path.join(BASE_DIR, "templates", "index.html"), "r", encoding="utf-8") as f:
        html = f.read()

    # 1. Title
    html = html.replace("<title>TRPG</title>", "<title>TRPG (Static)</title>")

    # 2. API GET URLs → static JSON files
    # Flask API paths → relative JSON file paths
    api_to_static = {
        # GET endpoints
        "'/api/game-state'": "'game_state.json'",
        "'/api/rules'": "'rules.json'",
        "'/api/items'": "'items.json'",
        "'/api/skills'": "'skills.json'",
        "'/api/scenario'": "'scenario.json'",
        "'/api/settings'": "'current_session.json'",
        "'/api/illustration'": "'illustration_state.json'",
        '"/api/game-state"': '"game_state.json"',
        '"/api/rules"': '"rules.json"',
        '"/api/items"': '"items.json"',
        '"/api/skills"': '"skills.json"',
        '"/api/scenario"': '"scenario.json"',
        '"/api/settings"': '"current_session.json"',
        '"/api/illustration"': '"illustration_state.json"',
    }
    for old, new in api_to_static.items():
        html = html.replace(old, new)

    # 3. Player stats API → entity files
    # fetch(`/api/player-stats/${playerId}`) → fetch(`entities/${scenarioId}/players/player_${playerId}.json`)
    html = re.sub(
        r"fetch\(`/api/player-stats/\$\{(\w+)\}`\)",
        r"fetch(`entities/${(gameState?.game_info?.scenario_id || 'karendel_journey')}/players/player_${\1}.json`)",
        html
    )

    # 4. Absolute paths → relative paths
    html = html.replace('"/static/', '"static/')
    html = html.replace("'/static/", "'static/")

    # 5. Disable POST operations (settings, toggle, reveal, clear)
    # Wrap POST fetch calls in if(false) to disable them
    post_patterns = [
        "fetch('/api/settings',",
        "fetch('/api/illustration/toggle'",
        "fetch('/api/illustration/clear'",
        "fetch('/api/npc/reveal'",
        'fetch("/api/settings",',
        'fetch("/api/illustration/toggle"',
        'fetch("/api/illustration/clear"',
        'fetch("/api/npc/reveal"',
    ]
    for pattern in post_patterns:
        html = html.replace(pattern, f"/* static: disabled */ false && {pattern}")

    # 6. Disable polling (static doesn't need real-time updates)
    html = html.replace(
        "setInterval(updateGameState, 2000);",
        "// setInterval disabled in static mode"
    )

    # 7. Disable settings toggle onclick (make read-only)
    html = html.replace(
        """onclick="toggleSetting('sd_illustration')" """,
        """title="Static mode: read-only" """
    )
    html = html.replace(
        """onclick="toggleSetting('show_dice_result')" """,
        """title="Static mode: read-only" """
    )
    html = html.replace(
        """onchange="changeSetting('display_mode', this.value)" """,
        """disabled title="Static mode: read-only" """
    )
    html = html.replace(
        """onchange="changeSetting('difficulty', this.value)" """,
        """disabled title="Static mode: read-only" """
    )

    # 8. The /api/illustration endpoint returns scene state in dynamic web.
    # For static web, we need to create a fallback since illustration_state.json won't exist.
    # Add a script snippet that provides fallback illustration data if fetch fails.
    fallback_script = """
    <script>
    // Static mode: illustration fallback
    window._staticIllustrationFallback = true;
    </script>
    """
    html = html.replace("</head>", fallback_script + "</head>")

    # 9. In updateIllustration, if illustration_state.json fetch fails (404),
    # fall back to chapter-based background.
    # This is handled by the existing try/catch in updateIllustration.
    # But we need illustration_state.json to exist, or the function needs to handle 404.
    # The simplest fix: create a minimal illustration_state.json in docs/ during sync.

    # Write output
    docs_path = os.path.join(BASE_DIR, "docs", "index.html")
    with open(docs_path, "w", encoding="utf-8") as f:
        f.write(html)

    # Create minimal illustration_state.json for static web
    import json
    ill_state = {
        "background": None,
        "layers": [],
        "generating": {"status": "idle", "type": None, "prompt": None, "error": None, "started_at": None},
        "enabled": False,
        "default_bg": {"sd": "static/illustrations/sd/ch1_forest.png", "pixel": "static/illustrations/pixel/forest.png"},
        "current_chapter": 1
    }
    # Try to read current game_state to get accurate chapter
    try:
        with open(os.path.join(BASE_DIR, "data", "game_state.json"), "r", encoding="utf-8") as f:
            gs = json.load(f)
        chapter = gs.get("game_info", {}).get("current_chapter", 1)
        ill_state["current_chapter"] = chapter
        chapter_bgs = {
            1: {"sd": "static/illustrations/sd/ch1_forest.png", "pixel": "static/illustrations/pixel/forest.png"},
            2: {"sd": "static/illustrations/sd/ch2_dungeon.png", "pixel": "static/illustrations/pixel/dungeon.png"},
            3: {"sd": "static/illustrations/sd/ch3_treasure.png", "pixel": "static/illustrations/pixel/treasure.png"},
        }
        ill_state["default_bg"] = chapter_bgs.get(chapter, chapter_bgs[1])

        # Find latest background illustration
        import glob
        sd_bgs = sorted(glob.glob(os.path.join(BASE_DIR, "static", "illustrations", "sd", "background_*")), key=os.path.getmtime, reverse=True)
        if sd_bgs:
            bg_name = os.path.basename(sd_bgs[0])
            ill_state["background"] = f"static/illustrations/sd/{bg_name}"
    except:
        pass

    ill_path = os.path.join(BASE_DIR, "docs", "illustration_state.json")
    with open(ill_path, "w", encoding="utf-8") as f:
        json.dump(ill_state, f, ensure_ascii=False, indent=2)

    print(f"Built docs/index.html from templates/index.html")
    src_size = os.path.getsize(os.path.join(BASE_DIR, "templates", "index.html"))
    dst_size = os.path.getsize(docs_path)
    print(f"  Source: {src_size} bytes -> Output: {dst_size} bytes")
    print(f"  illustration_state.json created")

if __name__ == "__main__":
    build()
