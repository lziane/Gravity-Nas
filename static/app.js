let isNavigating = false;
let selectedRows = new Set();
let selectionBox = null;
let startX, startY;
let lastActionTarget = null;
let healthChart = null;

function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, character => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[character]));
}

function safeColor(value, fallback) {
    const color = String(value ?? '');
    return /^#[0-9a-f]{3,8}$/i.test(color) || /^(var|rgb|hsl)a?\([\w\s%,.-]+\)$/i.test(color)
        ? color
        : fallback;
}

// ── Service Worker ──
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/static/sw.js').catch(()=>{});

// ── SPA Engine (Turbo Mode Premium) ──
let navAbortController = null;
const navCache = new Map(); // Cache des pages visitées {url: {html: string, time: number}}
const CACHE_TTL = 300000;    // 5 minutes de validité

async function navigateTo(url, pushState = true) {
    if (navAbortController) navAbortController.abort();
    
    // Déterminer si on demande des données JSON ou du HTML
    const isApiRequest = url === '/' || url.startsWith('/?path=');
    const query = url.includes('?') ? new URL(url, window.location.origin).searchParams : new URLSearchParams();
    const fetchUrl = isApiRequest ? `/api/files?path=${encodeURIComponent(query.get('path') || '')}` : url;

    // Vérification du cache
    const cached = navCache.get(url);
    if (cached && (Date.now() - cached.time < CACHE_TTL)) {
        isApiRequest ? renderFiles(cached.data, url, pushState) : renderPage(cached.html, url, pushState, true);
        return;
    }

    navAbortController = new AbortController();
    isNavigating = true;
    showLoading(true, 40);

    const mainContainer = document.getElementById('file-grid-zone');
    if (mainContainer) {
        mainContainer.classList.add('view-leaving');
        setTimeout(() => {
            if (isNavigating) showSkeletons();
        }, 150);
    }

    try {
        const response = await fetch(fetchUrl, { signal: navAbortController.signal });
        
        if (isApiRequest) {
            const data = await response.json();
            navCache.set(url, { data, time: Date.now() });
            renderFiles(data, url, pushState);
        } else {
            const html = await response.text();
            navCache.set(url, { html, time: Date.now() });
            renderPage(html, url, pushState, false);
        }

    } catch (err) {
        if (err.name !== 'AbortError') {
            console.error("Navigation error:", err);
            window.location.href = url;
        }
    } finally {
        showLoading(false);
        isNavigating = false;
    }
}

function renderFiles(payload, url, pushState) {
    if (!payload || payload.status !== 'success') {
        console.error("Invalid API response:", payload);
        return;
    }
    const data = payload.data;
    const grid = document.getElementById('fileGrid');
    const zone = document.getElementById('file-grid-zone');
    if (!grid || !zone) return;

    window.CURRENT_PATH = data.path || "";
    if (pushState) history.pushState({ url }, '', url);

    // Mettre à jour le titre et les inputs cachés
    document.title = `GravityNAS - ${data.path || 'Racine'}`;
    const pathInputs = document.querySelectorAll('input[name="path"]');
    pathInputs.forEach(input => input.value = window.CURRENT_PATH);

    // 1. Mettre à jour les miettes de pain
    updateBreadcrumbs(data.path, data.breadcrumbs || []);

    // 2. Vider et Reconstruire la liste
    grid.innerHTML = '';
    
    // Ligne ".."
    if (data.path) {
        const parts = data.path.split('/');
        parts.pop();
        const parentPath = parts.join('/');
        const upRow = document.createElement('tr');
        upRow.className = "file-row cursor-pointer border-b border-[var(--border-glass)]";
        upRow.innerHTML = `<td class="px-5 py-4 font-medium text-[var(--text-secondary)]"><div class="flex items-center"><i class="fas fa-level-up-alt mx-2 mr-6 text-[20px] text-[var(--text-muted)]"></i>..</div></td><td class="hidden sm:table-cell"></td><td class="hidden sm:table-cell"></td><td class="hidden sm:table-cell"></td><td class="hidden sm:table-cell"></td>`;
        upRow.onclick = () => navigateTo(`/?path=${parentPath}`);
        grid.appendChild(upRow);
    }

    // Fichiers et Dossiers
    if (data.items && data.items.length > 0) {
        // Cacher le message vide s'il existe
        const emptyMsg = zone.querySelector('.empty-state-container');
        if (emptyMsg) emptyMsg.remove();
        zone.querySelector('table').classList.remove('hidden');

        data.items.forEach((f, i) => {
            const row = document.createElement('tr');
            row.className = "file-row cursor-pointer border-b group transition-colors border-[var(--border-glass)]";
            row.dataset.name = f.name;
            row.dataset.path = f.relative_path;
            row.dataset.isdir = f.is_dir;
            row.dataset.ext = f.extension || '';
            
            const fileName = escapeHtml(f.name);
            const modified = escapeHtml(f.modified ? f.modified.split(' ')[0] : '');
            const fileSize = escapeHtml(f.size);
            const fileColor = safeColor(f.color, f.is_dir ? '#5c9aff' : 'var(--text-muted)');
            const iconHtml = f.emoji
                ? `<span class="text-[32px] max-sm:text-[40px] drop-shadow-md">${escapeHtml(f.emoji)}</span>`
                : `<i class="fas ${f.is_dir ? 'fa-folder' : 'fa-file-alt'} text-[24px] max-sm:text-[34px] drop-shadow-sm" style="color: ${fileColor}"></i>`;
            const tagsHtml = (f.tags || []).map(tag => `<span class="inline-block px-2 py-0.5 rounded-md text-[10px] font-bold mr-1 bg-[var(--accent-glow)] text-[var(--accent)]">${escapeHtml(tag)}</span>`).join('');

            row.innerHTML = `
                <td class="px-5 py-3 relative text-[var(--text-primary)]">
                    <div class="flex items-center relative">
                        <div class="flex items-center justify-center w-10 h-10 shrink-0 mr-4 transition-transform group-hover:scale-105">${iconHtml}</div>
                        <div class="flex flex-col w-full min-w-0 pr-12 max-sm:pr-14">
                            <div class="truncate text-[13px] max-sm:text-[16px] font-medium max-sm:font-semibold leading-tight">${fileName}</div>
                            <div class="flex items-center gap-2 text-[12px] font-normal sm:hidden opacity-60">
                                <span>${modified}</span><span>•</span><span>${fileSize}</span>
                                ${f.is_pinned ? '<i class="fas fa-thumbtack text-[9px] text-[var(--accent)]"></i>' : ''}
                            </div>
                        </div>
                    </div>
                    <!-- Badges (Top-Right) -->
                    <div class="absolute right-2 top-2 flex items-center gap-1.5 z-10">
                        ${f.is_vault ? '<i class="fas fa-shield-halved text-[10px] text-[var(--accent)]"></i>' : ''}
                        ${f.is_pinned ? '<i class="fas fa-thumbtack text-[10px] text-[var(--accent)]"></i>' : ''}
                    </div>
                    <!-- 3 dots (Mobile only) -->
                    <button onclick="handleContextMenu(event, this.closest('tr')); event.stopPropagation();" class="absolute right-2 top-1/2 -translate-y-1/2 hidden max-sm:flex w-10 h-10 items-center justify-center rounded-full text-gray-500 hover:bg-gray-400/10 active:bg-gray-400/20 active:scale-95 transition-all">
                        <i class="fas fa-ellipsis-v text-[18px]"></i>
                    </button>
                </td>
                <td class="px-5 py-3 hidden sm:table-cell"><div class="flex items-center text-[12px] font-medium text-[var(--text-secondary)]">moi</div></td>
                <td class="px-5 py-3 hidden sm:table-cell">${tagsHtml}</td>
                <td class="px-5 py-3 text-right text-[12px] hidden sm:table-cell text-[var(--text-muted)]">${modified}</td>
                <td class="px-5 py-3 text-right text-[12px] font-medium hidden sm:table-cell text-[var(--text-muted)]">${fileSize}</td>
            `;

            row.onclick = (e) => rowClicked(e, f.relative_path, f.is_dir, f.extension);
            row.ondblclick = (e) => rowOpened(f.relative_path, f.is_dir, f.extension, e);
            row.oncontextmenu = (e) => handleContextMenu(e, row);
            
            row.style.animationDelay = (i * 0.02) + 's';
            grid.appendChild(row);
        });
    } else {
        // Afficher le message vide
        zone.querySelector('table').classList.add('hidden');
        let emptyMsg = zone.querySelector('.empty-state-container');
        if (!emptyMsg) {
            emptyMsg = document.createElement('div');
            emptyMsg.className = "flex flex-col items-center justify-center w-full mt-20 mb-20 opacity-60 pointer-events-none empty-state-container";
            emptyMsg.innerHTML = `
                <div class="w-24 h-24 mb-4 rounded-full flex items-center justify-center bg-gray-500/5">
                    <i class="fas fa-folder-open text-5xl text-[var(--text-muted)]"></i>
                </div>
                <p class="text-[15px] font-semibold text-[var(--text-secondary)]">Ce dossier est vide</p>`;
            zone.appendChild(emptyMsg);
        }
    }

    zone.classList.remove('view-leaving');
    zone.classList.add('view-entering');
    setTimeout(() => zone.classList.remove('view-entering'), 500);
    
    applyViewPreference();
    attachSPAListeners();
}

