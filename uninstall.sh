#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# GalactiLog — Uninstall Script
#
# Stops and removes all containers, networks, images, database, and thumbnails.
# Does NOT delete FITS source files or this repository.
#
# Run:  bash uninstall.sh
# ──────────────────────────────────────────────────────────────────────────────
set -uo pipefail

# ── Colors & helpers ─────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${CYAN}ℹ${NC}  $*"; }
success() { echo -e "${GREEN}✔${NC}  $*"; }
warn()    { echo -e "${YELLOW}⚠${NC}  $*"; }
error()   { echo -e "${RED}✖${NC}  $*"; }
header()  { echo -e "\n${BOLD}━━━ $* ━━━${NC}\n"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Confirmation ─────────────────────────────────────────────────────────────
header "GalactiLog — Uninstall"

echo -e "  This will ${RED}permanently delete${NC}:"
echo ""
echo "    • All Docker containers, networks, and volumes"
echo "    • Docker image (chvvkumar/galactilog)"
echo "    • Database files (/docker/astro_cataloger/postgres)"
echo "    • Thumbnail files (/docker/astro_cataloger/thumbnails)"
echo "    • .env configuration file"
echo ""
echo -e "  This will ${GREEN}NOT${NC} delete:"
echo ""
echo "    • Your FITS source files (/astro_incoming)"
echo "    • This git repository"
echo ""

read -rp "$(echo -e "${RED}?${NC}  Are you sure you want to uninstall? Type 'yes' to confirm: ")" CONFIRM
if [ "$CONFIRM" != "yes" ]; then
    info "Uninstall cancelled."
    exit 0
fi

# ── Stop and remove containers ───────────────────────────────────────────────
header "Stopping Containers"

if docker compose ps -q 2>/dev/null | grep -q .; then
    docker compose down -v --remove-orphans
    success "Containers stopped and removed"
else
    info "No running containers found"
fi

# ── Remove Docker image ─────────────────────────────────────────────────────
header "Removing Docker Image"

if docker image inspect chvvkumar/galactilog &>/dev/null; then
    docker image rm chvvkumar/galactilog
    success "Removed chvvkumar/galactilog image"
else
    info "Image not found, skipping"
fi

# ── Remove data directories ─────────────────────────────────────────────────
header "Removing Data"

if [ -d "/docker/astro_cataloger/postgres" ]; then
    sudo rm -rf /docker/astro_cataloger/postgres
    success "Removed database files"
else
    info "Database directory not found, skipping"
fi

if [ -d "/docker/astro_cataloger/thumbnails" ]; then
    sudo rm -rf /docker/astro_cataloger/thumbnails
    success "Removed thumbnail files"
else
    info "Thumbnails directory not found, skipping"
fi

# Remove parent if empty
if [ -d "/docker/astro_cataloger" ]; then
    rmdir /docker/astro_cataloger 2>/dev/null && success "Removed /docker/astro_cataloger" || true
fi

# ── Remove .env ──────────────────────────────────────────────────────────────
header "Removing Configuration"

if [ -f "$SCRIPT_DIR/.env" ]; then
    rm "$SCRIPT_DIR/.env"
    success "Removed .env"
else
    info ".env not found, skipping"
fi

# ── Done ─────────────────────────────────────────────────────────────────────
header "Uninstall Complete"

echo "  Everything has been cleaned up."
echo ""
echo "  To reinstall, run:"
echo "    bash setup.sh"
echo ""
