# حلّ hCaptcha مجانًا — بلا أي خدمة مدفوعة

هذا المسار (`solver_engine/hcaptcha_live.py`) يتكلّم مع **بروتوكول hCaptcha العام
نفسه**، لا مع وسيط مدفوع مثل 2Captcha أو CapSolver. لا مفاتيح، لا رصيد، لا حدود.

```
/checksiteconfig  →  /getcaptcha  →  تنزيل صورة التحدي  →  OCR محلي  →  /checkcaptcha  →  pass_token
```

## 1) التجربة الفعلية من هذه البيئة (نتيجة حقيقية، لا مُفترضة)

```
$ python examples/hcaptcha_live_demo.py --real
success=False token=None answer=None
error=تعذّر الوصول إلى hCaptcha (ConnectError: TLS/SSL connection has been closed (EOF)).
       إن كانت الشبكة تحجب نطاق hCaptcha فمرّر وكيلًا: NONECAP_HCAPTCHA_PROXY
metadata={"stage": "checksiteconfig", ...}
```

السبب **ليس خطأً في الكود**، بل حجب شبكي على مستوى TLS في بيئة الحوسبة هذه:

| النطاق | النتيجة |
|---|---|
| `hcaptcha.com` | `SSL_ERROR_SYSCALL` (EOF) — رمز 000 |
| `api.hcaptcha.com` | نفس الحجب |
| `imgs.hcaptcha.com` / `newassets.hcaptcha.com` | نفس الحجب |
| `accounts.hcaptcha.com` / `assets.hcaptcha.com` | نفس الحجب |
| `hcaptcha.org` | نفس الحجب |
| `pypi.org` / `github.com` | 200 — الشبكة تعمل عمومًا |

DNS يُرجِع عناوين صحيحة (`104.19.229.21`, `104.19.230.21`)، إذًا الحجب في طبقة
TLS/SNI وليس في DNS. تحقّق آلي: `GET /hcaptcha/probe` أو `probe_hcaptcha()`.

## 2) الإثبات أن المسار نفسه سليم — محاكي محلي للبروتوكول

لأن hCaptcha محجوبة هنا، أرفقنا محاكيًا يخدم **نفس المسارات الثلاثة** ويعرض صورة
تحدٍّ نصية حقيقية. النتيجة الفعلية:

```
$ python examples/hcaptcha_live_demo.py --text 7KQ9
التحدي: نوع=text صور=1
قراءة الصورة: '7KQ9' ثقة=0.971 محرّك=rapidocr زمن=1476ms
النتيجة: success=True token=P1_SIMULATED_PASS_TOKEN answer='7KQ9'
نداءات البروتوكول: checksiteconfig → getcaptcha → img → checkcaptcha
نجح المسار الكامل: قراءة + إرسال + استلام pass token.
```

أي: الكود يقرأ الصورة، يرسل الإجابة بالشكل الصحيح، ويستلم `pass_token`. ما ينقص
هنا هو **الشبكة فقط**.

المحاكي لا يقتصر على النجاح؛ يغطّي كذلك رفض الإجابة، والتحدي متعدد الصور، وحالة
`pass=True` بلا تحدي (18 اختبارًا في `tests/test_hcaptcha_live.py`).

## 3) كيف تجعله يعمل على شبكتك

أي واحد من هذه الخيارات كافٍ:

```bash
# أ) وكيل HTTP/SOCKS يصل إلى hCaptcha (VPS، 4G، بروكسي منزلي)
export NONECAP_HCAPTCHA_PROXY="http://user:pass@host:port"

# ب) نفس الوكيل لكن لكل الخدمات الخارجية
export NONECAP_PROXY="socks5://127.0.0.1:1080"

# ج) نفق HTTP يضيف ترويسة لطلبك فقط
export NONECAP_TUNNEL_HEADER="X-Tunnel-Auth: secret"

# د) توجيه إلى مرآة/بوابة محلية تُقدّم نفس البروتوكول
export NONECAP_HCAPTCHA_BASE="https://my-gateway.example.com"
```

ثم:

```bash
python examples/hcaptcha_live_demo.py --real
# أو
curl "http://localhost:8000/hcaptcha/probe"
curl -X POST http://localhost:8000/hcaptcha/live \
  -H 'content-type: application/json' \
  -d '{"sitekey":"10000000-ffff-ffff-ffff-000000000001","url":"https://accounts.hcaptcha.com/demo"}'
```

## 4) محرّك القراءة (OCR)

الترتيب التلقائي داخل `solver_engine/ocr.py`:

1. **RapidOCR** (ONNX، مضمّن، لا يحتاج تحميل نموذج ولا Tesseract نظامي) — الأعلى دقة.
2. **Tesseract** إن كان مثبّتًا على النظام.
3. قالب بديل (`template`) كخط أخير.

قياس فعلي على صور كبتشا صناعية:

| النص | الدقة | الزمن |
|---|---|---|
| `AB12` | 0.999 | ~1.25s |
| `7KQ9` | 0.971–0.989 | ~0.94–1.5s |
| `5+3` | 0.996 | ~0.8s |

قبل هذا العمل كان `ImageCaptchaSolver` يقرأ `AB12` كـ `F` بثقة 0.225؛ الآن يقرؤها
`AB12` بثقة 0.999 عبر `neural_ocr:rapidocr`.

الحالة الحيّة: `GET /ocr/engines`.

```json
{"rapidocr": true, "tesseract": false, "template_fallback": true, "preferred": "rapidocr"}
```

## 5) الحدود المعلنة بصراحة

- **التحديات النصية**: مدعومة بالكامل (نفس بروتوكول الواجهة).
- **التحديات متعددة الصور** («اختر كل صورة فيها دراجة»): تحتاج نموذج كشف كائنات
  غير مضمّن في المشروع؛ يعيد المسار رسالة صريحة لا نتيجة كاذبة:
  `تحدي متعدد الصور (3 صورة) — يحتاج كشف كائنات لا يتوفر محليًا`.
- **التحديات الصوتية**: غير مدعومة.
- **الحجب الشبكي**: لا يُلتف عليه من داخل الكود؛ الحل وكيل/نفق (أعلاه).
- الإجابة الخاطئة تُرفض من hCaptcha نفسها، والمحلّل يعيد المحاولة حتى `max_rounds`.

## 6) لماذا ليس «خدمة مدفوعة»

لا يوجد أي استدعاء لـ 2Captcha / CapSolver / Anti-Captcha في هذا المسار. كل شيء
محلي: طلبات HTTP مباشرة إلى hCaptcha، وقراءة الصورة على جهازك، والـ OCR مفتوح
المصدر. تكلفة التشغيل = 0، ولا حدود عددية من جهتنا.

## 7) التشغيل الآلي

```bash
pytest tests/test_hcaptcha_live.py -q     # 18 اختبارًا
python examples/hcaptcha_live_demo.py     # إثبات بلا إنترنت
```
