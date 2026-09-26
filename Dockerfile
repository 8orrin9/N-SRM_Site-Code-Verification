# ---- stage 1: 프론트 정적 빌드 ----
FROM node:22-alpine AS web
WORKDIR /web
COPY app/frontend/package.json app/frontend/package-lock.json ./
RUN npm ci
COPY app/frontend/ ./
ENV NEXT_PUBLIC_API_BASE=""
RUN npm run build

# ---- stage 2: 파이썬 런타임 ----
FROM python:3.11-slim AS app
WORKDIR /app
COPY requirements-deploy.txt ./
RUN pip install --no-cache-dir -r requirements-deploy.txt
COPY scripts/ ./scripts/
COPY config/ ./config/
COPY app/backend/ ./app/backend/
COPY --from=web /web/out ./app/frontend/out
ENV MAPS_ADAPTER_MODE=mock
ENV PORT=8000
CMD ["sh", "-c", "uvicorn main:app --app-dir app/backend --host 0.0.0.0 --port ${PORT}"]
