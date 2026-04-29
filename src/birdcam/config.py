"""Load and validate config.yaml into typed dataclasses."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class CameraConfig:
    resolution: tuple[int, int] = (640, 480)
    fps: int = 5


@dataclass
class DetectionConfig:
    model: str = "yolov8n.pt"
    confidence_threshold: float = 0.5
    cooldown_seconds: float = 5.0
    buffer_seconds: float = 3.0


@dataclass
class StorageConfig:
    base_path: Path = field(default_factory=lambda: Path("/mnt/birdcam"))
    thumbnail_width: int = 320
    prune_burst_after_days: int = 90


@dataclass
class ClassifierConfig:
    enabled: bool = True
    max_requests_per_day: int = 200
    model: str = "claude-haiku-4-5-20251001"


@dataclass
class WebConfig:
    host: str = "0.0.0.0"
    port: int = 8080


@dataclass
class Config:
    camera: CameraConfig = field(default_factory=CameraConfig)
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    classifier: ClassifierConfig = field(default_factory=ClassifierConfig)
    web: WebConfig = field(default_factory=WebConfig)


def load_config(path: Path | None = None) -> Config:
    """Load config from YAML file. Falls back to defaults if no file given."""
    if path is None:
        path = Path("config.yaml")
    if not path.exists():
        return Config()

    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    cfg = Config()

    if "camera" in raw:
        c = raw["camera"]
        if "resolution" in c:
            cfg.camera.resolution = tuple(c["resolution"])
        if "fps" in c:
            cfg.camera.fps = c["fps"]

    if "detection" in raw:
        d = raw["detection"]
        if "model" in d:
            cfg.detection.model = d["model"]
        if "confidence_threshold" in d:
            cfg.detection.confidence_threshold = d["confidence_threshold"]
        if "cooldown_seconds" in d:
            cfg.detection.cooldown_seconds = d["cooldown_seconds"]
        if "buffer_seconds" in d:
            cfg.detection.buffer_seconds = d["buffer_seconds"]

    if "storage" in raw:
        s = raw["storage"]
        if "base_path" in s:
            cfg.storage.base_path = Path(s["base_path"])
        if "thumbnail_width" in s:
            cfg.storage.thumbnail_width = s["thumbnail_width"]
        if "prune_burst_after_days" in s:
            cfg.storage.prune_burst_after_days = s["prune_burst_after_days"]

    if "classifier" in raw:
        cl = raw["classifier"]
        if "enabled" in cl:
            cfg.classifier.enabled = cl["enabled"]
        if "max_requests_per_day" in cl:
            cfg.classifier.max_requests_per_day = cl["max_requests_per_day"]
        if "model" in cl:
            cfg.classifier.model = cl["model"]

    if "web" in raw:
        w = raw["web"]
        if "host" in w:
            cfg.web.host = w["host"]
        if "port" in w:
            cfg.web.port = w["port"]

    return cfg
