"""Entry point: starts detector thread + web server."""

import argparse
import logging
import signal
import sys
import threading
from pathlib import Path

import uvicorn

from birdcam.backfill import Backfiller
from birdcam.classifier import Classifier
from birdcam.config import load_config
from birdcam.db import DetectionDB
from birdcam.detector import Detector
from birdcam.storage import Storage
from birdcam.web.app import create_app

log = logging.getLogger("birdcam")


def main():
    parser = argparse.ArgumentParser(description="BirdCam — bird detection system")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.yaml"),
        help="Path to config file (default: config.yaml)",
    )
    args = parser.parse_args()

    config = load_config(args.config)

    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    log.info("BirdCam starting up")
    log.info("Storage: %s", config.storage.base_path)
    log.info("Web UI: http://%s:%d", config.web.host, config.web.port)

    # Initialize components
    db = DetectionDB(config.storage.base_path / "birdcam.db")
    storage = Storage(config.storage, db)
    classifier = Classifier(config.classifier, db)
    detector = Detector(config, storage, classifier)
    backfiller = Backfiller(classifier, db, storage)
    app = create_app(db, storage, frame_buffer=detector.buffer, classifier=classifier)

    # Handle shutdown
    shutdown_event = threading.Event()

    def handle_signal(signum, frame):
        log.info("Received signal %d, shutting down...", signum)
        shutdown_event.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    # Start detector
    detector.start()
    backfiller.start()

    # Schedule daily burst pruning
    def prune_loop():
        while not shutdown_event.is_set():
            shutdown_event.wait(timeout=86400)  # once per day
            if not shutdown_event.is_set():
                try:
                    storage.prune_old_bursts()
                except Exception:
                    log.exception("Error during burst pruning")

    prune_thread = threading.Thread(target=prune_loop, name="pruner", daemon=True)
    prune_thread.start()

    # Run web server (blocks until shutdown)
    try:
        uvicorn.run(
            app,
            host=config.web.host,
            port=config.web.port,
            log_level="warning",
        )
    finally:
        log.info("Shutting down detector...")
        shutdown_event.set()
        backfiller.stop()
        detector.stop()
        db.close()
        log.info("BirdCam stopped")


if __name__ == "__main__":
    main()
