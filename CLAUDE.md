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
- ❌ 나레이션과 시스템 로그가 섞이는 것 (Phase 분리 필수)
- ❌ 배경 위 인물 레이어에 불투명 배경 사용
- ❌ 동일 인물의 외형이 장면마다 바뀌는 것

### 필수 자동화 (코드로 동작)
- ✅ Flask 시작/로드 시 `restore_scene()` → 배경 자동 복원
- ✅ SD 실패 시 Cairo 폴백 (빈 화면 없음)
- ✅ 이미지 재활용 (이름 매칭 → 기존 고퀄 우선)
- ✅ 초상화 배경 자동 제거 (transparent-background)
- ✅ 이미지 생성 폴백: SD WebUI 우선 → Cairo 폴백 (빈 화면 없음)
- ✅ 저장 시 docs/ 자동 동기화 (GitHub Pages) — build_static.py가 HTML 복사 + 데이터(JSON, 이미지) 동기화
- ✅ NPC 엔티티 자동 생성 (check_npcs)
- ✅ 맵 장소별 자동 전환 (current_location → worldbuilding.json)

---

## GM 턴 처리 순서 (엄격 준수)

> 메인 GM은 3단계만 기억한다. 세부 처리는 하위 에이전트가 담당.

```
유저 액션 선언
  ↓
[1단계 — 에이전트에게 물어본다]
  관련 에이전트를 병렬 호출하여 결과를 받는다:
  - Agent [NPC:{name}] → 해당 NPC 대사/행동 생성
  - Agent [룰 심판]   → 판정 필요 여부 + 주사위 결과
  - Agent [세계관]    → 지명/설정 정합성 확인
  - Agent [시나리오]  → 챕터/퀘스트 상태 확인
  - Agent [세계 지도] → 위치/지리 확인 (위치 변경 시)
  ↓
[2단계 — 나레이션 작성]
  에이전트 결과를 종합하여 나레이션을 작성한다.
  - show_dice_result가 false면 판정 수치 노출 금지
  - 유저 캐릭터(controlled_by: "user")의 대사/감정/판단을 GM이 만들지 않는다
  ↓
[3단계 — 시스템 반영 (Agent [시스템]에게 넘긴다)]
  Agent [시스템 반영]이 다음을 자동 처리:
  - game_state.json + entities/ 업데이트
  - gm-update API 호출 (나레이션 + 웹 UI 반영)
  - 위치 변경 시 current_location 갱신 + 배경 일러스트 교체
  - 시간대 변경 시 배경에 시간대 반영
  - 나레이션에 등장한 NPC 등록 확인
  - 사후 자동 검증 (안전망): 세계관/룰/시나리오/NPC/세계지도
  - gm_turn.py 로그 기록
  - git commit (매 턴), push (3턴마다/명시 시)
  ↓
[나레이션 출력]
  터미널에 나레이션 텍스트 출력
  맵 표시 + 유저 다음 행동 대기
```

> 상세: guides/gm_rules.txt 참조

---

## Agent 분담 구조

```
유저 (터미널 채팅으로 액션 선언)
  ↓
메인 Claude = GM (나레이션/진행/유저 상호작용)
  ├── Agent [룰 심판]   → rulesets/{id}.json 판정, 주사위, 이니셔티브
  ├── Agent [시나리오]  → scenarios/{id}.json 챕터/이벤트/엔딩 분기
  ├── Agent [세계관]    → worldbuilding.json 지명/화폐/세력/NPC 관리
  ├── Agent [NPC:{name}] → entities/{id}/npcs/npc_{id}.json (NPC 1명당 1개)
  ├── Agent [플레이어]  → entities/{id}/players/player_{id}.json
  ├── Agent [오브젝트]  → entities/{id}/objects/obj_{id}.json
  ├── Agent [세계 지도] → worldbuildings/{id}.json 지리 검증 + 지도 갱신
  └── Agent [시스템 반영] → game_state 업데이트 + gm-update + 일러스트 + NPC 등록 + 로그 + git
  ↓
결과 종합 → 나레이션 + 맵 출력 + game_state.json 업데이트 + 저장(git push)
```

> 상세: guides/entities.txt 참조

---

## 기술 스택
- **백엔드**: Flask 2.3.0 (Python)
- **이미지**: SD WebUI API (포트 7860) + Cairo/Pillow 폴백
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
  map_generator.py        - Cairo/PIL 이미지 생성, SD OFF 시 폴백
  ascii_map.py            - CLI 터미널용 이모지 ASCII 맵 출력
  gm_turn.py              - GM 턴 추적기 (실행 작업 기록 + 누락 경고)
  save_manager.py         - 세이브/로드 매니저
  game_mechanics.py       - 주사위, 판정, 전투, 회복, 아이템, 상태이상 처리
