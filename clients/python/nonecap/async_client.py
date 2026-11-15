"""عميل بايثون غير متزامن (asyncio) لسيرفر NoneCap Clone."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import httpx


@dataclass
class SolveResult:
    success: bool
    captcha_type: str
    text: Optional[str] = None
    token: Optional[str] = None
    confidence: float = 0.0
    response_time_ms: int = 0
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    analysis: Optional[Dict[str, Any]] = None
    alerts: List[Dict[str, Any]] = field(default_factory=list)
    strategy_used: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "SolveResult":
        return cls(
            success=data.get("success", False),
            captcha_type=data.get("captcha_type", ""),
            text=data.get("text"),
            token=data.get("token"),
            confidence=float(data.get("confidence", 0.0)),
            response_time_ms=int(data.get("response_time_ms", 0)),
            error=data.get("error"),
            metadata=data.get("metadata", {}) or {},
            analysis=data.get("analysis"),
            alerts=data.get("alerts", []) or [],
            strategy_used=data.get("strategy_used"),
        )


@dataclass
class AutoSolveResult:
    """نتيجة الحل الذاتي الكامل القادمة من /auto."""
    result: SolveResult
    detected_type: str = ""
    detection_confidence: float = 0.0
    strategy_used: str = ""
    params_used: Dict[str, Any] = field(default_factory=dict)
    escalations: int = 0
    trace: List[str] = field(default_factory=list)
    alerts: List[Dict[str, Any]] = field(default_factory=list)
    total_time_ms: int = 0

    @property
    def success(self) -> bool:
        return self.result.success

    @classmethod
    def from_dict(cls, data: dict) -> "AutoSolveResult":
        return cls(
            result=SolveResult.from_dict(data.get("result", {})),
            detected_type=data.get("detected_type", ""),
            detection_confidence=float(data.get("detection_confidence", 0.0)),
            strategy_used=data.get("strategy_used", ""),
            params_used=data.get("params_used", {}) or {},
            escalations=int(data.get("escalations", 0)),
            trace=data.get("trace", []) or [],
            alerts=data.get("alerts", []) or [],
            total_time_ms=int(data.get("total_time_ms", 0)),
        )


class NoneCapAsync:
    """عميل غير متزامن."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        timeout: float = 60.0,
        api_key: Optional[str] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.api_key = api_key
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    def _headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def solve(
        self,
        captcha_type: str = "image",
        sitekey: Optional[str] = None,
        url: Optional[str] = None,
        action: Optional[str] = None,
        cdata: Optional[str] = None,
        target_color: Optional[str] = None,
        min_area: int = 20,
        image_path: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        template_path: Optional[str] = None,
        template_bytes: Optional[bytes] = None,
        psm: int = 7,
        oem: int = 3,
        whitelist: Optional[str] = None,
        preprocess: bool = True,
        resize_width: int = 400,
        threshold: str = "otsu",
        human_like: bool = False,
    ) -> SolveResult:
        client = await self._get_client()
        files: Dict[str, Any] = {}
        data: Dict[str, Any] = {
            "captcha_type": captcha_type,
            "sitekey": sitekey,
            "url": url,
            "action": action,
            "cdata": cdata,
            "target_color": target_color,
            "min_area": min_area,
            "psm": psm,
            "oem": oem,
            "preprocess": preprocess,
            "resize_width": resize_width,
            "threshold": threshold,
            "human_like": human_like,
        }
        if whitelist:
            data["whitelist"] = whitelist

        if image_bytes is not None:
            files["file"] = ("captcha.png", image_bytes, "image/png")
        elif image_path is not None:
            files["file"] = (image_path, open(image_path, "rb"), "image/png")
        if template_bytes is not None:
            files["template"] = ("template.png", template_bytes, "image/png")
        elif template_path is not None:
            files["template"] = (template_path, open(template_path, "rb"), "image/png")

        data = {k: v for k, v in data.items() if v is not None}
        try:
            resp = await client.post(
                f"{self.base_url}/solve/{captcha_type}",
                files=files or None,
                data=data or None,
                headers=self._headers(),
            )
            resp.raise_for_status()
            body = resp.json()
            result_data = body.get("result", body)
            result_data["analysis"] = body.get("analysis")
            result_data["alerts"] = body.get("alerts", []) or []
            result_data["strategy_used"] = body.get("strategy_used")
            return SolveResult.from_dict(result_data)
        finally:
            for f in files.values():
                try:
                    f[1].close()
                except Exception:
                    pass

    async def solve_image(
        self,
        image_path: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        psm: int = 7,
        oem: int = 3,
        whitelist: Optional[str] = None,
        preprocess: bool = True,
        resize_width: int = 400,
        threshold: str = "otsu",
    ) -> SolveResult:
        return await self.solve(
            captcha_type="image",
            image_path=image_path,
            image_bytes=image_bytes,
            psm=psm,
            oem=oem,
            whitelist=whitelist,
            preprocess=preprocess,
            resize_width=resize_width,
            threshold=threshold,
        )

    async def solve_hcaptcha(
        self,
        sitekey: str,
        url: str,
        image_b64: Optional[str] = None,
    ) -> SolveResult:
        client = await self._get_client()
        data: Dict[str, Any] = {"sitekey": sitekey, "url": url}
        if image_b64:
            data["image_b64"] = image_b64
        resp = await client.post(
            f"{self.base_url}/solve/hcaptcha",
            json=data,
            headers=self._headers(),
        )
        resp.raise_for_status()
        body = resp.json()
        return SolveResult.from_dict(body.get("result", body))

    async def solve_recaptcha(
        self,
        sitekey: str,
        url: str,
        captcha_type: str = "recaptcha_v2",
        action: Optional[str] = None,
        image_b64: Optional[str] = None,
    ) -> SolveResult:
        client = await self._get_client()
        data: Dict[str, Any] = {
            "captcha_type": captcha_type,
            "sitekey": sitekey,
            "url": url,
        }
        if action:
            data["action"] = action
        if image_b64:
            data["image_b64"] = image_b64
        resp = await client.post(
            f"{self.base_url}/solve/{captcha_type}",
            json=data,
            headers=self._headers(),
        )
        resp.raise_for_status()
        body = resp.json()
        return SolveResult.from_dict(body.get("result", body))

    async def solve_turnstile(
        self,
        sitekey: str,
        url: str,
        action: Optional[str] = None,
        cdata: Optional[str] = None,
    ) -> SolveResult:
        client = await self._get_client()
        data: Dict[str, Any] = {"sitekey": sitekey, "url": url}
        if action:
            data["action"] = action
        if cdata:
            data["cdata"] = cdata
        resp = await client.post(
            f"{self.base_url}/solve/turnstile",
            json=data,
            headers=self._headers(),
        )
        resp.raise_for_status()
        body = resp.json()
        return SolveResult.from_dict(body.get("result", body))

    async def solve_drag(
        self,
        image_path: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        template_path: Optional[str] = None,
        template_bytes: Optional[bytes] = None,
    ) -> SolveResult:
        client = await self._get_client()
        files: Dict[str, Any] = {}
        if image_bytes is not None:
            files["file"] = ("captcha.png", image_bytes, "image/png")
        elif image_path is not None:
            files["file"] = (image_path, open(image_path, "rb"), "image/png")
        if template_bytes is not None:
            files["template"] = ("template.png", template_bytes, "image/png")
        elif template_path is not None:
            files["template"] = (template_path, open(template_path, "rb"), "image/png")
        try:
            resp = await client.post(
                f"{self.base_url}/solve/drag",
                files=files,
                headers=self._headers(),
            )
            resp.raise_for_status()
            body = resp.json()
            return SolveResult.from_dict(body.get("result", body))
        finally:
            for f in files.values():
                try:
                    f[1].close()
                except Exception:
                    pass

    async def solve_point(
        self,
        image_path: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        target_color: Optional[str] = None,
        min_area: int = 20,
    ) -> SolveResult:
        client = await self._get_client()
        files: Dict[str, Any] = {}
        if image_bytes is not None:
            files["file"] = ("captcha.png", image_bytes, "image/png")
        elif image_path is not None:
            files["file"] = (image_path, open(image_path, "rb"), "image/png")
        data: Dict[str, Any] = {}
        if target_color:
            data["target_color"] = target_color
        data["min_area"] = str(min_area)
        try:
            resp = await client.post(
                f"{self.base_url}/solve/point",
                files=files,
                data=data,
                headers=self._headers(),
            )
            resp.raise_for_status()
            body = resp.json()
            return SolveResult.from_dict(body.get("result", body))
        finally:
            for f in files.values():
                try:
                    f[1].close()
                except Exception:
                    pass

    async def solve_async_submit(
        self,
        captcha_type: str,
        sitekey: Optional[str] = None,
        url: Optional[str] = None,
        image_path: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        **kwargs: Any,
    ) -> str:
        client = await self._get_client()
        files: Dict[str, Any] = {}
        data: Dict[str, Any] = {"captcha_type": captcha_type}
        if sitekey:
            data["sitekey"] = sitekey
        if url:
            data["url"] = url
        for k, v in kwargs.items():
            if v is not None:
                data[k] = v
        if image_bytes is not None:
            files["file"] = ("captcha.png", image_bytes, "image/png")
        elif image_path is not None:
            files["file"] = (image_path, open(image_path, "rb"), "image/png")
        try:
            resp = await client.post(
                f"{self.base_url}/solve/async/{captcha_type}",
                files=files or None,
                data=data or None,
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json().get("job_id", "")
        finally:
            for f in files.values():
                try:
                    f[1].close()
                except Exception:
                    pass

    async def job_status(self, job_id: str) -> SolveResult:
        client = await self._get_client()
        resp = await client.get(f"{self.base_url}/job/{job_id}", headers=self._headers())
        resp.raise_for_status()
        body = resp.json()
        return SolveResult.from_dict(body.get("result", body))

    async def auto(
        self,
        captcha_type: Optional[str] = None,
        image_path: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        template_path: Optional[str] = None,
        template_bytes: Optional[bytes] = None,
        sitekey: Optional[str] = None,
        url: Optional[str] = None,
        action: Optional[str] = None,
        cdata: Optional[str] = None,
        human_like: bool = False,
        max_escalations: int = 2,
    ) -> AutoSolveResult:
        """حل ذاتي كامل غير متزامن."""
        client = await self._get_client()
        files: Dict[str, Any] = {}
        data: Dict[str, Any] = {
            "captcha_type": captcha_type,
            "sitekey": sitekey,
            "url": url,
            "action": action,
            "cdata": cdata,
            "human_like": human_like,
            "max_escalations": max_escalations,
        }
        if image_bytes is not None:
            files["file"] = ("captcha.png", image_bytes, "image/png")
        elif image_path is not None:
            files["file"] = (image_path, open(image_path, "rb"), "image/png")
        if template_bytes is not None:
            files["template"] = ("template.png", template_bytes, "image/png")
        elif template_path is not None:
            files["template"] = (template_path, open(template_path, "rb"), "image/png")
        data = {k: v for k, v in data.items() if v is not None}
        try:
            resp = await client.post(
                f"{self.base_url}/auto",
                files=files or None,
                data=data or None,
                headers=self._headers(),
            )
            resp.raise_for_status()
            return AutoSolveResult.from_dict(resp.json())
        finally:
            for f in files.values():
                try:
                    f[1].close()
                except Exception:
                    pass

    async def auto_submit(
        self,
        captcha_type: Optional[str] = None,
        image_path: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        template_path: Optional[str] = None,
        template_bytes: Optional[bytes] = None,
        sitekey: Optional[str] = None,
        url: Optional[str] = None,
        human_like: bool = False,
        max_escalations: int = 2,
    ) -> str:
        client = await self._get_client()
        files: Dict[str, Any] = {}
        data: Dict[str, Any] = {
            "captcha_type": captcha_type,
            "sitekey": sitekey,
            "url": url,
            "human_like": human_like,
            "max_escalations": max_escalations,
        }
        if image_bytes is not None:
            files["file"] = ("captcha.png", image_bytes, "image/png")
        elif image_path is not None:
            files["file"] = (image_path, open(image_path, "rb"), "image/png")
        if template_bytes is not None:
            files["template"] = ("template.png", template_bytes, "image/png")
        elif template_path is not None:
            files["template"] = (template_path, open(template_path, "rb"), "image/png")
        data = {k: v for k, v in data.items() if v is not None}
        try:
            resp = await client.post(
                f"{self.base_url}/auto/async",
                files=files or None,
                data=data or None,
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json().get("job_id", "")
        finally:
            for f in files.values():
                try:
                    f[1].close()
                except Exception:
                    pass

    async def auto_job(self, job_id: str) -> Dict[str, Any]:
        client = await self._get_client()
        resp = await client.get(f"{self.base_url}/auto/job/{job_id}", headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    async def auto_status(self) -> Dict[str, Any]:
        client = await self._get_client()
        resp = await client.get(f"{self.base_url}/auto/status", headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    async def feedback(
        self,
        strategy: str,
        success: bool,
        confidence: float = 0.0,
        response_time_ms: int = 0,
        captcha_type: str = "image",
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        client = await self._get_client()
        payload: Dict[str, Any] = {
            "strategy": strategy,
            "success": success,
            "confidence": confidence,
            "response_time_ms": response_time_ms,
            "captcha_type": captcha_type,
        }
        if params is not None:
            payload["params"] = params
        resp = await client.post(f"{self.base_url}/feedback", json=payload, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    async def stats(self) -> Dict[str, Any]:
        client = await self._get_client()
        resp = await client.get(f"{self.base_url}/stats", headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    async def health(self) -> Dict[str, Any]:
        client = await self._get_client()
        resp = await client.get(f"{self.base_url}/health", headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()
