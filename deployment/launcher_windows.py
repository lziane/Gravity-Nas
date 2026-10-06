# launcher_windows.py
import webview # type: ignore
import threading
import uvicorn
import sys
import os
import asyncio

# Assure que le dossier parent est dans le path pour les imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from main import app
from pystray import Icon, Menu, MenuItem # type: ignore
from PIL import Image

def start_server():
    # Configuration du serveur pour une exécution locale silencieuse
    config = uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="error")
    server = uvicorn.Server(config)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(server.serve())

def on_quit(icon, item):
    icon.stop()
    os._exit(0)

if __name__ == "__main__":
    # 1. Lancement du serveur FastAPI dans un thread séparé
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # 2. Création de l'icône Systray
    try:
        icon_img = Image.open("static/logo.png")
    except Exception:
        # Fallback si pas d'image : carré bleu
        icon_img = Image.new('RGB', (64, 64), color=(0, 120, 215))

    def show_window():
        window.restore()
        window.show()

    menu = Menu(
        MenuItem('Ouvrir GravityNAS', show_window), 
        MenuItem('Quitter', on_quit)
    )
    icon = Icon("GravityNAS", icon_img, "GravityNAS", menu)
    threading.Thread(target=icon.run, daemon=True).start()

    # 3. Fenêtre Webview native (Sert d'interface principale)
    window = webview.create_window(
        'GravityNAS', 
        'http://127.0.0.1:8000', 
        width=1200, 
        height=800,
        background_color='#1a1a1a'
    )
    
    # Lancement de la boucle d'interface
    webview.start()
