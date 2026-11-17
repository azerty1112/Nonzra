"""اختبارات مسار hCaptcha المباشر — عبر محاكي محلي لبروتوكول hCaptcha.

المحاكي يخدم نفس المسارات الثلاثة (checksiteconfig → getcaptcha → checkcaptcha)
ويُعيد صورة تحدٍّ نصية حقيقية، فنختبر المسار كاملًا دون أي خدمة خارجية.
"""

import json
import threading

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
        hcaptcha_live, "_read_text_from", lambda url: ("WRONG9", 0.9, "stub")
    )
    result = hcaptcha_live.HCaptchaLiveSolver().solve(
        sitekey="sk", url="https://example.com"
    )
    assert result.success is False
    assert "invalid answer" in (result.error or "")
    # المحلّل يعيد المحاولة بعد الرفض (max_rounds الافتراضي = 2)
    assert len(fake_hcaptcha.answers) == 2
    assert len({a["key"] for a in fake_hcaptcha.answers}) == 2


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
    assert result.engine in ("rapidocr", "tesseract")


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
