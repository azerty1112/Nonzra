# توثيق API - NoneCap Clone

النقاط الأساسية للسيرفر (يفترض التشغيل على `http://localhost:8000`).

## `GET /health`
فحص حالة السيرفر.

```json
{ "status": "ok", "service": "nonecap-clone", "version": "0.4.0" }
```

## `POST /solve/image`
حل صورة كبتشا نصية عبر رفع ملف.

```
Content-Type: multipart/form-data

file: (ملف الصورة)
psm: 7
oem: 3
preprocess: true
resize_width: 400
threshold: otsu
whitelist: (اختياري)
```

## `POST /solve/image/b64`
حل صورة كبتشا عبر base64 في JSON.

```json
{
  "image_b64": "...",
  "psm": 7,
  "oem": 3,
  "preprocess": true,
  "resize_width": 400,
  "threshold": "otsu"
}
```

## رد الاستجابة

```json
{
  "success": true,
  "captcha_type": "image",
  "text": "AB12",
  "token": null,
  "confidence": 0.7,
  "response_time_ms": 340,
  "error": null,
  "metadata": { "chars": 4, "method": "tesseract" }
}
```

## الحل الذاتي الكامل

### `POST /auto`
حل ذاتي من البداية للنهاية: كشف تلقائي للنوع (عند عدم تحديده)، تحليل، ضبط تكيفي، اختيار استراتيجية متعلمة، حل، تقييم، وتصعيد تلقائي عند ضعف الثقة.

```
Content-Type: multipart/form-data

file: (اختياري — صورة/لغز)
template: (اختياري — قالب drag)
captcha_type: (اختياري — يكشف تلقائيًا إذا تُرك فارغًا)
sitekey, url, action, cdata: (اختياري)
human_like: true|false
max_escalations: 2
```

الرد:

```json
{
  "result": {
    "success": true,
    "captcha_type": "image",
    "text": "AB12",
    "token": null,
    "confidence": 0.93,
    "response_time_ms": 210,
    "error": null,
    "metadata": {}
  },
  "detected_type": "image",
  "detection_confidence": 0.8,
  "strategy_used": "local_primary",
  "params_used": { "psm": 7, "threshold": "otsu", "denoise": true },
  "escalations": 0,
  "trace": ["كشف تلقائي: ...", "تحليل: ...", "اكتمل: ..."],
  "alerts": [],
  "total_time_ms": 320
}
```

### `POST /auto/async`
يرسل المهمة إلى العامل الخلفي الذاتي ويعيد `job_id`.

### `GET /auto/job/{job_id}`
حالة المهمة: `queued` / `processing` / `completed` / `failed` مع النتيجة الكاملة.

### `GET /auto/status`
حالة العامل + لقطة محرك التعلّم + لقطة الضبط التكيفي + تقرير المراقبة.

### `POST /feedback`
تغذية تعلّم خارجية لتحسين القرارات:

```json
{
  "strategy": "local_primary",
  "success": true,
  "confidence": 0.9,
  "response_time_ms": 150,
  "captcha_type": "image",
  "params": { "psm": 7, "threshold": "otsu", "denoise": true }
}
```

## العملاء

### بايثون (متزامن)

```python
from nonecap_client import NoneCap

nc = NoneCap(base_url="http://localhost:8000")
result = nc.solve_image(image_path="captcha.png")
print(result.text)

# الحل الذاتي الكامل
auto = nc.auto(image_path="captcha.png", human_like=True)
print(auto.detected_type, auto.strategy_used, auto.result.text)
print(nc.auto_status())
```

### بايثون (غير متزامن)

```python
from nonecap_client import NoneCapAsync

async def main():
    nc = NoneCapAsync()
    result = await nc.solve_image(image_bytes=b"...")
    print(result.text)
```

### تايبسكريبت

```ts
import { NoneCap } from "nonecap-client";

const nc = new NoneCap({ baseUrl: "http://localhost:8000" });
const result = await nc.solveImage(file);
console.log(result.text);
```

## الإضافة للمتصفح

حمل مجلد `extension/` عبر `chrome://extensions` > Developer mode > Load unpacked.

## الترخيص

MIT - للاستخدام المصرح به في الاختبار والمراقبة والأتمتة فقط.

## `GET /capabilities`
قائمة أنواع الكبتشا المدعومة فعليًا مع المحرّكات المسجّلة لكل نوع.

```json
{
  "supported_types": ["drag", "hcaptcha", "image", "math", "point", "recaptcha_v2", "rotate", "slider", "text", "turnstile"],
  "types": { "math": { "solvers": ["MathSolver"], "count": 1 } },
  "unsupported_types": ["funcaptcha", "geetest", "hcaptcha_enterprise", "recaptcha_v2_invisible", "recaptcha_v3"],
  "total_solvers": 10,
  "version": "0.6.0"
}
```

