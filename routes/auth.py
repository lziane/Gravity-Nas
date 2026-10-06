import secrets
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from app.dependencies import auth, templates, get_current_user
from app.core.config import get_client_ip

router = APIRouter()

SESSION_TTL = 3600 * 24 * 7 # Increased to 1 week for better UX

def set_harden_cookie(response, token, secure=True):
    response.set_cookie(
        "nas_session", 
        token, 
        httponly=True, 
        secure=secure, 
        samesite="lax", 
        max_age=SESSION_TTL
    )

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {})

@router.post("/login")
def process_login(request: Request, username: str = Form(...), password: str = Form(...)):
    user_data = auth.authenticate(username, password)
    client_ip = get_client_ip(request)
    
    if user_data:
        auth.clear_failed_login(client_ip)
        if user_data.get("mfa_enabled"):
            token = secrets.token_hex(32)
            auth.create_session(token, username, 300) # 5 min for MFA
            return RedirectResponse(url=f"/login/mfa?t={token}", status_code=303)

        token = secrets.token_hex(64)
        auth.create_session(token, username, SESSION_TTL)
        response = RedirectResponse(url="/", status_code=303)
        is_secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        set_harden_cookie(response, token, secure=is_secure)
        return response
    
    auth.track_failed_login(client_ip)
    return RedirectResponse(url="/login?error=1", status_code=303)

@router.post("/logout")
def logout(request: Request):
    token = request.cookies.get("nas_session")
    if token:
        auth.delete_session(token)
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("nas_session")
    return response

@router.get("/login/mfa", response_class=HTMLResponse)
def mfa_page(request: Request, t: str):
    return templates.TemplateResponse(request, "login_mfa.html", {"token": t})

@router.post("/login/mfa")
def process_mfa(request: Request, t: str = Form(...), code: str = Form(...)):
    import pyotp
    session = auth.get_session(t)
    if not session: return RedirectResponse(url="/login")
    
    user_info = auth.get_user_info(session["username"])
    totp = pyotp.TOTP(user_info["mfa_secret"])
    
    client_ip = get_client_ip(request)
    
    if totp.verify(code):
        auth.delete_session(t)
        new_token = secrets.token_hex(64)
        auth.create_session(new_token, session["username"], SESSION_TTL)
        response = RedirectResponse(url="/", status_code=303)
        is_secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        set_harden_cookie(response, new_token, secure=is_secure)
        return response
            
    auth.track_failed_login(client_ip)
    return RedirectResponse(url=f"/login/mfa?t={t}&error=1", status_code=303)

@router.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_page(request: Request):
    return templates.TemplateResponse(request, "forgot_password.html", {})
