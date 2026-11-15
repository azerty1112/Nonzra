"""أداة سطر الأوامر (CLI) لسيرفر NoneCap Clone."""

import argparse
import base64
import json
import sys
from typing import Any, Optional

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:  # pragma: no cover
    _HTTPX_AVAILABLE = False
    httpx: Any = None  # type: ignore[assignment, no-redef]


def _client(base_url: str, timeout: float, api_key: Optional[str]):
    if httpx is None:
        print("خطأ: حزمة httpx غير مثبتة. شغّل: pip install httpx", file=sys.stderr)
        sys.exit(1)
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout, headers=headers)


def cmd_health(args: argparse.Namespace) -> int:
    with _client(args.base_url, args.timeout, args.api_key) as c:
        try:
            r = c.get("/health")
            r.raise_for_status()
            print(json.dumps(r.json(), ensure_ascii=False, indent=2))
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"خطأ: {exc}", file=sys.stderr)
            return 1


def cmd_stats(args: argparse.Namespace) -> int:
    with _client(args.base_url, args.timeout, args.api_key) as c:
        try:
            r = c.get("/stats")
            r.raise_for_status()
            print(json.dumps(r.json(), ensure_ascii=False, indent=2))
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"خطأ: {exc}", file=sys.stderr)
            return 1


def cmd_solve(args: argparse.Namespace) -> int:
    with _client(args.base_url, args.timeout, args.api_key) as c:
        data = {
            "captcha_type": args.type,
            "sitekey": args.sitekey,
            "url": args.url,
            "action": args.action,
            "cdata": args.cdata,
            "target_color": args.target_color,
            "min_area": args.min_area,
            "psm": args.psm,
            "oem": args.oem,
            "preprocess": args.preprocess,
            "resize_width": args.resize_width,
            "threshold": args.threshold,
        }
        if args.whitelist:
            data["whitelist"] = args.whitelist
        data = {k: v for k, v in data.items() if v is not None}

        files = {}
        if args.image:
            files["file"] = (args.image, open(args.image, "rb"), "image/png")
        if args.template:
            files["template"] = (args.template, open(args.template, "rb"), "image/png")

        try:
            r = c.post(
                f"/solve/{args.type}",
                files=files or None,
                data=data or None,
            )
            r.raise_for_status()
            body = r.json()
            result = body.get("result", body)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get("success") else 1
        except Exception as exc:  # noqa: BLE001
            print(f"خطأ: {exc}", file=sys.stderr)
            return 1
        finally:
            for f in files.values():
                try:
                    f[1].close()
                except Exception:
                    pass


def cmd_async(args: argparse.Namespace) -> int:
    with _client(args.base_url, args.timeout, args.api_key) as c:
        data = {
            "captcha_type": args.type,
            "sitekey": args.sitekey,
            "url": args.url,
            "action": args.action,
            "cdata": args.cdata,
        }
        data = {k: v for k, v in data.items() if v is not None}
        files = {}
        if args.image:
            files["file"] = (args.image, open(args.image, "rb"), "image/png")
        try:
            r = c.post(f"/solve/async/{args.type}", files=files or None, data=data or None)
            r.raise_for_status()
            body = r.json()
            print(f"تم إنشاء المهمة: {body.get('job_id')}")
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"خطأ: {exc}", file=sys.stderr)
            return 1
        finally:
            for f in files.values():
                try:
                    f[1].close()
                except Exception:
                    pass


def cmd_job(args: argparse.Namespace) -> int:
    with _client(args.base_url, args.timeout, args.api_key) as c:
        try:
            r = c.get(f"/job/{args.job_id}")
            r.raise_for_status()
            print(json.dumps(r.json(), ensure_ascii=False, indent=2))
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"خطأ: {exc}", file=sys.stderr)
            return 1


def cmd_auto(args: argparse.Namespace) -> int:
    with _client(args.base_url, args.timeout, args.api_key) as c:
        data = {
            "captcha_type": args.type,
            "sitekey": args.sitekey,
            "url": args.url,
            "human_like": args.human_like,
            "max_escalations": args.max_escalations,
        }
        data = {k: v for k, v in data.items() if v is not None}
        files = {}
        if args.image:
            files["file"] = (args.image, open(args.image, "rb"), "image/png")
        if args.template:
            files["template"] = (args.template, open(args.template, "rb"), "image/png")
        try:
            r = c.post("/auto", files=files or None, data=data or None)
            r.raise_for_status()
            body = r.json()
            print(json.dumps(body, ensure_ascii=False, indent=2))
            return 0 if body.get("result", {}).get("success") else 1
        except Exception as exc:  # noqa: BLE001
            print(f"خطأ: {exc}", file=sys.stderr)
            return 1
        finally:
            for f in files.values():
                try:
                    f[1].close()
                except Exception:
                    pass


