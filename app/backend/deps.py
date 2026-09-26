# -*- coding: utf-8 -*-
"""공통 부트스트랩: scripts/를 sys.path에 넣고 .env를 로드한다.

모든 service/router는 최상단에서 `import deps`를 먼저 수행해
기존 코어 모듈(STD_VLD_*, SIM_*)을 bare name으로 import할 수 있게 한다.
코어 로직은 수정하지 않는다(계획 원칙).
"""

import os
import sys

# app/backend/deps.py → ROOT = 상위 2단계
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(BACKEND_DIR))
SCRIPTS_DIR = os.path.join(ROOT, "scripts")
DATA_DIR = os.path.join(ROOT, "data")
TABLES_DIR = os.path.join(DATA_DIR, "tables")

if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

# .env 로드(있으면). GOOGLE_MAPS_API_KEY / MAPS_ADAPTER_MODE / CORS_ORIGIN
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(ROOT, ".env"))
except ImportError:  # dotenv 미설치 환경에서도 죽지 않게
    pass
