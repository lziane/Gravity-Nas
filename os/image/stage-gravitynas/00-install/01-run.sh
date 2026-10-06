#!/usr/bin/env bash
set -euo pipefail

STAGE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_SOURCE="${STAGE_DIR}/files/gravitynas"
VERSION="$(<"${STAGE_DIR}/files/version")"
ROOTFS_RELEASE="${ROOTFS_DIR}/opt/gravitynas/releases/${VERSION}"

install -d "${ROOTFS_RELEASE}"
rsync -a --delete "${APP_SOURCE}/" "${ROOTFS_RELEASE}/"
printf '%s\n' "${VERSION}" > "${ROOTFS_RELEASE}/.gravitynas-release"
install -D -m 0644 "${STAGE_DIR}/files/update.pub" \
    "${ROOTFS_DIR}/etc/gravitynas/update.pub"
install -D -m 0644 "${ROOTFS_RELEASE}/os/etc/gravitynas.env.example" \
    "${ROOTFS_DIR}/etc/gravitynas/gravitynas.env"
install -D -m 0644 "${ROOTFS_RELEASE}/os/systemd/gravitynas.service" \
    "${ROOTFS_DIR}/etc/systemd/system/gravitynas.service"
install -D -m 0644 "${ROOTFS_RELEASE}/config/nginx.conf" \
    "${ROOTFS_DIR}/etc/nginx/sites-available/gravitynas"
install -D -m 0644 "${ROOTFS_RELEASE}/os/etc/samba/gravitynas.conf" \
    "${ROOTFS_DIR}/etc/samba/smb.conf"
install -D -m 0755 "${ROOTFS_RELEASE}/os/scripts/update.sh" \
    "${ROOTFS_DIR}/usr/local/sbin/gravitynas-update"
install -D -m 0755 "${ROOTFS_RELEASE}/os/scripts/configure-usb-storage.sh" \
    "${ROOTFS_DIR}/usr/local/sbin/gravitynas-storage"
sed -i 's|server_name  nas.local  _;|server_name  gravitynas.local  _;|' \
    "${ROOTFS_DIR}/etc/nginx/sites-available/gravitynas"
ln -sfn /etc/nginx/sites-available/gravitynas \
    "${ROOTFS_DIR}/etc/nginx/sites-enabled/gravitynas"
rm -f "${ROOTFS_DIR}/etc/nginx/sites-enabled/default"
printf '%s\n' 'gravitynas' > "${ROOTFS_DIR}/etc/hostname"

on_chroot << EOF
set -e
if ! id -u gravitynas >/dev/null 2>&1; then
    useradd --system --home-dir /var/lib/gravitynas --create-home --shell /usr/sbin/nologin gravitynas
fi
groupadd -f gravitynas_users
usermod -aG gravitynas_users gravitynas
install -d -o gravitynas -g gravitynas -m 0700 \
    /var/lib/gravitynas /var/lib/gravitynas/data \
    /var/lib/gravitynas/storage /var/lib/gravitynas/backups
install -d -o root -g gravitynas -m 0750 /etc/gravitynas
chown root:gravitynas /etc/gravitynas/gravitynas.env
chmod 0640 /etc/gravitynas/gravitynas.env
chown -R root:root /opt/gravitynas/releases/${VERSION}
chmod -R u=rwX,go=rX /opt/gravitynas/releases/${VERSION}
ln -s releases/${VERSION} /opt/gravitynas/current
python3 -m venv /opt/gravitynas/releases/${VERSION}/venv
/opt/gravitynas/releases/${VERSION}/venv/bin/pip install --disable-pip-version-check \
    -r /opt/gravitynas/releases/${VERSION}/requirements.txt
/opt/gravitynas/releases/${VERSION}/venv/bin/python -m compileall -q \
    /opt/gravitynas/releases/${VERSION}/main.py \
    /opt/gravitynas/releases/${VERSION}/app \
    /opt/gravitynas/releases/${VERSION}/routes
systemctl enable gravitynas nginx smbd avahi-daemon
EOF