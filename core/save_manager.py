import json
import os
import sys
sys.stdout.reconfigure(encoding='utf-8')
import shutil
import glob
import filecmp
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAVES_DIR = os.path.join(BASE_DIR, "saves")
GAME_STATE_PATH = os.path.join(BASE_DIR, "data", "game_state.json")
CURRENT_SESSION_PATH = os.path.join(BASE_DIR, "data", "current_session.json")

# 백업 보관 최대 수
MAX_BACKUPS = 5


EVENTS_ARCHIVE_PATH = os.path.join(BASE_DIR, "data", "events_archive.json")


def archive_old_events(game_state_path=None, max_recent=10):
    """game_state의 events가 max_recent를 초과하면 오래된 이벤트를 아카이브 파일로 이동.

    - 최근 max_recent개만 game_state에 유지
    - 나머지는 data/events_archive.json에 추가 (append)
    - 아카이브 파일은 시나리오별로 구분
    """
    if game_state_path is None:
        game_state_path = GAME_STATE_PATH

    # 1. Load game_state.json
    if not os.path.isfile(game_state_path):
        return 0

    with open(game_state_path, "r", encoding="utf-8") as f:
        game_state = json.load(f)

    events = game_state.get("events", [])

    # 2. If events count <= max_recent, do nothing
    if len(events) <= max_recent:
        return 0

    # 3. Split events into archive (older) and keep (recent max_recent)
    to_archive = events[:-max_recent]
    to_keep = events[-max_recent:]

    # 4. Append archived events to data/events_archive.json
    scenario_id = game_state.get("game_info", {}).get("scenario_id", "unknown")
    today = datetime.now().strftime("%Y-%m-%d")

    archive_path = os.path.join(os.path.dirname(game_state_path), "events_archive.json")

    if os.path.isfile(archive_path):
        with open(archive_path, "r", encoding="utf-8") as f:
            archive_data = json.load(f)
    else:
        archive_data = {
            "scenario_id": scenario_id,
            "archived_events": [],
        }

    # 시나리오 ID가 다르면 경고하되 계속 진행 (동일 파일에 누적)
    if archive_data.get("scenario_id") != scenario_id:
        print(f"[WARN] archive: 기존 아카이브 scenario_id='{archive_data.get('scenario_id')}' ≠ 현재='{scenario_id}'")
        archive_data["scenario_id"] = scenario_id

    # archived_at 타임스탬프 추가
    for evt in to_archive:
        evt["archived_at"] = today

    archive_data["archived_events"].extend(to_archive)

    with open(archive_path, "w", encoding="utf-8") as f:
        json.dump(archive_data, f, ensure_ascii=False, indent=2)

    # 5. Update game_state.json with only recent events
    game_state["events"] = to_keep
    with open(game_state_path, "w", encoding="utf-8") as f:
        json.dump(game_state, f, ensure_ascii=False, indent=2)

    # 6. Return count of archived events
    archived_count = len(to_archive)
    print(f"[INFO] archive: {archived_count}개 이벤트 아카이브 완료 (유지: {len(to_keep)}개)")
    return archived_count


