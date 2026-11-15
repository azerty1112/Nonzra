# NoneCap Clone - إطار عمل مفتوح المصدر ومُستضاف ذاتيًا لحل الكبتشا تلقائيًا

إطار عمل متكامل ومفتوح المصدر ومُستضاف ذاتيًا لحل الكبتشا (CAPTCHA Solver)، يقابل خدمة NoneCap بأكثر من ذلك، مع دعم جميع أنواع الكبتشا الشائعة وميزات متقدمة.

## الميزات الرئيسية

| الميزة | التفاصيل |
|--------|-----------|
| **محرك حل محلي** | لا يعتمد على خدمة خارجية مدفوعة؛ يعمل بالكامل على أجهزة المستخدم |
| **سيرفر API RESTful** | نقاط نهاية للحل متزامن وغير متزامن مع دعم WebSocket للتقدم الفعلي |
| **كل أنواع الكبتشا** | صورة/نص، hCaptcha (عادي ومؤسسي)، reCAPTCHA v2/v2-invisible/v3، Cloudflare Turnstile، Drag puzzles، Point-on-image، Text، Math |
| **معالجة صور متقدمة** | تبييض، تباين، إزالة ضوضاء، تقطيع، تعديل الإمالة (deskew)، OCR عبر Tesseract |
| **التعلم العميق** | نموذج CNN لتعريف حروف الكبتشا (اختياري، عند توفر PyTorch) |
| **عميل بايثون SDK** | متزامن (`NoneCap`) وغير متزامن (`NoneCapAsync`) مع typing كامل |
| **عميل تايبسكريبت SDK** | Node.js، Bun، Deno، متصفح، مع دعم WebSocket |
| **أداة سطر أوامر (CLI)** | أمر `nonecap` للحل والفحص والإحصائيات من التيرمينال |
| **تكامل متصفح حقيقي** | Playwright لفتح متصفح والتقاط الكبتشا وحله مباشرة |
| **إضافة كروم (Manifest V3)** | كشف تلقائي وحل للكبتشا أثناء التصفح، إعدادات عبر Pop-up |
| **لوحة تحكم HTML** | `/dashboard` لمراقبة الإحصائيات والحل السريع |
| **مقاييس Prometheus** | endpoint `/metrics` لمراقبة الأداء ومعدل النجاح |
| **مفاتيح API** | حماية النقاط endpoints عبر Bearer token مع controle المعدل لكل مفتاح |
| **قاعدة بيانات** | SQLite لتخزين محاولات الحل والإحصائيات (اختيارية) |
| **قاعدة معرفة الأنماط** | تخزن الحلول الناجحة وتستفيد من التشابه لحل كبتشا مشابه فورًا |
| **محرك الخبرة** | يُقيّم مستوى ذكاء النظام (1-10) وحكمة القرارات بناءً على الخبرة المتراكمة |
| **التوسع التلقائي للعامل** | يزيد عدد العمال تلقائيًا حسب عمق طابور المهام |
| **الحل الجماعي (Bulk)** | حل عشرات الكبتشا في دفعة واحدة مع تتبع حالة كل مهمة |
| **ويب هوكس** | إرسال النتائج تلقائيًا إلى عناوين خارجية عند الانتهاء مع إعادة المحاولة |
| **واجهة ويب احترافية** | لوحة تحكم واحدة-page مع إحصائيات مباشرة، سجل حي، وإدارة المفاتيح |
| **Docker / Compose** | تشغيل مبسط عبر حاوية واحدة |
| **اختبارات و CI** | اختبارات وحدة وتكامل، سير عمل GitHub Actions |

## طبقة الذكاء المتكاملة

يحتوي المشروع على طبقة `intelligence/` تضيف أبعادًا متكاملة من الذكاء، ثم تجمعها في طبقة ذاتية تعمل دون تدخل بشري.

### 1. الذكاء التحليلي (`analysis.py`)
يحلل صورة الكبتشا قبل الحل ويحدد:
- درجة الصعوبة (0.0 سهل إلى 1.0 صعب جدًا)
- معدل النجاح المتوقع ووقت الاستجابة المقدر
- الميزات المرئية: التباين، السطوع، كثافة الحواف، الضوضاء، عدد الأحرف
- الاستراتيجية الموصى بها: `local_ocr`، `ensemble_ocr`، أو `external_service`
- نقطة النهاية: `POST /analysis/image`

