"""اختبارات مسار hCaptcha المباشر — عبر محاكي محلي لبروتوكول hCaptcha.

المحاكي يخدم نفس المسارات الثلاثة (checksiteconfig → getcaptcha → checkcaptcha)
ويُعيد صورة تحدٍّ نصية حقيقية، فنختبر المسار كاملًا دون أي خدمة خارجية.
"""

import json
import threading
import time

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from http.server import BaseHTTPRequestHandler, HTTPServer

from solver_engine import hcaptcha_live
from solver_engine.net import NetworkConfig
from solver_engine.ocr import engines_status, read_text


# ---------------------- محاكي hCaptcha ----------------------


def _text_image(text: str, noise: int = 2) -> bytes:
    img = np.full((80, 250, 3), 245, np.uint8)
    cv2.putText(img, text, (14, 56), cv2.FONT_HERSHEY_SIMPLEX, 1.7, (20, 20, 20), 3, cv2.LINE_AA)
    rng = np.random.default_rng(5)
    for _ in range(noise):
        p1 = (int(rng.integers(0, 250)), int(rng.integers(0, 80)))
        p2 = (int(rng.integers(0, 250)), int(rng.integers(0, 80)))
        cv2.line(img, p1, p2, (120, 120, 120), 1, cv2.LINE_AA)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