function updateBreadcrumbs(currentPath, breadcrumbs) {
    const container = document.getElementById('breadcrumb-trail');
    if (!container) return;
    
    let html = `
        <button onclick="toggleSidebar()" class="w-9 h-9 lg:hidden flex items-center justify-center rounded-xl bg-[var(--bg-glass-hover)] border border-[var(--border-glass)] shadow-sm">
            <i class="fas fa-bars-staggered text-sm"></i>
        </button>
        <a href="/" class="spa-link p-1 rounded transition-all hover:text-[var(--accent)]"><i class="fas fa-house text-[11px]"></i></a>
    `;

    breadcrumbs.forEach(bc => {
        html += `<i class="fas fa-chevron-right text-[8px] text-[var(--text-muted)]"></i>
             <a href="/?path=${encodeURIComponent(bc.path)}" class="spa-link px-1.5 py-0.5 rounded hover:text-[var(--accent)] transition-colors">${escapeHtml(bc.name)}</a>`;
    });

    container.innerHTML = html;
    attachSPAListeners();
}

function showLoading(show, initialWidth = 30) {
    const bar = document.getElementById('loading-bar');
    if (!bar) return;
    if (show) {
        bar.style.opacity = '1';
        bar.style.transition = 'width 0.2s ease-out, opacity 0.2s';
        bar.style.width = initialWidth + '%';
        setTimeout(() => { if (isNavigating) bar.style.width = '85%'; }, 150);
    } else {
        bar.style.width = '100%';
        setTimeout(() => { 
            bar.style.opacity = '0'; 
            setTimeout(() => { bar.style.width = '0'; }, 200);
        }, 200);
    }
}

function showSkeletons() {
    const zone = document.getElementById('file-grid-zone');
    if (!zone) return;
    const isGrid = zone.classList.contains('grid-mode');
    let html = '';
    
    if (isGrid) {
        html = `<div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4 p-4">`;
        for (let i = 0; i < 18; i++) {
            html += `<div class="h-32 rounded-2xl skeleton opacity-40"></div>`;
        }
        html += `</div>`;
    } else {
        html = `<div class="space-y-2 p-4">`;
        for (let i = 0; i < 15; i++) {
            html += `<div class="h-11 rounded-lg skeleton opacity-40"></div>`;
        }
        html += `</div>`;
    }
    zone.innerHTML = html;
}

function attachSPAListeners() {
    // Intercept links
    document.querySelectorAll('.spa-link').forEach(link => {
        link.onclick = (e) => {
            if (e.metaKey || e.ctrlKey) return; // Allow new tab
            e.preventDefault();
            navigateTo(link.getAttribute('href'));
        };
    });
    
    // Search listener (Enhanced with slide animation)
    document.getElementById('searchInput')?.addEventListener('input', e => {
        const term = e.target.value.toLowerCase();
        document.querySelectorAll('.file-row').forEach(row => {
            const name = (row.dataset.name || '').toLowerCase();
            const matches = name.includes(term);
            
            if (matches) {
                row.classList.remove('search-out');
                row.style.removeProperty('display');
            } else {
                if (!row.classList.contains('search-out')) {
                    row.classList.add('search-out');
                    // Utiliser setProperty avec important pour écraser le display: flex !important du mode grille
                    setTimeout(() => { 
                        if (row.classList.contains('search-out')) {
                            row.style.setProperty('display', 'none', 'important');
                        }
                    }, 300);
                }
            }
        });
    });

    initLasso();
    applyViewPreference();
    initPrefetching();
}

function initPrefetching() {
    // Préchargement au survol des dossiers
    document.querySelectorAll('.file-row[data-isdir="true"]').forEach(row => {
        let timer;
        row.onmouseenter = () => {
            timer = setTimeout(() => {
                const url = `/?path=${row.dataset.path}`;
                if (!navCache.has(url)) {
                    fetch(url).then(r => r.text()).then(html => {
                        navCache.set(url, { html, time: Date.now() });
                        console.log("[PREFETCH] Dossier chargé en avance:", row.dataset.name);
                    });
                }
            }, 150); // Attendre 150ms de survol
        };
        row.onmouseleave = () => clearTimeout(timer);
    });
}

function applyViewPreference() {
    const isGrid = localStorage.getItem('gravity_view') === 'grid';
    const zone = document.getElementById('file-grid-zone');
    if (zone) {
        zone.classList.toggle('grid-mode', isGrid);
    }
    const btn = document.getElementById('viewToggleBtn');
    if (btn) btn.innerHTML = isGrid ? '<i class="fas fa-list"></i>' : '<i class="fas fa-th-large"></i>';
}

function toggleView() {
    const isGrid = localStorage.getItem('gravity_view') === 'grid';
    const newMode = isGrid ? 'list' : 'grid';
    const zone = document.getElementById('file-grid-zone');
    
    // Animation de sortie synchronisée
    const rows = zone?.querySelectorAll('.file-row') || [];
    rows.forEach((row, i) => {
        row.style.transition = `opacity 0.2s ease, transform 0.25s var(--motion-curve)`;
        row.style.opacity = '0';
        row.style.transform = 'scale(0.96) translateY(4px)';
    });
    
    setTimeout(() => {
        localStorage.setItem('gravity_view', newMode);
        applyViewPreference();
        
        // Animation d'entrée en cascade fluide
        rows.forEach((row, i) => {
            row.style.transition = 'none';
            row.style.opacity = '0';
            row.style.transform = newMode === 'grid' ? 'scale(0.9) translateY(12px)' : 'translateX(-12px)';
            
            requestAnimationFrame(() => {
                row.style.transition = `opacity 0.3s var(--motion-curve) ${i * 0.02}s, transform 0.4s var(--motion-curve) ${i * 0.02}s`;
                row.style.opacity = '1';
                row.style.transform = 'scale(1) translateX(0) translateY(0)';
                setTimeout(() => { row.style.transition = ''; }, 500 + (i * 20));
            });
        });
    }, 200);
}

