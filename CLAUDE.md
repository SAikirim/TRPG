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
- ✅ 저장 시 docs/ 자동 동기화 (GitHub Pages)
- ✅ NPC 엔티티 자동 생성 (check_npcs)
- ✅ 맵 장소별 자동 전환 (current_location → worldbuilding.json)

---

## GM 턴 처리 순서 (엄격 준수)

> 유저에게 보이는 나레이션은 반드시 모든 시스템 작업이 끝난 후 마지막에 출력한다.

```
유저 액션 선언
  ↓
[Phase 1 — 시스템 처리] (나레이션 출력 금지)
  1. NPC Agent 병렬 호출 (대사/행동 생성)
  2. 룰 판정 (주사위, DC 체크)
  3. game_state.json + entities/ 업데이트
  4. gm-update API 호출 (웹 UI 반영 + 일러스트)
  5. docs/ 동기화 + git commit + push
  ↓
[Phase 2 — 나레이션 출력] (시스템 작업 완료 후)
  6. 터미널에 나레이션 텍스트 출력
  7. 맵 표시 + 유저 다음 행동 대기
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
  └── Agent [웹 반영]   → gm-update API 호출 + 일러스트 생성
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
session_validator.py      - 세션 검증 자동화 (상태 일관성 검사 + 자동 수정)
sd_generator.py           - SD WebUI API 래퍼, 레이어 시스템
map_generator.py          - Cairo/PIL 이미지 생성, SD OFF 시 폴백
ascii_map.py              - CLI 터미널용 이모지 ASCII 맵 출력
gm_turn.py                - GM 턴 추적기 (실행 작업 기록 + 누락 경고)
save_manager.py           - 세이브/로드 매니저
game_state.json           - 현재 게임 상태
current_session.json      - 현재 활성 세션 요약 (세션 복원용)
worldbuilding.json        - 세계관 설정 (시나리오 독립)
rules.json / scenario.json - 현재 활성 룰셋 / 시나리오
entities/{scenario_id}/   - npcs/ players/ objects/ 엔티티 파일
rulesets/ / scenarios/    - 룰셋/시나리오 카탈로그
static/                   - 맵, 초상화, 일러스트 이미지
  map.png                 - 전체 맵 (클릭 확대용, ~1000x1000px)
  map_mini.png            - 미니맵 (플레이어 중심 크롭, 사이드바용)
templates/                - 웹 UI + 캐릭터 클래스 템플릿
saves/                    - 세이브 데이터
guides/                   - 상세 규칙 참조 파일
```

---

## 세션 시작 체크리스트
1. CLAUDE.md 읽기 (이 파일)
2. `python session_validator.py` 실행 — 상태 검증 + 자동 수정
3. `current_session.json` → `worldbuilding.json` → `game_state.json` 읽기
4. Flask 서버 확인 → 웹 UI 장면 복원 (자동: `restore_scene`)
5. 유저에게 현재 상황 요약 → 게임 이어가기

> 상세 로드 절차: 아래 "세션 로드 상세" 참조

### 세션 로드 상세
1. `CLAUDE.md` → 2. `python session_validator.py` (상태 검증 + 엔티티 누락 자동 생성)
3. `current_session.json` → 4. `worldbuilding.json` → 5. `game_state.json`
6. `entities/{scenario_id}/` (players, npcs, objects)
7. `scenario.json` + `rules.json`
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
python app.py          # 웹 UI: http://localhost:5000
python ascii_map.py    # 터미널 맵 확인
```

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
