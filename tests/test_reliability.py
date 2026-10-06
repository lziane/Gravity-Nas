import pytest
import os
import shutil
import asyncio
import time
import sqlite3
from starlette.requests import Request
from app.core.secure_fs import SecureFileSystem
from app.core.config import get_client_ip
from app.services.file_service import FileService
from app.services.search_service import SearchService
from app.services.backup_service import BackupService
from routes.files import LockManager

@pytest.fixture
def temp_storage(tmp_path):
    storage = tmp_path / "nas_storage"
    storage.mkdir()
    return str(storage)

@pytest.fixture
def temp_db(tmp_path):
    return str(tmp_path / "test.db")

# TEST 1: Path Traversal and Symlink Detection
def test_secure_fs_traversal(temp_storage):
    sfs = SecureFileSystem(temp_storage)
    user_path = os.path.join(temp_storage, "user1")
    os.makedirs(user_path, exist_ok=True)
    
    # Valid path
    assert sfs.get_abs_path("file.txt", user_path) == os.path.realpath(os.path.join(user_path, "file.txt"))
    
    # Traversal attempt
    with pytest.raises(PermissionError):
        sfs.get_abs_path("../outside.txt", user_path)
        
    # Symlink attempt
    secret_file = os.path.join(temp_storage, "secret.txt")
    with open(secret_file, "w") as f: f.write("secret")
    
    symlink_path = os.path.join(user_path, "link.txt")
    try:
        os.symlink(secret_file, symlink_path)
        with pytest.raises(PermissionError):
            sfs.get_abs_path("link.txt", user_path)
    except OSError as e:
        if e.winerror == 1314:
            pytest.skip("Symlink privilege not available on Windows")
        raise

    symlink_dir = os.path.join(user_path, "linked-dir")
    os.symlink(temp_storage, symlink_dir)
    with pytest.raises(PermissionError):
        sfs.get_abs_path("linked-dir/secret.txt", user_path)

# TEST 2: LockManager Concurrency
@pytest.mark.asyncio
async def test_lock_manager_concurrency():
    lm = LockManager()
    lock = lm.get_lock("user1")
    
    async def task():
        async with lm.get_lock("user1"):
            await asyncio.sleep(0.1)
            return True

    # Start first task
    async with lock:
        # Second task should wait
        t2 = asyncio.create_task(task())
        done, pending = await asyncio.wait([t2], timeout=0.05)
        assert len(done) == 0 # Still locked
    
    # After releasing, second task should finish
    await t2
    assert t2.result() is True

# TEST 3: LockManager Pruning (Memory Leak Prevention)
def test_lock_manager_pruning():
    lm = LockManager()
    lm.get_lock("user1")
    lm.get_lock("user2")
    
    # Manually backdate access
    lm._last_access["user1"] = asyncio.get_event_loop().time() - 4000 
    
    lm.prune(max_age=3600)
    assert "user1" not in lm._locks
    assert "user2" in lm._locks

# TEST 4: SearchService Indexing (Mock OCR)
def test_search_service_indexing(temp_db, temp_storage, monkeypatch):
    # Mock OCR to avoid external dependencies
    monkeypatch.setattr("app.services.search_service.extract_text_from_file", lambda x: "mocked content")
    
    ss = SearchService(temp_db)
    # Initialize tables (this is usually done in main, but here for test)
    conn = ss._get_conn()
    conn.executescript('''
        CREATE TABLE file_index (filepath TEXT PRIMARY KEY, filename TEXT, extension TEXT, size INTEGER, mtime DATETIME, username TEXT, content_text TEXT);
        CREATE VIRTUAL TABLE file_index_fts USING fts5(filepath UNINDEXED, filename, extension UNINDEXED, content_text, username UNINDEXED);
        CREATE TRIGGER file_index_ai AFTER INSERT ON file_index BEGIN
            INSERT INTO file_index_fts(filepath, filename, extension, content_text, username)
            VALUES (new.filepath, new.filename, new.extension, new.content_text, new.username);
        END;
    ''')
    
    test_file = os.path.join(temp_storage, "test.pdf")
    with open(test_file, "w") as f: f.write("hello world")
    
    ss.index_file(test_file, "test.pdf", "user1")
    results = ss.search("mocked", "user1")
    
    assert len(results) == 1
    assert results[0]["filename"] == "test.pdf"

