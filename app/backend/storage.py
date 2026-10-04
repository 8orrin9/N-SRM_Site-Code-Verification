# -*- coding: utf-8 -*-
"""파일 기반 테이블 영속화.

data/tables/<menu>/<slug>.json + data/tables/index.json.
각 테이블 JSON = {name, menu, columns, rows, saved_at}.
원본 테이블 이름은 JSON 내부에 보존하고, 파일명은 안전한 slug를 쓴다.
"""

import json
import os
import re
import unicodedata
from datetime import datetime, timezone

import deps

TABLES_DIR = deps.TABLES_DIR
INDEX_PATH = os.path.join(TABLES_DIR, "index.json")

MENUS = ("upload", "standardized", "deduped", "similarity")


def _now_iso() -> str:
    """현재 시각을 로컬 타임존 ISO 8601 문자열(초 단위)로 반환한다.

    Returns:
        str: 예) "2026-10-04T13:05:00+09:00".
    """
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _slugify(name: str) -> str:
    """파일명 안전화. 한글은 유지하되 경로/제어 문자만 제거한다.

    Args:
        name (str): 원본 테이블 이름.

    Returns:
        str: 파일 시스템에 안전한 slug(최대 120자). 비면 "table".
    """
    s = unicodedata.normalize("NFC", str(name)).strip()
    s = re.sub(r'[\\/:*?"<>|]+', "_", s)   # 파일 시스템 금지 문자
    s = re.sub(r"\s+", "_", s)
    s = s.strip("._") or "table"
    return s[:120]


def _menu_dir(menu: str) -> str:
    """메뉴 디렉토리 경로를 반환하고 없으면 생성한다.

    Args:
        menu (str): 메뉴 이름(MENUS 중 하나).

    Returns:
        str: data/tables/<menu> 절대 경로.

    Raises:
        ValueError: menu가 MENUS에 없을 때.
    """
    if menu not in MENUS:
        raise ValueError(f"알 수 없는 메뉴: {menu}")
    d = os.path.join(TABLES_DIR, menu)
    os.makedirs(d, exist_ok=True)
    return d


def _read_json(path: str, default):
    """JSON 파일을 읽는다. 파일이 없으면 default를 반환한다.

    Args:
        path (str): JSON 파일 경로.
        default: 파일이 없을 때 반환할 기본값.

    Returns:
        파싱된 JSON 객체(dict/list) 또는 default.
    """
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: str, obj) -> None:
    """객체를 JSON 파일로 저장한다(한글 보존, 들여쓰기 2).

    상위 디렉토리가 없으면 생성한다.

    Args:
        path (str): 저장할 파일 경로.
        obj: JSON 직렬화 가능한 객체.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def _load_index() -> list:
    """전체 테이블 메타 인덱스를 로드한다.

    Returns:
        list: 메타 dict 목록. 인덱스 파일이 없으면 빈 리스트.
    """
    return _read_json(INDEX_PATH, [])


def _save_index(index: list) -> None:
    """테이블 메타 인덱스를 저장한다.

    Args:
        index (list): 메타 dict 목록.
    """
    _write_json(INDEX_PATH, index)


def list_tables(menu: str | None = None) -> list:
    """메타 인덱스 반환. menu 지정 시 해당 메뉴만.

    Args:
        menu (str | None): 필터링할 메뉴. None이면 전체.

    Returns:
        list: saved_at 내림차순으로 정렬된 메타 dict 목록.
    """
    index = _load_index()
    if menu:
        index = [m for m in index if m.get("menu") == menu]
    return sorted(index, key=lambda m: m.get("saved_at", ""), reverse=True)


def load_table(menu: str, name: str) -> dict | None:
    """특정 테이블을 로드한다.

    Args:
        menu (str): 메뉴 이름.
        name (str): 테이블 이름.

    Returns:
        dict | None: {name, menu, columns, rows, saved_at} 또는
            파일이 없으면 None.
    """
    path = os.path.join(_menu_dir(menu), _slugify(name) + ".json")
    return _read_json(path, None)


def save_table(menu: str, name: str, columns: list, rows: list,
               overwrite: bool = False) -> dict:
    """테이블 저장 + 인덱스 upsert.

    같은 (menu, name)이 이미 있고 overwrite=False면 FileExistsError.

    Args:
        menu (str): 메뉴 이름.
        name (str): 테이블 이름.
        columns (list): 컬럼명 목록.
        rows (list): 행 데이터 목록.
        overwrite (bool, optional): 기존 파일 덮어쓰기 허용 여부. 기본 False.

    Returns:
        dict: 저장된 테이블의 메타({name, menu, slug, row_count, saved_at}).

    Raises:
        FileExistsError: 같은 테이블이 있고 overwrite=False일 때.
    """
    slug = _slugify(name)
    path = os.path.join(_menu_dir(menu), slug + ".json")
    if os.path.exists(path) and not overwrite:
        raise FileExistsError(name)

    saved_at = _now_iso()
    _write_json(path, {
        "name": name, "menu": menu, "columns": columns,
        "rows": rows, "saved_at": saved_at,
    })

    meta = {"name": name, "menu": menu, "slug": slug,
            "row_count": len(rows), "saved_at": saved_at}
    index = [m for m in _load_index()
             if not (m.get("menu") == menu and m.get("slug") == slug)]
    index.append(meta)
    _save_index(index)
    return meta


def delete_table(menu: str, name: str) -> bool:
    """테이블 파일과 인덱스 항목을 삭제한다.

    Args:
        menu (str): 메뉴 이름.
        name (str): 테이블 이름.

    Returns:
        bool: 삭제 전 파일이 실제로 존재했는지 여부.
    """
    slug = _slugify(name)
    path = os.path.join(_menu_dir(menu), slug + ".json")
    existed = os.path.exists(path)
    if existed:
        os.remove(path)
    index = [m for m in _load_index()
             if not (m.get("menu") == menu and m.get("slug") == slug)]
    _save_index(index)
    return existed
