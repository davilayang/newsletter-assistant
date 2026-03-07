#!/usr/bin/env bash
# Deploy newsletter-assistant to Raspberry Pi.
#
# Usage:
#   Fresh deploy:   ./scripts/deploy-pi.sh
#   After changes:  ./scripts/deploy-pi.sh
#
# Assumes Docker Engine + Compose plugin are already installed on the Pi.
# Set PI env var or edit the default below.

set -euo pipefail

PI="${PI:-rpi-a}"
PI_DIR="~/newsletter-assistant"
SERVICES="frontend agent"

# --- Helpers ----------------------------------------------------------------

info()  { printf "\033[1;34m==> %s\033[0m\n" "$*"; }
error() { printf "\033[1;31mERROR: %s\033[0m\n" "$*" >&2; exit 1; }

# Transfer a docker image to the Pi with a progress bar.
# Uses pv if available, otherwise falls back to plain gzip.
transfer_image() {
    local image="$1"
    local size
    size=$(docker image inspect "$image" --format='{{.Size}}')
    # Compressed size is ~40% of uncompressed; estimate for pv
    local est_size=$(( size * 40 / 100 ))

    if command -v pv >/dev/null; then
        docker save "$image" | gzip | pv -s "$est_size" -N "$image" | ssh "$PI" "docker load -q"
    else
        docker save "$image" | gzip | ssh "$PI" "docker load -q"
    fi
}

# --- Pre-flight checks ------------------------------------------------------

command -v docker >/dev/null || error "docker not found"
ssh -q -o ConnectTimeout=5 "$PI" true 2>/dev/null || error "Cannot SSH to $PI"

for f in .env docker-compose.yml docker-compose.pi.yml; do
    [ -f "$f" ] || error "Missing $f — run from project root"
done
[ -d creds ] || error "Missing creds/ directory"
[ -d config ] || error "Missing config/ directory"

# --- 1. Build images --------------------------------------------------------

info "Building images locally..."
DOCKER_USER=local docker compose build $SERVICES

# --- 2. Transfer images to Pi -----------------------------------------------

info "Transferring images to Pi ($PI)..."
if ! command -v pv >/dev/null; then
    info "(install pv for progress bars: brew install pv)"
fi
for svc in $SERVICES; do
    image="local/newsletter-${svc}:latest"
    transfer_image "$image"
done

# --- 3. Sync config & credentials -------------------------------------------

info "Syncing files to Pi..."
ssh "$PI" "mkdir -p $PI_DIR"

rsync -avz -v \
    .env \
    docker-compose.yml \
    docker-compose.pi.yml \
    "$PI:$PI_DIR/"

rsync -avz -v creds/  "$PI:$PI_DIR/creds/"
rsync -avz -v config/ "$PI:$PI_DIR/config/"

# --- 4. Deploy on Pi --------------------------------------------------------

info "Starting containers on Pi..."
ssh "$PI" "cd $PI_DIR && \
    DOCKER_USER=local docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d --force-recreate"

# --- Done -------------------------------------------------------------------

PI_IP="${PI#*@}"
info "Deployed! Access at https://${PI_IP}:8080"
