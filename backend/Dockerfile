FROM python:3.11-slim

# System dependencies for OCR (Tesseract) and PDF rasterization (Poppler)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    poppler-utils \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the whole repository so both backend/ and frontend/ keep their
# relative layout (app/main.py resolves frontend/ two levels up from itself).
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend ./backend
COPY frontend ./frontend

RUN mkdir -p ./backend/storage/uploads

WORKDIR /app/backend
ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
