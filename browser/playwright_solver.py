"""تكامل Playwright لحل الكبتشا داخل متصفح حقيقي."""

from typing import Any, Optional
from playwright.sync_api import sync_playwright, Page, Browser

try:
    from httpx import Client
except ImportError:  # pragma: no cover
    Client: Any = None  # type: ignore[assignment, no-redef]


class BrowserSolver:
    """يفتح متصفحًا حقيقيًا، يكتشف الكبتشا، ويرسله للسيرفر المحلي للحل."""

    def __init__(self, base_url: str = "http://localhost:8000", headless: bool = True) -> None:
        self.base_url = base_url.rstrip("/")
        self.headless = headless
        self._browser: Optional[Browser] = None
        self._playwright = None

    def start(self) -> None:
        if self._playwright is None:
            playwright = sync_playwright().start()
            self._playwright = playwright
            self._browser = playwright.chromium.launch(headless=self.headless)

    def stop(self) -> None:
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    def new_page(self) -> Page:
        self.start()
        assert self._browser is not None
        return self._browser.new_page()

    def solve_page_captcha(
        self,
        page: Page,
        captcha_type: str = "image",
        sitekey: Optional[str] = None,
        url: Optional[str] = None,
    ) -> dict:
        import base64

        # أخذ لقطة للكابتشا إن وجد
        screenshot_b64: Optional[str] = None
        try:
            shot = page.screenshot(full_page=False)
            screenshot_b64 = base64.b64encode(shot).decode("utf-8")
        except Exception:  # noqa: BLE001
            screenshot_b64 = None

        payload: dict = {
            "captcha_type": captcha_type,
            "sitekey": sitekey,
            "url": url or page.url,
            "image_b64": screenshot_b64,
        }
        payload = {k: v for k, v in payload.items() if v is not None}

        if Client is None:
            raise RuntimeError("httpx غير مثبت")

        with Client(timeout=60.0) as client:
            resp = client.post(f"{self.base_url}/solve/{captcha_type}", json=payload)
            resp.raise_for_status()
            return resp.json()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()