### 2. الذكاء الحل (`solver_strategy.py`)
يختار أنسب استراتيجية حل بشكل تكيفي:
- `local_primary`: الحل المحلي أولًا للحالات السهلة
- `external_primary`: الخدمة الخارجية أولًا للحالات الصعبة
- `ensemble_with_fallback`: تجميع محركات متعددة ثم حل احتياطي خارجي
- يحسب عتبة الثقة المحايدة وأقصى عدد المحاولات بناءً على Schwierية التحدي

### 3. الذكاء المراقب (`monitor.py`)
يسجل كل محاولة حل ويكشف الشذوذ تلقائيًا:
- معدل النجاح، متوسط زمن الاستجابة، وتجميع الأخطاء حسب النوع
- تنبيهات ذكية (info/warning/critical) عند انخفاض معدل النجاح أو ارتفاع الكمون
- نقطة النهاية: `GET /monitor` مع تقرير وتوصية تلقائية

### 4. الذكاء التفاعلي البشري (`human_behavior.py`)
يقلد السلوك البشري لتجنب الكشف الآلي:
- تأخيرات عشوائية بين الإجراءات (كتابة، نقر، تحريك ماوس)
- حركات ماوس بمنحنى بييزيير غير خطي (تسريع ثم إبطاء)
- احتمالية التردد قبل الإجراء، واحتمالية خطأ كتابي ثم تصحيحه
- ملف سلوك قابل للتخصيص (سرعة الكتابة، عامل الاهتزاز، إلخ)

### 5. الطبقة الذاتية الكاملة (`detector.py` + `tuner.py` + `learning.py` + `orchestrator.py` + `worker.py`)

حل ذاتي من البداية للنهاية: لا تحتاج لتحديد نوع الكبتشا أو معاملات المعالجة أو متابعة المحاولات.

- **كشف تلقائي** (`detector.py`): يصنّف نوع التحدي (image / point / drag / grid) من ميزات الصورة (التشبع، المكونات، المحاذاة، نسبة الأبعاد).
- **ضبط تكيفي** (`tuner.py`): يتعلم أفضل تركيبة `psm` / `threshold` / `denoise` لكل نوع عبر سجل نجاح/ثقة/كمون.
- **تعلّم معزز** (`learning.py`): epsilon-greedy multi-armed bandit يختار أفضل استراتيجية ويقلل الاستكشاف تدريجيًا.
- **منسّق ذاتي** (`orchestrator.py`): خط أنابيب كامل: كشف ← تحليل ← قرار ← ضبط ← حل ← تقييم ← **تصعيد تلقائي** ← تعلّم ← مراقبة، مع أثر قرارات (`trace`).
- **عامل خلفي** (`worker.py`): قائمة مهام غير متزامنة بمعالجة متوازية، تُشغَّل تلقائيًا مع السيرفر.
- نقاط النهاية: `POST /auto`، `POST /auto/async`، `GET /auto/job/{id}`، `GET /auto/status`، `POST /feedback`

### 6. قاعدة معرفة الأنماط (`knowledge_base.py`)

تخزن كل حل ناجح كبصمةomorphometrics (بصمةiformية) للصور مع النص المحلول ومعدل النجاح. عند مواجهة كبتشا جديد، يُقارن بميزات الأنماط المخزنة؛ إذا وُجد تطابق عالٍ (>0.75)، يُستخدم الحل المعروف فورًا دون إعادة الحل.

- **بصمة الميزات**: تجزئة SHA-256 لخصائص الصورة (التشبع، عدد المكونات، متوسط العرض/الارتفاع، إلخ).
- **الاقتراب الذكي**: يُعطي أولوية للأنماط ذات معدل نجاح عالٍ وميزات مشابهة.
- **تحديث معدل النجاح**: كل محاولة (نجاح أو فشل) تُحدّث نسبة نجاح النمط.

### 7. محرك الخبرة (`experience_engine.py`)

يُقيّم مستوى ذكاء النظام بناءً على الخبرة المتراكمة:

