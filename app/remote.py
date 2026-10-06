import os
import ngrok
import threading
import time

class RemoteManager:
    def __init__(self, base_dir):
        self.base_dir = base_dir
        self.public_url = None
        self.is_running = False
        self.listener = None
        self.default_domain = "fiber-landed-deprecate.ngrok-free.dev"

    def start_tunnel(self, mode="ngrok", local_port=8000, token=None, domain=None):
        """Démarre le tunnel de manière native via le SDK Ngrok."""
        if self.is_running or self.listener:
            self.stop_tunnel()

        if not token:
            print("[REMOTE] Aucun token Ngrok fourni. Le tunnel natif nécessite une authentification.")
            return False

        effective_domain = domain.strip() if (domain and domain.strip()) else None
        domain_str = effective_domain if effective_domain else "un domaine dynamique gratuit"
        
        print(f"[REMOTE] Lancement du tunnel natif Ngrok sur {domain_str}...")
        
        try:
            # On lance le tunnel dans un thread séparé car il est bloquant dans certaines versions du SDK
            # ou on utilise l'API asynchrone si possible. Ici on va utiliser le thread de contrôle.
            def _connect():
                retries = 6
                while retries > 0:
                    try:
                        # Configuration globale du token
                        kwargs = {
                            "authtoken": token,
                            "schemes": ["https"]
                        }
                        if effective_domain:
                            kwargs["domain"] = effective_domain
                        
                        self.listener = ngrok.forward(local_port, **kwargs)
                        self.public_url = self.listener.url()
                        self.is_running = True
                        print(f"[REMOTE] Tunnel établi avec succès : {self.public_url}")
                        
                        # Garder le tunnel ouvert jusqu'à l'arrêt
                        while self.is_running:
                            time.sleep(1)
                        break
                    except Exception as e:
                        error_msg = str(e)
                        retries -= 1
                        
                        if "ERR_NGROK_334" in error_msg or "already online" in error_msg:
                            print(f"[REMOTE] Erreur : Le domaine {domain_str} est déjà utilisé par une autre session.")
                            print("[REMOTE] Cela arrive souvent si l'application a été redémarrée trop vite ou si une autre instance tourne.")
                            print("[REMOTE] Attente de la libération du domaine par Ngrok...")
                        else:
                            print(f"[REMOTE] Échec du tunnel Ngrok (Attente réseau probable) : {e}")
                        
                        if retries > 0:
                            wait_time = 15 if "ERR_NGROK_334" in error_msg else 10
                            print(f"[REMOTE] Nouvelle tentative dans {wait_time}s... ({retries} essais restants)")
                            time.sleep(wait_time)
                        else:
                            print("[REMOTE] Abandon du tunnel après plusieurs tentatives.")
                            self.is_running = False
                            self.public_url = None


            thread = threading.Thread(target=_connect, daemon=True)
            thread.start()
            
            # Attendre un peu pour que l'URL soit générée
            for _ in range(10):
                if self.public_url: break
                time.sleep(0.5)
                
            return True
        except Exception as e:
            print(f"[REMOTE] Erreur critique RemoteManager : {e}")
            return False

    def stop_tunnel(self):
        """Arrête proprement le tunnel Ngrok."""
        if self.is_running:
            print("[REMOTE] Fermeture du tunnel Ngrok...")
            self.is_running = False
            try:
                ngrok.disconnect()
            except:
                pass
            self.listener = None
            self.public_url = None
