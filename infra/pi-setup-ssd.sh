#!/usr/bin/env bash
# One-shot SSD setup for the Raspberry Pi.
#
# What it does:
#   - Partitions and formats the SSD as a single ext4 volume (label: badi-data)
#   - Mounts it at /mnt/data and adds a persistent fstab entry (by UUID)
#   - Creates application directories: postgres, parquet, docker, backups
#   - Moves Docker's data-root to /mnt/data/docker (keeps SD card writes minimal)
#
# Usage (as root):
#   bash infra/pi-setup-ssd.sh [DEVICE]
#   bash infra/pi-setup-ssd.sh /dev/sda    # default if no arg
#
# Run `lsblk` first to confirm the SSD device name.

set -euo pipefail

DEVICE=${1:-/dev/sda}
MOUNT=/mnt/data

# ── Sanity checks ───────────────────────────────────────────────────────────

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: run as root (sudo bash $0)" >&2
  exit 1
fi

if [[ ! -b "$DEVICE" ]]; then
  echo "ERROR: $DEVICE not found. Pass the SSD device as first argument." >&2
  echo "  lsblk   # to list block devices" >&2
  exit 1
fi

echo "=== SSD setup: $DEVICE → $MOUNT ==="
lsblk "$DEVICE"
echo ""
read -rp "WARNING: this will WIPE $DEVICE completely. Continue? [y/N] " confirm
[[ "${confirm,,}" == "y" ]] || { echo "Aborted."; exit 0; }

# ── Partition & format ───────────────────────────────────────────────────────

parted -s "$DEVICE" mklabel gpt mkpart primary ext4 0% 100%
sleep 2  # let udev register the new partition node

PARTITION="${DEVICE}1"
[[ -b "$PARTITION" ]] || PARTITION="${DEVICE}p1"

if [[ ! -b "$PARTITION" ]]; then
  echo "ERROR: could not find partition ($DEVICE)1 or (${DEVICE})p1" >&2
  exit 1
fi

mkfs.ext4 -F -L badi-data "$PARTITION"
echo "Formatted $PARTITION as ext4 (label: badi-data)"

# ── Mount & fstab ────────────────────────────────────────────────────────────

mkdir -p "$MOUNT"
mount "$PARTITION" "$MOUNT"

UUID=$(blkid -s UUID -o value "$PARTITION")

if grep -q "$UUID" /etc/fstab; then
  echo "fstab entry for UUID=$UUID already present — skipping"
else
  echo "UUID=$UUID  $MOUNT  ext4  defaults,noatime  0  2" >> /etc/fstab
  echo "Added $MOUNT to /etc/fstab (UUID=$UUID)"
fi

# ── Application directories ──────────────────────────────────────────────────

mkdir -p \
  "$MOUNT/postgres" \
  "$MOUNT/parquet" \
  "$MOUNT/docker" \
  "$MOUNT/backups"

# TimescaleDB container runs as UID 999 (postgres user inside the image)
chown 999:999 "$MOUNT/postgres"

# ── Move Docker data-root to SSD ─────────────────────────────────────────────
# SD card writes are the #1 Pi failure mode. Keeping images + layers on SSD
# dramatically extends SD card life.

if systemctl is-active --quiet docker 2>/dev/null; then
  echo "Stopping Docker to relocate data-root …"
  systemctl stop docker
fi

if [[ -d /var/lib/docker && ! -L /var/lib/docker ]]; then
  echo "Copying /var/lib/docker → $MOUNT/docker (this may take a minute) …"
  rsync -a --ignore-errors /var/lib/docker/ "$MOUNT/docker/" || true
fi

mkdir -p /etc/docker
python3 - <<EOF
import json, pathlib
cfg_path = pathlib.Path('/etc/docker/daemon.json')
cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
cfg['data-root'] = '$MOUNT/docker'
cfg_path.write_text(json.dumps(cfg, indent=2) + '\n')
print(f"Set Docker data-root = $MOUNT/docker in /etc/docker/daemon.json")
EOF

systemctl start docker
sleep 3
docker info | grep "Docker Root Dir"

# ── Summary ───────────────────────────────────────────────────────────────────

echo ""
echo "=== SSD setup complete ==="
echo "  Mount point : $MOUNT  (UUID=$UUID)"
echo "  postgres    : $MOUNT/postgres   (PostgreSQL / TimescaleDB data)"
echo "  parquet     : $MOUNT/parquet    (nightly Parquet exports)"
echo "  docker      : $MOUNT/docker     (Docker images and containers)"
echo "  backups     : $MOUNT/backups    (restic snapshots)"
echo ""
echo "Next step: run  sudo bash infra/pi-bootstrap.sh"