async function fetchAction(url, method = 'GET', body = null) {
    showLoading(true);
    const options = { method: method.toUpperCase() };
    if (body) options.body = body;
    try {
        const res = await fetch(url, options);
        if (res.ok) {
            navCache.clear();
            await navigateTo(window.location.href, false);
            return true;
        } else {
            let errorMsg = "Action impossible";
            try {
                const data = await res.json();
                errorMsg = (typeof data.detail === 'string') ? data.detail : JSON.stringify(data.detail || data);
            } catch(e) {
                errorMsg = await res.text() || errorMsg;
            }
            showToast(errorMsg, 'error');
            return false;
        }
    } catch (e) {
        showToast("Erreur réseau", 'error');
        return false;
    } finally {
        showLoading(false);
    }
}

function showToast(message, type = 'info') {
    if (message === null || message === undefined || String(message).trim() === '') return;
    const toast = document.createElement('div');
    toast.className = `fixed bottom-24 left-1/2 -translate-x-1/2 z-[1000] px-6 py-3 rounded-2xl glass shadow-2xl flex items-center gap-3 anim-fadeUp`;
    const icon = type === 'error' ? 'fa-circle-exclamation text-red-500' : 'fa-circle-info text-indigo-500';
    toast.innerHTML = `<i class="fas ${icon}"></i> <span class="text-[13px] font-bold" style="color:var(--text-primary)">${message}</span>`;
    document.body.appendChild(toast);
    setTimeout(() => {
        toast.classList.add('opacity-0', 'translate-y-4');
        setTimeout(() => toast.remove(), 400);
    }, 3000);
}

async function submitSPAForm(event) {
    event.preventDefault();
    const form = event.target;
    const url = form.action;
    const method = form.method || 'POST';
    const formData = new FormData(form);

    showLoading(true);
    try {
        const response = await fetch(url, {
            method: method.toUpperCase(),
            body: formData
        });
        
        if (response.ok) {
            navCache.clear(); // Vider le cache car les données ont changé (ex: nouveau dossier)
            await navigateTo(window.location.href, false);
            
            // Fermer tous les modals ouverts
            document.querySelectorAll('.modal-overlay').forEach(m => hideDialog(m.id));
            
            // Si c'est une création, vider l'input
            const input = form.querySelector('input[type="text"]');
            if (input) input.value = '';
            
        } else {
            const err = await response.text();
            alert("Erreur: " + err);
        }
    } catch (e) {
        console.error("SPA Form error:", e);
    } finally {
        showLoading(false);
    }
}

async function submitUpload() {
    const input = document.getElementById('fileUpload');
    if (!input || !input.files.length) return;
    const dest = window.CURRENT_PATH || '';
    uploadFiles(input.files, dest);
    input.value = '';
}

let uploadQueue = [];
let activeUploads = 0;
const MAX_CONCURRENT = 3;
let refreshTimeout = null;

function debouncedRefresh(path) {
    if (refreshTimeout) return;
    refreshTimeout = setTimeout(() => {
        if (window.CURRENT_PATH === path) navigateTo(window.location.href, false);
        refreshTimeout = null;
    }, 1000);
}

function uploadFiles(files, path) {
    const panel = document.getElementById('transferPanel');
    if (panel) panel.classList.add('active');
    
    Array.from(files).forEach(file => {
        uploadQueue.push({ file, path });
    });
    processQueue();
}

function processQueue() {
    if (activeUploads >= MAX_CONCURRENT || uploadQueue.length === 0) return;

    activeUploads++;
    const { file, path } = uploadQueue.shift();
    const list = document.getElementById('transferList');
    
    const id = 'up-' + Math.random().toString(36).substr(2, 9);
    const item = document.createElement('div');
    item.className = 'transfer-item anim-fadeUp';
    item.id = id;
    item.innerHTML = `
        <div class="transfer-info">
            <span class="truncate w-40">${file.name}</span>
            <span class="percent">Initialisation...</span>
        </div>
        <div class="transfer-progress-bg">
            <div class="transfer-progress-fill" style="width:0%"></div>
        </div>
    `;
    list.appendChild(item);

    const xhr = new XMLHttpRequest();
    const fd = new FormData();
    fd.append('path', path);
    fd.append('files', file);
    const rel = file.fullPath || file.webkitRelativePath;
    if (rel) fd.append('fullPaths', rel);

    xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
            const p = Math.round((e.loaded / e.total) * 100);
            item.querySelector('.percent').innerText = p + '%';
            item.querySelector('.transfer-progress-fill').style.width = p + '%';
        }
    };

    xhr.onload = () => {
        activeUploads--;
        item.classList.add('opacity-50');
        item.querySelector('.percent').innerHTML = '<i class="fas fa-check text-green-500"></i>';
        
        lastActionTarget = file.name; // Trigger bounce for the new file
        
        setTimeout(() => {
            item.remove();
            const panel = document.getElementById('transferPanel');
            if (activeUploads === 0 && uploadQueue.length === 0) {
                 panel.classList.remove('active');
                 debouncedRefresh(path); // Final ensure refresh
            }
        }, 1500);
        
        debouncedRefresh(path);
        processQueue();
    };

    xhr.onerror = () => {
        activeUploads--;
        item.querySelector('.percent').innerHTML = '<i class="fas fa-exclamation-triangle text-red-500"></i>';
        processQueue();
    };

    xhr.open('POST', '/upload');
    xhr.send(fd);
    
    // Si on a encore de la place, on en lance un autre
    if (activeUploads < MAX_CONCURRENT) processQueue();
}

// ── Interaction Logic ──
let lastSelectedRow = null;

function rowClicked(event, path, isDir, ext) {
    const row = event.currentTarget;
    const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0;
    const isCmd = isMac ? event.metaKey : event.ctrlKey;

    if (event.shiftKey && lastSelectedRow) {
        // Sélection Multiple (Shift)
        const rows = Array.from(document.querySelectorAll('.file-row'));
        const start = rows.indexOf(lastSelectedRow);
        const end = rows.indexOf(row);
        
        clearSelection();
        const min = Math.min(start, end);
        const max = Math.max(start, end);
        
        for (let i = min; i <= max; i++) {
            selectedRows.add(rows[i]);
            rows[i].classList.add('active-selection');
        }
    } else if (isCmd) {
        // Ctrl/Cmd + Clic
        if (selectedRows.has(row)) {
            selectedRows.delete(row);
            row.classList.remove('active-selection');
        } else {
            selectedRows.add(row);
            row.classList.add('active-selection');
            lastSelectedRow = row;
        }
    } else {
        // Sélection unique
        clearSelection();
        selectedRows.add(row);
        row.classList.add('active-selection');
        lastSelectedRow = row;
    }
    
    updateSelectionBar();
}

