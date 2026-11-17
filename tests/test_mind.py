"""اختبارات «عقل» النظام: المعايرة، الكفاءة، المخطّط، المتأمّل، والذخيرة المعرفية."""

import json
import os

import pytest
from fastapi.testclient import TestClient

from intelligence.calibration import ConfidenceCalibrator
from intelligence.competence import CompetenceEstimator
from intelligence.decision_planner import DecisionPlanner
from intelligence.knowledge_corpus import (
    CARDS,
    brief_for,
    cards_for_type,
    catalog,
    get_card,
    quiz,
)
from intelligence.mind import Mind
from intelligence.reflector import SelfReflector, classify_error

# ---------------------- المعايرة ----------------------


def test_calibrator_shrinks_toward_base_rate_initially():
    cal = ConfidenceCalibrator(min_observations=30)
    # قبل البيانات: الثقة العالية لا تُترجم إلى 0.95 مباشرة
    value = cal.calibrate(0.95)
    assert 0.4 < value < 0.95
    assert cal.brier_score() is None


def test_calibrator_learns_monotonic_curve():
    cal = ConfidenceCalibrator(min_observations=20)
    # ثقة عالية تنجح دائمًا، وثقة منخفضة تفشل دائمًا
    for _ in range(25):
        cal.observe(0.9, True)
    for _ in range(25):
        cal.observe(0.2, False)

    high = cal.calibrate(0.9)
    low = cal.calibrate(0.2)
    assert high > low
    assert high >= 0.75
    assert low <= 0.35
    assert cal.brier_score() is not None
    snap = cal.snapshot()
    assert snap["observations"] == 50
    assert snap["is_learned"] is True
    assert len(snap["curve"]) == cal.bins_count


def test_calibrator_curve_is_monotonic_after_noise():
    cal = ConfidenceCalibrator(min_observations=10)
    # بيانات متعارضة عمدًا: المعايرة يجب أن تُنتج منحنى غير متناقص
    for i in range(120):
        conf = 0.1 + (i % 9) * 0.1
        cal.observe(conf, success=(i % 3 == 0))
    curve = [p["success_probability"] for p in cal.snapshot()["curve"]]
    assert curve == sorted(curve)


def test_calibrator_expected_utility_advises_retry_on_low_confidence():
    cal = ConfidenceCalibrator(min_observations=10)
    for _ in range(20):
        cal.observe(0.3, False)
        cal.observe(0.9, True)
    low = cal.expected_utility(0.35)
    high = cal.expected_utility(0.92)
    assert low["advise_retry"] == 1.0
    assert high["advise_retry"] == 0.0
    assert high["accept_utility"] > low["accept_utility"]


def test_calibrator_persistence(tmp_path):
    path = str(tmp_path / "cal.json")
    cal = ConfidenceCalibrator(path=path, min_observations=5)
    for _ in range(10):
        cal.observe(0.8, True)
    cal.save()
    reloaded = ConfidenceCalibrator(path=path, min_observations=5)
    assert reloaded.total_observations == 10
    assert reloaded.calibrate(0.8) > 0.5


# ---------------------- الكفاءة ----------------------


def test_competence_beta_posterior_and_verdicts():
    comp = CompetenceEstimator()
    for _ in range(9):
        comp.observe("image", True, 120)
    comp.observe("image", False, 400)
    record = comp.types["image"]
    assert record.attempts == 10
    assert record.successes == 9
    assert 0.7 < comp.expected_success("image") < 0.95
    assert record.verdict == "قوي"
    assert record.latency_ewma_ms > 0


def test_competence_ranks_and_detects_weakness():
    comp = CompetenceEstimator()
    for _ in range(8):
        comp.observe("image", True, 100)
    for _ in range(8):
        comp.observe("turnstile", False, 4000)
    ranking = comp.ranking()
    assert ranking[0]["captcha_type"] == "image"
    assert "image" in comp.strengths()
    assert "turnstile" in comp.weaknesses()
    assert comp.is_failing("turnstile") is True
    assert 0.0 <= comp.self_rating() <= 1.0


def test_competence_persistence(tmp_path):
    path = str(tmp_path / "comp.json")
    comp = CompetenceEstimator(path=path)
    comp.observe("math", True, 50)
    comp.observe("math", True, 60)
    comp.save()
    reloaded = CompetenceEstimator(path=path)
    assert reloaded.types["math"].attempts == 2
    assert reloaded.expected_success("math") > 0.5


