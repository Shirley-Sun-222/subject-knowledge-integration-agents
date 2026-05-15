FROM node:20-bookworm-slim AS frontend-builder

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json frontend/
RUN npm --prefix frontend ci

COPY frontend/tsconfig.json frontend/tsconfig.json
COPY frontend/tsconfig.node.json frontend/tsconfig.node.json
COPY frontend/vite.config.ts frontend/vite.config.ts
COPY frontend/index.html frontend/index.html
COPY frontend/src frontend/src
RUN npm --prefix frontend run build

FROM python:3.11-slim-bookworm AS backend

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

ARG INSTALL_PLAYWRIGHT_BROWSER=0
ARG INSTALL_OCR=1

WORKDIR /app
RUN if [ "${INSTALL_OCR}" = "1" ]; then \
      apt-get update -o Acquire::Retries=5 && apt-get install -y --fix-missing --no-install-recommends -o Acquire::Retries=5 \
        ca-certificates \
        tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng \
        && rm -rf /var/lib/apt/lists/*; \
    fi

COPY requirements-docker.txt ./
RUN pip install --no-cache-dir -r requirements-docker.txt

RUN if [ "${INSTALL_PLAYWRIGHT_BROWSER}" = "1" ]; then \
      pip install --no-cache-dir playwright==1.49.1 && python -m playwright install --with-deps chromium; \
    fi

COPY backend backend
COPY docs docs
COPY report report
COPY scripts scripts
COPY README.md README.md
COPY .env.example .env.example
COPY --from=frontend-builder /app/frontend/dist frontend/dist

ENV FRONTEND_DIST=/app/frontend/dist \
    PDF_RENDERER=reportlab \
    PORT=7860
EXPOSE 7860
CMD ["sh", "-c", "uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
