# GravityNAS - Script de Mise a Jour Rapide (Version PC Windows)

$PI_USER = "rayan"
$PI_IP   = "192.168.2.83"
$PI_DIR  = "~/GravityNAS/"

Write-Host "`n[1/2] Envoi du code (Python, HTML, JS, CSS)..." -ForegroundColor Cyan

# Liste des fichiers/dossiers a envoyer
$TARGETS = @("static", "templates", "*.py", "requirements.txt", "setup_samba.sh")

foreach ($item in $TARGETS) {
    Write-Host "  -> Transfert de $item..."
    scp -r $item "${PI_USER}@${PI_IP}:${PI_DIR}"
}

Write-Host "`n[2/2] Redemarrage du serveur GravityNAS sur le Pi..." -ForegroundColor Cyan
ssh "${PI_USER}@${PI_IP}" "sudo systemctl restart gravitynas"

Write-Host "`nMISSION REUSSIE : Ton NAS est a jour !`n" -ForegroundColor Green
