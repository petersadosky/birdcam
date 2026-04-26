"""Tests for the circular frame buffer."""

from birdcam.buffer import FrameBuffer


def test_add_and_snapshot():
    buf = FrameBuffer(max_frames=3)
    buf.add(b"frame1")
    buf.add(b"frame2")
    frames = buf.snapshot()
    assert len(frames) == 2
    assert frames[0].jpeg_data == b"frame1"
    assert frames[1].jpeg_data == b"frame2"


def test_eviction():
    buf = FrameBuffer(max_frames=2)
    buf.add(b"a")
    buf.add(b"b")
    buf.add(b"c")
    frames = buf.snapshot()
    assert len(frames) == 2
    assert frames[0].jpeg_data == b"b"
    assert frames[1].jpeg_data == b"c"


def test_snapshot_returns_copy():
    buf = FrameBuffer(max_frames=5)
    buf.add(b"x")
    snap1 = buf.snapshot()
    buf.add(b"y")
    snap2 = buf.snapshot()
    assert len(snap1) == 1
    assert len(snap2) == 2


def test_len():
    buf = FrameBuffer(max_frames=3)
    assert len(buf) == 0
    buf.add(b"a")
    assert len(buf) == 1
    buf.add(b"b")
    buf.add(b"c")
    buf.add(b"d")  # evicts "a"
    assert len(buf) == 3


def test_timestamp_set():
    buf = FrameBuffer(max_frames=5)
    frame = buf.add(b"data")
    assert frame.timestamp > 0
