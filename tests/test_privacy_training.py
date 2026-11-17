"""اختبارات خصوصية عينات التدريب: لا صور افتراضيًا، سقف، حذف، وكتابة آمنة."""

import json

import pytest

from intelligence.training import CaptchaDataset


@pytest.fixture()
def dataset(tmp_path):
    return CaptchaDataset(path=str(tmp_path / "samples.json"), flush_every=1000)


def test_images_are_not_stored_by_default(dataset):
    """أهم ضمان: الوضع الافتراضي لا يكتب صور المستخدمين على القرص."""
    dataset.add("image", image_b64="SENSITIVE", text="AB12", confidence=0.95)
    assert dataset.stats()["with_images"] == 0
    assert dataset.samples[0].image_b64 is None
    dataset.flush()
    assert "SENSITIVE" not in open(dataset.path, encoding="utf-8").read()


def test_opt_in_storage_keeps_images(tmp_path):
    store = CaptchaDataset(path=str(tmp_path / "on.json"), store_images=True, flush_every=1)
    store.add("image", image_b64="KEEP-ME", text="AB12", confidence=0.95)
    assert store.stats()["with_images"] == 1
    assert "KEEP-ME" in open(store.path, encoding="utf-8").read()


def test_legacy_file_with_images_is_scrubbed_on_load(tmp_path):
    """ترقية آمنة: ملف قديم فيه صور يُنظَّف فورًا إن كان التخزين معطّلًا."""
    path = tmp_path / "legacy.json"
    path.write_text(
        json.dumps([{"id": "1", "captcha_type": "image", "image_b64": "OLD", "text": "AB12"}]),
        encoding="utf-8",
    )
    loaded = CaptchaDataset(path=str(path))
    assert loaded.stats()["with_images"] == 0
    assert "OLD" not in path.read_text(encoding="utf-8")


def test_max_samples_drops_oldest(tmp_path):
    capped = CaptchaDataset(
        path=str(tmp_path / "cap.json"), max_samples=3, ttl_hours=0, flush_every=1000
    )
    for index in range(6):
        capped.add("image", text=f"T{index}")
    assert capped.stats()["total"] == 3
    # الأحدث يبقى
    assert [s.text for s in capped.samples] == ["T3", "T4", "T5"]
    assert capped.dropped >= 3


def test_purge_all_and_by_type(dataset):
    dataset.add("image", text="A")
    dataset.add("image", text="B")
    dataset.add("hcaptcha", text="C")
    assert dataset.purge(captcha_type="image") == 2
    assert dataset.stats()["total"] == 1
    assert dataset.purge() == 1
    assert dataset.stats()["total"] == 0


def test_batched_writes_are_deferred(dataset, tmp_path):
    """الكتابة متأخرة: لا ملف قبل بلوغ العتبة (كانت O(n) لكل طلب)."""
    dataset.add("image", text="A")
    dataset.add("image", text="B")
    assert not (tmp_path / "samples.json").exists()
    assert dataset.flush() is True
    assert (tmp_path / "samples.json").exists()


def test_atomic_write_leaves_no_temp_files(tmp_path):
    ds = CaptchaDataset(path=str(tmp_path / "atomic.json"), flush_every=1)
    ds.add("image", text="A")
    ds.flush()
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_stats_reports_privacy_mode(dataset):
    stats = dataset.stats()
    assert stats["store_images"] is False
    assert "لا تُحفظ صور" in stats["privacy"]


def test_endpoints_expose_state_and_deletion():
    from fastapi.testclient import TestClient

    import api_server.main as main_mod

    client = TestClient(main_mod.app)
    state = client.get("/training/samples")
    assert state.status_code == 200
    assert "store_images" in state.json()

    purged = client.delete("/training/samples")
    assert purged.status_code == 200
    assert "purged" in purged.json()


def test_retrain_marker_behaviour_is_preserved(dataset):
    """انحدار: `mark_retrained` كانت موجودة قبل إعادة الكتابة — لا تُفقد."""
    dataset.mark_retrained()
    dataset.add("image", text="X", source="retrain_marker", confirmed=True)
    assert dataset.count_by_source("retrain_marker") == 2
