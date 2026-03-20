# TRPG 시스템 (Claude GM)

## 프로젝트 개요
Claude Code CLI 터미널에서 Claude가 GM 역할을 하며 진행하는 TRPG 시스템.
웹 UI는 **표시 전용** (Flask + PIL). 실제 게임 진행은 터미널에서만.
시나리오와 룰셋을 교체하여 판타지, 현대, 공포(CoC) 등 다양한 세계관에서 플레이 가능.

---

## 게임 진행 방식

### 역할 분담
- **터미널(Claude GM)**: 액션 선언 수신 → 판정 → 나레이션 → 상태 업데이트
- **웹 UI** (`http://localhost:5000`): 표시 전용 — 맵/스탯/인벤토리/배경/초상화 실시간 표시. 행동 버튼 없음.

### GM 나레이션 원칙
- **캐릭터 시점으로만 묘사** — 캐릭터가 보고, 듣고, 느끼는 것만 전달
- **게임 수치/판정 정보 노출 금지** — DC, 성공/실패 결과, 아이템 효과 등을 미리 알려주지 않음
- **함정/위험 요소는 분위기로만 암시** — "함정이 있습니다"가 아니라 캐릭터가 느끼는 위화감으로 표현
- **선택지 제시 시 결과 스포일 금지** — 행동 옵션만 제시, 결과는 행동 후 판정으로 결정
- 나쁜 예: `"비문 조사 (INT DC 14 — 성공 시 고대 열쇠 획득)"`
- 좋은 예: `"벽면에 무언가 빽빽하게 새겨져 있다. 오래된 문자들이 횃불 빛에 흐릿하게 반짝인다."`

### 이미지 전략 (토큰 절약)
- **위치 정보 제공 시 맵 필수** — 캐릭터 위치, 이동, 전투 배치 등을 알려줄 때 반드시 `python ascii_map.py` 맵도 함께 출력
- **웹/이미지 가능 환경** → PIL 이미지 자동 갱신. Claude가 위치를 텍스트로 설명할 필요 없음 → 토큰 절약
- **터미널(이미지 불가)** → `python ascii_map.py` 로 이모지 ASCII 맵 출력
- **커스텀 이미지** → `static/custom/` 폴더에 파일 두면 PIL 생성본 대신 사용
- **향후**: Stable Diffusion 로컬 API 연동 예정 (현재 미구현)

### 저장 규칙
- **저장 = git commit + push 한 세트** (반드시 push까지)
- 커밋 메시지 형식: `save: 턴N 내용 — 결과 요약`
- 브랜치: `claude/clarify-task-xApb3`

#### 저장 트리거 (아래 상황에서 반드시 즉시 저장)
| 상황 | 저장 대상 파일 |
|------|--------------|
| 전투 종료 | game_state.json, current_session.json, entities/{id}/npcs/ |
| 아이템 획득/분배/사용 | game_state.json, current_session.json, entities/{id}/players/ |
| 함정/오브젝트 상호작용 | game_state.json, current_session.json, entities/{id}/objects/ |
| 챕터 전환 | game_state.json, current_session.json 전체 |
| 캐릭터 HP/MP 변동 | game_state.json, current_session.json, entities/{id}/players/ |
| 퍼즐/이벤트 해결 | game_state.json, current_session.json, entities/{id}/objects/ |

#### 이벤트 로그 기록 원칙
- **모든 의미 있는 행동을 개별 이벤트로 기록** (여러 행동을 한 줄로 압축 금지)
- 나쁜 예: `"챕터 1 완료. 숲을 지나 던전 진입."` → 탐색/아이템/함정 내용 누락
- 좋은 예:
  - `"사이키가 숲에서 약초를 발견했다."`
  - `"루체나가 덩굴 함정을 해제했다. 밧줄 획득."`
  - `"챕터 1 완료. 던전 진입."`

---

## 기술 스택
- **백엔드**: Flask 2.3.0 (Python)
- **이미지**: Pillow (PIL) — 맵(800x600), 배경(800x450), 초상화(120x160)
- **데이터**: JSON 파일 기반 (game_state.json + entities/)
- **프론트엔드**: 순수 HTML/CSS/JS (2초 폴링, 표시 전용)

---

