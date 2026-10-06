import json
import os
import zipfile
import tempfile
import mimetypes
import asyncio
import shutil
from typing import List, Annotated, Optional
from fastapi import APIRouter, File, UploadFile, HTTPException, Form, Depends, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.concurrency import run_in_threadpool
from starlette.background import BackgroundTask

from app.core.responses import ApiResponse
from app.dependencies import file_service, search_service, task_service, auth, get_current_user

router = APIRouter()

# Refactored Lock Management with auto-cleanup
class LockManager:
    def __init__(self):
        self._locks = {}
        self._last_access = {}

    def get_lock(self, key: str):
        self._last_access[key] = asyncio.get_event_loop().time()
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    def prune(self, max_age: int = 3600):
        now = asyncio.get_event_loop().time()
        to_delete = [k for k, t in self._last_access.items() if now - t > max_age]
        for k in to_delete:
            del self._locks[k]
            del self._last_access[k]

upload_locks = LockManager()

_MIME_FALLBACK = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
    ".mp4": "video/mp4", ".webm": "video/webm", ".mkv": "video/x-matroska",
    ".pdf": "application/pdf", ".txt": "text/plain", ".md": "text/markdown",
    ".csv": "text/csv", ".json": "application/json", ".xml": "application/xml",
    ".html": "text/html", ".css": "text/css", ".js": "text/javascript",
    ".py": "text/x-python", ".yml": "text/yaml", ".yaml": "text/yaml",
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg", ".m4a": "audio/mp4", ".flac": "audio/flac",
    ".avif": "image/avif", ".tif": "image/tiff", ".tiff": "image/tiff",
}
MAX_UPLOAD_BYTES = int(os.environ.get("NAS_MAX_UPLOAD_BYTES", str(10 * 1024**3)))

@router.get("/api/files")
def get_files_api(path: str = "", user: dict = Depends(get_current_user)):
    normalized_path = path.replace("\\", "/")
    path_parts = normalized_path.split("/")
    if os.path.isabs(path) or any(part == ".." for part in path_parts):
        return ApiResponse.error("Chemin de dossier invalide", code="INVALID_PATH", status_code=400)

    try:
        files = file_service.list_files(path, user["username"])
        
        # Calcul des breadcrumbs pour le frontend
        breadcrumbs = []
        if path:
            parts = path.strip("/").split("/")
            curr = ""
            for p in parts:
                curr = f"{curr}/{p}" if curr else p
                breadcrumbs.append({"name": p, "path": curr})
        
        return ApiResponse.success({
            "path": path, 
            "items": files,
            "breadcrumbs": breadcrumbs
        })
    except PermissionError as e:
        return ApiResponse.forbidden(str(e))

@router.post("/upload")
async def upload_files(
    files:     Annotated[List[UploadFile], File(...)],
    path:      Annotated[str, Form()] = "",
    fullPaths: Annotated[Optional[List[str]], Form()] = None,
    user:      dict = Depends(get_current_user)
):
    user_storage = file_service.get_user_storage(user["username"])
    
    async with upload_locks.get_lock(user["username"]):
        user_info = await run_in_threadpool(auth.get_user_info, user["username"])
        quota_gb = user_info.get("quota_gb", 0)
        if quota_gb > 0:
            current_usage = await run_in_threadpool(file_service.get_user_usage, user["username"])
            upload_size = sum([f.size for f in files if f.size])
            if current_usage + upload_size > (quota_gb * 1024**3):
                raise HTTPException(status_code=400, detail=f"Quota dépassé ({quota_gb}GB)")

        def _save_file_sync(file_obj, target_p):
            os.makedirs(os.path.dirname(target_p), exist_ok=True)
            temp_path = f"{target_p}.uploading"
            bytes_written = 0
            try:
                with open(temp_path, "wb") as buf:
                    while chunk := file_obj.file.read(1024 * 1024):
                        bytes_written += len(chunk)
                        if bytes_written > MAX_UPLOAD_BYTES:
                            raise ValueError("Fichier trop volumineux")
                        buf.write(chunk)
                    buf.flush()
                    os.fsync(buf.fileno())
                os.replace(temp_path, target_p)
                return bytes_written
            except Exception:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                raise

        for i, file in enumerate(files):
            rel_name = (fullPaths[i] if (fullPaths and i < len(fullPaths) and fullPaths[i]) 
                        else (file.filename or "upload"))
            
            # Use FileService to get safe absolute path
            file_service.assert_path_unlocked(os.path.join(path, rel_name), user["username"])
            target_path = file_service.get_abs_path(os.path.join(path, rel_name), user_storage)
            
            try:
                try:
                    await run_in_threadpool(_save_file_sync, file, target_path)
                except ValueError as exc:
                    raise HTTPException(status_code=413, detail=str(exc))
                
                # Async Indexing via TaskQueue
                rel_p = os.path.relpath(target_path, user_storage).replace("\\", "/")
                await task_service.enqueue(search_service.index_file, target_path, rel_p, user["username"])
            finally:
                await file.close()

    return ApiResponse.success(message="Upload terminé")

