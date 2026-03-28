# TRPG 시스템 (Claude GM)

Claude Code CLI 터미널에서 Claude가 GM 역할을 하며 진행하는 TRPG 시스템.
웹 UI는 **표시 전용** (Flask + PIL). 실제 게임 진행은 터미널에서만.
시나리오와 룰셋을 교체하여 판타지, 현대, 공포(CoC) 등 다양한 세계관에서 플레이 가능.

---

## ⚠️ 핵심 규칙 요약 (모든 세션 필독)

> **이 섹션은 모든 세션에서 가장 먼저 읽고 준수해야 한다.**

### 절대 금지
- ❌ 유저 캐릭터(controlled_by: "user")의 대사/감정/판단을 GM이 만들지 않는다
- ❌ 터미널에만 나레이션 쓰고 웹 반영(gm-update) 안 하는 것
- ❌ "나중에 하겠습니다", "TODO" — 발견 즉시 처리 또는 폴백
- ❌ 나레이션과 시스템 출력이 같은 블록에 섞이는 것 (단계 분리 필수, 나레이션은 굵게 구분하여 출력)
- ❌ 배경 위 인물 레이어에 불투명 배경 사용
- ❌ 동일 인물의 외형이 장면마다 바뀌는 것
- ❌ GM이 에이전트를 거치지 않고 직접 판단하는 것 (세계관/룰/NPC 관련)
- ❌ show_dice_result: false인데 나레이션에 판정 수치를 노출하는 것 (표시 설정과 무관하게 내부 기록은 항상 필수)
- ❌ 판정을 했는데 이벤트에 기록하지 않는 것 (판정 기록 ≠ 판정 표시)
- ❌ 세이브 파일을 백업 없이 덮어쓰거나 삭제하는 것
- ❌ 기존 세이브가 있는 슬롯에 확인 없이 저장하는 것 (반드시 빈 슬롯 또는 active_save_slot 사용)
- ❌ 다른 시나리오의 데이터를 세이브에 혼합하는 것 (scenario_id 불일치)
- ❌ 세이브 데이터를 추측으로 조작하는 것 (실제 플레이 데이터를 찾아서 사용)

### 필수 자동화 (코드로 동작)
- ✅ Flask 시작/로드 시 `restore_scene()` → 배경 자동 복원
- ✅ 이미지 생성: SD WebUI 우선 → Skia 폴백 (빈 화면 없음), 이미지 재활용 (기존 고퀄 우선), 초상화 배경 자동 제거
- ✅ 저장 시 docs/ 자동 동기화 (GitHub Pages) — build_static.py가 HTML 복사 + 데이터(JSON, 이미지) 동기화
- ✅ 비활성 슬롯 덮어쓰기 자동 거부 (활성 슬롯은 허용, 비활성은 차단 + 빈 슬롯 안내)
- ✅ 세이브 덮어쓰기 전 자동 백업 (`.backups/`, 최대 5개)
- ✅ 세이브 저장/로드 시 scenario_id 정합성 자동 검증
- ✅ session_validator가 모든 세이브 파일 정합성 검증 (scenario_id, NPC 오염, 위치)
- ✅ NPC 엔티티 자동 생성 (check_npcs) — GM이 언급했으나 등록을 누락한 NPC를 위한 안전망
- ✅ 연계 시나리오 시 세계관 NPC 상태 자동 이월 (사망/기억/관계)
- ✅ 새 게임 시 monster 엔티티만 정리, 세계관 NPC(friendly/neutral) 보존
- ✅ session_validator가 NPC 시간 정합성 검증 (이전 시나리오 사망 NPC ↔ 현재 상태)
- ✅ 맵 장소별 자동 전환 (current_location → worldbuilding.json)

