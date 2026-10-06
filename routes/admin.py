from fastapi import APIRouter, Form, Depends, HTTPException
from fastapi.responses import JSONResponse
from app.dependencies import auth, file_service, get_current_admin
import shutil

router = APIRouter(prefix="/admin", tags=["admin"])

@router.post("/create-user")
def admin_create_user(
    username: str = Form(...),
    password: str = Form(...),
    role:     str = Form("user"),
    quota_gb: int = Form(0),
    admin_user: dict = Depends(get_current_admin)
):
    if quota_gb < 0 or role not in {"user", "admin"}:
        raise HTTPException(status_code=400, detail="Rôle ou quota invalide")
    if auth.create_user(username, password, "", role):
        conn = auth._get_conn()
        conn.execute('UPDATE users SET quota_gb = ? WHERE username = ?', (quota_gb, username))
        conn.commit()
        return JSONResponse({"status": "success"})
    raise HTTPException(status_code=400, detail="Erreur création utilisateur")

@router.post("/delete-user/{target_username}")
def admin_delete_user(target_username: str, admin_user: dict = Depends(get_current_admin)):
    if auth.delete_user(target_username, admin_user["username"], admin_user["role"]):
        user_storage = file_service.get_user_storage(target_username)
        shutil.rmtree(user_storage, ignore_errors=True)
        auth.delete_user_sessions(target_username)
        return JSONResponse({"status": "success"})
    raise HTTPException(status_code=403, detail="Action non autorisée")