@router.get("/download/{filename:path}")
def download_file(filename: str, user: dict = Depends(get_current_user)):
    user_storage = file_service.get_user_storage(user["username"])
    try:
        file_service.assert_path_unlocked(filename, user["username"])
        file_path = file_service.get_abs_path(filename, user_storage)
        if not os.path.isfile(file_path):
            raise HTTPException(status_code=404, detail="Fichier introuvable")
        return FileResponse(file_path, filename=os.path.basename(file_path))
    except PermissionError:
        raise HTTPException(status_code=403, detail="Accès refusé")

@router.post("/share/external")
def create_external_share(request: Request, filepath: str = Form(...), user: dict = Depends(get_current_user)):
    user_storage = file_service.get_user_storage(user["username"])
    try:
        file_path = file_service.get_abs_path(filepath, user_storage)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Accès refusé")
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Fichier introuvable")

    token = auth.create_share_token(user["username"], filepath)
    return {"link": str(request.base_url).rstrip("/") + f"/share/{token}"}

@router.get("/share/{token}")
def download_shared_file(token: str):
    share = auth.get_share_info(token)
    if not share:
        raise HTTPException(status_code=404, detail="Lien invalide ou expiré")

    user_storage = file_service.get_user_storage(share["username"])
    try:
        file_service.assert_path_unlocked(share["filepath"], share["username"])
        file_path = file_service.get_abs_path(share["filepath"], user_storage)
    except PermissionError:
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    media_type = _MIME_FALLBACK.get(os.path.splitext(file_path)[1].lower()) or "application/octet-stream"
    return FileResponse(file_path, filename=os.path.basename(file_path), media_type=media_type)

@router.post("/download/multi")
async def download_multi(paths: str = Form(...), user: dict = Depends(get_current_user)):
    paths_list = json.loads(paths)
    user_storage = file_service.get_user_storage(user["username"])
    fd, temp_path = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    
    def _create_zip_sync():
        with zipfile.ZipFile(temp_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for p in paths_list:
                try:
                    file_service.assert_path_unlocked(p, user["username"])
                    abs_p = file_service.get_abs_path(p, user_storage)
                    if not os.path.exists(abs_p): continue
                    if os.path.isdir(abs_p):
                        for root, _, files in os.walk(abs_p):
                            for file in files:
                                file_abs = os.path.join(root, file)
                                if os.path.islink(file_abs):
                                    continue
                                arcname = os.path.relpath(file_abs, os.path.dirname(abs_p))
                                zipf.write(file_abs, arcname)
                    else:
                        if os.path.islink(abs_p):
                            continue
                        zipf.write(abs_p, os.path.basename(abs_p))
                except PermissionError: continue

    await run_in_threadpool(_create_zip_sync)
    return FileResponse(temp_path, filename="GravityNAS_Archive.zip", background=BackgroundTask(lambda: os.remove(temp_path)))

@router.get("/api/thumbnail/{filepath:path}")
def get_thumbnail(filepath: str, user: dict = Depends(get_current_user)):
    try:
        file_service.assert_path_unlocked(filepath, user["username"])
    except PermissionError:
        raise HTTPException(status_code=403, detail="Coffre-fort verrouillé")
    thumb_path = file_service.get_thumbnail(filepath, user["username"])
    if thumb_path: return FileResponse(thumb_path, media_type="image/webp")
    # Fallback to preview if no thumbnail
    return preview_file(filepath, user)

@router.get("/preview/{filename:path}")
def preview_file(filename: str, user: dict = Depends(get_current_user)):
    user_storage = file_service.get_user_storage(user["username"])
    try:
        file_service.assert_path_unlocked(filename, user["username"])
    except PermissionError:
        raise HTTPException(status_code=403, detail="Coffre-fort verrouillé")
    file_path = file_service.get_abs_path(filename, user_storage)
    if not os.path.isfile(file_path): raise HTTPException(status_code=404)
    
    ext = os.path.splitext(filename)[1].lower()
    media_type = _MIME_FALLBACK.get(ext) or mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    headers = {
        "Content-Security-Policy": "default-src 'none'; sandbox allow-same-origin",
        "X-Content-Type-Options": "nosniff",
        "Accept-Ranges": "bytes",
    }
    return FileResponse(file_path, media_type=media_type, content_disposition_type="inline", headers=headers)

@router.get("/api/search")
def api_search(q: str = "", user: dict = Depends(get_current_user)):
    return search_service.search(q, user["username"]) if q else []

@router.post("/mkdir")
async def create_folder(folder_name: str = Form(...), path: str = Form(""), user: dict = Depends(get_current_user)):
    user_storage = file_service.get_user_storage(user["username"])
    file_service.assert_path_unlocked(path, user["username"])
    target = file_service.get_abs_path(os.path.join(path, folder_name), user_storage)
    if os.path.exists(target): raise HTTPException(status_code=400, detail="Existe déjà")
    await run_in_threadpool(os.makedirs, target)
    # Async Indexing
    await task_service.enqueue(search_service.index_file, target, os.path.join(path, folder_name), user["username"])
    return JSONResponse({"status": "success"})

@router.post("/delete/batch")
async def delete_batch(paths: str = Form(...), user: dict = Depends(get_current_user)):
    paths_list = json.loads(paths)
    success_count = 0
    for p in paths_list:
        try:
            file_service.assert_path_unlocked(p, user["username"])
        except PermissionError:
            continue
        if await run_in_threadpool(file_service.delete_item, p, user["username"]):
            await run_in_threadpool(auth.clear_file_meta, user["username"], p)
            await run_in_threadpool(search_service.remove_file, p, user["username"])
            success_count += 1
    return {"status": "success", "deleted": success_count}

@router.post("/trash/empty")
async def empty_trash(user: dict = Depends(get_current_user)):
    user_storage = file_service.get_user_storage(user["username"])
    trash_dir = os.path.join(user_storage, ".Corbeille")
    if os.path.exists(trash_dir):
        await run_in_threadpool(shutil.rmtree, trash_dir)
        await run_in_threadpool(os.makedirs, trash_dir)
    return {"status": "success"}

@router.post("/trash/restore/batch")
async def restore_batch(paths: str = Form(...), user: dict = Depends(get_current_user)):
    try:
        paths_list = json.loads(paths)
        if not isinstance(paths_list, list):
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="Liste de fichiers invalide")

    restored = []
    for path in paths_list:
        try:
            restored_path = await run_in_threadpool(file_service.restore_item, path, user["username"])
            restored.append(restored_path)
        except (FileNotFoundError, FileExistsError, PermissionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc))
    return {"status": "success", "restored": restored}