class FakeHCaptcha(BaseHTTPRequestHandler):
    expected = "AB12"
    mode = "text"          # text | multi | config_pass
    answers: list = []
    rounds = 0

    def _send(self, payload, code=200, ctype="application/json"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/checksiteconfig"):
            if FakeHCaptcha.mode == "config_pass":
                return self._send({"pass": True, "generated_pass_UUID": "P1_NO_CHALLENGE"})
            return self._send({"pass": False, "c": {"req": "REQ1", "hostToken": "HT1"}})
        if self.path.startswith("/img/"):
            return self._send(_text_image(FakeHCaptcha.expected), ctype="image/png")
        return self._send({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("content-length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path.startswith("/getcaptcha/"):
            FakeHCaptcha.rounds += 1
            if FakeHCaptcha.mode == "multi":
                return self._send(
                    {
                        "c": {
                            "request_type": "image_label_binary",
                            "requester_question": {"en": "click bicycles"},
                            "image_urls": ["/img/a", "/img/b", "/img/c"],
                            "key": "K-MULTI",
                        }
                    }
                )
            return self._send(
                {
                    "c": {
                        "request_type": "text",
                        "requester_question": "Type the text",
                        "image_urls": ["/img/chal"],
                        "key": f"K-{FakeHCaptcha.rounds}",
                    }
                }
            )
        if self.path.startswith("/checkcaptcha"):
            FakeHCaptcha.answers.append(body)
            if str(body.get("text", "")).upper() == FakeHCaptcha.expected.upper():
                return self._send({"generated_pass_UUID": "P1_TOKEN_OK"})
            return self._send({"error": "invalid answer"})
        return self._send({"error": "not found"}, 404)

    def log_message(self, *args):  # noqa: D102
        pass


@pytest.fixture()
def fake_hcaptcha(monkeypatch):
    FakeHCaptcha.expected = "AB12"
    FakeHCaptcha.mode = "text"
    FakeHCaptcha.answers = []
    FakeHCaptcha.rounds = 0
    server = HTTPServer(("127.0.0.1", 0), FakeHCaptcha)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("NONECAP_HCAPTCHA_BASE", f"http://127.0.0.1:{port}")
    monkeypatch.setattr(hcaptcha_live, "hcaptcha_base_url", lambda: f"http://127.0.0.1:{port}")
    monkeypatch.setattr(hcaptcha_live, "NETWORK", NetworkConfig(timeout_seconds=20))
    yield FakeHCaptcha
    server.shutdown()


# ---------------------- تحليل الاستجابة ----------------------


def test_parse_challenge_detects_text_challenge():
    payload = {
        "c": {
            "request_type": "text",
            "requester_question": "Type the text",
            "image_urls": ["/img/1"],
            "key": "K1",
        }
    }
    challenge = hcaptcha_live.parse_challenge(payload)
    assert challenge.kind == "text"
    assert challenge.image_urls == ["/img/1"]
    assert challenge.key == "K1"


def test_parse_challenge_detects_multi_image_and_prompt():
    payload = {
        "c": {
            "request_type": "image_label_binary",
            "requester_question": {"en": "Please click each image containing a bicycle"},
            "image_urls": ["a", "b", "c"],
            "key": "K2",
        }
    }
    challenge = hcaptcha_live.parse_challenge(payload)
    assert challenge.kind == "multi_image"
    assert len(challenge.image_urls) == 3
    assert "bicycle" in challenge.prompt


def test_parse_challenge_marks_unsupported():
    challenge = hcaptcha_live.parse_challenge({"c": {"request_type": "unknown_type"}})
    assert challenge.kind == "unsupported"


def test_absolute_url_handles_relative_paths(monkeypatch):
    monkeypatch.setattr(hcaptcha_live, "hcaptcha_base_url", lambda: "https://hcaptcha.com")
    assert hcaptcha_live._absolute_url("/img/x.png") == "https://hcaptcha.com/img/x.png"
    assert hcaptcha_live._absolute_url("//cdn/x.png") == "https://cdn/x.png"
    assert hcaptcha_live._absolute_url("https://a/b") == "https://a/b"


# ---------------------- المسار الكامل ----------------------


@pytest.mark.parametrize("expected", ["AB12", "7KQ9"])
def test_live_solver_solves_text_challenge(fake_hcaptcha, expected):
    fake_hcaptcha.expected = expected
    result = hcaptcha_live.HCaptchaLiveSolver().solve(
        sitekey="10000000-ffff-ffff-ffff-000000000001",
        url="https://accounts.hcaptcha.com/demo",
    )
    assert result.success is True
    assert result.token == "P1_TOKEN_OK"
    assert result.text == expected
    assert result.metadata["stage"] == "checkcaptcha"
    assert fake_hcaptcha.answers[-1]["text"] == expected


def test_live_solver_reports_rejected_answer(fake_hcaptcha, monkeypatch):
    fake_hcaptcha.expected = "ZZZZ"
    monkeypatch.setattr(
        hcaptcha_live,
        "_read_text_detailed",
        lambda data, expected_len=None, deep=False, order=None: {
            "text": "WRONG9",
            "confidence": 0.9,
            "engine": "stub",
            "plausibility": 1.0,
        },
    )
    result = hcaptcha_live.HCaptchaLiveSolver().solve(
        sitekey="sk", url="https://example.com"
    )
    assert result.success is False
    assert "invalid answer" in (result.error or "")
    assert result.metadata["attempts"] and result.metadata["attempts"][0]["answer"] == "WRONG9"
    assert result.metadata["last_certainty"] > 0
    # المحلّل يعيد المحاولة بعد الرفض (max_rounds الافتراضي = 2)
    # المحلّل يعيد المحاولة حتى max_rounds (الافتراضي الآن 3)
    assert len(fake_hcaptcha.answers) >= 2
    assert len({a["key"] for a in fake_hcaptcha.answers}) == len(fake_hcaptcha.answers)


def test_live_solver_handles_multi_image_explicitly(fake_hcaptcha):
    fake_hcaptcha.mode = "multi"
    result = hcaptcha_live.HCaptchaLiveSolver().solve(
        sitekey="sk", url="https://example.com"
    )
    assert result.success is False
    assert "متعدد الصور" in (result.error or "")
    assert result.metadata["stage"] == "parse"


def test_live_solver_accepts_config_pass_without_challenge(fake_hcaptcha):
    fake_hcaptcha.mode = "config_pass"
    result = hcaptcha_live.HCaptchaLiveSolver().solve(
        sitekey="sk", url="https://example.com"
    )
    assert result.success is True
    assert result.token == "P1_NO_CHALLENGE"


def test_live_solver_requires_sitekey_and_url():
    result = hcaptcha_live.HCaptchaLiveSolver().solve(sitekey=None, url=None)
    assert result.success is False
    assert "sitekey" in (result.error or "")


def test_live_solver_reports_proxy_hint_on_network_block(monkeypatch):
    monkeypatch.setattr(hcaptcha_live, "hcaptcha_base_url", lambda: "http://127.0.0.1:1")
    monkeypatch.setattr(hcaptcha_live, "NETWORK", NetworkConfig(timeout_seconds=2))
    result = hcaptcha_live.HCaptchaLiveSolver().solve(
        sitekey="sk", url="https://example.com"
    )
    assert result.success is False
    assert "NONECAP_HCAPTCHA_PROXY" in (result.error or "")
    assert result.metadata["stage"] == "checksiteconfig"


# ---------------------- محرّك القراءة ----------------------


def test_ocr_reads_synthetic_captcha():
    image = np.full((80, 250, 3), 245, np.uint8)
    cv2.putText(image, "AB12", (14, 56), cv2.FONT_HERSHEY_SIMPLEX, 1.7, (20, 20, 20), 3)
    result = read_text(image, allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
    assert result.success is True
    assert result.text == "AB12"
    assert result.confidence > 0.8
    assert result.engine  # "padded" أو "ensemble:balanced" حسب صعوبة الصورة
    assert result.plausibility >= 0.99


def test_ocr_engines_status_reports_available_engine():
    status = engines_status()
    assert isinstance(status["rapidocr"], bool)
    assert status["preferred"] in ("rapidocr", "tesseract", "template")
    assert status["template_fallback"] is True


def test_ocr_returns_empty_for_blank_image():
    blank = np.full((60, 200, 3), 255, np.uint8)
    result = read_text(blank)
    assert result.success is False or not result.text.strip()


# ---------------------- نقاط النهاية ----------------------


@pytest.fixture()
def client(monkeypatch):
    import api_server.main as main_mod

    monkeypatch.setattr(hcaptcha_live, "hcaptcha_base_url", lambda: "http://127.0.0.1:1")
    monkeypatch.setattr(hcaptcha_live, "NETWORK", NetworkConfig(timeout_seconds=2))
    return TestClient(main_mod.app)


def test_hcaptcha_probe_endpoint_reports_unreachable_with_hint(client):
    resp = client.get("/hcaptcha/probe")
    assert resp.status_code == 200
    data = resp.json()
    assert data["reachable"] is False
    assert "error" in data
    assert "hint" in data
    assert data["ocr"]["template_fallback"] is True


def test_ocr_engines_endpoint(client):
    resp = client.get("/ocr/engines")
    assert resp.status_code == 200
    assert resp.json()["preferred"]


def test_hcaptcha_live_endpoint_returns_explicit_failure(client):
    resp = client.post(
        "/hcaptcha/live",
        json={"sitekey": "10000000-ffff-ffff-ffff-000000000001", "url": "https://x.com"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["error"]
    assert data["metadata"]["stage"] == "checksiteconfig"


def test_hcaptcha_live_endpoint_solves_against_fake_server(fake_hcaptcha):
    import api_server.main as main_mod

    client = TestClient(main_mod.app)
    resp = client.post(
        "/hcaptcha/live",
        json={
            "sitekey": "10000000-ffff-ffff-ffff-000000000001",
            "url": "https://accounts.hcaptcha.com/demo",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["token"] == "P1_TOKEN_OK"
    assert data["answer"] == "AB12"


# ---------------------- الاحتياطات (موثوقية) ----------------------


def test_solver_opens_breaker_after_repeated_network_failure(monkeypatch):
    """أعطال متتالية تفتح قاطع الدائرة، فيصبح الفشل فوريًا وواضحًا."""
    from solver_engine.resilience import get_breaker

    breaker = get_breaker("hcaptcha")
    breaker.reset()
    monkeypatch.setattr(hcaptcha_live, "hcaptcha_base_url", lambda: "http://127.0.0.1:1")
    monkeypatch.setattr(hcaptcha_live, "NETWORK", NetworkConfig(timeout_seconds=1))

    solver = hcaptcha_live.HCaptchaLiveSolver(max_rounds=1)
    for _ in range(4):
        result = solver.solve(sitekey="sk", url="https://example.com")
        assert result.success is False

    blocked = solver.solve(sitekey="sk", url="https://example.com")
    assert blocked.metadata["stage"] == "circuit_open"
    assert blocked.metadata["retry_after_seconds"] > 0
    assert "قاطع الدائرة" in (blocked.error or "")
    breaker.reset()


def test_solver_reports_timeout_explicitly(monkeypatch):
    """تعلّق الشبكة يتحول إلى فشل صريح بمهلة، لا انتظار أبدي."""
    from solver_engine.resilience import get_breaker

    get_breaker("hcaptcha").reset()
    solver = hcaptcha_live.HCaptchaLiveSolver(max_rounds=1, call_timeout=0.2)
    monkeypatch.setattr(solver, "checksiteconfig", lambda *a, **k: time.sleep(3))

    started = time.time()
    result = solver.solve(sitekey="sk", url="https://example.com")
    elapsed = time.time() - started

    assert result.success is False
    assert elapsed < 2.5
    assert result.metadata["stage"] == "checksiteconfig"
    assert "مهلة" in (result.error or "") or "Timeout" in (result.error or "")
    get_breaker("hcaptcha").reset()


def test_solver_rotates_strategies_between_rounds(monkeypatch, fake_hcaptcha):
    """كل جولة تبدأ من طريقة عرض مختلفة — تنويع لا تكرار أعمى."""
    orders = []

    def fake_details(data, expected_len=None, deep=False, order=None):
        orders.append(tuple(order) if order else None)
        return {"text": "AB12", "confidence": 0.9, "engine": "stub", "plausibility": 1.0}

    monkeypatch.setattr(hcaptcha_live, "_read_text_detailed", fake_details)
    fake_hcaptcha.expected = "ZZZZ"  # يرفض دائمًا ⇒ نمرّ بكل الجولات

    result = hcaptcha_live.HCaptchaLiveSolver(max_rounds=3).solve(
        sitekey="sk", url="https://example.com"
    )
    assert result.success is False
    assert len(orders) >= 3
    assert len(set(orders[:3])) == 3  # ترتيبات مختلفة فعلًا


def test_solver_returns_actionable_suggestion_on_rejection(fake_hcaptcha, monkeypatch):
    monkeypatch.setattr(
        hcaptcha_live,
        "_read_text_detailed",
        lambda data, expected_len=None, deep=False, order=None: {
            "text": "AB12",
            "confidence": 0.95,
            "engine": "stub",
            "plausibility": 1.0,
        },
    )
    fake_hcaptcha.expected = "ZZZZ"
    result = hcaptcha_live.HCaptchaLiveSolver(max_rounds=2).solve(
        sitekey="sk", url="https://example.com"
    )
    assert result.success is False
    assert result.metadata["suggestion"]
    assert result.metadata["logs"]
    assert all({"round", "action", "ok"} <= set(log) for log in result.metadata["logs"])


def test_live_endpoint_includes_request_id(client):
    response = client.post(
        "/hcaptcha/live",
        json={"sitekey": "sk", "url": "https://example.com", "max_rounds": 1},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["request_id"]
    assert payload["success"] is False


def test_health_resilience_endpoint(client):
    response = client.get("/health/resilience")
    assert response.status_code == 200
    payload = response.json()
    assert "breakers" in payload and "ocr" in payload
    assert payload["ocr"]["ensemble"] is True


# ---------------------- الامتناع (abstain) ----------------------


def test_solver_abstains_instead_of_burning_a_round(fake_hcaptcha, monkeypatch):
    """قراءة منخفضة الثقة ⇒ لا إرسال، وتحدٍّ جديد بدل إحراق محاولة."""
    monkeypatch.setattr(
        hcaptcha_live,
        "_read_text_detailed",
        lambda data, expected_len=None, deep=False, order=None: {
            "text": "AB12",
            "confidence": 0.2,  # منخفضة جدًا
            "engine": "stub",
            "plausibility": 1.0,
        },
    )
    solver = hcaptcha_live.HCaptchaLiveSolver(max_rounds=2, allow_abstain=True)
    result = solver.solve(sitekey="sk", url="https://example.com")

    # الجولة 1 تمتنع (لا إرسال)، والجولة الأخيرة ترسل أفضل ما لديها
    assert fake_hcaptcha.answers and len(fake_hcaptcha.answers) == 1
    assert result.metadata["abstentions"]
    assert result.metadata["abstentions"][0]["send"] is False
    assert any(log["action"] == "abstain" for log in result.metadata["logs"])


def test_solver_sends_last_round_even_when_unsure(fake_hcaptcha, monkeypatch):
    """في الجولة الأخيرة لا معنى للامتناع: نرسل أفضل ما لدينا."""
    monkeypatch.setattr(
        hcaptcha_live,
        "_read_text_detailed",
        lambda data, expected_len=None, deep=False, order=None: {
            "text": "AB12",
            "confidence": 0.2,
            "engine": "stub",
            "plausibility": 1.0,
        },
    )
    result = hcaptcha_live.HCaptchaLiveSolver(max_rounds=1, allow_abstain=True).solve(
        sitekey="sk", url="https://example.com"
    )
    assert len(fake_hcaptcha.answers) == 1
    assert result.success is True  # AB12 صحيحة في المحاكي


def test_abstain_can_be_disabled(fake_hcaptcha, monkeypatch):
    monkeypatch.setattr(
        hcaptcha_live,
        "_read_text_detailed",
        lambda data, expected_len=None, deep=False, order=None: {
            "text": "AB12",
            "confidence": 0.2,
            "engine": "stub",
            "plausibility": 1.0,
        },
    )
    fake_hcaptcha.expected = "ZZZZ"
    solver = hcaptcha_live.HCaptchaLiveSolver(max_rounds=1, allow_abstain=False)
    result = solver.solve(sitekey="sk", url="https://example.com")
    assert result.success is False
    assert len(fake_hcaptcha.answers) == 1  # أرسل رغم انخفاض الثقة


def test_single_character_read_is_always_refused(fake_hcaptcha, monkeypatch):
    """نص بحرف واحد = قراءة فاشلة، حتى لو ادّعى المحرّك ثقة عالية."""
    monkeypatch.setattr(
        hcaptcha_live,
        "_read_text_detailed",
        lambda data, expected_len=None, deep=False, order=None: {
            "text": "A",
            "confidence": 0.99,
            "engine": "stub",
            "plausibility": 1.0,
        },
    )
    solver = hcaptcha_live.HCaptchaLiveSolver(max_rounds=2)
    result = solver.solve(sitekey="sk", url="https://example.com")
    assert result.success is False
    assert fake_hcaptcha.answers == []


# ---------------------- سياسة الامتناع (وحدة مستقلة) ----------------------


def test_abstain_thresholds_and_hard_refusal():
    from solver_engine.abstain import decide, threshold_for_round

    sure = decide(0.95, text="AB12", expected_len=4, rounds_left=2)
    unsure = decide(0.2, text="AB12", expected_len=4, rounds_left=2)
    last_round = decide(0.2, text="AB12", rounds_left=0)
    single = decide(0.99, text="A", rounds_left=2)

    assert sure.send is True and sure.probability > 0.8
    assert unsure.send is False and unsure.retry_advice
    assert last_round.send is True  # لا محاولات ⇒ أرسل أفضل تخمين
    assert single.send is False  # لكن حرف واحد يُرفض دائمًا
    # العتبة تتراجع مع الجولات حتى لا نبقى ممتنعين بلا نهاية
    assert threshold_for_round(1) > threshold_for_round(3)
    assert threshold_for_round(3) >= 0.2


def test_abstain_gate_uses_shape_signal_not_confidence():
    """القياس أثبت أن الثقة لا تفصل الصحيح عن الخطأ — الشكل هو ما يفصل.

    الأرقام الحقيقية على 24 صورة: الصحيح ثقة 0.95 وشكل 1.00، والخطأ ثقة 0.90
    وشكل 0.84. أي عتبة على الثقة وحدها ترفض صحيحًا بقدر ما ترفض خطأً.
    """
    from solver_engine.abstain import decide

    # ثقة عالية + شكل سليم ⇒ يُرسل
    good = decide(0.95, text="AB12", expected_len=4, rounds_left=1, plausibility=1.0)
    # ثقة عالية جدًا + شكل متناقض ⇒ يمتنع (هذا ما فشل خطأً قبل الإصلاح)
    doubtful = decide(1.0, text="Y7H9D", rounds_left=1, plausibility=0.69)

    assert good.send is True
    assert doubtful.send is False
    assert doubtful.probability < good.probability
    assert doubtful.extra.get("shape_doubt") is True


def test_abstain_improves_precision_on_real_batch(monkeypatch):
    """انحدار: على دفعة حقيقية، الامتناع يرفع الدقة لكل محاولة ولا يخسر صحيحًا."""
    from solver_engine import bench
    from solver_engine import ocr_plus as op
    from solver_engine.abstain import decide
    from solver_engine.ocr import read_text

    items = bench.dataset(count=8, seed=7, tier="realistic")
    sent = 0
    sent_correct = 0
    abstained_wrong = 0
    abstained_total = 0
    for item in items:
        result = read_text(item["image"], allowlist=op.DEFAULT_CHARSET, level="fast")
        decision = decide(
            confidence=result.confidence,
            text=result.text or "",
            rounds_left=1,
            plausibility=result.plausibility,
        )
        correct = result.text == item["label"]
        if decision.send:
            sent += 1
            sent_correct += int(correct)
        else:
            abstained_total += 1
            abstained_wrong += int(not correct)

    assert sent > 0
    # كل ما امتنع عنه النظام لم يكن صحيحًا (هذا هو مكسب الامتناع كله)
    assert abstained_wrong == abstained_total
    # والدقة بين ما أُرسل أعلى من الدقة العامة على نفس الدفعة
    overall = sum(
        1
        for item in items
        if read_text(item["image"], allowlist=op.DEFAULT_CHARSET, level="fast").text
        == item["label"]
    ) / len(items)
    assert sent_correct / sent >= overall
