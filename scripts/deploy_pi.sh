#!/bin/bash
# ╔══════════════════════════════════════════════════════════╗
# ║      GravityNAS — Déploiement Raspberry Pi OS Lite       ║
# ║      Avec serveur web Nginx + URL personnalisée          ║
# ╚══════════════════════════════════════════════════════════╝
# Usage : chmod +x deploy_pi.sh && sudo ./deploy_pi.sh

set -e

NAS_DIR="/opt/gravitynas"
NAS_USER="pi"
SERVICE_NAME="gravitynas"
HOSTNAME_CUSTOM="gravitynas"   # → accessible via gravitynas.local

echo ""
echo "╔══════════════════════════════════════╗"
echo "║   GravityNAS — Installation Auto     ║"
echo "╚══════════════════════════════════════╝"
echo ""

# Vérification root
if [ "$(id -u)" -ne 0 ]; then
    echo "❌ Ce script doit être lancé avec sudo."
    exit 1
fi

# ── 1. Mise à jour système ─────────────────────────────
echo "[1/10] Mise à jour système..."
apt-get update -qq
apt-get upgrade -y -qq

# ── 2. Dépendances système ────────────────────────────
echo "[2/10] Installation des dépendances..."
apt-get install -y -qq \
    python3 python3-pip python3-venv python3-psutil \
    nginx certbot python3-certbot-nginx \
    avahi-daemon \
    git curl sqlite3 \
    libffi-dev libssl-dev

# ── 3. Hostname (pour accès via gravitynas.local) ─────
echo "[3/10] Configuration du nom réseau : ${HOSTNAME_CUSTOM}.local ..."
hostnamectl set-hostname "$HOSTNAME_CUSTOM"

# Avahi pour la découverte mDNS (.local)
systemctl enable avahi-daemon 2>/dev/null || true
systemctl start  avahi-daemon 2>/dev/null || true

# ── 4. Copie du projet ────────────────────────────────
echo "[4/10] Installation du projet dans $NAS_DIR..."
mkdir -p "$NAS_DIR"

if ! command -v rsync &> /dev/null; then
    apt-get install -y rsync -qq
fi

# Utilisation de rsync pour sécuriser une potentielle double-installation
# et ne pas écraser les bases de données / stockages existants par erreur
rsync -a \
    --exclude='nas_storage/' \
    --exclude='users_auth.db*' \
    --exclude='backups/' \
    --exclude='venv/' \
    --exclude='.git/' \
    "$(dirname "$0")/" "$NAS_DIR/"

chown -R "$NAS_USER:$NAS_USER" "$NAS_DIR"

# ── 5. Environnement virtuel Python ──────────────────
echo "[5/10] Création de l'environnement Python..."
sudo -u "$NAS_USER" python3 -m venv "$NAS_DIR/venv"
sudo -u "$NAS_USER" "$NAS_DIR/venv/bin/pip" install --upgrade pip -q
sudo -u "$NAS_USER" "$NAS_DIR/venv/bin/pip" install -r "$NAS_DIR/requirements.txt" -q

# ── 6. Dossier de stockage et utilitaires ────────────
echo "[6/10] Préparation des dossiers..."
mkdir -p "$NAS_DIR/nas_storage"
mkdir -p "$NAS_DIR/static"
mkdir -p "$NAS_DIR/bin"
chown -R "$NAS_USER:$NAS_USER" "$NAS_DIR/nas_storage"
chown -R "$NAS_USER:$NAS_USER" "$NAS_DIR/static"
chown -R "$NAS_USER:$NAS_USER" "$NAS_DIR/bin"

# ── 7. Optimisations carte SD ────────────────────────
echo "[7/10] Optimisations Raspberry Pi..."
if ! grep -q "vm.swappiness=10" /etc/sysctl.conf 2>/dev/null; then
    echo "vm.swappiness=10" >> /etc/sysctl.conf
    sysctl vm.swappiness=10
fi
if ! grep -q "noatime" /etc/fstab 2>/dev/null; then
    sed -i 's/defaults/defaults,noatime/g' /etc/fstab
fi

# ── 8. Service systemd ───────────────────────────────
echo "[8/10] Création du service systemd..."
cat > "/etc/systemd/system/$SERVICE_NAME.service" << EOF
[Unit]
Description=GravityNAS — Serveur NAS personnel
After=network.target
Wants=network-online.target

[Service]
Type=exec
User=$NAS_USER
WorkingDirectory=$NAS_DIR
ExecStart=$NAS_DIR/venv/bin/python $NAS_DIR/main.py
Restart=always
RestartSec=5
MemoryMax=512M
Nice=0
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl start  "$SERVICE_NAME"

# ── 9. Configuration Nginx ────────────────────────────
echo "[9/10] Configuration du serveur web Nginx..."
cp "$NAS_DIR/gravitynas.nginx.conf" /etc/nginx/sites-available/gravitynas

# Adapter les chemins dans la config
sed -i "s|/opt/gravitynas|${NAS_DIR}|g" /etc/nginx/sites-available/gravitynas
sed -i "s|nas.local|${HOSTNAME_CUSTOM}.local|g" /etc/nginx/sites-available/gravitynas

ln -sf /etc/nginx/sites-available/gravitynas /etc/nginx/sites-enabled/gravitynas
rm -f /etc/nginx/sites-enabled/default

# Test de syntaxe puis redémarrage
nginx -t && systemctl restart nginx
systemctl enable nginx

# ── 10. Résumé final ──────────────────────────────────
PI_IP=$(hostname -I | awk '{print $1}')

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║           ✅  GravityNAS est INSTALLÉ !              ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║                                                      ║"
echo "║  🌐 Accès réseau local :                             ║"
echo "║     → http://${HOSTNAME_CUSTOM}.local                ║"
echo "║     → http://${PI_IP}                                ║"
echo "║                                                      ║"
echo "║  🛠️  Commandes utiles :                              ║"
echo "║     Statut  : systemctl status $SERVICE_NAME         ║"
echo "║     Logs    : journalctl -u $SERVICE_NAME -f         ║"
echo "║     Restart : systemctl restart $SERVICE_NAME        ║"
echo "║                                                      ║"
echo "║  🔒 HTTPS (optionnel) :                              ║"
echo "║     sudo certbot --nginx -d votre-domaine.com        ║"
echo "║                                                      ║"
echo "║  📱 Sur vos appareils, ouvrez l'URL dans un          ║"
echo "║     navigateur pour créer votre compte admin.         ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "💡 Pour accéder via '${HOSTNAME_CUSTOM}.local' depuis"
echo "   un PC Windows, ajoutez dans C:\\Windows\\System32\\drivers\\etc\\hosts :"
echo "   ${PI_IP}  ${HOSTNAME_CUSTOM}.local"
echo ""
