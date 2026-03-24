#!/usr/bin/env python
"""docs/ 동기화: HTML 복사 + 데이터 동기화."""
import json
import os
import shutil
import sys
sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.save_manager import SaveManager

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

if __name__ == "__main__":
    # 1. HTML 단순 복사
    src = os.path.join(BASE_DIR, "templates", "index.html")
    dst = os.path.join(BASE_DIR, "docs", "index.html")
    shutil.copy2(src, dst)
    print(f"HTML copied: templates/index.html -> docs/index.html")

    # 2. 데이터 동기화
    with open(os.path.join(BASE_DIR, "data", "game_state.json"),
              "r", encoding="utf-8") as f:
        state = json.load(f)
    SaveManager()._sync_docs(state)
    print("docs/ data synced")
