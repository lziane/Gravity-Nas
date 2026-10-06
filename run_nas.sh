#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
PYTHON="${VENV_DIR}/bin/python"

if ! command -v python3 >/dev/null 2>&1; then
    echo "Erreur: python3 est requis. Installez-le avec: sudo apt install python3 python3-venv" >&2
    exit 1
fi

if [[ ! -x "${PYTHON}" ]]; then
    echo "Creation de l'environnement Python local..."
    if ! python3 -m venv "${VENV_DIR}"; then
        echo "Erreur: le module venv manque. Lancez: sudo apt install python3-venv" >&2
        exit 1
    fi
fi

if ! "${PYTHON}" -m pip --version >/dev/null 2>&1; then
    echo "Environnement incomplet, recreation de .venv..."
    rm -rf "${VENV_DIR}"
    if ! python3 -m venv "${VENV_DIR}"; then
        echo "Erreur: le module venv manque. Lancez: sudo apt install python3-venv" >&2
        exit 1
    fi
fi

if [[ ! -f "${VENV_DIR}/.requirements-installed" || "${ROOT_DIR}/requirements.txt" -nt "${VENV_DIR}/.requirements-installed" ]]; then
    echo "Installation des dependances Python..."
    PIP_DISABLE_PIP_VERSION_CHECK=1 "${PYTHON}" -m pip install --disable-pip-version-check -q -r "${ROOT_DIR}/requirements.txt"
    touch "${VENV_DIR}/.requirements-installed"
fi

cd "${ROOT_DIR}"
# Remote access is opt-in. It still requires remote_enabled=1 and a token.
export GRAVITY_ALLOW_REMOTE="${GRAVITY_ALLOW_REMOTE:-0}"
exec "${PYTHON}" main.py "$@"
