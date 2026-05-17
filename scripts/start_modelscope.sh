#!/usr/bin/env bash
set -euo pipefail

export FRONTEND_DIST="${FRONTEND_DIST:-$(pwd)/frontend/dist}"
export DATABASE_URL="${DATABASE_URL:-sqlite:///./data/app.db}"
export UPLOAD_DIR="${UPLOAD_DIR:-./data/uploads}"
export INDEX_DIR="${INDEX_DIR:-./data/indexes}"
export GENERATED_DIR="${GENERATED_DIR:-./data/generated}"
export PDF_TEXT_EXTRACT_WORKERS="${PDF_TEXT_EXTRACT_WORKERS:-4}"
export PDF_OCR_WORKERS="${PDF_OCR_WORKERS:-2}"

python -m uvicorn backend.app.main:app --host 0.0.0.0 --port "${PORT:-7860}"
