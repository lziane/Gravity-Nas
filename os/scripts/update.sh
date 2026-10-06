#!/usr/bin/env bash
set -Eeuo pipefail

INSTALL_ROOT="${GRAVITYNAS_INSTALL_DIR:-/opt/gravitynas}"
STATE_DIR="${GRAVITYNAS_STATE_DIR:-/var/lib/gravitynas}"
SERVICE_NAME="${GRAVITYNAS_SERVICE:-gravitynas}"
ENV_FILE="${GRAVITYNAS_ENV_FILE:-/etc/gravitynas/gravitynas.env}"
PUBLIC_KEY="${GRAVITYNAS_UPDATE_PUBLIC_KEY:-/etc/gravitynas/update.pub}"
SERVICE_URL="http://127.0.0.1:${NAS_PORT:-8000}/health"
RELEASE_DIR=""
PRESERVE_RELEASE=0

if [[ "${EUID}" -ne 0 ]]; then
    echo "Lancez le programme avec sudo." >&2
    exit 1
fi
if [[ -r "${ENV_FILE}" ]]; then
    set -a
    # Ce fichier est créé root:gravitynas et n'est pas modifiable par le service.
    # shellcheck disable=SC1090
    . "${ENV_FILE}"
    set +a
fi
exec 9>/run/lock/gravitynas-update.lock
if ! flock -n 9; then
    echo "Une mise à jour GravityNAS est déjà en cours." >&2
    exit 1
fi
SERVICE_URL="http://127.0.0.1:${NAS_PORT:-8000}/health"

TMP_DIR="$(mktemp -d)"
cleanup() {
    rm -rf "${TMP_DIR}"
    if [[ -n "${RELEASE_DIR}" && "${PRESERVE_RELEASE}" -eq 0 ]]; then
        local current="${INSTALL_ROOT}/current"
        local release_target="releases/$(basename "${RELEASE_DIR}")"
        if [[ ! -L "${current}" || "$(readlink "${current}")" != "${release_target}" ]]; then
            rm -rf "${RELEASE_DIR}"
        fi
    fi
}
trap cleanup EXIT

INPUT="${1:-${GRAVITYNAS_UPDATE_URL:-}}"
if [[ -z "${INPUT}" ]]; then
    echo "Usage: sudo gravitynas-update /chemin/gravitynas-VERSION.tar.gz" >&2
    echo "   ou: GRAVITYNAS_UPDATE_URL=https://.../gravitynas-VERSION.tar.gz sudo -E gravitynas-update" >&2
    exit 2
fi

