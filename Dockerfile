# Trading Universe - single-container deployment.
#
# Stage 1 builds the frontend as a static export; stage 2 is the Python API,
# which serves that export at "/" alongside /api, /ws and /docs. One process,
# one port, one URL. Defaults to DEMO data + PAPER env + ADVISORY mode, so the
# image is safe to run anywhere; nothing in it can reach a real account
# without TRADING_ENV, ALLOW_REAL_ORDERS and Moomoo credentials being set.

FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
ENV STATIC_EXPORT=1 \
    NEXT_PUBLIC_API_URL="" \
    NEXT_PUBLIC_WS_SAME_ORIGIN=1 \
    NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM python:3.11-slim AS runtime
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TU_DATA_MODE=DEMO \
    TRADING_ENV=PAPER \
    ALLOW_REAL_ORDERS=false \
    TU_OPERATING_MODE=ADVISORY \
    TU_API_HOST=0.0.0.0 \
    TU_API_PORT=8000 \
    TU_STATIC_DIR=/app/frontend/out \
    TU_DATABASE_URL=sqlite:////app/db/trading.sqlite
COPY backend/pyproject.toml backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ ./backend/
RUN pip install --no-cache-dir --no-deps -e ./backend
COPY config/ ./config/
COPY data/ ./data/
COPY --from=frontend /app/frontend/out ./frontend/out
RUN mkdir -p /app/db
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/system/status').status==200 else 1)"
CMD ["python", "-m", "trading_universe.cli", "serve"]
