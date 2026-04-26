#!/usr/bin/env bash
#
# BirdCam setup script for Raspberry Pi 5 running Pi OS (Bookworm).
# Run as your normal user (pi), not root. Uses sudo where needed.
#
set -euo pipefail

BIRDCAM_DIR="$HOME/birdcam"
VENV_DIR="$BIRDCAM_DIR/venv"
STORAGE_DIR="/mnt/birdcam"

echo "=== BirdCam Setup ==="
echo ""

# --- System dependencies ---
echo "[1/6] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3-venv \
    python3-dev \
    python3-picamera2 \
    libatlas3-base \
    libjpeg-dev \
    libopenblas-dev \
    > /dev/null

# --- Storage setup ---
echo "[2/6] Setting up storage directory..."
# If the SSD isn't mounted yet, create a local fallback
if mountpoint -q "$STORAGE_DIR" 2>/dev/null; then
    echo "  SSD is mounted at $STORAGE_DIR"
else
    echo "  WARNING: $STORAGE_DIR is not a mount point."
    echo "  Creating it as a regular directory. For production use,"
    echo "  mount your SSD there first. See README.md for instructions."
    sudo mkdir -p "$STORAGE_DIR"
fi
sudo chown "$(whoami):$(whoami)" "$STORAGE_DIR"

# --- Project setup ---
echo "[3/6] Setting up Python environment..."
cd "$BIRDCAM_DIR"
python3 -m venv --system-site-packages "$VENV_DIR"
# --system-site-packages lets us use the apt-installed picamera2
source "$VENV_DIR/bin/activate"
pip install --upgrade pip -q
pip install -e ".[pi]" -q

# --- Download YOLO model ---
echo "[4/6] Downloading YOLOv8n model..."
python3 -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"

# --- Copy config ---
echo "[5/6] Setting up config..."
if [ ! -f "$BIRDCAM_DIR/config.yaml" ]; then
    echo "  No config.yaml found — this shouldn't happen if you cloned the repo."
    echo "  Using defaults."
fi

# --- Install systemd service ---
echo "[6/6] Installing systemd service..."
sed -e "s|BIRDCAM_USER|$(whoami)|g" \
    -e "s|BIRDCAM_DIR|$BIRDCAM_DIR|g" \
    "$BIRDCAM_DIR/systemd/birdcam.service" \
    | sudo tee /etc/systemd/system/birdcam.service > /dev/null
sudo systemctl daemon-reload
sudo systemctl enable birdcam.service
echo "  Service installed and enabled."

echo ""
echo "=== Setup complete ==="
echo ""
echo "To start BirdCam now:"
echo "  sudo systemctl start birdcam"
echo ""
echo "To view logs:"
echo "  journalctl -u birdcam -f"
echo ""
echo "Web UI will be at:"
echo "  http://$(hostname -I | awk '{print $1}'):8080"
echo ""

# --- SSD mount instructions ---
if ! mountpoint -q "$STORAGE_DIR" 2>/dev/null; then
    echo "IMPORTANT: Mount your SSD before running in production."
    echo ""
    echo "1. Find your SSD:  lsblk"
    echo "2. Format if new:  sudo mkfs.ext4 /dev/sda1"
    echo "3. Get UUID:       sudo blkid /dev/sda1"
    echo "4. Add to fstab:   UUID=<your-uuid> /mnt/birdcam ext4 defaults,noatime 0 2"
    echo "5. Mount:          sudo mount -a"
    echo ""
fi