- **مستوى الخبرة** (1-10): يرتفع مع عدد الحلول الناجحة (عتبات: 10, 50, 150, 400, 1000, 2500, 5000, 10000).
- **درجة الحكمة** (0-1): combined من معدل النجاح، عدد الأنماط المخزنة، ومستوى الخبرة.
- **التأكيد التلقائي**: الحلول عالية الثقة (≥0.85) تُؤكد تلقائيًا وتُضاف لقاعدة المعرفة كبيانات تدريب.
- **نقاط النهاية**: `GET /experience/stats`، `GET /experience/knowledge`، `POST /experience/find`

## هيكل المشروع

```
nonecap-clone/
├── README.md
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── install.sh
├── deploy.sh
├── .github/workflows/ci.yml
├── .gitignore
├── api_server/                 # السيرفر (FastAPI)
│   ├── __init__.py
│   ├── main.py                 # جميع نقاط النهاية + لوحة التحكم + المقاييس
│   └── requirements.txt
├── solver_engine/              # محرك الحل المحلي
│   ├── __init__.py
│   ├── base.py                 # CaptchaType, SolverResult, BaseSolver
│   ├── preprocess.py           # معالجات الصور (otsu, adaptive, denoise, deskew, segment)
│   ├── image.py                # حلّال صور نصية (Tesseract OCR)
│   ├── hcaptcha.py             # hCaptcha (محلي + خدمة خارجية)
│   ├── recaptcha.py            # reCAPTCHA v2/v3
│   ├── turnstile.py            # Cloudflare Turnstile
│   ├── drag.py                 # Drag puzzle (template matching)
│   ├── point.py                # Point-on-image (تحديد الهدف باللون)
│   ├── cnn.py                  # نموذج CNN للتعلم العميق (اختياري)
│   ├── db.py                   # قاعدة بيانات SQLite للإحصائيات (اختيارية)
│   └── registry.py             # سجل المحركات مع فولباك تلقائي
├── cli/                        # أداة سطر الأوامر
│   ├── __main__.py
│   ├── nonecap_cli.py
│   └── pyproject.toml
├── browser/                    # تكامل Playwright
│   ├── playwright_solver.py
│   └── pyproject.toml
├── intelligence/               # طبقة الذكاء المتكاملة والذاتية
│   ├── __init__.py
│   ├── monitor.py              # المراقبة الذكية واكتشاف الشذوذ
│   ├── analysis.py             # تحليل صعوبة الكبتشا وتوقع النجاح
│   ├── solver_strategy.py      # استراتيجيات الحل الذكية والتجميع
│   ├── human_behavior.py       # محاكاة السلوك البشري (ماوس، كتابة، تأخيرات)
│   ├── detector.py             # الكشف التلقائي لنوع الكبتشا
│   ├── tuner.py                # الضبط التكيفي لمعاملات المعالجة
│   ├── learning.py             # محرك التعلّم المعزز (bandit)
│   ├── orchestrator.py         # المنسّق الذاتي الكامل مع التصعيد
│   ├── worker.py               # العامل الخلفي غير المتزامن
│   ├── knowledge_base.py       # قاعدة معرفة الأنماط الناجحة
│   └── experience_engine.py    # محرك الخبرة ومستوى الذكاء
├── web/                        # واجهة الويب الاحترافية
│   ├── templates/
│   │   └── dashboard.html      # لوحة تحكم واحدة-page
│   └── static/
│       ├── css/dashboard.css   # أنماط التصميم
│       └── js/dashboard.js     # تفاعل الواجهة مع API
├── clients/
│   ├── python/nonecap/         # عميل بايثون (client.py, async_client.py)
│   └── typescript/src/         # عميل تايبسكريبت (client.ts)
├── extension/                  # إضافة كروم (Manifest V3)
│   ├── manifest.json
│   ├── content.js
│   ├── background.js
│   ├── popup.html
│   └── popup.js
├── tests/
│   ├── test_solver.py          # اختبارات محرك الحل (9 اختبارات)
│   ├── test_api.py             # اختبارات تكامل للسيرفر (4 اختبارات)
│   ├── test_autonomous.py      # اختبارات الطبقة الذاتية (18 اختبارًا)
│   └── conftest.py (تلقائي)
└── docs/
    └── API.md
```

## التثبيت والتشغيل السريع

### باستخدام بايثون مباشرة
```bash
cd nonecap-clone
pip install -r api_server/requirements.txt
uvicorn api_server.main:app --reload --host 0.0.0.0 --port 8000
```

### باستخدام السكريبت المساعد
```bash
chmod +x install.sh
./install.sh
```

