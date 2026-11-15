"""إرسال نتائج الحل عبر ويب هوكس مع إعادة المحاولة الأتوماتيكية."""

from typing import Any, Dict, Optional
import httpx
import asyncio
import json


class WebhookDeliverer:
    """يُسلّم نتيجة الحل إلى عنوان URL خارجي عند الانتهاء، مع إعادة محاولة أسيوية."""

    def __init__(self, max_retries: int = 3, timeout: float = 10.0) -> None:
        self.max_retries = max_retries
        self.timeout = timeout

    async def deliver(
        self,
        url: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> bool:
        last_error: Optional[str] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(
                        url,
                        json=payload,
                        headers=headers or {"Content-Type": "application/json"},
                    )
                    if resp.status_code < 300:
                        return True
                    last_error = f"HTTP {resp.status_code}"
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
            if attempt < self.max_retries:
                await asyncio.sleep(0.5 * (2 ** (attempt - 1)))
        # Dernier échec consigné silencieusement (لا يُفشل المهمة الأساسية)
        return False

    def build_payload(
        self,
        job_id: str,
        status: str,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        finished_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "job_id": job_id,
            "status": status,
            "result": result,
            "error": error,
            "finished_at": finished_at,
        }


webhook_deliverer = WebhookDeliverer()

__all__ = ["WebhookDeliverer", "webhook_deliverer"]
