"""ذخيرة معرفية موسّعة: معلومات وتقنيات ومصائد لكل نوع كبتشا.

تُستخدم هذه الذخيرة في:
- شرح قرار العقل («لماذا هذا المسار؟») بلغة مفهومة.
- توليد أسئلة تدريب (كويز) لتقييم المعرفة قبل الحل.
- عرض بطاقات معلومات في لوحة التحكم.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class KnowledgeCard:
    """بطاقة معرفة عن نوع كبتشا أو تقنية."""

    key: str
    title: str
    category: str  # type / technique / risk / benchmark
    summary: str
    facts: List[str] = field(default_factory=list)
    pitfalls: List[str] = field(default_factory=list)
    related: List[str] = field(default_factory=list)
    difficulty: float = 0.5  # 0.0 سهل → 1.0 صعب

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "category": self.category,
            "summary": self.summary,
            "facts": self.facts,
            "pitfalls": self.pitfalls,
            "related": self.related,
            "difficulty": round(self.difficulty, 2),
        }


CARDS: List[KnowledgeCard] = [
    KnowledgeCard(
        key="image_text",
        title="كبتشا الصور النصية",
        category="type",
        summary=(
            "أقدم أنواع الكبتشا وأكثرها انتشارًا: أحرف/أرقام مشوّشة داخل صورة. "
            "تُحل عبر OCR بعد معالجة مسبقة، أو بشبكة عصبية عند التشويش العالي."
        ),
        facts=[
            "Tesseract يعمل أفضل مع psm 7 (سطر واحد) وpsm 8 (كلمة واحدة).",
            "عتبة Otsu مناسبة للخلفيات أحادية اللون، وAdaptive أفضل مع التدرّجات.",
            "إزالة الضوضاء قبل التقطيع ترفع دقة تقسيم الحروف بنسبة ملحوظة.",
            "تغيير مقاس الصورة إلى عرض ~400px يُحسّن OCR دون فقدان التفاصيل.",
        ],
        pitfalls=[
            "قصّ الصورة عند الحدود يدمج أول حرف بالأخير عند التقطيع.",
            "الاعتماد على ثقة OCR الخام دون معايرة يعني قبول إجابات خاطئة بثقة عالية.",
        ],
        related=["preprocessing", "cnn", "calibration"],
        difficulty=0.25,
    ),
    KnowledgeCard(
        key="math",
        title="كبتشا العمليات الحسابية",
        category="type",
        summary=(
            "تعبير رياضي مثل 5 + 3 يُطلب ناتجه. الحل الصحيح = قراءة صحيحة + حساب صحيح؛ "
            "خطأ في أحدهما يُفسد النتيجة كاملة."
        ),
        facts=[
            "تطبيع الرموز (× ÷ −) إلى عوامل قياسية يمنع أخطاء القراءة الشائعة.",
            "الخلط بين O/0 وl/1 وS/5 وB/8 هو أكثر أخطاء OCR شيوعًا هنا.",
            "الحساب يجب أن يكون بلا eval: تحليل AST يمنع تنفيذ أي كود.",
            "القسمة على صفر أو أُس كبير يجب رفضهما لا محاولة حلّهما.",
        ],
        pitfalls=[
            "تمرير النص الخام إلى eval أو eval-like: ثغرة تنفيذ كود مباشرة.",
            "إرجاع التعبير بدل ناتجه (5+3 بدل 8) يسبب رفضًا من الموقع.",
        ],
        related=["image_text", "preprocessing"],
        difficulty=0.3,
    ),
    KnowledgeCard(
        key="slider",
        title="ألغاز الفجوة المنزلقة (Slider)",
        category="type",
        summary=(
            "قطعة يجب سحبها إلى فجوة في صورة خلفية. المطلوب إحداثي x للفجوة، "
            "وغالبًا ألغاز معقدة تضيف مسارًا منحنيًا أو قطعًا متعددة."
        ),
        facts=[
            "المطابقة بالقالب مع CCOEFF_NORMED تعمل جيدًا إذا كانت القطعة مشتقة من الصورة.",
            "المطابقة بالحواف (Canny) أكثر مقاومة لاختلاف الإضاءة بين القطعة والفجوة.",
            "كشف الحواف العمودية القوية بديل عند غياب القالب.",
            "الفجوة عادة مظلّلة بنسبة 40-60% من سطوع الخلفية الأصلي.",
        ],
        pitfalls=[
            "قالب موحّد اللون يجعل CCOEFF_NORMED يعطي درجة عشوائية عالية.",
            "العودة للإحداثي صفر عند الفشل أسوأ من إعلان الفشل صراحةً.",
        ],
        related=["image_text", "drag"],
        difficulty=0.45,
    ),
    KnowledgeCard(
        key="rotate",
        title="كبتشا التدوير",
        category="type",
        summary="صورة مائلة يجب تدويرها إلى الوضع الصحيح. المخرَج زاوية بالدرجات.",
        facts=[
            "تباين المسقط الأفقي يبلغ أقصاه عندما يكون النص أفقيًا.",
            "بحث خشن بخطوة 5° ثم تنقيح بخطوة 1° يوازن الدقة والزمن.",
            "مع قالب أصلي، دوران القالب ومطابقته يعطي الزاوية مباشرة.",
            "الفرق بين angle (الدوران الحالي) وcorrection (التصحيح) يجب أن يكون واضحًا.",
        ],
        pitfalls=[
            "إرجاع زاوية التصحيح بدل زاوية الدوران (أو العكس) يقلب النتيجة.",
            "الاعتماد على 5° فقط يجعل الخطأ أكبر من الحد المسموح في كثير من المواقع.",
        ],
        related=["image_text", "slider"],
        difficulty=0.4,
    ),
    KnowledgeCard(
        key="drag",
        title="ألغاز السحب والترتيب",
        category="type",
        summary="سحب عناصر إلى مواقعها أو ترتيب صور/حروف بترتيب معيّن.",
        facts=[
            "قالب العنصر + مطابقة على الخلفية يعطي الموقع المستهدف.",
            "التسلسل غالبًا منطقي (ترتيب زمني/حجمي) لا عشوائي.",
            "في الألغاز متعددة الخطوات، تُقيّم كل خطوة على حدة قبل الإرسال.",
        ],
        pitfalls=[
            "افتراض ترتيب من اليسار لليمين دائمًا يخالف المواقع التي تُطلب فيها تنازليًا.",
        ],
        related=["slider", "point"],
        difficulty=0.55,
    ),
    KnowledgeCard(
        key="point",
        title="اختر النقطة (Point-on-image)",
        category="type",
        summary="النقر على كائن محدد («اضغط على الدراجة»). يعتمد على كشف كائنات.",
        facts=[
            "فلترة الألوان في HSV تفيد عندما يُوصف الهدف بلون.",
            "مساحة الكونتور + مركز الكتلة يعطيان نقطة نقر معقولة.",
            "مواقع كبرى تستخدم نماذج كشف كائنات، والحل يحتاج بيانات تدريب.",
        ],
        pitfalls=[
            "اختيار أكبر كونتور لا يعني الهدف الصحيح؛ قد تكون خلفية كبيرة.",
        ],
        related=["drag", "cnn"],
        difficulty=0.6,
    ),
    KnowledgeCard(
        key="hcaptcha",
        title="hCaptcha",
        category="type",
        summary=(
            "كبتشا تحدي متعدد الصور («اختر كل ما يحتوي على...»). يعتمد على سمعة الجلسة "
            "والتفاعل البشري، ويصعب حلّه محليًا بلا نماذج رؤية."
        ),
        facts=[
            "التوكن الناتج صالح لفترة قصيرة (دقائق) ويُستهلك مرة واحدة.",
            "التحدي قد يتغير من صورة إلى أخرى في الجلسة نفسها.",
            "جودة الوكيل (proxy) والبصمة (fingerprint) تؤثر على صعوبة التحدي أكثر من الحل نفسه.",
            "الوضع المؤسسي (Enterprise) يضيف تحققًا من الجهة المستضيفة.",
        ],
        pitfalls=[
            "إعادة استخدام التوكن = رفض فوري.",
            "السلوك الآلي المكشوف يرفع الصعوبة تدريجيًا في الجلسة نفسها.",
        ],
        related=["human_behavior", "turnstile", "external_services"],
        difficulty=0.8,
    ),
    KnowledgeCard(
        key="recaptcha",
        title="reCAPTCHA v2 / v3",
        category="type",
        summary=(
            "v2 يعرض تحدّي صور عند الشك، وv3 يعطي درجة 0.0-1.0 دون تفاعل. "
            "الدرجة تُحسب من سلوك الجلسة لا من إجابة واحدة."
        ),
        facts=[
            "v2-invisible يشبه v2 لكن التحدي يظهر فقط عند الشك.",
            "v3 يحتاج إرسال التوكن مع الطلب الأصلي، والموقع يقرر قبوله من الدرجة.",
            "الدرجة المنخفضة تُعالج بتحسين السلوك لا بإعادة المحاولة العمياء.",
        ],
        pitfalls=[
            "محاولة حلّ v3 كأنه v2: v3 قد لا يعرض أي تحدٍّ أصلًا.",
            "مفاتيح الموقع (sitekey) العامة لا تعني صلاحية حل دائمة.",
        ],
        related=["human_behavior", "hcaptcha"],
        difficulty=0.75,
    ),
    KnowledgeCard(
        key="turnstile",
        title="Cloudflare Turnstile",
        category="type",
        summary=(
            "كبتشا غير مرئية تهدف لأن تكون «صامتة»: لا تحدي في الحالات الطبيعية. "
            "تعتمد على إشارات المتصفح والشبكة."
        ),
        facts=[
            "قد تمر دون أي تدخل إذا كانت الجلسة تبدو طبيعية.",
            "التوكن صالح لمرة واحدة ومرتبط بالمفتاح والموقع.",
            "التنفيذ داخل متصفح حقيقي غالبًا أنجح من محاولة استدعاء الواجهة يدويًا.",
        ],
        pitfalls=[
            "استدعاء الواجهة برمجيًا بلا سياق متصفح يعطي رفضًا شبه دائم.",
        ],
        related=["human_behavior", "browser"],
        difficulty=0.7,
    ),
    KnowledgeCard(
        key="funcaptcha",
        title="FunCaptcha (Arkose)",
        category="type",
        summary="ألغاز ثلاثية الأبعاد وتدوير كائنات ومطابقة أنماط، بتحديات متعددة الخطوات.",
        facts=[
            "كل خطوة تُقيَّم منفصلة؛ خطأ واحد يبطل الجلسة كلها.",
            "الزمن بين الخطوات يُحتسب كإشارة سلوكية.",
        ],
        pitfalls=["التسريع الشديد بين الخطوات يُصنّف آليًا."],
        related=["point", "human_behavior"],
        difficulty=0.85,
    ),
    KnowledgeCard(
        key="geetest",
        title="GeeTest",
        category="type",
        summary="شائع في المواقع الصينية: لغز سلايدر ثم تحقق سلوكي إضافي.",
        facts=[
            "قد يُطلب مسار سحب غير خطّي (انحناء) لا مجرد إحداثي.",
            "بعد السلايدر يُطلب توكن تحقق ثانٍ في كثير من الإصدارات.",
        ],
        pitfalls=["سحب خط مستقيم بسرعة ثابتة يُكشف بسهولة."],
        related=["slider", "human_behavior"],
        difficulty=0.75,
    ),
    KnowledgeCard(
        key="preprocessing",
        title="المعالجة المسبقة للصور",
        category="technique",
        summary=(
            "أهم عامل في تحسين دقة OCR: تحويل رمادي، إزالة ضوضاء، عتبة، تقطيع، "
            "وتصحيح إمالة — بترتيب مدروس."
        ),
        facts=[
            "Median Blur (3x3) يزيل الضوضاء النقطية دون إذابة الحروف.",
            "Otsu يفترض توزيعًا ثنائيًا للسطوع؛ مع إضاءة متغيّرة استخدم Adaptive.",
            "التقطيع يعتمد على الكونتورات: احذف الصغيرة (<5px) والكبيرة جدًا.",
            "تصحيح الإمالة (deskew) يحسّن OCR عندما تكون الصورة مائلة >5°.",
        ],
        pitfalls=[
            "ترتيب خاطئ: عتبة قبل إزالة الضوضاء تُثبّت الضوضاء في الصورة.",
            "تكبير مفرط يُنتج حواف مسننة تُربك Tesseract.",
        ],
        related=["image_text", "cnn"],
        difficulty=0.35,
    ),
    KnowledgeCard(
        key="cnn",
        title="الشبكات العصبية لقراءة الحروف",
        category="technique",
        summary=(
            "عندما يفشل OCR التقليدي، يدخل CNN: يتعلم الحروف من صور مُسمّاة، "
            "ويصبح أفضل من Tesseract مع التشويش المتسق."
        ),
        facts=[
            "تحتاج مئات العينات لكل نمط كبتشا لتحقيق نتيجة معتبرة.",
            "البيانات الصناعية (مولّد محلي) تفيد في مرحلة الإقلاع قبل جمع الحقيقية.",
            "زيادة البيانات (تدوير/ضجيج/تحجيم) تحسّن التعميم بشكل كبير.",
            "ابدأ بمشكلة تصنيف حروف مفردة بعد التقطيع، لا كلمة كاملة.",
        ],
        pitfalls=[
            "التدريب على نوع واحد ثم استخدامه على نوع آخر بنفس الثقة.",
            "الإفراط في التدريب على بيانات صناعية يجعل النموذج ينهار على صور حقيقية.",
        ],
        related=["preprocessing", "synthetic", "calibration"],
        difficulty=0.6,
    ),
    KnowledgeCard(
        key="calibration",
        title="معايرة الثقة",
        category="technique",
        summary=(
            "الثقة التي يُرجعها المحرّك ليست احتمال نجاح. المعايرة تُصلح هذه الفجوة "
            "بتعلّم العلاقة الحقيقية من النتائج (isotonic / PAVA)."
        ),
        facts=[
            "Brier Score يقيس دقة الاحتمالات: أقل = أفضل.",
            "الانكماش نحو المعدل الأساسي يحمي من الثقة الزائفة في البداية.",
            "قرار «أقبل أم أعيد؟» يُبنى على طاقة متوقعة لا على عتبة ثابتة.",
            "المعايرة تحتاج بيانات من نفس التوزيع؛ تغيير النوع يُبطلها مؤقتًا.",
        ],
        pitfalls=[
            "استخدام ثقة نموذج غير مُعاير لاتخاذ قرارات تشغيلية حساسة.",
            "معايرة نموذج على بيانات صناعية ثم تطبيقه على الحقيقية بلا إعادة معايرة.",
        ],
        related=["cnn", "image_text"],
        difficulty=0.55,
    ),
    KnowledgeCard(
        key="human_behavior",
        title="محاكاة السلوك البشري",
        category="technique",
        summary=(
            "الحركة والزمن جزء من الكبتشا الحديثة: نقرات فورية أو سحب بسرعة ثابتة "
            "إشارات آلية قوية."
        ),
        facts=[
            "منحنى بيزيير مع تسريع ثم إبطاء يشبه حركة اليد.",
            "تأخيرات قصيرة غير منتظمة بين الإجراءات تكسر الأنماط الجامدة.",
            "الملاحة داخل الصفحة قبل التحدي تُحسّن السمعة السلوكية.",
            "التنويع أهم من الكمال: النمط المثالي المتكرر نفسه يصبح بصمة.",
        ],
        pitfalls=[
            "تطبيق «سلوك بشري» بمعاملات ثابتة في كل جلسة.",
            "حركة سريعة جدًا أو خطّية تمامًا.",
        ],
        related=["hcaptcha", "geetest", "turnstile"],
        difficulty=0.4,
    ),
    KnowledgeCard(
        key="external_services",
        title="الخدمات الخارجية كاحتياط",
        category="technique",
        summary=(
            "عندما يتجاوز النوع قدرة المحرّك المحلي، يُستخدم مسار خارجي — لكن "
            "القرار يجب أن يكون اقتصاديًا: تكلفة، زمن، وثقة."
        ),
        facts=[
            "سلسلة خدمات متعددة مع إعادة محاولة ترفع النجاح ظاهريًا لكن تطيل الزمن.",
            "التخزين المؤقت للحلول المتكررة يوفّر التكلفة بشكل كبير.",
            "الأولوية: محلي → تجميع → خارجي، ما لم تُثبت البيانات العكس.",
        ],
        pitfalls=[
            "الاعتماد الكامل على خدمة خارجية يجعل التوقف الكلي عند تعطّلها.",
            "إعادة المحاولة بلا سقف تُحوّل خطأً عابرًا إلى عاصفة طلبات.",
        ],
        related=["hcaptcha", "recaptcha"],
        difficulty=0.5,
    ),
    KnowledgeCard(
        key="risk",
        title="المخاطر والاستخدام المسؤول",
        category="risk",
        summary=(
            "حلّ الكبتشا يمسّ شروط استخدام المواقع والخصوصية. الاستخدام المسؤول "
            "يعني: اختبار أنظمتك، أو بياناتك، أو ما لديك إذن صريح به."
        ),
        facts=[
            "تجاوز حماية موقع بلا إذن قد يخالف الشروط والقصور المحلية.",
            "تخزين حلول الكبتشا قد يُسجّل بيانات شخصية؛ شفّرها وقيّد الوصول.",
            "مفاتيح API في قاعدة البيانات يجب أن تكون مشفّرة بمفتاح ثابت.",
        ],
        pitfalls=[
            "تسريب مفاتيح في التوثيق أو السجلات.",
            "تخزين صور كبتشا حقيقية بلا حدّ زمني أو تشفير.",
        ],
        related=["calibration"],
        difficulty=0.2,
    ),
]


CORPUS: Dict[str, KnowledgeCard] = {card.key: card for card in CARDS}


def get_card(key: str) -> Optional[KnowledgeCard]:
    return CORPUS.get(key)


def cards_for_type(captcha_type: str) -> List[KnowledgeCard]:
    """بطاقات مرتبطة بنوع كبتشا معيّن (يشمل التقنيات ذات الصلة)."""
    type_keys = {
        "image": "image_text",
        "text": "image_text",
        "math": "math",
        "slider": "slider",
        "rotate": "rotate",
        "drag": "drag",
        "point": "point",
        "hcaptcha": "hcaptcha",
        "hcaptcha_enterprise": "hcaptcha",
        "recaptcha_v2": "recaptcha",
        "recaptcha_v2_invisible": "recaptcha",
        "recaptcha_v3": "recaptcha",
        "turnstile": "turnstile",
        "funcaptcha": "funcaptcha",
        "geetest": "geetest",
    }
    primary = CORPUS.get(type_keys.get(captcha_type, "image_text"))
    if primary is None:
        return []
    related = [CORPUS[k] for k in primary.related if k in CORPUS]
    return [primary] + related


def brief_for(captcha_type: str, limit: int = 2) -> List[str]:
    """جُمل قصيرة تُعرض في شرح القرار أو في اللوحة."""
    out: List[str] = []
    for card in cards_for_type(captcha_type)[:limit]:
        out.append(f"{card.title}: {card.summary}")
    return out


def catalog(category: Optional[str] = None) -> List[Dict[str, Any]]:
    cards = CARDS if category is None else [c for c in CARDS if c.category == category]
    return [c.to_dict() for c in cards]


def quiz(limit: int = 5, seed: Optional[int] = None) -> List[Dict[str, Any]]:
    """يولّد أسئلة تدريب من الذخيرة (سؤال + خيارات + الجواب الصحيح)."""
    import random

    rng = random.Random(seed)
    items: List[Dict[str, Any]] = []
    pool = list(CARDS)
    rng.shuffle(pool)
    titles = {c.key: c.title for c in CARDS}

    for card in pool:
        if len(items) >= limit:
            break
        if not card.facts:
            continue
        correct = rng.choice(card.facts)
        distractors_pool = [f for c in CARDS for f in c.facts if f != correct]
        rng.shuffle(distractors_pool)
        options = distractors_pool[:3] + [correct]
        rng.shuffle(options)
        items.append(
            {
                "card": card.key,
                "subject": titles[card.key],
                "question": f"ما الحقيقة الصحيحة بخصوص «{card.title}»؟",
                "options": options,
                "answer_index": options.index(correct),
                "explanation": card.summary,
            }
        )
    return items


__all__ = [
    "KnowledgeCard",
    "CARDS",
    "CORPUS",
    "get_card",
    "cards_for_type",
    "brief_for",
    "catalog",
    "quiz",
]
