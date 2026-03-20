# 판타지 TRPG - 잃어버린 보물의 숲 던전

## 프로젝트 개요
Claude Code CLI 터미널에서 Claude가 GM 역할을 하며 진행하는 TRPG.
웹 UI는 **표시 전용** (Flask + PIL). 실제 게임 진행은 터미널에서만.

## 게임 진행 방식 (핵심)

### 역할 분담
- **터미널(Claude GM)**: 액션 선언 수신 → 판정 → 나레이션 → 상태 업데이트
- **웹 UI**: 표시 전용 — 맵 이미지, 스탯, 인벤토리, 배경, 초상화 실시간 표시. 행동 버튼 없음.

### 이미지 전략 (토큰 절약)
- **웹/이미지 사용 가능 환경** → PIL 이미지(`static/map.png`) 자동 갱신 — Claude가 위치를 텍스트로 설명할 필요 없음 → 토큰 절약
- **터미널(이미지 불가 환경)** → `python ascii_map.py`로 이모지 ASCII 맵 출력

### 저장 규칙
- **저장 = git commit + push 한 세트** (반드시 push까지)
- 커밋 메시지 형식: `save: 턴N 내용 — 결과 요약`
- 브랜치: `claude/clarify-task-xApb3`

#### 저장 트리거 (아래 상황에서 반드시 즉시 저장)
| 상황 | 저장 대상 파일 |
|------|--------------|
| 전투 종료 | game_state.json, entities/npcs/ |
| 아이템 획득/분배/사용 | game_state.json, entities/players/ |
| 함정/오브젝트 상호작용 | game_state.json, entities/objects/ |
| 챕터 전환 | game_state.json 전체 |
| 캐릭터 HP/MP 변동 | game_state.json, entities/players/ |
| 퍼즐/이벤트 해결 | game_state.json, entities/objects/ |

#### 이벤트 로그 기록 원칙
- **모든 의미 있는 행동을 개별 이벤트로 기록** (여러 행동을 한 줄로 압축 금지)
- 나쁜 예: `"챕터 1 완료. 숲을 지나 던전 진입."` (탐색/아이템/함정 내용 누락)
- 좋은 예:
  - `"사이키가 숲에서 약초를 발견했다."`
  - `"루체나가 덩굴 함정을 해제했다. 밧줄 획득."`
  - `"챕터 1 완료. 던전 진입."`
- 아이템 획득 즉시 → entities/players/ 업데이트 + 이벤트 기록 + 저장
- 오브젝트 상태 변경 즉시 → entities/objects/ 업데이트 + 이벤트 기록 + 저장

## 기술 스택
- **백엔드**: Flask 2.3.0 (Python)
- **맵/이미지**: Pillow (PIL) — 맵(800x600), 배경(800x450), 초상화(120x160)
- **데이터**: JSON 파일 기반 (game_state.json + entities/)
- **프론트엔드**: 순수 HTML/CSS/JS (2초 폴링, 표시 전용)

## 파일 구조
```
app.py                  - Flask 웹 서버 (포트 5000)
map_generator.py        - PIL 이미지 생성 (맵 + 챕터 배경 + 캐릭터 초상화)
ascii_map.py            - CLI 터미널용 이모지 ASCII 맵 출력 도구
game_state.json         - 전체 게임 상태 (플레이어, NPC, 맵, 턴, 이벤트)
scenario.json           - 시나리오 (3챕터, 이벤트/트리거/엔딩 분기)
rules.json              - 룰셋 (전투/주사위/액션/상태이상/사망)
save_manager.py         - 세이브/로드 매니저
rulesets/               - 룰셋 카탈로그 (fantasy_basic.json)
scenarios/              - 시나리오 카탈로그 (index.json)
templates/              - 캐릭터 클래스 템플릿
  character_classes.json
entities/               - 엔티티 파일 (Agent 연속성, 시나리오별 관리)
  {scenario_id}/
    npcs/               - NPC 개별 상태 (성격, 전투AI, 기억)
    players/            - 플레이어 개별 상태 (능력치, 인벤토리, 히스토리)
    objects/            - 오브젝트 상태 (함정, 퍼즐, 보물상자)
static/
  map.png               - 생성된 맵 이미지
  backgrounds/          - 챕터별 배경 이미지 (chapter_N.png)
  portraits/            - 캐릭터 초상화 (player_N.png)
  custom/               - 커스텀 이미지 교체용 (이 폴더 이미지가 우선 적용)
templates/index.html    - 웹 UI (표시 전용)
saves/                  - 저장 데이터
```