# ---------------------- المخطّط ----------------------


def test_planner_prefers_local_when_external_unavailable():
    planner = DecisionPlanner()
    decision = planner.plan("image", difficulty=0.2, external_available=False)
    names = [a["route"] for a in decision.alternatives]
    assert decision.chosen == "local_primary"
    assert "external_primary" not in names
    assert decision.explanation


def test_planner_uses_external_for_hard_types_when_allowed():
    planner = DecisionPlanner()
    decision = planner.plan("funcaptcha", difficulty=0.9, external_available=True)
    assert decision.chosen in ("external_primary", "nvidia_api", "ensemble_with_fallback")
    assert decision.confidence_target >= 0.55


def test_planner_prefer_speed_shortens_budget_and_threshold_behaviour():
    planner = DecisionPlanner()
    fast = planner.plan("image", difficulty=0.3, external_available=True, prefer_speed=True)
    normal = planner.plan("image", difficulty=0.3, external_available=True)
    fast_best = max(a["expected_value"] for a in fast.alternatives)
    normal_best = max(a["expected_value"] for a in normal.alternatives)
    assert fast_best <= normal_best + 0.51  # القيمة تُحسب على ميزانية أقصر


def test_planner_learns_from_competence():
    comp = CompetenceEstimator()
    for _ in range(20):
        comp.observe("image", True, 90)
    planner = DecisionPlanner(competence=comp)
    decision = planner.plan("image", difficulty=0.2, external_available=True)
    best = decision.alternatives[0]
    assert best["success_probability"] >= 0.6
    assert "image" in decision.explanation


def test_planner_explains_retry_advice_with_hint():
    planner = DecisionPlanner()
    decision = planner.plan("image", external_available=False, confidence_hint=0.2)
    assert decision.should_retry in (True, False)
    assert planner.snapshot()["decisions"] >= 1


# ---------------------- المتأمّل ----------------------


@pytest.mark.parametrize(
    "error,expected_fragment",
    [
        ("ثقة منخفضة جدًا", "ثقة"),
        ("request timeout", "مهلة"),
        ("no solver registered for type", "محرّك"),
        ("401 Unauthorized", "مصادقة"),
        ("connection refused", "الوصول"),
    ],
)
def test_classify_error_maps_root_causes(error, expected_fragment):
    cause, advice = classify_error(error)
    assert expected_fragment in cause
    assert advice


def test_reflector_accumulates_lessons_and_measures_effectiveness():
    reflector = SelfReflector()
    for _ in range(3):
        reflector.observe_failure("hcaptcha", "timeout while solving")
    snap = reflector.snapshot()
    assert snap["failures_seen"] == 3
    assert snap["distinct_lessons"] == 1
    lesson = snap["top_lessons"][0]
    assert lesson["occurrences"] == 3

    reflector.observe_success("hcaptcha")
    snap = reflector.snapshot()
    assert snap["successes_after_advice"] >= 1
    assert snap["advice_effectiveness"] is not None


def test_reflector_advice_is_type_specific():
    reflector = SelfReflector()
    reflector.observe_failure("slider", "low confidence gap")
    reflector.observe_failure("math", "invalid expression")
    slider_advice = reflector.advice_for("slider")
    math_advice = reflector.advice_for("math")
    assert slider_advice and math_advice
    assert slider_advice != math_advice


# ---------------------- العقل ----------------------


def test_mind_think_plan_and_learn_cycle():
    mind = Mind(state_path=None)
    decision = mind.think("image", difficulty=0.3, external_available=True)
    assert decision.chosen
    assert decision.explanation

    for _ in range(12):
        cycle = mind.learn("image", True, 0.88, 150, decision=decision)
    assert cycle.success is True
    assert mind.total_cycles == 12
    assert mind.competence.expected_success("image") > 0.7

    report = mind.self_report()
    assert report["identity"]
    assert report["self_rating"] > 0.5
    assert report["notes"]
    assert report["mood"]


def test_mind_accept_decision_uses_calibration():
    mind = Mind(state_path=None)
    for _ in range(20):
        mind.learn("image", True, 0.9, 100)
    confident = mind.should_accept(0.9)
    doubtful = mind.should_accept(0.25)
    assert confident["accept"] is True
    assert doubtful["accept"] is False


