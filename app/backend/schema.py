# -*- coding: utf-8 -*-
"""컬럼 스키마 단일 진실원천 재수출.

기존 run_verification의 컬럼 상수를 그대로 재수출해 백엔드/프론트가
동일한 한국어 컬럼 키를 사용하도록 한다.
"""

import deps  # noqa: F401  (sys.path 부트스트랩)

from STD_VLD_260917_run_verification import (  # noqa: E402
    BASE_COLUMNS,
    EXTRA_COLUMNS,
    OUT_COLUMNS,
)

__all__ = ["BASE_COLUMNS", "EXTRA_COLUMNS", "OUT_COLUMNS"]
