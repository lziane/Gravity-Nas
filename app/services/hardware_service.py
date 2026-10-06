import logging
import os
import socket

try:
    from gpiozero import PWMOutputDevice # type: ignore
    HAS_GPIO = os.path.exists("/proc/device-tree/model")
except ImportError:
    HAS_GPIO = False

try:
    from zeroconf import ServiceInfo, Zeroconf # type: ignore
    HAS_ZEROCONF = True
except ImportError:
    HAS_ZEROCONF = False

logger = logging.getLogger("GravityNAS.HardwareService")

class HardwareService:
    def __init__(self, fan_pin: int = 18):
        self.fan_pin = fan_pin
        self.fan = None
        self.zeroconf = None
        self._init_fan()

    def _init_fan(self):
        if HAS_GPIO:
            try:
                self.fan = PWMOutputDevice(self.fan_pin)
            except Exception as e:
                logger.warning(f"GPIO Init failed: {e}")

    def update_fan_speed(self, temp_c: float):
        if not self.fan: return
        
        if temp_c < 45: speed = 0.3
        elif temp_c > 62: speed = 1.0
        else: speed = 0.3 + (0.7 * (temp_c - 45) / (62 - 45))
        
        try:
            self.fan.value = round(speed, 2)
        except Exception as e:
            logger.error(f"Fan speed update failed: {e}")

    def start_mdns(self, port: int = 8000):
        if not HAS_ZEROCONF: return
        try:
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
            self.zeroconf = Zeroconf()
            info = ServiceInfo(
                "_http._tcp.local.",
                f"GravityNAS-{hostname}._http._tcp.local.",
                addresses=[socket.inet_aton(local_ip)],
                port=port,
                properties={"path": "/"}
            )
            self.zeroconf.register_service(info)
            logger.info(f"mDNS registered: {hostname}.local")
        except Exception as e:
            logger.warning(f"mDNS registration unavailable: {e}")
            if self.zeroconf:
                self.zeroconf.close()
                self.zeroconf = None

    def stop_mdns(self):
        if self.zeroconf:
            try:
                self.zeroconf.unregister_all_services()
            except Exception as e:
                logger.warning(f"mDNS cleanup failed: {e}")
            finally:
                self.zeroconf.close()
                self.zeroconf = None