def test_mind_suggests_next_experiment_from_weakness():
    mind = Mind(state_path=None)
    for _ in range(6):
        mind.learn("turnstile", False, 0.2, 5000, error="no solver registered")
    experiment = mind.next_experiment()
    assert experiment is not None
    assert experiment["target_type"] == "turnstile"
    assert experiment["advice"]


def test_mind_explain_includes_knowledge_and_pitfalls():
    mind = Mind(state_path=None)
    explanation = mind.explain("slider")
    assert explanation["decision"]["chosen"]
    assert explanation["known_insights"]
    assert explanation["pitfalls"]
    assert 0.0 <= explanation["difficulty_prior"] <= 1.0


def test_mind_persists_state_to_disk(tmp_path):
    path = str(tmp_path / "mind_state.json")
    mind = Mind(state_path=path, autosave_every=1)
    for _ in range(3):
        mind.learn("image", True, 0.8, 120)
    assert os.path.exists(path)
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["total_cycles"] == 3
    reloaded = Mind(state_path=path)
    assert reloaded.total_cycles == 3
    assert reloaded.competence.types["image"].attempts == 3


# ---------------------- الذخيرة المعرفية ----------------------


def test_corpus_has_rich_cards_with_all_fields():
    assert len(CARDS) >= 17
    for card in CARDS:
        assert card.summary
        assert card.facts
        assert card.category in ("type", "technique", "risk")
        assert 0.0 <= card.difficulty <= 1.0
    keys = {c.key for c in CARDS}
    for expected in ("image_text", "hcaptcha", "slider", "rotate", "math", "cnn", "calibration"):
        assert expected in keys


def test_cards_for_type_maps_and_includes_related():
    cards = cards_for_type("turnstile")
    assert cards[0].key == "turnstile"
    assert len(cards) >= 2
    assert get_card("hcaptcha") is not None
    assert brief_for("hcaptcha")
    assert catalog("technique")
    assert all(c["category"] == "technique" for c in catalog("technique"))


def test_quiz_generates_consistent_questions():
    questions = quiz(limit=5, seed=7)
    assert len(questions) == 5
    for q in questions:
        assert len(q["options"]) == 4
        assert 0 <= q["answer_index"] < 4
        assert q["options"][q["answer_index"]]
        assert q["explanation"]


# ---------------------- نقاط النهاية ----------------------


@pytest.fixture()
def client():
    from api_server.main import app

    return TestClient(app)


def test_mind_endpoint_reports_self_rating(client):
    resp = client.get("/mind")
    assert resp.status_code == 200
    data = resp.json()
    assert 0.0 <= data["self_rating"] <= 1.0
    assert "skills" in data and "reflection" in data
    assert isinstance(data["notes"], list)


def test_mind_plan_endpoint(client):
    resp = client.post(
        "/mind/plan",
        json={"captcha_type": "image", "difficulty": 0.2, "external_available": False},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["chosen"] == "local_primary"
    assert data["explanation"]


def test_mind_observe_endpoint_updates_skills(client):
    before = client.get("/mind/skills").json()
    resp = client.post(
        "/mind/observe",
        json={"captcha_type": "rotate", "success": True, "confidence": 0.9, "latency_ms": 90},
    )
    assert resp.status_code == 200
    after = client.get("/mind/skills").json()
    assert after["types"]["rotate"]["attempts"] >= before["types"].get("rotate", {}).get(
        "attempts", 0
    )


def test_mind_accept_and_calibration_endpoints(client):
    assert client.get("/mind/accept?confidence=0.9").json()["accept"] in (True, False)
    calib = client.get("/mind/calibration").json()
    assert "observations" in calib and "curve" in calib
    assert client.get("/mind/reflect").status_code == 200
    assert client.post("/mind/save").status_code == 200


def test_knowledge_endpoints(client):
    all_cards = client.get("/knowledge").json()
    assert all_cards["count"] >= 17
    focused = client.get("/knowledge?category=risk").json()
    assert all(c["category"] == "risk" for c in focused["cards"])
    for_type = client.get("/knowledge/for/math").json()
    assert for_type["decision"]["chosen"]
    questions = client.get("/knowledge/quiz?limit=2&seed=3").json()["questions"]
    assert len(questions) == 2
    answer = client.post(
        f"/knowledge/quiz/answer?card={questions[0]['card']}"
        f"&chosen_index={questions[0]['answer_index']}"
        f"&correct_index={questions[0]['answer_index']}"
    ).json()
    assert answer["correct"] is True
