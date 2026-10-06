#!/bin/bash
# gravity-install.sh
set -e

echo "--- 🚀 GravityNAS: Installation Auto-Pilot ---"

# 1. Détection Architecture
ARCH=$(uname -m)
case $ARCH in
    x86_64)  IMG="gravitynas/app:latest-amd64" ;;
    armv7l)  IMG="gravitynas/app:latest-armv7" ;;
    aarch64) IMG="gravitynas/app:latest-arm64" ;;
    *) echo "Architecture non supportée: $ARCH"; exit 1 ;;
esac

# 2. Vérification Docker
if ! [ -x "$(command -v docker)" ]; then
    echo "📦 Installation de Docker..."
    curl -sSL https://get.docker.com | sh
    sudo usermod -aG docker $USER
fi

# 3. Récupération de l'image
echo "📥 Récupération de l'image $IMG..."
# Note: On suppose ici que l'utilisateur a poussé son image sur le hub
# En attendant, le script peut aussi build localement si besoin
if ! docker pull "$IMG"; then
    echo "Image distante non trouvée, passage au build local..."
    docker build -f deployment/Dockerfile -t gravitynas .
else
    docker tag "$IMG" gravitynas:latest
fi

# 4. Configuration Systemd
echo "⚙️ Configuration du service système..."
cat <<EOF | sudo tee /etc/systemd/system/gravitynas.service
[Unit]
Description=GravityNAS Service
After=docker.service
Requires=docker.service

[Service]
Restart=always
WorkingDirectory=$(pwd)
ExecStartPre=-/usr/bin/docker stop gravitynas
ExecStartPre=-/usr/bin/docker rm gravitynas
ExecStart=/usr/bin/docker run --name gravitynas -p 8000:8000 -v $(pwd)/nas_storage:/app/nas_storage -v $(pwd)/data:/app/data -v $(pwd)/backups:/app/backups gravitynas:latest
ExecStop=/usr/bin/docker stop gravitynas

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable gravitynas
sudo systemctl start gravitynas

echo "✅ GravityNAS est opérationnel sur le port 8000 !"
echo "Accédez à l'interface via http://$(hostname -I | awk '{print $1}'):8000"
