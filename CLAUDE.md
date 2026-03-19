# 판타지 TRPG - 잃어버린 보물의 숲 던전

## 프로젝트 개요
웹 기반 멀티플레이어 TRPG 게임 시스템. Flask + PIL + JSON으로 구축.

## 기술 스택
- **백엔드**: Flask 2.3.0 (Python)
- **맵 생성**: Pillow (PIL) - 800x600px 타일 기반 맵 이미지
- **데이터**: game_state.json (파일 기반 상태 관리)
- **프론트엔드**: 순수 HTML/CSS/JS (2초 간격 폴링)

## 파일 구조
```
app.py              - Flask 웹 서버 (포트 5000, 7개 API 엔드포인트)
map_generator.py    - PIL 맵 이미지 생성기 (20x15 타일, 40px/타일)
game_state.json     - 게임 상태 (플레이어, NPC, 맵, 턴, 이벤트)
scenario.json       - 시나리오 (3챕터 구성, 이벤트/트리거/엔딩 분기)
rules.json          - 룰셋 (전투/주사위/액션/상태이상/사망 규칙)
save_manager.py     - 세이브/로드 매니저 (시나리오별 슬롯 저장)
saves/              - 저장 데이터 디렉토리 (.gitignore 처리됨)
entities/           - 엔티티 상태 파일 (Agent 연속성 유지)
  npcs/             - NPC 개별 상태 (성격, 전투AI, 기억)
  players/          - 플레이어 개별 상태 (능력치, 인벤토리, 히스토리)
  objects/          - 오브젝트 상태 (함정, 퍼즐, 보물상자)
templates/index.html - 게임 UI (맵 표시, 플레이어 정보, 액션 버튼, 이벤트 로그)
static/map.png      - 생성된 맵 이미지 (.gitignore 처리됨)
```

## API 엔드포인트
| 경로 | 메서드 | 기능 |
|------|--------|------|
| `/` | GET | 웹 UI |
| `/api/game-state` | GET | 전체 게임 상태 |
| `/api/player-action` | POST | 플레이어 액션 (턴 증가) |
| `/api/player-stats/<id>` | GET | 특정 플레이어 정보 |
| `/api/events` | GET | 최근 20개 이벤트 |
| `/api/gm-update` | POST | GM이 게임 상태 업데이트 |
| `/api/reset-game` | POST | 게임 초기화 |
| `/api/load` | POST | 저장된 게임 불러오기 (scenario_id, slot) |
| `/api/saves` | GET | 저장 목록 조회 (?scenario_id=) |
| `/api/progress/<id>` | GET | 시나리오별 진행 상황 조회 |

자동 저장: 턴이 변경될 때마다 (player-action, gm-update, reset) 시나리오별 슬롯 1에 자동 저장됨.

## 게임 설정
- **플레이어 3명**: 전사 아론(HP:30), 마법사 리나(HP:15, MP:20), 도적 카이(HP:20, DEX:18)
- **몬스터 2마리**: 어두운 오크(위치 [5,10]), 마법사 슬라임(위치 [10,10])
- **맵 영역**: 숲의 입구(grass) → 고대 던전(dungeon) → 보물실(treasure)
- **목표**: 보물실에 도달하여 보물 획득

## 실행 방법
```bash
pip install -r requirements.txt
python app.py
# http://localhost:5000 접속
```

## 현재 상태 (2026-03-19)
- 초기 구현 완료 - 모든 기본 기능 동작 확인
- 게임 턴: 0 (아직 플레이 시작 전)
- 서버 정상 작동 확인됨

## CLI 세션 TRPG 모드

웹 UI 없이 Claude Code CLI 세션에서 직접 TRPG를 진행하는 방식. Flask 서버 불필요.

### Agent 기반 아키텍처

메인 Claude가 GM(게임 마스터) 역할을 하며, 각 엔티티는 개별 Agent 툴로 처리된다.

```
유저 (액션 선언)
  ↓
메인 Claude = GM (나레이션/시나리오 진행/유저 상호작용)
  │
  ├── Agent [룰 심판]
  │   └── rules.json 기반 판정
  │       - 액션 유효성 검증 (불가능한 행동 차단)
  │       - 주사위 판정 ($RANDOM 기반 1d20, 1d6, 1d8 등)
  │       - 전투 순서 (DEX 기반 이니셔티브)
  │       - 거리/범위 체크
  │       - 상태이상 처리
  │
  ├── Agent [시나리오 진행]
  │   └── scenario.json 기반
  │       - 챕터 전환 조건 체크
  │       - 이벤트 트리거 판정
  │       - 엔딩 분기 조건 확인
  │       - GM이 시나리오를 임의로 건너뛰는 것 방지
  │
  ├── Agent [NPC: 어두운 오크] → entities/npcs/npc_100.json
  │   └── 상황 판단 + 행동 결정 + 상태 저장
  │
  ├── Agent [NPC: 마법사 슬라임] → entities/npcs/npc_101.json
  │   └── 상황 판단 + 행동 결정 + 상태 저장
  │
  ├── Agent [플레이어 상태] → entities/players/player_*.json
  │   └── HP/MP/인벤토리/상태이상 읽기/쓰기/유효성 체크
  │
  └── Agent [오브젝트] → entities/objects/obj_*.json
      └── 트랩/퍼즐/보물상자 상태 관리
  ↓
GM이 모든 Agent 결과를 종합하여 나레이션 출력
```