let selectionBarTimeout = null;
function updateSelectionBar() {
    const bar = document.getElementById('selection-bar');
    if (!bar) return;
    const countEl = document.getElementById('sel-count');
    
    if (selectionBarTimeout) clearTimeout(selectionBarTimeout);

    if (selectedRows.size > 0) {
        countEl.innerText = `${selectedRows.size} sélectionné${selectedRows.size > 1 ? 's' : ''}`;
        
        // Délai de latence pour éviter l'apparition sur double-clic
        selectionBarTimeout = setTimeout(() => {
            bar.classList.remove('pointer-events-none', 'opacity-0', 'translate-y-12');
            bar.classList.add('opacity-100', 'translate-y-0');
            document.getElementById('sel-share').classList.toggle('hidden', selectedRows.size > 1);
        }, 150); // 150ms delay
    } else {
        bar.classList.remove('opacity-100', 'translate-y-0');
        bar.classList.add('pointer-events-none', 'opacity-0', 'translate-y-12');
    }
}

function multiDownload() {
    if (selectedRows.size === 0) return;
    
    if (selectedRows.size === 1) {
        const row = Array.from(selectedRows)[0];
        const encPath = encodeURIComponent(row.dataset.path).replace(/%2F/g, '/');
        window.location.href = '/download/' + encPath;
        return;
    }

    const paths = Array.from(selectedRows).map(r => r.dataset.path);
    const fd = new FormData();
    fd.append('paths', JSON.stringify(paths));

    const dlBtn = document.querySelector('#selection-bar i.fa-download');
    if(dlBtn) dlBtn.className = 'fas fa-spinner fa-spin text-[16px]';

    fetch('/download/multi', {
        method: 'POST',
        body: fd
    })
    .then(async res => {
        if (!res.ok) throw new Error('Erreur lors du zippage sur le serveur.');
        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;
        a.download = 'Archive_GravityNAS.zip';
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        if(dlBtn) dlBtn.className = 'fas fa-download text-[16px]';
        clearSelection();
    })
    .catch(err => {
        showToast(err.message, 'error');
        if(dlBtn) dlBtn.className = 'fas fa-download text-[16px]';
    });
}

function rowOpened(path, isDir, ext, event) {
    if (isDir) {
        // Effet d'immersion : on fait grossir l'icône cliquée
        if (event && event.currentTarget) {
            const row = event.currentTarget;
            row.style.zIndex = "100";
            row.style.transition = "transform 0.4s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.3s";
            row.style.transform = "scale(1.05)";
            row.style.background = "var(--accent-glow)";
        }
        navigateTo(`/?path=${path}`);
    } else {
        openPreview(path, ext || '');
    }
}

function clearSelection() {
    selectedRows.forEach(r => r.classList.remove('active-selection'));
    selectedRows.clear();
    lastSelectedRow = null;
    updateSelectionBar();
}

function setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    document.body.setAttribute('data-theme', theme);
    localStorage.setItem('gravity_theme', theme);
    
    // Mise à jour visuelle immédiate des sélecteurs
    document.querySelectorAll('.theme-selector').forEach(btn => {
        btn.classList.toggle('active-theme', btn.dataset.themeVal === theme);
    });
    
    // Sauvegarde persistante (silencieuse)
    const fd = new FormData();
    fd.append('theme', theme);
    // On n'envoie PAS avatarUrl et wallpaperUrl pour ne pas les écraser par défaut
    fetch('/settings/profile', { method: 'POST', body: fd })
        .then(res => {
            if (!res.ok) console.warn("Erreur synchro thème");
        })
        .catch(e => console.error("Échec réseau synchro thème", e));
}

// Appliquer le thème et la vue sauvegardés au chargement immédiat
(function() {
    const savedTheme = localStorage.getItem('gravity_theme') || document.documentElement.dataset.theme || 'light';
    setTheme(savedTheme);
    applyViewPreference();
})();

function showDialog(id) {
    const m = document.getElementById(id);
    if (!m) return;
    m.classList.remove('hidden');
    // Force reflow pour garantir que la transition scale s'applique
    void m.offsetWidth; 
    m.classList.add('active');
}
function hideDialog(id) {
    const m = document.getElementById(id);
    if (!m) return;
    m.classList.remove('active');
    // On attend la fin de l'animation CSS (var(--motion-normal) = 250ms)
    setTimeout(() => m.classList.add('hidden'), 250);
}

function switchTab(evt, tabId) {
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.getElementById(tabId).classList.add('active');
    evt.currentTarget.classList.add('active');
}

function handleContextMenu(event, rowEl) {
    event.preventDefault(); event.stopPropagation();
    
    // Si l'élément n'est pas déjà sélectionné, on le sélectionne seul
    if (!selectedRows.has(rowEl)) {
        clearSelection();
        selectedRows.add(rowEl);
        rowEl.classList.add('active-selection');
        lastSelectedRow = rowEl;
        updateSelectionBar();
    }

    const cm = document.getElementById('contextMenu');
    const isTrash = CURRENT_PATH === '.Corbeille';
    const isSingle = selectedRows.size === 1;
    const firstRow = Array.from(selectedRows)[0];
    const encPath = encodeURIComponent(firstRow.dataset.path).replace(/%2F/g, '/');
    
    document.getElementById('cm-download').classList.toggle('hidden', !isSingle);
    if (isSingle) document.getElementById('cm-download').href = '/download/' + encPath;
    
    document.getElementById('cm-restore').classList.toggle('hidden', !isTrash);
    document.getElementById('cm-share').classList.toggle('hidden', isTrash || !isSingle);
    
    // Nouvelles options de personnalisation
    const isImg = isSingle && ['.jpg','.jpeg','.png','.webp'].some(ex => firstRow.dataset.path.toLowerCase().endsWith(ex));
    document.querySelectorAll('.cm-img-only').forEach(el => el.classList.toggle('hidden', !isImg));

    document.getElementById('cm-delete-text').innerText = isTrash 
        ? (selectedRows.size > 1 ? `Supprimer les ${selectedRows.size} éléments` : 'Supprimer définitivement')
        : (selectedRows.size > 1 ? `Mettre ${selectedRows.size} éléments à la corbeille` : 'Supprimer');

    cm.classList.remove('hidden');
    let x = event.clientX, y = event.clientY;
    if (x + 240 > window.innerWidth) x = window.innerWidth - 250;
    if (y + 300 > window.innerHeight) y = window.innerHeight - 310;
    cm.style.left = x + 'px'; cm.style.top = y + 'px';
}

function hideContextMenu() { 
    document.getElementById('contextMenu')?.classList.add('hidden'); 
    document.getElementById('desktopContextMenu')?.classList.add('hidden'); 
}
document.body.addEventListener('click', hideContextMenu);

function handleDesktopContextMenu(event) {
    if (event.target.closest('.file-row')) return;
    event.preventDefault();
    hideContextMenu();
    
    const cm = document.getElementById('desktopContextMenu');
    cm.classList.remove('hidden');
    let x = event.clientX, y = event.clientY;
    if (x + 240 > window.innerWidth) x = window.innerWidth - 250;
    if (y + 300 > window.innerHeight) y = window.innerHeight - 310;
    cm.style.left = x + 'px'; cm.style.top = y + 'px';
}

function cmExecute() {
    hideContextMenu(); if (selectedRows.size === 0) return;
    const row = Array.from(selectedRows)[0];
    rowOpened(row.dataset.path, row.dataset.isdir === 'true', '', { currentTarget: row });
}

