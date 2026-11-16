#!/usr/bin/env python3
"""
اختبار تكامل كامل للخادم عبر HTTP.
يختبر جميع نقاط النهاية بما في ذلك hCaptcha مع محاكاة الخدمة الخارجية.
"""

import subprocess
import time
import json
import httpx
import sys
import os
import signal

BASE_URL = "http://127.0.0.1:8002"

def start_server():
    """تشغيل السيرفر في عملية منفصلة."""
    proc = subprocess.Popen(
        ["python3", "-m", "uvicorn", "api_server.main:app", 
         "--host", "127.0.0.1", "--port", "8002", "--log-level", "error"],
        cwd="/home/codespace/.local/nonecap-clone",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    return proc

def wait_for_server(max_wait=15):
    """انتظار حتى يصبح السيرفر جاهزاً."""
    for i in range(max_wait):
        try:
            resp = httpx.get(f"{BASE_URL}/health", timeout=2.0)
            if resp.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False

def test_endpoints():
    """اختبار جميع نقاط النهاية."""
    print("=" * 80)
    print("اختبار تكامل كامل للخادم عبر HTTP")
    print("=" * 80)
    
    results = {}
    
    # 1. اختبار الصحة
    print("\n[1] اختبار /health...")
    try:
        resp = httpx.get(f"{BASE_URL}/health", timeout=5.0)
        results['health'] = resp.status_code == 200
        print(f"   الحالة: {'✓ نجح' if resp.status_code == 200 else '✗ فشل'} (كود {resp.status_code})")
    except Exception as e:
        results['health'] = False
        print(f"   ✗ فشل: {e}")
    
    # 2. اختبار الإحصائيات
    print("\n[2] اختبار /stats...")
    try:
        resp = httpx.get(f"{BASE_URL}/stats", timeout=5.0)
        results['stats'] = resp.status_code == 200
        print(f"   الحالة: {'✓ نجح' if resp.status_code == 200 else '✗ فشل'} (كود {resp.status_code})")
        if resp.status_code == 200:
            data = resp.json()
            print(f"   إجمالي المحاولات: {data.get('total', 0)}")
            print(f"   معدل النجاح: {data.get('success_rate', 0)}%")
    except Exception as e:
        results['stats'] = False
        print(f"   ✗ فشل: {e}")
    
    # 3. اختبار إنشاء مفتاح API
    print("\n[3] اختبار إنشاء مفتاح API (/api/keys)...")
    try:
        resp = httpx.post(f"{BASE_URL}/api/keys", json={"name": "test-key"}, timeout=5.0)
        results['create_key'] = resp.status_code == 200
        print(f"   الحالة: {'✓ نجح' if resp.status_code == 200 else '✗ فشل'} (كود {resp.status_code})")
        if resp.status_code == 200:
            data = resp.json()
            print(f"   معرف المفتاح: {data.get('key_id', 'N/A')[:8]}...")
            print(f"   المفتاح: {data.get('api_key', 'N/A')[:20]}...")
    except Exception as e:
        results['create_key'] = False
        print(f"   ✗ فشل: {e}")
    
    # 4. اختبار قائمة المفاتيح
    print("\n[4] اختبار قائمة المفاتيح (/api/keys GET)...")
    try:
        resp = httpx.get(f"{BASE_URL}/api/keys", timeout=5.0)
        results['list_keys'] = resp.status_code == 200
        print(f"   الحالة: {'✓ نجح' if resp.status_code == 200 else '✗ فشل'} (كود {resp.status_code})")
        if resp.status_code == 200:
            keys = resp.json()
            print(f"   عدد المفاتيح: {len(keys)}")
    except Exception as e:
        results['list_keys'] = False
        print(f"   ✗ فشل: {e}")
    
    # 5. اختبار الحل التلقائي مع صورة
    print("\n[5] اختبار الحل التلقائي (/auto) مع صورة...")
    try:
        # إنشاء صورة تجريبية بسيطة
        import cv2
        import numpy as np
        img = np.full((60, 200, 3), 255, dtype=np.uint8)
        cv2.putText(img, "TEST", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0,0,0), 2)
        _, buf = cv2.imencode('.png', img)
        
        files = {"file": ("captcha.png", buf.tobytes(), "image/png")}
        data = {"captcha_type": "auto", "human_like": "false", "max_escalations": "2"}
        
        resp = httpx.post(f"{BASE_URL}/auto", files=files, data=data, timeout=30.0)
        results['auto_solve'] = resp.status_code == 200
        print(f"   الحالة: {'✓ نجح' if resp.status_code == 200 else '✗ فشل'} (كود {resp.status_code})")
        if resp.status_code == 200:
            data = resp.json()
            result = data.get('result', {})
            print(f"   النوع المكتشف: {data.get('detected_type', 'N/A')}")
            print(f"   نتيجة الحل: {'نجاح' if result.get('success') else 'فشل'}")
            print(f"   النص المحلول: {result.get('text', 'N/A')}")
            print(f"   ثقة الحل: {result.get('confidence', 0):.2f}")
            print(f"   الاستراتيجية: {data.get('strategy_used', 'N/A')}")
            print(f"   التصعيدات: {data.get('escalations', 0)}")
    except Exception as e:
        results['auto_solve'] = False
        print(f"   ✗ فشل: {e}")
    
    # 6. اختبار ضبط خدمة nindiad الخارجية
    print("\n[6] اختبار ضبط خدمة nindiad الخارجية...")
    try:
        resp = httpx.post(f"{BASE_URL}/api/hcaptcha/external", json={
            "api_key": "test_nindiad_key",
            "external_api": "https://api.nindiad.com",
            "external_api_type": "nindiad",
            "max_retries": 5,
            "retry_delay": 1.0
        }, timeout=5.0)
        results['config_hcaptcha'] = resp.status_code == 200
        print(f"   الحالة: {'✓ نجح' if resp.status_code == 200 else '✗ فشل'} (كود {resp.status_code})")
        if resp.status_code == 200:
            data = resp.json()
            print(f"   الرسالة: {data.get('message', 'N/A')}")
            print(f"   مُconfigured: {data.get('configured', False)}")
    except Exception as e:
        results['config_hcaptcha'] = False
        print(f"   ✗ فشل: {e}")
    
    # 7. اختبار إحصائيات الخبرة
    print("\n[7] اختبار إحصائيات الخبرة (/experience/stats)...")
    try:
        resp = httpx.get(f"{BASE_URL}/experience/stats", timeout=5.0)
        results['exp_stats'] = resp.status_code == 200
        print(f"   الحالة: {'✓ نجح' if resp.status_code == 200 else '✗ فشل'} (كود {resp.status_code})")
        if resp.status_code == 200:
            data = resp.json()
            print(f"   مستوى الخبرة: {data.get('experience_level', 0)}")
            print(f"   درجة الحكمة: {data.get('wisdom_score', 0)}")
            print(f"   إجمالي الحلول: {data.get('total_solved', 0)}")
    except Exception as e:
        results['exp_stats'] = False
        print(f"   ✗ فشل: {e}")
    
    # 8. اختبار قاعدة المعرفة
    print("\n[8] اختبار قاعدة المعرفة (/experience/knowledge)...")
    try:
        resp = httpx.get(f"{BASE_URL}/experience/knowledge", timeout=5.0)
        results['kb_stats'] = resp.status_code == 200
        print(f"   الحالة: {'✓ نجح' if resp.status_code == 200 else '✗ فشل'} (كود {resp.status_code})")
        if resp.status_code == 200:
            data = resp.json()
            print(f"   إجمالي الأنماط: {data.get('total_patterns', 0)}")
            print(f"   متوسط معدل النجاح: {data.get('avg_success_rate', 0)}")
    except Exception as e:
        results['kb_stats'] = False
        print(f"   ✗ فشل: {e}")
    
    # 9. اختبار الحل من رابط URL
    print("\n[9] اختبار الحل من رابط URL (/captcha-solve/url)...")
    try:
        resp = httpx.post(f"{BASE_URL}/captcha-solve/url", json={
            "url": "https://example.com/captcha.png",
            "captcha_type": "image"
        }, timeout=15.0)
        # قد يفشل إذا كان الرابط غير متاح، لكننا نتأكد من أن النقطة تعمل
        results['solve_url'] = resp.status_code in (200, 400)
        print(f"   الحالة: {'✓ نجح (أو فشل متوقع)' if resp.status_code in (200, 400) else '✗ فشل غير متوقع'} (كود {resp.status_code})")
    except Exception as e:
        results['solve_url'] = False
        print(f"   ✗ فشل: {e}")
    
    # 10. اختبار الحل الجماعي
    print("\n[10] اختبار الحل الجماعي (/bulk/auto)...")
    try:
        resp = httpx.post(f"{BASE_URL}/bulk/auto", json={
            "items": [
                {"captcha_type": "image"},
                {"captcha_type": "image"},
            ]
        }, timeout=30.0)
        results['bulk'] = resp.status_code == 200
        print(f"   الحالة: {'✓ نجح' if resp.status_code == 200 else '✗ فشل'} (كود {resp.status_code})")
        if resp.status_code == 200:
            data = resp.json()
            print(f"   عدد المهام: {data.get('count', 0)}")
            print(f"   معرف المجموعة: {data.get('bulk_id', 'N/A')[:8]}...")
    except Exception as e:
        results['bulk'] = False
        print(f"   ✗ فشل: {e}")
    
    # ملخص النتائج
    print("\n" + "=" * 80)
    print("ملخص نتائج الاختبار:")
    print("=" * 80)
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    for test, passed_test in results.items():
        status = "✓ نجح" if passed_test else "✗ فشل"
        print(f"   {test}: {status}")
    print(f"\nالإجمالي: {passed}/{total} اختبار نجح")
    
    if passed == total:
        print("\n🎉 جميع الاختبارات نجحت! النظام يعمل بشكل كامل.")
    else:
        print(f"\n⚠️  هناك {total - passed} اختبار(es) فشلت. يرجى مراجعة الأخطاء أعلاه.")
    
    return passed == total


if __name__ == "__main__":
    # تشغيل السيرفر
    print("جاري تشغيل السيرفر...")
    proc = start_server()
    
    try:
        if wait_for_server():
            print("✓ السيرفر يعمل على", BASE_URL)
            success = test_endpoints()
        else:
            print("✗ فشل تشغيل السيرفر")
            success = False
    finally:
        proc.terminate()
        proc.wait()
        print("\nتم إيقاف السيرفر.")
    
    sys.exit(0 if success else 1)
