"""Camera capture loop with YOLOv8 bird detection."""

import io
import logging
import threading
import time

from birdcam.buffer import FrameBuffer
from birdcam.config import Config
from birdcam.storage import Storage

log = logging.getLogger(__name__)

# COCO class index for "bird"
BIRD_CLASS_ID = 14


class Detector:
    """Captures frames from the Pi Camera, runs YOLO inference, saves detections."""

    def __init__(self, config: Config, storage: Storage):
        self._config = config
        self._storage = storage
        self._running = False
        self._thread: threading.Thread | None = None

        max_frames = int(config.camera.fps * config.detection.buffer_seconds)
        self._buffer = FrameBuffer(max_frames=max(max_frames, 1))

        self._cooldown = config.detection.cooldown_seconds
        self._last_detection_time = 0.0
        self._threshold = config.detection.confidence_threshold

    def start(self) -> None:
        """Start the detection loop in a background thread."""
        self._running = True
        self._thread = threading.Thread(target=self._run, name="detector", daemon=True)
        self._thread.start()
        log.info("Detector started")

    def stop(self) -> None:
        """Signal the detection loop to stop."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)
            log.info("Detector stopped")

    def _run(self) -> None:
        camera = None
        model = None

        try:
            camera = self._init_camera()
            model = self._load_model()
            log.info(
                "Camera and model ready. Capturing at %d FPS, %s resolution",
                self._config.camera.fps,
                self._config.camera.resolution,
            )

            while self._running:
                jpeg_data = self._capture_frame(camera)
                if jpeg_data is None:
                    continue

                frame = self._buffer.add(jpeg_data)

                detections = self._detect_birds(model, jpeg_data)
                if detections and self._cooldown_elapsed():
                    best = max(detections, key=lambda d: d["confidence"])
                    burst = self._buffer.snapshot()
                    self._storage.save_detection(
                        frame=frame,
                        confidence=best["confidence"],
                        bbox=best["bbox"],
                        burst_frames=burst,
                    )
                    self._last_detection_time = time.time()

        except Exception:
            log.exception("Detector crashed")
        finally:
            if camera is not None:
                self._stop_camera(camera)

    def _init_camera(self):
        """Initialize picamera2. Returns the camera object."""
        from picamera2 import Picamera2

        cam = Picamera2()
        w, h = self._config.camera.resolution
        cam_config = cam.create_still_configuration(
            main={"size": (w, h), "format": "RGB888"},
        )
        cam.configure(cam_config)
        cam.start()
        # Let auto-exposure settle
        time.sleep(2)
        return cam

    def _stop_camera(self, camera) -> None:
        try:
            camera.stop()
            camera.close()
        except Exception:
            log.exception("Error closing camera")

    def _capture_frame(self, camera) -> bytes | None:
        """Capture a single JPEG frame. Returns JPEG bytes or None on error."""
        try:
            array = camera.capture_array("main")
            from PIL import Image

            img = Image.fromarray(array)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            return buf.getvalue()
        except Exception:
            log.exception("Frame capture error")
            return None

    def _load_model(self):
        """Load the YOLO model."""
        from ultralytics import YOLO

        model_path = self._config.detection.model
        log.info("Loading YOLO model: %s", model_path)
        model = YOLO(model_path)
        # Warm up with a dummy inference
        import numpy as np

        dummy = np.zeros((480, 640, 3), dtype=np.uint8)
        model(dummy, verbose=False)
        log.info("Model loaded and warmed up")
        return model

    def _detect_birds(self, model, jpeg_data: bytes) -> list[dict]:
        """Run YOLO on a JPEG frame. Returns list of bird detections."""
        from PIL import Image

        img = Image.open(io.BytesIO(jpeg_data))
        results = model(img, verbose=False, conf=self._threshold)

        birds = []
        for result in results:
            for box in result.boxes:
                cls_id = int(box.cls[0])
                if cls_id == BIRD_CLASS_ID:
                    conf = float(box.conf[0])
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    birds.append({
                        "confidence": conf,
                        "bbox": (x1, y1, x2, y2),
                    })
        return birds

    def _cooldown_elapsed(self) -> bool:
        return (time.time() - self._last_detection_time) >= self._cooldown