## `POST /math/evaluate`
حساب تعبير رياضي بأمان، أو حلّ صورة كبتشا حسابية عبر `image_b64`.

```json
{ "expression": "12 × 4" }
→ { "success": true, "expression": "12 * 4", "answer": "48", "error": null }
```

## `POST /batch/solve`
حل حتى 50 صورة مرمّزة بـ base64 في طلب واحد.

```json
{
  "captcha_type": "image",
  "items": [
    { "image_b64": "iVBORw0...", "captcha_type": "image" },
    { "image_b64": "iVBORw0...", "template_b64": "iVBORw0...", "captcha_type": "drag" }
  ]
}
```

الاستجابة تحتوي `count`, `succeeded`, `failed`, `success_rate`, و`results` (لكل عنصر `index`, `success`, `text`, `confidence`, `error`).

## `POST /synthetic/batch`
توليد صور كبتشا صناعية مع تسمياتها لتدريب CNN أو الاختبار.

```json
{ "count": 10, "length": 4, "seed": 7, "with_png": true }
→ { "count": 10, "charset": "ABCDEFGHJKLMNPQRSTUVWXYZ23456789", "items": [{ "text": "WK3D", "png_base64": "..." }] }
```

## `GET /synthetic/sample?length=4&seed=1`
يُرجع صورة PNG مباشرة، والنص الصحيح في الترويسة `X-Captcha-Text`.

## `GET /metrics`
صيغة Prometheus النصية القياسية (`text/plain; version=0.0.4`) — صالحة للسكراب مباشرة. تعيد `503` إذا لم تكن `prometheus-client` مثبتة.

## hCaptcha مباشرة (بلا خدمة مدفوعة)

| الطريقة | المسار | الوصف |
|---------|--------|-------|
| GET | `/hcaptcha/probe` | `?sitekey=&url=` → هل هذه الشبكة تصل إلى hCaptcha؟ + خطأ صريح + تلميح وكيل + حالة OCR |
| GET | `/ocr/engines` | المحرّكات المتاحة فعلًا وترتيب الأفضلية |
| POST | `/hcaptcha/live` | `{sitekey, url, host?, max_rounds?}` → حلّ عبر البروتوكول العام: `{success, token, answer, confidence, response_time_ms, error, metadata}` |

```bash
curl "http://localhost:8000/hcaptcha/probe"
curl -X POST http://localhost:8000/hcaptcha/live \
  -H 'content-type: application/json' \
  -d '{"sitekey":"10000000-ffff-ffff-ffff-000000000001","url":"https://accounts.hcaptcha.com/demo"}'
```

`metadata.stage` يبيّن أين توقف المسار (`checksiteconfig`, `getcaptcha`, `parse`, `checkcaptcha`).
راجع [`HCAPTCHA_FREE.md`](HCAPTCHA_FREE.md) للحدود ولطريقة تمرير وكيل.

## متغيرات البيئة

| المتغير | الوصف |
|---------|-------|
| `NONECAP_HCAPTCHA_PROXY` | وكيل مخصّص لطلبات hCaptcha (يعمل عندما يحجب المزوّد النطاق) |
| `NONECAP_PROXY` | وكيل عام لكل الاستدعاءات الخارجية (http/socks5) |
| `NONECAP_TUNNEL_HEADER` | ترويسة تُضاف لطلبات hCaptcha عبر نفقك، مثال `X-Tunnel-Auth: secret` |
| `NONECAP_HTTP_TIMEOUT` | مهلة الاستدعاءات الخارجية بالثواني (افتراضي 60) |
| `NONECAP_HCAPTCHA_BASE` | عنوان بديل لخدمة hCaptcha (مرآة/بوابة محلية) |
| `DATABASE_URL` | رابط قاعدة البيانات (افتراضيًا `sqlite:///nonecap_clone.db`) |
| `NONECAP_ENCRYPTION_KEY` | مفتاح تشفير ثابت لمفاتيح API (إن لم يُحدَّد يُحفظ في `data/.encryption_key`) |
| `NONECAP_KEY_FILE` | مسار ملف مفتاح التشفير |
| `NONECAP_CORS_ORIGINS` | أصول CORS مسموحة (`*` أو قائمة مفصولة بفواصل) |
| `NVIDIA_API_KEY` / `NVIDIA_API_ENDPOINT` | خدمة حل خارجية اختيارية |

## صيغة جسم الطلب في `/solve/{type}`