@router.post("/rename")
async def rename_file(old_name: str = Form(...), new_name: str = Form(...), user: dict = Depends(get_current_user)):
    user_storage = file_service.get_user_storage(user["username"])
    try:
        new_path = await run_in_threadpool(file_service.rename_item, old_name, new_name, user["username"])
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (ValueError, FileExistsError, PermissionError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await run_in_threadpool(search_service.remove_file, old_name, user["username"])
    await task_service.enqueue(search_service.index_user_files, user_storage, user["username"])
    return {"status": "success", "path": new_path}

@router.post("/move")
async def move_file(filepath: str = Form(...), destination: str = Form(""), user: dict = Depends(get_current_user)):
    user_storage = file_service.get_user_storage(user["username"])
    try:
        new_path = await run_in_threadpool(file_service.move_item, filepath, destination, user["username"])
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except NotADirectoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except (ValueError, FileExistsError, PermissionError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    await run_in_threadpool(search_service.remove_file, filepath, user["username"])
    await task_service.enqueue(search_service.index_user_files, user_storage, user["username"])
    return {"status": "success", "path": new_path}

@router.post("/move/batch")
async def move_batch(paths: str = Form(...), destination: str = Form(""), user: dict = Depends(get_current_user)):
    try:
        paths_list = json.loads(paths)
        if not isinstance(paths_list, list) or not paths_list:
            raise ValueError("Liste de fichiers invalide")
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    moved = []
    for filepath in paths_list:
        try:
            new_path = await run_in_threadpool(file_service.move_item, filepath, destination, user["username"])
        except (FileNotFoundError, NotADirectoryError, ValueError, FileExistsError, PermissionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        await run_in_threadpool(search_service.remove_file, filepath, user["username"])
        moved.append(new_path)
    user_storage = file_service.get_user_storage(user["username"])
    await task_service.enqueue(search_service.index_user_files, user_storage, user["username"])
    return {"status": "success", "moved": moved}

@router.post("/vault/create")
def vault_create(filepath: str = Form(...), password: str = Form(...), user: dict = Depends(get_current_user)):
    try:
        if file_service.create_vault(filepath, password, user["username"]):
            return {"status": "success"}
    except (PermissionError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    raise HTTPException(status_code=400, detail="Création du coffre-fort impossible")

@router.post("/vault/unlock")
def vault_unlock(filepath: str = Form(...), password: str = Form(...), user: dict = Depends(get_current_user)):
    try:
        if file_service.unlock_vault(filepath, password, user["username"]):
            return {"status": "success"}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    raise HTTPException(status_code=401, detail="Mauvais mot de passe")

@router.post("/vault/lock")
def vault_lock(filepath: str = Form(...), password: str = Form(...), user: dict = Depends(get_current_user)):
    try:
        if file_service.lock_vault(filepath, password, user["username"]):
            return {"status": "success"}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    raise HTTPException(status_code=401, detail="Mauvais mot de passe ou coffre déjà verrouillé")
