#!/usr/bin/env python
"""docs/ 데이터 동기화 CLI. save_manager._sync_docs()를 직접 호출.
docs/index.html은 독립적으로 관리되며, 이 스크립트로 생성/변환하지 않는다."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.save_manager import SaveManager

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

if __name__ == "__main__":
    with open(os.path.join(BASE_DIR, "data", "game_state.json"),
              "r", encoding="utf-8") as f:
        state = json.load(f)
    SaveManager()._sync_docs(state)
    print("docs/ 동기화 완료")