### باستخدام دوكير كومبوز
```bash
chmod +x deploy.sh
./deploy.sh
# السيرفر على http://localhost:8000
# لوحة التحكم: http://localhost:8000/dashboard
# المقاييس: http://localhost:8000/metrics
```

## نقاط نهاية API

| الطريقة | المسار | الوصف |
|--------|--------|-------|
| GET | `/health` | فحص حالة السيرفر |
| GET | `/stats` | إحصائيات المحاولات ومعدل النجاح |
| GET | `/metrics` | مقاييس Prometheus |
| GET | `/dashboard` | لوحة تحكم HTML |
| GET | `/monitor` | تقرير المراقبة الذكية والتنبيهات |
| POST | `/analysis/image` | تحليل صورة كبتشا قبل الحل |
| POST | `/solve/{type}` | حل متزامن (أنواع: image, hcaptcha, recaptcha_v2, recaptcha_v3, turnstile, drag, point) |
| POST | `/solve/async/{type}` | إرسال مهمة غير متزامنة (تُرجع job_id) |
| GET | `/job/{job_id}` | استعلام عن نتيجة مهمة غير متزامنة |
| WS | `/ws/job/{job_id}` | متابعة التقدم الفعلي عبر WebSocket |
| POST | `/auto` | **حل ذاتي كامل**: كشف تلقائي + ضبط + تصعيد + تعلّم |
| POST | `/auto/async` | إرسال مهمة للعامل الخلفي الذاتي (تُرجع job_id) |
| GET | `/auto/job/{job_id}` | استعلام عن مهمة العامل الذاتي |
| GET | `/auto/status` | حالة العامل والتعلّم والضبط والمراقبة |
| POST | `/feedback` | تغذية تعلّم خارجية لتحسين القرارات |
| POST | `/api/keys` | إنشاء مفتاح API جديد |
| GET | `/api/keys` | قائمة مفاتيح API |
| DELETE | `/api/keys/{key_id}` | إلغاء مفتاح API |
| POST | `/bulk/auto` | حل جماعي لدفعات من الكبتشا |
| GET | `/bulk/{bulk_id}` | حالة مهمة حل جماعي |
| GET | `/self-improve/stats` | إحصائيات التعلم الذاتي |
| POST | `/self-improve/confirm/{id}` | تأكيد عينة للتدريب الذاتي |
| POST | `/self-improve/retrain` | إعادة تدريب النموذج الذاتي |
| GET | `/experience/stats` | إحصائيات خبرة النظام ومستوى الذكاء |
| GET | `/experience/knowledge` | إحصائيات قاعدة المعرفة |
| POST | `/experience/find` | البحث عن حل معروف لنمط مشابه |
| GET | `/web` | لوحة التحكم الاحترافية (واجهة ويب) |

### مثال الحل الذاتي الكامل (بدون تحديد النوع)
```bash
curl -X POST http://localhost:8000/auto \
  -F "file=@captcha.png" \
  -F "human_like=true" \
  -F "max_escalations=2"
```

### مثال إرسال مهمة ذاتية غير متزامنة
```bash
curl -X POST http://localhost:8000/auto/async -F "file=@captcha.png"
# {"job_id":"...","status":"queued",...}
curl http://localhost:8000/auto/job/<job_id>
```

### مثال استدعاء حل صورة
```bash
curl -X POST http://localhost:8000/solve/image \
  -F "file=@captcha.png" \
  -F "psm=7" -F "preprocess=true"
```

### مثال استدعاء hCaptcha
```bash
curl -X POST http://localhost:8000/solve/hcaptcha \
  -H "Content-Type: application/json" \
  -d '{"sitekey":"10000000-ffff-ffff-ffff-000000000001","url":"https://example.com"}'
```

## الاستخدام عبر عميل بايثون

