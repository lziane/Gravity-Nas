# Guide d'exploitation GravityNAS

Ce document décrit le fonctionnement quotidien du service, les paramètres de lancement, les contrôles de santé et les procédures de dépannage.

## 1. Préparer l'hôte

### Configuration minimale

- Python 3.11 ou plus récent.
- 256 Mo de RAM minimum ; 512 Mo ou plus si l'OCR est activé.
- Un volume de stockage accessible en écriture.
- `python3-venv` et `python3-pip` sur Debian/Ubuntu.
- Tesseract installé si la recherche dans les images est nécessaire.

Le service est compatible avec x86_64, ARMv7 et ARM64. Sur Raspberry Pi, installer aussi les paquets matériels requis par `gpiozero` selon le modèle utilisé.

### Installation reproductible

```bash
sudo apt install python3 python3-venv python3-pip
./run_nas.sh
```

`run_nas.sh` crée l'environnement `.venv`, installe les dépendances si `requirements.txt` a changé, puis démarre le serveur. Les dépendances ne sont donc pas réinstallées à chaque démarrage.

## 2. Configuration

Les variables principales sont :

| Variable | Défaut | Rôle |
| --- | --- | --- |
| `NAS_PORT` | `8000` | Port HTTP local. |
| `GRAVITY_STORAGE_PATH` | Détection automatique | Racine des fichiers utilisateurs. |
| `GRAVITY_DATA_PATH` | `data/` | Base SQLite et données applicatives. |
| `GRAVITY_ALLOW_REMOTE` | `0` | Autorise le tunnel distant au niveau du processus. |
| `GRAVITY_TRUSTED_PROXIES` | vide | Liste d'adresses IP de reverse proxies autorisés à transmettre `X-Real-IP`, séparées par des virgules. |

L'accès distant est volontairement désactivé par défaut. Pour l'activer, il faut à la fois définir `GRAVITY_ALLOW_REMOTE=1`, activer `remote_enabled` dans les réglages et fournir un jeton de tunnel valide.

`X-Real-IP` est ignoré sauf si l'adresse du pair TCP figure dans `GRAVITY_TRUSTED_PROXIES`. Ne renseignez cette variable qu'avec les adresses réelles de vos reverse proxies ; un accès direct à Uvicorn ne doit pas être exposé publiquement.

Exemple :

```bash
GRAVITY_STORAGE_PATH=/srv/gravitynas NAS_PORT=8080 ./run_nas.sh
```

Ne placez jamais de jeton ou de mot de passe dans un fichier versionné. Utilisez l'environnement du service systemd ou un gestionnaire de secrets.

## 3. Démarrage et arrêt

Démarrage local :

```bash
./run_nas.sh
```

Réinitialisation contrôlée d'un mot de passe :

```bash
./run_nas.sh --reset nom_utilisateur
```

Le processus lance FastAPI/Uvicorn, la file de tâches, la découverte mDNS et les deux tâches périodiques de maintenance. À l'arrêt, les tâches périodiques sont annulées, le mDNS et le tunnel sont arrêtés, puis les workers sont annulés et libérés.

Contrôle de santé :

```bash
curl -fsS http://127.0.0.1:8000/health
```

Réponse attendue :

```json
{"status":"ok","service":"gravitynas"}
```

## 4. Stockage et indexation

- `GRAVITY_STORAGE_PATH` est la racine physique des utilisateurs.
- SQLite contient les comptes, sessions, métadonnées et index de recherche.
- Les fichiers supprimés passent par la corbeille avant nettoyage.
- L'indexation OCR est exécutée dans `TaskService` pour ne pas bloquer les requêtes HTTP.
- L'OCR est limité aux images de 10 Mo et aux PDF de 30 Mo, avec un maximum de 100 pages par PDF.

Une recherche vide après un import peut être normale : l'indexation est asynchrone. Vérifiez les logs avant de relancer manuellement une opération.

## 5. Logs et diagnostic

Le serveur écrit des logs structurés sur la sortie standard. Pour isoler un problème :

```bash
./run_nas.sh 2>&1 | tee gravitynas.log
```

Vérifications rapides :

1. `curl /health` répond-il ?
2. Le chemin de `GRAVITY_STORAGE_PATH` existe-t-il et est-il inscriptible ?
3. Le fichier `data/users_auth.db` est-il accessible par le compte du service ?
4. Tesseract est-il installé si les logs signalent une erreur OCR ?
5. Le port choisi est-il déjà occupé ?

## 6. Déploiement systemd