## 파일 구조
```
app.py                    - Flask 웹 서버 (포트 5000)
map_generator.py          - PIL 이미지 생성 (맵 + 배경 + 초상화)
ascii_map.py              - CLI 터미널용 이모지 ASCII 맵 출력
game_state.json           - 현재 게임 상태 (플레이어/NPC/맵/턴/이벤트)
current_session.json      - 현재 활성 세션 요약 (시나리오/세이브/진행상황 — 세션 복원용)
save_manager.py           - 세이브/로드 매니저
rules.json                - 현재 활성 룰셋 (심볼릭 또는 복사본)
scenario.json             - 현재 활성 시나리오 (심볼릭 또는 복사본)

rulesets/                 - 룰셋 카탈로그
  index.json              - 룰셋 목록 및 메타데이터
  fantasy_basic.json      - 판타지 기본 룰 (D20 시스템)
  (추가 룰셋...)

scenarios/                - 시나리오 카탈로그
  index.json              - 시나리오 목록 및 메타데이터
  (추가 시나리오...)

templates/                - 공통 템플릿
  character_classes.json  - 클래스별 캐릭터 생성 템플릿

entities/                 - 엔티티 파일 (Agent 연속성, 시나리오별 격리)
  {scenario_id}/
    npcs/                 - NPC 개별 상태 (성격/전투AI/기억)
    players/              - 플레이어 개별 상태 (능력치/인벤토리/히스토리)
    objects/              - 오브젝트 상태 (함정/퍼즐/보물상자)

static/
  map.png                 - 현재 맵 이미지 (자동 생성)
  backgrounds/            - 챕터별 배경 이미지 (자동 생성)
  portraits/              - 캐릭터 초상화 (자동 생성)
  custom/                 - 커스텀 이미지 (이 폴더 우선 적용)

templates/index.html      - 웹 UI (표시 전용)
saves/                    - 세이브 데이터
```

---

## 시나리오 / 룰셋 추가 방법

### 새 시나리오 추가
1. `scenarios/` 에 `{scenario_id}.json` 파일 생성
2. `scenarios/index.json` 에 메타데이터 등록
3. `entities/{scenario_id}/` 디렉토리 생성 후 npcs/players/objects/ 파일 작성
4. 게임 시작 시 `game_state.json` 에 `scenario_id` 지정

### 새 룰셋 추가
1. `rulesets/` 에 `{ruleset_id}.json` 파일 생성 (`fantasy_basic.json` 참고)
2. `rulesets/index.json` 에 등록
3. `scenario.json` 의 `ruleset` 필드에서 참조

### 시나리오 구성 요소
```json
{
  "id": "scenario_id",
  "title": "시나리오 제목",
  "ruleset": "fantasy_basic",
  "chapters": [...],
  "chapter_themes": {
    "1": {"name": "숲", "bg_type": "forest"},
    "2": {"name": "던전", "bg_type": "dungeon"},
    "3": {"name": "보물실", "bg_type": "treasure"}
  },
  "default_party": {...},
  "endings": [...]
}
```
- `chapter_themes.bg_type` 값으로 배경 이미지 자동 생성 (map_generator.py 참고)

---

## API 엔드포인트
| 경로 | 메서드 | 기능 |
|------|--------|------|
| `/` | GET | 웹 UI (표시 전용) |
| `/api/game-state` | GET | 전체 게임 상태 |
| `/api/entities` | GET | 엔티티 상세 (players/npcs/objects) |
| `/api/scene` | GET | 현재 챕터/배경 이미지 URL |
| `/api/gm-update` | POST | GM 상태 업데이트 |
| `/api/reset-game` | POST | 게임 초기화 |
| `/api/load` | POST | 저장된 게임 불러오기 |
| `/api/saves` | GET | 저장 목록 |
| `/api/progress/<id>` | GET | 시나리오 진행 상황 |

### gm-update 파라미터
```json
{
  "description": "GM 설명",
  "narrative": "나레이션 (금색 표시)",
  "player_updates": [{"id": 1, "hp": 10, "mp": 5, "position": [3,9], "inventory": [...]}],
  "npc_updates": [{"id": 101, "hp": 0, "status": "dead"}],
  "new_npcs": [...],
  "game_status": "in_progress",
  "scene_update": {"chapter": 3, "narrative_title": "보물실 진입"}
}
```