### 매 턴 필수 (GM이 반드시 지켜야 함)
- ❗ AI 플레이어의 행동/대사는 Player Agent가 생성한다 — GM이 직접 쓰지 않는다
- ❗ NPC 대사/행동은 NPC Agent가 생성한다 — GM이 직접 쓰지 않는다 (NPC는 능동적으로 행동한다)
- ❗ 판정은 룰 Agent가 처리한다 — GM이 직접 주사위를 굴리지 않는다
- ❗ 판정 상세(주사위값, DC, 수정치, 결과)는 gm-update의 dice_rolls 필드로 항상 기록한다
- ❗ 위치 변경 시 배경 일러스트를 반드시 교체한다 (시간대도 반영: 낮/밤/새벽)
- ❗ 세계 지도 데이터 변경 시 세계관/세계지도 에이전트 검토 필수 (상세: guides/illustration.txt '세계 지도 최종 검토')
- ❗ 나레이션에 개별 묘사된 NPC는 game_state에 등록한다 (자동 생성은 안전망 — GM이 1차 등록 책임; 또는 배경 묘사로 처리)
- ❗ 새 설정(지명/NPC/경로)은 에이전트에 확인 후 나레이션에 포함한다
- ❗ 이벤트 로그에 잘못된 정보가 발견되면 즉시 수정한다
---

## 플레이어 vs 캐릭터 (IC/OOC 구분)

> 이 시스템은 세 계층이 있다: **유저** (실제 사람), **AI 플레이어** (AI 페르소나), **캐릭터** (게임 내 존재).

| 계층 | 정체성 | 예시 | 역할 |
|------|--------|------|------|
| **유저** | 터미널 앞의 실제 사람 | 당신 (인간) | 캐릭터 직접 조종, AI에게 OOC 지시, 모든 최종 결정권 |
| **AI 플레이어 (OOC)** | 인간처럼 플레이하는 AI 페르소나 | 준혁, 서연, 민지, 수아, 지현 | 각자 성격/플레이스타일 보유. Player Agent로 배정된 캐릭터 조종 |
| **캐릭터 (IC)** | 게임 내 인물 | 사이키, 루세나, 노엘, 가온 등 | 게임 세계에 존재. 유저 또는 AI 플레이어가 조종 |

### 매핑 (시나리오별)
- AI 플레이어 ↔ 캐릭터 매핑은 `agents/agent_*.json`의 `current_character`로 정의
- 유저가 직접 조종할 캐릭터를 선택 (controlled_by: "user")
- 유저가 어떤 AI 플레이어가 어떤 캐릭터를 조종할지 선택 — 언제든 변경 가능
- 5명의 AI 플레이어(agent_a~e)는 모두 동급 — 어느 하나가 "유저의 분신"이 아님

### 현재 매핑 (karendel_journey):
- 유저 → 사이키 (controlled_by: "user")
- agent_b (서연) → 루세나 (controlled_by: "ai")
- agent_c (민지) → 노엘 (controlled_by: "ai")

### GM 판별 규칙
- **IC 입력**: 캐릭터 이름 사용, 게임 내 행동/대사 → GM 턴으로 처리 (나레이션)
- **OOC 입력**: AI 플레이어 이름 사용 (민지, 서연), 메타 발언 (전략, 규칙) → Player Agent를 OOC 모드로 호출, AI 플레이어 페르소나로 응답
- **유저 지시**: 유저가 AI 플레이어에게 직접 명령 ("수아, 가온으로 정찰해") → AI 플레이어가 실행
- OOC 응답은 나레이션이나 이벤트 로그에 포함하지 않는다
- AI 플레이어끼리 또는 유저와 OOC 전략 상의 후, IC로 전환하여 실제 턴 진행 가능

---

## GM 턴 처리 순서 (엄격 준수)

> GM = 연출가 (전체 흐름을 알고 방향을 잡는다), 에이전트 = 전문가 (방향이 정합한지 검증 + 구체적 결과 생성)
> 에이전트는 매번 새로 생성되어 대화 컨텍스트가 없다. GM만 전체 흐름을 안다.
> 따라서 GM이 먼저 방향을 잡고, 그 방향을 에이전트에게 전달해야 한다.

```
유저 액션 선언
 → [1a] GM 방향 설정 (이벤트/분위기/전개 판단, 에이전트 선정)
 → [1b] 에이전트 병렬 호출 (방향 + 맥락 + 질문 전달 → 검증 + 결과 수신)
 → [2]  나레이션 작성 (에이전트 결과 종합)
 → [3]  시스템 반영 (Agent [시스템 반영]: state/gm-update/일러스트/로그/git)
 → 나레이션 출력 + 맵 표시 + 행동 대기
```

> 상세 (각 단계 설명 + 예시): guides/gm_rules.txt 참조

### GM 턴 템플릿 (매 턴 이 순서를 따른다)

