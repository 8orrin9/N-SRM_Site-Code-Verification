# -*- coding: utf-8 -*-
"""FastAPI 앱 엔트리.

실행: uvicorn main:app --reload --app-dir app/backend --port 8000
"""

import os

import deps  # noqa: F401  (sys.path + .env 부트스트랩; 최우선 import)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
    return {"ok": True, "adapter_mode": os.getenv("MAPS_ADAPTER_MODE", "real")}
