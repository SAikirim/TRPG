import json
import os
import shutil
import glob
import filecmp
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAVES_DIR = os.path.join(BASE_DIR, "saves")
GAME_STATE_PATH = os.path.join(BASE_DIR, "data", "game_state.json")
CURRENT_SESSION_PATH = os.path.join(BASE_DIR, "data", "current_session.json")


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

    @staticmethod
    def _copy_if_changed(src, dst):
        """mtime+size 비교 후 변경된 파일만 복사. 복사했으면 True 반환."""
        if not os.path.isfile(src):
            return False
        if os.path.isfile(dst):
            s_stat = os.stat(src)
            d_stat = os.stat(dst)
            if (s_stat.st_size == d_stat.st_size
                    and s_stat.st_mtime <= d_stat.st_mtime):
                return False
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        return True

    @staticmethod
    def _sync_dir_incremental(src_dir, dst_dir):
        """디렉토리 증분 동기화: 변경분만 복사 + dst에만 있는 파일 삭제."""
        if not os.path.isdir(src_dir):
            return 0
        os.makedirs(dst_dir, exist_ok=True)
        copied = 0

        # src 기준으로 변경/추가 파일 복사
        for root, dirs, files in os.walk(src_dir):
            rel = os.path.relpath(root, src_dir)
            dst_root = os.path.join(dst_dir, rel) if rel != "." else dst_dir
            os.makedirs(dst_root, exist_ok=True)
            for f in files:
                sf = os.path.join(root, f)
                df = os.path.join(dst_root, f)
                if not os.path.isfile(df):
                    shutil.copy2(sf, df)
                    copied += 1
                else:
                    s_stat = os.stat(sf)
                    d_stat = os.stat(df)
                    if (s_stat.st_size != d_stat.st_size
                            or s_stat.st_mtime > d_stat.st_mtime):
                        shutil.copy2(sf, df)
                        copied += 1

        # dst에만 있는 파일/디렉토리 삭제
        for root, dirs, files in os.walk(dst_dir, topdown=False):
            rel = os.path.relpath(root, dst_dir)
            src_root = os.path.join(src_dir, rel) if rel != "." else src_dir
            for f in files:
                if not os.path.exists(os.path.join(src_root, f)):
                    os.remove(os.path.join(root, f))
            for d in dirs:
                src_d = os.path.join(src_root, d)
                dst_d = os.path.join(root, d)
                if not os.path.exists(src_d) and os.path.isdir(dst_d):
                    shutil.rmtree(dst_d)

        return copied

    def _sync_docs(self, game_state):
        """docs/ 증분 동기화 (GitHub Pages용).
        변경된 파일만 복사하여 I/O 최소화."""
        docs_dir = os.path.join(BASE_DIR, "docs")
        os.makedirs(docs_dir, exist_ok=True)

        # 1. JSON 데이터 파일 — 변경분만 복사
        json_files = [
            "game_state.json", "current_session.json", "scenario.json",
            "rules.json", "worldbuilding.json", "items.json", "skills.json",
            "status_effects.json", "creature_templates.json", "shops.json",
            "quests.json", "pending_actions.json",
        ]
        for fname in json_files:
            src = os.path.join(BASE_DIR, "data", fname)
            dst = os.path.join(docs_dir, fname)
            self._copy_if_changed(src, dst)

        # 2. illustration_state.json 생성
        self._build_illustration_state(game_state, docs_dir)

        # 3. 이미지 파일 — 증분 동기화
        image_dirs = [
            "static/illustrations/sd",
            "static/illustrations/pixel",
            "static/portraits/pixel",
            "static/portraits/sd",
            "static/portraits/original",
        ]
        for rel in image_dirs:
            self._sync_dir_incremental(
                os.path.join(BASE_DIR, rel),
                os.path.join(docs_dir, rel))

        # 단일 파일 (맵)
        for fname in ["static/map.png", "static/map_mini.png"]:
            self._copy_if_changed(
                os.path.join(BASE_DIR, fname),
                os.path.join(docs_dir, fname))

        # 4. 엔티티/템플릿/룰셋 — 증분 동기화 (rmtree 제거)
        for src_rel in ["entities", "templates", "rulesets"]:
            self._sync_dir_incremental(
                os.path.join(BASE_DIR, src_rel),
                os.path.join(docs_dir, src_rel))

        # 5. 정적 빌드 전용 데이터 생성
        #    동적 API가 계산해서 내려주는 값들을 정적 JSON으로 미리 빌드
        self._build_static_player_stats(game_state, docs_dir)
        self._build_static_settings(game_state, docs_dir)

        # 6. HTML 복사
        self._copy_if_changed(
            os.path.join(BASE_DIR, "templates", "index.html"),
            os.path.join(docs_dir, "index.html"))

    def _build_illustration_state(self, game_state, docs_dir):
        """정적 웹용 illustration_state.json 생성"""
        try:
            chapter = game_state.get("game_info", {}).get("current_chapter", 1)
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
                glob.glob(os.path.join(
                    BASE_DIR, "static", "illustrations", "sd", "background_*")),
                key=os.path.getmtime, reverse=True)
            if sd_bgs:
                background = "static/illustrations/sd/" + os.path.basename(sd_bgs[0])

            ill_state = {
                "background": background,
                "layers": [],
                "generating": {
                    "status": "idle", "type": None, "prompt": None,
                    "error": None, "started_at": None},
                "enabled": False,
                "default_bg": chapter_bgs.get(chapter, chapter_bgs[1]),
                "current_chapter": chapter,
            }

            # NPC 레이어 추가 (초상화 파일이 존재하는 NPC만)
            player1 = next((p for p in game_state.get("players", []) if p.get("id") == 1), None)
            p1_x = player1["position"][0] if player1 else 0
            p1_y = player1["position"][1] if player1 else 0
            current_loc = game_state.get("current_location", "")

            npcs_to_add = []
            for npc in game_state.get("npcs", []):
                if npc.get("status") not in ("alive", "idle", "active"):
                    continue
                npc_loc = npc.get("location", "")
                if current_loc and npc_loc and npc_loc != current_loc:
                    continue
                npc_name = npc.get("name", "")
                portrait_path = None
                for ext in [".webp", ".png"]:
                    for prefix in ["portrait_", ""]:
                        check = os.path.join(BASE_DIR, "static", "portraits", "sd", f"{prefix}{npc_name}{ext}")
                        if os.path.exists(check):
                            portrait_path = f"static/portraits/sd/{prefix}{npc_name}{ext}"
                            break
                    if portrait_path:
                        break
                if not portrait_path:
                    continue
                npc_pos = npc.get("position", [0, 0])
                sort_key = -(npc_pos[0] - p1_x)
                distance = max(abs(npc_pos[0] - p1_x), abs(npc_pos[1] - p1_y))
                if distance <= 1:
                    size_class = "d1"
                elif distance <= 2:
                    size_class = "d2"
                elif distance <= 4:
                    size_class = "d3"
                else:
                    size_class = "d4"
                npcs_to_add.append((sort_key, npc_name, portrait_path, distance, size_class))

            npcs_to_add.sort(key=lambda x: x[0])
            for idx, (sort_key, name, path, dist, size) in enumerate(npcs_to_add[:4]):
                if sort_key > 1:
                    pos_name = "far-right"
                elif sort_key == 1:
                    pos_name = "right"
                elif sort_key == 0:
                    pos_name = "center"
                elif sort_key == -1:
                    pos_name = "left"
                else:
                    pos_name = "far-left"

                ill_state["layers"].append({
                    "type": "portrait",
                    "image": path,
                    "position": pos_name,
                    "name": name,
                    "distance": dist,
                    "size_class": size,
                })

            with open(os.path.join(docs_dir, "illustration_state.json"),
                       "w", encoding="utf-8") as f:
                json.dump(ill_state, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _build_static_player_stats(self, game_state, docs_dir):
        """정적 웹용 플레이어 상세 파일 빌드.
        동적 API(/api/player-stats/<id>)는 game_state + entity를 머지해서 반환하므로,
        정적에서도 동일한 머지 결과를 entities/ 안에 덮어쓴다."""
        scenario_id = game_state.get("game_info", {}).get("scenario_id", "")
        if not scenario_id:
            return
        players_dir = os.path.join(docs_dir, "entities", scenario_id, "players")
        if not os.path.isdir(players_dir):
            return

        for p in game_state.get("players", []):
            pid = p.get("id")
            entity_path = os.path.join(
                BASE_DIR, "entities", scenario_id, "players", f"player_{pid}.json")
            if not os.path.isfile(entity_path):
                continue

            with open(entity_path, "r", encoding="utf-8") as f:
                entity = json.load(f)

            # 동적 API와 동일한 머지: game_state 기본 + entity의 equipment/actions
            merged = dict(p)
            merged.setdefault("equipment", entity.get("equipment"))
            merged.setdefault("available_actions", entity.get("available_actions"))
            # entity 고유 필드도 포함 (growth, skills, history 등)
            for key in ("growth", "skills", "history", "personality",
                        "relationships", "class_features", "original_image"):
                if key in entity and key not in merged:
                    merged[key] = entity[key]

            dst = os.path.join(players_dir, f"player_{pid}.json")
            with open(dst, "w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)

    def _build_static_settings(self, game_state, docs_dir):
        """정적 웹용 settings JSON 빌드.
        동적 API(/api/settings)는 current_session + game_state.difficulty를 합산."""
        session_path = os.path.join(BASE_DIR, "data", "current_session.json")
        if not os.path.isfile(session_path):
            return

        with open(session_path, "r", encoding="utf-8") as f:
            session = json.load(f)

        settings = {
            "sd_illustration": session.get("sd_illustration", False),
            "show_dice_result": session.get("show_dice_result", False),
            "display_mode": session.get("display_mode", "mobile"),
            "difficulty": game_state.get("game_info", {}).get("difficulty", "normal"),
        }

        dst = os.path.join(docs_dir, "current_session.json")
        with open(dst, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