> **gm_turn.py 필수 사용**: 매 턴 `start → phase/agent/log → end` 호출로 추적한다.
> gm_turn.py가 show_system_log 설정에 따라 터미널 출력을 자동 제어한다.
> 핵심 흐름: `gm_turn.py start` → phase 1a (방향) → phase 1b (에이전트) → phase 2 (나레이션) → phase 3 (시스템 반영) → `gm_turn.py end`
> show_system_log: 단계 헤더/에이전트명은 항상 표시, 세부 내용은 on/off, 내부 로그는 무조건 기록.
> 상세 템플릿 + show_system_log 출력 예시: guides/gm_rules.txt 참조

---

## Agent 분담 구조

```
유저 (터미널 채팅으로 액션 선언)
  ↓
메인 Claude = GM (나레이션/진행/유저 상호작용)
  ├── Agent [룰 심판]      — 판정, 주사위, 전투 규칙 검증
  ├── Agent [시나리오]      — 챕터/이벤트/엔딩 분기, 퀘스트 상태
  ├── Agent [세계관]        — 지명/화폐/세력/NPC, 정합성 검증
  ├── Agent [Player:{name}] — AI 플레이어 의사결정/대사/행동 (user 제외)
  ├── Agent [NPC:{name}]    — NPC 대사/행동/능동적 판단
  ├── Agent [세계 지도]     — 좌표/지리 검증, 경로, 지도 갱신
  └── Agent [시스템 반영]   — game_state, gm-update, 일러스트, 로그, git
  ↓
결과 종합 → 나레이션 + 맵 출력 + game_state.json 업데이트 + 저장(git push)
```

> 각 에이전트의 필수 읽기 파일, 역할 상세, 페르소나: guides/entities.txt 참조

> **에이전트 필수 읽기 규칙**: 모든 하위 에이전트는 호출 시 "필수 읽기" 파일을 반드시 먼저 읽고 동작해야 한다. 가이드를 읽지 않고 동작하는 것은 금지.

> **에이전트 호출 공통 규칙**: 에이전트는 매번 새로 생성되어 대화 컨텍스트가 없다. GM이 1b단계에서 반드시 방향 + 맥락 + 구체적 질문을 전달해야 한다. 상세: guides/gm_rules.txt 참조.

---

## 세이브 관리 규칙

> **세이브 = 유저의 플레이 기록. 2중 3중으로 보호한다.**

### 4중 안전망
1. **덮어쓰기 방지** (코드): 비활성 슬롯에 기존 세이브가 있으면 자동 거부 + 빈 슬롯 안내. 활성 슬롯(active_save_slot)은 자동 허용
2. **자동 백업** (코드): save_manager가 덮어쓰기 전 `.backups/`에 자동 백업 (최대 5개)
3. **정합성 검증** (코드): 저장/로드 시 scenario_id 일치 자동 체크, 불일치하면 저장 거부
4. **세션 검증** (수동): `session_validator.py`가 모든 세이브 파일의 scenario_id, NPC, 위치 검증

### 세이브 데이터 수정 시 필수 원칙
- ❗ **실제 플레이 데이터를 찾아서 사용한다** — 추측으로 만들지 않는다
- ❗ **수정 전 반드시 백업한다** — 코드가 자동으로 하지만, 수동 작업 시에도 반드시
- ❗ **scenario_id가 폴더명과 일치해야 한다** — `saves/lost_treasure/`에 karendel_journey 데이터 금지
- ❗ **타 시나리오 NPC가 섞이면 안 된다** — 시나리오별 NPC는 해당 시나리오 세이브에만
- ❗ **시나리오 분리 시 세이브도 분리한다** — 각 시나리오별 독립 세이브 유지
- ❗ **새 게임 시작이 기존 세이브를 삭제하지 않는다** — 기존 세이브는 항상 보존
- ❗ **연계 시나리오에서 NPC 시간 연속성을 지킨다** — 이전에서 죽은 NPC는 다음에서도 dead

### NPC 시간 연속성 (연계 시나리오)
- **이어하기**: `_carry_over_npc_states()`가 dead/memory/relationships 자동 이월 (monster 제외)
- **새 게임**: NPC 초기 상태 (시간 리셋). session_validator [11]이 시간 모순 자동 감지

