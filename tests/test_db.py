"""Tests for the detection database."""

import time

import pytest

from birdcam.db import DetectionDB


@pytest.fixture
def db(tmp_path):
    d = DetectionDB(tmp_path / "test.db")
    yield d
    d.close()


def test_insert_and_get(db):
    detection_id = db.insert(
        timestamp=time.time(),
        confidence=0.85,
        bbox=(10.0, 20.0, 100.0, 200.0),
        image_path="images/2024-01-01/120000_000.jpg",
        thumbnail_path="thumbnails/2024-01-01/120000_000.jpg",
    )
    assert detection_id == 1

    det = db.get(detection_id)
    assert det is not None
    assert det.confidence == 0.85
    assert det.bbox == (10.0, 20.0, 100.0, 200.0)
    assert det.favorite is False
    assert det.burst_paths == []


def test_list_detections_ordering(db):
    now = time.time()
    db.insert(now - 100, 0.7, (0, 0, 1, 1), "a.jpg", "a_t.jpg")
    db.insert(now - 50, 0.9, (0, 0, 1, 1), "b.jpg", "b_t.jpg")
    db.insert(now, 0.6, (0, 0, 1, 1), "c.jpg", "c_t.jpg")

    dets = db.list_detections()
    # newest first
    assert dets[0].image_path == "c.jpg"
    assert dets[1].image_path == "b.jpg"
    assert dets[2].image_path == "a.jpg"


def test_filter_by_confidence(db):
    now = time.time()
    db.insert(now, 0.4, (0, 0, 1, 1), "low.jpg", "low_t.jpg")
    db.insert(now, 0.8, (0, 0, 1, 1), "high.jpg", "high_t.jpg")

    dets = db.list_detections(min_confidence=0.5)
    assert len(dets) == 1
    assert dets[0].image_path == "high.jpg"


def test_count(db):
    now = time.time()
    db.insert(now, 0.9, (0, 0, 1, 1), "a.jpg", "a_t.jpg")
    db.insert(now, 0.3, (0, 0, 1, 1), "b.jpg", "b_t.jpg")

    assert db.count() == 2
    assert db.count(min_confidence=0.5) == 1


def test_favorites(db):
    now = time.time()
    did = db.insert(now, 0.9, (0, 0, 1, 1), "a.jpg", "a_t.jpg")
    db.set_favorite(did, True)

    det = db.get(did)
    assert det.favorite is True

    dets = db.list_detections(favorites_only=True)
    assert len(dets) == 1

    db.set_favorite(did, False)
    dets = db.list_detections(favorites_only=True)
    assert len(dets) == 0


def test_burst_paths(db):
    now = time.time()
    did = db.insert(
        now, 0.9, (0, 0, 1, 1), "a.jpg", "a_t.jpg",
        burst_paths=["burst/001.jpg", "burst/002.jpg"],
    )
    det = db.get(did)
    assert det.burst_paths == ["burst/001.jpg", "burst/002.jpg"]


def test_get_nonexistent(db):
    assert db.get(999) is None


def test_get_dates(db):
    # Insert two detections on different dates
    db.insert(1704067200.0, 0.9, (0, 0, 1, 1), "a.jpg", "a_t.jpg")  # 2024-01-01
    db.insert(1704153600.0, 0.8, (0, 0, 1, 1), "b.jpg", "b_t.jpg")  # 2024-01-02

    dates = db.get_dates()
    assert len(dates) == 2
    # newest first
    assert dates[0] > dates[1]


def test_classifications_today_uses_classified_at(db):
    now = time.time()
    yesterday = now - 86400
    # Live classification today
    today_id = db.insert(now, 0.9, (0, 0, 1, 1), "a.jpg", "a_t.jpg")
    db.set_species(today_id, "Robin")
    # Backfilled classification of an old detection — happens "now", so counts
    backfill_id = db.insert(yesterday, 0.9, (0, 0, 1, 1), "b.jpg", "b_t.jpg")
    db.set_species(backfill_id, "Sparrow")
    # Old detection, never classified — should not count
    db.insert(yesterday, 0.9, (0, 0, 1, 1), "c.jpg", "c_t.jpg")

    assert db.classifications_today() == 2


def test_pagination(db):
    now = time.time()
    for i in range(10):
        db.insert(now + i, 0.9, (0, 0, 1, 1), f"{i}.jpg", f"{i}_t.jpg")

    page1 = db.list_detections(limit=3, offset=0)
    page2 = db.list_detections(limit=3, offset=3)
    assert len(page1) == 3
    assert len(page2) == 3
    assert page1[0].id != page2[0].id
