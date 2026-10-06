#!/usr/bin/env bash
set -euo pipefail

DEVICE="${1:-}"
MOUNT_POINT="${GRAVITYNAS_STORAGE_MOUNT:-/srv/gravitynas-storage}"
SERVICE_USER="${GRAVITYNAS_USER:-gravitynas}"

if [[ "${EUID}" -ne 0 ]]; then
    echo "Lancez cette commande avec sudo." >&2
    exit 1
fi
if [[ -z "${DEVICE}" || ! -b "${DEVICE}" ]]; then
    echo "Usage: sudo gravitynas-storage /dev/sdX1" >&2
    exit 2
fi
if [[ ! "${MOUNT_POINT}" =~ ^/[A-Za-z0-9_./-]+$ ]]; then
    echo "Point de montage invalide: ${MOUNT_POINT}" >&2
    exit 2
fi
FILESYSTEM="$(blkid -o value -s TYPE "${DEVICE}" 2>/dev/null || true)"
UUID="$(blkid -o value -s UUID "${DEVICE}" 2>/dev/null || true)"
if [[ "${FILESYSTEM}" != "ext4" || -z "${UUID}" ]]; then
    echo "Le volume doit déjà être formaté en ext4 et posséder un UUID. Aucun formatage n'est effectué." >&2
    exit 1
fi
ROOT_UUID="$(findmnt -n -o UUID --target /)"
if [[ -n "${ROOT_UUID}" && "${UUID}" == "${ROOT_UUID}" ]]; then
    echo "Le volume racine ne peut pas être configuré comme disque de données." >&2
    exit 1
fi
if [[ ! -x "$(command -v mountpoint)" || ! -x "$(command -v findmnt)" ]]; then
    echo "Les outils mountpoint et findmnt sont requis." >&2
    exit 1
fi
if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
    echo "Compte GravityNAS introuvable: ${SERVICE_USER}. Installez d'abord le NAS." >&2
    exit 1
fi

FSTAB_ENTRY="UUID=${UUID} ${MOUNT_POINT} ext4 noatime,nofail,x-systemd.device-timeout=10s 0 2"
FSTAB_ADDED=0
if awk -v target="${MOUNT_POINT}" '$0 !~ /^[[:space:]]*#/ && $2 == target { found=1 } END { exit !found }' /etc/fstab; then
    if ! awk -v target="${MOUNT_POINT}" -v uuid="UUID=${UUID}" \
        '$0 !~ /^[[:space:]]*#/ && $2 == target && $1 == uuid && $3 == "ext4" { found=1 } END { exit !found }' \
        /etc/fstab; then
        echo "Une autre entrée /etc/fstab utilise déjà ${MOUNT_POINT}; modifiez-la manuellement." >&2
        exit 1
    fi
else
    printf '%s\n' "${FSTAB_ENTRY}" >> /etc/fstab
    FSTAB_ADDED=1
fi

install -d -m 0755 "${MOUNT_POINT}"
if ! mountpoint -q "${MOUNT_POINT}"; then
    if ! mount "${MOUNT_POINT}"; then
        if [[ "${FSTAB_ADDED}" -eq 1 ]]; then
            FSTAB_TEMP="$(mktemp /etc/fstab.gravitynas.XXXXXX)"
            awk -v entry="${FSTAB_ENTRY}" '$0 != entry' /etc/fstab > "${FSTAB_TEMP}"
            install -o root -g root -m 0644 "${FSTAB_TEMP}" /etc/fstab
            rm -f "${FSTAB_TEMP}"
        fi
        echo "Montage impossible. Vérifiez /etc/fstab; le disque n'a pas été formaté." >&2
        exit 1
    fi
fi
MOUNTED_UUID="$(findmnt -n -o UUID --target "${MOUNT_POINT}")"
if [[ "${MOUNTED_UUID}" != "${UUID}" ]]; then
    if [[ "${FSTAB_ADDED}" -eq 1 ]]; then
        FSTAB_TEMP="$(mktemp /etc/fstab.gravitynas.XXXXXX)"
        awk -v entry="${FSTAB_ENTRY}" '$0 != entry' /etc/fstab > "${FSTAB_TEMP}"
        install -o root -g root -m 0644 "${FSTAB_TEMP}" /etc/fstab
        rm -f "${FSTAB_TEMP}"
    fi
    echo "Le volume monté sur ${MOUNT_POINT} n'est pas celui demandé." >&2
    exit 1
fi

systemctl stop gravitynas || true
chown "${SERVICE_USER}:gravitynas_users" "${MOUNT_POINT}"
chmod 2770 "${MOUNT_POINT}"
ENV_FILE="/etc/gravitynas/gravitynas.env"
ENV_TEMP="$(mktemp /etc/gravitynas/gravitynas.env.XXXXXX)"
grep -v '^GRAVITY_STORAGE_PATH=' "${ENV_FILE}" > "${ENV_TEMP}" || true
printf 'GRAVITY_STORAGE_PATH=%s\n' "${MOUNT_POINT}" >> "${ENV_TEMP}"
chown root:"${SERVICE_USER}" "${ENV_TEMP}"
chmod 0640 "${ENV_TEMP}"
mv -f "${ENV_TEMP}" "${ENV_FILE}"

install -d -o root -g root -m 0755 /etc/systemd/system/gravitynas.service.d
cat > /etc/systemd/system/gravitynas.service.d/storage.conf <<EOF
[Unit]
RequiresMountsFor=${MOUNT_POINT}

[Service]
ExecStartPre=/usr/bin/mountpoint -q ${MOUNT_POINT}
ReadWritePaths=${MOUNT_POINT}
EOF
if [[ -f /etc/samba/smb.conf ]]; then
    sed -i "s|^   path = .*|   path = ${MOUNT_POINT}/%S|" /etc/samba/smb.conf
fi
systemctl daemon-reload
systemctl restart gravitynas
systemctl restart smbd || true

echo "Stockage GravityNAS configuré sur ${DEVICE} (${UUID}), monté dans ${MOUNT_POINT}."
echo "Aucun formatage ni effacement n'a été effectué."