---

## 이미지 생성 (map_generator.py)
- `save_map()` — 맵 이미지 + 배경/초상화 자동 갱신
- `generate_background(chapter_num)` — 시나리오 chapter_themes의 bg_type 기반 생성
- `generate_portrait(player_class, player_id)` — 클래스별 픽셀아트 초상화
- 지원 bg_type: `forest`, `dungeon`, `treasure` (추가 가능)

## ASCII 맵 도구 (ascii_map.py)
```bash
python ascii_map.py    # 맵 + 파티 상태 + 이벤트 로그 출력
```
- 이모지 맵: 지형/플레이어/NPC/오브젝트 표시
- 함수: `show_emoji_map()`, `show_party()`, `show_dice_roll()`, `show_damage()`, `show_event_log()`

---

## Agent 분담 구조

```
유저 (터미널 채팅으로 액션 선언)
  ↓
메인 Claude = GM (나레이션/진행/유저 상호작용)
  ├── Agent [룰 심판]   → rulesets/{id}.json 판정, 주사위($RANDOM), 이니셔티브
  ├── Agent [시나리오]  → scenarios/{id}.json 챕터/이벤트/엔딩 분기
  ├── Agent [NPC]       → entities/{scenario_id}/npcs/npc_{id}.json
  ├── Agent [플레이어]  → entities/{scenario_id}/players/player_{id}.json
  └── Agent [오브젝트]  → entities/{scenario_id}/objects/obj_{id}.json
  ↓
결과 종합 → 나레이션 + 맵 출력 + game_state.json 업데이트 + 저장(git push)
```

### Agent 연속성 (파일 기반 메모리)
Agent 툴은 일회성이므로 연속성은 JSON 파일로 유지:
- 호출 시: JSON 읽어 컨텍스트 복원 → 판단/행동 → JSON 저장 → 결과 리턴
- 시나리오별 격리: `entities/{scenario_id}/` 하위 관리

---

## 세션 시작 시 필수 확인 (로드 절차)
> **세션이 바뀔 때마다 반드시 아래 파일을 순서대로 읽고 컨텍스트를 복원한다.**

1. `CLAUDE.md` — 프로젝트 구조·규칙 확인
2. `current_session.json` — 현재 활성 시나리오/세이브/진행 요약 (빠른 컨텍스트 복원)
3. `game_state.json` — 턴/챕터/파티 HP·MP·위치·인벤토리·이벤트 로그
4. `entities/{scenario_id}/players/` — 각 플레이어 상세 (히스토리, 장비, 컨디션)
5. `entities/{scenario_id}/npcs/` — 생존/사망 NPC 상태
6. `entities/{scenario_id}/objects/` — 퍼즐/함정/오브젝트 해결 여부
7. `scenario.json` + `rules.json` — 현재 시나리오 챕터 구조 및 룰셋 확인

위 파일을 **모두 확인한 후** 유저에게 현재 상황 요약을 제시하고 게임을 이어간다.

### current_session.json 갱신 규칙
- **저장 트리거 발생 시** (전투 종료, 아이템 변동, 챕터 전환 등) `current_session.json`도 함께 갱신
- 시나리오를 전환하면 `active_scenario`와 관련 필드를 모두 교체
- 이 파일은 CLAUDE.md와 달리 **게임별 상태**만 담는다 (프로젝트 구조 정보 X)

---

## 게임 시작 플로우 (신규 게임)
1. `scenarios/index.json` 에서 시나리오 선택
2. 연결된 룰셋 (`rulesets/`) 확인
3. 캐릭터 메이킹 (`templates/character_classes.json` 참고)
   - 유저가 선택: 파티 인원, 클래스, 이름, 능력치 배분
   - 미선택 항목: 시나리오 기본값 자동 적용
4. `entities/{scenario_id}/` 엔티티 파일 생성
5. `game_state.json` 초기화
6. 챕터 1 오프닝 + 맵 표시

---

## 실행 방법
```bash
pip install -r requirements.txt
python app.py          # 웹 UI: http://localhost:5000
python ascii_map.py    # 터미널 맵 확인
```

