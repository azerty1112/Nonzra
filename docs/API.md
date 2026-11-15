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
