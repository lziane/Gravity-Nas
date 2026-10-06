// ══════════════════════════════════════════════════
// NAS FILE PICKER (Explorateur intégré pour Paramètres)
// ══════════════════════════════════════════════════

let nasPickerTargetInputId = null;
let currentNasPickerPath = '';
let nasPickerMode = 'asset';

/**
 * Ouvre l'explorateur NAS dans un modal
 * @param {string} targetInputId ID de l'input texte à remplir (ex: 'avatarUrlInput')
 */
function openNasPicker(targetInputId) {
    nasPickerMode = 'asset';
    document.getElementById('nasPickerChooseFolder')?.classList.add('hidden');
    nasPickerTargetInputId = targetInputId;
    currentNasPickerPath = '';
    
    const modal = document.getElementById('nasPickerModal');
    modal.classList.remove('hidden');
    setTimeout(() => modal.classList.add('active'), 10);
    
    loadNasPickerPath(currentNasPickerPath);
}

function openMovePicker() {
    nasPickerTargetInputId = 'moveInput';
    nasPickerMode = 'folder';
    document.getElementById('nasPickerChooseFolder')?.classList.remove('hidden');
    currentNasPickerPath = '';
    const modal = document.getElementById('nasPickerModal');
    modal.classList.remove('hidden');
    setTimeout(() => modal.classList.add('active'), 10);
    loadNasPickerPath('');
}

function closeNasPicker() {
    const modal = document.getElementById('nasPickerModal');
    modal.classList.remove('active');
    setTimeout(() => modal.classList.add('hidden'), 300);
}

async function loadNasPickerPath(path) {
    currentNasPickerPath = path;
    const grid = document.getElementById('nasPickerGrid');
    const pathSpan = document.getElementById('nasPickerPath');
    
    pathSpan.textContent = '/' + path;
    grid.innerHTML = '<div class="col-span-full flex justify-center py-8"><i class="fas fa-spinner fa-spin text-2xl text-indigo-500"></i></div>';
    
    try {
        const res = await fetch('/api/files?path=' + encodeURIComponent(path));
        const payload = await res.json();
        const data = payload.data || payload;
        
        grid.innerHTML = '';
        
        if (data.items.length === 0) {
            grid.innerHTML = '<div class="col-span-full text-center py-8 text-[12px] opacity-60">Dossier vide</div>';
            return;
        }

        data.items.forEach(item => {
            const el = document.createElement('div');
            el.className = 'flex items-center p-3 rounded-xl cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors border border-transparent hover:border-gray-200 dark:hover:border-gray-700';
            
            // Icon
            const iconDiv = document.createElement('div');
            iconDiv.className = 'w-10 h-10 rounded-lg flex items-center justify-center shrink-0 mr-3';
            if (item.emoji) {
                iconDiv.innerHTML = `<span class="text-2xl">${item.emoji}</span>`;
            } else if (item.is_dir) {
                iconDiv.innerHTML = `<i class="fas fa-folder text-2xl" style="color:${item.color || '#5c9aff'}"></i>`;
            } else {
                iconDiv.innerHTML = `<i class="fas fa-image text-2xl text-gray-400"></i>`;
            }
            
            // Info
            const infoDiv = document.createElement('div');
            infoDiv.className = 'min-w-0 flex-1';
            infoDiv.innerHTML = `<div class="text-[13px] font-bold truncate">${item.name}</div>
                                 <div class="text-[11px] opacity-60">${item.is_dir ? 'Dossier' : item.size}</div>`;
            
            el.appendChild(iconDiv);
            el.appendChild(infoDiv);
            
            el.onclick = () => {
                if (nasPickerMode === 'folder') {
                    if (item.is_dir) {
                        document.getElementById(nasPickerTargetInputId).value = item.relative_path;
                        loadNasPickerPath(item.relative_path);
                    }
                    return;
                }
                if (item.is_dir) {
                    loadNasPickerPath(item.relative_path);
                } else {
                    // C'est un fichier, on vérifie l'extension
                    const validExts = ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.mp4'];
                    if (validExts.includes(item.ext)) {
                        // On injecte le chemin preview
                        const previewUrl = '/preview/' + item.relative_path;
                        document.getElementById(nasPickerTargetInputId).value = previewUrl;
                        closeNasPicker();
                    } else {
                        alert("Veuillez sélectionner un format d'image valide.");
                    }
                }
            };
            
            grid.appendChild(el);
        });

    } catch (err) {
        console.error(err);
        grid.innerHTML = '<div class="col-span-full text-center py-8 text-red-500">Erreur de chargement</div>';
    }
}

function selectCurrentMoveFolder() {
    if (nasPickerMode !== 'folder') return;
    const paths = window.pendingExplorerMove;
    if (Array.isArray(paths) && paths.length) {
        const form = new FormData();
        form.append('paths', JSON.stringify(paths));
        form.append('destination', currentNasPickerPath);
        fetch('/move/batch', { method: 'POST', body: form })
            .then((response) => {
                if (!response.ok) throw new Error('Déplacement impossible');
                window.pendingExplorerMove = null;
                closeNasPicker();
                window.navigateTo?.(window.location.href, false);
            })
            .catch((error) => window.showToast?.(error.message, 'error'));
        return;
    }
    document.getElementById(nasPickerTargetInputId).value = currentNasPickerPath;
    closeNasPicker();
}

function nasPickerUp() {
    if (!currentNasPickerPath) return;
    const parts = currentNasPickerPath.split('/').filter(Boolean);
    parts.pop();
    loadNasPickerPath(parts.join('/'));
}
