"""عرض توضيحي لجميع ميزات الذكاء المضافة لمشروع NoneCap Clone."""

import numpy as np
from PIL import Image, ImageDraw
import io

from solver_engine import registry, SolverResult
from intelligence import (
    CaptchaAnalyzer,
    IntelligentMonitor,
    IntelligentSolverStrategy,
    SolveEvent,
    HumanBehavior,
    HumanProfile,
    AutoDetector,
    AdaptiveTuner,
    LearningEngine,
    AutoOrchestrator,
)
from solver_engine.base import BaseSolver, CaptchaType, SolverResult
from solver_engine.registry import SolverRegistry
from solver_engine.db import Database


def make_captcha(text="AB12", size=(200, 80), noisy=False):
    img = Image.new("RGB", size, color="white")
    draw = ImageDraw.Draw(img)
    x = 10
    for ch in text:
        draw.text((x, 25), ch, fill="black")
        x += 45
    if noisy:
        # إضافة ضوضاء
        arr = np.array(img)
        noise = np.random.randint(0, 60, arr.shape, dtype=np.uint8)
        arr = np.clip(arr.astype(int) + noise, 0, 255).astype(np.uint8)
        img = Image.fromarray(arr)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def demo_analysis():
    print("=" * 60)
    print("1. الذكاء التحليلي - تحليل صعوبة الكبتشا")
    print("=" * 60)
    analyzer = CaptchaAnalyzer()
    for label, data in [("سهل", make_captcha("AB12")), ("ضوضائي", make_captcha("XYZ9", noisy=True))]:
        analysis = analyzer.analyze_image(np.array(Image.open(io.BytesIO(data)).convert("RGB")))
        rec = analyzer.recommend(analysis)
        print(f"\n[{label}] difficulty={analysis.difficulty_score} "
              f"success={analysis.estimated_success_rate} "
              f"time={analysis.estimated_time_ms}ms")
        print(f"  الاستراتيجية الموصى بها: {rec['strategy']}")
        print(f"  الميزات: {analysis.features}")
        print(f"  التحذيرات: {analysis.warnings}")


def demo_human_behavior():
    print("\n" + "=" * 60)
    print("2. الذكاء التفاعلي - محاكاة السلوك البشري")
    print("=" * 60)
    hb = HumanBehavior(HumanProfile(typing_wpm=40, hesitation_chance=0.15), seed=42)
    print("\nتسلسل كتابة 'NoneCap' مع تأخيرات بشرية:")
    for ch, delay in hb.human_typing_sequence("NoneCap"):
        print(f"  '{ch}' بعد {delay*1000:.0f}ms")
    print("\nمسار ماوس من (100,100) إلى (300,200):")
    path = hb.human_mouse_path((100, 100), (300, 200))
    for x, y, d in path[:5]:
        print(f"  ({x:.1f}, {y:.1f}) تأخير {d*1000:.0f}ms")
    print(f"  ... ({len(path)} نقطة إجمالاً)")
    print(f"  تردد قبل الإجراء: {hb.should_hesitate()}")
    print(f"  احتمال خطأ كتابي: {hb.should_make_error()}")


def demo_monitor():
    print("\n" + "=" * 60)
    print("3. الذكاء المراقب - المراقبة واكتشاف الشذوذ")
    print("=" * 60)
    mon = IntelligentMonitor(window_minutes=60)
    now = "2026-11-15T10:00:00+00:00"
    # تسجيل أحداث مختلطة
    events = [
        SolveEvent(now, "image", True, 1200, 0.9, "local"),
        SolveEvent(now, "image", True, 1500, 0.85, "local"),
        SolveEvent(now, "image", False, 3000, 0.2, "local", "فشل OCR"),
        SolveEvent(now, "image", False, 3200, 0.1, "local", "فشل OCR"),
        SolveEvent(now, "image", False, 3100, 0.15, "local", "فشل OCR"),
        SolveEvent(now, "hcaptcha", True, 9000, 0.9, "external"),
    ]
    for ev in events:
        alerts = mon.record(ev)
        for a in alerts:
            print(f"  [تنبيه {a.level}] {a.message}")
    report = mon.report()
    print(f"\nالتقرير: إجمالي={report['total']}, نجاح={report['success_rate']:.1%}, "
          f"متوسط زمن={report['avg_latency_ms']}ms")
    print(f"  التوصية: {report['recommendation']}")


