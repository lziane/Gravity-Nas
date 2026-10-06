# launcher_mac.py
import rumps # type: ignore
import threading
import uvicorn
import webview # type: ignore
import sys
import os
import asyncio

# Assure que le dossier parent est dans le path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from main import app

class GravityNASMenuBar(rumps.App):
    def __init__(self):
        # Utilise l'icône si dispo, sinon texte
        logo_path = "static/logo.png"
        super(GravityNASMenuBar, self).__init__("Gravity", icon=logo_path if os.path.exists(logo_path) else None)
        self.menu = ["Ouvrir l'interface", "Redémarrer le serveur", "Quitter"]

    @rumps.clicked("Ouvrir l'interface")
    def open_ui(self, _):
        # Ouvre la fenêtre webview
        webview.create_window('GravityNAS', 'http://127.0.0.1:8000', width=1200, height=800)
        webview.start()

    @rumps.clicked("Quitter")
    def quit_app(self, _):
        rumps.quit_application()

def start_server():
    config = uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="error")
    server = uvicorn.Server(config)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(server.serve())

if __name__ == "__main__":
    # Lancement du serveur
    threading.Thread(target=start_server, daemon=True).start()
    
    # Lancement de l'icône de barre de menu
    GravityNASMenuBar().run()
