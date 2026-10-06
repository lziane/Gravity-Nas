# 🚀 GravityNAS - Le Cloud Privé Haute Performance

**GravityNAS** est une solution de Network Attached Storage (NAS) moderne, légère et ultra-sécurisée, conçue spécifiquement pour transformer votre Raspberry Pi ou votre serveur personnel en un coffre-fort numérique intelligent.

## 🌟 Points Forts
*   **Sécurité intégrée** : Les mots de passe et sessions utilisent `scrypt`, et les chemins de fichiers sont contrôlés par notre couche `SecureFileSystem`.
*   **Recherche Intelligente (OCR)** : Grâce à l'indexation Tesseract intégrée, recherchez du texte *à l'intérieur* de vos images et PDFs.
*   **Légèreté & Vitesse** : Écrit en Python/FastAPI avec une base de données SQLite optimisée (mode WAL), GravityNAS reste fluide même sur du matériel modeste.
*   **Accès Distant Natif** : Tunneling sécurisé intégré pour accéder à vos fichiers partout dans le monde.

## Prérequis
*   Python 3.11 ou plus récent
*   256MB de RAM minimum (512MB recommandé pour l'OCR)
*   Architecture : x86_64, ARMv7 ou ARM64 (Raspberry Pi 3/4/5)

## Lancement depuis le terminal

Depuis le dossier du projet, lancez :

```bash
sudo apt install python3-venv python3-pip
./run_nas.sh
```

Le script crée `.venv`, installe `requirements.txt`, puis démarre le serveur sur
`http://127.0.0.1:8000`. Le port peut être changé avec `NAS_PORT=8080 ./run_nas.sh`.
Pour réinitialiser un mot de passe : `./run_nas.sh --reset nom_utilisateur`.

## ⚡ Installation Rapide (One-Click)
Lancez GravityNAS en une seule commande (Linux/macOS) :
```bash
curl -sSL https://gravitynas.io/install.sh | bash
```

## 📂 Structure du projet
*   `app/` : Logique métier (services, sécurité).
*   `routes/` : API et navigation.
*   `deployment/` : Scripts pour Windows, Mac et Docker.
*   `tests/` : Validation de la fiabilité.
*   `os/` : Première couche d'intégration pour la future distribution Linux GravityNAS.

## Vers GravityNAS OS

Le projet contient désormais un socle Debian appliance dans `os/` : service
systemd, répertoires persistants, environnement de secrets et bootstrap de
premier démarrage. Cette couche permet de préparer le produit sans empêcher
l'exécution actuelle avec `./run_nas.sh`.

Pour construire une image Raspberry Pi OS Lite 64 bits dédiée au Raspberry Pi
4, consulter [os/README.md](os/README.md). L'image est destinée à être flashée
sur une microSD avec Raspberry Pi Imager ; elle n'est pas une ISO PC. Le disque
USB séparé est recommandé pour les données du NAS.

## Documentation professionnelle

La documentation est organisée par usage :

- [Guide d'exploitation](docs/OPERATIONS.md) : installation, configuration, santé, logs, systemd, sauvegardes et dépannage.
- [Architecture](docs/ARCHITECTURE.md) : cycle de vie, services, responsabilités et règles d'extension.
- [Référence API](docs/API_DOCS.md) : routes HTTP et contrats de réponse.
- [Whitepaper sécurité](docs/SECURITY_WHITEPAPER.md) : authentification, isolation des chemins et protection des données.

## Démarrage recommandé

```bash
sudo apt install python3 python3-venv python3-pip
./run_nas.sh
curl -fsS http://127.0.0.1:8000/health
```

Le mode distant est opt-in. `run_nas.sh` conserve `GRAVITY_ALLOW_REMOTE=0` par
défaut ; l'activation exige une configuration explicite du tunnel et un jeton
valide. Les chemins de stockage et de données peuvent être déplacés avec
`GRAVITY_STORAGE_PATH` et `GRAVITY_DATA_PATH`.

## Vérification avant livraison

```bash
.venv/bin/python -m pytest -q tests/test_reliability.py
.venv/bin/python -m compileall -q main.py app routes
```

Les fonctions matérielles, mDNS, tunnel distant et OCR sont optionnelles selon
l'hôte. Leur absence ne doit pas empêcher le mode local de démarrer ; consultez
le guide d'exploitation pour les prérequis associés.
