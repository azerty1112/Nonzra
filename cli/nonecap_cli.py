"""أداة سطر الأوامر (CLI) لسيرفر NoneCap Clone."""

import argparse
import base64
import json
import sys
from typing import Any, Optional, Dict

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


def cmd_create_key(args: argparse.Namespace) -> int:
    with _client(args.base_url, args.timeout, args.api_key) as c:
        data = {}
        if args.name:
            data["name"] = args.name
        try:
            r = c.post("/api/keys", json=data)
            r.raise_for_status()
            print(json.dumps(r.json(), ensure_ascii=False, indent=2))
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"خطأ: {exc}", file=sys.stderr)
            return 1


def cmd_list_keys(args: argparse.Namespace) -> int:
    with _client(args.base_url, args.timeout, args.api_key) as c:
        try:
            r = c.get("/api/keys")
            r.raise_for_status()
            print(json.dumps(r.json(), ensure_ascii=False, indent=2))
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"خطأ: {exc}", file=sys.stderr)
            return 1


def cmd_delete_key(args: argparse.Namespace) -> int:
    with _client(args.base_url, args.timeout, args.api_key) as c:
        try:
            r = c.delete(f"/api/keys/{args.key_id}")
            r.raise_for_status()
            print(json.dumps(r.json(), ensure_ascii=False, indent=2))
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"خطأ: {exc}", file=sys.stderr)
            return 1


def cmd_self_improve_stats(args: argparse.Namespace) -> int:
    with _client(args.base_url, args.timeout, args.api_key) as c:
        try:
            r = c.get("/self-improve/stats")
            r.raise_for_status()
            print(json.dumps(r.json(), ensure_ascii=False, indent=2))
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"خطأ: {exc}", file=sys.stderr)
            return 1


def cmd_self_improve_retrain(args: argparse.Namespace) -> int:
    with _client(args.base_url, args.timeout, args.api_key) as c:
        try:
            r = c.post("/self-improve/retrain")
            r.raise_for_status()
            print(json.dumps(r.json(), ensure_ascii=False, indent=2))
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"خطأ: {exc}", file=sys.stderr)
            return 1


def cmd_capabilities(args: argparse.Namespace) -> int:
    """عرض أنواع الكبتشا المدعومة فعليًا على السيرفر."""
    with _client(args.base_url, args.timeout, args.api_key) as c:
        try:
            r = c.get("/capabilities")
            r.raise_for_status()
            data = r.json()
            if getattr(args, "json", False):
                print(json.dumps(data, ensure_ascii=False, indent=2))
                return 0
            print(f"الإصدار: {data.get('version', '-')}")
            print(f"عدد المحرّكات: {data.get('total_solvers', 0)}")
            print("الأنواع المدعومة:")
            for t in data.get("supported_types", []):
                solvers = data.get("types", {}).get(t, {}).get("solvers", [])
                print(f"  • {t:<22} ({', '.join(solvers) or '—'})")
            missing = data.get("unsupported_types") or []
            if missing:
                print("غير مدعومة (تحتاج خدمة خارجية):")
                print("  " + ", ".join(missing))
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"خطأ: {exc}", file=sys.stderr)
            return 1


def cmd_math(args: argparse.Namespace) -> int:
    """حساب تعبير رياضي أو حل صورة كبتشا حسابية."""
    payload: Dict[str, Any] = {}
    if args.image:
        with open(args.image, "rb") as fh:
            payload["image_b64"] = base64.b64encode(fh.read()).decode("ascii")
        payload["expression"] = ""
    else:
        payload["expression"] = args.expression
    with _client(args.base_url, args.timeout, args.api_key) as c:
        try:
            r = c.post("/math/evaluate", json=payload)
            r.raise_for_status()
            data = r.json()
            if data.get("success"):
                print(data.get("answer"))
            else:
                print(f"فشل: {data.get('error')}", file=sys.stderr)
                return 1
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"خطأ: {exc}", file=sys.stderr)
            return 1


def cmd_generate(args: argparse.Namespace) -> int:
    """توليد صور كبتشا صناعية (لتدريب النموذج أو للاختبار)."""
    import os

    payload = {
        "count": args.count,
        "length": args.length,
        "width": args.width,
        "height": args.height,
        "with_png": True,
    }
    if args.charset:
        payload["charset"] = args.charset
    if args.seed is not None:
        payload["seed"] = args.seed
    with _client(args.base_url, args.timeout, args.api_key) as c:
        try:
            r = c.post("/synthetic/batch", json=payload)
            r.raise_for_status()
            items = r.json().get("items", [])
        except Exception as exc:  # noqa: BLE001
            print(f"خطأ: {exc}", file=sys.stderr)
            return 1

    out_dir = args.out
    os.makedirs(out_dir, exist_ok=True)
    labels = []
    for i, item in enumerate(items):
        text = item.get("text", "")
        path = os.path.join(out_dir, f"{i:04d}_{text}.png")
        with open(path, "wb") as fh:
            fh.write(base64.b64decode(item["png_base64"]))
        labels.append(f"{os.path.basename(path)},{text}")
        print(path)
    if args.labels:
        with open(args.labels, "w", encoding="utf-8") as fh:
            fh.write("filename,text\n" + "\n".join(labels) + "\n")
        print(f"ملف التسميات: {args.labels}")
    print(f"تم توليد {len(items)} صورة في {out_dir}")
    return 0