function cmAction(modalId) {
    hideContextMenu(); if (selectedRows.size === 0) return;
    // On récupère le premier élément sélectionné VALIDE (qui a un path)
    const validRows = Array.from(selectedRows).filter(r => r.dataset.path);
    if (validRows.length === 0) return;
    const activeRow = validRows[0];

    if (modalId === 'renameModal') document.getElementById('renameInput').value = activeRow.dataset.name;
    else if (modalId === 'sendModal') {
        document.getElementById('sendItemName').innerText = activeRow.dataset.name;
        document.getElementById('sendInputFile').value = activeRow.dataset.path;
    } else if (modalId === 'metaModal') {
        document.getElementById('metaItemName').innerText = activeRow.dataset.name;
        const pinBtn = document.getElementById('metaPinBtn');
        if (activeRow.dataset.isdir === 'false') pinBtn.classList.add('hidden');
        else {
            pinBtn.classList.remove('hidden');
            pinBtn.innerHTML = activeRow.dataset.ispinned === 'true' ? '<i class="fas fa-thumbtack mr-1.5"></i>Désépingler' : '<i class="fas fa-thumbtack mr-1.5"></i>Épingler';
        }
    } else if (modalId === 'shareExternalModal') {
        document.getElementById('shareExternalName').innerText = activeRow.dataset.name;
        document.getElementById('shareLinkContainer').classList.add('hidden');
        document.getElementById('generateShareBtn').classList.remove('hidden');
    } else if (modalId === 'vaultModal') {
        const isVault = activeRow.dataset.isvault === 'true';
        document.getElementById('vaultActionBtn').innerText = isVault ? 'Déverrouiller' : 'Sécuriser (AES-256)';
        document.getElementById('vaultPassword').value = '';
        document.getElementById('vaultStatusMsg').classList.add('hidden');
    }
    showDialog(modalId);
}

function setNASAsset(type) {
    hideContextMenu();
    const row = Array.from(selectedRows)[0];
    const fd = new FormData();
    fd.append('path', row.dataset.path);
    fetchAction(type === 'bg' ? '/profile/nas-background' : '/profile/nas-avatar', 'POST', fd);
}

async function cmDelete() {
    hideContextMenu(); if (selectedRows.size === 0) return;
    const isTrash = CURRENT_PATH === '.Corbeille';
    const msg = isTrash 
        ? (selectedRows.size > 1 ? `Détruire ces ${selectedRows.size} éléments ?` : `Détruire cet élément ?`)
        : (selectedRows.size > 1 ? `Envoyer ces ${selectedRows.size} éléments à la corbeille ?` : `Mettre à la corbeille ?`);

    if (confirm(msg)) {
        const paths = Array.from(selectedRows).map(r => r.dataset.path);
        const fd = new FormData();
        fd.append('paths', JSON.stringify(paths));
        fd.append('current_path', CURRENT_PATH);
        
        selectedRows.forEach(r => r.classList.add('fade-out'));
        await fetchAction('/delete/batch', 'POST', fd);
        showToast(`${selectedRows.size} élément(s) supprimé(s)`);
        clearSelection();
    }
}

async function cmRestore() {
    hideContextMenu(); if (selectedRows.size === 0) return;
    const paths = Array.from(selectedRows).map(r => r.dataset.path);
    const fd = new FormData();
    fd.append('paths', JSON.stringify(paths));
    
    selectedRows.forEach(r => r.classList.add('fade-out'));
    await fetchAction('/trash/restore/batch', 'POST', fd);
    showToast(`${selectedRows.size} élément(s) restauré(s)`);
    clearSelection();
}

async function submitMkdir() {
    const input = document.getElementById('mkdirInput');
    const name = input.value;
    if (!name) return;
    
    const fd = new FormData();
    fd.append('path', CURRENT_PATH);
    fd.append('folder_name', name);
    lastActionTarget = name; // Préparer le rebond
    await fetchAction('/mkdir', 'POST', fd);
    hideDialog('mkdirModal');
    input.value = '';
}

async function submitRename() {
    const activeRow = Array.from(selectedRows)[0];
    const fd = new FormData();
    fd.append('old_name', activeRow.dataset.path);
    fd.append('new_name', document.getElementById('renameInput').value);
    fd.append('path', CURRENT_PATH);
    await fetchAction('/rename', 'POST', fd);
    hideDialog('renameModal');
}

async function submitMove() {
    const row = Array.from(selectedRows)[0];
    if (!row) return;
    const fd = new FormData();
    fd.append('filepath', row.dataset.path);
    fd.append('destination', document.getElementById('moveInput').value);
    fd.append('path', CURRENT_PATH);
    await fetchAction('/move', 'POST', fd);
    hideDialog('moveModal');
}

async function submitMeta(key, value) {
    if (selectedRows.size === 0) return;
    for (const row of selectedRows) {
        const fd = new FormData();
        fd.append('filepath', row.dataset.path);
        fd.append('meta_key', key); 
        fd.append('meta_value', value === 'reset' ? '' : value); // Fix reset
        fd.append('path', CURRENT_PATH);
        await fetchAction('/file/meta', 'POST', fd);
    }
}

async function quickUnpin(path) {
    const fd = new FormData();
    fd.append('filepath', path); fd.append('meta_key', 'is_pinned'); fd.append('meta_value', '0'); fd.append('path', CURRENT_PATH);
    await fetchAction('/file/meta', 'POST', fd);
}

function handleFolderDragOver(e, el) { e.preventDefault(); el.classList.add('drag-over'); }
function handleFolderDragLeave(e, el) { el.classList.remove('drag-over'); }
async function handleFolderDrop(e, targetPath, el) {
    e.preventDefault(); el.classList.remove('drag-over');
    
    if (selectedRows.size > 0) {
        const paths = Array.from(selectedRows).map(r => r.dataset.path);
        // Filtrage : on ne déplace pas dans soi-même
        const validPaths = paths.filter(p => p !== targetPath && !targetPath.startsWith(p + '/'));
        
        if (validPaths.length > 0) {
            const fd = new FormData();
            fd.append('paths', JSON.stringify(validPaths));
            fd.append('destination', targetPath);
            fd.append('current_path', window.CURRENT_PATH);
            
            selectedRows.forEach(r => r.classList.add('fade-out'));
            await fetchAction('/move/batch', 'POST', fd);
            showToast(`${validPaths.length} élément(s) déplacé(s)`);
            clearSelection();
        }
    } else {
        const src = e.dataTransfer.getData('text/plain');
        if (src && src !== targetPath) {
            const fd = new FormData(); fd.append('filepath', src); fd.append('destination', targetPath); fd.append('path', window.CURRENT_PATH);
            await fetchAction('/move', 'POST', fd);
        }
    }
}

function handleDragStart(e, path, isDir) {
    // Si l'élément n'est pas sélectionné, on le sélectionne
    const row = document.querySelector(`.file-row[data-path="${path}"]`);
    if (row && !selectedRows.has(row)) {
        clearSelection();
        selectedRows.add(row);
        row.classList.add('active-selection');
    }

    e.dataTransfer.setData('text/plain', path); 
    e.dataTransfer.setData('isDir', isDir ? 'true' : 'false');
    e.dataTransfer.effectAllowed = 'move';
}
document.addEventListener('dragend', () => { document.getElementById('sidebarDropZone')?.classList.remove('drag-over'); });

