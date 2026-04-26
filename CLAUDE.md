# Bird Camera

Bird detection camera system for Raspberry Pi 5 + Pi Camera Module 3.

## Status

**Phase 1 (MVP) — code complete, awaiting hardware for testing.**

Hardware on order (Pi 5 8GB, Camera Module 3, SSD, cooler, etc.). Once it arrives:
1. Clone to Pi, mount SSD, run `./scripts/setup.sh`
2. Run 24-hour validation against done-criteria (see below)

### Phase 1 done-criteria

Runs 24 hours unattended. Browsable web UI with timestamped detections, thumbnails,
confidence scores, bounding boxes, and filtering by date/confidence. False positive
rate <10% on obvious non-birds. Survives reboots via systemd.

## Phases

1. **Phase 1 — MVP, Pi Camera only** (current) — motion detection + bird classification, local web UI
2. **Phase 2 — Sony a6100 integration** — trigger high-res capture via gphoto2 (USB, no soldering)
3. **Phase 3 — Species ID** — species classifier, visit grouping with cooldown
4. **Phase 4 — Polish** — squirrel/false-positive filtering, day/night handling, storage management, cloud backup

## Project structure

- `src/birdcam/` — main package
- `src/birdcam/web/` — FastAPI app + Jinja2 templates
- `tests/` — pytest tests (run without Pi hardware, 19 tests, all passing)
- `systemd/` — systemd service file
- `scripts/` — setup and utility scripts
- `config.yaml` — single config file for all tunables

## Development

```bash
# Install in dev mode (on macOS, without picamera2)
# Uses a venv — the system Python is 3.14 and needs --break-system-packages otherwise
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# Run tests (use venv python directly — shell aliases can override `python`)
.venv/bin/python -m pytest tests/ -v

# On the Pi (with picamera2)
python3 -m venv --system-site-packages venv
venv/bin/pip install -e ".[dev,pi]"
birdcam                          # runs with default config.yaml
birdcam --config /path/to/config.yaml
```

## Key decisions

- SQLite for metadata, images as files on disk (external SSD at `/mnt/birdcam`)
- Single process: detector thread + FastAPI in main thread
- JPEG circular buffer (~3 seconds), not video
- YOLOv8n (nano) for bird detection — COCO "bird" class (index 14)
- picamera2 for camera capture (Pi only)
- FastAPI + Jinja2 for web UI, localhost only (Tailscale-ready for remote access later)
- Retention: all metadata + thumbnails forever, 1-2 best frames per visit forever, burst frames pruned after 90 days, "favorite" flag exempts from pruning

## Things to validate on real hardware

- YOLOv8n inference speed on Pi 5 CPU (target: <200ms/frame at 640x480)
- False positive rate with COCO "bird" class
- Thermal behavior in weatherproof enclosure with active cooler
- picamera2 sustained capture at 5 FPS under load
