"""تكامل Selenium مع متصفحات الويب لحل الكبتشا تلقائياً."""

from typing import Any, Dict, Optional
import time

try:
    from selenium import webdriver  # type: ignore[import]
    from selenium.webdriver.common.by import By  # type: ignore[import]
    from selenium.webdriver.chrome.options import Options as ChromeOptions  # type: ignore[import]
    from selenium.webdriver.firefox.options import Options as FirefoxOptions  # type: ignore[import]
    from selenium.common.exceptions import TimeoutException, WebDriverException  # type: ignore[import]

    _SELENIUM_AVAILABLE = True
except Exception:  # noqa: BLE001
    _SELENIUM_AVAILABLE = False


class SeleniumSolver:
    """يستخدم Selenium لفتح متصفح، العثور على الكبتشا، التقاط صورته، وإرسالها للحل."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        api_key: Optional[str] = None,
        browser: str = "chrome",
        headless: bool = True,
        timeout: float = 30.0,
    ) -> None:
        if not _SELENIUM_AVAILABLE:
            raise RuntimeError("حزمة selenium غير مثبتة. شغّل: pip install selenium")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.driver: Optional[Any] = None
        self._setup_driver(browser, headless)

    def _setup_driver(self, browser: str, headless: bool) -> None:
        if browser.lower() == "chrome":
            options = ChromeOptions()
            if headless:
                options.add_argument("--headless=new")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--window-size=1920,1080")
            self.driver = webdriver.Chrome(options=options)  # type: ignore[call-arg]
        elif browser.lower() == "firefox":
            options = FirefoxOptions()
            if headless:
                options.add_argument("--headless")
            self.driver = webdriver.Firefox(options=options)  # type: ignore[call-arg]
        else:
            raise ValueError(f"المتصفح غير مدعوم: {browser}")
        self.driver.implicitly_wait(int(self.timeout))

    def navigate(self, url: str) -> None:
        """ينتقل إلى رابط صفحة ويب."""
        if self.driver is None:
            raise RuntimeError("المتصفح غير مهيأ")
        self.driver.get(url)

    def find_captcha_image(
        self,
        selector: Optional[str] = None,
        by: str = By.CSS_SELECTOR,
    ) -> Optional[Any]:
        """يعثر على عنصر صورة الكبتشا في الصفحة."""
        if self.driver is None:
            return None
        if selector:
            elements = self.driver.find_elements(by, selector)  # type: ignore[attr-defined]
            if elements:
                return elements[0]
        selectors = [
            "img[src*='captcha']",
            "img[alt*='captcha']",
            "img[class*='captcha']",
            ".captcha-image",
            ".captcha img",
            "[data-captcha]",
        ]
        for sel in selectors:
            try:
                elements = self.driver.find_elements(by, sel)  # type: ignore[attr-defined]
                if elements:
                    return elements[0]
            except Exception:
                continue
        return None

    def capture_captcha_image(self, element: Any) -> Optional[bytes]:
        """يؤخذ لقطة شاشة لعنصر الكبتشا ويعيدها كبايتات."""
        if self.driver is None or element is None:
            return None
        try:
            return element.screenshot_as_png  # type: ignore[attr-defined]
        except Exception:
            return None

    def solve_captcha_element(
        self,
        element: Any,
        captcha_type: Optional[str] = None,
        human_like: bool = False,
    ) -> Dict[str, Any]:
        """يلتقط صورة عنصر الكبتشا ويرسلها للسيرفر للحل التلقائي."""
        import httpx

        image_bytes = self.capture_captcha_image(element)
        if not image_bytes:
            return {"success": False, "error": "فشل التقاط صورة الكبتشا"}

        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        files = {"file": ("captcha.png", image_bytes, "image/png")}
        data: Dict[str, Any] = {
            "captcha_type": captcha_type or "auto",
            "human_like": human_like,
            "max_escalations": 2,
        }

        try:
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(
                    f"{self.base_url}/auto",
                    files=files,
                    data=data,
                    headers=headers,
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": str(exc)}

    def solve_captcha_by_selector(
        self,
        selector: str,
        by: str = By.CSS_SELECTOR,
        captcha_type: Optional[str] = None,
        human_like: bool = False,
    ) -> Dict[str, Any]:
        """يعثر على الكبتشا باستخدام المحدد ويحلّه تلقائياً."""
        element = self.find_captcha_image(selector, by)
        if element is None:
            return {"success": False, "error": "لم يتم العثور على صورة الكبتشا"}
        return self.solve_captcha_element(element, captcha_type, human_like)

    def fill_result(
        self,
        result: Dict[str, Any],
        input_selector: Optional[str] = None,
        input_by: str = By.CSS_SELECTOR,
    ) -> bool:
        """يملأ نتيجة الحل في حقل الإدخال المحدد."""
        if self.driver is None:
            return False
        text = result.get("text") or result.get("token", "")
        if not text:
            return False

        if input_selector:
            try:
                input_elem = self.driver.find_element(input_by, input_selector)  # type: ignore[attr-defined]
                input_elem.clear()
                input_elem.send_keys(text)
                return True
            except Exception:
                return False

        try:
            inputs = self.driver.find_elements(By.TAG_NAME, "input")  # type: ignore[attr-defined]
            for inp in inputs:
                try:
                    inp_type = inp.get_attribute("type") or ""
                    if inp_type in ("text", "", "password"):
                        inp.clear()
                        inp.send_keys(text)
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        return False

    def quit(self) -> None:
        """يغلق المتصفح."""
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None

    def __enter__(self) -> "SeleniumSolver":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.quit()


__all__ = ["SeleniumSolver"]