# TEST 5: FileService Quota calculation
def test_file_service_usage(temp_db, temp_storage):
    fs = FileService(temp_storage, temp_db)
    user_storage = fs.get_user_storage("user1")
    with open(os.path.join(user_storage, "one.bin"), "wb") as handle:
        handle.write(b"a" * 1024)
    with open(os.path.join(user_storage, "two.bin"), "wb") as handle:
        handle.write(b"b" * 2048)
    
    assert fs.get_user_usage("user1") == 3072

# TEST 6: File operations enforce safe names and destinations
def test_file_service_rename_and_move(temp_db, temp_storage):
    fs = FileService(temp_storage, temp_db)
    user_storage = fs.get_user_storage("user1")
    os.makedirs(os.path.join(user_storage, "Documents"))
    with open(os.path.join(user_storage, "notes.txt"), "w") as handle:
        handle.write("notes")

    renamed = fs.rename_item("notes.txt", "archive.txt", "user1")
    assert renamed == "archive.txt"
    moved = fs.move_item("archive.txt", "Documents", "user1")
    assert moved == "Documents/archive.txt"
    assert os.path.exists(os.path.join(user_storage, moved))

    with pytest.raises(FileExistsError):
        fs.move_item("Documents/archive.txt", "Documents", "user1")
    with pytest.raises(ValueError):
        fs.rename_item("Documents/archive.txt", "../outside.txt", "user1")

# TEST 7: Directory size includes nested files
def test_file_service_directory_size(temp_db, temp_storage):
    fs = FileService(temp_storage, temp_db)
    directory = os.path.join(fs.get_user_storage("user1"), "Photos")
    os.makedirs(os.path.join(directory, "2026"))
    with open(os.path.join(directory, "cover.jpg"), "wb") as handle:
        handle.write(b"a" * 17)
    with open(os.path.join(directory, "2026", "trip.jpg"), "wb") as handle:
        handle.write(b"b" * 31)

    item = next(item for item in fs.list_files("", "user1") if item["name"] == "Photos")
    assert item["size_bytes"] == 48
    assert item["size"] != "4.0 KB"

# TEST 8: Directory moves and trash restoration preserve relative paths
def test_file_service_directory_move_and_restore(temp_db, temp_storage):
    fs = FileService(temp_storage, temp_db)
    user_storage = fs.get_user_storage("user1")
    os.makedirs(os.path.join(user_storage, "Projects", "nested"))
    with open(os.path.join(user_storage, "Projects", "nested", "plan.txt"), "w") as handle:
        handle.write("plan")
    os.makedirs(os.path.join(user_storage, "Archive"))

    moved = fs.move_item("Projects", "Archive", "user1")
    assert moved == "Archive/Projects"
    assert os.path.exists(os.path.join(user_storage, moved, "nested", "plan.txt"))

    assert fs.delete_item(moved, "user1") is True
    assert os.path.exists(os.path.join(user_storage, ".Corbeille", "Projects"))
    assert fs.restore_item(".Corbeille/Projects", "user1") == "Projects"
    assert os.path.exists(os.path.join(user_storage, "Projects", "nested", "plan.txt"))

# TEST 9: File listings expose the path contract consumed by the picker
def test_file_listing_uses_relative_path(temp_db, temp_storage):
    fs = FileService(temp_storage, temp_db)
    user_storage = fs.get_user_storage("user1")
    os.makedirs(os.path.join(user_storage, "Documents"))

    item = next(item for item in fs.list_files("", "user1") if item["name"] == "Documents")
    assert item["relative_path"] == "Documents"
    assert "path" not in item