### 세이브 구조
```
saves/
  {scenario_id}/
    progress.json           - 진행 히스토리 (턴/챕터/설명 기록)
    slot_1/
      save.json             - 세이브 데이터 (save_info + game_state)
      .backups/             - 자동 백업 (덮어쓰기 전 보관, 최대 5개)
        save.json.20260321_035021.bak
    slot_2/ ...
```

---

## 기술 스택
- **백엔드**: Flask 2.3.0 (Python)
- **이미지**: SD WebUI API (포트 7860) + Skia/Pillow 폴백
- **데이터**: JSON 파일 기반 (game_state.json + entities/)
- **프론트엔드**: 순수 HTML/CSS/JS (2초 폴링, 표시 전용)

---

## 파일 구조 (주요)
```
app.py                    - Flask 웹 서버, API 엔드포인트, gm-update 처리
game_start.py             - 게임 시작 자동화 CLI (새 게임/이어하기/세이브 로드)
build_static.py           - docs/ 데이터 동기화 CLI (save_manager._sync_docs 호출)
session_validator.py      - 세션 검증 자동화 (상태 일관성 검사 + 자동 수정)
core/                     - Python 엔진 모듈 (패키지)
  __init__.py
  sd_generator.py         - SD WebUI API 래퍼, 레이어 시스템
  map_generator.py        - Skia/PIL 이미지 생성, SD OFF 시 폴백
  ascii_map.py            - 터미널 블록맵 (유저 요청 시에만 `python core/ascii_map.py` 실행, 웹 맵과 별개)
  gm_turn.py              - GM 턴 추적기 (실행 작업 기록 + 누락 경고)
  save_manager.py         - 세이브/로드 매니저
  game_mechanics.py       - 주사위, 판정, 전투, 회복, 아이템, 상태이상 처리
data/                     - JSON 데이터 파일
  game_state.json         - 현재 게임 상태
  current_session.json    - 현재 활성 세션 요약 (세션 복원용)
  worldbuilding.json      - 세계관 설정 (시나리오 독립)
  rules.json / scenario.json / quests.json - 활성 룰셋/시나리오/퀘스트
  items.json / skills.json / status_effects.json / creature_templates.json / shops.json - 게임 데이터 DB
  pending_actions.json    - 보류 중인 액션
  game_state_initial.json - 초기 게임 상태 템플릿
agents/                   - 플레이어 에이전트 정체성 (시나리오 독립, 지속)
  agent_a.json            - 에이전트 A (성별, 성격, 플레이스타일, current_character)
entities/{scenario_id}/   - npcs/ players/ objects/ 엔티티 파일
rulesets/ / scenarios/    - 룰셋/시나리오 카탈로그
worldbuildings/           - 세계관 파일 카탈로그 (시나리오에서 참조)
static/                   - 맵, 초상화, 일러스트 이미지
  maps/local/map.png      - 전체 맵 (클릭 확대용, ~1000x1000px)
  maps/local/map_mini.png - 미니맵 (플레이어 중심 크롭, 사이드바용)
  maps/world/{세계관}/     - 월드맵 (world_map.png, background_skia.webp, background_sd.webp)
templates/                - 웹 UI (동적/정적 자동 감지) + 캐릭터 클래스 템플릿
docs/index.html           - templates/index.html 복사본 (build_static.py가 자동 복사)
saves/                    - 세이브 데이터
guides/                   - 상세 규칙 참조 파일
```

---

## 웹 관리 규칙

- **templates/index.html**만 편집 — docs/index.html은 build_static.py가 자동 복사
- 런타임에 isStatic 변수로 동적/정적 환경 자동 감지 (API/경로 전환)

---

## 세션 절차

### 공통 단계 (새 게임·로드 모두)
1. CLAUDE.md 읽기 (이 파일) — 특히 "핵심 규칙 요약" + "매 턴 필수" + "GM 턴 템플릿" 숙지
2. `python session_validator.py` 실행 — 상태 검증 + 자동 수정
3. `data/current_session.json` → `data/worldbuilding.json` → `data/game_state.json` 읽기
4. `guides/gm_rules.txt` 읽기 — 주사위 표시, NPC 등록, 에이전트 규칙 확인
5. Flask 서버 확인 → 웹 UI 장면 복원 (자동: `restore_scene`)
6. 현재 세션 설정을 유저에게 표시:
   - `show_dice_result` (true/false)
   - `show_system_log` (true/false)
   - `player_input_mode` (batch/sequential)
   - `sd_illustration` (true/false)

