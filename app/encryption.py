import os
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
import secrets

class AESCipherManager:
    MAGIC = b"GNVAULT1"

    def __init__(self, secret_key: str):
        # Derive a 256-bit key
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"gravitynas_salt",
            iterations=100000,
            backend=default_backend()
        )
        self.key = kdf.derive(secret_key.encode())

    def encrypt_file(self, file_path: str, chunk_size=64*1024):
        """Encrypts a file in place using AES-256-GCM"""
        if not os.path.exists(file_path):
            return False

        iv = secrets.token_bytes(12)
        encryptor = Cipher(
            algorithms.AES(self.key),
            modes.GCM(iv),
            backend=default_backend()
        ).encryptor()

        temp_path = file_path + ".enc"
        try:
            with open(file_path, "rb") as f_in, open(temp_path, "wb") as f_out:
                f_out.write(self.MAGIC + iv)
                while chunk := f_in.read(chunk_size):
                    f_out.write(encryptor.update(chunk))
                f_out.write(encryptor.finalize())
                f_out.write(encryptor.tag) # Append GCM tag
            os.replace(temp_path, file_path)
            return True
        except Exception as e:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise e

    def decrypt_file(self, file_path: str, chunk_size=64*1024):
        """Decrypts a file in place using AES-256-GCM"""
        if not os.path.exists(file_path):
            return False

        temp_path = file_path + ".dec"
        try:
            with open(file_path, "rb") as f_in:
                magic = f_in.read(len(self.MAGIC))
                if magic != self.MAGIC:
                    raise ValueError("Unsupported encrypted file format")
                iv = f_in.read(12)
                f_in.seek(0, 2)
                file_size = f_in.tell()
                f_in.seek(12)

                data_size = file_size - len(self.MAGIC) - 12 - 16
                if data_size < 0:
                    raise ValueError("File is too small to be encrypted")
                
                # read tag from the end
                f_in.seek(file_size - 16)
                tag = f_in.read(16)
                
                f_in.seek(len(self.MAGIC) + 12)
                
                decryptor = Cipher(
                    algorithms.AES(self.key),
                    modes.GCM(iv, tag),
                    backend=default_backend()
                ).decryptor()

                with open(temp_path, "wb") as f_out:
                    bytes_read = 0
                    while bytes_read < data_size:
                        read_size = min(chunk_size, data_size - bytes_read)
                        chunk = f_in.read(read_size)
                        f_out.write(decryptor.update(chunk))
                        bytes_read += len(chunk)
                    f_out.write(decryptor.finalize())
            os.replace(temp_path, file_path)
            return True
        except Exception as e:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise e