```python
from nonecap_client import NoneCap

nc = NoneCap(base_url="http://localhost:8000")

# حل صورة كبتشا
result = nc.solve_image(image_path="captcha.png")
print("النص:", result.text)

# حل hCaptcha
result = nc.solve_hcaptcha(
    sitekey="...",
    url="https://example.com",
)
print("التوكن:", result.token)

# حل reCAPTCHA v2
result = nc.solve_recaptcha(sitekey="...", url="https://example.com")

# حل Turnstile
result = nc.solve_turnstile(sitekey="...", url="https://example.com")

# حل Drag puzzle (يلزم صورة اللغز وصورة القالب)
result = nc.solve_drag(image_path="drag.png", template_path="template.png")
print("الإحداثيات:", result.text)  # "x,y"

# حل Point-on-image
result = nc.solve_point(image_path="point.png", target_color="red")
print("الإحداثيات:", result.text)

# الحل الذاتي الكامل: كشف النوع تلقائيًا + ضبط + تصعيد + تعلّم
auto = nc.auto(image_path="captcha.png", human_like=True)
print("النوع المكتشف:", auto.detected_type, "الثقة:", auto.detection_confidence)
print("الاستراتيجية:", auto.strategy_used, "التصعيدات:", auto.escalations)
print("النص:", auto.result.text)
print("أثر القرارات:", auto.trace)

# مهمة ذاتية في الخلفية
job_id = nc.auto_submit(image_path="captcha.png")
print(nc.auto_job(job_id))

# حالة العامل والتعلّم والضبط
print(nc.auto_status())

# تغذية تعلّم خارجية
nc.feedback("local_primary", success=True, confidence=0.92, captcha_type="image")

# مهمة غير متزامنة
job_id = nc.solve_async_submit("image", image_path="captcha.png")
result = nc.job_status(job_id)

# الإحصائيات
print(nc.stats())

# غير متزامن (asyncio)
from nonecap_client import NoneCapAsync
async def main():
    async with NoneCapAsync() as nc:
        result = await nc.solve_image(image_bytes=b"...")
```

## الاستخدام عبر أداة سطر الأوامر (CLI)

```bash
# فحص الحالة
nonecap health

# الإحصائيات
nonecap stats

# حل صورة
nonecap solve --type image --image captcha.png

# حل hCaptcha
nonecap solve --type hcaptcha --sitekey "..." --url "https://example.com"

# إرسال مهمة غير متزامنة
nonecap async --type image --image captcha.png

# استعلام عن مهمة
nonecap job <job_id>

# حل ذاتي كامل (كشف تلقائي للنوع)
nonecap auto --image captcha.png --human-like

# إرسال مهمة ذاتية للعامل الخلفي
nonecap auto-async --image captcha.png

# استعلام عن مهمة ذاتية
nonecap auto-job <job_id>

# حالة العامل والتعلّم والضبط
nonecap auto-status
```

## الاستخدام عبر عميل تايبسكريبت

```ts
import { NoneCap } from "nonecap-client";

const nc = new NoneCap({ baseUrl: "http://localhost:8000" });

const result = await nc.solveImage(file);
console.log(result.text);

const token = await nc.solveHCaptcha(sitekey, url);
console.log(token.token);

// الحل الذاتي الكامل: كشف تلقائي + ضبط + تصعيد + تعلّم
const auto = await nc.auto({ human_like: true }, file);
console.log(auto.detected_type, auto.strategy_used, auto.trace);
console.log(auto.result.text);

// مهمة ذاتية غير متزامنة
const jobId = await nc.autoSubmit({}, file);
console.log(await nc.autoJobStatus(jobId));
console.log(await nc.autoStatus());

// متابعة مهمة عبر WebSocket
nc.subscribeJob(jobId, (r) => console.log(r));
```

## إضافة كروم للمتصفح

1. افتح `chrome://extensions`
2- فعّل "Developer mode"
3- انقر "Load unpacked" واختر مجلد `extension/`
4- أضف رابط السيرفر في الإعدادات (افتراضياً `http://localhost:8000`)
5- فعّل الحل التلقائي من الـ Pop-up

## متطلبات النظام

- Python 3.9+
- Tesseract OCR (للحل النصي)
- OpenCV, Pillow, NumPy, pytesseract
- FastAPI, Uvicorn, httpx, pydantic
- اختيارياً: sqlalchemy, slowapi, prometheus-client, torch, playwright

## الترخيص

MIT License - للاستخدام المصرح به في الاختبار، المراقبة، والأتمتة الخاصة بك فقط. يُحظر استخدامه للتحايل على أنظمة الغير دون إذن صريح.

## المساهمة

مساهماتكم مرحب بها! يرجى فتح Issue أو Pull Request.

```bash
# تشغيل الاختبارات
pytest tests/ -v

# فحص الأنواع
mypy solver_engine/ api_server/ clients/python/nonecap/
```
