import os
from fastapi import Request, HTTPException, Depends
from fastapi.templating import Jinja2Templates

from app.services.file_service import FileService
from app.services.search_service import SearchService
from app.services.monitor_service import MonitorService
from app.services.hardware_service import HardwareService
from app.services.task_service import TaskService
from app.services.backup_service import BackupService
from app.services.service_manager import ServiceManager
from app.auth import AuthManager
from app.remote import RemoteManager

# Configuration
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORAGE_DIR = os.path.join(BASE_DIR, "nas_storage")
AUTH_DB = os.path.join(BASE_DIR, "data", "users_auth.db")
STATIC_DIR = os.path.join(BASE_DIR, "static")

templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Service Instances (initialized in main.py)
file_service: FileService = None
search_service: SearchService = None
monitor_service: MonitorService = None
hardware_service: HardwareService = None
task_service: TaskService = None
backup_service: BackupService = None
auth: AuthManager = None
remote: RemoteManager = None
service_manager: ServiceManager = None

def get_current_user(request: Request) -> dict:
    token = request.cookies.get("nas_session")
    if not token:
        raise HTTPException(status_code=401, detail="Non autorisé")
    
    session = auth.get_session(token)
    if not session:
        raise HTTPException(status_code=401, detail="Session expirée ou invalide")
    
    return session

def get_current_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in ["admin", "superadmin"]:
        raise HTTPException(status_code=403, detail="Réservé aux administrateurs")
    return user
