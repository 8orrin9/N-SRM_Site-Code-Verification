# -*- coding: utf-8 -*-
"""FastAPI 앱 엔트리.

실행: uvicorn main:app --reload --app-dir app/backend --port 8000
"""

import logging
import os

import deps  # noqa: F401  (sys.path + .env 부트스트랩; 최우선 import)

import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request

from routers import dedup, similarity, standardize, tables, upload

_LOG = logging.getLogger(__name__)

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


def _maps_api_error_detail(exc: requests.exceptions.RequestException) -> str:
    """Google Maps/Places API 호출 실패에서 사용자에게 보여줄 메시지를 뽑아낸다.

    잘못된 좌표(범위 밖 위/경도)·잘못된 요청 형식 등으로 Google이 4xx/5xx를
    돌려주면 requests가 예외를 던진다. 응답 본문에 에러 메시지가 있으면 그걸
    노출하고, 없으면 상태코드만으로 안내한다.

    Args:
        exc (requests.exceptions.RequestException): 발생한 예외.

    Returns:
        str: 프론트 toast에 그대로 표시할 메시지.
    """
    resp = getattr(exc, "response", None)
    if resp is not None:
        try:
            body = resp.json()
            msg = (body.get("error") or {}).get("message") or body.get("error_message")
        except ValueError:
            msg = None
        if msg:
            return f"지도 API 요청이 거부되었습니다 ({resp.status_code}): {msg}"
        return f"지도 API 요청이 거부되었습니다 (HTTP {resp.status_code}). 주소/좌표 값을 확인해주세요."
    return f"지도 API 호출에 실패했습니다: {exc}"


@app.exception_handler(requests.exceptions.RequestException)
async def maps_api_exception_handler(request: Request, exc: requests.exceptions.RequestException):
    """Google Maps/Places 호출 중 발생한 예외를 500 대신 502 + 안내 메시지로 변환.

    원인은 보통 잘못된 좌표(예: 위/경도가 뒤바뀌어 범위를 벗어남)나 요청 형식
    오류다. 이 핸들러가 없으면 처리되지 않은 예외로 올라가 FastAPI가 일반 500을
    돌려주고, 프론트에는 아무 설명 없는 에러만 보인다. 여기서 잡아 `{"detail": ...}`
    로 응답하면 프론트의 jsonFetch가 기존 HTTP 에러와 동일한 toast로 보여준다.

    Args:
        request (Request): 들어온 요청(미사용, 시그니처 요구).
        exc (requests.exceptions.RequestException): 발생한 예외.

    Returns:
        JSONResponse: 502 상태코드 + {"detail": 안내 메시지}.
    """
    _LOG.warning("Maps API 호출 실패: %s", exc)
    return JSONResponse(status_code=502, content={"detail": _maps_api_error_detail(exc)})


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
