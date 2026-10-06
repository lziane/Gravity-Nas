import os
import shutil
import secrets
import mimetypes
import uvicorn
import asyncio
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.concurrency import run_in_threadpool

from app.auth import AuthManager
from app.remote import RemoteManager
from app.services.file_service import FileService
from app.services.search_service import SearchService
from app.services.monitor_service import MonitorService
from app.services.hardware_service import HardwareService
from app.services.task_service import TaskService
from app.services.backup_service import BackupService
from app.core.config import get_client_ip
import app.dependencies as deps

import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("GravityNAS.main")

# --- Configuration & Initialization ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_PORT = int(os.environ.get("NAS_PORT", "8000"))

def detect_largest_drive():
    import sys
    default_path = os.path.join(BASE_DIR, "nas_storage")
    if sys.platform != "linux": return default_path
    try:
        max_free = shutil.disk_usage(BASE_DIR).free
        best_path = default_path
        with open('/proc/mounts', 'r') as f:
            for line in f:
                parts = line.split()
                if len(parts) < 3: continue
                mount_point = parts[1].replace('\040', ' ')
                if parts[2] in ['tmpfs', 'devtmpfs', 'squashfs', 'overlay', 'proc', 'sysfs', 'cgroup2']:
                    continue
                if mount_point.startswith(('/proc', '/sys', '/dev', '/run')):
                    continue
                try:
                    usage = shutil.disk_usage(mount_point)
                    if usage.free > max_free + (1024**3):
                        max_free = usage.free
                        best_path = os.path.join(mount_point, "GravityNAS_Storage")
                except Exception as e:
                    logger.warning(f"Impossible de lire l'usage de {mount_point}: {e}")
                    continue
        return best_path
    except Exception as e:
        logger.error(f"Erreur critique lors de la détection du plus grand disque: {e}")
        return default_path

STORAGE_DIR = os.environ.get("GRAVITY_STORAGE_PATH") or detect_largest_drive()
os.makedirs(STORAGE_DIR, exist_ok=True)
DATA_DIR = os.environ.get("GRAVITY_DATA_PATH", os.path.join(BASE_DIR, "data"))
os.makedirs(DATA_DIR, exist_ok=True)
AUTH_DB = os.path.join(DATA_DIR, "users_auth.db")

# Initialize Services
from app.services.service_manager import ServiceManager
deps.auth = AuthManager(AUTH_DB)
deps.file_service = FileService(STORAGE_DIR, AUTH_DB)
deps.file_service.protect_vault_permissions()
deps.search_service = SearchService(AUTH_DB)
deps.monitor_service = MonitorService(STORAGE_DIR)
deps.hardware_service = HardwareService()
deps.task_service = TaskService(concurrency=2)
deps.backup_service = BackupService(DATA_DIR, STORAGE_DIR, os.path.join(BASE_DIR, "backups"))
deps.remote = RemoteManager(BASE_DIR)
deps.service_manager = ServiceManager()

mimetypes.init()

# --- Background Tasks ---
async def thermo_regulator():
    while True:
        try:
            stats = deps.monitor_service.get_stats()
            deps.hardware_service.update_fan_speed(stats.get("cpu_temp", 35))
        except Exception as e:
            logger.error(f"Erreur dans le régulateur thermique : {e}")
        await asyncio.sleep(10)

async def background_maintenance():
    while True:
        try:
            deps.auth.prune_expired_sessions()
            weeks = int(deps.auth.get_system_setting("trash_cleanup_weeks", "4"))
            deps.file_service.cleanup_recycle_bin(weeks)
            
            # Periodic indexing
            users = deps.auth.get_users()
            for u in users:
                user_storage = deps.file_service.get_user_storage(u["username"])
                await deps.task_service.enqueue(deps.search_service.index_user_files, user_storage, u["username"])
        except Exception as e:
            logger.error(f"Erreur dans la maintenance en arrière-plan : {e}")
        await asyncio.sleep(3600)

@asynccontextmanager
async def lifespan(app):
    background_tasks = []
    # Startup
    remote_token = deps.auth.get_system_setting("remote_token", "").strip()
    if (os.environ.get("GRAVITY_ALLOW_REMOTE", "0") == "1" and
            deps.auth.get_system_setting("remote_enabled", "0") == "1" and
            remote_token):
        deps.remote.start_tunnel(
            mode="ngrok", local_port=SERVER_PORT,
            token=remote_token,
            domain=deps.auth.get_system_setting("remote_domain")
        )
    
    # Start Services
    await deps.task_service.start()
    background_tasks.append(
        asyncio.create_task(
            asyncio.to_thread(deps.hardware_service.start_mdns, SERVER_PORT),
            name="mdns-registration",
        )
    )
    
    # Background Loops
    background_tasks.extend((
        asyncio.create_task(thermo_regulator(), name="thermo-regulator"),
        asyncio.create_task(background_maintenance(), name="background-maintenance"),
    ))
    
    yield
    # Shutdown
    for task in background_tasks:
        task.cancel()
    await asyncio.gather(*background_tasks, return_exceptions=True)
    await asyncio.to_thread(deps.hardware_service.stop_mdns)
    deps.remote.stop_tunnel()
    await deps.task_service.stop()

