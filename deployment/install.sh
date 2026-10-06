#!/bin/bash
# ╔══════════════════════════════════════════════════════════╗
# ║    GravityNAS — L'Installeur Invincible (V2 Versatile)   ║
# ║    Auto-détection, WSDD Forcé, Zéro Bug                  ║
# ╚══════════════════════════════════════════════════════════╝

set -e

# --- Détection de l'utilisateur réel ---
# Si lancé via sudo, SUDO_USER contient le nom de celui qui a lancé la commande
REAL_USER=${SUDO_USER:-$(id -un)}
NAS_DIR="/opt/gravitynas"
SERVICE_NAME="gravitynas"
HOSTNAME_CUSTOM="gravitynas"

# --- Couleurs ---
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║       GravityNAS — Installation Invincible       ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════╝${NC}"
echo -e "Utilisateur détecté : ${GREEN}$REAL_USER${NC}"

if [ "$(id -u)" -ne 0 ]; then
    echo -e "${RED}❌ Erreur : Ce script doit être lancé avec sudo.${NC}"
    exit 1
fi

# 1. Mise à jour système
echo -e "\n${YELLOW}[1/10] Rafraîchissement des dépôts...${NC}"
apt-get update -qq

# 2. Installation des dépendances de base
echo -e "${YELLOW}[2/10] Installation des composants système...${NC}"
apt-get install -y -qq \
    python3-full python3-pip python3-venv \
    samba samba-common-bin avahi-daemon \
    nginx rsync sqlite3 curl git \
    libffi-dev libssl-dev

# 3. WSDD : Par tous les moyens (Windows Discovery)
echo -e "${YELLOW}[3/10] Configuration de WSDD (Windows Network Tab)...${NC}"
if apt-get install -y -qq wsdd 2>/dev/null; then
    # Modifier la configuration système de wsdd si installé par apt
    if [ -f /etc/default/wsdd ]; then
        sed -i 's/WSDD_PARAMS=.*/WSDD_PARAMS="-n GravityNAS"/' /etc/default/wsdd
    fi
    echo -e "${GREEN}✅ wsdd installé via les dépôts.${NC}"
else
    echo -e "${YELLOW}⚠️  wsdd absent des dépôts. Installation manuelle via GitHub...${NC}"
    curl -sL https://raw.githubusercontent.com/christgau/wsdd/master/src/wsdd.py -o /usr/local/bin/wsdd
    chmod +x /usr/local/bin/wsdd
    
    # Création du service systemd manuel pour wsdd
    cat > /etc/systemd/system/wsdd.service << EOF
[Unit]
Description=Web Services Dynamic Discovery host daemon
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /usr/local/bin/wsdd -n GravityNAS
Restart=always

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    echo -e "${GREEN}✅ wsdd installé manuellement.${NC}"
fi

# 4. Réseau & Hostname
echo -e "${YELLOW}[4/10] Configuration réseau (${HOSTNAME_CUSTOM})...${NC}"
hostnamectl set-hostname "$HOSTNAME_CUSTOM"
# Correction du fichier hosts pour éviter les erreurs sudo
sed -i "/127.0.1.1/d" /etc/hosts
echo "127.0.1.1       $HOSTNAME_CUSTOM" >> /etc/hosts
echo "127.0.0.1       $HOSTNAME_CUSTOM" >> /etc/hosts

systemctl enable avahi-daemon wsdd
systemctl restart avahi-daemon wsdd

# 5. Déploiement propre
echo -e "${YELLOW}[5/10] Déploiement des fichiers...${NC}"
mkdir -p "$NAS_DIR"
# Création du groupe dédié pour les utilisateurs du NAS
groupadd -f gravitynas_users

rsync -a --delete \
    --exclude='nas_storage/' \
    --exclude='*.db*' \
    --exclude='venv/' \
    --exclude='.git/' \
    --exclude='__pycache__/' \
    "$(dirname "$0")/" "$NAS_DIR/"

mkdir -p "$NAS_DIR/nas_storage"
chown -R "$REAL_USER:gravitynas_users" "$NAS_DIR"
chmod -R 775 "$NAS_DIR"

# 6. Environnement Python
echo -e "${YELLOW}[6/10] Préparation de l'environnement virtuel...${NC}"
sudo -u "$REAL_USER" python3 -m venv "$NAS_DIR/venv"
sudo -u "$REAL_USER" "$NAS_DIR/venv/bin/pip" install --upgrade pip -q
sudo -u "$REAL_USER" "$NAS_DIR/venv/bin/pip" install -r "$NAS_DIR/requirements.txt" -q

# 7. SAMBA (Partage Réseau)
echo -e "${YELLOW}[7/10] Configuration du partage Samba...${NC}"
cat > /etc/samba/smb.conf << EOF
[global]
   workgroup = WORKGROUP
   server string = GravityNAS
   netbios name = GravityNAS
   security = user
   map to guest = Never
   logging = file
   
   # MacOS Optimisations
   vfs objects = catia fruit streams_xattr
   fruit:metadata = stream
   fruit:model = MacSamba
   fruit:nfs_aces = no

[GravityStockage]
   comment = Stockage GravityNAS
   path = $NAS_DIR/nas_storage
   browseable = yes
   read only = no
   guest ok = no
   valid users = @gravitynas_users
   force group = gravitynas_users
   directory mask = 0775
   create mask = 0664
EOF
systemctl restart smbd nmbd


# 8. NGINX (Reverse Proxy) - Zéro doublon
echo -e "${YELLOW}[8/10] Configuration du serveur Web (Nginx)...${NC}"
cp "$NAS_DIR/config/nginx.conf" /etc/nginx/sites-available/gravitynas
sed -i "s|/opt/gravitynas|$NAS_DIR|g" /etc/nginx/sites-available/gravitynas
sed -i "s|nas.local|$HOSTNAME_CUSTOM.local|g" /etc/nginx/sites-available/gravitynas

ln -sf /etc/nginx/sites-available/gravitynas /etc/nginx/sites-enabled/gravitynas
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx

# 9. SERVICE SYSTEMD
echo -e "${YELLOW}[9/10] Activation du service auto-launch...${NC}"
cat > "/etc/systemd/system/$SERVICE_NAME.service" << EOF
[Unit]
Description=GravityNAS Server
After=network-online.target
Wants=network-online.target


[Service]
Type=simple
User=$REAL_USER
WorkingDirectory=$NAS_DIR
ExecStart=$NAS_DIR/venv/bin/python $NAS_DIR/main.py
Restart=always
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl start "$SERVICE_NAME"

# 10. Optimisations SD
echo -e "${YELLOW}[10/10] Optimisations de fin...${NC}"
touch /etc/sysctl.conf
if ! grep -q "vm.swappiness=10" /etc/sysctl.conf; then
    echo "vm.swappiness=10" >> /etc/sysctl.conf
    sysctl -p >/dev/null 2>&1
fi

echo -e "\n${GREEN}✅ GRAVITYNAS EST PRÊT !${NC}"
echo -e "Accès : http://$HOSTNAME_CUSTOM.local"

echo -e "\n${BLUE}🔄 Redémarrage automatique dans 5 secondes...${NC}"
sleep 5
reboot