def cmd_parse_math(args: argparse.Namespace) -> int:
    """حساب تعبير محليًا دون الحاجة للسيرفر."""
    from solver_engine.math import evaluate_expression, format_number, normalize_expression

    expression = normalize_expression(args.expression)
    ok, value, error = evaluate_expression(expression)
    if not ok or value is None:
        print(f"فشل: {error}", file=sys.stderr)
        return 1
    print(format_number(value))
    return 0


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

    sp = sub.add_parser("create-key", help="إنشاء مفتاح API جديد")
    sp.add_argument("--name", default=None)
    sp.set_defaults(func=cmd_create_key)

    sp = sub.add_parser("list-keys", help="قائمة مفاتيح API")
    sp.set_defaults(func=cmd_list_keys)

    sp = sub.add_parser("delete-key", help="إلغاء مفتاح API")
    sp.add_argument("key_id")
    sp.set_defaults(func=cmd_delete_key)

    sp = sub.add_parser("self-improve-stats", help="إحصائيات التعلم الذاتي")
    sp.set_defaults(func=cmd_self_improve_stats)

    sp = sub.add_parser("self-improve-retrain", help="إعادة تدريب النموذج الذاتي")
    sp.set_defaults(func=cmd_self_improve_retrain)

    sp = sub.add_parser("capabilities", help="عرض أنواع الكبتشا المدعومة والمحرّكات")
    sp.add_argument("--json", action="store_true", help="إخراج JSON")
    sp.set_defaults(func=cmd_capabilities)

    sp = sub.add_parser("math", help="حساب تعبير رياضي أو حل صورة كبتشا حسابية عبر السيرفر")
    sp.add_argument("expression", nargs="?", default="", help="مثال: 5+3 أو '12 × 4'")
    sp.add_argument("--image", default=None, help=" صورة كبتشا حسابية بدلًا من التعبير")
    sp.set_defaults(func=cmd_math)

    sp = sub.add_parser("calc", help="حساب تعبير محليًا (بدون سيرفر)")
    sp.add_argument("expression")
    sp.set_defaults(func=cmd_parse_math)

    sp = sub.add_parser("generate", help="توليد صور كبتشا صناعية للتدريب/الاختبار")
    sp.add_argument("--count", type=int, default=10)
    sp.add_argument("--length", type=int, default=4)
    sp.add_argument("--width", type=int, default=160)
    sp.add_argument("--height", type=int, default=60)
    sp.add_argument("--charset", default=None)
    sp.add_argument("--seed", type=int, default=None)
    sp.add_argument("--out", default="synthetic_captchas")
    sp.add_argument("--labels", default=None, help="مسار ملف CSV للتسميات")
    sp.set_defaults(func=cmd_generate)

    sp = sub.add_parser("interactive", help="وضع تفاعلي للحل والتحكم")
    sp.add_argument("--base-url", default="http://localhost:8000", help="رابط السيرفر")
    sp.add_argument("--api-key", default=None, help="مفتاح API")
    sp.set_defaults(func=cmd_interactive)

    return p


