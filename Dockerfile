# المرحلة 1: الاعتمادات فقط (بدون أدوات البناء الثقيلة)
FROM python:3.11-slim AS builder

WORKDIR /app

COPY api_server/requirements.txt ./api_server/requirements.txt
# torch/torchvision اختيارية وضخمة جدًا؛ تُستثنى صورة التشغيل الافتراضية
RUN grep -viE '^(torch|torchvision)' api_server/requirements.txt > /tmp/requirements.txt \
    && pip install --no-cache-dir --user -r /tmp/requirements.txt

# المرحلة 2: صورة التشغيل النهائية
FROM python:3.11-slim

# Tesseract مطلوب لقراءة كبتشا الصور والنصوص والعمليات الحسابية
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-ara \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# مستخدم غير جذري للأمان
RUN groupadd -r nonecap && useradd -r -g nonecap -d /app -s /sbin/nologin nonecap

WORKDIR /app

COPY --from=builder /root/.local /home/nonecap/.local
ENV PATH=/home/nonecap/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    NONECAP_ENV=production

COPY --chown=nonecap:nonecap solver_engine ./solver_engine
COPY --chown=nonecap:nonecap api_server ./api_server
COPY --chown=nonecap:nonecap clients ./clients
COPY --chown=nonecap:nonecap intelligence ./intelligence
COPY --chown=nonecap:nonecap browser ./browser
COPY --chown=nonecap:nonecap extension ./extension
COPY --chown=nonecap:nonecap web ./web
COPY --chown=nonecap:nonecap cli ./cli
COPY --chown=nonecap:nonecap pyproject.toml ./

RUN mkdir -p /app/data && chown nonecap:nonecap /app/data
ENV DATABASE_URL=sqlite:////app/data/nonecap_clone.db
VOLUME ["/app/data"]

USER nonecap

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["python", "-m", "uvicorn", "api_server.main:app", "--host", "0.0.0.0", "--port", "8000"]
