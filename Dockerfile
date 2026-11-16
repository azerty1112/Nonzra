# مرحلة البناء - تثبيت الاعتمادات
FROM python:3.11-slim AS builder

WORKDIR /app

# تثبيت أدوات البناء
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# تثبيت الاعتمادات Python
COPY api_server/requirements.txt ./api_server/requirements.txt
RUN pip install --no-cache-dir --user -r api_server/requirements.txt

# مرحلة التشغيل - صورة نهائية خفيفة
FROM python:3.11-slim

# تثبيت تesseract和 librosas
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libtesseract-dev \
    libgl1-mesa-glx \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# إنشاء مستخدم غير جذر للأمان
RUN groupadd -r nonecap && useradd -r -g nonecap -d /app -s /sbin/nologin nonecap

WORKDIR /app

# نسخ الاعتمادات المثبتة من مرحلة البناء
COPY --from=builder /root/.local /home/nonecap/.local
ENV PATH=/home/nonecap/.local/bin:$PATH

# نسخ كود التطبيق
COPY --chown=nonecap:nonecap solver_engine ./solver_engine
COPY --chown=nonecap:nonecap api_server ./api_server
COPY --chown=nonecap:nonecap clients ./clients
COPY --chown=nonecap:nonecap intelligence ./intelligence
COPY --chown=nonecap:nonecap browser ./browser
COPY --chown=nonecap:nonecap extension ./extension
COPY --chown=nonecap:nonecap pyproject.toml ./

# تغيير المستخدم إلى غير جذر
USER nonecap

# كشف المنفذ
EXPOSE 8000

# أمر التشغيل
CMD ["python", "-m", "uvicorn", "api_server.main:app", "--host", "0.0.0.0", "--port", "8000"]
