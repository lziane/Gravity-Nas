import os
import subprocess
import logging
from typing import Dict

logger = logging.getLogger("GravityNAS.ServiceManager")

class ServiceManager:
    def __init__(self):
        # Mapping des noms de services internes vers les noms systemd réels
        self.services = {
            "ftp": "vsftpd",
            "smb": "smbd",
            "plex": "plexmediaserver",
            "backup": "gravity-backup.timer"
        }
        self.is_linux = os.name != 'nt'

    def get_service_status(self, service_name: str) -> bool:
        if not self.is_linux:
            return True # Mock on Windows
            
        systemd_name = self.services.get(service_name)
        if not systemd_name: return False
        
        try:
            res = subprocess.run(["systemctl", "is-active", systemd_name], capture_output=True, text=True)
            return res.stdout.strip() == "active"
        except Exception:
            return False

    def toggle_service(self, service_name: str, enable: bool) -> bool:
        systemd_name = self.services.get(service_name)
        if not systemd_name: return False
        
        action = "start" if enable else "stop"
        logger.info(f"Action {action} on service {service_name} ({systemd_name})")
        
        if not self.is_linux:
            return True # Mock success on Windows
            
        try:
            # On utilise sudo car la gestion des services nécessite des privilèges
            subprocess.run(["sudo", "systemctl", action, systemd_name], check=True)
            # On active/désactive aussi au démarrage
            boot_action = "enable" if enable else "disable"
            subprocess.run(["sudo", "systemctl", boot_action, systemd_name], check=True)
            return True
        except Exception as e:
            logger.error(f"Failed to {action} service {service_name}: {e}")
            return False

    def get_all_statuses(self) -> Dict[str, bool]:
        return {name: self.get_service_status(name) for name in self.services}
