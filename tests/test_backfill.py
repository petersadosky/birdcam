"""Tests for the backfill loop."""

import io
import time

import pytest
from PIL import Image

from birdcam.backfill import Backfiller, IDLE_INTERVAL_SECONDS, ACTIVE_INTERVAL_SECONDS
from birdcam.buffer import Frame
from birdcam.config import StorageConfig
from birdcam.db import DetectionDB
from birdcam.storage import Storage


def _make_jpeg() -> bytes:
    img = Image.new("RGB", (32, 32), color=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


class FakeClassifier:
    """Stand-in for Classifier with controllable success/failure."""

    def __init__(self, enabled=True, fail_first_n=0, return_value="Test Bird"):
        self.enabled = enabled
        self.calls: list[int] = []
        self._fail_remaining = fail_first_n
        self._return_value = return_value
        self._db = None  # set by tests that need set_species()

    def classify(self, detection_id: int, jpeg_data: bytes):
        self.calls.append(detection_id)
        if self._fail_remaining > 0:
            self._fail_remaining -= 1
            return None
        if self._db is not None:
            self._db.set_species(detection_id, self._return_value)
        return self._return_value


class LimitedFakeClassifier:
    """Mirrors Classifier's real per-day limit gate."""

    def __init__(self, db, max_per_day: int):
        self.enabled = True
        self.calls: list[int] = []
        self._db = db
        self._max = max_per_day

    def classify(self, detection_id: int, jpeg_data: bytes):
        if self._db.classifications_today() >= self._max:
            return None
        self.calls.append(detection_id)
        self._db.set_species(detection_id, "Test Bird")
        return "Test Bird"


@pytest.fixture
def env(tmp_path):
    db = DetectionDB(tmp_path / "test.db")
    storage = Storage(StorageConfig(base_path=tmp_path), db)
    yield db, storage, tmp_path
    db.close()


_uniq = 0


def _insert_detection(tmp_path, db, with_image=True, ts=None) -> int:
    global _uniq
    _uniq += 1
    if ts is None:
        ts = time.time()
    rel = f"images/2026-04-29/{int(ts*1e6)}_{_uniq}.jpg"
    if with_image:
        full = tmp_path / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(_make_jpeg())
    return db.insert(
        timestamp=ts,
        confidence=0.9,
        bbox=(0, 0, 10, 10),
        image_path=rel,
        thumbnail_path=rel,
    )


def test_classifies_unclassified_detection(env):
    db, storage, tmp_path = env
    det_id = _insert_detection(tmp_path, db)
    classifier = FakeClassifier()
    classifier._db = db

    bf = Backfiller(classifier, db, storage)
    interval = bf._tick()

    assert classifier.calls == [det_id]
    assert db.get(det_id).species == "Test Bird"
    assert interval == ACTIVE_INTERVAL_SECONDS


def test_idle_when_classifier_disabled(env):
    db, storage, tmp_path = env
    _insert_detection(tmp_path, db)
    classifier = FakeClassifier(enabled=False)

    bf = Backfiller(classifier, db, storage)
    interval = bf._tick()

    assert classifier.calls == []
    assert interval == IDLE_INTERVAL_SECONDS


def test_idle_when_no_unclassified(env):
    db, storage, _ = env
    classifier = FakeClassifier()

    bf = Backfiller(classifier, db, storage)
    interval = bf._tick()

    assert classifier.calls == []
    assert interval == IDLE_INTERVAL_SECONDS


def test_skips_detection_with_missing_image(env):
    db, storage, tmp_path = env
    det_id = _insert_detection(tmp_path, db, with_image=False)
    classifier = FakeClassifier()
    classifier._db = db

    bf = Backfiller(classifier, db, storage)
    bf._tick()

    assert classifier.calls == []
    assert det_id in bf._skip
    assert db.get(det_id).species is None

    # Subsequent ticks should also skip — no infinite retry
    interval = bf._tick()
    assert classifier.calls == []
    assert interval == IDLE_INTERVAL_SECONDS


def test_backs_off_on_classify_failure(env):
    db, storage, tmp_path = env
    det_id = _insert_detection(tmp_path, db)
    classifier = FakeClassifier(fail_first_n=1)
    classifier._db = db

    bf = Backfiller(classifier, db, storage)
    interval = bf._tick()

    assert classifier.calls == [det_id]
    assert db.get(det_id).species is None
    assert interval == IDLE_INTERVAL_SECONDS

    # Next tick succeeds (e.g. Wi-Fi back) and same row gets classified
    interval = bf._tick()
    assert classifier.calls == [det_id, det_id]
    assert db.get(det_id).species == "Test Bird"


def test_processes_oldest_first(env):
    db, storage, tmp_path = env
    older = _insert_detection(tmp_path, db)
    time.sleep(0.01)
    newer = _insert_detection(tmp_path, db)
    classifier = FakeClassifier()
    classifier._db = db

    bf = Backfiller(classifier, db, storage)
    bf._tick()

    assert classifier.calls[0] == older
    assert classifier.calls[1] == newer


def test_backfill_counts_against_daily_limit(env):
    """Backfilling old-timestamp detections must consume today's API budget."""
    db, storage, tmp_path = env
    # Insert 5 detections with timestamps from previous days
    yesterday = time.time() - 86400
    ids = [
        _insert_detection(tmp_path, db, ts=yesterday - i * 3600)
        for i in range(5)
    ]
    classifier = LimitedFakeClassifier(db, max_per_day=2)

    bf = Backfiller(classifier, db, storage)
    # First tick drains until limit; classify() returns None on the 3rd row
    bf._tick()

    classified = [i for i in ids if db.get(i).species is not None]
    assert len(classified) == 2
    assert db.classifications_today() == 2

    # Further ticks should not classify more
    bf._tick()
    classified = [i for i in ids if db.get(i).species is not None]
    assert len(classified) == 2
