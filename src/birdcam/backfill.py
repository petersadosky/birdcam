"""Background backfill of species classifications.

Drains detections that have no species label by feeding their saved JPEGs
through the Claude classifier. The classifier already turns network outages,
rate limits, billing problems, and daily-limit hits into a `None` return —
this loop uses that as the signal to back off and retry later, so when the
Pi regains Wi-Fi (or the daily limit resets) the backlog drains on its own.
"""

import logging
import threading

from birdcam.classifier import Classifier
from birdcam.db import DetectionDB
from birdcam.storage import Storage

log = logging.getLogger(__name__)

ACTIVE_INTERVAL_SECONDS = 2.0
IDLE_INTERVAL_SECONDS = 60.0
BATCH_SIZE = 25


class Backfiller:
    def __init__(self, classifier: Classifier, db: DetectionDB, storage: Storage):
        self._classifier = classifier
        self._db = db
        self._storage = storage
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._skip: set[int] = set()

    def start(self) -> None:
        if not self._classifier.enabled:
            log.info("Backfill not started — classifier disabled")
            return
        self._thread = threading.Thread(
            target=self._run, name="backfiller", daemon=True
        )
        self._thread.start()
        log.info("Backfiller started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            interval = self._tick()
            self._stop.wait(timeout=interval)

    def _tick(self) -> float:
        """Process one batch. Returns seconds to wait before the next tick."""
        if not self._classifier.enabled:
            return IDLE_INTERVAL_SECONDS

        rows = [
            d for d in self._db.get_unclassified(limit=BATCH_SIZE)
            if d.id not in self._skip
        ]
        if not rows:
            return IDLE_INTERVAL_SECONDS

        log.info("Backfilling %d detection(s)", len(rows))
        for det in rows:
            if self._stop.is_set():
                return 0

            try:
                image_path = self._storage.resolve_path(det.image_path)
            except ValueError:
                log.warning("Bad image path for detection #%d — skipping", det.id)
                self._skip.add(det.id)
                continue

            if not image_path.exists():
                log.warning(
                    "Image missing for detection #%d at %s — skipping",
                    det.id, image_path,
                )
                self._skip.add(det.id)
                continue

            try:
                jpeg_data = image_path.read_bytes()
            except OSError:
                log.exception("Failed to read image for detection #%d", det.id)
                self._skip.add(det.id)
                continue

            species = self._classifier.classify(det.id, jpeg_data)
            if species is None:
                # Offline, rate-limited, daily-limited, or billing failure.
                # Back off; we'll retry the same row on the next tick.
                return IDLE_INTERVAL_SECONDS

            if self._stop.wait(timeout=ACTIVE_INTERVAL_SECONDS):
                return 0

        return ACTIVE_INTERVAL_SECONDS
