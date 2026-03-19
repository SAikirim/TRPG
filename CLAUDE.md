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

## CLI 세션 TRPG 모드 (TODO)
웹 UI 없이 Claude Code CLI 세션에서 직접 TRPG를 진행하는 방식.

### 개요
- Claude가 GM 역할을 하며 채팅으로 TRPG 진행
- 유저가 액션 선언 → Claude가 판정/나레이션 → game_state.json 업데이트
- Flask 서버 불필요

### 맵 표시 방식
- **ASCII 맵**: 이모지/텍스트 기반 (모바일 호환)
- PIL 이미지: 데스크탑 CLI에서는 Read 도구로 이미지 확인 가능, 모바일은 불가
- 캐릭터 일러스트 생성은 불가 (도형 기반 맵만 가능)

### ASCII 맵 범례
```
🔴 전사 아론    🟢 마법사 리나    🔵 도적 카이
🔺 몬스터       🌲 숲(grass)     ⬜ 던전(dungeon)    🟡 보물실(treasure)
```

### 진행 방식
1. 유저가 채팅으로 액션 선언 (예: "아론이 오크를 공격")
2. Claude(GM)가 rules.json 기반으로 주사위 판정 (Bash에서 $RANDOM 사용)
3. game_state.json 업데이트 (HP, 위치, 턴 등)
4. ASCII 맵 + 나레이션 텍스트로 결과 표시
5. 턴 종료 시 자동 저장

### 필요 파일
- `game_state.json` - 상태 추적
- `rules.json` - 전투/판정 규칙
- `scenario.json` - 시나리오 진행

### 구현 TODO
- [ ] CLI TRPG 진행용 Python 스크립트 (ascii_map.py) - ASCII 맵 생성기
- [ ] GM 판정 로직 헬퍼 (dice_roller.py) - 주사위/판정 유틸
- [ ] 세션 간 이어하기 지원 (game_state.json 기반)

## 게임 플로우
웹 UI에서 액션 버튼 클릭 → Flask API로 전송 → game_state.json 업데이트 → 맵 이미지 재생성 → UI 자동 갱신(2초)

GM(Claude)이 `/api/gm-update`로 나레이션, NPC 반응, HP/MP 변경 등을 처리.

## GM 업데이트 예시
```bash
curl -X POST http://localhost:5000/api/gm-update \
  -H "Content-Type: application/json" \
  -d '{"description": "전사가 오크를 공격!", "npc_updates": [{"id": 100, "hp": 20}], "narrative": "오크가 으르렁거린다!"}'
```
