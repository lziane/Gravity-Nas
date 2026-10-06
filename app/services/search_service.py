import os
import sqlite3
import threading
import logging
from typing import List, Dict
from app.ocr import extract_text_from_file

logger = logging.getLogger("GravityNAS.SearchService")

class SearchService:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._local = threading.local()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=10)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return self._local.conn

    def index_file(self, abs_path: str, rel_path: str, username: str):
        """Indexes a single file, including OCR if applicable."""
        if not os.path.isfile(abs_path):
            return
        ext = os.path.splitext(abs_path)[1].lower()
        content_text = ""
        
        if ext in ['.pdf', '.png', '.jpg', '.jpeg', '.webp']:
            content_text = extract_text_from_file(abs_path)
        
        stat = os.stat(abs_path)
        conn = self._get_conn()
        conn.execute('''
            INSERT OR REPLACE INTO file_index (filepath, filename, extension, size, mtime, username, content_text)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (rel_path, os.path.basename(rel_path), ext, stat.st_size, stat.st_mtime, username, content_text))
        conn.commit()

    def search(self, query: str, username: str) -> List[Dict]:
        conn = self._get_conn()
        fts_query = query + "*"
        try:
            rows = conn.execute('''
                SELECT f.filepath, f.filename, f.extension, i.size, i.mtime 
                FROM file_index_fts f
                JOIN file_index i ON f.filepath = i.filepath AND f.username = i.username
                WHERE file_index_fts MATCH ? AND f.username = ?
                LIMIT 100
            ''', (fts_query, username)).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            # Fallback to LIKE
            q = f"%{query}%"
            rows = conn.execute('''
                SELECT filepath, filename, extension, size, mtime 
                FROM file_index 
                WHERE username = ? AND (filename LIKE ? OR content_text LIKE ?)
                LIMIT 100
            ''', (username, q, q)).fetchall()
            return [dict(r) for r in rows]

    def index_user_files(self, user_storage: str, username: str):
        """Walks through user storage and updates the index."""
        indexed_files = set(r['filepath'] for r in self._get_conn().execute('SELECT filepath FROM file_index WHERE username = ?', (username,)).fetchall())
        current_files = set()

        for root, _, files in os.walk(user_storage):
            if ".Corbeille" in root or ".thumbnails" in root: continue
            for f in files:
                abs_p = os.path.join(root, f)
                rel_p = os.path.relpath(abs_p, user_storage).replace("\\", "/")
                current_files.add(rel_p)
                self.index_file(abs_p, rel_p, username)
        
        to_delete = indexed_files - current_files
        for p in to_delete:
            self.remove_file(p, username)
        self._get_conn().commit()

    def remove_file(self, rel_path: str, username: str):
        conn = self._get_conn()
        # Delete the file itself
        conn.execute('DELETE FROM file_index WHERE filepath = ? AND username = ?', (rel_path, username))
        # Also delete sub-files if it was a directory
        prefix = rel_path + "/"
        conn.execute('DELETE FROM file_index WHERE filepath LIKE ? AND username = ?', (prefix + '%', username))
        conn.commit()
