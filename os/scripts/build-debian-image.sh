#!/usr/bin/env bash
set -euo pipefail

# Bootstrap only: image partitioning, bootloader, firmware and OTA are deliberately
# left to the hardware-specific image pipeline.
if [[ "${EUID}" -ne 0 ]]; then
    echo "Run this script as root." >&2
    exit 1
fi

if ! command -v debootstrap >/dev/null 2>&1 || ! command -v rsync >/dev/null 2>&1; then
    echo "Install debootstrap and rsync before building an image." >&2
    exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUTPUT="${1:-${ROOT_DIR}/build/gravitynas-rootfs}"
mkdir -p "${OUTPUT}"

debootstrap --variant=minbase \
    "${GRAVITYNAS_SUITE:-bookworm}" "${OUTPUT}" "${GRAVITYNAS_MIRROR:-http://deb.debian.org/debian}"

rsync -a --delete \
    --exclude='.venv/' --exclude='__pycache__/' --exclude='.pytest_cache/' \
    --exclude='data/*.db*' --exclude='nas_storage/' --exclude='backups/' \
    "${ROOT_DIR}/" "${OUTPUT}/opt/gravitynas/"

install -D -m 0644 "${ROOT_DIR}/os/systemd/gravitynas.service" \
    "${OUTPUT}/etc/systemd/system/gravitynas.service"
install -D -m 0755 "${ROOT_DIR}/os/scripts/first-boot.sh" \
    "${OUTPUT}/usr/local/libexec/gravitynas-first-boot"

cat <<'NOTICE'
Root filesystem bootstrap complete.
Next steps are hardware-specific: install Python dependencies in the rootfs,
create the service user, configure networking, choose a partition layout, and
add a signed update/recovery mechanism before producing a bootable image.
NOTICE
