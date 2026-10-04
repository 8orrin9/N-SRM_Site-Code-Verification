# -*- coding: utf-8 -*-
"""FastAPI 앱 엔트리.

실행: uvicorn main:app --reload --app-dir app/backend --port 8000
"""

import os

import deps  # noqa: F401  (sys.path + .env 부트스트랩; 최우선 import)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from routers import dedup, similarity, standardize, tables, upload

app = FastAPI(title="N-SRM Site Code Verification API")

_origins = os.getenv("CORS_ORIGIN", "http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tables.router)
app.include_router(upload.router)
app.include_router(standardize.router)
app.include_router(dedup.router)
app.include_router(similarity.router)


@app.get("/api/health")
def health():
    """헬스체크 엔드포인트.

    Returns:
        dict: 서버 생존 여부와 현재 Maps 어댑터 모드.
            {"ok": True, "adapter_mode": "real"|"mock"}
    """
    return {"ok": True, "adapter_mode": os.getenv("MAPS_ADAPTER_MODE", "real")}


# 프론트 정적 export(out/) 서빙 — 반드시 모든 /api 라우터 include 이후에 마운트한다.
# 로컬 개발(out 미빌드)에서는 마운트를 건너뛰어 기존 8000 API-only 동작을 유지한다.
_OUT = os.path.join(deps.ROOT, "app", "frontend", "out")
if os.path.isdir(_OUT):
    app.mount("/", StaticFiles(directory=_OUT, html=True), name="static")
