# -*- coding: utf-8 -*-
"""유사 검색 / 중복 제거 성능 평가 공용 부트스트랩.

코어 매칭 로직(SIM_260926_dedup.py)과 유사 검색 래퍼(app/backend/find_similar.py)를
결정적으로 평가하기 위한 import 부트스트랩 + 임계값 오버라이드 + 공용 헬퍼.
코어 코드는 수정하지 않고 함수/상수만 호출·패치한다.

설계 문서: documents/Site Code 채번 고도화_260929_Similarity_Golden Dataset 설계.md
"""

import contextlib
import os
import sys

# ---------------------------------------------------------------------------
# import 부트스트랩: scripts/ 와 app/backend/ 를 모두 sys.path 에 넣는다.
#   - find_similar.py 는 `import deps` 후 `import SIM_260926_dedup` 를 수행하므로
#     backend 디렉터리(deps 위치)와 scripts 디렉터리가 둘 다 필요하다.
# ---------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS_DIR = os.path.join(ROOT, "scripts")
BACKEND_DIR = os.path.join(ROOT, "app", "backend")
DATA_DIR = os.path.join(ROOT, "data")
REPORTS_DIR = os.path.join(ROOT, "docs", "reports")

for _p in (SCRIPTS_DIR, BACKEND_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import deps  # noqa: E402,F401  (scripts/ 를 path 에 추가 + .env 로드)
import SIM_260926_dedup as dd  # noqa: E402
import STD_VLD_260917_std_company as stdc  # noqa: E402
import STD_VLD_260917_geo_common as gc  # noqa: E402
from find_similar import find_similar, score_pair  # noqa: E402

# gate verdict 상수 재노출
EQUAL, SIMILAR, DIFFERENT, SKIP = dd.EQUAL, dd.SIMILAR, dd.DIFFERENT, dd.SKIP


@contextlib.contextmanager
def override_thresholds(*, name_threshold=None, addr_jaccard=None, coord_m=None,
                        code_max_edits=None, addr_upper_max_edits=None):
    """실행 동안만 코어 임계값을 임시 오버라이드하고 finally 에서 원복한다.

    dedup_service._override 와 동일 패턴이며 ADDR_UPPER_MAX_EDITS 까지 확장했다.

    Args:
        name_threshold (float, optional): 업체명 SIM 임계치.
        addr_jaccard (float, optional): 하위 주소 토큰 Jaccard 임계.
        coord_m (float, optional): 좌표 동일 판정 거리(m).
        code_max_edits (int, optional): 코드/Duns 유사 최대 편집거리.
        addr_upper_max_edits (int, optional): 상위 주소 오타 허용 최대 편집거리.

    Yields:
        None: 오버라이드가 적용된 컨텍스트.
    """
    mapping = {
        "name_threshold": (stdc, "SIM_THRESHOLD", name_threshold),
        "addr_jaccard": (dd, "ADDR_LOWER_JACCARD", addr_jaccard),
        "coord_m": (dd, "COORD_EQUAL_M", coord_m),
        "code_max_edits": (dd, "CODE_SIMILAR_MAX_EDITS", code_max_edits),
        "addr_upper_max_edits": (dd, "ADDR_UPPER_MAX_EDITS", addr_upper_max_edits),
    }
    saved = {}
    try:
        for _key, (mod, attr, val) in mapping.items():
            if val is not None:
                saved[(mod, attr)] = getattr(mod, attr)
                setattr(mod, attr, val)
        yield
    finally:
        for (mod, attr), val in saved.items():
            setattr(mod, attr, val)


def to_gate_row(record: dict) -> dict:
    """한국어 키 dict 1건 → dedup 내부 게이트 입력 dict.

    find_similar._prep 와 동일하게 std_name 이 비면 label(업체/업체명)로 폴백한다.

    Args:
        record (dict): 한국어 키 레코드 1건.

    Returns:
        dict: dedup 게이트 입력 행(std_name 폴백 적용).
    """
    g = dd._to_rows([record])[0]
    if not g.get("std_name"):
        g["std_name"] = g.get("label") or ""
    return g


def gate_verdicts(rec_a: dict, rec_b: dict) -> dict:
    """두 한국어 키 dict 에 대한 게이트별 판정 {code,duns,addr,coord,name}.

    per-gate 진단용. name 은 (verdict, score) 중 verdict 만 취한다.

    Args:
        rec_a (dict): 한국어 키 레코드 A.
        rec_b (dict): 한국어 키 레코드 B.

    Returns:
        dict: {code, duns, addr, coord, name} 게이트별 판정.
    """
    ga, gb = to_gate_row(rec_a), to_gate_row(rec_b)
    name_verdict, _ = dd.name_gate(ga, gb)
    return {
        "code": dd.code_gate(ga, gb),
        "duns": dd.duns_gate(ga, gb),
        "addr": dd.address_gate(ga, gb),
        "coord": dd.coord_gate(ga, gb),
        "name": name_verdict,
    }