# --- FastAPI App ---
app = FastAPI(title="GravityNAS", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=deps.STATIC_DIR), name="static")

# Include Routers
from routes import admin, auth, files, settings
app.include_router(auth.router)
app.include_router(files.router)
app.include_router(settings.router)
app.include_router(admin.router)

# --- Middleware ---
@app.middleware("http")
async def check_setup_and_security(request: Request, call_next):
    path = request.url.path
    if path.startswith("/static") or path == "/favicon.ico":
        return await call_next(request)

    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin") or request.headers.get("referer")
        if origin:
            origin_host = urlparse(origin).netloc
            request_host = request.headers.get("host", "").split(":", 1)[0]
            if origin_host and request_host and origin_host.split(":", 1)[0] != request_host:
                return JSONResponse({"detail": "Origine de requête refusée"}, status_code=403)

    client_ip = get_client_ip(request)
    
    if await run_in_threadpool(deps.auth.is_ip_banned, client_ip):
        return HTMLResponse("Accès suspendu (Bruteforce détecté).", status_code=403)

    user_count = await run_in_threadpool(deps.auth.get_user_count)
    bypass = {"/health", "/setup", "/setup/process", "/login", "/logout", "/forgot-password", "/reset-password"}
    if user_count == 0 and path not in bypass:
        return RedirectResponse(url="/setup", status_code=303)

    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "gravitynas"}

# --- Core Routes ---
@app.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request):
    if deps.auth.get_user_count() > 0: return RedirectResponse(url="/login")
    usage = shutil.disk_usage(STORAGE_DIR)
    return deps.templates.TemplateResponse(request, "setup.html", {
        "storage_path": STORAGE_DIR,
        "storage_total_gb": round(usage.total / 1024**3, 1),
        "storage_free_gb": round(usage.free / 1024**3, 1),
    })

@app.post("/setup/process")
def setup_process(request: Request, username: str = Form(...), password: str = Form(...), email: str = Form(...), quota_gb: int = Form(0)):
    if deps.auth.get_user_count() > 0: return RedirectResponse(url="/login")
    if quota_gb < 0:
        return RedirectResponse(url="/setup?error=1", status_code=303)
    success = deps.auth.create_user(username.strip(), password, email.strip(), "superadmin")
    if success:
        conn = deps.auth._get_conn()
        conn.execute("UPDATE users SET quota_gb = ? WHERE username = ?", (quota_gb, username.strip()))
        conn.commit()
        token = secrets.token_hex(64)
        deps.auth.create_session(token, username, 3600 * 12)
        response = RedirectResponse(url="/", status_code=303)
        is_secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        response.set_cookie("nas_session", token, httponly=True, secure=is_secure, samesite="lax")
        return response
    return RedirectResponse(url="/setup?error=1", status_code=303)

@app.get("/", response_class=HTMLResponse)
def home(request: Request, path: str = ""):
    try:
        user = deps.get_current_user(request)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=303)

    files_list = deps.file_service.list_files(path, username=user["username"])
    all_meta = deps.auth.get_user_file_meta(user["username"])
    
    pinned_items = []
    
    for fpath, meta in all_meta.items():
        if meta.get("is_pinned"): 
            pinned_items.append({"name": fpath.rsplit("/", 1)[-1] or fpath, "path": fpath})

    # Breadcrumbs logic
    parts, curr, breadcrumbs = (path.split("/") if path else []), "", []
    for p in parts:
        if p:
            curr = f"{curr}/{p}" if curr else p
            breadcrumbs.append({"name": p, "path": curr})

    is_admin = user.get("role") in {"admin", "superadmin"}

    return deps.templates.TemplateResponse(request, "index.html", {
        "files": files_list, "path": path, "breadcrumbs": breadcrumbs, 
        "parent_path": path.rsplit("/", 1)[0] if "/" in path else "",
        "current_path": path, "stats": deps.monitor_service.get_stats(), "user": user,
        "all_users": deps.auth.get_users() if is_admin else [],
        "pinned_items": pinned_items, "remote_url": deps.remote.public_url,
        "remote_enabled": deps.auth.get_system_setting("remote_enabled", "0") == "1",
        "remote_token": deps.auth.get_system_setting("remote_token", "") if is_admin else "",
        "remote_domain": deps.auth.get_system_setting("remote_domain", "") if is_admin else "",
        "service_statuses": deps.service_manager.get_all_statuses()
    })

if __name__ == "__main__":
    import argparse
    import sys
    
    parser = argparse.ArgumentParser(description="GravityNAS Server")
    parser.add_argument("--reset", type=str, help="Réinitialiser le mot de passe d'un utilisateur")
    args = parser.parse_known_args()[0]
    
    if args.reset:
        new_pwd = secrets.token_hex(4) # Génère un code court
        if deps.auth.reset_password_cli(args.reset, new_pwd):
            print(f"\n[SUCCÈS] Mot de passe réinitialisé pour {args.reset}")
            print(f"Nouveau mot de passe temporaire : {new_pwd}")
            print("Connectez-vous et changez-le immédiatement.\n")
            sys.exit(0)
        else:
            print(f"\n[ERREUR] Utilisateur '{args.reset}' introuvable.\n")
            sys.exit(1)

    uvicorn.run(app, host="0.0.0.0", port=SERVER_PORT)