"""ملف اختبار الأحمال (Locust) لسيرفر NoneCap Clone.

لتشغيل الاختبار:
    locust -f locustfile.py --host=http://localhost:8000
ثم افتح http://localhost:8089 في المتصفح.
"""

from locust import HttpUser, task, between
import random
import io


class NoneCapUser(HttpUser):
    """مستخدم محاكي لاختبار أداء سيرفر NoneCap Clone."""
    wait_time = between(1, 5)
    host = "http://localhost:8000"

    def on_start(self):
        """يُنفذ عند بدء كل مستخدم محاكي."""
        self.api_key = None
        # يمكن إنشاء مفتاح API هنا إذا كان السيرفر يتطلب مصادقة

    @task(3)
    def health_check(self):
        """فحص حالة السيرفر."""
        self.client.get("/health", name="health")

    @task(2)
    def get_stats(self):
        """الحصول على الإحصائيات."""
        self.client.get("/stats", name="stats")

    @task(5)
    def solve_image_captcha(self):
        """حل صورة كبتشا تجريبية."""
        # إنشاء صورة تجريبية بسيطة (بكسل أبيض وأسود)
        image_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x01\x00\x18\xdd\x4d\xb4\x00\x00\x00\x00IEND\xaeB`\x82"

        files = {"file": ("captcha.png", io.BytesIO(image_data), "image/png")}
        data = {
            "captcha_type": "image",
            "psm": "7",
            "preprocess": "true",
        }
        self.client.post("/solve/image", files=files, data=data, name="solve_image")

    @task(2)
    def solve_auto(self):
        """حل ذاتي تلقائي."""
        image_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x01\x00\x18\xdd\x4d\xb4\x00\x00\x00\x00IEND\xaeB`\x82"

        files = {"file": ("captcha.png", io.BytesIO(image_data), "image/png")}
        data = {
            "captcha_type": "auto",
            "human_like": "false",
            "max_escalations": "2",
        }
        self.client.post("/auto", files=files, data=data, name="auto_solve")

    @task(1)
    def solve_url(self):
        """حل من رابط URL."""
        payload = {
            "url": "https://example.com/captcha.png",
            "captcha_type": "image",
        }
        self.client.post("/solve/url", json=payload, name="solve_url")

    @task(1)
    def auto_status(self):
        """الحصول على حالة العامل التلقائي."""
        self.client.get("/auto/status", name="auto_status")

    @task(1)
    def experience_stats(self):
        """الحصول على إحصائيات الخبرة."""
        self.client.get("/experience/stats", name="experience_stats")


class AdminUser(HttpUser):
    """مستخدم محاكي لاختبار نقاط نهاية الإدارة."""
    wait_time = between(10, 30)
    host = "http://localhost:8000"

    @task
    def create_api_key(self):
        """إنشاء مفتاح API."""
        self.client.post("/api/keys", json={"name": "load-test-key"}, name="create_key")

    @task
    def list_keys(self):
        """قائمة المفاتيح."""
        self.client.get("/api/keys", name="list_keys")

    @task
    def bulk_auto(self):
        """حل جماعي."""
        payload = {
            "items": [
                {"captcha_type": "image"},
                {"captcha_type": "image"},
                {"captcha_type": "image"},
            ]
        }
        self.client.post("/bulk/auto", json=payload, name="bulk_auto")