## API 엔드포인트
| 경로 | 메서드 | 기능 |
|------|--------|------|
| `/` | GET | 웹 UI (표시 전용) |
| `/api/game-state` | GET | 전체 게임 상태 |
| `/api/entities` | GET | 엔티티 상세 (players/npcs/objects JSON) |
| `/api/scene` | GET | 현재 챕터/배경 이미지 URL |
| `/api/gm-update` | POST | GM이 게임 상태 업데이트 |
| `/api/player-action` | POST | 플레이어 액션 (하위 호환용) |
| `/api/reset-game` | POST | 게임 초기화 |
| `/api/load` | POST | 저장된 게임 불러오기 |
| `/api/saves` | GET | 저장 목록 |
| `/api/progress/<id>` | GET | 시나리오 진행 상황 |

### gm-update 파라미터
```json
{
  "description": "GM 설명 텍스트",
  "narrative": "나레이션 텍스트 (금색 표시)",
  "player_updates": [{"id": 1, "hp": 10, "mp": 5, "position": [3,9], "inventory": [...]}],
  "npc_updates": [{"id": 101, "hp": 0, "status": "dead"}],
  "new_npcs": [...],
  "game_status": "in_progress",
  "scene_update": {"chapter": 3, "narrative_title": "보물실 진입"}
}
```

## 이미지 생성 (map_generator.py)
- `save_map()` — 맵 이미지 생성 + 배경/초상화 자동 갱신
- `generate_background(chapter_num)` — 챕터별 배경 (1=숲, 2=던전, 3=보물실)
- `generate_portrait(player_class, player_id)` — 클래스별 픽셀아트 초상화
- `static/custom/` 폴더에 파일 있으면 PIL 생성본 대신 사용 (커스텀 우선)
- 향후 Stable Diffusion 로컬 API 연동 예정 (현재 미구현)

## ASCII 맵 도구 (ascii_map.py)
터미널에서 이미지 사용 불가 시 사용:
```bash
python ascii_map.py
```
- 이모지 기반 맵 (🌲숲 🪨던전 🟡보물실 🔵마법사 🟢도적 🔴전사 💀처치됨)
- HP/MP 바, 소지품, 이벤트 로그 포함
- `show_emoji_map(state)`, `show_party(state)`, `show_dice_roll(...)`, `show_damage(...)` 함수 제공

## Agent 분담 구조

메인 Claude가 GM 역할, 각 역할별로 Agent 툴 분담 호출:

```
유저 (터미널 채팅으로 액션 선언)
  ↓
메인 Claude = GM (나레이션/진행/유저 상호작용)
  ├── Agent [룰 심판]   → rules.json 판정, 주사위($RANDOM), 이니셔티브
  ├── Agent [시나리오]  → scenario.json 챕터/이벤트/엔딩 분기
  ├── Agent [NPC]       → entities/npcs/npc_{id}.json 읽기/쓰기
  ├── Agent [플레이어]  → entities/players/player_{id}.json 읽기/쓰기
  └── Agent [오브젝트]  → entities/objects/obj_{id}.json 읽기/쓰기
  ↓
결과 종합 → 나레이션 + 맵 출력 + game_state.json 업데이트 + 저장(git push)
```

### Agent 연속성 (파일 기반 메모리)
Agent 툴은 일회성이므로 연속성은 JSON 파일로 유지:
- 호출 시: JSON 읽어 컨텍스트 복원 → 판단/행동 → JSON 저장 → 결과 리턴
- 시나리오별 분리: `entities/{scenario_id}/` 하위 관리

## 현재 게임 상태 (2026-03-20, 턴 4)
- **시나리오**: 잃어버린 보물의 숲 던전 (`lost_treasure`)
- **챕터**: 2 (고대 던전)
- **파티**: 사이키(마법사, HP15/15, MP26/30) · 루체나(도적, HP22/22) · 노을(전사, HP32/32)
- **처치**: 어두운 오크(턴3) · 마법사 슬라임(턴4) — 던전 2구역 전멸
- **다음**: 보물실([14,10]) 진입 — 보물 수호자 골렘 대기 중

## 게임 시작 플로우 (신규 게임)
1. `scenarios/index.json` 에서 시나리오 선택
2. `rulesets/` 에서 룰셋 확인
3. 캐릭터 메이킹 (`templates/character_classes.json` 참고)
4. `entities/{scenario_id}/` 엔티티 파일 생성
5. `game_state.json` 초기화
6. 챕터 1 오프닝 + ASCII 맵 표시

## 실행 방법
```bash
pip install -r requirements.txt
python app.py          # 웹 UI: http://localhost:5000
python ascii_map.py    # 터미널 맵 확인
```

## GM 업데이트 예시
```bash
curl -X POST http://localhost:5000/api/gm-update \
  -H "Content-Type: application/json" \
  -d '{"description": "슬라임 처치!", "npc_updates": [{"id": 101, "hp": 0, "status": "dead"}], "narrative": "슬라임이 녹아내렸다."}'
```
