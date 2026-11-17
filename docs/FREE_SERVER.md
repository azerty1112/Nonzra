# خادم Nonzra المجاني — بلا حدود

هذا الدليل يجعل Nonzra خادمًا كاملًا يعمل **مجانًا وبلا حدود**: لا اشتراك،
لا حصة، لا مفتاح إلزامي، ولا حظر تلقائي.

## الوضع الافتراضي

| البند | القيمة الافتراضية |
|-------|-------------------|
| حدود الطلبات لكل IP | **0 (معطّل)** |
| حدود الطلبات لكل مفتاح | **0 (معطّل)** |
| حظر IP بعد التجاوز | **معطّل** |
| مفتاح API | **غير مطلوب** |
| عدد عناصر الدفعة | 200 لكل طلب |
| عمال الحل | 4 (يتوسّع إلى 16) |
| الاحتفاظ بالمهام | ساعة، وسقف 5000 مهمة ثم تنظيف تلقائي |

تحقّق في أي لحظة:

```bash
curl -s http://localhost:8000/status | python -m json.tool
```

```json
{
  "mode": "unlimited",
  "free": true,
  "requires_api_key": false,
  "policy": { "per_ip_per_minute": 0, "per_key_per_minute": 0 },
  "supported_types": ["drag", "hcaptcha", "image", "math", "point", "..."]
}
```

## التشغيل في دقيقة

### 1) محليًا

```bash
git clone https://github.com/azerty1112/Nonzra && cd Nonzra
bash run.sh
# http://localhost:8000          الصفحة العامة (فيها حل صورة مباشر)
# http://localhost:8000/dashboard لوحة التحكم
# http://localhost:8000/docs      توثيق API التفاعلي
```

`run.sh` يثبّت الاعتمادات الناقصة تلقائيًا ثم يشغّل الخادم.

### 2) Docker

```bash
docker compose up -d
# أو
docker run -d --name nonecap -p 8000:8000 nonecap/clone:latest
```

### 3) نشر مجاني على السحابة

| المنصة | الأمر | ملاحظات |
|--------|-------|---------|
| **Fly.io** | `fly launch --now --copy-config` | `fly.toml` جاهز، تخزين دائم 1GB |
| **Render** | اربط المستودع | `render.yaml` جاهز (خطة مجانية + قرص) |
| **Railway** | اربط المستودع | `railway.json` + `Procfile` جاهزان |
| **VPS** | `docker compose -f docker-compose.prod.yml up -d` | Caddy يعطيك HTTPS تلقائيًا |

## HTTPS بلا تكلفة

`docker-compose.prod.yml` يشغّل Caddy بجانب الخادم:

```bash
DOMAIN=captcha.example.com docker compose -f docker-compose.prod.yml up -d
```

Caddy يحصل على شهادة Let's Encrypt ويجدّدها تلقائيًا، ويضبط الضغط والرؤوس الأمنية.

## إذا أردت التضييق (اختياري)

الخادم يبقى مجانيًا، لكن يمكنك حماية مواردك عند النشر العام:

```bash
# .env
NONECAP_UNLIMITED=0
NONECAP_RATE_LIMIT_PER_MINUTE=120
NONECAP_KEY_RATE_LIMIT_PER_MINUTE=60
NONECAP_IP_BLOCK_SECONDS=300
NONECAP_REQUIRE_API_KEY=1
```

| المتغير | الافتراضي | المعنى |
|---------|-----------|--------|
| `NONECAP_UNLIMITED` | `1` | `0` يفعّل كل الحدود أدناه |
| `NONECAP_REQUIRE_API_KEY` | `0` | إلزام `Authorization: Bearer <key>` |
| `NONECAP_RATE_LIMIT_PER_MINUTE` | `0` | حد لكل IP |
| `NONECAP_KEY_RATE_LIMIT_PER_MINUTE` | `0` | حد لكل مفتاح |
| `NONECAP_IP_BLOCK_SECONDS` | `0` | مدة الحظر |
| `NONECAP_MAX_BATCH` | `200` | سقف عناصر الدفعة |
| `NONECAP_CONCURRENCY` | `4` | عمال متوازون |
| `NONECAP_MAX_CONCURRENCY` | `16` | سقف التوسّع التلقائي |
| `NONECAP_JOB_TTL_SECONDS` | `3600` | حذف المهام المنتهية |
| `NONECAP_MAX_JOBS` | `5000` | سقف المهام في الذاكرة |
| `NONECAP_CORS_ORIGINS` | فارغ | `*` أو قائمة أصول مفصولة بفواصل |

## استهلاك الخدمة من الكود

```python
import httpx

with httpx.Client(base_url="http://localhost:8000") as c:
    with open("captcha.png", "rb") as fh:
        r = c.post("/auto", files={"file": ("captcha.png", fh, "image/png")})
    data = r.json()
    print(data["result"]["text"], data["mind"]["calibrated_confidence"])
```

بلا مفتاح، بلا تهيئة، بلا حصة.

## ملاحظات على الموارد

الخادم بلا حدود في الطلبات، لكن العتاد له حدود. الإعدادات الافتراضية توزّع
العمل على 4 عمال وتنظّف الذاكرة كل دقيقة (مهام منتهية + متتبّعات معدل).
إذا كان الجهاز ضعيفًا:

```bash
NONECAP_CONCURRENCY=1 NONECAP_MAX_CONCURRENCY=2 bash run.sh
```

## الاستخدام المسؤول

حلّ الكبتشا يخضع لشروط استخدام المواقع. استخدم الخادم على أنظمة تملكها أو
لديك إذن صريح باختبارها، والترخيص MIT يعني أنك مسؤول عن استخدامك.
