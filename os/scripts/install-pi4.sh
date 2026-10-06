#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INSTALL_DIR="${GRAVITYNAS_INSTALL_DIR:-/opt/gravitynas}"
STATE_DIR="${GRAVITYNAS_STATE_DIR:-/var/lib/gravitynas}"
STORAGE_DIR="${GRAVITYNAS_STORAGE_PATH:-${STATE_DIR}/storage}"
SERVICE_USER="${GRAVITYNAS_USER:-gravitynas}"
HOSTNAME_NAME="${GRAVITYNAS_HOSTNAME:-gravitynas}"
RELEASE_VERSION="${GRAVITYNAS_VERSION:-local-$(date +%Y%m%d%H%M%S)}"
RELEASE_DIR="${INSTALL_DIR}/releases/${RELEASE_VERSION}"

if [[ "${EUID}" -ne 0 ]]; then
    echo "Lancez cet installateur avec sudo." >&2
    exit 1
fi
if [[ -e "${INSTALL_DIR}/current" || -L "${INSTALL_DIR}/current" ]]; then
    echo "GravityNAS semble déjà installé dans ${INSTALL_DIR}. Utilisez gravitynas-update pour le mettre à jour." >&2
    exit 1
fi
if [[ ! "${RELEASE_VERSION}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]]; then
    echo "Identifiant de release invalide: ${RELEASE_VERSION}" >&2
    exit 1
fi
if [[ -z "${GRAVITYNAS_UPDATE_PUBLIC_KEY:-}" || ! -r "${GRAVITYNAS_UPDATE_PUBLIC_KEY}" ]]; then
    echo "Définissez GRAVITYNAS_UPDATE_PUBLIC_KEY vers la clé publique des releases signées." >&2
    exit 1
fi
if [[ ! "${STORAGE_DIR}" =~ ^/[A-Za-z0-9_./-]+$ ]]; then
    echo "Chemin de stockage invalide: ${STORAGE_DIR}" >&2
    exit 1
fi
if [[ "${STORAGE_DIR}" != "${STATE_DIR}/storage" ]] && \
    { [[ ! -d "${STORAGE_DIR}" ]] || ! mountpoint -q "${STORAGE_DIR}"; }; then
    echo "Le stockage externe doit être monté avant l'installation: ${STORAGE_DIR}" >&2
    exit 1
fi

ARCH="$(dpkg --print-architecture 2>/dev/null || true)"
if [[ "${ARCH}" != "arm64" ]]; then
    echo "Cet installateur cible Raspberry Pi 4 en 64-bit ARM (arm64), architecture détectée: ${ARCH:-inconnue}." >&2
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-venv python3-pip python3-psutil \
    nginx samba samba-common-bin avahi-daemon rsync sqlite3 \
    curl openssl ca-certificates
openssl pkey -pubin -in "${GRAVITYNAS_UPDATE_PUBLIC_KEY}" -noout
if [[ "${GRAVITYNAS_INSTALL_OCR:-0}" == "1" ]]; then
    apt-get install -y tesseract-ocr tesseract-ocr-fra
else
    echo "OCR non installé (activer avec GRAVITYNAS_INSTALL_OCR=1 pour économiser l'espace)."
fi

if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
    useradd --system --home-dir "${STATE_DIR}" --create-home --shell /usr/sbin/nologin "${SERVICE_USER}"
fi
groupadd -f gravitynas_users
usermod -aG gravitynas_users "${SERVICE_USER}"

install -d -o root -g root -m 0755 "${INSTALL_DIR}/releases"
if [[ -e "${RELEASE_DIR}" ]]; then
    echo "La release ${RELEASE_VERSION} existe déjà: ${RELEASE_DIR}" >&2
    exit 1
fi
install -d -o root -g root -m 0755 "${RELEASE_DIR}"
rsync -a --delete \
    --exclude='.venv/' --exclude='__pycache__/' --exclude='.pytest_cache/' \
    --exclude='data/*.db*' --exclude='data/.nas_encryption.key' \
    --exclude='nas_storage/' --exclude='backups/' --exclude='build/' \
    "${ROOT_DIR}/" "${RELEASE_DIR}/"
printf '%s\n' "${RELEASE_VERSION}" > "${RELEASE_DIR}/.gravitynas-release"

install -d -o "${SERVICE_USER}" -g "${SERVICE_USER}" -m 0700 \
    "${STATE_DIR}" "${STATE_DIR}/data" "${STATE_DIR}/backups"
install -d -o "${SERVICE_USER}" -g gravitynas_users -m 2770 "${STORAGE_DIR}"
chown -R root:root "${RELEASE_DIR}"
chmod -R u=rwX,go=rX "${RELEASE_DIR}"
ln -s "releases/${RELEASE_VERSION}" "${INSTALL_DIR}/current"

python3 -m venv "${RELEASE_DIR}/venv"
"${RELEASE_DIR}/venv/bin/pip" install --disable-pip-version-check -r "${RELEASE_DIR}/requirements.txt"
"${RELEASE_DIR}/venv/bin/python" -m compileall -q \
    "${RELEASE_DIR}/main.py" "${RELEASE_DIR}/app" "${RELEASE_DIR}/routes"

install -d -o root -g "${SERVICE_USER}" -m 0750 /etc/gravitynas
if [[ ! -f /etc/gravitynas/gravitynas.env ]]; then
    install -o root -g "${SERVICE_USER}" -m 0640 \
    "${RELEASE_DIR}/os/etc/gravitynas.env.example" /etc/gravitynas/gravitynas.env
fi
sed -i "s|^GRAVITY_STORAGE_PATH=.*|GRAVITY_STORAGE_PATH=${STORAGE_DIR}|" /etc/gravitynas/gravitynas.env
sed -i "s|^GRAVITY_DATA_PATH=.*|GRAVITY_DATA_PATH=${STATE_DIR}/data|" /etc/gravitynas/gravitynas.env
grep -q '^GRAVITY_STORAGE_PATH=' /etc/gravitynas/gravitynas.env || echo "GRAVITY_STORAGE_PATH=${STORAGE_DIR}" >> /etc/gravitynas/gravitynas.env
grep -q '^GRAVITY_DATA_PATH=' /etc/gravitynas/gravitynas.env || echo "GRAVITY_DATA_PATH=${STATE_DIR}/data" >> /etc/gravitynas/gravitynas.env
install -o root -g root -m 0644 "${GRAVITYNAS_UPDATE_PUBLIC_KEY}" /etc/gravitynas/update.pub

install -D -m 0644 "${RELEASE_DIR}/os/systemd/gravitynas.service" \
    /etc/systemd/system/gravitynas.service
sed -i "s|/opt/gravitynas|${INSTALL_DIR}|g; s|User=gravitynas|User=${SERVICE_USER}|; s|Group=gravitynas|Group=${SERVICE_USER}|; s|/var/lib/gravitynas|${STATE_DIR}|g" \
    /etc/systemd/system/gravitynas.service
install -D -o root -g root -m 0755 "${RELEASE_DIR}/os/scripts/update.sh" \
    /usr/local/sbin/gravitynas-update
install -D -o root -g root -m 0755 "${RELEASE_DIR}/os/scripts/configure-usb-storage.sh" \
    /usr/local/sbin/gravitynas-storage
install -D -m 0644 "${RELEASE_DIR}/config/nginx.conf" \
    /etc/nginx/sites-available/gravitynas
sed -i "s|/opt/gravitynas|${INSTALL_DIR}|g" /etc/nginx/sites-available/gravitynas
sed -i -E "s|server_name[[:space:]]+nas\.local[[:space:]]+_;|server_name ${HOSTNAME_NAME}.local _;|" \
    /etc/nginx/sites-available/gravitynas
ln -sfn /etc/nginx/sites-available/gravitynas /etc/nginx/sites-enabled/gravitynas
rm -f /etc/nginx/sites-enabled/default

install -D -m 0644 "${RELEASE_DIR}/os/etc/samba/gravitynas.conf" /etc/samba/smb.conf
sed -i "s|^   path = .*|   path = ${STORAGE_DIR}/%S|" /etc/samba/smb.conf
if [[ "${STORAGE_DIR}" != "${STATE_DIR}/storage" ]]; then
    install -d -o root -g root -m 0755 /etc/systemd/system/gravitynas.service.d
    cat > /etc/systemd/system/gravitynas.service.d/storage.conf <<EOF
[Unit]
RequiresMountsFor=${STORAGE_DIR}

[Service]
ExecStartPre=/usr/bin/mountpoint -q ${STORAGE_DIR}
ReadWritePaths=${STORAGE_DIR}
EOF
fi

hostnamectl set-hostname "${HOSTNAME_NAME}"
nginx -t
systemctl daemon-reload
systemctl enable gravitynas nginx smbd avahi-daemon
systemctl restart gravitynas nginx smbd avahi-daemon

cat <<EOF
GravityNAS est installé sur ce Raspberry Pi 4.
Accès local : http://${HOSTNAME_NAME}.local
Release : ${RELEASE_VERSION}
État : systemctl status gravitynas
Logs : journalctl -u gravitynas -f
Données : ${STORAGE_DIR}
Mise à jour : sudo gravitynas-update /chemin/vers/gravitynas-VERSION.tar.gz
Stockage USB après installation : sudo gravitynas-storage /dev/sdX1
EOF