class SaveManager:
    def __init__(self):
        os.makedirs(SAVES_DIR, exist_ok=True)

    def _save_dir(self, scenario_id, slot=None):
        if slot:
            return os.path.join(SAVES_DIR, scenario_id, f"slot_{slot}")
        return os.path.join(SAVES_DIR, scenario_id)

    def find_empty_slot(self, scenario_id, max_slots=10):
        """비어있는 가장 낮은 번호의 슬롯을 찾는다. 없으면 None."""
        for i in range(1, max_slots + 1):
            save_file = os.path.join(self._save_dir(scenario_id, i), "save.json")
            if not os.path.exists(save_file):
                return i
        return None

    def get_slot_info(self, scenario_id, slot):
        """슬롯에 저장된 세이브 정보를 반환. 없으면 None."""
        save_file = os.path.join(self._save_dir(scenario_id, slot), "save.json")
        if not os.path.exists(save_file):
            return None
        try:
            with open(save_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("save_info", {})
        except Exception:
            return None

    def save_game(self, scenario_id, slot=1, description="", overwrite=False):
        """현재 게임 상태를 시나리오별 슬롯에 저장.
        저장 전 기존 파일 자동 백업 + 정합성 검증.
        overwrite=False일 때, 기존 세이브가 있으면 저장을 거부하고 빈 슬롯을 안내한다."""
        save_path = self._save_dir(scenario_id, slot)
        os.makedirs(save_path, exist_ok=True)

        with open(GAME_STATE_PATH, "r", encoding="utf-8") as f:
            game_state = json.load(f)

        # 정합성 검증: game_state의 scenario_id와 저장 대상이 일치해야 함
        gs_scenario = game_state.get("game_info", {}).get("scenario_id", "")
        if gs_scenario and gs_scenario != scenario_id:
            print(f"[WARN] save_game: game_state.scenario_id='{gs_scenario}' ≠ save target='{scenario_id}'")
            print(f"  다른 시나리오의 데이터를 잘못된 슬롯에 저장하는 것을 방지합니다.")
            print(f"  강제 저장이 필요하면 game_state.scenario_id를 먼저 수정하세요.")
            return None

        # 현재 활성 슬롯 확인 — 활성 슬롯이면 자동 덮어쓰기 허용
        save_file = os.path.join(save_path, "save.json")
        is_active_slot = False
        if os.path.exists(CURRENT_SESSION_PATH):
            try:
                with open(CURRENT_SESSION_PATH, "r", encoding="utf-8") as f:
                    session = json.load(f)
                active_scenario = session.get("active_scenario", "")
                active_slot = session.get("active_save_slot", -1)
                is_active_slot = (active_scenario == scenario_id and active_slot == slot)
            except Exception:
                pass

        # 기존 세이브 덮어쓰기 방지 (활성 슬롯은 제외)
        if os.path.exists(save_file) and not overwrite and not is_active_slot:
            existing = self.get_slot_info(scenario_id, slot)
            if existing:
                party_str = ", ".join(
                    f"{p['name']}({p['class']})" for p in existing.get("party_summary", [])
                ) or "(파티 정보 없음)"
                print(f"[BLOCK] 슬롯 {slot}에 기존 세이브가 있습니다:")
                print(f"  파티: {party_str}")
                print(f"  턴 {existing.get('turn_count', '?')}, "
                      f"ch{existing.get('chapter', '?')}, "
                      f"{existing.get('description', '')}")
                print(f"  saved_at: {existing.get('saved_at', '?')}")
                empty = self.find_empty_slot(scenario_id)
                if empty:
                    print(f"  → 빈 슬롯 추천: slot {empty}")
                    print(f"  덮어쓰려면 overwrite=True를 명시하세요.")
                else:
                    print(f"  → 빈 슬롯이 없습니다. overwrite=True로 덮어쓰세요.")
                return None

        # 파티 요약 생성 (세이브 식별용)
        party_summary = []
        for p in game_state.get("players", []):
            party_summary.append({
                "name": p.get("name", ""),
                "class": p.get("class", ""),
                "level": p.get("level", 1),
                "controlled_by": p.get("controlled_by", "ai"),
            })

        save_data = {
            "save_info": {
                "scenario_id": scenario_id,
                "slot": slot,
                "description": description,
                "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "turn_count": game_state.get("turn_count", 0),
                "chapter": self._detect_chapter(game_state),
                "party_summary": party_summary,
            },
            "game_state": game_state,
        }

        # 기존 세이브 백업 (덮어쓰기 전)
        save_file = os.path.join(save_path, "save.json")
        self._backup_save(save_file)

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
        """저장된 게임 상태를 불러와서 현재 게임에 적용.
        로드 전 현재 game_state.json 자동 백업."""
        save_file = os.path.join(self._save_dir(scenario_id, slot), "save.json")
        if not os.path.exists(save_file):
            return None

        with open(save_file, "r", encoding="utf-8") as f:
            save_data = json.load(f)

        # 세이브 정합성 검증
        save_scenario = save_data.get("save_info", {}).get("scenario_id", "")
        gs_scenario = save_data.get("game_state", {}).get("game_info", {}).get("scenario_id", "")
        if save_scenario and gs_scenario and save_scenario != gs_scenario:
            print(f"[WARN] load_game: save_info.scenario_id='{save_scenario}' ≠ game_state.scenario_id='{gs_scenario}'")
            print(f"  세이브 파일 내부 불일치 — 데이터 오염 가능성")

        # 현재 game_state.json 백업 (로드로 덮어쓰기 전)
        self._backup_save(GAME_STATE_PATH)

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

    def _backup_save(self, file_path):
        """파일 덮어쓰기 전 자동 백업. 최대 MAX_BACKUPS개 유지."""
        if not os.path.isfile(file_path):
            return
        backup_dir = os.path.join(os.path.dirname(file_path), ".backups")
        os.makedirs(backup_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = os.path.basename(file_path)
        backup_name = f"{base_name}.{timestamp}.bak"
        backup_path = os.path.join(backup_dir, backup_name)
        shutil.copy2(file_path, backup_path)

        # 오래된 백업 정리 (MAX_BACKUPS개 초과 시 삭제)
        backups = sorted(
            [f for f in os.listdir(backup_dir) if f.startswith(base_name) and f.endswith(".bak")],
            reverse=True,
        )
        for old in backups[MAX_BACKUPS:]:
            os.remove(os.path.join(backup_dir, old))

    def validate_save(self, scenario_id, slot=1):
        """세이브 파일 정합성 검증. 문제 목록 반환 (빈 리스트 = 정상)."""
        errors = []
        save_file = os.path.join(self._save_dir(scenario_id, slot), "save.json")
        if not os.path.exists(save_file):
            return [f"세이브 파일 없음: {save_file}"]

        with open(save_file, "r", encoding="utf-8") as f:
            save_data = json.load(f)

        info = save_data.get("save_info", {})
        gs = save_data.get("game_state", {})
        gi = gs.get("game_info", {})

        # 1. scenario_id 일치
        if info.get("scenario_id") != scenario_id:
            errors.append(f"save_info.scenario_id='{info.get('scenario_id')}' ≠ 폴더='{scenario_id}'")
        if gi.get("scenario_id") and gi["scenario_id"] != scenario_id:
            errors.append(f"game_state.scenario_id='{gi['scenario_id']}' ≠ 폴더='{scenario_id}'")

        # 2. save_info와 game_state 내부 일치
        if info.get("scenario_id") != gi.get("scenario_id"):
            errors.append(f"save_info.scenario_id='{info.get('scenario_id')}' ≠ game_state.scenario_id='{gi.get('scenario_id')}'")

        # 3. 필수 필드 존재
        for key in ["players", "npcs", "events"]:
            if key not in gs:
                errors.append(f"game_state.{key} 누락")

        # 4. current_location 유효성
        loc = gs.get("current_location")
        if not loc:
            errors.append("current_location 비어있음")
        else:
            wb_path = os.path.join(BASE_DIR, "data", "worldbuilding.json")
            if os.path.exists(wb_path):
                with open(wb_path, "r", encoding="utf-8") as f:
                    wb = json.load(f)
                if loc not in wb.get("locations", {}):
                    errors.append(f"current_location='{loc}'이 worldbuilding에 없음")

        # 5. NPC가 해당 시나리오에 소속되는지 (시나리오 파일과 대조)
        scenario_path = os.path.join(BASE_DIR, "scenarios", f"{scenario_id}.json")
        if os.path.exists(scenario_path):
            with open(scenario_path, "r", encoding="utf-8") as f:
                scenario = json.load(f)
            valid_npc_ids = {n["id"] for n in scenario.get("default_npcs", [])}
            # 시나리오 default_npcs에 없는 NPC는 게임 중 추가된 것 → 경고만
            for npc in gs.get("npcs", []):
                npc_id = npc.get("id")
                if npc_id and npc_id not in valid_npc_ids and npc.get("status") not in ("dead", "removed", "fled"):
                    errors.append(f"NPC '{npc.get('name', npc_id)}'(id={npc_id})이 시나리오 default_npcs에 없음 (게임 중 추가?)")

        # 6. 플레이어 HP/MP 범위
        for p in gs.get("players", []):
            name = p.get("name", "?")
            if p.get("hp", 0) > p.get("max_hp", 0):
                errors.append(f"{name} HP({p['hp']}) > max_hp({p['max_hp']})")
            if p.get("mp", 0) > p.get("max_mp", 0):
                errors.append(f"{name} MP({p['mp']}) > max_mp({p['max_mp']})")

        return errors

    def validate_all_saves(self):
        """모든 세이브 파일 정합성 검증. {scenario_id/slot: errors} 반환."""
        results = {}
        if not os.path.exists(SAVES_DIR):
            return results
        for sid in os.listdir(SAVES_DIR):
            sid_path = os.path.join(SAVES_DIR, sid)
            if not os.path.isdir(sid_path):
                continue
            for slot_dir in os.listdir(sid_path):
                if not slot_dir.startswith("slot_"):
                    continue
                try:
                    slot_num = int(slot_dir.replace("slot_", ""))
                except ValueError:
                    continue
                errors = self.validate_save(sid, slot_num)
                if errors:
                    results[f"{sid}/{slot_dir}"] = errors
        return results

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
        existing_show_system_log = False
        existing_sd_illustration = False
        if os.path.exists(CURRENT_SESSION_PATH):
            with open(CURRENT_SESSION_PATH, "r", encoding="utf-8") as f:
                existing = json.load(f)
                existing_display_mode = existing.get("display_mode", "mobile")
                existing_show_dice = existing.get("show_dice_result", False)
                existing_show_system_log = existing.get("show_system_log", False)
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
            "show_system_log": existing_show_system_log,
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

        # 1b. lang/ 디렉토리 — ko.json 등
        self._sync_dir_incremental(
            os.path.join(BASE_DIR, "lang"),
            os.path.join(docs_dir, "lang"))

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

        # 맵 디렉토리 (maps/local + maps/world)
        self._sync_dir_incremental(
            os.path.join(BASE_DIR, "static", "maps"),
            os.path.join(docs_dir, "static", "maps"))

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
        """정적 웹용 illustration_state.json 생성 — 동적 웹의 scene_state를 반영"""
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

            # 배경/레이어 결정: 3단계 폴백
            # 1) sd_generator 메모리 (Flask 내 호출)
            # 2) Flask API HTTP 호출 (CLI에서 Flask가 동작 중일 때)
            # 3) glob 최신 파일 (Flask 미실행)
            background = None
            live_layers = []

            # 1단계: sd_generator 메모리
            try:
                from core.sd_generator import get_scene_state
                scene = get_scene_state()
                if scene.get("background"):
                    background = scene["background"].lstrip("/")
                    live_layers = scene.get("layers", [])
            except Exception:
                pass

            # 2단계: Flask API 호출 (1단계에서 background를 못 가져왔을 때)
            if not background:
                try:
                    import urllib.request
                    req = urllib.request.Request("http://localhost:5000/api/illustration", method="GET")
                    resp = urllib.request.urlopen(req, timeout=2)
                    import json as _json
                    api_data = _json.loads(resp.read().decode("utf-8"))
                    if api_data.get("background"):
                        background = api_data["background"].lstrip("/")
                    if api_data.get("layers") and not live_layers:
                        live_layers = api_data["layers"]
                except Exception:
                    pass

            # 3단계: glob 최신 파일
            if not background:
                sd_bgs = sorted(
                    glob.glob(os.path.join(
                        BASE_DIR, "static", "illustrations", "sd", "background_*")),
                    key=os.path.getmtime, reverse=True)
                if sd_bgs:
                    background = "static/illustrations/sd/" + os.path.basename(sd_bgs[0])

            # live_layers의 이미지 경로도 상대경로로 정규화
            for layer in live_layers:
                if "image" in layer:
                    layer["image"] = layer["image"].lstrip("/")

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

            # sd_generator에서 가져온 라이브 레이어가 있으면 우선 사용
            if live_layers:
                for layer in live_layers:
                    img_path = layer.get("image", "")
                    ill_state["layers"].append({
                        "type": layer.get("type", "portrait"),
                        "image": img_path.lstrip("/"),
                        "position": layer.get("position", "center"),
                        "name": layer.get("name", ""),
                        "distance": layer.get("distance", 0),
                        "size_class": layer.get("size_class", "d2"),
                    })

            if not live_layers:
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
        except Exception as e:
            print(f"[WARN] illustration state 빌드 실패: {e}")

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
        """정적 웹용 current_session.json 보강.
        동적 API(/api/settings)가 game_state.difficulty를 합산하므로,
        이미 복사된 current_session.json에 difficulty를 추가한다."""
        dst = os.path.join(docs_dir, "current_session.json")
        if not os.path.isfile(dst):
            return

        with open(dst, "r", encoding="utf-8") as f:
            session = json.load(f)

        # 동적 API가 합산하는 필드 보강
        session["difficulty"] = game_state.get(
            "game_info", {}).get("difficulty", "normal")

        with open(dst, "w", encoding="utf-8") as f:
            json.dump(session, f, ensure_ascii=False, indent=2)
