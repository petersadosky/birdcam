# BirdCam

A bird detection camera system built on a Raspberry Pi 5. It watches a bird feeder with a Pi Camera Module 3, runs YOLOv8 to detect birds in real time, and saves timestamped photos with bounding boxes and confidence scores. A local web UI lets you browse and delete detections, and stream a live camera feed.

## How it works

1. The Pi Camera captures JPEG frames at ~5 FPS
2. Frames feed into a circular buffer (~3 seconds) so the moment of arrival is never missed
3. Each frame runs through YOLOv8n (nano) for bird detection
4. When a bird is detected above the confidence threshold, the best frame and burst buffer are saved to disk
5. A cooldown timer prevents duplicate captures of the same bird sitting still
6. SQLite stores all metadata; a FastAPI web UI serves the gallery

```
Pi Camera → Frame Buffer → YOLOv8n → Storage (SSD + SQLite)
                                          ↓
                                     FastAPI Web UI
```

## Hardware

| Item | Notes |
|------|-------|
| Raspberry Pi 5 (8GB) | Active cooler required — throttles without one |
| Pi Camera Module 3 | Wide version recommended at close range (~10 ft) |
| CSI ribbon cable for Pi 5 | Pi 5 uses a smaller FPC connector — the cable in the Camera Module 3 box won't fit |
| MicroSD, 64GB+, A2-rated | Samsung Pro Endurance or SanDisk High Endurance |
| External SSD, 500GB+, USB 3.0 | SD cards die under continuous writes — images go on the SSD |
| 27W USB-C power supply | Official Pi 5 PSU — don't use a phone charger |
| Weatherproof enclosure | ABS IP65 junction box, ~220x170x110mm |

## Setup

### 1. Prepare the SSD (optional — works without one)

```bash
# Find your SSD
lsblk

# Format if new
sudo mkfs.ext4 /dev/sda1

# Create mount point and add to fstab
sudo mkdir -p /mnt/birdcam
sudo blkid /dev/sda1  # note the UUID
# Add to /etc/fstab:
# UUID=<your-uuid> /mnt/birdcam ext4 defaults,noatime 0 2
sudo mount -a
```

If no SSD is mounted, setup.sh creates `/mnt/birdcam` as a regular directory on the microSD card.

### 2. Clone and install

```bash
cd ~
git clone https://github.com/petersadosky/birdcam.git
cd birdcam
./scripts/setup.sh
```

The setup script installs system dependencies, creates a Python venv, downloads the YOLOv8n model (~6MB), and installs a systemd service.

### 3. Start it

```bash
sudo systemctl start birdcam
```

The web UI will be at `http://<pi-ip>:8080`.

### Useful commands

```bash
journalctl -u birdcam -f            # view logs
sudo systemctl stop birdcam         # stop
sudo systemctl restart birdcam      # restart
vcgencmd measure_temp               # check Pi temperature
```

## Configuration

All settings live in `config.yaml`:

```yaml
camera:
  resolution: [640, 480]
  fps: 5

detection:
  model: yolov8n.pt
  confidence_threshold: 0.5   # raise to reduce false positives
  cooldown_seconds: 5          # min seconds between captures
  buffer_seconds: 3            # how many seconds of pre-detection frames to keep

storage:
  base_path: /mnt/birdcam
  thumbnail_width: 320
  prune_burst_after_days: 90   # burst frames auto-deleted after this

web:
  host: 0.0.0.0
  port: 8080
```

## Web UI

- **Gallery** — grid of detection thumbnails, newest first, auto-refreshes every 30 seconds
- **Detail view** — full-resolution image, bounding box coordinates, burst frames, delete button
- **Live view** — real-time MJPEG stream from the camera

## Development

```bash
# On macOS (no Pi camera needed for tests)
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest tests/ -v
```

## Roadmap

- [x] **Phase 1** — Pi Camera detection + web UI
- [ ] **Phase 2** — Sony a6100 integration for high-res captures via gphoto2
- [ ] **Phase 3** — Species identification + visit grouping
- [ ] **Phase 4** — Squirrel filtering, day/night handling, cloud backup
