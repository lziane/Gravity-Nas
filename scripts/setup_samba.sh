#!/bin/bash
# ╔══════════════════════════════════════════════════════════╗
# ║        GravityNAS — Installation Samba (Windows/Mac)     ║
# ╚══════════════════════════════════════════════════════════╝

set -e

if [ "$(id -u)" -ne 0 ]; then
    echo "❌ Ce script doit être lancé avec sudo."
    exit 1
fi

NAS_USER="${GRAVITYNAS_USER:-pi}"
groupadd -f gravitynas_users
if id -u "$NAS_USER" >/dev/null 2>&1; then
    usermod -aG gravitynas_users "$NAS_USER"
fi

echo "📦 Installation de Samba et des outils de découverte réseau..."
apt-get update -qq
apt-get install -y samba samba-common-bin avahi-daemon wsdd -qq || echo "⚠️ wsdd non trouvé"

if [ ! -f /etc/samba/smb.conf.bak ]; then
    cp /etc/samba/smb.conf /etc/samba/smb.conf.bak
fi

echo "⚙️ Configuration avancée de smb.conf..."
cat > /etc/samba/smb.conf << EOF
[global]
   workgroup = WORKGROUP
   server string = GravityNAS
   netbios name = GravityNAS
   security = user
    map to guest = Never
    server min protocol = SMB2
   dns proxy = no
   # Performance & MacOS Fixes
   min protocol = SMB2
   vfs objects = catia fruit streams_xattr
   fruit:metadata = stream
   fruit:model = MacSamba
   fruit:veto_appledouble = no
   fruit:wipe_intentionally_left_blank_rfork = yes 
   fruit:nfs_aces = no

[homes]
   comment = Espace Personnel GravityNAS
   browseable = no
   path = /opt/gravitynas/nas_storage/%S
   valid users = %S
   read only = no
    force group = gravitynas_users
    inherit acls = yes
    inherit permissions = yes
    create mask = 0660
    directory mask = 0770
EOF

echo "🔄 Redémarrage des services..."
systemctl restart smbd nmbd avahi-daemon
systemctl enable smbd nmbd

echo ""
echo "✅ Configuration Samba terminée."
echo "GravityNAS apparaitra bientôt dans l'onglet Réseau de Windows et macOS."
echo ""
