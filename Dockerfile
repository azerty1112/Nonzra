FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libtesseract-dev \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY api_server/requirements.txt ./api_server/requirements.txt
RUN pip install --no-cache-dir -r api_server/requirements.txt

COPY solver_engine ./solver_engine
COPY api_server ./api_server

EXPOSE 8000

CMD ["uvicorn", "api_server.main:app", "--host", "0.0.0.0", "--port", "8000"]
