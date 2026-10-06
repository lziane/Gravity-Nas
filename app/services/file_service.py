import os
import shutil
import sqlite3
import threading
import logging
import hashlib
import hmac
import time
from datetime import datetime
from typing import List, Dict, Any, Optional
from app.core.secure_fs import SecureFileSystem
from app.encryption import AESCipherManager

try:
    from PIL import Image
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

logger = logging.getLogger("GravityNAS.FileService")

class FileService(SecureFileSystem):
    def __init__(self, base_storage_path: str, db_path: str):
        super().__init__(base_storage_path)
        self.db_path = db_path
        self._local = threading.local()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=20)
            conn.execute("PRAGMA journal_mode=WAL")
            # Extra resilience against power failure
            conn.execute("PRAGMA synchronous=EXTRA")
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return self._local.conn

    def get_user_storage(self, username: str) -> str:
        user_path = os.path.join(self.base_path, username)
        os.makedirs(user_path, exist_ok=True)
        return user_path

    def list_files(self, subpath: str, username: str) -> List[Dict]:
        if self.is_locked_path(subpath, username):
            return []
        user_storage = self.get_user_storage(username)
        target_dir = self.get_abs_path(subpath, user_storage)

        # Récupérer les métadonnées de la DB d'un coup pour optimiser
        conn = self._get_conn()
        meta_map = {}
        tags_map = {}
        vaults = []
        try:
            # On cherche les infos pour ce dossier
            rows = conn.execute('SELECT filepath, color, emoji, is_pinned FROM file_meta WHERE username = ?', (username,)).fetchall()
            for r in rows:
                meta_map[r['filepath']] = dict(r)
            
            # Récupérer tous les tags d'un coup
            tags_rows = conn.execute('SELECT filepath, tag FROM file_tags WHERE username = ?', (username,)).fetchall()
            for tr in tags_rows:
                if tr['filepath'] not in tags_map: tags_map[tr['filepath']] = []
                tags_map[tr['filepath']].append(tr['tag'])
            
            vaults = [r['filepath'] for r in conn.execute('SELECT filepath FROM file_vaults WHERE username = ? AND is_locked = 1', (username,)).fetchall()]
        except sqlite3.OperationalError:
            pass

        files_list = []
        if not os.path.exists(target_dir):
            return []

        try:
            with os.scandir(target_dir) as it:
                for entry in it:
                    if entry.name in [".nas_metadata.db", ".thumbnails"] or (not subpath and entry.name == ".Corbeille"):
                        continue
                    
                    stat = entry.stat(follow_symlinks=False)
                    size_bytes = self._entry_size(entry.path, entry.is_dir(follow_symlinks=False))
                    rel = os.path.relpath(entry.path, user_storage).replace("\\", "/")
                    
                    # Fusionner avec les métadonnées
                    meta = meta_map.get(rel, {})
                    
                    files_list.append({
                        "name": entry.name,
                        "size": self._fmt_size(size_bytes),
                        "size_bytes": size_bytes,
                        "modified": datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M'),
                        "modified_ts": stat.st_mtime,
                        "is_dir": entry.is_dir(),
                        "extension": os.path.splitext(entry.name)[1].lower(),
                        "relative_path": rel,
                        "color": meta.get("color"),
                        "emoji": meta.get("emoji"),
                        "is_pinned": bool(meta.get("is_pinned")),
                        "is_vault": rel in vaults,
                        "tags": tags_map.get(rel, [])
                    })
        except Exception as e:
            logger.error(f"Error listing files in {subpath}: {e}")
        
        files_list.sort(key=lambda x: (not x['is_dir'], x['name'].lower()))
        return files_list

    def _entry_size(self, path: str, is_dir: bool) -> int:
        if not is_dir:
            return os.path.getsize(path)
        total = 0
        for root, dirs, files in os.walk(path, followlinks=False):
            dirs[:] = [directory for directory in dirs if not os.path.islink(os.path.join(root, directory))]
            for filename in files:
                file_path = os.path.join(root, filename)
                try:
                    if not os.path.islink(file_path):
                        total += os.path.getsize(file_path)
                except OSError:
                    continue
        return total

    def delete_item(self, rel_path: str, username: str) -> bool:
        self.assert_path_unlocked(rel_path, username)
        user_storage = self.get_user_storage(username)
        target = self.get_abs_path(rel_path, user_storage)
        
        if not os.path.exists(target): return False

        # Trash logic
        if ".Corbeille" in os.path.normpath(rel_path).split(os.sep):
            self._force_delete(target)
            return True

        trash_dir = os.path.join(user_storage, ".Corbeille")
        os.makedirs(trash_dir, exist_ok=True)
        
        dest = os.path.join(trash_dir, os.path.basename(rel_path))
        if os.path.exists(dest):
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            name, ext = os.path.splitext(os.path.basename(rel_path))
            dest = os.path.join(trash_dir, f"{name}_{ts}{ext}")

        try:
            shutil.move(target, dest)
            return True
        except Exception as e:
            logger.error(f"Delete failed for {rel_path}: {e}")
            return False

    def rename_item(self, rel_path: str, new_name: str, username: str) -> str:
        self.assert_path_unlocked(rel_path, username)
        user_storage = self.get_user_storage(username)
        if not new_name or new_name in {".", ".."} or os.path.basename(new_name) != new_name:
            raise ValueError("Nom de fichier invalide")

        source = self.get_abs_path(rel_path, user_storage)
        if not os.path.lexists(source):
            raise FileNotFoundError("Fichier introuvable")
        destination = self.get_abs_path(
            os.path.join(os.path.dirname(rel_path), new_name), user_storage
        )
        if os.path.lexists(destination):
            raise FileExistsError("Un élément porte déjà ce nom")

        os.rename(source, destination)
        return os.path.relpath(destination, user_storage).replace("\\", "/")

    def move_item(self, rel_path: str, destination_dir: str, username: str) -> str:
        self.assert_path_unlocked(rel_path, username)
        self.assert_path_unlocked(destination_dir, username)
        user_storage = self.get_user_storage(username)
        source = self.get_abs_path(rel_path, user_storage)
        target_dir = self.get_abs_path(destination_dir, user_storage)
        if not os.path.lexists(source):
            raise FileNotFoundError("Fichier introuvable")
        if not os.path.isdir(target_dir):
            raise NotADirectoryError("Dossier de destination introuvable")
        if os.path.isdir(source) and self.is_safe(target_dir, source):
            raise ValueError("Un dossier ne peut pas être déplacé dans lui-même")

        destination = os.path.join(target_dir, os.path.basename(source))
        destination = self.get_abs_path(
            os.path.relpath(destination, user_storage), user_storage
        )
        if os.path.lexists(destination):
            raise FileExistsError("Un élément porte déjà ce nom dans la destination")

        os.rename(source, destination)
        return os.path.relpath(destination, user_storage).replace("\\", "/")

    def _force_delete(self, path: str):
        if os.path.isdir(path): shutil.rmtree(path)
        else: os.remove(path)

    def restore_item(self, rel_path: str, username: str) -> str:
        user_storage = self.get_user_storage(username)
        normalized = rel_path.replace("\\", "/").strip("/")
        if not normalized.startswith(".Corbeille/"):
            raise PermissionError("Seuls les éléments de la corbeille peuvent être restaurés")

        source = self.get_abs_path(normalized, user_storage)
        if not os.path.lexists(source):
            raise FileNotFoundError("Élément de corbeille introuvable")

        name = os.path.basename(source)
        destination = self.get_abs_path(name, user_storage)
        if os.path.lexists(destination):
            raise FileExistsError("Un élément porte déjà ce nom à la racine")
        os.rename(source, destination)
        return name

    def _fmt_size(self, size_bytes: int) -> str:
        if size_bytes == 0: return "0 B"
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size_bytes < 1024: return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} PB"

    # Vaults logic
    def is_locked_path(self, rel_path: str, username: str) -> bool:
        normalized = rel_path.replace("\\", "/").strip("/")
        if not normalized:
            return False
        try:
            rows = self._get_conn().execute(
                'SELECT filepath FROM file_vaults WHERE username = ? AND is_locked = 1',
                (username,)
            ).fetchall()
        except sqlite3.OperationalError:
            return False
        return any(normalized == row["filepath"].strip("/") or
                   normalized.startswith(row["filepath"].strip("/") + "/")
                   for row in rows)

    def assert_path_unlocked(self, rel_path: str, username: str) -> None:
        if self.is_locked_path(rel_path, username):
            raise PermissionError("Coffre-fort verrouillé")

    def create_vault(self, rel_path: str, password: str, username: str):
        self.assert_path_unlocked(rel_path, username)
        user_storage = self.get_user_storage(username)
        if not password or not os.path.isdir(self.get_abs_path(rel_path, user_storage)):
            raise ValueError("Le coffre-fort doit être un dossier existant")
        self._protect_vault_directory(self.get_abs_path(rel_path, user_storage))
        conn = self._get_conn()
        if conn.execute(
            'SELECT 1 FROM file_vaults WHERE filepath = ? AND username = ?',
            (rel_path, username)
        ).fetchone():
            raise ValueError("Ce dossier est déjà un coffre-fort")
        salt = os.urandom(16)
        pwd_hash = hashlib.scrypt(password.encode(), salt=salt, n=8192, r=8, p=1, dklen=32)
        conn.execute(
            'INSERT INTO file_vaults (filepath, username, salt, password_hash, is_locked) VALUES (?, ?, ?, ?, 1)',
            (rel_path, username, salt, pwd_hash)
        )
        conn.commit()
        try:
            self._encrypt_vault_files(rel_path, user_storage, password, salt)
        except Exception:
            conn.execute(
                'DELETE FROM file_vaults WHERE filepath = ? AND username = ?',
                (rel_path, username)
            )
            conn.commit()
            raise
        return True

    def is_vault(self, rel_path: str, username: str) -> bool:
        row = self._get_conn().execute('SELECT is_locked FROM file_vaults WHERE filepath = ? AND username = ?', 
                                        (rel_path, username)).fetchone()
        return row is not None

    def unlock_vault(self, rel_path: str, password: str, username: str) -> bool:
        row = self._get_conn().execute('SELECT salt, password_hash FROM file_vaults WHERE filepath = ? AND username = ?', 
                                        (rel_path, username)).fetchone()
        if not row: return False
        
        pwd_hash = hashlib.scrypt(password.encode(), salt=row['salt'], n=8192, r=8, p=1, dklen=32)
        if hmac.compare_digest(row['password_hash'], pwd_hash):
            self._decrypt_vault_files(rel_path, username, password, row['salt'])
            self._get_conn().execute('UPDATE file_vaults SET is_locked = 0 WHERE filepath = ? AND username = ?', (rel_path, username))
            self._get_conn().commit()
            return True
        return False

    def _vault_cipher(self, password: str, salt: bytes) -> AESCipherManager:
        return AESCipherManager(password + salt.hex())

    def _protect_vault_directory(self, vault_path: str) -> None:
        if os.name != "nt":
            os.chmod(vault_path, 0o700)

    def protect_vault_permissions(self) -> None:
        if os.name == "nt":
            return
        try:
            rows = self._get_conn().execute('SELECT filepath, username FROM file_vaults').fetchall()
        except sqlite3.OperationalError:
            return
        user_storage_cache = {}
        for row in rows:
            name = row["username"]
            user_storage_cache.setdefault(name, self.get_user_storage(name))
            path = self.get_abs_path(row["filepath"], user_storage_cache[name])
            if os.path.isdir(path):
                self._protect_vault_directory(path)

    def _vault_files(self, rel_path: str, user_storage: str):
        vault_path = self.get_abs_path(rel_path, user_storage)
        for root, dirs, files in os.walk(vault_path, followlinks=False):
            dirs[:] = [name for name in dirs if not os.path.islink(os.path.join(root, name))]
            for name in files:
                path = os.path.join(root, name)
                if not os.path.islink(path):
                    yield path

    def _encrypt_vault_files(self, rel_path: str, user_storage: str, password: str, salt: bytes):
        cipher = self._vault_cipher(password, salt)
        encrypted = []
        try:
            for path in self._vault_files(rel_path, user_storage):
                cipher.encrypt_file(path)
                encrypted.append(path)
        except Exception:
            for path in reversed(encrypted):
                try:
                    cipher.decrypt_file(path)
                except Exception:
                    logger.critical("Vault encryption rollback failed for %s", path)
            raise

    def _decrypt_vault_files(self, rel_path: str, username: str, password: str, salt: bytes):
        user_storage = self.get_user_storage(username)
        cipher = self._vault_cipher(password, salt)
        decrypted = []
        try:
            for path in self._vault_files(rel_path, user_storage):
                cipher.decrypt_file(path)
                decrypted.append(path)
        except Exception:
            for path in reversed(decrypted):
                try:
                    cipher.encrypt_file(path)
                except Exception:
                    logger.critical("Vault decryption rollback failed for %s", path)
            raise ValueError("Contenu du coffre-fort illisible")

    def lock_vault(self, rel_path: str, password: str, username: str) -> bool:
        row = self._get_conn().execute(
            'SELECT salt, password_hash, is_locked FROM file_vaults WHERE filepath = ? AND username = ?',
            (rel_path, username)
        ).fetchone()
        if not row or row['is_locked']:
            return False
        pwd_hash = hashlib.scrypt(password.encode(), salt=row['salt'], n=8192, r=8, p=1, dklen=32)
        if not hmac.compare_digest(row['password_hash'], pwd_hash):
            return False
        self._encrypt_vault_files(rel_path, self.get_user_storage(username), password, row['salt'])
        self._get_conn().execute(
            'UPDATE file_vaults SET is_locked = 1 WHERE filepath = ? AND username = ?',
            (rel_path, username)
        )
        self._get_conn().commit()
        return True

    def get_user_usage(self, username: str) -> int:
        user_storage = self.get_user_storage(username)
        total = 0
        for root, dirs, files in os.walk(user_storage, followlinks=False):
            dirs[:] = [name for name in dirs if name != ".thumbnails" and
                       not os.path.islink(os.path.join(root, name))]
            for name in files:
                path = os.path.join(root, name)
                if name.endswith(".uploading") or os.path.islink(path):
                    continue
                try:
                    total += os.path.getsize(path)
                except OSError:
                    continue
        return total

    def cleanup_recycle_bin(self, max_weeks: int = 4):
        now, max_age = time.time(), max_weeks * 7 * 24 * 3600
        try:
            user_dirs = [entry.path for entry in os.scandir(self.base_path)
                         if entry.is_dir(follow_symlinks=False)]
        except OSError as exc:
            logger.error(f"Unable to inspect storage for recycle-bin cleanup: {exc}")
            return

        for user_dir in user_dirs:
            trash_path = os.path.join(user_dir, ".Corbeille")
            if not os.path.isdir(trash_path):
                continue
            for root, dirs, files in os.walk(trash_path, topdown=False):
                for name in files:
                    path = os.path.join(root, name)
                    try:
                        if now - os.path.getmtime(path) > max_age:
                            os.remove(path)
                    except OSError:
                        logger.warning(f"Unable to remove expired trash item: {path}")
                for name in dirs:
                    path = os.path.join(root, name)
                    try:
                        if not os.listdir(path):
                            os.rmdir(path)
                    except OSError:
                        logger.warning(f"Unable to remove empty trash directory: {path}")

    def get_thumbnail(self, rel_path: str, username: str) -> Optional[str]:
        if not HAS_PILLOW: return None
        user_storage = self.get_user_storage(username)
        abs_p = self.get_abs_path(rel_path, user_storage)
        if not os.path.exists(abs_p): return None
        
        thumb_dir = os.path.join(user_storage, ".thumbnails")
        os.makedirs(thumb_dir, exist_ok=True)
        h = hashlib.md5(rel_path.encode()).hexdigest()
        thumb_path = os.path.join(thumb_dir, f"{h}.webp")
        
        if os.path.exists(thumb_path) and os.path.getmtime(thumb_path) > os.path.getmtime(abs_p):
            return thumb_path
            
        try:
            with Image.open(abs_p) as img:
                img.thumbnail((256, 256))
                img.save(thumb_path, "WEBP", quality=80)
            return thumb_path
        except Exception: return None

    def add_tag(self, rel_path: str, tag: str, username: str) -> bool:
        try:
            self._get_conn().execute('INSERT OR IGNORE INTO file_tags (username, filepath, tag) VALUES (?, ?, ?)', (username, rel_path, tag))
            self._get_conn().commit()
            return True
        except Exception: return False
