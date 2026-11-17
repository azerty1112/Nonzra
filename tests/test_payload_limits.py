"""اختبارات حدود حجم الحمولة: الرفض يجب أن يحدث قبل استهلاك الذاكرة."""

import asyncio


from api_server.main import _BodySizeGuard, _BodyTooLarge


async def _drive(limit: int, declared=None, chunks=(b"x" * 1000,) * 10):
    """يشغّل الحماية على مستوى ASGI ويعيد (بايتات مقروءة، حالة الاستجابة)."""
    state = {"consumed": 0, "sent": []}
    pending = list(chunks)

    async def inner_app(scope, receive, send):
        while True:
            message = await receive()
            if not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def receive():
        if not pending:
            return {"type": "http.request", "body": b"", "more_body": False}
        chunk = pending.pop(0)
        state["consumed"] += len(chunk)
        return {"type": "http.request", "body": chunk, "more_body": bool(pending)}

    async def send(message):
        state["sent"].append(message)

    headers = [(b"content-length", str(declared).encode())] if declared else []
    await _BodySizeGuard(inner_app, limit)({"type": "http", "headers": headers}, receive, send)
    status = next(
        (m["status"] for m in state["sent"] if m["type"] == "http.response.start"), None
    )
    return state["consumed"], status


def test_declared_oversize_body_is_rejected_without_reading():
    """أهم ضمان: لا نقرأ ولو بايتًا واحدًا إن أعلن العميل حجمًا أكبر."""
    consumed, status = asyncio.run(_drive(limit=5000, declared=400_000))
    assert status == 413
    assert consumed == 0


def test_streaming_oversize_body_is_cut_at_limit():
    consumed, status = asyncio.run(_drive(limit=5000, chunks=(b"x" * 2000,) * 10))
    assert status == 413
    # يُقطع عند أول تجاوز، لا بعد قراءة كل التدفّق (20KB)
    assert consumed <= 6000


def test_small_body_passes_through():
    consumed, status = asyncio.run(
        _drive(limit=5000, declared=2000, chunks=(b"x" * 1000,) * 2)
    )
    assert status == 200
    assert consumed == 2000


def test_body_too_large_is_raised_to_caller():
    """الإشارة الداخلية موجودة ومميّزة (ليست ValueError عابرة)."""
    assert issubclass(_BodyTooLarge, Exception)


def test_api_rejects_oversized_base64_fast():
    from fastapi.testclient import TestClient

    import api_server.main as main_mod

    client = TestClient(main_mod.app)
    response = client.post("/solve/image", json={"image_b64": "A" * (40 * 1024 * 1024)})
    assert response.status_code == 413
    assert "الحد المسموح" in response.json()["detail"]


def test_api_accepts_image_under_limit():
    import base64

    from fastapi.testclient import TestClient

    import api_server.main as main_mod

    client = TestClient(main_mod.app)
    payload = base64.b64encode(b"\x89PNG" + b"\x00" * 1024).decode()
    response = client.post("/solve/image", json={"image_b64": payload})
    # لا 413: الصورة صغيرة بما يكفي (النتيجة نفسها قد تفشل قراءةً)
    assert response.status_code != 413


def test_forwarded_for_is_ignored_by_default():
    """تزوير X-Forwarded-For كان يُفلت العميل من تحديد المعدل والحظر."""
    from starlette.requests import Request

    import api_server.main as main_mod

    request = Request(
        {
            "type": "http",
            "headers": [(b"x-forwarded-for", b"9.9.9.9")],
            "client": ("127.0.0.1", 1),
            "method": "GET",
            "path": "/",
            "query_string": b"",
        }
    )
    assert main_mod.POLICY.trust_forwarded_for is False
    assert main_mod._get_client_ip(request) == "127.0.0.1"


def test_rate_limit_tracking_is_capped():
    """قاموس العناوين كان ينمو بلا حد — استنزاف ذاكرة برشّ عناوين وهمية."""
    import api_server.main as main_mod

    original_limit = main_mod.MAX_TRACKED_IPS
    original_rate = main_mod.MAX_REQUESTS_PER_MINUTE
    main_mod._REQUEST_TIMESTAMPS.clear()
    main_mod.MAX_TRACKED_IPS = 50
    main_mod.MAX_REQUESTS_PER_MINUTE = 100
    try:
        for index in range(1000):
            main_mod._check_rate_limit(f"10.0.{index // 256}.{index % 256}")
        assert len(main_mod._REQUEST_TIMESTAMPS) <= 50
    finally:
        main_mod.MAX_TRACKED_IPS = original_limit
        main_mod.MAX_REQUESTS_PER_MINUTE = original_rate
        main_mod._REQUEST_TIMESTAMPS.clear()
