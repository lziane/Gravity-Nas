#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="${1:-}"
OUTPUT_DIR="${2:-${ROOT_DIR}/build/releases}"
SIGNING_KEY="${GRAVITYNAS_SIGNING_KEY:-}"

if [[ ! "${VERSION}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]]; then
    echo "Usage: GRAVITYNAS_SIGNING_KEY=/path/to/private.pem $0 VERSION [output-dir]" >&2
    exit 2
fi
if [[ -z "${SIGNING_KEY}" || ! -f "${SIGNING_KEY}" ]]; then
    echo "GRAVITYNAS_SIGNING_KEY doit désigner la clé privée de signature." >&2
    exit 2
fi
for command in openssl rsync tar gzip sha256sum; do
    command -v "${command}" >/dev/null 2>&1 || {
        echo "Commande requise introuvable: ${command}" >&2
        exit 1
    }
done

mkdir -p "${OUTPUT_DIR}"
ARCHIVE="${OUTPUT_DIR}/gravitynas-${VERSION}.tar.gz"
SIGNATURE="${ARCHIVE}.sig"
if [[ -e "${ARCHIVE}" || -e "${SIGNATURE}" ]]; then
    echo "Cette release existe déjà: ${ARCHIVE}" >&2
    exit 1
fi

STAGING="$(mktemp -d)"
trap 'rm -rf "${STAGING}"' EXIT
rsync -a --delete \
    --exclude='.git/' --exclude='.venv/' --exclude='venv/' \
    --exclude='__pycache__/' --exclude='.pytest_cache/' \
    --exclude='data/' --exclude='backups/' --exclude='nas_storage/' \
    --exclude='build/' --exclude='*.db' --exclude='*.db-*' \
    --exclude='.nas_encryption.key' --exclude='*.pyc' \
    "${ROOT_DIR}/" "${STAGING}/"
printf '%s\n' "${VERSION}" > "${STAGING}/.gravitynas-release"

tar --sort=name --mtime='UTC 1970-01-01' --owner=0 --group=0 --numeric-owner \
    -C "${STAGING}" -cf - . | gzip -n > "${ARCHIVE}"
openssl dgst -sha256 -sign "${SIGNING_KEY}" -out "${SIGNATURE}" "${ARCHIVE}"
sha256sum "${ARCHIVE}" > "${ARCHIVE}.sha256"
openssl pkey -in "${SIGNING_KEY}" -pubout -out "${OUTPUT_DIR}/gravitynas-update.pub"

echo "Release créée: ${ARCHIVE}"
echo "Signature: ${SIGNATURE}"
echo "Clé publique à installer sur le NAS: ${OUTPUT_DIR}/gravitynas-update.pub"