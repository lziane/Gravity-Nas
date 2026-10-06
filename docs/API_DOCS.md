# 📑 API Reference v1.0

Toutes les réponses suivent la structure standard : `{"status": "success", "data": {...}, "message": "..."}`.

### 🔐 Authentification
`POST /login`
*   **Body** : `username`, `password`
*   **Retour** : Cookie `nas_session` (Hardened: HttpOnly, Secure, SameSite=Lax)

### 📁 Gestion de fichiers
`GET /api/files?path=...`
*   **Description** : Liste les fichiers du répertoire.
*   **Success** : `{"status": "success", "data": {"path": "...", "items": [...]}}`

`POST /upload`
*   **Content-Type** : `multipart/form-data`
*   **Description** : Envoie un ou plusieurs fichiers. L'indexation OCR est lancée en arrière-plan automatiquement via le TaskQueue.

`POST /rename`
*   **Body** : `old_name`, `new_name`
*   **Description** : Renomme un élément dans son dossier parent. Les collisions et les noms avec séparateurs sont refusés.

`POST /move` ou `POST /move/batch`
*   **Body** : `filepath`, `destination` ou `paths` (JSON), `destination`
*   **Description** : Déplace un ou plusieurs éléments vers un dossier existant. Les collisions, traversals et déplacements récursifs sont refusés.

### 🔍 Recherche
`GET /api/search?q=query`
*   **Description** : Recherche plein texte dans les noms de fichiers et le contenu extrait par OCR.
*   **Success** : Liste des fichiers correspondants.