### Agent 연속성 (파일 기반 메모리)

Agent 툴은 일회성이므로, 각 엔티티의 연속성은 JSON 파일로 유지한다.

- **NPC**: `entities/npcs/npc_{id}.json` — 성격, 행동 패턴, 기억(만난 플레이어, 받은 데미지 등), 현재 목표
- **플레이어**: `entities/players/player_{id}.json` — 능력치, 인벤토리, 전투 상태, 행동 히스토리, 생존 조건
- **오브젝트**: `entities/objects/obj_{id}.json` — 함정/퍼즐/보물 상태, 상호작용 기록

Agent가 호출될 때마다:
1. 해당 엔티티의 JSON 파일을 읽어 컨텍스트 복원
2. 현재 상황에 맞는 판단/행동 수행
3. 결과를 JSON 파일에 저장 (memory 업데이트)
4. GM에게 행동 결과 리턴

### 엔티티 파일 구조
```
entities/
├── npcs/
│   ├── npc_100.json    - 어두운 오크 (성격/전투AI/기억)
│   └── npc_101.json    - 마법사 슬라임 (성격/전투AI/기억)
├── players/
│   ├── player_1.json   - 전사 아론 (능력치/인벤토리/히스토리)
│   ├── player_2.json   - 마법사 리나
│   └── player_3.json   - 도적 카이
└── objects/
    ├── obj_200.json    - 덩굴 함정 (armed/disarmed 상태)
    ├── obj_201.json    - 고대 비문 (퍼즐, 해독 여부)
    ├── obj_202.json    - 전설의 보물 상자 (잠금/수호자/내용물)
    └── obj_203.json    - 안전한 방 (휴식 장소, 사용 횟수)
```

### 턴 진행 플로우
1. 유저가 채팅으로 액션 선언 (예: "아론이 오크를 공격")
2. GM이 **룰 심판 Agent** 호출 → 유효성 검증 + 주사위 판정
3. GM이 **해당 NPC Agent** 호출 → NPC 반응/행동 결정
4. GM이 **플레이어 Agent** 호출 → 플레이어 상태 업데이트
5. GM이 **시나리오 Agent** 호출 → 챕터 진행/이벤트 트리거 체크
6. GM이 결과 종합 → ASCII 맵 + 나레이션 출력
7. game_state.json 동기화 + 자동 저장

### 맵 표시 방식
- **ASCII 맵**: 이모지/텍스트 기반 (모바일 호환)
- PIL 이미지: 데스크탑 CLI에서는 Read 도구로 이미지 확인 가능, 모바일은 불가

### ASCII 맵 범례
```
🔴 전사 아론    🟢 마법사 리나    🔵 도적 카이
🔺 몬스터       🌲 숲(grass)     ⬜ 던전(dungeon)    🟡 보물실(treasure)
```

### 필요 파일
- `game_state.json` - 전체 게임 상태 (턴, 맵, 이벤트 로그)
- `rules.json` - 전투/판정 규칙
- `scenario.json` - 시나리오 진행
- `entities/` - 모든 엔티티 상태 파일 (NPC, 플레이어, 오브젝트)

### 구현 TODO
- [x] 엔티티 파일 구조 설계 및 생성 (NPC, 플레이어, 오브젝트)
- [ ] CLI TRPG 진행용 Python 스크립트 (ascii_map.py) - ASCII 맵 생성기
- [ ] GM 판정 로직 헬퍼 (dice_roller.py) - 주사위/판정 유틸
- [ ] 세션 간 이어하기 지원 (game_state.json + entities/ 기반)

## 게임 플로우
웹 UI에서 액션 버튼 클릭 → Flask API로 전송 → game_state.json 업데이트 → 맵 이미지 재생성 → UI 자동 갱신(2초)

GM(Claude)이 `/api/gm-update`로 나레이션, NPC 반응, HP/MP 변경 등을 처리.

## GM 업데이트 예시
```bash
curl -X POST http://localhost:5000/api/gm-update \
  -H "Content-Type: application/json" \
  -d '{"description": "전사가 오크를 공격!", "npc_updates": [{"id": 100, "hp": 20}], "narrative": "오크가 으르렁거린다!"}'
```