async function handleSidebarPinDrop(e, el) {
    e.preventDefault(); el.classList.remove('drag-over');
    if (selectedRows.size === 0) return;

    for (const row of selectedRows) {
        const path = row.dataset.path;
        const isDir = row.dataset.isdir === 'true';
        if (path && isDir) {
            const fd = new FormData(); fd.append('filepath', path); fd.append('meta_key','is_pinned'); fd.append('meta_value','1'); fd.append('path', CURRENT_PATH);
            await fetchAction('/file/meta', 'POST', fd);
        }
    }
}

async function handleTrashDrop(e, el) {
    e.preventDefault(); el.classList.remove('drag-over');
    if (selectedRows.size === 0) return;

    const names = selectedRows.size > 1 ? `${selectedRows.size} éléments` : Array.from(selectedRows)[0].dataset.name;
    if (confirm(`Mettre ${names} à la corbeille ?`)) {
        for (const row of selectedRows) {
            const path = row.dataset.path;
            await fetchAction(`/delete/${encodeURIComponent(path)}?path=${encodeURIComponent(CURRENT_PATH)}`, 'POST');
        }
    }
}

function initLasso() {
    const grid = document.getElementById('file-grid-zone');
    if (!grid) return;

    grid.addEventListener('mousedown', (e) => {
        // Désactivation du lasso sur mobile (tactile)
        if ('ontouchstart' in window && window.innerWidth < 1024) return;

        // Nettoyage de sécurité : on supprime tous les lassos qui auraient pu rester
        document.querySelectorAll('.selection-lasso').forEach(el => el.remove());

        // Si on clique sur un fichier ou bouton, on ne lance pas le lasso
        if (e.target.closest('.file-row') || e.target.closest('button') || e.target.closest('a') || e.target.closest('input')) return;
        
        // Clic dans le vide : on nettoie si ni Ctrl ni Shift ne sont pressés
        if (!e.ctrlKey && !e.shiftKey) clearSelection();
        
        startX = e.pageX; startY = e.pageY;
        selectionBox = document.createElement('div');
        selectionBox.className = 'selection-lasso';
        document.body.appendChild(selectionBox);

        const onMouseMove = (e) => {
            const curX = e.pageX;
            const curY = e.pageY;
            
            const x = Math.min(startX, curX), y = Math.min(startY, curY);
            const w = Math.abs(startX - curX), h = Math.abs(startY - curY);
            
            selectionBox.style.left = x + 'px'; selectionBox.style.top = y + 'px';
            selectionBox.style.width = w + 'px'; selectionBox.style.height = h + 'px';

            const boxRect = selectionBox.getBoundingClientRect();

            document.querySelectorAll('.file-row').forEach(row => {
                // EXCLUSION : on ignore la ligne '..' (elle n'a pas de data-path)
                if (!row.dataset.path) return;

                const rRect = row.getBoundingClientRect();
                const overlap = !(rRect.right < boxRect.left || rRect.left > boxRect.right || rRect.bottom < boxRect.top || rRect.top > boxRect.bottom);
                
                if (overlap) {
                    row.classList.add('active-selection');
                    selectedRows.add(row);
                } else if (!e.ctrlKey && !e.shiftKey) {
                    row.classList.remove('active-selection');
                    selectedRows.delete(row);
                }
            });
            updateSelectionBar();
        };

        const onMouseUp = () => {
            document.removeEventListener('mousemove', onMouseMove);
            document.removeEventListener('mouseup', onMouseUp);
            if (selectionBox) { selectionBox.remove(); selectionBox = null; }
            updateSelectionBar();
        };

        document.addEventListener('mousemove', onMouseMove);
        document.addEventListener('mouseup', onMouseUp);
    });
}

// ── Gestion des raccourcis globaux (Navigation Clavier) ──
document.addEventListener('keydown', (e) => {
    // Si on tape dans un input, on ignore les raccourcis de navigation
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') {
        if (e.key === 'Escape') e.target.blur();
        return;
    }

    if (e.key === 'Escape') {
        if (!document.getElementById('previewOverlay').classList.contains('hidden')) closePreview();
        else if (document.querySelector('.modal:not(.hidden)')) document.querySelectorAll('.modal').forEach(m => m.classList.add('hidden'));
        else clearSelection();
    }

    // Flèches (Navigation)
    if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key)) {
        const rows = Array.from(document.querySelectorAll('.file-row:not([style*="display: none"])'));
        if (rows.length === 0) return;
        
        e.preventDefault();
        let nextIndex = 0;
        
        if (selectedRows.size > 0) {
            const current = lastSelectedRow || Array.from(selectedRows)[0];
            const currentIndex = rows.indexOf(current);
            
            if (e.key === 'ArrowDown' || e.key === 'ArrowRight') nextIndex = Math.min(currentIndex + 1, rows.length - 1);
            else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') nextIndex = Math.max(currentIndex - 1, 0);
        }

        const targetRow = rows[nextIndex];
        if (targetRow) {
            clearSelection();
            selectedRows.add(targetRow);
            targetRow.classList.add('active-selection');
            lastSelectedRow = targetRow;
            targetRow.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
            updateSelectionBar();
        }
    }

    // Entrée (Ouvrir)
    if (e.key === 'Enter' && selectedRows.size === 1) {
        const row = Array.from(selectedRows)[0];
        rowOpened(row.dataset.path, row.dataset.isdir === 'true', row.dataset.ext, { currentTarget: row });
    }

    // Suppr (Supprimer)
    if ((e.key === 'Delete' || e.key === 'Backspace') && selectedRows.size > 0) {
        if (e.key === 'Backspace' && !e.metaKey && !e.ctrlKey) return; // Backspace seul ne supprime pas (standard)
        cmDelete();
    }
});

const dz = document.getElementById('dropZone');
if (dz) {
    ['dragenter','dragover','dragleave','drop'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); e.stopPropagation(); }));
    dz.addEventListener('dragover', () => dz.style.boxShadow = 'inset 0 0 0 3px var(--accent)');
    dz.addEventListener('dragleave', () => dz.style.boxShadow = '');
    dz.addEventListener('drop', async e => {
        dz.style.boxShadow = '';
        const items = e.dataTransfer.items;
        if (!items) return;
        const targetPath = window.CURRENT_PATH || '';
        showLoading(true); // Feedback direct
        for (let i = 0; i < items.length; i++) {
            const entry = items[i].webkitGetAsEntry();
            if (entry) traverseFileTree(entry, targetPath);
        }
        setTimeout(() => showLoading(false), 500);
    });
}

function traverseFileTree(entry, destPath, internalPath = "") {
    if (entry.isFile) {
        entry.file(file => {
            file.fullPath = internalPath + file.name;
            uploadFiles([file], destPath);
        });
    } else if (entry.isDirectory) {
        const folderPath = internalPath + entry.name;
        // Création immédiate du dossier (nécessaire pour les dossiers vides)
        const fd = new FormData();
        fd.append('path', destPath);
        fd.append('folder_name', folderPath);
        fetch('/mkdir', { method: 'POST', body: fd }).then(() => {
            if (window.CURRENT_PATH === destPath) debouncedRefresh(destPath);
        });

        const dirReader = entry.createReader();
        const readEntries = () => {
            dirReader.readEntries(entries => {
                if (entries.length > 0) {
                    entries.forEach(e => traverseFileTree(e, destPath, folderPath + "/"));
                    readEntries();
                }
            });
        };
        readEntries();
    }
}