def demo_strategy():
    print("\n" + "=" * 60)
    print("4. الذكاء الحل - اختيار الاستراتيجية الذكية")
    print("=" * 60)
    strat = IntelligentSolverStrategy()
    img_data = make_captcha("HELLO", noisy=True)
    import cv2
    img = cv2.imdecode(np.frombuffer(img_data, np.uint8), cv2.IMREAD_COLOR)
    decision = strat.decide("image", image=img)
    print(f"\nالاستراتيجية المختارة: {decision.strategy}")
    print(f"  محلي: {decision.use_local}, خارجي: {decision.use_external}")
    print(f"  الحد الأدنى للثقة: {decision.confidence_threshold}")
    print(f"  أقصى محاولات: {decision.max_attempts}")
    print("  المبررات:")
    for r in decision.reasoning:
        print(f"    - {r}")


def demo_detector():
    print("\n" + "=" * 60)
    print("5. الكشف التلقائي - تصنيف نوع الكبتشا من الصورة")
    print("=" * 60)
    import cv2
    img_data = make_captcha("AB12")
    img = cv2.imdecode(np.frombuffer(img_data, np.uint8), cv2.IMREAD_COLOR)
    det = AutoDetector().detect(img)
    print(f"\nالنوع المكتشف: {det.captcha_type} (ثقة {det.confidence})")
    print(f"الميزات: {det.features}")


def demo_tuner_learning():
    print("\n" + "=" * 60)
    print("6. الضبط والتعلّم الذاتي - أفضل معاملات واستراتيجية")
    print("=" * 60)
    tuner = AdaptiveTuner(epsilon=0.0, seed=7)
    good = {"psm": 8, "threshold": "adaptive", "denoise": False}
    bad = {"psm": 7, "threshold": "otsu", "denoise": True}
    for _ in range(5):
        tuner.record("image", good, True, 0.92, 120)
        tuner.record("image", bad, False, 0.2, 800)
    print(f"\nأفضل معاملات تعلمها الضابط: {tuner.best('image')}")

    learner = LearningEngine(epsilon=0.2, seed=7)
    for arm, rew in [
        ("local_primary", 0.9),
        ("local_primary", 0.85),
        ("ensemble_with_fallback", 0.6),
        ("external_primary", 0.3),
    ]:
        learner.update(arm, rew)
    print(f"أفضل استراتيجية تعلمها المحرك: {learner.best_arm()}")
    print(f"لقطة التعلّم: {learner.snapshot()}")


def demo_orchestrator():
    print("\n" + "=" * 60)
    print("7. المنسّق الذاتي الكامل - خط أنابيب من البداية للنهاية")
    print("=" * 60)

    class DemoSolver(BaseSolver):
        captcha_type = CaptchaType.IMAGE

        def solve(self, *args, **kwargs) -> SolverResult:
            return SolverResult(
                success=True,
                captcha_type=CaptchaType.IMAGE,
                text="AB12",
                confidence=0.95,
                response_time_ms=80,
            )

    reg = SolverRegistry()
    reg.register(DemoSolver())
    orch = AutoOrchestrator(
        registry=reg,
        learner=LearningEngine(epsilon=0.0, seed=1),
        tuner=AdaptiveTuner(epsilon=0.0, seed=1),
    )
    out = orch.solve(captcha_type="image", max_escalations=2)
    print(f"\nالنتيجة: نجاح={out.result.success}, نص={out.result.text}")
    print(f"الاستراتيجية: {out.strategy_used}, التصعيدات: {out.escalations}")
    print("أثر القرارات:")
    for line in out.trace:
        print(f"  - {line}")
    print(f"الزمن الكلي: {out.total_time_ms}ms")


def main():
    demo_analysis()
    demo_human_behavior()
    demo_monitor()
    demo_strategy()
    demo_detector()
    demo_tuner_learning()
    demo_orchestrator()
    print("\n" + "=" * 60)
    print("انتهى العرض التوضيحي للذكاء المتكامل والذاتي")
    print("=" * 60)


if __name__ == "__main__":
    main()
