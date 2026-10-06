# ╔══════════════════════════════════════════════════════════╗
# ║      GravityNAS — Ordonnanceur d'Installation à Distance ║
# ║      Transfert et Configuration Automatique (PC -> Pi)   ║
# ╚══════════════════════════════════════════════════════════╝

$ErrorActionPreference = "Stop"

# --- Configuration Visuelle ---
$G = "[GravityNAS-Remote]"
$Host.UI.RawUI.WindowTitle = "GravityNAS - Installation à distance"

Clear-Host
Write-Host "`n  $G Initialisation de l'ordonnanceur..." -ForegroundColor Cyan

# 1. Vérification des outils locaux
if (!(Get-Command ssh -ErrorAction SilentlyContinue)) {
    Write-Host "  ❌ Erreur : 'ssh' n'est pas installé sur votre PC. Installez OpenSSH Client (Windows Settings)." -ForegroundColor Red
    exit
}

# 2. Collecte des informations cibles
Write-Host "`n  --- Paramètres de connexion ---" -ForegroundColor Yellow

if (!($Global:NAS_REMOTE_IP)) {
    $Global:NAS_REMOTE_IP = Read-Host "  > Entrez l'adresse IP du Raspberry Pi (ex: 192.168.1.50)"
}
$PI_IP = $Global:NAS_REMOTE_IP

if (!($Global:NAS_REMOTE_USER)) {
    $DefaultUser = "pi"
    if ($env:USERNAME -ne "Administrator") { $DefaultUser = $env:USERNAME }
    $InUser = Read-Host "  > Utilisateur SSH [Par défaut: $DefaultUser]"
    if ([string]::IsNullOrWhiteSpace($InUser)) { $Global:NAS_REMOTE_USER = $DefaultUser } else { $Global:NAS_REMOTE_USER = $InUser }
}
$PI_USER = $Global:NAS_REMOTE_USER

# 3. Choix du mode : Installation ou Mise à jour
Write-Host "`n  [?] Type d'opération souhaité :" -ForegroundColor Yellow
Write-Host "  [1] Installation Complète (Nouveau Pi / Réinstallation système)"
Write-Host "  [2] Mise à jour Rapide (Code, UI, Fixes - Zéro perte de données)"
$ModeChoice = Read-Host "  > Choix (Défaut: 2)"
if ([string]::IsNullOrWhiteSpace($ModeChoice)) { $ModeChoice = "2" }

$REMOTE_SCRIPT = "install.sh"
if ($ModeChoice -eq "2") {
    $REMOTE_SCRIPT = "scripts/update_pi.sh"
    Write-Host "`n  $G Mode Mise à jour Rapide sélectionné." -ForegroundColor Green
} else {
    Write-Host "`n  $G Mode Installation Complète sélectionné." -ForegroundColor Yellow
}

# 3. Préparation de l'environnement (Non-destructif)
Write-Host "`n  $G Préparation du Pi..." -ForegroundColor Cyan
ssh "${PI_USER}@${PI_IP}" "mkdir -p ~/gravitynas_setup"




# 4. Optionnel : Configuration de la clé SSH (Zéro mot de passe)
$PubKeyPath = "$HOME\.ssh\id_rsa.pub"
if (!(Test-Path $PubKeyPath)) {
    $CreateKey = Read-Host "`n  [?] Aucune clé SSH détectée. Voulez-vous en générer une pour ne plus avoir à taper votre mot de passe ? (O/n)"
    if ($CreateKey -ne "n") {
        Write-Host "  -> Génération de la clé..." -ForegroundColor Gray
        ssh-keygen -t rsa -b 4096 -f "$HOME\.ssh\id_rsa" -N '""'
    }
}

if (Test-Path $PubKeyPath) {
    if (!($KeyAlreadyPushed)) {
        $SetupKey = Read-Host "`n  [?] Voulez-vous installer votre clé sur le Pi pour libérer l'installation des mots de passe ? (O/n)"
        if ($SetupKey -ne "n") {
            Write-Host "  -> Installation de la clé sur le Pi..." -ForegroundColor Gray
            $PubKey = Get-Content $PubKeyPath
            ssh "${PI_USER}@${PI_IP}" "mkdir -p ~/.ssh && echo '$PubKey' >> ~/.ssh/authorized_keys && chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys"
            Write-Host "  ✅ Clé configurée !" -ForegroundColor Green
        }
    }
}

# 5. Transfert autonome du code (Envoi groupé)
Write-Host "`n  $G Transfert des fichiers source..." -ForegroundColor Cyan
scp -r app static templates config scripts main.py requirements.txt install.sh "${PI_USER}@${PI_IP}:~/gravitynas_setup/"

# 6. Lancement de l'installation ou mise à jour à distance
Write-Host "`n  $G DÉMARRAGE DE L'OPÉRATION SUR LE PI ($REMOTE_SCRIPT)..." -ForegroundColor Green
Write-Host "  (Appuyez sur Entrée si le terminal semble figé après le mot de passe)`n" -ForegroundColor Gray

# Exécution directe pour une meilleure interactivité
ssh -t "${PI_USER}@${PI_IP}" "cd ~/gravitynas_setup && chmod +x install.sh scripts/*.sh && sudo ./$REMOTE_SCRIPT $PI_USER"


if ($LASTEXITCODE -ne 0) {
    Write-Host "`n  ❌ L'installation a échoué (Code : $LASTEXITCODE)." -ForegroundColor Red
    exit
}

# 7. Finalisation
Write-Host "`n  $G Installation terminée avec succès !" -ForegroundColor Green
Write-Host "  Nettoyage..." -ForegroundColor Gray
ssh "${PI_USER}@${PI_IP}" "rm -rf ~/gravitynas_setup"


Write-Host "`n  --- MISSION RÉUSSIE ---" -ForegroundColor Cyan
$NAS_URL = "http://${PI_IP}"
Write-Host "  Votre NAS est prêt sur $NAS_URL" -ForegroundColor Green

$OpenNow = Read-Host "  Souhaitez-vous ouvrir l'interface de création de compte ? (O/n)"
if ($OpenNow -ne "n") {
    Start-Process $NAS_URL
}

Write-Host "`n  Appuyez sur Entrée pour quitter..."
Read-Host
