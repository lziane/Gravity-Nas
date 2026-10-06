(() => {
    const state = { path: window.CURRENT_PATH || '', items: [], breadcrumbs: [], selected: new Set(), view: localStorage.getItem('gravity_view') || 'list', sort: localStorage.getItem('gravity_sort') || 'name', filter: 'all' };
    const imageExtensions = new Set(['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg']);

    const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[char]);
    const encodePath = (path) => path.split('/').map(encodeURIComponent).join('/');
    const iconFor = (item) => item.is_dir ? 'fa-folder' : (imageExtensions.has(item.extension) ? 'fa-image' : 'fa-file-lines');

    async function load(path = state.path, push = true) {
        const response = await fetch(`/api/files?path=${encodeURIComponent(path)}&_=${Date.now()}`, { cache: 'no-store' });
        if (!response.ok) throw new Error('Impossible de charger ce dossier');
        const payload = await response.json();
        const data = payload.data || payload;
        state.path = data.path || '';
        state.items = data.items || [];
        state.breadcrumbs = data.breadcrumbs || [];
        state.selected.clear();
        if (push) history.pushState({ explorerPath: state.path }, '', state.path ? `/?path=${encodeURIComponent(state.path)}` : '/');
        render(data.breadcrumbs || []);
    }

    function render(breadcrumbs) {
        const zone = document.getElementById('file-grid-zone');
        const grid = document.getElementById('fileGrid');
        if (!zone || !grid) return;
        const query = (document.getElementById('searchInput')?.value || '').trim().toLowerCase();
        const visible = state.items.filter((item) => item.name.toLowerCase().includes(query) && matchesFilter(item)).sort(sortItems);
        zone.classList.toggle('explorer-grid-view', state.view === 'grid');
        zone.classList.toggle('explorer-has-items', visible.length > 0);
        grid.innerHTML = visible.map((item, index) => {
            const selected = state.selected.has(item.relative_path);
            return `<tr class="file-row explorer-item${selected ? ' active-selection' : ''}" style="animation-delay:${Math.min(index * 18, 240)}ms" data-path="${escapeHtml(item.relative_path)}" data-isdir="${item.is_dir}" data-ext="${escapeHtml(item.extension || '')}" data-extension="${escapeHtml(item.extension || '')}" tabindex="0" draggable="true">
                <td><div class="explorer-name"><span class="explorer-icon ${item.is_dir ? 'folder' : ''}"><i class="fas ${iconFor(item)}"></i></span><span class="explorer-label"><strong>${escapeHtml(item.name)}</strong><small>${item.is_dir ? 'Dossier' : escapeHtml(item.extension || 'Fichier')}</small></span></div></td>
                <td class="explorer-meta">${escapeHtml(item.modified || '-')}</td>
                <td class="explorer-meta">${escapeHtml(item.size || '-')}</td>
                <td class="explorer-meta">Moi</td>
                <td class="explorer-actions"><button class="explorer-more" type="button" aria-label="Actions" title="Actions"><i class="fas fa-ellipsis"></i></button></td>
            </tr>`;
        }).join('');
        if (!visible.length) grid.innerHTML = `<tr><td colspan="5" class="explorer-empty"><i class="fas fa-folder-open"></i><strong>${query || state.filter !== 'all' ? 'Aucun résultat' : 'Dossier vide'}</strong><span>${query || state.filter !== 'all' ? 'Modifiez votre recherche ou votre filtre.' : 'Importez un fichier ou créez un dossier pour commencer.'}</span></td></tr>`;
        updateBreadcrumbs(breadcrumbs.length ? breadcrumbs : state.breadcrumbs);
        updateSelectionBar();
        updateExplorerStatus(visible.length);
    }

    function matchesFilter(item) {
        if (state.filter === 'folders') return item.is_dir;
        if (state.filter === 'images') return imageExtensions.has(item.extension);
        if (state.filter === 'documents') return ['.pdf', '.txt', '.md', '.doc', '.docx', '.xls', '.xlsx'].includes(item.extension);
        if (state.filter === 'media') return ['.mp4', '.mov', '.webm', '.mp3', '.wav'].includes(item.extension);
        return true;
    }

    function sortItems(left, right) {
        if (left.is_dir !== right.is_dir) return left.is_dir ? -1 : 1;
        if (state.sort === 'size') return (right.size_bytes || 0) - (left.size_bytes || 0) || left.name.localeCompare(right.name);
        if (state.sort === 'modified') return (right.modified_ts || 0) - (left.modified_ts || 0) || left.name.localeCompare(right.name);
        return left.name.localeCompare(right.name, undefined, { sensitivity: 'base', numeric: true });
    }

    function updateExplorerStatus(visibleCount) {
        const status = document.getElementById('explorer-status');
        if (status) status.textContent = `${visibleCount} élément${visibleCount > 1 ? 's' : ''}`;
    }

    function bindDropTarget(element, callback) {
        let dragDepth = 0;
        element.addEventListener('dragenter', (event) => {
            event.preventDefault();
            dragDepth += 1;
            element.classList.add('drag-target');
        });
        element.addEventListener('dragover', (event) => {
            event.preventDefault();
            event.dataTransfer.dropEffect = 'move';
        });
        element.addEventListener('dragleave', (event) => {
            if (event.relatedTarget && element.contains(event.relatedTarget)) return;
            dragDepth = Math.max(0, dragDepth - 1);
            if (!dragDepth) element.classList.remove('drag-target');
        });
        element.addEventListener('drop', async (event) => {
            dragDepth = 0;
            element.classList.remove('drag-target');
            await callback(event);
        });
    }

    function clearDragVisuals() {
        document.querySelectorAll('.drag-target, .is-dragging').forEach((element) => {
            element.classList.remove('drag-target', 'is-dragging');
        });
    }

    function installExplorerTools() {
        const toolbar = document.getElementById('toolbar-actions');
        if (!toolbar || document.getElementById('explorer-tools')) return;
        const tools = document.createElement('div');
        tools.id = 'explorer-tools';
        tools.innerHTML = `<select id="explorer-filter" class="explorer-select" aria-label="Filtrer les fichiers"><option value="all">Tous</option><option value="folders">Dossiers</option><option value="images">Images</option><option value="documents">Documents</option><option value="media">Médias</option></select><select id="explorer-sort" class="explorer-select" aria-label="Trier les fichiers"><option value="name">Nom</option><option value="modified">Modifié</option><option value="size">Taille</option></select><button id="explorer-refresh" class="explorer-tool-button" type="button" title="Actualiser"><i class="fas fa-rotate"></i></button>`;
        toolbar.insertBefore(tools, toolbar.firstChild);
        const sort = document.getElementById('explorer-sort');
        sort.value = state.sort;
        sort.addEventListener('change', () => { state.sort = sort.value; localStorage.setItem('gravity_sort', state.sort); render([]); });
        document.getElementById('explorer-filter').addEventListener('change', (event) => { state.filter = event.target.value; render([]); });
        document.getElementById('explorer-refresh').addEventListener('click', () => load(state.path, false).catch((error) => window.showToast?.(error.message, 'error')));
    }

    function updateBreadcrumbs(breadcrumbs) {
        const target = document.getElementById('breadcrumb-trail');
        if (!target) return;
        target.innerHTML = `<button class="explorer-nav-home" type="button" title="Mon stockage"><i class="fas fa-house"></i></button>` + breadcrumbs.map((crumb) => `<i class="fas fa-chevron-right explorer-separator"></i><button class="explorer-crumb" type="button" data-path="${escapeHtml(crumb.path)}">${escapeHtml(crumb.name)}</button>`).join('');
        target.querySelectorAll('.explorer-crumb').forEach((link) => link.addEventListener('click', (event) => { event.preventDefault(); load(link.dataset.path); }));
        target.querySelector('.explorer-nav-home')?.addEventListener('click', () => load(''));
        target.querySelectorAll('button').forEach((button) => {
            bindDropTarget(button, (event) => dropTo(event, button.dataset.path || ''));
        });
    }

    function updateSelectionBar() {
        let bar = document.getElementById('explorer-command-bar');
        if (!bar) {
            bar = document.createElement('div'); bar.id = 'explorer-command-bar'; bar.className = 'explorer-command-bar';
            bar.innerHTML = `<span id="explorer-selection-count"></span><button data-action="share" title="Partager"><i class="fas fa-share-nodes"></i></button><button data-action="download" title="Télécharger"><i class="fas fa-download"></i></button><button data-action="rename" title="Renommer"><i class="fas fa-pen"></i></button><button data-action="move" title="Déplacer"><i class="fas fa-folder-open"></i></button><button data-action="delete" class="danger" title="Mettre à la corbeille"><i class="fas fa-trash"></i></button><button data-action="clear" title="Annuler"><i class="fas fa-xmark"></i></button>`;
            document.body.appendChild(bar);
            bar.addEventListener('click', handleCommand);
        }
        bar.classList.toggle('visible', state.selected.size > 0);
        const count = document.getElementById('explorer-selection-count');
        if (count) count.textContent = `${state.selected.size} sélectionné${state.selected.size > 1 ? 's' : ''}`;
    }

    function syncSelectionClasses() {
        document.querySelectorAll('#fileGrid .explorer-item').forEach((row) => {
            row.classList.toggle('active-selection', state.selected.has(row.dataset.path));
        });
        updateSelectionBar();
    }

    async function handleCommand(event) {
        const action = event.target.closest('[data-action]')?.dataset.action;
        if (!action) return;
        const paths = [...state.selected];
        if (action === 'clear') state.selected.clear();
        if (action === 'share') {
            if (paths.length === 1) openShareMenu(paths[0]);
            else window.showToast?.('Sélectionnez un seul élément pour le partager.', 'error');
        }
        if (action === 'download') paths.forEach((path) => { window.location.href = `/download/${encodePath(path)}`; });
        if (action === 'rename' && paths.length === 1) {
            const name = window.prompt('Nouveau nom', paths[0].split('/').pop());
            if (name) await request('/rename', { old_name: paths[0], new_name: name });
        }
        if (action === 'move') {
            if (window.openMovePicker) {
                window.openMovePicker();
                window.pendingExplorerMove = paths;
            }
        }
        if (action === 'delete' && window.confirm(`Mettre ${paths.length} élément(s) à la corbeille ?`)) {
            await request('/delete/batch', { paths: JSON.stringify(paths) });
            const deleted = new Set(paths);
            state.items = state.items.filter((item) => !deleted.has(item.relative_path));
            state.selected.clear();
            render(state.breadcrumbs);
        }
        updateSelectionBar();
    }

    async function dropTo(event, destination) {
        event.preventDefault();
        event.currentTarget?.classList.remove('drag-target');
        const source = event.dataTransfer.getData('text/plain');
        if (!source || source === destination || destination.startsWith(`${source}/`)) return;
        try { await request('/move', { filepath: source, destination }); }
        catch (error) { window.showToast?.(error.message, 'error'); }
    }

    async function pinToFavorite(event) {
        event.preventDefault();
        const target = event.currentTarget;
        clearDragVisuals();
        const source = event.dataTransfer.getData('text/plain');
        if (!source) return;
        const body = new FormData();
        body.append('filepath', source);
        body.append('meta_key', 'is_pinned');
        body.append('meta_value', '1');
        try {
            const response = await fetch('/file/meta', { method: 'POST', body });
            if (!response.ok) throw new Error('Impossible d’épingler cet élément');
            addFavoriteLink(source);
            window.showToast?.('Élément ajouté aux favoris');
            target.classList.add('favorite-pinned');
        } catch (error) {
            window.showToast?.(error.message, 'error');
        }
    }

    function addFavoriteLink(path) {
        const sidebarNav = document.getElementById('sidebar-nav');
        const dropZone = document.getElementById('sidebarDropZone');
        if (!sidebarNav || !dropZone || sidebarNav.querySelector(`[data-favorite-path="${CSS.escape(path)}"]`)) return;
        const wrapper = document.createElement('div');
        wrapper.className = 'relative group';
        wrapper.dataset.favoritePath = path;
        wrapper.innerHTML = `<a href="/?path=${encodeURIComponent(path)}" data-favorite="true" data-favorite-path="${escapeHtml(path)}" class="spa-link flex items-center px-3 py-2 rounded-lg text-[13px] font-medium transition-all" style="color:var(--text-secondary)"><i class="fas fa-thumbtack mr-2.5 w-4 text-center text-[9px]" style="color:var(--accent)"></i><span class="truncate">${escapeHtml(path.split('/').pop())}</span></a>`;
        sidebarNav.insertBefore(wrapper, dropZone);
        bindFavoriteDrop(wrapper.querySelector('a'));
    }

    function removeFavoriteLink(path) {
        document.querySelector(`[data-favorite-path="${CSS.escape(path)}"]`)?.closest('.group')?.remove();
    }

    function bindFavoriteDrop(link) {
        if (!link || link.dataset.dropBound) return;
        link.dataset.dropBound = 'true';
        bindDropTarget(link, (event) => pinToFavorite(event));
    }

    function openShareMenu(path) {
        const name = path.split('/').pop();
        const nameField = document.getElementById('sendItemName');
        const pathField = document.getElementById('sendInputFile');
        if (nameField && pathField && typeof window.showDialog === 'function') {
            nameField.textContent = name;
            pathField.value = path;
            window.showDialog('sendModal');
            return;
        }
        window.showToast?.(`Élément prêt à être partagé : ${name}`);
    }

    function showActionMenu(row, event) {
        document.querySelector('.explorer-action-menu')?.remove();
        const menu = document.createElement('div');
        menu.className = 'explorer-action-menu';
            menu.innerHTML = `<button data-menu-action="open"><i class="fas fa-arrow-up-right-from-square"></i>Ouvrir</button><button data-menu-action="share"><i class="fas fa-share-nodes"></i>Partager</button><button data-menu-action="download"><i class="fas fa-download"></i>Télécharger</button><button data-menu-action="rename"><i class="fas fa-pen"></i>Renommer</button><button data-menu-action="move"><i class="fas fa-folder-open"></i>Déplacer</button><button data-menu-action="delete" class="danger"><i class="fas fa-trash"></i>Mettre à la corbeille</button>`;
        menu.style.left = `${Math.min(event.clientX, window.innerWidth - 210)}px`;
        menu.style.top = `${Math.min(event.clientY, window.innerHeight - 250)}px`;
        document.body.appendChild(menu);
        menu.addEventListener('click', async (menuEvent) => {
            const action = menuEvent.target.closest('[data-menu-action]')?.dataset.menuAction;
            state.selected.clear(); state.selected.add(row.dataset.path); syncSelectionClasses(); menu.remove();
            try {
                if (action === 'open') row.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
                if (action === 'share') openShareMenu(row.dataset.path);
                if (action === 'download') window.location.href = `/download/${encodePath(row.dataset.path)}`;
                if (action === 'rename' || action === 'move' || action === 'delete') {
                    await handleCommand({ target: { closest: () => ({ dataset: { action } }) } });
                }
            } catch (error) {
                window.showToast?.(error.message, 'error');
            }
        });
    }

    async function request(url, values) {
        const body = new FormData(); Object.entries(values).forEach(([key, value]) => body.append(key, value));
        const response = await fetch(url, { method: 'POST', body });
        if (!response.ok) { const payload = await response.json().catch(() => ({})); throw new Error(payload.detail || 'Action impossible'); }
        await load(state.path, false);
    }

    function bindRows() {
        document.querySelectorAll('#fileGrid .explorer-item').forEach((row) => {
            row.onclick = null;
            row.ondblclick = null;
            row.oncontextmenu = null;
            row.addEventListener('click', (event) => {
                if (event.target.closest('.explorer-more')) {
                    state.selected.clear();
                    state.selected.add(row.dataset.path);
                    syncSelectionClasses();
                    return;
                }
                if (!(event.ctrlKey || event.metaKey || event.shiftKey)) state.selected.clear();
                if (state.selected.has(row.dataset.path)) state.selected.delete(row.dataset.path); else state.selected.add(row.dataset.path);
                syncSelectionClasses();
            });
            row.addEventListener('dblclick', (event) => {
                event.preventDefault();
                event.stopPropagation();
                if (row.dataset.isdir === 'true') load(row.dataset.path).catch((error) => window.showToast?.(error.message, 'error'));
                else if (window.openPreview) window.openPreview(row.dataset.path, row.dataset.ext || '');
                else window.open(`/preview/${encodePath(row.dataset.path)}`, '_blank', 'noopener');
            });
            row.addEventListener('dragstart', (event) => { event.dataTransfer.setData('text/plain', row.dataset.path); event.dataTransfer.effectAllowed = 'move'; row.classList.add('is-dragging'); });
            row.addEventListener('dragend', clearDragVisuals);
            if (row.dataset.isdir === 'true') bindDropTarget(row, (event) => dropTo(event, row.dataset.path));
            row.querySelector('.explorer-more')?.addEventListener('click', (event) => { event.preventDefault(); event.stopPropagation(); showActionMenu(row, event); });
            row.addEventListener('keydown', (event) => {
                if (event.key === 'Enter') row.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
            });
        });
    }

    const originalRender = render;
    render = (breadcrumbs) => { originalRender(breadcrumbs); bindRows(); };
    window.navigateTo = (url) => load(new URL(url, window.location.origin).searchParams.get('path') || '');
    window.toggleView = () => { state.view = state.view === 'grid' ? 'list' : 'grid'; localStorage.setItem('gravity_view', state.view); render([]); };

    document.addEventListener('DOMContentLoaded', () => {
        installExplorerTools();
        document.getElementById('searchInput')?.addEventListener('input', () => render([]));
        document.addEventListener('click', (event) => {
            const link = event.target.closest('a.spa-link');
            if (!link || event.defaultPrevented || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
            const target = new URL(link.href, window.location.origin);
            if (target.origin !== window.location.origin) return;
            event.preventDefault();
            load(target.searchParams.get('path') || '');
        });
        window.addEventListener('popstate', (event) => load(event.state?.explorerPath || '', false));
        load(state.path, false).catch((error) => window.showToast?.(error.message, 'error'));
        document.addEventListener('keydown', (event) => {
            if (['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target.tagName)) return;
            if (event.key === 'Escape') { document.querySelector('.explorer-action-menu')?.remove(); state.selected.clear(); syncSelectionClasses(); }
            if (event.key === 'r' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); load(state.path, false); }
        });
        document.addEventListener('click', (event) => {
            if (!event.target.closest('.explorer-action-menu, .explorer-more')) document.querySelector('.explorer-action-menu')?.remove();
        });
        const sidebar = document.getElementById('sidebar');
        sidebar?.querySelectorAll('a[data-favorite="true"]').forEach(bindFavoriteDrop);
        const pinZone = document.getElementById('sidebarDropZone');
        pinZone && bindDropTarget(pinZone, async (event) => {
            const source = event.dataTransfer.getData('text/plain');
            if (!source) return;
            const body = new FormData(); body.append('filepath', source); body.append('meta_key', 'is_pinned'); body.append('meta_value', '1');
            const response = await fetch('/file/meta', { method: 'POST', body });
            if (!response.ok) throw new Error('Impossible d’épingler cet élément');
            addFavoriteLink(source);
            window.showToast?.('Élément ajouté aux favoris');
        });
        document.getElementById('file-grid-zone')?.addEventListener('click', (event) => {
            if (!event.target.closest('.explorer-item, .explorer-action-menu, button, a, input, select')) {
                state.selected.clear();
                syncSelectionClasses();
            }
        });
        window.quickUnpin = async (path) => {
            const body = new FormData();
            body.append('filepath', path);
            body.append('meta_key', 'is_pinned');
            body.append('meta_value', '0');
            const response = await fetch('/file/meta', { method: 'POST', body });
            if (!response.ok) {
                window.showToast?.('Impossible de retirer ce favori', 'error');
                return;
            }
            removeFavoriteLink(path);
            window.showToast?.('Élément retiré des favoris');
        };
        document.addEventListener('dragend', clearDragVisuals);
        document.addEventListener('drop', clearDragVisuals);
    });
})();
