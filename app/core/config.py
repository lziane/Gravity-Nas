from pathlib import Path
import ipaddress
import os
from fastapi import Request

# Base Paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"
BACKUP_DIR = BASE_DIR / "backups"

# Ensure directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

# Database
AUTH_DB = DATA_DIR / "users_auth.db"

# Settings
REMOTE_PORT = 8000
CONCURRENCY_LEVEL = 2
TRASH_CLEANUP_WEEKS_DEFAULT = 4

def get_client_ip(request: Request) -> str:
    """Return the peer address unless a configured proxy vouches for it."""
    peer_ip = request.client.host if request.client else ""
    trusted_proxies = {
        value.strip()
        for value in os.environ.get("GRAVITY_TRUSTED_PROXIES", "").split(",")
        if value.strip()
    }
    if peer_ip not in trusted_proxies:
        return peer_ip

    forwarded_ip = request.headers.get("x-real-ip", "").strip()
    try:
        return str(ipaddress.ip_address(forwarded_ip))
    except ValueError:
        return peer_ip

def get_storage_dir():
    # Placeholder for logic from main.py
    default_path = BASE_DIR / "nas_storage"
    return str(default_path)
