#!/usr/bin/env bash
# Pi base setup: Docker Compose plugin, firewall, timezone, unattended upgrades.
# Run once as root on Pi OS Lite 64-bit (after pi-setup-ssd.sh).
#
# Usage:
#   sudo bash infra/pi-bootstrap.sh

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: run as root (sudo bash $0)" >&2
  exit 1
fi

CALLING_USER=${SUDO_USER:-pi}

# ── Timezone ─────────────────────────────────────────────────────────────────

echo "=== Setting timezone to Europe/Zurich ==="
timedatectl set-timezone Europe/Zurich
timedatectl show --no-pager | grep -E "Timezone|NTP"

# ── Packages ─────────────────────────────────────────────────────────────────

echo "=== Updating package lists ==="
apt-get update -qq

echo "=== Installing Docker, ufw, unattended-upgrades ==="
apt-get install -y --no-install-recommends \
  docker.io \
  docker-compose-v2 \
  ufw \
  unattended-upgrades \
  apt-listchanges \
  curl \
  wget \
  git \
  python3-pip

# ── Docker ───────────────────────────────────────────────────────────────────

echo "=== Configuring Docker ==="
systemctl enable --now docker
usermod -aG docker "$CALLING_USER"
echo "Added $CALLING_USER to docker group (re-login required)"

# ── Firewall ─────────────────────────────────────────────────────────────────
# Cloudflare Tunnel handles all inbound HTTP/HTTPS — no ports needed.
# SSH only (via Tailscale in practice, but keep 22 for emergency LAN access).

echo "=== Configuring ufw ==="
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw --force enable
ufw status verbose

# ── Unattended upgrades ───────────────────────────────────────────────────────

echo "=== Enabling unattended-upgrades ==="
dpkg-reconfigure -plow unattended-upgrades

# ── NTP ───────────────────────────────────────────────────────────────────────

echo "=== NTP status ==="
timedatectl timesync-status 2>/dev/null || echo "(timedatectl timesync-status not available — check systemd-timesyncd)"

# ── Summary ───────────────────────────────────────────────────────────────────

echo ""
echo "=== Pi bootstrap complete ==="
echo ""
echo "  Docker      : $(docker --version)"
echo "  Compose     : $(docker compose version 2>/dev/null || echo 'not found')"
echo "  Timezone    : $(timedatectl show -p Timezone --value)"
echo "  User        : $CALLING_USER (added to docker group)"
echo ""
echo "Next steps:"
echo "  1. Log out and back in (docker group takes effect)"
echo "  2. cd deploy/"
echo "  3. mkdir -p secrets && echo '<pg_password>' > secrets/pg_password"
echo "  4. echo '<cloudflare_tunnel_token>' > secrets/cf_tunnel_token"
echo "  5. docker compose up -d"
