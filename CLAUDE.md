# Bird Camera

Bird detection camera system for Raspberry Pi 5 + Pi Camera Module 3.

## Status

**Phase 1 (MVP) — running on Pi, pending 24-hour validation.**

Pi 5 is set up (hostname: `bird`, user: `peter`), camera connected, BirdCam running as a systemd service. SSD not yet installed (using microSD for now). Weatherproof enclosure not yet assembled.

### Phase 1 done-criteria

Runs 24 hours unattended. Browsable web UI with timestamped detections, thumbnails, confidence scores, and bounding boxes. FP rate <10% on obvious non-birds. Survives reboots via systemd.

## Phases

1. **Phase 1 — MVP, Pi Camera only** (current)
2. **Phase 2 — Sony a6100 integration** — gphoto2, USB, no soldering
3. **Phase 3 — Species ID** — species classifier, visit grouping with cooldown
4. **Phase 4 — Polish** — squirrel filtering, day/night, storage management, cloud backup

## Development

```bash
# macOS (no picamera2)
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest tests/ -v

# After editing files, re-run `pip install -e ".[dev]"` — Python 3.14
# editable installs go stale on file changes.

# On the Pi
cd ~/birdcam && git pull && sudo systemctl restart birdcam
journalctl -u birdcam -f
```

## Key decisions

- SQLite for metadata, images as files on disk (`/mnt/birdcam`)
- Single process: detector thread + FastAPI in main thread
- JPEG circular buffer (~3 seconds), not video
- YOLOv8n (nano) — COCO "bird" class (index 14)
- `create_video_configuration` without FrameRate control (IMX708 rejects it); FPS throttled in the capture loop
- systemd: `PrivateTmp=true` (needed for ultralytics), `YOLO_CONFIG_DIR=/mnt/birdcam/.ultralytics`, `ProtectHome=read-only`
- Service file uses placeholders (`BIRDCAM_USER`, `BIRDCAM_DIR`) templated by `setup.sh`
- Jinja2 TemplateResponse must use keyword args (`request=`, `name=`, `context=`) for Bookworm compatibility
- Web UI: no filtering/favorites (removed for simplicity), has delete, live MJPEG stream, 30s auto-refresh

## Gotchas found during Pi setup

- `libatlas-base-dev` renamed to `libatlas3-base` in Bookworm
- Pi 5 CSI cable is different from the one shipped with Camera Module 3
- Can't use `rpicam-still` while BirdCam has the camera open — stop the service first
