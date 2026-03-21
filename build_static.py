#!/usr/bin/env python
"""정적 웹(docs/) 데이터 동기화. HTML은 건드리지 않는다.
docs/index.html은 독립적으로 관리되는 파일이며, 이 스크립트로 생성/변환하지 않는다."""
import json
import os
import shutil
import glob

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def sync():
    """data/ -> docs/ 동기화. JSON, 이미지, 엔티티, 템플릿, 룰셋 복사."""
    docs_dir = os.path.join(BASE_DIR, "docs")
    if not os.path.exists(docs_dir):
        os.makedirs(docs_dir)

    # 1. JSON 데이터 파일 동기화
    json_files = [
        "game_state.json", "current_session.json", "scenario.json",
        "rules.json", "worldbuilding.json", "items.json", "skills.json",
        "status_effects.json", "creature_templates.json", "shops.json",
        "quests.json", "pending_actions.json",
    ]
    for fname in json_files:
        src = os.path.join(BASE_DIR, "data", fname)
        dst = os.path.join(docs_dir, fname)
        if os.path.isfile(src):
            shutil.copy2(src, dst)

    # 2. illustration_state.json 생성 (정적 웹의 일러스트 표시용)
    try:
        gs_path = os.path.join(BASE_DIR, "data", "game_state.json")
        with open(gs_path, "r", encoding="utf-8") as fh:
            gs = json.load(fh)
        chapter = gs.get("game_info", {}).get("current_chapter", 1)
        chapter_bgs = {
            1: {"sd": "static/illustrations/sd/ch1_forest.png",
                "pixel": "static/illustrations/pixel/forest.png"},
            2: {"sd": "static/illustrations/sd/ch2_dungeon.png",
                "pixel": "static/illustrations/pixel/dungeon.png"},
            3: {"sd": "static/illustrations/sd/ch3_treasure.png",
                "pixel": "static/illustrations/pixel/treasure.png"},
        }
        background = None
        sd_bgs = sorted(
            glob.glob(os.path.join(BASE_DIR, "static", "illustrations",
                                   "sd", "background_*")),
            key=os.path.getmtime, reverse=True)
        if sd_bgs:
            background = ("static/illustrations/sd/"
                          + os.path.basename(sd_bgs[0]))
        ill_state = {
            "background": background,
            "layers": [],
            "generating": {"status": "idle", "type": None, "prompt": None,
                           "error": None, "started_at": None},
            "enabled": False,
            "default_bg": chapter_bgs.get(chapter, chapter_bgs[1]),
            "current_chapter": chapter,
        }
        ill_path = os.path.join(docs_dir, "illustration_state.json")
        with open(ill_path, "w", encoding="utf-8") as fh:
            json.dump(ill_state, fh, ensure_ascii=False, indent=2)
    except Exception as exc:
        print("  [WARN] illustration_state.json:", exc)

    # 3. 이미지 파일 동기화
    image_entries = [
        ("static/illustrations/sd", "static/illustrations/sd"),
        ("static/illustrations/pixel", "static/illustrations/pixel"),
        ("static/portraits/pixel", "static/portraits/pixel"),
        ("static/portraits/sd", "static/portraits/sd"),
        ("static/portraits/original", "static/portraits/original"),
        ("static/map.png", "static/map.png"),
        ("static/map_mini.png", "static/map_mini.png"),
    ]
    for src_rel, dst_rel in image_entries:
        src = os.path.join(BASE_DIR, src_rel)
        dst = os.path.join(docs_dir, dst_rel)
        if os.path.isdir(src):
            os.makedirs(dst, exist_ok=True)
            for entry in os.listdir(src):
                sf = os.path.join(src, entry)
                df = os.path.join(dst, entry)
                if os.path.isfile(sf):
                    shutil.copy2(sf, df)
        elif os.path.isfile(src):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)

    # 4. 엔티티/템플릿/룰셋 동기화
    for dirname in ["entities", "templates", "rulesets"]:
        src = os.path.join(BASE_DIR, dirname)
        dst = os.path.join(docs_dir, dirname)
        if os.path.exists(src):
            if os.path.exists(dst):
                shutil.rmtree(dst)
            shutil.copytree(src, dst)

    print("docs/ 데이터 동기화 완료 (HTML 미변경)")


if __name__ == "__main__":
    sync()