# TEST 10: Absolute and traversal API paths are rejected before filesystem access
def test_file_api_rejects_invalid_paths():
    from routes.files import get_files_api

    response = get_files_api("/var/home/user", {"username": "user1"})
    assert response.status_code == 400
    assert response.body == b'{"status":"error","error":{"code":"INVALID_PATH","message":"Chemin de dossier invalide"}}'

    response = get_files_api("../../outside", {"username": "user1"})
    assert response.status_code == 400

# TEST 11: Symlinked storage roots still expose relative client paths
def test_file_service_canonicalizes_storage_root(temp_db, temp_storage, tmp_path):
    linked_storage = tmp_path / "linked-storage"
    try:
        linked_storage.symlink_to(temp_storage, target_is_directory=True)
    except OSError:
        pytest.skip("Symlink privilege not available")

    fs = FileService(str(linked_storage), temp_db)
    user_storage = fs.get_user_storage("user1")
    os.makedirs(os.path.join(user_storage, "Photos"))

    item = next(item for item in fs.list_files("", "user1") if item["name"] == "Photos")
    assert item["relative_path"] == "Photos"
    assert not item["relative_path"].startswith("../")


def test_client_ip_ignores_untrusted_forwarded_headers(monkeypatch):
    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"x-real-ip", b"203.0.113.10")],
        "client": ("198.51.100.2", 1234),
        "server": ("127.0.0.1", 8000),
    })
    monkeypatch.delenv("GRAVITY_TRUSTED_PROXIES", raising=False)
    assert get_client_ip(request) == "198.51.100.2"

    monkeypatch.setenv("GRAVITY_TRUSTED_PROXIES", "198.51.100.2")
    assert get_client_ip(request) == "203.0.113.10"


def test_vault_encrypts_content_at_rest(temp_db, temp_storage):
    fs = FileService(temp_storage, temp_db)
    conn = fs._get_conn()
    conn.execute('''CREATE TABLE file_vaults (
        filepath TEXT PRIMARY KEY, username TEXT, salt BLOB,
        password_hash BLOB, is_locked INTEGER
    )''')

    user_storage = fs.get_user_storage("user1")
    vault_path = os.path.join(user_storage, "Private")
    os.mkdir(vault_path)
    file_path = os.path.join(vault_path, "secret.txt")
    original = b"private contents"
    with open(file_path, "wb") as handle:
        handle.write(original)

    assert fs.create_vault("Private", "vault-password", "user1")
    encrypted = open(file_path, "rb").read()
    assert encrypted != original
    assert encrypted.startswith(b"GNVAULT1")
    assert fs.list_files("Private", "user1") == []

    assert fs.unlock_vault("Private", "vault-password", "user1")
    assert open(file_path, "rb").read() == original


def test_backup_manifest_and_staged_restore(tmp_path):
    data_dir = tmp_path / "data"
    storage_dir = tmp_path / "storage"
    backup_dir = tmp_path / "backups"
    data_dir.mkdir()
    storage_dir.mkdir()
    database = sqlite3.connect(data_dir / "users_auth.db")
    database.execute("CREATE TABLE marker (value TEXT)")
    database.execute("INSERT INTO marker VALUES ('database')")
    database.commit()
    database.close()
    (storage_dir / "document.txt").write_bytes(b"document")

    service = BackupService(str(data_dir), str(storage_dir), str(backup_dir))
    backup = service.create_backup(include_storage=True)
    service.restore_backup(os.path.basename(backup), restore_storage=True)

    restored = sqlite3.connect(data_dir / "users_auth.db.restore")
    assert restored.execute("SELECT value FROM marker").fetchone()[0] == "database"
    restored.close()
    assert (storage_dir / "document.txt").read_bytes() == b"document"
