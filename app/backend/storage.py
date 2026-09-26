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
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _slugify(name: str) -> str:
    """파일명 안전화. 한글은 유지하되 경로/제어 문자만 제거한다."""
    s = unicodedata.normalize("NFC", str(name)).strip()
    s = re.sub(r'[\\/:*?"<>|]+', "_", s)   # 파일 시스템 금지 문자
    s = re.sub(r"\s+", "_", s)
    s = s.strip("._") or "table"
    return s[:120]


def _menu_dir(menu: str) -> str:
    if menu not in MENUS:
        raise ValueError(f"알 수 없는 메뉴: {menu}")
    d = os.path.join(TABLES_DIR, menu)
    os.makedirs(d, exist_ok=True)
    return d


def _read_json(path: str, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def _load_index() -> list:
    return _read_json(INDEX_PATH, [])


def _save_index(index: list) -> None:
    _write_json(INDEX_PATH, index)


def list_tables(menu: str | None = None) -> list:
    """메타 인덱스 반환. menu 지정 시 해당 메뉴만."""
    index = _load_index()
    if menu:
        index = [m for m in index if m.get("menu") == menu]
    return sorted(index, key=lambda m: m.get("saved_at", ""), reverse=True)


def load_table(menu: str, name: str) -> dict | None:
    path = os.path.join(_menu_dir(menu), _slugify(name) + ".json")
    return _read_json(path, None)


def save_table(menu: str, name: str, columns: list, rows: list,
               overwrite: bool = False) -> dict:
    """테이블 저장 + 인덱스 upsert. 반환: 메타 dict.

    같은 (menu, name)이 이미 있고 overwrite=False면 FileExistsError.
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
    slug = _slugify(name)
    path = os.path.join(_menu_dir(menu), slug + ".json")
    existed = os.path.exists(path)
    if existed:
        os.remove(path)
    index = [m for m in _load_index()
             if not (m.get("menu") == menu and m.get("slug") == slug)]
    _save_index(index)
    return existed