data/                     - JSON 데이터 파일
  game_state.json         - 현재 게임 상태
  current_session.json    - 현재 활성 세션 요약 (세션 복원용)
  worldbuilding.json      - 세계관 설정 (시나리오 독립)
  rules.json              - 현재 활성 룰셋
  scenario.json           - 현재 활성 시나리오
  items.json              - 아이템 데이터베이스 (효과, 설명, 수치, 희귀도)
  skills.json             - 스킬 데이터베이스 (효과, 비용, 사거리, 요구 레벨)
  status_effects.json     - 상태이상 데이터베이스 (버프/디버프, 지속시간, 치료법)
  creature_templates.json - 생물체 템플릿 (몬스터, 동물, 소환수)
  shops.json              - 상점 데이터베이스 (위치, 품목, 가격, 매입률)
  quests.json             - 퀘스트 데이터베이스 (활성/완료/실패 상태 추적)
  pending_actions.json    - 보류 중인 액션
  game_state_initial.json - 초기 게임 상태 템플릿
entities/{scenario_id}/   - npcs/ players/ objects/ 엔티티 파일
rulesets/ / scenarios/    - 룰셋/시나리오 카탈로그
worldbuildings/           - 세계관 파일 카탈로그 (시나리오에서 참조)
static/                   - 맵, 초상화, 일러스트 이미지
  map.png                 - 전체 맵 (클릭 확대용, ~1000x1000px)
  map_mini.png            - 미니맵 (플레이어 중심 크롭, 사이드바용)
templates/                - 웹 UI (동적/정적 자동 감지) + 캐릭터 클래스 템플릿
docs/index.html           - templates/index.html 복사본 (build_static.py가 자동 복사)
saves/                    - 세이브 데이터
guides/                   - 상세 규칙 참조 파일
```

---

## 웹 관리 규칙

templates/index.html과 docs/index.html은 동일 파일이다.
런타임에 isStatic 변수로 환경을 자동 감지하여 API/경로를 전환한다.
build_static.py는 HTML 복사 + 데이터 동기화를 수행한다.
웹 기능 수정 시 templates/index.html만 편집하면 docs/에 자동 반영된다.

- **templates/index.html**: 단일 소스 (동적/정적 자동 감지)
- **docs/index.html**: templates/index.html의 복사본 (build_static.py 또는 _sync_docs가 자동 복사)
- **build_static.py**: HTML 복사 + 데이터(JSON, 이미지, 엔티티) docs/에 동기화

---

## 세션 시작 체크리스트
1. CLAUDE.md 읽기 (이 파일)
2. `python session_validator.py` 실행 — 상태 검증 + 자동 수정
3. `data/current_session.json` → `data/worldbuilding.json` → `data/game_state.json` 읽기
4. Flask 서버 확인 → 웹 UI 장면 복원 (자동: `restore_scene`)
5. 유저에게 현재 상황 요약 → 게임 이어가기

> 상세 로드 절차: 아래 "세션 로드 상세" 참조

### 세션 로드 상세
1. `CLAUDE.md` → 2. `python session_validator.py` (상태 검증 + 엔티티 누락 자동 생성)
3. `data/current_session.json` → 4. `data/worldbuilding.json` (활성 세계관 — worldbuildings/에서 복사됨) → 5. `data/game_state.json`
6. `entities/{scenario_id}/` (players, npcs, objects)
7. `data/scenario.json` + `data/rules.json`
8. Flask 서버 확인 → gm-update로 현재 장면 복원 (배경+NPC 레이어)
9. 유저에게 현재 상황 요약 제시

> 세션 로드 시 웹 UI가 빈 화면이거나 이전 장면을 보여주는 것은 금지.

### 새 게임 시작
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
python ascii_map.py    # 터미널 맵 확인
# 또는 편의 스크립트: start_server.bat (Windows) / start_server.sh (Git Bash)
```

> **참고**: Flask 서버는 SD WebUI의 venv Python으로 실행해야 torch GPU, transparent-background, PIL 등
> 라이브러리를 통일할 수 있다. 시스템 Python에 별도 설치할 필요 없음.

---

## 상세 참조 파일

| 파일 | 내용 |
|------|------|
| `guides/gm_rules.txt` | GM 나레이션 원칙, 웹 반영, 주사위 판정, 맵 표시, 좌표 시스템, 저장 규칙, 턴 추적기 |
| `guides/illustration.txt` | SD 연동, 레이어 시스템, 파라미터, 사전 생성 이미지, 외형 일관성, 품질 관리 |
| `guides/sd_environment.txt` | SD WebUI 경로, 실행 명령, 모델/VAE/확장 목록, 호환성 수정 |
| `guides/entities.txt` | NPC 엔티티 규칙, JSON 구조, 자동 생성, Agent 연속성, 세계관/웹 반영 Agent 상세 |
| `guides/api.txt` | 전체 API 엔드포인트 목록, gm-update 파라미터 |
| `guides/scenario.txt` | 시나리오/룰셋 추가 방법, 구성 요소, 게임 시작 플로우 |
| `guides/process.txt` | 프로세스 관리, 실행/종료, 중복 방지, 상태 확인 |
