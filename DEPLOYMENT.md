# دليل النشر الشامل لمشروع NoneCap Clone

هذا الدليل يشرح كيفية نشر مشروع NoneCap Clone في بيئات مختلفة (التطوير، الإنتاج، كوبرنتيس).

## متطلبات النظام

- Python 3.11+
- Tesseract OCR (اختياري، للحل النصي)
- Redis (اختياري، للطابور الموزع)
- PostgreSQL (اختياري، لقاعدة بيانات الإنتاج)
- Docker و Docker Compose (للنشر عبر حاويات)
- Kubernetes (للنشر المتقدم)

## 1. النشر باستخدام Docker Compose (الموصى به للتطوير)

```bash
# استنساخ المستودع
git clone https://github.com/azerty1112/Nonzra.git
cd Nonzra

# منح صلاحية تشغيل السكربت
chmod +x deploy.sh

# التشغيل
./deploy.sh

# السيرفر سيكون متاحاً على http://localhost:8000
# لوحة التحكم: http://localhost:8000/web
# المقاييس: http://localhost:8000/metrics
```

### متغيرات البيئة (`.env`)

أنشئ ملف `.env` في جذر المشروع:

```env
# قاعدة البيانات
DATABASE_URL=sqlite:///nonecap_clone.db
# أو لـ PostgreSQL:
# DATABASE_URL=postgresql://nonecap:nonecap@localhost:5432/nonecap

# مفتاح التشفير (مهم جداً للإنتاج)
NONECAP_ENCRYPTION_KEY=ضع_مفتاح_عشوائي_قوي_هنا

# عنوان Redis للطابور الموزع
REDIS_URL=redis://localhost:6379/0

# عنوان ديسكورد للتنبيهات (اختياري)
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

# عنوان الويب هوك للتنبيهات (اختياري)
ALERT_WEBHOOK_URL=https://your-webhook-endpoint.com/alerts
```

## 2. النشر باستخدام Kubernetes

```bash
# تطبيق أسرار التشفير
kubectl apply -f deploy/k8s/redis-postgres.yaml

# تطبيق محاكيات الخدمة
kubectl apply -f deploy/k8s/deployment.yaml
kubectl apply -f deploy/k8s/hpa.yaml

# التحقق من حالة التشغيل
kubectl get pods -w
kubectl get svc
```

### الوصول إلى الخدمة

```bash
# الحصول على عنوان خدمة LoadBalancer
kubectl get svc nonecap-api

# فتح لوحة التحكم
open http://<LOADBALANCER_IP>/web
```

## 3. النشر اليدوي (باستخدام بايثون مباشرة)

```bash
# استنساخ المستودع
git clone https://github.com/azerty1112/Nonzra.git
cd Nonzra

# تثبيت المتطلبات
pip install -r api_server/requirements.txt

# متغيرات البيئة
export DATABASE_URL=sqlite:///nonecap_clone.db
export NONECAP_ENCRYPTION_KEY=مفتاح_تشفير_قوي
export REDIS_URL=redis://localhost:6379/0

# تشغيل السيرفر
uvicorn api_server.main:app --host 0.0.0.0 --port 8000 --workers 4
```

## 4. إعداد خدمة خارجية لـ hCaptcha (nindiad)

لحل hCaptcha باستخدام خدمة nindiad الخارجية مع إعادة المحاولة التلقائية:

```bash
# عبر واجهة API
curl -X POST http://localhost:8000/api/hcaptcha/external \
  -H "Content-Type: application/json" \
  -d '{
    "api_key": "مفتاح_nindiad_خاص_بك",
    "external_api": "https://api.nindiad.com",
    "external_api_type": "nindiad",
    "max_retries": 10,
    "retry_delay": 5.0
  }'
```

## 5. اختبار الأداء باستخدام Locust

```bash
# تثبيت Locust
pip install locust

# تشغيل اختبار الأحمال
locust -f locustfile.py --host=http://localhost:8000

# افتح واجهة المستخدم على http://localhost:8089
```

## 6. العملاء المدعومون

### بايثون (متزامن/غير متزامن)
```python
from nonecap_client import NoneCap

nc = NoneCap(base_url="http://localhost:8000", api_key="مفتاح_المفتاح")
result = nc.solve_image(image_path="captcha.png")
auto = nc.auto(image_path="captcha.png", human_like=True)
```

### تايبسكريبت
```typescript
import { NoneCap } from "nonecap-client";

const nc = new NoneCap({ baseUrl: "http://localhost:8000", apiKey: "مفتاح_المفتاح" });
const result = await nc.solveImage(file);
const auto = await nc.auto({ humanLike: true }, file);
```

### Go
```go
package main

import (
    "fmt"
    nonecap "nonecap-client"
)

func main() {
    nc := nonecap.NewNoneCap(
        nonecap.WithBaseURL("http://localhost:8000"),
        nonecap.WithAPIKey("مفتاح_المفتاح"),
    )
    
    result, err := nc.SolveImage("captcha.png")
    if err != nil {
        fmt.Println("خطأ:", err)
        return
    }
    fmt.Println("النص:", result.Text)
}
```

## 7. مراقبة النظام

- لوحة التحكم: `/web`
- الإحصائيات: `/stats`
- حالة العامل التلقائي: `/auto/status`
- إحصائيات الخبرة: `/experience/stats`
- قاعدة المعرفة: `/experience/knowledge`
- مقاييس Prometheus: `/metrics`
- لوحة تحكم Grafana (اختياري): يمكن إضافة ملف تعريف في `deploy/grafana/`

## 8. الأمان

- مفاتيح API تُخزّن مشفرة في قاعدة البيانات
- حظر عناوين IP التي تتجاوز معدل الطلب المسموح
- حد معدل الطلب: 120 طلب في الدقيقة لكل عنوان IP (قابل للتعديل)
- يمكن إنشاء وإدارة مفاتيح API عبر `/api/keys`

## 9. استكشاف الأخطاء

```bash
# فحص حالة السيرفر
curl http://localhost:8000/health

# فحص السجلات
docker-compose logs -f nonecap

# التحقق من الاتصال بقاعدة البيانات
curl http://localhost:8000/stats

# التحقق من حالة العامل التلقائي
curl http://localhost:8000/auto/status
```

## الترخيص

MIT License - للاستخدام المصرح به في الاختبار، المراقبة، والأتمتة الخاصة بك فقط. يُحظر استخدامه للتحايل على أنظمة الغير دون إذن صريح.
