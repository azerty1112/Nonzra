#!/usr/bin/env python3
"""
عرض توضيحي لاختبار حل hCaptcha مع خدمة nindiad الخارجية.
هذا السكريبت يُظهر كيفية استخدام النظام لحل hCaptcha مع إعادة المحاولة التلقائية.
"""

import json
import time
from intelligence.orchestrator import AutoOrchestrator
from solver_engine.registry import registry, configure_hcaptcha_external
from solver_engine.base import CaptchaType


def demo_hcaptcha_with_nindiad():
    """
    عرض توضيحي لحل hCaptcha مع خدمة nindiad الخارجية.
    
    ملاحظة: هذا العرض يستخدم محاكاة (mock) للخدمة الخارجية لأننا لا نملك
    مفاتيح nindiad حقيقية. في البيئة reales، استبدلوا بمفاتيحكم الفعلية.
    """
    print("=" * 70)
    print("عرض توضيحي: حل hCaptcha مع خدمة nindiad الخارجية")
    print("=" * 70)
    
    # 1. ضبط خدمة nindiad الخارجية مع إعادة المحاولة التلقائية
    print("\n[1] ضبط خدمة nindiad الخارجية...")
    configure_hcaptcha_external(
        api_key="مفتاح_nindiad_خاص_بك_هنا",
        external_api="https://api.nindiad.com",
        external_api_type="nindiad",
        max_retries=10,       # حتى 10 محاولات
        retry_delay=5.0,      # تأخير 5 ثوانٍ بين المحاولات
        enable_fallback=True,  # تفعيل الفولباك للخدمة الاحتياطية
    )
    print("   ✓ تم ضبط خدمة nindiad بنجاح")
    print("   ✓ عدد المحاولات القصوى: 10")
    print("   ✓ تأخير بين المحاولات: 5 ثوانٍ")
    print("   ✓ الفولباك التلقائي: مفعل")
    
    # 2. إنشاء المنسّق الذاتي
    print("\n[2] إنشاء المنسّق الذاتي (AutoOrchestrator)...")
    orch = AutoOrchestrator(
        registry=registry,
    )
    print("   ✓ تم إنشاء المنسّق الذاتي")
    
    # 3. محاولة حل hCaptcha (سيفشل بدون خدمة حقيقية، لكن سيعرض المنطق)
    print("\n[3] محاولة حل hCaptcha (مع max_escalations=3)...")
    print("   ملاحظة: بدون مفاتيح nindiad حقيقية، سيُظهر هذا عرضاً للمنطق فقط")
    
    # إظهار إحصائيات الخدمة
    from solver_engine.registry import get_hcaptcha_service_stats
    stats = get_hcaptcha_service_stats()
    print(f"\n[4] إحصائيات خدمات hCaptcha:")
    print(f"   عدد الخدمات المسجلة: {len(stats)}")
    for s in stats:
        print(f"   - {s['name']} ({s['api_type']}): معدل النجاح {s['success_rate']:.1%}")
    
    print("\n" + "=" * 70)
    print("لاختبار حقيقي مع مفاتيح nindiad الفعلية، استخدموا الأوامر التالية:")
    print("=" * 70)
    print("""
    # 1. ضبط خدمة nindiad في السيرفر:
    curl -X POST http://localhost:8000/api/hcaptcha/external \\
      -H "Content-Type: application/json" \\
      -d '{
        "api_key": "مفتاح_نindiad_الخاص_بك",
        "external_api": "https://api.nindiad.com",
        "external_api_type": "nindiad",
        "max_retries": 10,
        "retry_delay": 5.0
      }'
    
    # 2. حل hCaptcha:
    curl -X POST http://localhost:8000/solve/hcaptcha \\
      -H "Content-Type: application/json" \\
      -d '{
        "sitekey": "مفتاح_الموقع_العامة",
        "url": "https://الموقع_المستهدف.com"
      }'
    
    # 3. أو استخدام الحل الذاتي التلقائي (/auto) مع hCaptcha:
    curl -X POST http://localhost:8000/auto \\
      -F "captcha_type=hcaptcha" \\
      -F "sitekey=مفتاح_الموقع_العامة" \\
      -F "url=https://الموقع_المستهدف.com"
    """)
    print("=" * 70)


def demo_hcaptcha_retry_logic():
    """
    عرض توضيحي لمنطق إعادة المحاولة التلقائية.
    يُظهر كيف يحاول النظام الحل مراراً حتى النجاح أو نفاد المحاولات.
    """
    print("\n" + "=" * 70)
    print("منطق إعادة المحاولة التلقائية لـ hCaptcha")
    print("=" * 70)
    print("""
    السيناريو:
    ┌─────────────────────────────────────────────────────────┐
    │ المحاولة 1 → فشل → انتظار 5 ثواني → المحاولة 2           │
    │                                                              │
    │ المحاولة 2 → فشل → انتظار 5 ثواني → المحاولة 3           │
    │                                                              │
    │ المحاولة 3 → نجاح! → إرجاع التوكن                         │
    └─────────────────────────────────────────────────────────┘
    
    إذا فشلت جميع المحاولات (10 محاولات):
    • يُعاد أخطر خطأ encountered
    • يُسجل في سجل المراقبة (IntelligentMonitor)
    • يُرسل تنبيه عبر ديسكورد/ويب هوك (إذا تم ضبطه)
    
    المزايا:
    ✓ لا يتوقف النظام عند الفشل الأول
    ✓ تجربة خدمات متعددة (nindiad → nonecap → أخرى)
    ✓ اختيار الخدمة الصحية تلقائياً (بناءً على معدل النجاح)
    ✓ تسجيل جميع المحاولات في قاعدة المعرفة للتعلم المستقبلي
    """)


if __name__ == "__main__":
    demo_hcaptcha_with_nindiad()
    demo_hcaptcha_retry_logic()