def cmd_interactive(args: argparse.Namespace) -> int:
    """وضع تفاعلي للحل والتحكم في السيرفر."""
    base_url = args.base_url or "http://localhost:8000"
    api_key = args.api_key

    print("=" * 60)
    print("نظام NoneCap Clone - الوضع التفاعلي")
    print("=" * 60)
    print(f"السيرفر: {base_url}")
    print(f"مفتاح API: {'محدد' if api_key else 'غير محدد'}")
    print("=" * 60)
    print("الأوامر المتاحة:")
    print("  health       - فحص حالة السيرفر")
    print("  stats        - عرض الإحصائيات")
    print("  solve        - حل صورة كبتشا")
    print("  auto         - حل تلقائي كامل")
    print("  jobs         - عرض المهام المجدولة")
    print("  users        - عرض المستخدمين (يتطلب صلاحية مشرف)")
    print("  help         - عرض هذه المساعدة")
    print("  exit/quit    - الخروج")
    print("=" * 60)

    while True:
        try:
            cmd = input("\nnonecap> ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\n-> خروجالنظام.")
            return 0

        if not cmd:
            continue

        if cmd in ("exit", "quit", "q"):
            print("-> خروجالنظام.")
            return 0

        elif cmd == "help":
            print("الأوامر المتاحة:")
            print("  health     - فحص حالة السيرفر")
            print("  stats      - عرض الإحصائيات")
            print("  solve      - حل صورة كبتشا")
            print("  auto       - حل تلقائي كامل")
            print("  jobs       - عرض المهام المجدولة")
            print("  users      - عرض المستخدمين (يتطلب صلاحية مشرف)")
            print("  help       - عرض هذه المساعدة")
            print("  exit/quit  - الخروج")

        elif cmd == "health":
            try:
                import httpx
                with httpx.Client(base_url=base_url, timeout=args.timeout,
                                  headers={"Authorization": f"Bearer {api_key}"} if api_key else {}) as c:
                    r = c.get("/health")
                    r.raise_for_status()
                    print(json.dumps(r.json(), ensure_ascii=False, indent=2))
            except Exception as exc:
                print(f"خطأ: {exc}")

        elif cmd == "stats":
            try:
                import httpx
                with httpx.Client(base_url=base_url, timeout=args.timeout,
                                  headers={"Authorization": f"Bearer {api_key}"} if api_key else {}) as c:
                    r = c.get("/stats")
                    r.raise_for_status()
                    print(json.dumps(r.json(), ensure_ascii=False, indent=2))
            except Exception as exc:
                print(f"خطأ: {exc}")

        elif cmd == "solve":
            image_path = input("مسار صورة الكبتشا: ").strip()
            captcha_type = input("نوع الكبتشا (image, hcaptcha, ...): ").strip() or "image"
            try:
                import httpx
                with open(image_path, "rb") as f:
                    image_data = f.read()
                with httpx.Client(base_url=base_url, timeout=args.timeout,
                                  headers={"Authorization": f"Bearer {api_key}"} if api_key else {}) as c:
                    files = {"file": ("captcha.png", image_data, "image/png")}
                    data = {"captcha_type": captcha_type}
                    r = c.post("/solve/image", files=files, data=data)
                    r.raise_for_status()
                    result = r.json()
                    print(json.dumps(result, ensure_ascii=False, indent=2))
            except Exception as exc:
                print(f"خطأ: {exc}")

        elif cmd == "auto":
            image_path = input("مسار صورة الكبتشا (اترك فارغًا للكشف التلقائي): ").strip()
            captcha_type = input("نوع الكبتشا (اترك فارغًا للكشف التلقائي): ").strip()
            try:
                import httpx
                files = {}
                auto_data: Dict[str, Any] = {"captcha_type": captcha_type or "image", "human_like": "false", "max_escalations": "2"}
                if image_path:
                    with open(image_path, "rb") as f:
                        files = {"file": ("captcha.png", f.read(), "image/png")}
                with httpx.Client(base_url=base_url, timeout=args.timeout,
                                  headers={"Authorization": f"Bearer {api_key}"} if api_key else {}) as c:
                    r = c.post("/auto", files=files, data=auto_data)
                    r.raise_for_status()
                    result = r.json()
                    print(json.dumps(result, ensure_ascii=False, indent=2))
            except Exception as exc:
                print(f"خطأ: {exc}")

        elif cmd == "jobs":
            try:
                import httpx
                with httpx.Client(base_url=base_url, timeout=args.timeout,
                                  headers={"Authorization": f"Bearer {api_key}"} if api_key else {}) as c:
                    r = c.get("/schedule/jobs")
                    r.raise_for_status()
                    jobs = r.json()
                    print(json.dumps(jobs, ensure_ascii=False, indent=2))
            except Exception as exc:
                print(f"خطأ: {exc}")

        elif cmd == "users":
            try:
                import httpx
                with httpx.Client(base_url=base_url, timeout=args.timeout,
                                  headers={"Authorization": f"Bearer {api_key}"} if api_key else {}) as c:
                    r = c.get("/users")
                    r.raise_for_status()
                    users = r.json()
                    print(json.dumps(users, ensure_ascii=False, indent=2))
            except Exception as exc:
                print(f"خطأ: {exc}")

        else:
            print(f"أمر غير معروف: {cmd}. استخدم 'help' للمساعدة.")

    return 0


_GLOBAL_FLAGS = ("--base-url", "--timeout", "--api-key")


def _normalize_argv(argv):
    """يسمح بتمرير الخيارات العامة قبل الأمر أو بعده (مثل git)."""
    if argv is None:
        argv = sys.argv[1:]
    argv = list(argv)
    global_args = []
    rest = []
    i = 0
    while i < len(argv):
        token = argv[i]
        matched = None
        for flag in _GLOBAL_FLAGS:
            if token == flag:
                if i + 1 < len(argv):
                    global_args.extend([flag, argv[i + 1]])
                    i += 2
                else:
                    i += 1
                matched = flag
                break
            if token.startswith(flag + "="):
                global_args.append(token)
                i += 1
                matched = flag
                break
        if matched is None:
            rest.append(token)
            i += 1
    return global_args + rest


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(_normalize_argv(argv))
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
