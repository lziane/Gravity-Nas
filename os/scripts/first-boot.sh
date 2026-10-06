#!/usr/bin/env bash
set -euo pipefail

SERVICE_USER="${GRAVITYNAS_USER:-gravitynas}"
STATE_DIR="${GRAVITYNAS_STATE_DIR:-/var/lib/gravitynas}"

if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
    useradd --system --home-dir "${STATE_DIR}" --create-home --shell /usr/sbin/nologin "${SERVICE_USER}"
fi

install -d -o "${SERVICE_USER}" -g "${SERVICE_USER}" -m 0700 "${STATE_DIR}"
install -d -o "${SERVICE_USER}" -g "${SERVICE_USER}" -m 0700 "${STATE_DIR}/data" "${STATE_DIR}/storage" "${STATE_DIR}/backups"
install -d -o root -g "${SERVICE_USER}" -m 0750 /etc/gravitynas

if [[ ! -f /etc/gravitynas/gravitynas.env ]]; then
    install -o root -g "${SERVICE_USER}" -m 0640 \
        "$(dirname "$0")/../etc/gravitynas.env.example" \
        /etc/gravitynas/gravitynas.env
fi

echo "GravityNAS first-boot layout prepared for ${SERVICE_USER}."
