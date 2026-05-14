FROM python:3.11-slim AS backend

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl nodejs npm \
    tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt package.json ./
RUN pip install --no-cache-dir -r requirements.txt

COPY frontend/package.json frontend/package.json
COPY frontend/tsconfig.json frontend/tsconfig.json
COPY frontend/tsconfig.node.json frontend/tsconfig.node.json
COPY frontend/vite.config.ts frontend/vite.config.ts
COPY frontend/index.html frontend/index.html
COPY frontend/src frontend/src
RUN npm --prefix frontend install && npm --prefix frontend run build

COPY backend backend
COPY docs docs
COPY report report
COPY scripts scripts
COPY README.md README.md
COPY .env.example .env.example

ENV FRONTEND_DIST=/app/frontend/dist
EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
