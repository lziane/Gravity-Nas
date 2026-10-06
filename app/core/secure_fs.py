import os
import logging
from typing import List

logger = logging.getLogger("GravityNAS.SecureFS")

class SecureFileSystem:
    """
    Gatekeeper for all disk I/O operations.
    Enforces path traversal protection and standardizes path handling.
    """
    def __init__(self, base_path: str):
        self.base_path = os.path.realpath(base_path)
        os.makedirs(self.base_path, exist_ok=True)

    def get_abs_path(self, rel_path: str, user_storage: str = None) -> str:
        """
        Converts a relative path to a safe absolute path.
        If user_storage is provided, it ensures the path is within that storage.
        """
        base = user_storage if user_storage else self.base_path
        # Normalize path: remove leading slashes, replace backslashes, handle ".."
        clean_rel = rel_path.lstrip("/").replace("\\", "/")

        # Check every existing component, not only the final target. A symlinked
        # directory could otherwise redirect a valid-looking child path.
        base_real = os.path.realpath(base)
        current = base_real
        for component in clean_rel.split("/"):
            if not component or component == ".":
                continue
            current = os.path.join(current, component)
            if os.path.lexists(current) and os.path.islink(current):
                logger.warning(f"Security Policy: Symlink detected and blocked: {current}")
                raise PermissionError("Access Denied: Symlinks are restricted for security.")
        
        # Resolve any symlinks to find the TRUE destination
        target = os.path.realpath(os.path.join(base, clean_rel))
        
        if not self.is_safe(target, base):
            logger.warning(f"Security Alert: Blocked access attempt to {target}")
            raise PermissionError("Access Denied: Path outside authorized directory.")
        
        # Additional check: Prevent symlink creation/usage if not explicitly allowed
        if os.path.islink(target):
             logger.warning(f"Security Policy: Symlink detected and blocked: {target}")
             raise PermissionError("Access Denied: Symlinks are restricted for security.")

        return target

    def is_safe(self, target: str, base: str) -> bool:
        """Robust check for path traversal."""
        try:
            return os.path.commonpath([os.path.realpath(base), os.path.realpath(target)]) == os.path.realpath(base)
        except (ValueError, OSError):
            return False

    def list_dir_safe(self, rel_path: str, user_storage: str) -> List[os.DirEntry]:
        """Safely list a directory."""
        abs_path = self.get_abs_path(rel_path, user_storage)
        if not os.path.isdir(abs_path):
            return []
        return list(os.scandir(abs_path))

    def sanitize_filename(self, filename: str) -> str:
        """Removes dangerous characters from a filename."""
        # Basic sanitization, could be expanded with pathvalidate
        return "".join(c for c in filename if c.isalnum() or c in "._- ").strip()