> 웹 UI가 빈 화면이거나 이전 장면을 보여주는 것은 금지.

### 새 게임 (turn_count=0, status=active)
game_start.py가 처리: 시나리오 선택 → 룰셋 선택 → 캐릭터 메이킹 → 데이터 초기화.
이후 GM이 오프닝 나레이션을 진행해야 게임이 시작된다 (GM 턴 0).

1. scenario.json의 opening.narrative 확인
2. GM 턴 템플릿대로 진행:
   - [1a] 오프닝 방향 설정 (첫 장면, 분위기, 등장인물)
   - [1b] 에이전트 호출 (세계관 정합성, NPC 있으면 대사)
   - [2] 오프닝 나레이션 작성 (캐릭터 등장 + 장면 묘사)
   - [3] 시스템 반영 (gm-update: 배경 일러스트 + 캐릭터 레이어)
3. 나레이션 출력 → 유저 행동 대기

> 오프닝 없이 "뭘 할래?"를 묻는 것은 금지. 캐릭터가 세계에 등장해야 행동할 수 있다.

### 로드 (저장된 게임 재개)
시나리오/룰셋/캐릭터 선택을 건너뛰고, 이전 세이브 데이터를 불러와 바로 게임을 진행한다.

1. 공통 단계 1-5 위 참조
2. `entities/{scenario_id}/` (players, npcs, objects) 읽기
3. `data/scenario.json` + `data/rules.json` 읽기
4. gm-update로 현재 장면 복원 (배경 + NPC 레이어)
5. 유저에게 현재 상황 요약 제시 → 행동 대기

### game_start.py 명령어
```bash
python game_start.py                    # 대화형: 시나리오 선택
python game_start.py new lost_treasure  # 특정 시나리오 새 게임
python game_start.py continue karendel_journey --from lost_treasure  # 이어하기
python game_start.py load               # 세이브 로드
```

---

## 실행 방법
```bash
pip install -r requirements.txt
C:\git\WebUI\stable-diffusion-webui\venv\Scripts\Python.exe app.py    # 웹 UI (SD venv 사용)
python core/ascii_map.py    # 터미널 맵 확인
# 또는 편의 스크립트: start_server.bat (Windows) / start_server.sh (Git Bash)
```

> **참고**: Flask 서버는 SD WebUI의 venv Python으로 실행해야 torch GPU, transparent-background, PIL 등
> 라이브러리를 통일할 수 있다. 시스템 Python에 별도 설치할 필요 없음.

---

## 상세 참조 파일

| 파일 | 내용 |
|------|------|
| `guides/gm_rules.txt` | GM 운영 규칙: 나레이션, 턴 처리, 웹 반영, 시스템 로그 |
| `guides/agents.txt` | 에이전트 역할, 호출 규칙, 최적화, 스키마 아키텍처, 경고 처리 |
| `guides/game_rules.txt` | 인게임 규칙: 주사위, 커버, 낙하 데미지, 환경 위험, 시야, 무게 |
| `guides/map_rules.txt` | 맵 표시 전략, 맵 시스템, 엔티티 표시, 미니맵 크롭, 좌표 기반 거리 시스템 |
| `guides/save_rules.txt` | 저장 규칙 (commit/push 타이밍, 메시지 형식, 저장 대상 파일) |
| `guides/illustration.txt` | SD 연동, 레이어 시스템, 파라미터, 사전 생성 이미지, 외형 일관성, 품질 관리 |
| `guides/sd_environment.txt` | SD WebUI 경로, 실행 명령, 모델/VAE/확장 목록, 호환성 수정 |
| `guides/entities.txt` | NPC 엔티티 규칙, JSON 구조, 자동 생성, Agent 연속성, 시스템 반영 Agent 상세 |
| `guides/api.txt` | 전체 API 엔드포인트 목록, gm-update 파라미터 |
| `guides/scenario.txt` | 시나리오/룰셋 추가 방법, 구성 요소, 게임 시작 플로우 |
| `guides/process.txt` | 프로세스 관리, 실행/종료, 중복 방지, 상태 확인 |
