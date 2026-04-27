"""Save detection images and manage storage lifecycle."""

import io
import logging
import time
from datetime import datetime
from pathlib import Path

from PIL import Image

from birdcam.buffer import Frame
from birdcam.config import StorageConfig
from birdcam.db import DetectionDB

log = logging.getLogger(__name__)


class Storage:
    def __init__(self, config: StorageConfig, db: DetectionDB):
        self._config = config
        self._db = db
        self._base = config.base_path
        self._images_dir = self._base / "images"
        self._thumbs_dir = self._base / "thumbnails"
        self._burst_dir = self._base / "burst"
        for d in (self._images_dir, self._thumbs_dir, self._burst_dir):
            d.mkdir(parents=True, exist_ok=True)

    def save_detection(
        self,
        frame: Frame,
        confidence: float,
        bbox: tuple[float, float, float, float],
        burst_frames: list[Frame] | None = None,
    ) -> int:
        """Save a detection: main image, thumbnail, optional burst frames.

        Returns the detection ID.
        """
        ts = frame.timestamp
        dt = datetime.fromtimestamp(ts)
        date_str = dt.strftime("%Y-%m-%d")
        time_str = dt.strftime("%H%M%S_%f")  # HHMMSS_microseconds

        # Save main image
        img_dir = self._images_dir / date_str
        img_dir.mkdir(exist_ok=True)
        img_path = img_dir / f"{time_str}.jpg"
        img_path.write_bytes(frame.jpeg_data)

        # Generate and save thumbnail
        thumb_dir = self._thumbs_dir / date_str
        thumb_dir.mkdir(exist_ok=True)
        thumb_path = thumb_dir / f"{time_str}.jpg"
        self._make_thumbnail(frame.jpeg_data, thumb_path)

        # Save burst frames
        burst_paths: list[str] = []
        if burst_frames:
            burst_base = self._burst_dir / date_str / time_str
            burst_base.mkdir(parents=True, exist_ok=True)
            for i, bf in enumerate(burst_frames):
                bp = burst_base / f"burst_{i:03d}.jpg"
                bp.write_bytes(bf.jpeg_data)
                burst_paths.append(str(bp.relative_to(self._base)))

        # Insert into database
        detection_id = self._db.insert(
            timestamp=ts,
            confidence=confidence,
            bbox=bbox,
            image_path=str(img_path.relative_to(self._base)),
            thumbnail_path=str(thumb_path.relative_to(self._base)),
            burst_paths=burst_paths,
        )

        log.info(
            "Saved detection #%d: confidence=%.2f at %s",
            detection_id,
            confidence,
            dt.strftime("%Y-%m-%d %H:%M:%S"),
        )
        return detection_id

    def delete_detection(self, detection_id: int) -> None:
        """Delete a detection and all its files (image, thumbnail, burst)."""
        det = self._db.get(detection_id)
        if det is None:
            return

        # Delete image and thumbnail
        for rel_path in (det.image_path, det.thumbnail_path):
            full = self._base / rel_path
            if full.exists():
                full.unlink()

        # Delete burst frames
        for bp in det.burst_paths:
            full = self._base / bp
            if full.exists():
                full.unlink()
            # Clean up empty burst directory
            parent = full.parent
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()

        self._db.delete(detection_id)
        log.info("Deleted detection #%d", detection_id)

    def prune_old_bursts(self) -> int:
        """Delete burst frames older than the configured retention period.

        Skips favorites. Returns the number of detections pruned.
        """
        days = self._config.prune_burst_after_days
        entries = self._db.get_burst_paths_older_than(days)
        pruned = 0
        for detection_id, paths in entries:
            for p in paths:
                full = self._base / p
                if full.exists():
                    full.unlink()
            # Clean up empty burst directories
            for p in paths:
                parent = (self._base / p).parent
                if parent.exists() and not any(parent.iterdir()):
                    parent.rmdir()
            self._db.clear_burst_paths(detection_id)
            pruned += 1

        if pruned:
            log.info("Pruned burst frames from %d old detections", pruned)
        return pruned

    def resolve_path(self, relative_path: str) -> Path:
        """Resolve a relative path to an absolute one under base_path."""
        resolved = (self._base / relative_path).resolve()
        # Ensure it's under base_path to prevent path traversal
        if not str(resolved).startswith(str(self._base.resolve())):
            raise ValueError("Path traversal not allowed")
        return resolved

    def _make_thumbnail(self, jpeg_data: bytes, dest: Path) -> None:
        img = Image.open(io.BytesIO(jpeg_data))
        w = self._config.thumbnail_width
        ratio = w / img.width
        h = int(img.height * ratio)
        img = img.resize((w, h), Image.LANCZOS)
        img.save(dest, "JPEG", quality=80)