Le fichier `os/systemd/gravitynas.service` fournit la base du déploiement appliance. Avant activation, adapter l'utilisateur, les chemins persistants et les secrets à l'hôte cible.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now gravitynas
sudo systemctl status gravitynas
journalctl -u gravitynas -f
```

Le service doit utiliser un utilisateur dédié sans privilèges administrateur. Les répertoires `data/`, `backups/` et le stockage doivent appartenir à cet utilisateur.

## 7. Sauvegardes et restauration

Les sauvegardes de configuration et de fichiers doivent être stockées sur un support distinct. Une sauvegarde n'est considérée valide qu'après restauration de test.

Avant toute mise à jour :

```bash
cp -a data data.pre-update
cp -a backups backups.pre-update
```

La restauration doit préserver les permissions et ne doit pas écraser le stockage actif sans validation de l'espace disponible.

## 8. Limites connues

- La détection automatique du plus grand volume dépend des montages visibles par le processus.
- L'OCR nécessite les dépendances Python et le binaire Tesseract ; sans lui, les fichiers restent accessibles mais ne sont pas indexés par image.
- Les avertissements `DeprecationWarning` provenant de FastAPI, Starlette ou pytest-asyncio peuvent dépendre de la version Python installée ; ils ne signalent pas nécessairement un échec du service.
- Une seule instance Uvicorn doit écouter un port donné.

Pour la surface HTTP, consulter [API_DOCS.md](API_DOCS.md). Pour le modèle de menace et les contrôles de sécurité, consulter [SECURITY_WHITEPAPER.md](SECURITY_WHITEPAPER.md).

### Disque USB de données

Pour garder les fichiers volumineux hors de la microSD, connectez un disque
USB déjà formaté en ext4 et lancez `sudo gravitynas-storage /dev/sda1` avec le
bon périphérique. L’assistant monte par UUID sous `/srv/gravitynas-storage`,
met à jour Samba et bloque le démarrage du NAS si le volume configuré manque.
Il ne formate ni n’efface le disque. La base SQLite et l’OS restent sur la
microSD.

## 9. Image appliance Raspberry Pi 4

Le constructeur `os/scripts/build-pi-image.sh` utilise `pi-gen` pour produire
une image Raspberry Pi OS Lite Trixie ARM64, sans environnement graphique.
Il doit être lancé en root sur un hôte Linux avec accès réseau. L'image `.img.xz`
est ensuite flashée sur une microSD avec Raspberry Pi Imager ; le script ne
choisit ni n'écrit lui-même un périphérique bloc.

Générez une clé RSA de publication sur une machine de confiance et conservez la
clé privée hors du NAS :

```bash
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out update-private.pem
chmod 0600 update-private.pem
openssl pkey -in update-private.pem -pubout -out update.pub
GRAVITYNAS_UPDATE_PUBLIC_KEY="$PWD/update.pub" sudo -E os/scripts/build-pi-image.sh 1.0.0
```

Le mot de passe SSH `nasadmin` est aléatoire par image et enregistré dans
`build/gravitynas-image/credentials.txt`. L’image active SSH pour permettre
l’administration, mais aucun mot de passe commun n’est intégré au projet.
Ethernet avec DHCP est le chemin de premier démarrage documenté ; l’accès web
local est `http://gravitynas.local`. L’OCR est désactivé dans l’image minimale ;
`GRAVITYNAS_IMAGE_OCR=1` ajoute Tesseract.

Un Pi déjà équipé de Raspberry Pi OS Lite 64 bits peut recevoir le même runtime
avec `GRAVITYNAS_UPDATE_PUBLIC_KEY="$PWD/update.pub" sudo -E os/scripts/install-pi4.sh`.
Ce script ne formate pas de disque et refuse de remplacer une installation
versionnée existante.

## 10. Releases et mise à jour

Construisez une archive signée depuis le poste de publication :

```bash
GRAVITYNAS_SIGNING_KEY="$PWD/update-private.pem" os/scripts/package-release.sh 1.0.1
```

Copiez l’archive `gravitynas-1.0.1.tar.gz` et son fichier `.sig` sur le NAS :

```bash
sudo gravitynas-update /chemin/gravitynas-1.0.1.tar.gz
```

L’updater vérifie la signature avec `/etc/gravitynas/update.pub`, prépare une
release et son environnement Python sans toucher au stockage utilisateur,
sauvegarde SQLite, bascule le lien `current`, puis vérifie `/health`. En cas
d’échec, il rétablit le code et la base précédents. Les releases installées
restent dans `/opt/gravitynas/releases/` ; aucun nettoyage automatique ne
supprime les versions de retour arrière.

Pour héberger les releases, définissez `GRAVITYNAS_UPDATE_URL` dans
`/etc/gravitynas/gravitynas.env` vers une URL HTTPS directe de l’archive. Le
fichier de signature doit être accessible à `${URL}.sig`. Le fichier
`.sha256` est utile pour les transferts manuels, mais l’authenticité repose sur
la signature et la clé publique installée lors de la fabrication de l’image.