function copyPublicUrl() {
    const input = document.getElementById('publicUrlInput');
    navigator.clipboard?.writeText(input.value).then(() => showToast('URL copiée !'));
}

// Gestion de la Galerie

// Logic replaced by the new version below

function closePreview() {
    const o = document.getElementById('previewOverlay');
    if (o && !o.classList.contains('hidden')) {
        const cont = document.getElementById('previewContainer');
        if (cont) {
            cont.style.transition = 'transform 0.3s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.25s';
            cont.style.transform = 'scale(0.85)';
            cont.style.opacity = '0';
        }
        o.style.transition = 'opacity 0.3s ease';
        o.style.opacity = '0';
        setTimeout(() => {
            o.classList.add('hidden');
            o.classList.remove('flex');
            o.style.opacity = '';
            if (cont) { cont.innerHTML = ''; cont.style.transform = ''; cont.style.opacity = ''; }
        }, 300);
    }
}

let previewFiles = [];
let currentPreviewIndex = -1;

function openPreview(path, ext) {
    const overlay = document.getElementById('previewOverlay');
    const container = document.getElementById('previewContainer');
    if (!overlay || !container) return;

    // Collecter tous les fichiers média du dossier actuel pour le carousel
    previewFiles = Array.from(document.querySelectorAll('.file-row'))
        .filter(r => {
            const e = (r.dataset.ext || '').toLowerCase();
            return ['.jpg', '.jpeg', '.png', '.webp', '.gif', '.mp4', '.mov', '.webm', '.mp3', '.wav', '.ogg', '.m4a'].includes(e);
        })
        .map(r => ({ path: r.dataset.path, ext: r.dataset.ext }));

    currentPreviewIndex = previewFiles.findIndex(f => f.path === path);

    overlay.classList.remove('hidden');
    overlay.classList.add('flex');
    
    const encPath = encodeURIComponent(path).replace(/%2F/g, '/');
    const lowExt = (ext || path.split('.').pop()).toLowerCase().replace(/^\./, '');
    const extension = '.' + lowExt;
    const mediaUrl = `/preview/${encPath}`;
    
    let content = '';
    if (['.jpg', '.jpeg', '.png', '.webp', '.gif', '.svg'].includes(extension)) {
        content = `<div class="relative group">
                    <img src="${mediaUrl}" alt="Aperçu de ${escapeHtml(path.split('/').pop())}" class="max-h-[85vh] max-w-full rounded-lg shadow-2xl anim-scaleIn">
                    <div class="absolute inset-0 bg-black/20 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center pointer-events-none">
                        <span class="bg-black/50 px-4 py-2 rounded-full text-white text-xs font-bold">MODE LIGHTROOM</span>
                    </div>
                   </div>`;
    } else if (['.mp4', '.mov', '.webm'].includes(extension)) {
        content = `<video controls autoplay playsinline class="max-h-[85vh] max-w-full rounded-lg shadow-2xl">
                    <source src="${mediaUrl}" type="${videoMimeType(extension)}">
                   </video>`;
    } else if (['.mp3', '.wav', '.ogg', '.m4a', '.flac'].includes(extension)) {
        content = `<div class="preview-audio glass rounded-3xl p-10 w-[min(90vw,34rem)] text-center">
                    <i class="fas fa-music text-6xl mb-6 text-indigo-400"></i>
                    <h2 class="text-lg font-bold mb-6">${escapeHtml(path.split('/').pop())}</h2>
                    <audio controls autoplay class="w-full"><source src="${mediaUrl}" type="${audioMimeType(extension)}"></audio>
                   </div>`;
    } else if (extension === '.pdf') {
        content = `<iframe src="${mediaUrl}" title="Aperçu PDF" class="preview-document w-[min(92vw,70rem)] h-[82vh] rounded-lg bg-white"></iframe>`;
    } else if (['.txt', '.md', '.csv', '.json', '.xml', '.html', '.css', '.js', '.py', '.yml', '.yaml', '.log'].includes(extension)) {
        content = `<pre id="previewText" class="preview-text w-[min(92vw,70rem)] max-h-[82vh] overflow-auto rounded-2xl p-6 text-left text-sm whitespace-pre-wrap break-words"></pre>`;
        container.innerHTML = content;
        fetch(mediaUrl, { headers: { 'Accept': 'text/plain' } })
            .then(response => { if (!response.ok) throw new Error('Lecture impossible'); return response.text(); })
            .then(text => { document.getElementById('previewText').textContent = text.slice(0, 2 * 1024 * 1024); })
            .catch(() => { document.getElementById('previewText').textContent = 'Impossible de charger ce document.'; });
        updateCarouselArrows();
        return;
    } else {
        content = `<div class="p-12 text-center glass rounded-3xl">
                    <i class="fas fa-file-alt text-6xl mb-4 opacity-20"></i>
                    <p class="mb-8 text-white/60 font-medium">Aperçu non disponible pour ce format</p>
                    <a href="/download/${encPath}" class="btn-primary w-full py-4 text-sm"><i class="fas fa-download mr-2"></i>Télécharger le fichier</a>
                   </div>`;
    }

    container.innerHTML = content;
    updateCarouselArrows();
}

window.openPreview = openPreview;

function videoMimeType(extension) {
    return ({ '.mp4': 'video/mp4', '.mov': 'video/quicktime', '.webm': 'video/webm' })[extension] || 'video/*';
}

function audioMimeType(extension) {
    return ({ '.mp3': 'audio/mpeg', '.wav': 'audio/wav', '.ogg': 'audio/ogg', '.m4a': 'audio/mp4', '.flac': 'audio/flac' })[extension] || 'audio/*';
}

function updateCarouselArrows() {
    let prevBtn = document.getElementById('prevBtn');
    let nextBtn = document.getElementById('nextBtn');
    
    if (!prevBtn) {
        prevBtn = document.createElement('div'); prevBtn.id = 'prevBtn'; prevBtn.className = 'carousel-btn carousel-prev';
        prevBtn.innerHTML = '<i class="fas fa-chevron-left"></i>';
        prevBtn.onclick = (e) => { e.stopPropagation(); navigateCarousel(-1); };
        document.getElementById('previewOverlay').appendChild(prevBtn);
        
        nextBtn = document.createElement('div'); nextBtn.id = 'nextBtn'; nextBtn.className = 'carousel-btn carousel-next';
        nextBtn.innerHTML = '<i class="fas fa-chevron-right"></i>';
        nextBtn.onclick = (e) => { e.stopPropagation(); navigateCarousel(1); };
        document.getElementById('previewOverlay').appendChild(nextBtn);
    }
    
    prevBtn.style.display = currentPreviewIndex > 0 ? 'flex' : 'none';
    nextBtn.style.display = (currentPreviewIndex < previewFiles.length - 1 && currentPreviewIndex !== -1) ? 'flex' : 'none';
}

function navigateCarousel(dir) {
    const newIdx = currentPreviewIndex + dir;
    if (newIdx >= 0 && newIdx < previewFiles.length) {
        const file = previewFiles[newIdx];
        openPreview(file.path, file.ext);
    }
}

document.addEventListener('keydown', (e) => {
    if (document.getElementById('previewOverlay').classList.contains('hidden')) return;
    if (e.key === 'ArrowLeft') navigateCarousel(-1);
    if (e.key === 'ArrowRight') navigateCarousel(1);
});

function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebar-overlay');
    if (!sidebar) return;
    
    const isActive = sidebar.classList.toggle('mobile-active');
    if (overlay) overlay.classList.toggle('active', isActive);
}

