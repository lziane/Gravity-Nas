#!/bin/bash
# ╔══════════════════════════════════════════════════════════╗
# ║      GravityNAS — Mise à Jour Logique & Design           ║
# ║      ZERO PERTE DE DONNÉES — AUTO-REBOOT OPTIONNEL       ║
# ╚══════════════════════════════════════════════════════════╝

set -e

# --- Détection de l'utilisateur réel ---
REAL_USER=${SUDO_USER:-$(id -un)}
NAS_DIR="/opt/gravitynas"
SERVICE_NAME="gravitynas"
BACKUP_DIR="${NAS_DIR}/backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}╔════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   GravityNAS — Mise à Jour Rapide & Sécurisée      ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════╝${NC}"

# Vérification root
if [ "$(id -u)" -ne 0 ]; then
    echo -e "❌ Ce script doit être lancé avec sudo."
    exit 1
fi

echo -e "${YELLOW}[1/5] Arrêt du service GravityNAS...${NC}"
systemctl stop "$SERVICE_NAME" || true

echo -e "${YELLOW}[2/5] Sauvegarde de sécurité des bases de données...${NC}"
mkdir -p "$BACKUP_DIR"
# Sauvegarde des fichiers critiques avant la mise à jour
for db in "users_auth.db" "nas_storage/.nas_metadata.db"; do
    if [ -f "$NAS_DIR/$db" ]; then
        db_name=$(basename "$db")
        cp "$NAS_DIR/$db" "$BACKUP_DIR/${db_name}_${TIMESTAMP}.bak"
        echo -e "      -> $db_name sauvegardée dans $BACKUP_DIR"
    fi
done

# Nettoyage des vieux backups (garde les 10 derniers)
ls -tp "$BACKUP_DIR"/*.bak 2>/dev/null | grep -v '/$' | tail -n +11 | xargs -r rm -- || true

echo -e "${YELLOW}[3/5] Synchronisation du nouveau code...${NC}"
# On remonte d'un cran car le script est dans /scripts/
SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)/"
rsync -a --delete \
    --exclude='nas_storage/' \
    --exclude='*.db*' \
    --exclude='backups/' \
    --exclude='venv/' \
    --exclude='.git/' \
    --exclude='__pycache__/' \
    "$SRC_DIR" "$NAS_DIR/"


chown -R "$REAL_USER:$REAL_USER" "$NAS_DIR"

echo -e "${YELLOW}[4/5] Mise à jour des dépendances...${NC}"
sudo -u "$REAL_USER" "$NAS_DIR/venv/bin/pip" install -r "$NAS_DIR/requirements.txt" -q

echo -e "${YELLOW}[5/5] Redémarrage du service...${NC}"
systemctl daemon-reload
systemctl start "$SERVICE_NAME"

echo -e "\n${GREEN}✅ MISE À JOUR TERMINÉE !${NC}"
echo -e "Vos données sont intactes. Le NAS est à jour."
