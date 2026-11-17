#!/usr/bin/env python3
"""إثبات عملي لمسار hCaptcha المجاني — بلا إنترنت وبلا خدمة مدفوعة.

يبني هذا السكربت محاكيًا محليًا صغيرًا يتصرّف مثل hCaptcha تمامًا
(``/checksiteconfig`` ← ``/getcaptcha`` ← ``/checkcaptcha``)، ويعرض تحدي نصّي
حقيقي كصورة، ثم يشغّل ``HCaptchaLiveSolver`` نفسه المستخدم مع hCaptcha الحقيقية.

التشغيل:
    python examples/hcaptcha_live_demo.py
    python examples/hcaptcha_live_demo.py --text 7KQ9      # نص آخر
    python examples/hcaptcha_live_demo.py --real           # محاولة على hCaptcha الحقيقية

في الوضع ``--real`` سيستدعي hcaptcha.com فعليًا؛ إن كان مزوّد الشبكة يحجب
النطاق فسترى رسالة الحجب الصريحة مع الحل (تمرير وكيل عبر NONECAP_HCAPTCHA_PROXY).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from solver_engine import hcaptcha_live  # noqa: E402
from solver_engine.hcaptcha_live import HCaptchaLiveSolver, parse_challenge  # noqa: E402
from solver_engine.net import NetworkConfig  # noqa: E402
from solver_engine.ocr import engines_status, read_text_bytes  # noqa: E402

GREEN, RED, DIM, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[0m"


def _render(text: str) -> bytes:
    """يرسم صورة تحدي نصّي شبيهة بتحديات hCaptcha (ضوضاء + خطوط)."""
    img = np.full((80, 260, 3), 248, np.uint8)
    cv2.putText(img, text, (16, 56), cv2.FONT_HERSHEY_SIMPLEX, 1.8, (18, 18, 18), 3, cv2.LINE_AA)
    rng = np.random.default_rng(7)
    for _ in range(3):
        p1 = (int(rng.integers(0, 260)), int(rng.integers(0, 80)))
        p2 = (int(rng.integers(0, 260)), int(rng.integers(0, 80)))
        cv2.line(img, p1, p2, (135, 135, 135), 1, cv2.LINE_AA)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


class Simulator(BaseHTTPRequestHandler):
    """محاكي بروتوكول hCaptcha: نفس المسارات ونفس شكل الاستجابات."""

    text = "AB12"
    calls: list[str] = []

    def _json(self, payload: dict, code: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/checksiteconfig"):
            Simulator.calls.append("checksiteconfig")
            return self._json({"pass": False, "c": {"req": "REQ", "hostToken": "HOST"}})
        if self.path.startswith("/img/"):
            Simulator.calls.append("img")
            body = _render(Simulator.text)
            self.send_response(200)
            self.send_header("content-type", "image/png")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return None
        return self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        size = int(self.headers.get("content-length", 0))
        body = json.loads(self.rfile.read(size) or b"{}")
        if self.path.startswith("/getcaptcha"):
            Simulator.calls.append("getcaptcha")
            return self._json(
                {
                    "c": {
                        "request_type": "text",
                        "requester_question": "Type the characters you see",
                        "image_urls": ["/img/challenge.png"],
                        "key": "KEY-1",
                    }
                }
            )
        if self.path.startswith("/checkcaptcha"):
            Simulator.calls.append("checkcaptcha")
            answer = str(body.get("text", "")).strip().upper()
            if answer == Simulator.text.upper():
                return self._json({"generated_pass_UUID": "P1_SIMULATED_PASS_TOKEN"})
            return self._json({"error": "invalid answer"})
        return self._json({"error": "not found"}, 404)

    def log_message(self, *args) -> None:  # noqa: D102
        pass


def run_offline(text: str) -> int:
    Simulator.text = text
    Simulator.calls = []
    server = HTTPServer(("127.0.0.1", 0), Simulator)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    base = f"http://127.0.0.1:{port}"
    hcaptcha_live.hcaptcha_base_url = lambda: base  # type: ignore[assignment]
    hcaptcha_live.NETWORK = NetworkConfig(timeout_seconds=20)  # type: ignore[assignment]

    print(f"{DIM}محاكي hCaptcha محلي: {base}{RESET}")
    print(f"{DIM}محرّكات القراءة: {engines_status()}{RESET}\n")

    # 1) تحليل التحدي كما يصل من الشبكة
    challenge = parse_challenge(
        {
            "c": {
                "request_type": "text",
                "image_urls": ["/img/challenge.png"],
                "key": "KEY-1",
            }
        }
    )
    print(f"التحدي: نوع={challenge.kind} صور={len(challenge.image_urls)}")

    # 2) قراءة الصورة بالـ OCR المحلي
    img = read_text_bytes(_render(text), allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
    print(f"قراءة الصورة: {img.text!r} ثقة={img.confidence:.3f} محرّك={img.engine} زمن={img.elapsed_ms:.0f}ms")

    # 3) الحل الكامل عبر البروتوكول
    result = HCaptchaLiveSolver(max_rounds=2).solve(
        sitekey="10000000-ffff-ffff-ffff-000000000001",
        url="https://accounts.hcaptcha.com/demo",
    )
    print(f"\nالنتيجة: success={result.success} token={result.token} answer={result.text!r}")
    print(f"نداءات البروتوكول: {' → '.join(Simulator.calls)}")

    if result.success and result.text == text:
        print(f"{GREEN}نجح المسار الكامل: قراءة + إرسال + استلام pass token.{RESET}")
        server.shutdown()
        return 0
    print(f"{RED}فشل: {result.error}{RESET}")
    server.shutdown()
    return 1


def run_real(sitekey: str, url: str) -> int:
    print(f"{DIM}محاولة حقيقية على {url} — مفتاح {sitekey}{RESET}")
    print(f"{DIM}محرّكات القراءة: {engines_status()}{RESET}")
    solver = HCaptchaLiveSolver(max_rounds=2)
    result = asyncio.run(asyncio.to_thread(solver.solve, sitekey=sitekey, url=url))
    print(f"\nsuccess={result.success} token={result.token} answer={result.text!r}")
    print(f"error={result.error}")
    print(f"metadata={json.dumps(result.metadata, ensure_ascii=False)}")
    if result.success:
        print(f"{GREEN}تم الحل على hCaptcha الحقيقية.{RESET}")
        return 0
    print(f"{RED}لم ينجح من هذه الشبكة — راجع نص الخطأ أعلاه (غالبًا حجب نطاق أو تحدي صور).{RESET}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="إثبات مسار hCaptcha المجاني")
    parser.add_argument("--text", default="AB12", help="نص التحدي في الوضع المحلي")
    parser.add_argument("--real", action="store_true", help="محاولة على hCaptcha الحقيقية")
    parser.add_argument(
        "--sitekey", default="10000000-ffff-ffff-ffff-000000000001", help="مفتاح موقع hCaptcha"
    )
    parser.add_argument("--url", default="https://accounts.hcaptcha.com/demo", help="صفحة الموقع")
    args = parser.parse_args()
    return run_real(args.sitekey, args.url) if args.real else run_offline(args.text)


if __name__ == "__main__":
    raise SystemExit(main())
