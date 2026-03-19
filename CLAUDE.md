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

## 게임 플로우
웹 UI에서 액션 버튼 클릭 → Flask API로 전송 → game_state.json 업데이트 → 맵 이미지 재생성 → UI 자동 갱신(2초)

GM(Claude)이 `/api/gm-update`로 나레이션, NPC 반응, HP/MP 변경 등을 처리.

## GM 업데이트 예시
```bash
curl -X POST http://localhost:5000/api/gm-update \
  -H "Content-Type: application/json" \
  -d '{"description": "전사가 오크를 공격!", "npc_updates": [{"id": 100, "hp": 20}], "narrative": "오크가 으르렁거린다!"}'
```
