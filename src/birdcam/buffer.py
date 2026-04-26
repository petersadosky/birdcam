"""Thread-safe circular buffer for JPEG frames."""

import threading
import time
from dataclasses import dataclass


@dataclass(slots=True)
class Frame:
    jpeg_data: bytes
    timestamp: float


class FrameBuffer:
    """Fixed-size circular buffer of JPEG frames.

    Thread-safe: the detector thread writes frames, and on detection
    we snapshot the buffer to get the pre-detection burst.
    """

    def __init__(self, max_frames: int):
        self._max = max_frames
        self._buf: list[Frame] = []
        self._lock = threading.Lock()

    def add(self, jpeg_data: bytes) -> Frame:
        """Add a frame, returning the Frame object."""
        frame = Frame(jpeg_data=jpeg_data, timestamp=time.time())
        with self._lock:
            self._buf.append(frame)
            if len(self._buf) > self._max:
                self._buf.pop(0)
        return frame

    def snapshot(self) -> list[Frame]:
        """Return a copy of the current buffer contents (oldest first)."""
        with self._lock:
            return list(self._buf)

    def __len__(self) -> int:
        with self._lock:
            return len(self._buf)