if [[ "${INPUT}" =~ ^https:// ]]; then
    ARCHIVE="${TMP_DIR}/release.tar.gz"
    SIGNATURE="${TMP_DIR}/release.tar.gz.sig"
    curl --fail --location --proto '=https' --tlsv1.2 --silent --show-error \
        "${INPUT}" --output "${ARCHIVE}"
    curl --fail --location --proto '=https' --tlsv1.2 --silent --show-error \
        "${INPUT}.sig" --output "${SIGNATURE}"
elif [[ "${INPUT}" =~ ^https?:// ]]; then
    echo "Les mises à jour distantes doivent utiliser HTTPS." >&2
    exit 1
else
    ARCHIVE="$(realpath -e -- "${INPUT}")"
    SIGNATURE="${ARCHIVE}.sig"
fi

if [[ ! -f "${ARCHIVE}" || ! -f "${SIGNATURE}" ]]; then
    echo "Archive ou signature introuvable." >&2
    exit 1
fi
if [[ ! -r "${PUBLIC_KEY}" ]]; then
    echo "Clé publique de mise à jour absente: ${PUBLIC_KEY}" >&2
    echo "Installez la clé de confiance avant d'appliquer une release." >&2
    exit 1
fi
openssl dgst -sha256 -verify "${PUBLIC_KEY}" -signature "${SIGNATURE}" "${ARCHIVE}"

TAR_LIST="${TMP_DIR}/members.txt"
tar -tzf "${ARCHIVE}" > "${TAR_LIST}"
while IFS= read -r member; do
    case "${member}" in
        /*|../*|*/../*|*/..|..)
            echo "Chemin interdit dans l'archive: ${member}" >&2
            exit 1
            ;;
    esac
done < "${TAR_LIST}"

mkdir -p "${INSTALL_ROOT}/releases"
EXTRACT_DIR="${TMP_DIR}/release"
mkdir -p "${EXTRACT_DIR}"
tar --no-same-owner --no-same-permissions -xzf "${ARCHIVE}" -C "${EXTRACT_DIR}"
if [[ ! -f "${EXTRACT_DIR}/.gravitynas-release" || ! -f "${EXTRACT_DIR}/main.py" || ! -f "${EXTRACT_DIR}/requirements.txt" ]]; then
    echo "L'archive n'est pas une release GravityNAS valide." >&2
    exit 1
fi
VERSION="$(<"${EXTRACT_DIR}/.gravitynas-release")"
if [[ ! "${VERSION}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]]; then
    echo "Identifiant de release invalide." >&2
    exit 1
fi

RELEASE_DIR="${INSTALL_ROOT}/releases/${VERSION}"
if [[ -e "${RELEASE_DIR}" ]]; then
    echo "La release ${VERSION} est déjà installée." >&2
    exit 1
fi
mkdir "${RELEASE_DIR}"
cp -a "${EXTRACT_DIR}/." "${RELEASE_DIR}/"
python3 -m venv "${RELEASE_DIR}/venv"
"${RELEASE_DIR}/venv/bin/pip" install --disable-pip-version-check --no-cache-dir \
    -r "${RELEASE_DIR}/requirements.txt"
"${RELEASE_DIR}/venv/bin/python" -m compileall -q \
    "${RELEASE_DIR}/main.py" "${RELEASE_DIR}/app" "${RELEASE_DIR}/routes"
chown -R root:root "${RELEASE_DIR}"
chmod -R u=rwX,go=rX "${RELEASE_DIR}"

CURRENT_LINK="${INSTALL_ROOT}/current"
if [[ ! -L "${CURRENT_LINK}" ]]; then
    echo "Installation versionnée introuvable: ${CURRENT_LINK} doit être un lien symbolique." >&2
    exit 1
fi
PREVIOUS_TARGET="$(readlink "${CURRENT_LINK}")"
if [[ "${PREVIOUS_TARGET}" != releases/* || ! -d "${INSTALL_ROOT}/${PREVIOUS_TARGET}" ]]; then
    echo "La version active actuelle n'est pas valide; mise à jour annulée." >&2
    exit 1
fi

atomic_switch() {
    local target="$1"
    local next_link="${INSTALL_ROOT}/.current.$$"
    ln -s "${target}" "${next_link}"
    mv -Tf "${next_link}" "${CURRENT_LINK}"
}

DB_PATH="${GRAVITY_DATA_PATH:-${STATE_DIR}/data}/${GRAVITY_DB_NAME:-users_auth.db}"
DB_BACKUP_DIR="${STATE_DIR}/backups/updates"
DB_BACKUP=""
if [[ -f "${DB_PATH}" ]]; then
    mkdir -p "${DB_BACKUP_DIR}"
    DB_BACKUP="${DB_BACKUP_DIR}/users_auth-$(date +%Y%m%d-%H%M%S).db"
    python3 - "${DB_PATH}" "${DB_BACKUP}" <<'PY'
import sqlite3
import sys

source = sqlite3.connect(sys.argv[1])
destination = sqlite3.connect(sys.argv[2])
try:
    source.backup(destination)
finally:
    destination.close()
    source.close()
PY
    chmod 0600 "${DB_BACKUP}"
fi

systemctl stop "${SERVICE_NAME}" || true
atomic_switch "releases/${VERSION}"
if systemctl start "${SERVICE_NAME}" && \
    curl --fail --silent --show-error --retry 20 --retry-delay 1 \
        --retry-connrefused --max-time 3 "${SERVICE_URL}" >/dev/null; then
    PRESERVE_RELEASE=1
    install -o root -g root -m 0755 "${RELEASE_DIR}/os/scripts/configure-usb-storage.sh" \
        /usr/local/sbin/gravitynas-storage
    install -o root -g root -m 0755 "${RELEASE_DIR}/os/scripts/update.sh" \
        /usr/local/sbin/gravitynas-update
    echo "GravityNAS ${VERSION} est installé et répond au contrôle de santé."
    echo "Version précédente conservée pour permettre un retour arrière manuel: ${PREVIOUS_TARGET}"
    exit 0
fi

echo "Échec du démarrage ou du contrôle de santé; retour à ${PREVIOUS_TARGET}." >&2
systemctl stop "${SERVICE_NAME}" || true
if [[ -n "${DB_BACKUP}" ]]; then
    rm -f "${DB_PATH}-wal" "${DB_PATH}-shm"
    cp -a "${DB_BACKUP}" "${DB_PATH}"
fi
atomic_switch "${PREVIOUS_TARGET}"
if ! systemctl start "${SERVICE_NAME}"; then
    echo "ATTENTION: le service n'a pas redémarré après le retour arrière." >&2
fi
exit 1