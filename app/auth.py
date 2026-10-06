import sqlite3
import os
import hashlib
import secrets
import threading
import subprocess
import base64
import logging
import re
from datetime import datetime, timedelta
from cryptography.fernet import Fernet
from typing import Optional, Dict, List, Any

logger = logging.getLogger("GravityNAS.Auth")

class AuthManager:
    _MASTER_KEY_MAGIC = b"GNMASTER1"

    def __init__(self, db_path: str, master_password: Optional[str] = None):
        self.db_path = db_path
        self._local = threading.local()
        master = master_password or os.environ.get("GRAVITY_MASTER_PWD", "")
        self._init_encryption(master)
        self._init_db()

    def _init_encryption(self, password: str) -> None:
        key_file = os.path.join(os.path.dirname(self.db_path), ".nas_encryption.key")
        try:
            if os.path.exists(key_file):
                with open(key_file, "rb") as f: key = f.read()
                if key.startswith(self._MASTER_KEY_MAGIC):
                    salt_start = len(self._MASTER_KEY_MAGIC)
                    salt = key[salt_start:salt_start + 16]
                    wrapped_key = key[salt_start + 16:]
                    if not password:
                        raise RuntimeError("GRAVITY_MASTER_PWD is required to open the encryption key")
                    wrapping_key = hashlib.scrypt(
                        password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32
                    )
                    key = Fernet(base64.urlsafe_b64encode(wrapping_key)).decrypt(wrapped_key)
                try:
                    self.fernet = Fernet(key)
                except ValueError:
                    if len(key) != 32:
                        raise
                    key = base64.urlsafe_b64encode(key)
                    with open(key_file, "wb") as f: f.write(key)
                    self.fernet = Fernet(key)
            else:
                key = Fernet.generate_key()
                if password:
                    salt = secrets.token_bytes(16)
                    wrapping_key = hashlib.scrypt(
                        password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32
                    )
                    wrapped = Fernet(base64.urlsafe_b64encode(wrapping_key)).encrypt(key)
                    key = self._MASTER_KEY_MAGIC + salt + wrapped
                    with open(key_file, "wb") as f: f.write(key)
                    self.fernet = Fernet(Fernet(base64.urlsafe_b64encode(wrapping_key)).decrypt(wrapped))
                else:
                    with open(key_file, "wb") as f: f.write(key)
                    self.fernet = Fernet(key)
            os.chmod(key_file, 0o600)
        except Exception as e:
            logger.critical(f"Encryption Init Failed: {e}")
            raise RuntimeError("CRITICAL: Storage Encryption Key Missing or Inaccessible.")

    def encrypt(self, data: str) -> str:
        return self.fernet.encrypt(data.encode()).decode() if data else ""

    def decrypt(self, token: str) -> str:
        if not token: return ""
        try: return self.fernet.decrypt(token.encode()).decode()
        except Exception: return "[ENCRYPTED_DATA_CORRUPTED]"

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=15)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA cache_size=-16000")
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.execute("PRAGMA mmap_size=134217728")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return self._local.conn

    def _init_db(self) -> None:
        conn = self._get_conn()
        try:
            self._migrate_file_index(conn)
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    password_hash BLOB NOT NULL,
                    salt BLOB NOT NULL,
                    email_encrypted TEXT,
                    email_hash TEXT,
                    role TEXT DEFAULT 'user',
                    quota_gb INTEGER DEFAULT 0,
                    mfa_secret TEXT,
                    mfa_enabled INTEGER DEFAULT 0,
                    recovery_token TEXT,
                    token_expiry DATETIME,
                    avatar TEXT DEFAULT '',
                    wallpaper TEXT DEFAULT '',
                    theme TEXT DEFAULT 'light',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS system_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );

                CREATE TABLE IF NOT EXISTS ip_bans (
                    ip TEXT PRIMARY KEY,
                    attempts INTEGER DEFAULT 0,
                    last_attempt DATETIME,
                    banned_until DATETIME
                );

                CREATE TABLE IF NOT EXISTS file_index (
                    filepath TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    filename TEXT,
                    extension TEXT,
                    size INTEGER,
                    mtime REAL,
                    content_text TEXT,
                    last_indexed DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS file_meta (
                    username TEXT NOT NULL,
                    filepath TEXT NOT NULL,
                    color TEXT DEFAULT '',
                    emoji TEXT DEFAULT '',
                    is_pinned INTEGER DEFAULT 0,
                    PRIMARY KEY (username, filepath)
                );

                CREATE TABLE IF NOT EXISTS file_shares (
                    token TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    filepath TEXT NOT NULL,
                    expires_at DATETIME,
                    download_count INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS file_vaults (
                    filepath TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    salt BLOB NOT NULL,
                    password_hash BLOB NOT NULL,
                    is_locked INTEGER DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS file_tags (
                    username TEXT NOT NULL,
                    filepath TEXT NOT NULL,
                    tag TEXT NOT NULL,
                    PRIMARY KEY (username, filepath, tag)
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    data TEXT DEFAULT '{}',
                    expires_at DATETIME NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(username) REFERENCES users(username) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_file_meta_user ON file_meta(username);
                CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token);

                -- FTS5 table for high-speed search (External Content)
                CREATE VIRTUAL TABLE IF NOT EXISTS file_index_fts USING fts5(
                    filepath, filename, username UNINDEXED, content_text, content='file_index'
                );

                -- Triggers to keep FTS in sync
                CREATE TRIGGER IF NOT EXISTS file_index_ai AFTER INSERT ON file_index BEGIN
                  INSERT INTO file_index_fts(rowid, filepath, filename, username, content_text)
                  VALUES (new.rowid, new.filepath, new.filename, new.username, new.content_text);
                END;
                CREATE TRIGGER IF NOT EXISTS file_index_ad AFTER DELETE ON file_index BEGIN
                  INSERT INTO file_index_fts(file_index_fts, rowid, filepath, filename, username, content_text)
                  VALUES('delete', old.rowid, old.filepath, old.filename, old.username, old.content_text);
                END;
                CREATE TRIGGER IF NOT EXISTS file_index_au AFTER UPDATE ON file_index BEGIN
                  INSERT INTO file_index_fts(file_index_fts, rowid, filepath, filename, username, content_text)
                  VALUES('delete', old.rowid, old.filepath, old.filename, old.username, old.content_text);
                  INSERT INTO file_index_fts(rowid, filepath, filename, username, content_text)
                  VALUES (new.rowid, new.filepath, new.filename, new.username, new.content_text);
                END;
            ''')
            
            settings_defaults = [("remote_token", ""), ("remote_domain", ""), ("remote_enabled", "0"), ("trash_cleanup_weeks", "4")]
            conn.executemany('INSERT OR IGNORE INTO system_settings (key, value) VALUES (?, ?)', settings_defaults)
            conn.execute('DELETE FROM sessions')
            conn.commit()
        except sqlite3.Error as e:
            logger.critical(f"Database Initialization Failed: {e}")
            raise

    def _migrate_file_index(self, conn: sqlite3.Connection) -> None:
        """Move legacy single-user paths to a per-user composite key."""
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'file_index'"
        ).fetchone()
        if not table:
            return

        columns = conn.execute("PRAGMA table_info(file_index)").fetchall()
        filepath_pk = next((row for row in columns if row[1] == "filepath"), None)
        username_pk = next((row for row in columns if row[1] == "username"), None)
        if not filepath_pk or filepath_pk[5] != 1 or (username_pk and username_pk[5] == 1):
            return

        conn.executescript("""
            DROP TRIGGER IF EXISTS file_index_ai;
            DROP TRIGGER IF EXISTS file_index_ad;
            DROP TRIGGER IF EXISTS file_index_au;
            DROP TABLE IF EXISTS file_index_fts;
            ALTER TABLE file_index RENAME TO file_index_legacy;
            CREATE TABLE file_index (
                filepath TEXT NOT NULL,
                username TEXT NOT NULL,
                filename TEXT,
                extension TEXT,
                size INTEGER,
                mtime REAL,
                content_text TEXT,
                last_indexed DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (username, filepath)
            );
            INSERT INTO file_index (filepath, username, filename, extension, size, mtime, content_text, last_indexed)
                SELECT filepath, username, filename, extension, size, mtime, content_text, last_indexed
                FROM file_index_legacy;
            DROP TABLE file_index_legacy;
        """)
        conn.commit()

    def get_user_count(self) -> int:
        return self._get_conn().execute('SELECT COUNT(*) FROM users').fetchone()[0]

    def create_session(self, token: str, username: str, expires_in_seconds: int) -> Optional[Dict]:
        conn = self._get_conn()
        expires_at = datetime.now() + timedelta(seconds=expires_in_seconds)
        conn.execute('INSERT INTO sessions (token, username, expires_at) VALUES (?, ?, ?)', (token, username, expires_at))
        conn.commit()
        return self.get_session(token)

    def _parse_db_date(self, val: Any) -> datetime:
        if isinstance(val, datetime): return val
        if not val: return datetime.min
        try:
            return datetime.strptime(str(val).split(".")[0], "%Y-%m-%d %H:%M:%S")
        except Exception:
            return datetime.min

    def get_session(self, token: str) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        row = conn.execute('''SELECT s.username, s.expires_at, u.role, u.avatar, u.wallpaper, u.theme FROM sessions s JOIN users u ON s.username = u.username WHERE s.token = ?''', (token,)).fetchone()
        if not row: return None
        
        expires_at = self._parse_db_date(row['expires_at'])
        if datetime.now() > expires_at:
            self.delete_session(token)
            return None
            
        return {"username": row['username'], "role": row['role'], "avatar": row['avatar'], "wallpaper": row['wallpaper'], "theme": row['theme'], "nas_token": token}

    def delete_session(self, token: str) -> None:
        conn = self._get_conn()
        conn.execute('DELETE FROM sessions WHERE token = ?', (token,))
        conn.commit()

    def prune_expired_sessions(self) -> None:
        conn = self._get_conn()
        conn.execute('DELETE FROM sessions WHERE expires_at < ?', (datetime.now(),))
        conn.commit()

    def update_session_data(self, username: str, **kwargs) -> None:
        """Met à jour les données de session en cache pour un utilisateur spécifique."""
        conn = self._get_conn()
        rows = conn.execute('SELECT token, data FROM sessions WHERE username = ?', (username,)).fetchall()
        for row in rows:
            try:
                import json
                data = json.loads(row['data'] or '{}')
                data.update(kwargs)
                conn.execute('UPDATE sessions SET data = ? WHERE token = ?', (json.dumps(data), row['token']))
            except Exception as e:
                logger.error(f"Failed to update session data for {username}: {e}")
        conn.commit()

    def delete_user_sessions(self, username: str) -> None:
        """Supprime toutes les sessions actives d'un utilisateur."""
        conn = self._get_conn()
        conn.execute('DELETE FROM sessions WHERE username = ?', (username,))
        conn.commit()

    def set_system_setting(self, key: str, value: Any) -> None:
        conn = self._get_conn()
        conn.execute('INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)', (key, str(value)))
        conn.commit()

    def get_system_setting(self, key: str, default: str = "") -> str:
        row = self._get_conn().execute('SELECT value FROM system_settings WHERE key = ?', (key,)).fetchone()
        return row[0] if row else default

    def update_user_preferences(self, username: str, avatar: str = None, wallpaper: str = None, theme: str = None) -> bool:
        conn = self._get_conn()
        updates, params = [], []
        if avatar is not None: updates.append("avatar = ?"); params.append(avatar)
        if wallpaper is not None: updates.append("wallpaper = ?"); params.append(wallpaper)
        if theme is not None: updates.append("theme = ?"); params.append(theme)
        
        if updates:
            params.append(username)
            conn.execute(f'UPDATE users SET {", ".join(updates)} WHERE username = ?', params)
            conn.commit()
        return True

    def _hash_password(self, password: str, salt: bytes = None) -> tuple[bytes, bytes]:
        salt = salt or secrets.token_bytes(32)
        pwd_hash = hashlib.scrypt(password.encode('utf-8'), salt=salt, n=16384, r=8, p=1, dklen=64)
        return pwd_hash, salt

    def _hash_email(self, email: str) -> str:
        return hashlib.sha256(email.lower().strip().encode()).hexdigest() if email else ""

    def _sync_samba(self, username: str, password: str) -> None:
        if os.name == 'nt': return
        try:
            subprocess.run(['sudo', '-n', 'groupadd', '-f', 'gravitynas_users'], capture_output=True)
            subprocess.run(['sudo', '-n', 'useradd', '-M', '-N', '-g', 'gravitynas_users', '-s', '/usr/sbin/nologin', username], capture_output=True)
            proc = subprocess.Popen(['sudo', '-n', 'smbpasswd', '-a', '-s', username], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
            proc.communicate(input=f"{password}\n{password}\n")
            subprocess.run(['sudo', '-n', 'smbpasswd', '-e', username], capture_output=True)
        except Exception as e: logger.error(f"Samba Sync Failed for {username}: {e}")

    def is_ip_banned(self, ip: str) -> bool:
        row = self._get_conn().execute('SELECT banned_until FROM ip_bans WHERE ip = ?', (ip,)).fetchone()
        if not row or not row[0]: return False
        return datetime.now() < self._parse_db_date(row[0])

    def track_failed_login(self, ip: str) -> None:
        conn = self._get_conn()
        row = conn.execute('SELECT attempts FROM ip_bans WHERE ip = ?', (ip,)).fetchone()
        attempts = (row['attempts'] if row else 0) + 1
        banned_until = datetime.now() + timedelta(minutes=15) if attempts >= 5 else None
        conn.execute('''
            INSERT OR REPLACE INTO ip_bans (ip, attempts, last_attempt, banned_until)
            VALUES (?, ?, ?, ?)
        ''', (ip, attempts, datetime.now(), banned_until))
        conn.commit()

    def clear_failed_login(self, ip: str) -> None:
        conn = self._get_conn()
        conn.execute('DELETE FROM ip_bans WHERE ip = ?', (ip,))
        conn.commit()

    def get_user_info(self, username: str) -> dict:
        row = self._get_conn().execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        return dict(row) if row else {}

    def create_user(self, username: str, password: str, email: str, role: str = "user") -> bool:
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9_]{2,31}$", username):
            logger.warning(f"Échec création utilisateur: Nom '{username}' invalide (lettres/chiffres/_, 3-32 caractères)")
            return False
        if len(password) < 8 or role not in {"user", "admin", "superadmin"}:
            return False
        pwd_hash, salt = self._hash_password(password)
        conn = self._get_conn()
        try:
            conn.execute('''INSERT INTO users (username, password_hash, salt, email_encrypted, email_hash, role) VALUES (?, ?, ?, ?, ?, ?)''', (username, pwd_hash, salt, self.encrypt(email), self._hash_email(email), role))
            conn.commit()
            threading.Thread(target=self._sync_samba, args=(username, password), daemon=True).start()
            return True
        except sqlite3.IntegrityError:
            logger.warning(f"Échec création utilisateur: Le nom '{username}' existe déjà.")
            return False

    def enable_mfa(self, username: str, secret: str) -> bool:
        conn = self._get_conn()
        conn.execute('UPDATE users SET mfa_secret = ?, mfa_enabled = 0 WHERE username = ?', (secret, username))
        conn.commit()
        return True

    def confirm_mfa(self, username: str, code: str) -> bool:
        import pyotp
        row = self._get_conn().execute(
            'SELECT mfa_secret FROM users WHERE username = ?', (username,)
        ).fetchone()
        if not row or not row['mfa_secret'] or not pyotp.TOTP(row['mfa_secret']).verify(code):
            return False
        self._get_conn().execute(
            'UPDATE users SET mfa_enabled = 1 WHERE username = ?', (username,)
        )
        self._get_conn().commit()
        return True

    def authenticate(self, username: str, password: str) -> Optional[Dict]:
        row = self._get_conn().execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        if row:
            computed_hash, _ = self._hash_password(password, bytes(row['salt']))
            if secrets.compare_digest(bytes(row['password_hash']), computed_hash):
                return {"username": username, "role": row['role'], "avatar": row['avatar'], "wallpaper": row['wallpaper'], "theme": row['theme'], "mfa_enabled": row['mfa_enabled']}
        return None

    def reset_password_cli(self, username: str, new_password: str) -> bool:
        if len(new_password) < 8:
            return False
        pwd_hash, salt = self._hash_password(new_password)
        conn = self._get_conn()
        cursor = conn.execute('UPDATE users SET password_hash = ?, salt = ?, recovery_token = NULL, token_expiry = NULL WHERE username = ?', (pwd_hash, salt, username))
        conn.commit()
        if cursor.rowcount > 0:
            threading.Thread(target=self._sync_samba, args=(username, new_password), daemon=True).start()
        return cursor.rowcount > 0

    def get_users(self) -> List[Dict]:
        rows = self._get_conn().execute('SELECT username, role, email_encrypted FROM users ORDER BY role DESC, username ASC').fetchall()
        return [{"username": r['username'], "role": r['role'], "email": self.decrypt(r['email_encrypted'])} for r in rows]

    def delete_user(self, target_username: str, deleter_username: str, deleter_role: str) -> bool:
        if target_username == deleter_username: return False
        conn = self._get_conn()
        target = conn.execute('SELECT role FROM users WHERE username = ?', (target_username,)).fetchone()
        if not target: return False
        
        can_delete = (deleter_role == "superadmin" and target['role'] != "superadmin") or (deleter_role == "admin" and target['role'] == "user")
        if can_delete:
            for table in ("file_meta", "file_tags", "file_shares", "file_vaults", "file_index"):
                conn.execute(f'DELETE FROM {table} WHERE username = ?', (target_username,))
            cursor = conn.execute('DELETE FROM users WHERE username = ?', (target_username,))
            conn.commit()
            if cursor.rowcount > 0:
                if os.name != 'nt':
                    subprocess.run(['sudo', '-n', 'smbpasswd', '-x', target_username], capture_output=True)
                    subprocess.run(['sudo', '-n', 'userdel', target_username], capture_output=True)
                return True
        return False

    def get_user_file_meta(self, username: str) -> Dict:
        rows = self._get_conn().execute('SELECT filepath, color, emoji, is_pinned FROM file_meta WHERE username = ?', (username,)).fetchall()
        return {r['filepath']: {"color": r['color'], "emoji": r['emoji'], "is_pinned": bool(r['is_pinned'])} for r in rows}

    def set_file_meta(self, username: str, filepath: str, key: str, value: Any) -> bool:
        if key not in ("color", "emoji", "is_pinned"): return False
        conn = self._get_conn()
        conn.execute('INSERT OR IGNORE INTO file_meta (username, filepath) VALUES (?, ?)', (username, filepath))
        if key in ("color", "emoji"): conn.execute(f'UPDATE file_meta SET {key} = ? WHERE username = ? AND filepath = ?', (str(value or ""), username, filepath))
        elif key == "is_pinned": conn.execute('UPDATE file_meta SET is_pinned = ? WHERE username = ? AND filepath = ?', (1 if str(value).lower() in ("1", "true") else 0, username, filepath))
        conn.commit()
        return True

    def clear_file_meta(self, username: str, filepath: str) -> bool:
        conn = self._get_conn()
        conn.execute('DELETE FROM file_meta WHERE username = ? AND (filepath = ? OR filepath LIKE ?)', (username, filepath, f"{filepath}/%"))
        conn.commit()
        return True

    def create_share_token(self, username: str, filepath: str, expiry_days: int = 7) -> str:
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now() + timedelta(days=expiry_days)
        self._get_conn().execute('INSERT INTO file_shares (token, username, filepath, expires_at) VALUES (?, ?, ?, ?)', (token, username, filepath, expires_at))
        self._get_conn().commit()
        return token

    def get_share_info(self, token: str) -> Optional[Dict]:
        row = self._get_conn().execute('SELECT * FROM file_shares WHERE token = ?', (token,)).fetchone()
        if not row: return None
        expires_at = self._parse_db_date(row['expires_at'])
        if datetime.now() > expires_at: return None
        return dict(row)
