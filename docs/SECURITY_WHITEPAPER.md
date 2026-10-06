# 🛡 Whitepaper Sécurité : Comment nous protégeons vos données

La confiance est le pilier de GravityNAS. Voici comment nous garantissons l'intégrité et la confidentialité de vos fichiers.

### 1. Authentification Robuste
Nous n'utilisons jamais de stockage de mot de passe en clair. GravityNAS utilise **scrypt** avec un coût de calcul élevé pour rendre les attaques par brute-force localement impossibles. 

### 2. Isolation Multi-Utilisateurs (SecureFileSystem)
Chaque utilisateur est enfermé dans une "jail" virtuelle. Notre couche logicielle `SecureFileSystem` vérifie chaque accès au disque via une résolution de chemin réel (`realpath`). 
*   **Protection Path Traversal** : Impossible de remonter dans l'arborescence via `../`.
*   **Restriction Symlinks** : Les liens symboliques sont bloqués pour éviter les fuites de données système vers l'interface utilisateur.

### 3. Protection des Données Sensibles
Les informations d'identité (comme les emails) sont chiffrées en base de données via **AES-256 (Fernet)**. Les "Vaults" (coffres-forts) utilisent un dérivé de clé unique pour garantir que même un administrateur système ne peut pas voir le contenu de vos dossiers sécurisés sans votre mot de passe.

### 4. Résilience Matérielle
Sur Raspberry Pi, les coupures de courant sont fréquentes. GravityNAS utilise SQLite en mode **WAL (Write-Ahead Logging)** avec une synchronisation `EXTRA` pour garantir qu'aucune transaction n'est perdue et que la base de données ne soit jamais corrompue au redémarrage.
