import json
import os
import shutil
import glob
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAVES_DIR = os.path.join(BASE_DIR, "saves")
GAME_STATE_PATH = os.path.join(BASE_DIR, "game_state.json")
CURRENT_SESSION_PATH = os.path.join(BASE_DIR, "current_session.json")


class SaveManager:
    def __init__(self):
        os.makedirs(SAVES_DIR, exist_ok=True)

    def _save_dir(self, scenario_id, slot=None):
        if slot:
            return os.path.join(SAVES_DIR, scenario_id, f"slot_{slot}")
        return os.path.join(SAVES_DIR, scenario_id)

    def save_game(self, scenario_id, slot=1, description=""):
        """현재 게임 상태를 시나리오별 슬롯에 저장"""
        save_path = self._save_dir(scenario_id, slot)
        os.makedirs(save_path, exist_ok=True)

        with open(GAME_STATE_PATH, "r", encoding="utf-8") as f:
            game_state = json.load(f)

        save_data = {
            "save_info": {
                "scenario_id": scenario_id,
                "slot": slot,
                "description": description,
                "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "turn_count": game_state.get("turn_count", 0),
                "chapter": self._detect_chapter(game_state),
            },
            "game_state": game_state,
        }

        save_file = os.path.join(save_path, "save.json")
        with open(save_file, "w", encoding="utf-8") as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)

        # 진행 상황 요약도 별도 저장
        self._update_progress(scenario_id, save_data["save_info"])

        # current_session.json 갱신
        self._update_current_session(scenario_id, slot, game_state)

        # docs/ 동기화 (GitHub Pages용)
        self._sync_docs(game_state)

        return save_data["save_info"]

    def load_game(self, scenario_id, slot=1):
        """저장된 게임 상태를 불러와서 현재 게임에 적용"""
        save_file = os.path.join(self._save_dir(scenario_id, slot), "save.json")
        if not os.path.exists(save_file):
            return None

        with open(save_file, "r", encoding="utf-8") as f:
            save_data = json.load(f)

        with open(GAME_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(save_data["game_state"], f, ensure_ascii=False, indent=2)

        # current_session.json도 로드한 게임에 맞게 갱신
        self._update_current_session(scenario_id, slot, save_data["game_state"])

        return save_data["save_info"]

    def list_saves(self, scenario_id=None):
        """저장 목록 조회. scenario_id 없으면 전체 조회."""
        result = []
        if not os.path.exists(SAVES_DIR):
            return result

        scenarios = [scenario_id] if scenario_id else os.listdir(SAVES_DIR)
        for sid in scenarios:
            scenario_path = os.path.join(SAVES_DIR, sid)
            if not os.path.isdir(scenario_path):
                continue
            for slot_dir in sorted(os.listdir(scenario_path)):
                save_file = os.path.join(scenario_path, slot_dir, "save.json")
                if os.path.exists(save_file):
                    with open(save_file, "r", encoding="utf-8") as f:
                        save_data = json.load(f)
                    result.append(save_data["save_info"])

        return result

    def delete_save(self, scenario_id, slot=1):
        """저장 슬롯 삭제"""
        save_path = self._save_dir(scenario_id, slot)
        if os.path.exists(save_path):
            shutil.rmtree(save_path)
            return True
        return False

    def get_progress(self, scenario_id):
        """시나리오별 진행 상황 요약 조회"""
        progress_file = os.path.join(self._save_dir(scenario_id), "progress.json")
        if os.path.exists(progress_file):
            with open(progress_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def _update_progress(self, scenario_id, save_info):
        """시나리오별 진행 상황 요약 갱신"""
        scenario_path = self._save_dir(scenario_id)
        os.makedirs(scenario_path, exist_ok=True)
        progress_file = os.path.join(scenario_path, "progress.json")

        if os.path.exists(progress_file):
            with open(progress_file, "r", encoding="utf-8") as f:
                progress = json.load(f)
        else:
            progress = {
                "scenario_id": scenario_id,
                "first_played": save_info["saved_at"],
                "total_saves": 0,
                "history": [],
            }

        progress["last_played"] = save_info["saved_at"]
        progress["last_chapter"] = save_info["chapter"]
        progress["last_turn"] = save_info["turn_count"]
        progress["total_saves"] += 1
        progress["history"].append({
            "slot": save_info["slot"],
            "chapter": save_info["chapter"],
            "turn": save_info["turn_count"],
            "description": save_info["description"],
            "saved_at": save_info["saved_at"],
        })
        # 최근 20개만 유지
        progress["history"] = progress["history"][-20:]

        with open(progress_file, "w", encoding="utf-8") as f:
            json.dump(progress, f, ensure_ascii=False, indent=2)

    def _update_current_session(self, scenario_id, slot, game_state):
        """current_session.json 갱신 — 현재 활성 게임의 빠른 컨텍스트 복원용"""
        game_info = game_state.get("game_info", {})
        chapter = game_info.get("current_chapter", self._detect_chapter(game_state))

        # 챕터 이름 추정 (scenario.json이 있으면 거기서, 아니면 맵 locations에서)
        chapter_name = ""
        locations = game_state.get("map", {}).get("locations", [])
        for loc in locations:
            area = loc.get("area", {})
            players = game_state.get("players", [])
            if players:
                px, py = players[0].get("position", [0, 0])
                if area.get("x1", 0) <= px <= area.get("x2", 0) and area.get("y1", 0) <= py <= area.get("y2", 0):
                    chapter_name = loc.get("name", "")
                    break

        party_summary = []
        for p in game_state.get("players", []):
            party_summary.append({
                "name": p["name"],
                "class": p["class"],
                "hp": f"{p['hp']}/{p['max_hp']}",
                "mp": f"{p['mp']}/{p['max_mp']}",
                "key_items": p.get("inventory", []),
            })

        # 최근 이벤트에서 진행 노트 추출 (최근 10개)
        events = game_state.get("events", [])
        progress_notes = [e["message"] for e in events[-10:]]

        # 기존 current_session.json에서 유저 설정 보존
        existing_display_mode = "mobile"
        existing_show_dice = False
        existing_sd_illustration = False
        if os.path.exists(CURRENT_SESSION_PATH):
            with open(CURRENT_SESSION_PATH, "r", encoding="utf-8") as f:
                existing = json.load(f)
                existing_display_mode = existing.get("display_mode", "mobile")
                existing_show_dice = existing.get("show_dice_result", False)
                existing_sd_illustration = existing.get("sd_illustration", False)

        session = {
            "active_scenario": scenario_id,
            "active_save_slot": slot,
            "ruleset": game_info.get("ruleset", ""),
            "turn": game_state.get("turn_count", 0),
            "chapter": chapter,
            "chapter_name": chapter_name,
            "party_summary": party_summary,
            "progress_notes": progress_notes,
            "next_objective": "",
            "display_mode": existing_display_mode,
            "show_dice_result": existing_show_dice,
            "sd_illustration": existing_sd_illustration,
            "last_updated": datetime.now().strftime("%Y-%m-%d"),
        }

        with open(CURRENT_SESSION_PATH, "w", encoding="utf-8") as f:
            json.dump(session, f, ensure_ascii=False, indent=2)

    def _detect_chapter(self, game_state):
        """플레이어 위치 기반으로 현재 챕터 추정"""
        players = game_state.get("players", [])
        if not players:
            return 1

        # 첫 번째 플레이어 위치 기준
        px, py = players[0].get("position", [0, 0])

        # scenario.json의 area 기준으로 판단
        if px >= 14 and py >= 10:
            return 3  # 보물실
        elif py >= 6:
            return 2  # 고대 던전
        return 1  # 숲의 입구

    def _sync_docs(self, game_state):
        """docs/ 폴더를 최신 상태로 동기화 (GitHub Pages용)"""
        docs_dir = os.path.join(BASE_DIR, "docs")
        if not os.path.exists(docs_dir):
            return

        # game_state.json 동기화
        docs_state = os.path.join(docs_dir, "game_state.json")
        with open(docs_state, "w", encoding="utf-8") as f:
            json.dump(game_state, f, ensure_ascii=False, indent=2)

        # static 파일 동기화 (illustrations, portraits)
        sync_dirs = [
            ("static/illustrations/sd", "static/illustrations/sd"),
            ("static/illustrations/pixel", "static/illustrations/pixel"),
            ("static/portraits/pixel", "static/portraits/pixel"),
            ("static/map.png", "static/map.png"),
        ]
        for src_rel, dst_rel in sync_dirs:
            src = os.path.join(BASE_DIR, src_rel)
            dst = os.path.join(docs_dir, dst_rel)
            if os.path.isdir(src):
                os.makedirs(dst, exist_ok=True)
                for f in os.listdir(src):
                    src_file = os.path.join(src, f)
                    dst_file = os.path.join(dst, f)
                    if os.path.isfile(src_file):
                        shutil.copy2(src_file, dst_file)
            elif os.path.isfile(src):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)

        # entities 동기화
        src_entities = os.path.join(BASE_DIR, "entities")
        dst_entities = os.path.join(docs_dir, "entities")
        if os.path.exists(src_entities):
            if os.path.exists(dst_entities):
                shutil.rmtree(dst_entities)
            shutil.copytree(src_entities, dst_entities)
