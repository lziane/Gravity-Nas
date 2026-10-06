import os
import hashlib
import shutil
import tempfile
import zipfile
import logging
from datetime import datetime

logger = logging.getLogger("GravityNAS.BackupService")

class BackupService:
    def __init__(self, data_dir: str, storage_dir: str, backup_root: str):
        self.data_dir = data_dir
        self.storage_dir = storage_dir
        self.backup_root = backup_root
        os.makedirs(self.backup_root, exist_ok=True)

    def create_backup(self, include_storage: bool = False) -> str:
        """Crée une archive de sauvegarde datée."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"gravity_backup_{timestamp}.zip"
        backup_path = os.path.join(self.backup_root, backup_filename)

        try:
            with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # 1. Sauvegarde transactionnelle et cohérente de la DB SQLite
                import sqlite3
                import tempfile
                
                db_filename = "users_auth.db"
                db_path = os.path.join(self.data_dir, db_filename)
                
                if os.path.exists(db_path):
                    # Créer une sauvegarde en ligne cohérente dans un fichier temporaire
                    temp_db_fd, temp_db_path = tempfile.mkstemp(suffix=".db")
                    os.close(temp_db_fd)
                    try:
                        src_conn = sqlite3.connect(db_path)
                        dest_conn = sqlite3.connect(temp_db_path)
                        with dest_conn:
                            src_conn.backup(dest_conn)
                        dest_conn.close()
                        src_conn.close()
                        
                        zipf.write(temp_db_path, os.path.join("data", db_filename))
                    finally:
                        if os.path.exists(temp_db_path):
                            os.remove(temp_db_path)
                
                # Écrire un fichier README de sécurité pour expliquer l'isolation de la clé
                readme_content = (
                    "ATTENTION - GRAVITYNAS SECURITY README:\n"
                    "Par mesure de securite, la cle de chiffrement (.nas_encryption.key) est EXCLUE de cette sauvegarde.\n"
                    "Veuillez sauvegarder manuellement le fichier .nas_encryption.key situe dans le repertoire data/\n"
                    "de votre serveur. Sans cette cle, les emails et metadonnees chiffres ne pourront pas etre recuperes.\n"
                )
                zipf.writestr("data/README_BACKUP.txt", readme_content)

                # 2. Sauvegarde optionnelle du stockage utilisateur
                if include_storage:
                    for root, dirs, files in os.walk(self.storage_dir):
                        dirs[:] = [name for name in dirs if not os.path.islink(os.path.join(root, name))]
                        for file in files:
                            if ".Corbeille" in root: continue # Ignorer la corbeille
                            file_path = os.path.join(root, file)
                            if os.path.islink(file_path): continue
                            arcname = os.path.join("storage", os.path.relpath(file_path, self.storage_dir))
                            zipf.write(file_path, arcname)

                manifest = []
                for info in zipf.infolist():
                    if info.filename != "data/MANIFEST.sha256" and not info.is_dir():
                        with zipf.open(info) as handle:
                            digest = hashlib.sha256(handle.read()).hexdigest()
                        manifest.append(f"{digest}  {info.filename}")
                zipf.writestr("data/MANIFEST.sha256", "\n".join(manifest) + "\n")

            logger.info(f"Sauvegarde réussie : {backup_path}")
            return backup_path
        except Exception as e:
            logger.error(f"Échec de la sauvegarde : {e}")
            if os.path.exists(backup_path): os.remove(backup_path)
            raise e

    def restore_backup(self, filename: str, restore_storage: bool = False) -> None:
        safe_name = os.path.basename(filename)
        backup_path = os.path.join(self.backup_root, safe_name)
        if safe_name != filename or not filename.endswith(".zip") or not os.path.isfile(backup_path):
            raise ValueError("Sauvegarde invalide")

        with tempfile.TemporaryDirectory(prefix="gravitynas-restore-") as staging:
            with zipfile.ZipFile(backup_path) as archive:
                members = archive.infolist()
                for member in members:
                    target = os.path.realpath(os.path.join(staging, member.filename))
                    if os.path.commonpath((staging, target)) != staging or member.is_dir():
                        continue
                    if member.filename.startswith("storage/") and not restore_storage:
                        continue
                    archive.extract(member, staging)

                manifest = os.path.join(staging, "data", "MANIFEST.sha256")
                if os.path.isfile(manifest):
                    with open(manifest, encoding="utf-8") as manifest_handle:
                        for line in manifest_handle:
                            digest, relative = line.rstrip("\n").split("  ", 1)
                            extracted = os.path.join(staging, relative)
                            if not os.path.isfile(extracted):
                                raise ValueError(f"Fichier manquant dans la sauvegarde: {relative}")
                            with open(extracted, "rb") as extracted_handle:
                                actual = hashlib.sha256(extracted_handle.read()).hexdigest()
                            if actual != digest:
                                raise ValueError(f"Sauvegarde corrompue: {relative}")

            database = os.path.join(staging, "data", "users_auth.db")
            if os.path.isfile(database):
                os.makedirs(self.data_dir, exist_ok=True)
                shutil.copy2(database, os.path.join(self.data_dir, "users_auth.db.restore"))
            if restore_storage:
                restored_storage = os.path.join(staging, "storage")
                if os.path.isdir(restored_storage):
                    os.makedirs(self.storage_dir, exist_ok=True)
                    for root, _, files in os.walk(restored_storage):
                        for name in files:
                            source = os.path.join(root, name)
                            relative = os.path.relpath(source, restored_storage)
                            destination = os.path.join(self.storage_dir, relative)
                            os.makedirs(os.path.dirname(destination), exist_ok=True)
                            shutil.copy2(source, destination)

    def list_backups(self):
        """Liste les fichiers de sauvegarde disponibles."""
        backups = []
        for f in os.listdir(self.backup_root):
            if f.endswith(".zip"):
                path = os.path.join(self.backup_root, f)
                backups.append({
                    "name": f,
                    "size": f"{os.path.getsize(path) / (1024*1024):.2f} MB",
                    "date": datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
                })
        return sorted(backups, key=lambda x: x['date'], reverse=True)

    def delete_backup(self, filename: str):
        safe_name = os.path.basename(filename)
        path = os.path.join(self.backup_root, safe_name)
        if safe_name == filename and filename.endswith(".zip") and os.path.isfile(path):
            os.remove(path)