def cmd_auto_async(args: argparse.Namespace) -> int:
    with _client(args.base_url, args.timeout, args.api_key) as c:
        data = {
            "captcha_type": args.type,
            "sitekey": args.sitekey,
            "url": args.url,
            "human_like": args.human_like,
            "max_escalations": args.max_escalations,
        }
        data = {k: v for k, v in data.items() if v is not None}
        files = {}
        if args.image:
            files["file"] = (args.image, open(args.image, "rb"), "image/png")
        try:
            r = c.post("/auto/async", files=files or None, data=data or None)
            r.raise_for_status()
            body = r.json()
            print(f"تم إنشاء المهمة الذاتية: {body.get('job_id')}")
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"خطأ: {exc}", file=sys.stderr)
            return 1
        finally:
            for f in files.values():
                try:
                    f[1].close()
                except Exception:
                    pass


def cmd_auto_job(args: argparse.Namespace) -> int:
    with _client(args.base_url, args.timeout, args.api_key) as c:
        try:
            r = c.get(f"/auto/job/{args.job_id}")
            r.raise_for_status()
            print(json.dumps(r.json(), ensure_ascii=False, indent=2))
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"خطأ: {exc}", file=sys.stderr)
            return 1


def cmd_auto_status(args: argparse.Namespace) -> int:
    with _client(args.base_url, args.timeout, args.api_key) as c:
        try:
            r = c.get("/auto/status")
            r.raise_for_status()
            print(json.dumps(r.json(), ensure_ascii=False, indent=2))
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"خطأ: {exc}", file=sys.stderr)
            return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="nonecap", description="CLI لسيرفر NoneCap Clone")
    p.add_argument("--base-url", default="http://localhost:8000", help="رابط السيرفر")
    p.add_argument("--timeout", type=float, default=60.0, help="مهلة الطلب بالثواني")
    p.add_argument("--api-key", default=None, help="مفتاح API اختياري")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("health", help="فحص حالة السيرفر")
    sp.set_defaults(func=cmd_health)

    sp = sub.add_parser("stats", help="الإحصائيات")
    sp.set_defaults(func=cmd_stats)

    sp = sub.add_parser("solve", help="حل كبتشا متزامن")
    sp.add_argument("--type", required=True, help="نوع الكبتشا (image, hcaptcha, recaptcha_v2, turnstile, drag, point)")
    sp.add_argument("--sitekey", default=None)
    sp.add_argument("--url", default=None)
    sp.add_argument("--action", default=None)
    sp.add_argument("--cdata", default=None)
    sp.add_argument("--target-color", dest="target_color", default=None)
    sp.add_argument("--min-area", type=int, default=20)
    sp.add_argument("--image", default=None, help="مسار صورة")
    sp.add_argument("--template", default=None, help="مسار صورة القالب (لـ drag)")
    sp.add_argument("--whitelist", default=None)
    sp.add_argument("--psm", type=int, default=7)
    sp.add_argument("--oem", type=int, default=3)
    sp.add_argument("--preprocess", action="store_true", default=True)
    sp.add_argument("--no-preprocess", dest="preprocess", action="store_false")
    sp.add_argument("--resize-width", type=int, default=400)
    sp.add_argument("--threshold", default="otsu")
    sp.set_defaults(func=cmd_solve)

    sp = sub.add_parser("async", help="إرسال مهمة غير متزامنة")
    sp.add_argument("--type", required=True)
    sp.add_argument("--sitekey", default=None)
    sp.add_argument("--url", default=None)
    sp.add_argument("--action", default=None)
    sp.add_argument("--cdata", default=None)
    sp.add_argument("--image", default=None)
    sp.set_defaults(func=cmd_async)

    sp = sub.add_parser("job", help="استعلام عن حالة مهمة")
    sp.add_argument("job_id")
    sp.set_defaults(func=cmd_job)

    sp = sub.add_parser("auto", help="حل ذاتي كامل (كشف تلقائي + ضبط + تصعيد)")
    sp.add_argument("--type", default=None, help="اتركه فارغًا للكشف التلقائي")
    sp.add_argument("--sitekey", default=None)
    sp.add_argument("--url", default=None)
    sp.add_argument("--image", default=None, help="مسار صورة")
    sp.add_argument("--template", default=None, help="مسار صورة القالب (لـ drag)")
    sp.add_argument("--human-like", dest="human_like", action="store_true", default=False)
    sp.add_argument("--max-escalations", dest="max_escalations", type=int, default=2)
    sp.set_defaults(func=cmd_auto)

    sp = sub.add_parser("auto-async", help="إرسال مهمة ذاتية للعامل الخلفي")
    sp.add_argument("--type", default=None)
    sp.add_argument("--sitekey", default=None)
    sp.add_argument("--url", default=None)
    sp.add_argument("--image", default=None)
    sp.add_argument("--human-like", dest="human_like", action="store_true", default=False)
    sp.add_argument("--max-escalations", dest="max_escalations", type=int, default=2)
    sp.set_defaults(func=cmd_auto_async)

    sp = sub.add_parser("auto-job", help="استعلام عن مهمة ذاتية")
    sp.add_argument("job_id")
    sp.set_defaults(func=cmd_auto_job)

    sp = sub.add_parser("auto-status", help="حالة العامل والتعلّم والضبط")
    sp.set_defaults(func=cmd_auto_status)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