// ── Dashboard & Health Logic ──
let statsInterval = null;

function initHealthChart() {
    const ctx = document.getElementById('healthChart')?.getContext('2d');
    if (!ctx) return;

    if (healthChart) healthChart.destroy();

    healthChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: Array(20).fill(''),
            datasets: [
                {
                    label: 'CPU %',
                    data: Array(20).fill(0),
                    borderColor: '#10b981',
                    backgroundColor: 'rgba(16, 185, 129, 0.1)',
                    fill: true,
                    tension: 0.4,
                    borderWidth: 2,
                    pointRadius: 0
                },
                {
                    label: 'RAM %',
                    data: Array(20).fill(0),
                    borderColor: '#6366f1',
                    backgroundColor: 'rgba(99, 102, 241, 0.1)',
                    fill: true,
                    tension: 0.4,
                    borderWidth: 2,
                    pointRadius: 0
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 800 },
            scales: {
                y: { min: 0, max: 100, display: false },
                x: { display: false }
            },
            plugins: { legend: { display: false } }
        }
    });
}

function startStatsPolling() {
    if (statsInterval) clearInterval(statsInterval);
    statsInterval = setInterval(async () => {
        try {
            const res = await fetch('/api/stats/realtime');
            if (!res.ok) return;
            const data = await res.json();
            
            // Update Chart
            if (healthChart) {
                healthChart.data.datasets[0].data.push(data.cpu_percent);
                healthChart.data.datasets[0].data.shift();
                healthChart.data.datasets[1].data.push(data.ram_percent);
                healthChart.data.datasets[1].data.shift();
                healthChart.update('none');
            }
            
            // Update UI Text
            const uptimeEl = document.getElementById('uptime-val');
            if (uptimeEl) uptimeEl.innerText = data.uptime;
            const ramEl = document.getElementById('ram-details');
            if (ramEl) ramEl.innerText = `${data.ram_used} / ${data.ram_total}`;
        } catch(e) {}
    }, 2000);
}

function stopStatsPolling() {
    if (statsInterval) clearInterval(statsInterval);
    statsInterval = null;
}

// ── Vault & Security ──
async function submitVaultAction() {
    const row = Array.from(selectedRows)[0];
    const pass = document.getElementById('vaultPassword').value;
    if (!pass) return showToast("Mot de passe requis", "error");

    const isVault = row.dataset.isvault === 'true';
    const endpoint = isVault ? '/vault/unlock' : '/vault/create';
    
    const fd = new FormData();
    fd.append('filepath', row.dataset.path);
    fd.append('password', pass);

    const btn = document.getElementById('vaultActionBtn');
    btn.disabled = true;
    btn.innerText = 'Traitement...';

    const res = await fetch(endpoint, { method: 'POST', body: fd });
    if (res.ok) {
        showToast(isVault ? "Coffre déverrouillé" : "Fichier sécurisé");
        hideDialog('vaultModal');
        navigateTo(window.location.href, false);
    } else {
        const data = await res.json();
        showToast(data.detail || "Échec de l'opération", "error");
    }
    btn.disabled = false;
    btn.innerText = isVault ? 'Déverrouiller' : 'Sécuriser';
}

// ── External Sharing ──
async function generateShareLink() {
    const row = Array.from(selectedRows)[0];
    const fd = new FormData();
    fd.append('filepath', row.dataset.path);
    
    const btn = document.getElementById('generateShareBtn');
    btn.innerText = 'Génération...';

    const res = await fetch('/share/external', { method: 'POST', body: fd });
    if (res.ok) {
        const data = await res.json();
        document.getElementById('shareExternalInput').value = data.link;
        document.getElementById('shareLinkContainer').classList.remove('hidden');
        btn.classList.add('hidden');
    }
}

function copyToClipboard(id) {
    const input = document.getElementById(id);
    input.select();
    document.execCommand('copy');
    showToast("Lien copié !");
}

// ── Maintenance ──
async function runSystemUpdate() {
    if (!confirm("Voulez-vous lancer la mise à jour Git ? Le système pourrait nécessiter un redémarrage manuel.")) return;
    const res = await fetch('/admin/system/update', { method: 'POST' });
    const data = await res.json();
    showToast(data.msg, data.status === 'ok' ? 'info' : 'error');
}

async function toggleNASService(serviceName, isEnabled) {
    try {
        const formData = new FormData();
        formData.append('name', serviceName);
        formData.append('enabled', isEnabled);
        
        const res = await fetch('/settings/services', {
            method: 'POST',
            body: formData
        });
        
        const data = await res.json();
        if (data.status === 'success') {
            showToast(data.message, 'success');
        } else {
            showToast("Erreur lors de l'action sur le service", 'error');
        }
    } catch (e) {
        console.error("Service toggle failed", e);
        showToast("Erreur de connexion au serveur", 'error');
    }
}

// ── Real-time Monitoring & Dashboard ──
let statsPollingInterval = null;
const originalSwitchTab = switchTab;
window.switchTab = function(evt, tabId) {
    if (typeof originalSwitchTab === 'function') originalSwitchTab(evt, tabId);
    if (tabId === 'tab-system') {
        initHealthChart();
        startStatsPolling();
    } else {
        stopStatsPolling();
    }
};

function initHealthChart() {
    const ctx = document.getElementById('healthChart')?.getContext('2d');
    if (!ctx) return;
    if (healthChart) healthChart.destroy();

    healthChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: Array(20).fill(''),
            datasets: [
                {
                    label: 'CPU %',
                    data: Array(20).fill(0),
                    borderColor: '#10b981',
                    backgroundColor: 'rgba(16, 185, 129, 0.1)',
                    fill: true,
                    tension: 0.4,
                    borderWidth: 2,
                    pointRadius: 0
                },
                {
                    label: 'RAM %',
                    data: Array(20).fill(0),
                    borderColor: '#6366f1',
                    backgroundColor: 'rgba(99, 102, 241, 0.1)',
                    fill: true,
                    tension: 0.4,
                    borderWidth: 2,
                    pointRadius: 0
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                y: { min: 0, max: 100, display: false },
                x: { display: false }
            },
            animation: { duration: 1000 }
        }
    });
}

function startStatsPolling() {
    if (statsPollingInterval) return;
    updateHealthDashboard();
    statsPollingInterval = setInterval(updateHealthDashboard, 3000);
}

function stopStatsPolling() {
    if (statsPollingInterval) {
        clearInterval(statsPollingInterval);
        statsPollingInterval = null;
    }
}

async function updateHealthDashboard() {
    try {
        const res = await fetch('/api/stats/realtime');
        const stats = await res.json();
        
        // Update Uptime and RAM
        const uptimeEl = document.getElementById('uptime-val');
        if (uptimeEl) uptimeEl.textContent = stats.uptime;
        
        const ramEl = document.getElementById('ram-details');
        if (ramEl) ramEl.textContent = `${stats.ram_percent}% (${stats.ram_used})`;
        
        // Update Chart
        if (healthChart) {
            healthChart.data.datasets[0].data.push(stats.cpu_percent);
            healthChart.data.datasets[0].data.shift();
            healthChart.data.datasets[1].data.push(stats.ram_percent);
            healthChart.data.datasets[1].data.shift();
            healthChart.update('none');
        }
    } catch (e) {
        console.error("Stats fetch failed", e);
    }
}
