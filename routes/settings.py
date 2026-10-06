import os
import zipfile
from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from app.dependencies import auth, file_service, monitor_service, backup_service, remote, service_manager, get_current_user, get_current_admin

router = APIRouter()

@router.post("/settings/profile")
async def update_profile(request: Request, user: dict = Depends(get_current_user)):
    form = await request.form()
    avatar = form.get("avatarUrl")
    wallpaper = form.get("wallpaperUrl")
    theme = form.get("theme")
    
    await run_in_threadpool(
        auth.update_user_preferences, 
        user["username"], 
        avatar=avatar if avatar is not None else None,
        wallpaper=wallpaper if wallpaper is not None else None,
        theme=theme if theme is not None else None
    )
    
    await run_in_threadpool(
        auth.update_session_data,
        user["username"],
        theme=theme,
        avatar=avatar,
        wallpaper=wallpaper
    )
    return JSONResponse({"status": "success", "message": "Profil mis à jour"})

@router.post("/settings/mfa/setup")
def mfa_setup(user: dict = Depends(get_current_user)):
    import pyotp
    secret = pyotp.random_base32()
    auth.enable_mfa(user["username"], secret)
    uri = pyotp.totp.TOTP(secret).provisioning_uri(name=user["username"], issuer_name="GravityNAS")
    return {"status": "ok", "secret": secret, "uri": uri}

@router.post("/settings/mfa/confirm")
def mfa_confirm(code: str = Form(...), user: dict = Depends(get_current_user)):
    if auth.confirm_mfa(user["username"], code.strip()):
        return {"status": "ok"}
    raise HTTPException(status_code=400, detail="Code MFA invalide")

@router.post("/settings/system")
def update_system_settings(
    admin_user: dict = Depends(get_current_admin)
):
    # Les réglages SMTP sont maintenant gérés par le Cloud Relay
    return JSONResponse({"status": "success"})

@router.post("/settings/services")
def toggle_service(
    name: str = Form(...),
    enabled: bool = Form(...),
    admin_user: dict = Depends(get_current_admin)
):
    if service_manager.toggle_service(name, enabled):
        return JSONResponse({"status": "success", "message": f"Service {name} {'activé' if enabled else 'désactivé'}"})
    raise HTTPException(status_code=500, detail="Échec de l'action sur le service")

@router.post("/settings/remote")
def update_remote_settings(
    enabled:  str = Form("0"),
    token:    str = Form(""),
    domain:   str = Form(""),
    admin_user: dict = Depends(get_current_admin)
):
    auth.set_system_setting("remote_enabled", enabled)
    auth.set_system_setting("remote_token", token.strip())
    auth.set_system_setting("remote_domain", domain.strip())
    if enabled == "1":
        remote.start_tunnel(mode="ngrok", local_port=int(os.environ.get("NAS_PORT", "8000")),
                            token=token.strip() or None,
                            domain=domain.strip() or None)
    else:
        remote.stop_tunnel()
    return JSONResponse({"status": "success"})

# --- Sauvegarde ---
@router.get("/api/backups")
def list_backups(user: dict = Depends(get_current_admin)):
    return backup_service.list_backups()

@router.post("/api/backups/create")
def create_backup(include_storage: bool = Form(False), user: dict = Depends(get_current_admin)):
    try:
        backup_service.create_backup(include_storage=include_storage)
        return JSONResponse({"status": "success", "message": "Sauvegarde créée avec succès"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/backups/{filename}/restore")
def restore_backup(filename: str, restore_storage: bool = Form(False), user: dict = Depends(get_current_admin)):
    try:
        backup_service.restore_backup(filename, restore_storage=restore_storage)
        return JSONResponse({"status": "success", "message": "Restauration préparée dans users_auth.db.restore"})
    except (ValueError, OSError, zipfile.BadZipFile) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@router.delete("/api/backups/{filename}")
def delete_backup(filename: str, user: dict = Depends(get_current_admin)):
    backup_service.delete_backup(filename)
    return JSONResponse({"status": "success"})

@router.get("/api/stats/realtime")
def get_realtime_stats(user: dict = Depends(get_current_user)):
    return monitor_service.get_stats()

@router.get("/api/nas-picker")
def nas_picker(path: str = "", user: dict = Depends(get_current_user)):
    items = file_service.list_files(path, user["username"])
    return [{"name": i["name"], "path": i["relative_path"], "is_dir": i["is_dir"]} for i in items]

@router.post("/file/meta")
def update_file_meta(
    filepath: str = Form(...),
    meta_key: str = Form(...),
    meta_value: str = Form(...),
    user: dict = Depends(get_current_user)
):
    auth.set_file_meta(user["username"], filepath, meta_key, meta_value)
    return JSONResponse({"status": "success"})