تُقبل الصيغتان معًا:

- **JSON**: `{"image_b64": "...", "psm": 7}` (يستخدمه SDK والاختبارات)
- **multipart/form-data**: حقول `file` و`template` مع الحقول النصية مثل `psm=7&preprocess=true` (تستخدمها أمثلة `curl` وأداة الـ CLI)

طلب لنوع محلي (image/text/math/drag/point/slider/rotate) بلا صورة يعيد `400` برسالة عربية واضحة.

## عقل النظام (Mind)

| الطريقة | المسار | الوصف |
|---------|--------|-------|
| GET | `/mind` | تقرير العقل: `self_rating`، `skills`، `calibration`، `reflection`، `next_experiment`، `notes`، `mood` |
| POST | `/mind/plan` | `{captcha_type, difficulty, external_available, prefer_speed}` → المسار المختار + شرح + بدائل |
| POST | `/mind/observe` | `{captcha_type, success, confidence, latency_ms, error}` → يُعلّم العقل |
| GET | `/mind/accept` | `?confidence=0.8&threshold=0.7` → قرار قبول بالقيمة المتوقعة |
| GET | `/mind/skills` | كفاءة كل نوع (Beta posterior، فاصل الثقة، اتجاه EWMA) |
| GET | `/mind/calibration` | منحنى المعايرة + Brier Score |
| GET | `/mind/reflect` | الدروس المستفادة ومدى فعّالية النصائح |
| POST | `/mind/save` | حفظ الحالة على القرص الآن |

### مثال

```bash
curl -X POST http://localhost:8000/mind/plan \
  -H "Content-Type: application/json" \
  -d '{"captcha_type":"slider","difficulty":0.5,"external_available":true}'
```

```json
{
  "chosen": "ensemble_with_fallback",
  "expected_value": 0.6232,
  "alternatives": [
    {"route": "ensemble_with_fallback", "success_probability": 0.84, "expected_value": 0.623},
    {"route": "local_primary", "success_probability": 0.63, "expected_value": 0.553}
  ],
  "explanation": "اخترت ensemble_with_fallback لنوع slider (احتمال نجاح 84% وزمن ~1600ms) — أفضل من local_primary بفارق 0.07",
  "confidence_target": 0.71,
  "should_retry": false
}
```

## الذخيرة المعرفية

| الطريقة | المسار | الوصف |
|---------|--------|-------|
| GET | `/knowledge` | كل البطاقات (`?category=type\|technique\|risk`) |
| GET | `/knowledge/for/{captcha_type}` | بطاقات النوع + مصائده + شرح قرار العقل |
| GET | `/knowledge/quiz` | `?limit=5&seed=1` أسئلة تدريب مع الجواب الصحيح |
| POST | `/knowledge/quiz/answer` | تقييم إجابة وتغذية العقل بها |

## ملفات الحالة على القرص

| الملف | المحتوى |
|-------|---------|
| `data/mind_state.json` | دورات التفكير الأخيرة والعدّاد الكلي |
| `data/calibration.json` | حاويات المعايرة وعدد المشاهدات وBrier |
| `data/competence.json` | معاملات Beta لكل نوع + EWMA الزمن |
| `data/.encryption_key` | مفتاح تشفير مفاتيح API (600) |

## `GET /status`
ملخّص تشغيلي: الوضع (unlimited/guarded)، الحدود الفعلية، الأصول المدعومة، الحمل، والتخزين.

```json
{
  "mode": "unlimited",
  "free": true,
  "requires_api_key": false,
  "policy": {
    "per_ip_per_minute": 0,
    "per_key_per_minute": 0,
    "max_batch_items": 200,
    "concurrency": 4
  },
  "supported_types": ["drag", "hcaptcha", "image", "math", "point", "recaptcha_v2", "rotate", "slider", "text", "turnstile"],
  "load": { "worker_running": true, "queued": 0, "processed": 0 },
  "storage": { "jobs_in_memory": 0, "job_ttl_seconds": 3600, "max_jobs": 5000 }
}
```

## الوضع غير المحدود

افتراضيًا: `NONECAP_UNLIMITED=1` → لا 429، لا حظر، ولا مفتاح إلزامي.
للتضييق: `NONECAP_UNLIMITED=0` ثم `NONECAP_RATE_LIMIT_PER_MINUTE=...`،
`NONECAP_REQUIRE_API_KEY=1`. الجدول الكامل في [FREE_SERVER.md](FREE_SERVER.md).

## `GET /`
صفحة عامة (HTML) فيها تعريف بالخادم وحل صورة مباشر من المتصفح بلا مفتاح.
