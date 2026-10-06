#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SOURCE_IMAGE="${1:-}"
VERSION="${2:-}"
PUBLIC_KEY="${GRAVITYNAS_UPDATE_PUBLIC_KEY:-}"
OUTPUT_IMAGE="${3:-}"
SERVICE_USER="${GRAVITYNAS_USER:-gravitynas}"
HOSTNAME_NAME="${GRAVITYNAS_HOSTNAME:-gravitynas}"
STATE_DIR="${GRAVITYNAS_STATE_DIR:-/var/lib/gravitynas}"
STORAGE_DIR="${GRAVITYNAS_STORAGE_PATH:-${STATE_DIR}/storage}"

if [[ "${EUID}" -ne 0 ]]; then
    echo "Lancez l'intégration avec sudo/root." >&2
    exit 1
fi
if [[ -z "${SOURCE_IMAGE}" || ! -f "${SOURCE_IMAGE}" || -z "${VERSION}" ||
      ! "${VERSION}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]]; then
    echo "Usage: $0 BASE.img.xz VERSION [gravitynas.img.xz]" >&2
    exit 2
fi
if [[ -z "${PUBLIC_KEY}" || ! -r "${PUBLIC_KEY}" ]]; then
    echo "GRAVITYNAS_UPDATE_PUBLIC_KEY doit désigner la clé publique des releases." >&2
    exit 2
fi
if [[ ! "${STATE_DIR}" =~ ^/[A-Za-z0-9_./-]+$ ||
      ! "${STORAGE_DIR}" =~ ^/[A-Za-z0-9_./-]+$ ||
      ! "${SERVICE_USER}" =~ ^[a-z_][a-z0-9_-]*$ ||
      ! "${HOSTNAME_NAME}" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
    echo "Utilisateur, hostname ou chemin invalide." >&2
    exit 2
fi
if [[ "${STORAGE_DIR}" != "${STATE_DIR}/storage" ]]; then
    echo "Configurez le disque USB avec gravitynas-storage au premier démarrage." >&2
    exit 2
fi
for command in xz losetup mount umount rsync chroot systemctl openssl blkid sha256sum mountpoint mknod; do
    command -v "${command}" >/dev/null 2>&1 || {
        echo "Commande requise introuvable: ${command}" >&2
        exit 1
    }
done

SOURCE_IMAGE="$(realpath -e -- "${SOURCE_IMAGE}")"
OUTPUT_IMAGE="${OUTPUT_IMAGE:-${SOURCE_IMAGE%.img.xz}-nas-${VERSION}.img.xz}"
OUTPUT_IMAGE="$(realpath -m -- "${OUTPUT_IMAGE}")"
if [[ "${SOURCE_IMAGE}" == "${OUTPUT_IMAGE}" || -e "${OUTPUT_IMAGE}" ]]; then
    echo "La sortie doit être nouvelle; l'image source ne sera pas écrasée." >&2
    exit 1
fi
openssl pkey -pubin -in "${PUBLIC_KEY}" -noout

OUTPUT_DIR="$(dirname "${OUTPUT_IMAGE}")"
WORK_DIR="$(mktemp -d "${OUTPUT_DIR}/.gravitynas-image.XXXXXX")"
RAW_IMAGE="${WORK_DIR}/image.img"
ROOT_MOUNT="${WORK_DIR}/root"
LOOP_DEVICE=""
MOUNTS=()
RESOLV_TARGET=""
RESOLV_KIND=""
RESOLV_LINK=""
RESOLV_BACKUP="${WORK_DIR}/resolv.conf.original"

restore_resolv_conf() {
    if [[ -z "${RESOLV_KIND}" || -z "${RESOLV_TARGET}" ]]; then
        return
    fi
    if [[ "${RESOLV_KIND}" == "symlink" ]]; then
        rm -f "${RESOLV_TARGET}"
        ln -s "${RESOLV_LINK}" "${RESOLV_TARGET}"
    else
        cp -a "${RESOLV_BACKUP}" "${RESOLV_TARGET}"
    fi
    RESOLV_KIND=""
    RESOLV_TARGET=""
}

unmount_rootfs() {
    local index
    for ((index=${#MOUNTS[@]}-1; index>0; index--)); do
        umount -lf "${MOUNTS[index]}" 2>/dev/null || true
    done
    restore_resolv_conf
    if [[ ${#MOUNTS[@]} -gt 0 ]]; then
        umount -lf "${MOUNTS[0]}" 2>/dev/null || true
    fi
    MOUNTS=()
}

cleanup() {
    unmount_rootfs
    if [[ -n "${LOOP_DEVICE}" ]]; then
        losetup -d "${LOOP_DEVICE}" 2>/dev/null || true
    fi
    rm -rf "${WORK_DIR}"
}
trap cleanup EXIT INT TERM

mkdir -p "${ROOT_MOUNT}"
echo "Décompression de l'image de base; l'original reste intact."
xz --decompress --stdout -- "${SOURCE_IMAGE}" > "${RAW_IMAGE}"
for device_info in /sys/block/loop[0-9]*/dev; do
    device_name="$(basename "$(dirname "${device_info}")")"
    if [[ ! -b "/dev/${device_name}" ]]; then
        IFS=: read -r device_major device_minor < "${device_info}"
        mknod -m 0660 "/dev/${device_name}" b "${device_major}" "${device_minor}"
    fi
done
LOOP_DEVICE="$(losetup --find --show --partscan "${RAW_IMAGE}")"
LOOP_NAME="$(basename "${LOOP_DEVICE}")"
for partition_number in 1 2; do
    partition_name="${LOOP_NAME}p${partition_number}"
    partition_info="/sys/class/block/${partition_name}/dev"
    if [[ ! -b "/dev/${partition_name}" && -r "${partition_info}" ]]; then
        IFS=: read -r partition_major partition_minor < "${partition_info}"
        mknod -m 0600 "/dev/${partition_name}" b "${partition_major}" "${partition_minor}"
    fi
done
ROOT_PART="${LOOP_DEVICE}p2"
BOOT_PART="${LOOP_DEVICE}p1"
if [[ ! -b "${ROOT_PART}" || ! -b "${BOOT_PART}" ]]; then
    echo "Partitions Pi attendues introuvables sur ${LOOP_DEVICE}." >&2
    exit 1
fi
if [[ "$(blkid -o value -s TYPE "${ROOT_PART}")" != "ext4" ]]; then
    echo "La partition racine de l'image n'est pas ext4." >&2
    exit 1
fi
mount "${ROOT_PART}" "${ROOT_MOUNT}"
MOUNTS+=("${ROOT_MOUNT}")
install -d "${ROOT_MOUNT}/boot/firmware"
mount "${BOOT_PART}" "${ROOT_MOUNT}/boot/firmware"
MOUNTS+=("${ROOT_MOUNT}/boot/firmware")
for directory in dev dev/pts proc sys; do
    install -d "${ROOT_MOUNT}/${directory}"
    mount --rbind "/${directory}" "${ROOT_MOUNT}/${directory}"
    MOUNTS+=("${ROOT_MOUNT}/${directory}")
    mount --make-rslave "${ROOT_MOUNT}/${directory}"
done

RESOLV_TARGET="${ROOT_MOUNT}/etc/resolv.conf"
if [[ -L "${RESOLV_TARGET}" ]]; then
    RESOLV_KIND="symlink"
    RESOLV_LINK="$(readlink "${RESOLV_TARGET}")"
    rm -f "${RESOLV_TARGET}"
    : > "${RESOLV_TARGET}"
else
    RESOLV_KIND="file"
    cp -a "${RESOLV_TARGET}" "${RESOLV_BACKUP}"
fi
cp /etc/resolv.conf "${RESOLV_TARGET}"

chroot "${ROOT_MOUNT}" /bin/bash -euc '
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y --no-install-recommends \
        python3-venv python3-pip python3-psutil nginx samba samba-common-bin \
        avahi-daemon rsync sqlite3 curl openssl ca-certificates
'

RELEASE_DIR="${ROOT_MOUNT}/opt/gravitynas/releases/${VERSION}"
if [[ -e "${RELEASE_DIR}" ]]; then
    echo "La release ${VERSION} existe déjà dans l'image." >&2
    exit 1
fi
install -d -o root -g root -m 0755 "${RELEASE_DIR}"
rsync -a --delete \
    --exclude='.git/' --exclude='.venv/' --exclude='venv/' \
    --exclude='__pycache__/' --exclude='.pytest_cache/' \
    --exclude='data/' --exclude='backups/' --exclude='nas_storage/' \
    --exclude='build/' --exclude='*.db' --exclude='*.db-*' \
    --exclude='.nas_encryption.key' --exclude='*.pyc' \
    "${ROOT_DIR}/" "${RELEASE_DIR}/"
printf '%s\n' "${VERSION}" > "${RELEASE_DIR}/.gravitynas-release"

install -d -o root -g root -m 0755 "${ROOT_MOUNT}/etc/gravitynas"
install -o root -g root -m 0644 "${PUBLIC_KEY}" "${ROOT_MOUNT}/etc/gravitynas/update.pub"
install -o root -g root -m 0640 \
    "${RELEASE_DIR}/os/etc/gravitynas.env.example" \
    "${ROOT_MOUNT}/etc/gravitynas/gravitynas.env"
install -o root -g root -m 0644 "${RELEASE_DIR}/os/systemd/gravitynas.service" \
    "${ROOT_MOUNT}/etc/systemd/system/gravitynas.service"
install -o root -g root -m 0644 "${RELEASE_DIR}/config/nginx.conf" \
    "${ROOT_MOUNT}/etc/nginx/sites-available/gravitynas"
install -o root -g root -m 0644 "${RELEASE_DIR}/os/etc/samba/gravitynas.conf" \
    "${ROOT_MOUNT}/etc/samba/smb.conf"
install -o root -g root -m 0755 "${RELEASE_DIR}/os/scripts/update.sh" \
    "${ROOT_MOUNT}/usr/local/sbin/gravitynas-update"
install -o root -g root -m 0755 "${RELEASE_DIR}/os/scripts/configure-usb-storage.sh" \
    "${ROOT_MOUNT}/usr/local/sbin/gravitynas-storage"

CHROOT_SETUP="${ROOT_MOUNT}/tmp/gravitynas-image-setup.sh"
cat > "${CHROOT_SETUP}" <<'CHROOT'
#!/usr/bin/env bash
set -euo pipefail
if ! id -u "${GRAVITYNAS_USER}" >/dev/null 2>&1; then
    useradd --system --home-dir "${GRAVITYNAS_STATE_DIR}" --create-home \
        --shell /usr/sbin/nologin "${GRAVITYNAS_USER}"
fi
groupadd -f gravitynas_users
usermod -aG gravitynas_users "${GRAVITYNAS_USER}"
install -d -o "${GRAVITYNAS_USER}" -g "${GRAVITYNAS_USER}" -m 0700 \
    "${GRAVITYNAS_STATE_DIR}" "${GRAVITYNAS_STATE_DIR}/data" \
    "${GRAVITYNAS_STATE_DIR}/backups"
install -d -o "${GRAVITYNAS_USER}" -g gravitynas_users -m 2770 \
    "${GRAVITYNAS_STORAGE_PATH}"
release="/opt/gravitynas/releases/${GRAVITYNAS_VERSION}"
chown -R root:root "${release}"
chmod -R u=rwX,go=rX "${release}"
ln -s "releases/${GRAVITYNAS_VERSION}" /opt/gravitynas/current
python3 -m venv "${release}/venv"
"${release}/venv/bin/pip" install --disable-pip-version-check \
    -r "${release}/requirements.txt"
"${release}/venv/bin/python" -m compileall -q \
    "${release}/main.py" "${release}/app" "${release}/routes"
sed -i "s|^GRAVITY_STORAGE_PATH=.*|GRAVITY_STORAGE_PATH=${GRAVITYNAS_STORAGE_PATH}|" \
    /etc/gravitynas/gravitynas.env
sed -i "s|^GRAVITY_DATA_PATH=.*|GRAVITY_DATA_PATH=${GRAVITYNAS_STATE_DIR}/data|" \
    /etc/gravitynas/gravitynas.env
sed -i -E "s|server_name[[:space:]]+nas\.local[[:space:]]+_;|server_name ${GRAVITYNAS_HOSTNAME}.local _;|" \
    /etc/nginx/sites-available/gravitynas
sed -i "s|^   path = .*|   path = ${GRAVITYNAS_STORAGE_PATH}/%S|" /etc/samba/smb.conf
ln -sfn /etc/nginx/sites-available/gravitynas /etc/nginx/sites-enabled/gravitynas
rm -f /etc/nginx/sites-enabled/default
chown root:"${GRAVITYNAS_USER}" /etc/gravitynas
chown root:"${GRAVITYNAS_USER}" /etc/gravitynas/gravitynas.env
chmod 0750 /etc/gravitynas
chmod 0640 /etc/gravitynas/gravitynas.env
printf '%s\n' "${GRAVITYNAS_HOSTNAME}" > /etc/hostname
nginx -t
CHROOT
chmod 0755 "${CHROOT_SETUP}"
chroot "${ROOT_MOUNT}" /usr/bin/env \
    "GRAVITYNAS_VERSION=${VERSION}" \
    "GRAVITYNAS_USER=${SERVICE_USER}" \
    "GRAVITYNAS_HOSTNAME=${HOSTNAME_NAME}" \
    "GRAVITYNAS_STATE_DIR=${STATE_DIR}" \
    "GRAVITYNAS_STORAGE_PATH=${STORAGE_DIR}" \
    /bin/bash /tmp/gravitynas-image-setup.sh
rm -f "${CHROOT_SETUP}"

systemctl --root="${ROOT_MOUNT}" enable gravitynas nginx smbd avahi-daemon
for required in \
    "${RELEASE_DIR}/main.py" \
    "${ROOT_MOUNT}/etc/gravitynas/update.pub"; do
    if [[ ! -e "${required}" ]]; then
        echo "Validation rootfs échouée, fichier manquant: ${required}" >&2
        exit 1
    fi
done
if [[ ! -e "${RELEASE_DIR}/venv/bin/python" && ! -L "${RELEASE_DIR}/venv/bin/python" ]]; then
    echo "Validation rootfs échouée: exécutable Python du venv absent." >&2
    exit 1
fi
if [[ ! -L "${ROOT_MOUNT}/etc/systemd/system/multi-user.target.wants/gravitynas.service" ]]; then
    echo "Validation rootfs échouée: le service GravityNAS n'est pas activé." >&2
    exit 1
fi

unmount_rootfs
losetup -d "${LOOP_DEVICE}"
LOOP_DEVICE=""
xz --threads=0 --compress --check=crc64 --stdout "${RAW_IMAGE}" > "${OUTPUT_IMAGE}"
xz --test "${OUTPUT_IMAGE}"
sha256sum "${OUTPUT_IMAGE}" > "${OUTPUT_IMAGE}.sha256"
printf 'GravityNAS %s intégré\nBase: %s\nSortie: %s\n' \
    "${VERSION}" "${SOURCE_IMAGE}" "${OUTPUT_IMAGE}" \
    > "${OUTPUT_IMAGE}.info"
echo "Image GravityNAS vérifiée: ${OUTPUT_IMAGE}"
