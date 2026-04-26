"""Tests for the storage layer."""

import io
import time

import pytest
from PIL import Image

from birdcam.buffer import Frame
from birdcam.config import StorageConfig
from birdcam.db import DetectionDB
from birdcam.storage import Storage


def _make_jpeg(width=640, height=480) -> bytes:
    """Create a minimal valid JPEG."""
    img = Image.new("RGB", (width, height), color=(100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def storage_env(tmp_path):
    config = StorageConfig(base_path=tmp_path, thumbnail_width=160)
    db = DetectionDB(tmp_path / "test.db")
    stor = Storage(config, db)
    yield stor, db, tmp_path
    db.close()


def test_save_detection_creates_files(storage_env):
    stor, db, base = storage_env
    jpeg = _make_jpeg()
    frame = Frame(jpeg_data=jpeg, timestamp=time.time())

    detection_id = stor.save_detection(
        frame=frame,
        confidence=0.85,
        bbox=(10.0, 20.0, 100.0, 200.0),
    )

    det = db.get(detection_id)
    assert det is not None

    # Check files exist
    img_path = base / det.image_path
    thumb_path = base / det.thumbnail_path
    assert img_path.exists()
    assert thumb_path.exists()

    # Thumbnail should be smaller
    thumb = Image.open(thumb_path)
    assert thumb.width == 160


def test_save_detection_with_burst(storage_env):
    stor, db, base = storage_env
    jpeg = _make_jpeg()
    frame = Frame(jpeg_data=jpeg, timestamp=time.time())
    burst = [Frame(jpeg_data=_make_jpeg(), timestamp=time.time()) for _ in range(3)]

    detection_id = stor.save_detection(
        frame=frame,
        confidence=0.9,
        bbox=(0, 0, 1, 1),
        burst_frames=burst,
    )

    det = db.get(detection_id)
    assert len(det.burst_paths) == 3
    for bp in det.burst_paths:
        assert (base / bp).exists()


def test_prune_old_bursts(storage_env):
    stor, db, base = storage_env
    # Create a detection with burst, timestamped 100 days ago
    old_time = time.time() - (100 * 86400)
    jpeg = _make_jpeg()
    frame = Frame(jpeg_data=jpeg, timestamp=old_time)
    burst = [Frame(jpeg_data=_make_jpeg(), timestamp=old_time)]

    detection_id = stor.save_detection(
        frame=frame,
        confidence=0.9,
        bbox=(0, 0, 1, 1),
        burst_frames=burst,
    )

    det = db.get(detection_id)
    burst_file = base / det.burst_paths[0]
    assert burst_file.exists()

    # Prune (config default is 90 days)
    pruned = stor.prune_old_bursts()
    assert pruned == 1
    assert not burst_file.exists()

    # DB should show empty burst paths
    det = db.get(detection_id)
    assert det.burst_paths == []

    # Main image and thumbnail should still exist
    assert (base / det.image_path).exists()
    assert (base / det.thumbnail_path).exists()


def test_prune_skips_favorites(storage_env):
    stor, db, base = storage_env
    old_time = time.time() - (100 * 86400)
    jpeg = _make_jpeg()
    frame = Frame(jpeg_data=jpeg, timestamp=old_time)
    burst = [Frame(jpeg_data=_make_jpeg(), timestamp=old_time)]

    detection_id = stor.save_detection(
        frame=frame,
        confidence=0.9,
        bbox=(0, 0, 1, 1),
        burst_frames=burst,
    )
    db.set_favorite(detection_id, True)

    pruned = stor.prune_old_bursts()
    assert pruned == 0

    det = db.get(detection_id)
    assert len(det.burst_paths) == 1
    assert (base / det.burst_paths[0]).exists()


def test_resolve_path_prevents_traversal(storage_env):
    stor, _, _ = storage_env
    with pytest.raises(ValueError, match="traversal"):
        stor.resolve_path("../../etc/passwd")
