#!/usr/bin/env bash
# تشغيل خادم Nonzra بأمر واحد — بلا مفاتيح وبلا حدود.
# الاستخدام:
#   bash run.sh              # المنفذ 8000
#   PORT=9000 bash run.sh    # منفذ آخر
#   NONECAP_UNLIMITED=0 NONECAP_RATE_LIMIT_PER_MINUTE=120 bash run.sh   # وضع محمي
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"
WORKERS="${WORKERS:-1}"
PYTHON_BIN="${PYTHON_BIN:-}"

# اختيار بايثون: بيئة افتراضية محلية إن وُجدت
if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x ".venv/bin/python" ]]; then
    PYTHON_BIN=".venv/bin/python"
  elif [[ -x "venv/bin/python" ]]; then
    PYTHON_BIN="venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

echo "▶ Nonzra — خادم حل الكبتشا المجاني"
echo "  بايثون : $($PYTHON_BIN -V 2>&1)"
echo "  الوضع  : ${NONECAP_UNLIMITED:-1} (1 = بلا حدود)"
echo "  العنوان: http://localhost:${PORT}"
echo

# تثبيت الاعتمادات إن كانت ناقصة (مرة واحدة)
if ! "$PYTHON_BIN" -c "import fastapi, cv2, numpy, PIL, pytesseract" >/dev/null 2>&1; then
  echo "⏳ تثبيت الاعتمادات المطلوبة…"
  "$PYTHON_BIN" -m pip install --quiet --upgrade pip
  "$PYTHON_BIN" -m pip install --quiet -r api_server/requirements.txt
fi

exec "$PYTHON_BIN" -m uvicorn api_server.main:app \
  --host "$HOST" --port "$PORT" --workers "$WORKERS" \
  --proxy-headers --forwarded-allow-ips="*"
