#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="${1:-}"
OUTPUT_DIR="${2:-${ROOT_DIR}/build/gravitynas-image}"
PI_GEN_REF="${GRAVITYNAS_PI_GEN_REF:-arm64}"
PUBLIC_KEY="${GRAVITYNAS_UPDATE_PUBLIC_KEY:-}"

if [[ ! "${VERSION}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]]; then
    echo "Usage: GRAVITYNAS_UPDATE_PUBLIC_KEY=/path/to/update.pub sudo -E $0 VERSION [output-dir]" >&2
    exit 2
fi
if [[ "${EUID}" -ne 0 ]]; then
    echo "La construction pi-gen doit être lancée avec sudo/root." >&2
    exit 1
fi
if [[ -z "${PUBLIC_KEY}" || ! -r "${PUBLIC_KEY}" ]]; then
    echo "GRAVITYNAS_UPDATE_PUBLIC_KEY doit désigner la clé publique de signature." >&2
    exit 2
fi
openssl pkey -pubin -in "${PUBLIC_KEY}" -noout
for command in git rsync openssl; do
    command -v "${command}" >/dev/null 2>&1 || {
        echo "Commande requise introuvable: ${command}" >&2
        exit 1
    }
done
if [[ -e "${OUTPUT_DIR}" ]]; then
    echo "Le dossier de sortie existe déjà: ${OUTPUT_DIR}" >&2
    exit 1
fi

OUTPUT_DIR="$(realpath -m "${OUTPUT_DIR}")"
PI_GEN_DIR="${OUTPUT_DIR}/pi-gen"
DEPLOY_DIR="${OUTPUT_DIR}/deploy"
mkdir -p "${OUTPUT_DIR}"
git clone --depth 1 --branch "${PI_GEN_REF}" \
    https://github.com/RPi-Distro/pi-gen.git "${PI_GEN_DIR}"
# Bazzite's container overlay rejects security.selinux xattrs on nested rootfs copies.
sed -i "s/rsync -aHAXx --numeric-ids/rsync -aHAXx --filter='-x security.selinux' --numeric-ids/" \
    "${PI_GEN_DIR}/scripts/common"
cp -a "${ROOT_DIR}/os/image/stage-gravitynas" "${PI_GEN_DIR}/"
mkdir -p "${PI_GEN_DIR}/stage-gravitynas/00-install/files/gravitynas"
chmod 0755 "${PI_GEN_DIR}/stage-gravitynas/00-install/01-run.sh"
rsync -a --delete \
    --exclude='.git/' --exclude='.venv/' --exclude='venv/' \
    --exclude='__pycache__/' --exclude='.pytest_cache/' \
    --exclude='data/' --exclude='backups/' --exclude='nas_storage/' \
    --exclude='build/' --exclude='*.db' --exclude='*.db-*' \
    --exclude='.nas_encryption.key' --exclude='*.pyc' \
    "${ROOT_DIR}/" "${PI_GEN_DIR}/stage-gravitynas/00-install/files/gravitynas/"
printf '%s\n' "${VERSION}" > "${PI_GEN_DIR}/stage-gravitynas/00-install/files/version"
install -m 0644 "${PUBLIC_KEY}" "${PI_GEN_DIR}/stage-gravitynas/00-install/files/update.pub"

if [[ "${GRAVITYNAS_IMAGE_OCR:-0}" == "1" ]]; then
    printf '%s\n' tesseract-ocr tesseract-ocr-fra \
        >> "${PI_GEN_DIR}/stage-gravitynas/00-install/00-packages"
fi

ADMIN_PASSWORD="$(openssl rand -hex 18)"
umask 077
cat > "${PI_GEN_DIR}/config" <<EOF
IMG_NAME='gravitynas-pi4'
RELEASE='trixie'
ARCH='arm64'
DEPLOY_COMPRESSION='xz'
DEPLOY_DIR='${DEPLOY_DIR}'
ENABLE_SSH=1
FIRST_USER_NAME='nasadmin'
FIRST_USER_PASS='${ADMIN_PASSWORD}'
LOCALE_DEFAULT='fr_FR.UTF-8'
TIMEZONE_DEFAULT='Europe/Paris'
KEYBOARD_KEYMAP='fr'
KEYBOARD_LAYOUT='French'
STAGE_LIST="stage0 stage1 stage2 stage-gravitynas"
EOF
printf 'Utilisateur SSH: nasadmin\nMot de passe initial: %s\n' "${ADMIN_PASSWORD}" \
    > "${OUTPUT_DIR}/credentials.txt"
chmod 0600 "${PI_GEN_DIR}/config" "${OUTPUT_DIR}/credentials.txt"
if [[ -n "${SUDO_UID:-}" && -n "${SUDO_GID:-}" ]]; then
    chown "${SUDO_UID}:${SUDO_GID}" "${OUTPUT_DIR}/credentials.txt"
fi

cd "${PI_GEN_DIR}"
./build.sh
if ! grep -Fq "Begin ${PI_GEN_DIR}/stage-gravitynas/00-install/01-run.sh" \
    "${WORK_DIR:-${PI_GEN_DIR}/work/gravitynas-pi4}/build.log"; then
    echo "Le stage GravityNAS n'a pas été exécuté; refus d'annoncer une image NAS." >&2
    exit 1
fi
printf 'GravityNAS %s\npi-gen ref: %s\npi-gen commit: %s\n' \
    "${VERSION}" "${PI_GEN_REF}" "$(git rev-parse HEAD)" \
    > "${OUTPUT_DIR}/build-info.txt"
if [[ -n "${SUDO_UID:-}" && -n "${SUDO_GID:-}" ]]; then
    chown -R "${SUDO_UID}:${SUDO_GID}" "${DEPLOY_DIR}"
    chown "${SUDO_UID}:${SUDO_GID}" "${OUTPUT_DIR}/build-info.txt"
fi

echo "Image GravityNAS créée dans: ${DEPLOY_DIR}"
echo "Identifiants initiaux (fichier privé): ${OUTPUT_DIR}/credentials.txt"
echo "Flashez l'image .img.xz sur une microSD avec Raspberry Pi Imager."