document.addEventListener('DOMContentLoaded', () => {
    // Mode Switcher Tabs
    const tabSingle = document.getElementById('tab-single');
    const tabBatch = document.getElementById('tab-batch');
    const singleCard = document.getElementById('single-mode-card');
    const batchCard = document.getElementById('batch-mode-card');

    // Search Elements
    const searchForm = document.getElementById('search-form');
    const searchQueryInput = document.getElementById('search-query');
    const searchTypeSelect = document.getElementById('search-type');
    const btnSearch = document.getElementById('btn-search');
    const searchResultsContainer = document.getElementById('search-results-container');
    const searchResultsCount = document.getElementById('search-results-count');
    const searchResultsGrid = document.getElementById('search-results-grid');
    const btnClearSearch = document.getElementById('btn-clear-search');

    // Single Form Elements
    const form = document.getElementById('tagger-form');
    const filePathInput = document.getElementById('file_path');
    const urlInput = document.getElementById('url'); // Textarea
    const btnBrowse = document.getElementById('btn-browse');
    const filePicker = document.getElementById('file-picker');
    const btnPreview = document.getElementById('btn-preview');
    const btnEmbed = document.getElementById('btn-embed');

    // Batch Form Elements
    const batchForm = document.getElementById('batch-tagger-form');
    const folderPathInput = document.getElementById('folder_path');
    const volumeUrlInput = document.getElementById('volume_url');
    const chkDeleteCbr = document.getElementById('chk-delete-cbr');
    const btnBrowseFolder = document.getElementById('btn-browse-folder');
    const btnBatchPreview = document.getElementById('btn-batch-preview');
    const btnBatchEmbed = document.getElementById('btn-batch-embed');

    // Multi-Issue Modal Elements
    const modal = document.getElementById('multi-issue-modal');
    const modalSubtitle = document.getElementById('modal-subtitle');
    const modalIssueList = document.getElementById('modal-issue-list');
    const modalClose = document.getElementById('modal-close');
    const modalCancelBtn = document.getElementById('modal-cancel-btn');
    const modalSaveBtn = document.getElementById('modal-save-btn');
    let activeModalRowIdx = null;

    // Status & Result Cards
    const statusBox = document.getElementById('status-box');
    const statusIcon = document.getElementById('status-icon');
    const statusTitle = document.getElementById('status-title');
    const statusMessage = document.getElementById('status-message');

    const resultCard = document.getElementById('result-card');
    const resultBadge = document.getElementById('result-badge');

    const metaSeries = document.getElementById('meta-series');
    const metaNumber = document.getElementById('meta-number');
    const metaTitle = document.getElementById('meta-title');
    const metaPublisher = document.getElementById('meta-publisher');
    const metaDate = document.getElementById('meta-date');
    const metaVolume = document.getElementById('meta-volume');
    const metaSummary = document.getElementById('meta-summary');
    const creditsContainer = document.getElementById('credits-container');
    const charactersContainer = document.getElementById('characters-container');
    const teamsContainer = document.getElementById('teams-container');
    const storyArcsContainer = document.getElementById('story-arcs-container');

    // Batch Result & Progress Elements
    const batchResultCard = document.getElementById('batch-result-card');
    const batchResultBadge = document.getElementById('batch-result-badge');
    const progressText = document.getElementById('progress-text');
    const progressPercent = document.getElementById('progress-percent');
    const progressFill = document.getElementById('progress-fill');
    const batchLogBox = document.getElementById('batch-log-box');
    const batchPreviewTbody = document.getElementById('batch-preview-tbody');

    let selectedFileObject = null;
    let currentPreviewItems = [];
    let currentIssuesList = [];

    // Tab Switching Logic
    tabSingle.addEventListener('click', () => {
        tabSingle.classList.add('active');
        tabBatch.classList.remove('active');
        singleCard.classList.remove('hidden');
        batchCard.classList.add('hidden');
        batchResultCard.classList.add('hidden');
    });

    tabBatch.addEventListener('click', () => {
        tabBatch.classList.add('active');
        tabSingle.classList.remove('active');
        batchCard.classList.remove('hidden');
        singleCard.classList.add('hidden');
        resultCard.classList.add('hidden');
    });

    function showStatus(type, title, message) {
        statusBox.className = `status-box ${type}`;
        if (type === 'info') statusIcon.textContent = '⏳';
        else if (type === 'success') statusIcon.textContent = '✅';
        else if (type === 'error') statusIcon.textContent = '⚠️';

        statusTitle.textContent = title;
        statusMessage.textContent = message;
        statusBox.classList.remove('hidden');
    }

    function appendLog(type, text) {
        const time = new Date().toLocaleTimeString();
        const line = document.createElement('div');
        line.className = `log-line ${type}`;
        line.textContent = `[${time}] ${text}`;
        batchLogBox.appendChild(line);
        batchLogBox.scrollTop = batchLogBox.scrollHeight;
    }

    function updateProgress(current, total) {
        const percent = total > 0 ? Math.round((current / total) * 100) : 0;
        progressText.textContent = `Processing: ${current} / ${total} files`;
        progressPercent.textContent = `${percent}%`;
        progressFill.style.width = `${percent}%`;
    }

    // 0. Search Engine Logic
    searchForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const query = searchQueryInput.value.trim();
        const searchType = searchTypeSelect.value;

        if (!query) return;

        btnSearch.disabled = true;
        showStatus('info', 'Searching Comic Vine', `Searching database for '${query}'...`);

        try {
            const res = await fetch('/api/search', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query, type: searchType })
            });
            const data = await res.json();

            if (!res.ok || data.error) {
                throw new Error(data.error || 'Failed to execute search.');
            }

            renderSearchResults(data.results || [], query);
            showStatus('success', 'Search Complete', `Found ${data.count} result(s) for '${query}'.`);
        } catch (err) {
            showStatus('error', 'Search Failed', err.message);
        } finally {
            btnSearch.disabled = false;
        }
    });

    function renderSearchResults(results, query) {
        searchResultsGrid.innerHTML = '';
        searchResultsCount.textContent = `Search Results for '${query}' (${results.length})`;

        if (results.length === 0) {
            searchResultsGrid.innerHTML = '<p class="help-text">No results found. Try a different title or search query.</p>';
            searchResultsContainer.classList.remove('hidden');
            return;
        }

        results.forEach(item => {
            const card = document.createElement('div');
            card.className = 'search-result-card';

            const placeholderImg = 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="60" height="85" viewBox="0 0 60 85"><rect width="60" height="85" fill="%23040810"/><text x="50%" y="50%" fill="%2394a3b8" dominant-baseline="middle" text-anchor="middle" font-size="20">📚</text></svg>';
            const imgSrc = item.image || placeholderImg;
            const typeBadgeClass = item.type === 'volume' ? 'volume' : 'issue';

            let actionButtonsHtml = '';
            if (item.type === 'volume') {
                actionButtonsHtml = `<button type="button" class="btn-use-url btn-use-volume" data-url="${item.url}">📁 Use for Batch Folder</button>`;
            } else {
                actionButtonsHtml = `
                    <button type="button" class="btn-use-url btn-use-single" data-url="${item.url}">📄 Use for Single File</button>
                    <button type="button" class="btn-use-url btn-add-tpb" data-url="${item.url}">➕ Add to TPB</button>
                `;
            }

            card.innerHTML = `
                <img src="${imgSrc}" class="search-thumb" alt="Cover" />
                <div class="search-info">
                    <span class="search-title">${item.title}</span>
                    <span class="search-type-badge ${typeBadgeClass}">${item.type_label} ${item.year ? '(' + item.year + ')' : ''}</span>
                    ${actionButtonsHtml}
                </div>
            `;
            searchResultsGrid.appendChild(card);
        });

        // Search Action Click Handlers
        searchResultsGrid.querySelectorAll('.btn-use-volume').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const url = e.target.getAttribute('data-url');
                volumeUrlInput.value = url;
                tabBatch.click();
                showStatus('success', 'URL Selected', `Set Volume URL to '${url}'!`);
            });
        });

        searchResultsGrid.querySelectorAll('.btn-use-single').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const url = e.target.getAttribute('data-url');
                urlInput.value = url;
                tabSingle.click();
                showStatus('success', 'URL Selected', `Set Single Issue URL to '${url}'!`);
            });
        });

        searchResultsGrid.querySelectorAll('.btn-add-tpb').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const url = e.target.getAttribute('data-url');
                const existing = urlInput.value.trim();
                urlInput.value = existing ? `${existing}\n${url}` : url;
                tabSingle.click();
                showStatus('success', 'URL Added', `Appended issue URL to TPB list!`);
            });
        });

        searchResultsContainer.classList.remove('hidden');
    }

    btnClearSearch.addEventListener('click', () => {
        searchResultsContainer.classList.add('hidden');
        searchQueryInput.value = '';
    });

    function renderComic(comic) {
        metaSeries.textContent = comic.series || 'N/A';
        metaNumber.textContent = comic.number ? `#${comic.number}` : 'N/A';
        metaTitle.textContent = comic.title || 'N/A';
        metaPublisher.textContent = comic.publisher || 'N/A';
        
        if (comic.year) {
            const m = comic.month ? String(comic.month).padStart(2, '0') : '01';
            const d = comic.day ? String(comic.day).padStart(2, '0') : '01';
            metaDate.textContent = `${comic.year}-${m}-${d}`;
        } else {
            metaDate.textContent = 'N/A';
        }

        metaVolume.textContent = comic.volume ? `Vol. ${comic.volume}` : 'N/A';
        metaSummary.textContent = comic.summary || 'No summary available.';

        // Render Creator Credits
        creditsContainer.innerHTML = '';
        const roles = [
            { key: 'writers', label: 'Writer' },
            { key: 'pencillers', label: 'Penciller' },
            { key: 'inkers', label: 'Inker' },
            { key: 'colorists', label: 'Colorist' },
            { key: 'letterers', label: 'Letterer' },
            { key: 'cover_artists', label: 'Cover Artist' }
        ];

        let creditCount = 0;
        roles.forEach(r => {
            const names = comic[r.key] || [];
            names.forEach(name => {
                creditCount++;
                const chip = document.createElement('div');
                chip.className = 'credit-chip';
                chip.innerHTML = `<span class="credit-role">${r.label}:</span> ${name}`;
                creditsContainer.appendChild(chip);
            });
        });

        if (creditCount === 0) {
            creditsContainer.innerHTML = '<span class="help-text">No creator credits found.</span>';
        }

        // Render Characters
        charactersContainer.innerHTML = '';
        const characters = comic.characters || [];
        if (characters.length > 0) {
            characters.forEach(charName => {
                const chip = document.createElement('div');
                chip.className = 'character-chip';
                chip.textContent = charName;
                charactersContainer.appendChild(chip);
            });
        } else {
            charactersContainer.innerHTML = '<span class="help-text">No characters tagged.</span>';
        }

        // Render Teams
        teamsContainer.innerHTML = '';
        const teams = comic.teams || [];
        if (teams.length > 0) {
            teams.forEach(teamName => {
                const chip = document.createElement('div');
                chip.className = 'team-chip';
                chip.textContent = teamName;
                teamsContainer.appendChild(chip);
            });
        } else {
            teamsContainer.innerHTML = '<span class="help-text">No teams tagged.</span>';
        }

        // Render Story Arcs
        storyArcsContainer.innerHTML = '';
        const storyArcs = comic.story_arcs || [];
        if (storyArcs.length > 0) {
            storyArcs.forEach(arcName => {
                const chip = document.createElement('div');
                chip.className = 'arc-chip';
                chip.textContent = arcName;
                storyArcsContainer.appendChild(chip);
            });
        } else {
            storyArcsContainer.innerHTML = '<span class="help-text">No story arcs tagged.</span>';
        }

        resultCard.classList.remove('hidden');
    }

    function renderDetailsCard(comic, container) {
        if (!comic) {
            container.innerHTML = '<span class="help-text">No metadata available for this issue.</span>';
            return;
        }

        const dateStr = comic.year ? `${comic.year}-${String(comic.month||1).padStart(2,'0')}-${String(comic.day||1).padStart(2,'0')}` : 'N/A';
        
        let writersHtml = (comic.writers || []).map(w => `<span class="credit-chip"><span class="credit-role">Writer:</span> ${w}</span>`).join(' ');
        let pencillersHtml = (comic.pencillers || []).map(p => `<span class="credit-chip"><span class="credit-role">Penciller:</span> ${p}</span>`).join(' ');
        let charactersHtml = (comic.characters || []).map(c => `<span class="character-chip">${c}</span>`).join(' ');
        let teamsHtml = (comic.teams || []).map(t => `<span class="team-chip">${t}</span>`).join(' ');
        let storyArcsHtml = (comic.story_arcs || []).map(a => `<span class="arc-chip">${a}</span>`).join(' ');

        container.innerHTML = `
            <div class="details-card-inner">
                <div class="details-meta-grid">
                    <div class="meta-item"><span class="meta-label">Title</span><span class="meta-value">${comic.title || 'N/A'}</span></div>
                    <div class="meta-item"><span class="meta-label">Series</span><span class="meta-value">${comic.series || 'N/A'}</span></div>
                    <div class="meta-item"><span class="meta-label">Issue #</span><span class="meta-value">#${comic.number || 'N/A'}</span></div>
                    <div class="meta-item"><span class="meta-label">Release Date</span><span class="meta-value">${dateStr}</span></div>
                    <div class="meta-item"><span class="meta-label">Publisher</span><span class="meta-value">${comic.publisher || 'N/A'}</span></div>
                    <div class="meta-item"><span class="meta-label">Format / Count</span><span class="meta-value">${comic.format || 'Comic'} (${comic.count || 1} Issues)</span></div>
                </div>

                <div>
                    <h4 style="font-size:0.85rem; color:var(--text-secondary); margin-bottom:0.35rem;">Summary / Overview</h4>
                    <div class="summary-text" style="font-size:0.85rem; padding:0.75rem; white-space:pre-wrap;">${comic.summary || 'No summary available.'}</div>
                </div>

                ${writersHtml || pencillersHtml ? `
                <div>
                    <h4 style="font-size:0.85rem; color:var(--text-secondary); margin-bottom:0.35rem;">Creators (${(comic.writers||[]).length + (comic.pencillers||[]).length})</h4>
                    <div class="credits-grid">${writersHtml} ${pencillersHtml}</div>
                </div>` : ''}

                ${charactersHtml ? `
                <div>
                    <h4 style="font-size:0.85rem; color:var(--text-secondary); margin-bottom:0.35rem;">Characters Featured (${comic.characters.length})</h4>
                    <div class="credits-grid">${charactersHtml}</div>
                </div>` : ''}

                ${teamsHtml ? `
                <div>
                    <h4 style="font-size:0.85rem; color:var(--text-secondary); margin-bottom:0.35rem;">Teams Featured (${comic.teams.length})</h4>
                    <div class="credits-grid">${teamsHtml}</div>
                </div>` : ''}

                ${storyArcsHtml ? `
                <div>
                    <h4 style="font-size:0.85rem; color:var(--text-secondary); margin-bottom:0.35rem;">Story Arcs (${comic.story_arcs.length})</h4>
                    <div class="credits-grid">${storyArcsHtml}</div>
                </div>` : ''}
            </div>
        `;
    }

    function renderPreviewTable(items, issuesList) {
        batchPreviewTbody.innerHTML = '';
        items.forEach((item, idx) => {
            const tr = document.createElement('tr');
            tr.id = `preview-row-${idx}`;

            // Build manual issue select options
            let optionsHtml = '<option value="">-- Single Issue Select --</option>';
            if (issuesList && issuesList.length > 0) {
                issuesList.forEach(iss => {
                    const sel = (item.matched_url && item.matched_url === iss.url && (!item.matched_urls || item.matched_urls.length <= 1)) ? 'selected' : '';
                    optionsHtml += `<option value="${iss.url}" ${sel}>Issue #${iss.number}</option>`;
                });
            }

            const selectHtml = `
                <div style="display:flex; align-items:center; gap:0.25rem;">
                    <select class="tbl-select" data-idx="${idx}">${optionsHtml}</select>
                    <button type="button" class="btn-multi" data-idx="${idx}" title="Select multiple issues to merge for TPB/Collected edition">🧩 Multi</button>
                </div>
            `;

            let statusClass = 'unmatched';
            let statusText = 'UNMATCHED';

            if (item.matched_urls && item.matched_urls.length > 1) {
                statusClass = 'tpb';
                statusText = `COLLECTED (${item.matched_urls.length} ISSUES)`;
            } else if (item.status === 'manual') {
                statusClass = 'manual';
                statusText = 'MANUAL MATCH';
            } else if (item.matched_url) {
                statusClass = 'ready';
                statusText = 'READY';
            }

            const actionText = (item.matched_urls && item.matched_urls.length > 1)
                ? `Merge ${item.matched_urls.length} Issues into TPB CBZ`
                : item.action;

            tr.innerHTML = `
                <td><b>${item.filename}</b></td>
                <td>#${item.issue_number}</td>
                <td><small>${actionText}</small></td>
                <td>${selectHtml}</td>
                <td><span id="row-badge-${idx}" class="tbl-badge ${statusClass}">${statusText}</span></td>
                <td><button type="button" class="btn-inspect" data-idx="${idx}">👁️ Inspect</button></td>
            `;
            batchPreviewTbody.appendChild(tr);

            // Collapsible details drawer row
            const detailsTr = document.createElement('tr');
            detailsTr.id = `details-row-${idx}`;
            detailsTr.className = 'details-row hidden';
            detailsTr.innerHTML = `
                <td colspan="6">
                    <div id="details-container-${idx}">
                        <span class="help-text">Click "Inspect" to load metadata for this issue.</span>
                    </div>
                </td>
            `;
            batchPreviewTbody.appendChild(detailsTr);
        });

        // Add event listeners to all dropdown select menus
        const selectElems = batchPreviewTbody.querySelectorAll('.tbl-select');
        selectElems.forEach(selElem => {
            selElem.addEventListener('change', (e) => {
                const idx = parseInt(e.target.getAttribute('data-idx'));
                const selectedUrl = e.target.value;
                const item = currentPreviewItems[idx];
                const rowBadge = document.getElementById(`row-badge-${idx}`);

                item.comic = null; // Clear cached comic on link change

                if (selectedUrl) {
                    item.matched_url = selectedUrl;
                    item.matched_urls = [selectedUrl];
                    item.status = 'manual';
                    if (rowBadge) {
                        rowBadge.className = 'tbl-badge manual';
                        rowBadge.textContent = 'MANUAL MATCH';
                    }
                    const matchedObj = currentIssuesList.find(x => x.url === selectedUrl);
                    const issNum = matchedObj ? matchedObj.number : 'Selected';
                    appendLog('info', `[Manual Link] Linked '${item.filename}' to Issue #${issNum}.`);
                } else {
                    item.matched_url = '';
                    item.matched_urls = [];
                    item.status = 'unmatched';
                    if (rowBadge) {
                        rowBadge.className = 'tbl-badge unmatched';
                        rowBadge.textContent = 'UNMATCHED';
                    }
                }
            });
        });

        // Add event listeners to Multi-Select TPB buttons
        const multiBtns = batchPreviewTbody.querySelectorAll('.btn-multi');
        multiBtns.forEach(btn => {
            btn.addEventListener('click', (e) => {
                const idx = parseInt(e.target.getAttribute('data-idx'));
                activeModalRowIdx = idx;
                const item = currentPreviewItems[idx];

                modalSubtitle.textContent = `Check all issues contained inside '${item.filename}':`;
                modalIssueList.innerHTML = '';

                const currentChecked = item.matched_urls || (item.matched_url ? [item.matched_url] : []);

                currentIssuesList.forEach(iss => {
                    const isChecked = currentChecked.includes(iss.url);
                    const label = document.createElement('label');
                    label.className = 'modal-issue-item';
                    label.innerHTML = `
                        <input type="checkbox" value="${iss.url}" ${isChecked ? 'checked' : ''} />
                        <span>Issue #${iss.number}</span>
                    `;
                    modalIssueList.appendChild(label);
                });

                modal.classList.remove('hidden');
            });
        });

        // Add event listeners to Inspect Meta buttons
        const inspectBtns = batchPreviewTbody.querySelectorAll('.btn-inspect');
        inspectBtns.forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const idx = parseInt(e.target.getAttribute('data-idx'));
                const item = currentPreviewItems[idx];
                const detailsRow = document.getElementById(`details-row-${idx}`);
                const detailsContainer = document.getElementById(`details-container-${idx}`);

                if (!detailsRow.classList.contains('hidden')) {
                    detailsRow.classList.add('hidden');
                    return;
                }

                detailsRow.classList.remove('hidden');

                const targetUrls = item.matched_urls && item.matched_urls.length > 0 ? item.matched_urls : (item.matched_url ? [item.matched_url] : []);

                if (targetUrls.length === 0) {
                    detailsContainer.innerHTML = '<span class="help-text text-warning">⚠️ Please select issue(s) from the dropdown or Multi-Select button first.</span>';
                    return;
                }

                if (item.comic) {
                    renderDetailsCard(item.comic, detailsContainer);
                    return;
                }

                const loadingText = targetUrls.length > 1
                    ? `⏳ Scraping & merging ${targetUrls.length} issues for collected edition...`
                    : `⏳ Scraping issue metadata from Comic Vine...`;

                detailsContainer.innerHTML = `<span class="help-text">${loadingText}</span>`;

                try {
                    const res = await fetch('/api/scrape', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ urls: targetUrls })
                    });
                    const data = await res.json();

                    if (!res.ok || data.error) {
                        throw new Error(data.error || 'Failed to fetch issue metadata.');
                    }

                    item.comic = data.comic;
                    renderDetailsCard(item.comic, detailsContainer);
                } catch (err) {
                    detailsContainer.innerHTML = `<span class="help-text text-error">❌ ${err.message}</span>`;
                }
            });
        });
    }

    // Modal Action Buttons
    modalClose.addEventListener('click', () => modal.classList.add('hidden'));
    modalCancelBtn.addEventListener('click', () => modal.classList.add('hidden'));

    modalSaveBtn.addEventListener('click', () => {
        if (activeModalRowIdx === null) return;
        const idx = activeModalRowIdx;
        const item = currentPreviewItems[idx];

        const checkedBoxes = modalIssueList.querySelectorAll('input[type="checkbox"]:checked');
        const selectedUrls = Array.from(checkedBoxes).map(cb => cb.value);

        item.comic = null; // Clear cached comic

        if (selectedUrls.length > 0) {
            item.matched_urls = selectedUrls;
            item.matched_url = selectedUrls[0];
            item.status = 'tpb';

            appendLog('info', `[Multi-Issue TPB] Linked '${item.filename}' to ${selectedUrls.length} issues.`);
        } else {
            item.matched_urls = [];
            item.matched_url = '';
            item.status = 'unmatched';
        }

        renderPreviewTable(currentPreviewItems, currentIssuesList);
        modal.classList.add('hidden');
    });

    // 1. File & Folder Browse Triggers
    btnBrowse.addEventListener('click', async () => {
        try {
            const res = await fetch('/api/browse-file', { method: 'POST' });
            const data = await res.json();
            if (data && data.success && data.file_path) {
                filePathInput.value = data.file_path;
                selectedFileObject = null;
                return;
            }
        } catch (e) {
            console.log("Native picker notice:", e);
        }
        filePicker.click();
    });

    btnBrowseFolder.addEventListener('click', async () => {
        try {
            const res = await fetch('/api/browse-folder', { method: 'POST' });
            const data = await res.json();
            if (data && data.success && data.folder_path) {
                folderPathInput.value = data.folder_path;
            }
        } catch (e) {
            console.log("Native folder picker notice:", e);
        }
    });

    filePicker.addEventListener('change', () => {
        if (filePicker.files && filePicker.files.length > 0) {
            selectedFileObject = filePicker.files[0];
            filePathInput.value = selectedFileObject.name;
        }
    });

    filePathInput.addEventListener('input', () => { selectedFileObject = null; });

    // 2. Single Preview
    btnPreview.addEventListener('click', async () => {
        const rawUrls = urlInput.value.trim();
        if (!rawUrls) {
            showStatus('error', 'URL Required', 'Please enter at least one valid Comic Vine issue URL.');
            return;
        }

        btnPreview.disabled = true;
        btnEmbed.disabled = true;
        showStatus('info', 'Scraping Metadata', 'Fetching issue metadata from Comic Vine...');

        try {
            const res = await fetch('/api/scrape', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ urls: rawUrls })
            });
            const data = await res.json();

            if (!res.ok || data.error) {
                throw new Error(data.error || 'Failed to fetch metadata.');
            }

            renderComic(data.comic);
            resultBadge.textContent = data.comic.count > 1 ? `Merged TPB (${data.comic.count} Issues)` : 'Preview Loaded';
            showStatus('success', 'Metadata Loaded', `Successfully fetched and merged ${data.comic.count || 1} issue(s)!`);
        } catch (err) {
            showStatus('error', 'Extraction Failed', err.message);
        } finally {
            btnPreview.disabled = false;
            btnEmbed.disabled = false;
        }
    });

    // 3. Single Embed Form Submit
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const filePath = filePathInput.value.trim();
        const rawUrls = urlInput.value.trim();

        if (!filePath || !rawUrls) {
            showStatus('error', 'Missing Information', 'Please provide both the comic file (or path) and Comic Vine URL(s).');
            return;
        }

        btnPreview.disabled = true;
        btnEmbed.disabled = true;

        try {
            const formData = new FormData();
            formData.append('urls', rawUrls);
            formData.append('file_path', filePath);

            if (selectedFileObject) {
                showStatus('info', 'Uploading File', `Processing comic file '${selectedFileObject.name}'...`);
                formData.append('comic_file', selectedFileObject, selectedFileObject.name);
            } else {
                const isCbr = filePath.toLowerCase().endsWith('.cbr');
                const statusMsg = isCbr
                    ? `Converting .cbr to .cbz, removing original .cbr, and embedding ComicInfo.xml...`
                    : `Embedding ComicInfo.xml into '${filePath}'...`;
                showStatus('info', 'Tagging Comic', statusMsg);
            }

            const res = await fetch('/api/embed', {
                method: 'POST',
                body: formData
            });
            const data = await res.json();

            if (!res.ok || data.error) {
                throw new Error(data.error || 'Failed to embed ComicInfo.xml.');
            }

            if (data.target_file) {
                filePathInput.value = data.target_file;
            }

            renderComic(data.comic);
            resultBadge.textContent = data.comic.count > 1 ? `Embedded TPB (${data.comic.count} Issues)` : 'Embedded in CBZ';
            showStatus('success', 'Successfully Embedded', data.message || 'ComicInfo.xml has been updated in the archive.');
        } catch (err) {
            showStatus('error', 'Embedding Failed', err.message);
        } finally {
            btnPreview.disabled = false;
            btnEmbed.disabled = false;
        }
    });

    // 4. Batch Preview Button
    async function loadBatchPreview() {
        const folderPath = folderPathInput.value.trim();
        const volumeUrl = volumeUrlInput.value.trim();

        if (!folderPath || !volumeUrl) {
            showStatus('error', 'Missing Information', 'Please enter both the Folder Directory and Volume URL.');
            return null;
        }

        btnBatchPreview.disabled = true;
        btnBatchEmbed.disabled = true;
        showStatus('info', 'Scraping Volume & Matching Files', 'Extracting volume issue links and scanning local directory...');

        try {
            const res = await fetch('/api/batch-preview', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: volumeUrl, folder_path: folderPath })
            });
            const data = await res.json();

            if (!res.ok || data.error) {
                throw new Error(data.error || 'Failed to generate volume preview.');
            }

            currentPreviewItems = data.items || [];
            currentIssuesList = data.issues_list || [];

            renderPreviewTable(currentPreviewItems, currentIssuesList);

            batchResultBadge.textContent = `${data.matched_count}/${data.total_files} Matched`;
            batchResultCard.classList.remove('hidden');

            appendLog('info', `🔍 Volume Preview loaded for series '${data.series_name}': Found ${data.total_files} local files (${data.matched_count} auto-matched with Comic Vine). Click '🧩 Multi' on any file to select multiple issues for TPB collected editions.`);
            showStatus('success', 'Volume Preview Ready', `Matched ${data.matched_count} of ${data.total_files} files for series '${data.series_name}'. Click '🧩 Multi' on any file for TPB multi-issue collected editions.`);
            return data;
        } catch (err) {
            showStatus('error', 'Preview Failed', err.message);
            return null;
        } finally {
            btnBatchPreview.disabled = false;
            btnBatchEmbed.disabled = false;
        }
    }

    btnBatchPreview.addEventListener('click', loadBatchPreview);

    // 5. Batch Embed Form Submit with Real-Time Progress & Terminal Logging
    batchForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        let previewData = currentPreviewItems;
        if (!previewData || previewData.length === 0) {
            const res = await loadBatchPreview();
            if (!res || !res.items) return;
            previewData = res.items;
        }

        const deleteCbr = chkDeleteCbr.checked;
        const total = previewData.length;
        if (total === 0) return;

        btnBatchPreview.disabled = true;
        btnBatchEmbed.disabled = true;
        batchResultCard.classList.remove('hidden');

        updateProgress(0, total);
        appendLog('info', `🚀 Starting batch processing for ${total} comic files...`);

        let successCount = 0;

        for (let i = 0; i < total; i++) {
            const item = previewData[i];
            const rowBadge = document.getElementById(`row-badge-${i}`);
            
            updateProgress(i, total);

            const targetUrls = item.matched_urls && item.matched_urls.length > 0 ? item.matched_urls : (item.matched_url ? [item.matched_url] : []);

            if (targetUrls.length === 0) {
                appendLog('warning', `[${i+1}/${total}] ⚠️ Skipped '${item.filename}': No issue link selected. Use the dropdown or 🧩 Multi button to set issues.`);
                if (rowBadge) {
                    rowBadge.className = 'tbl-badge unmatched';
                    rowBadge.textContent = 'SKIPPED';
                }
                continue;
            }

            const multiNote = targetUrls.length > 1 ? ` (Merging ${targetUrls.length} issues into TPB)` : ` (Issue #${item.issue_number})`;
            appendLog('info', `[${i+1}/${total}] ⚙️ Processing '${item.filename}'${multiNote}...`);

            if (item.is_cbr) {
                appendLog('info', `[${i+1}/${total}] 📦 Extracting CBR via unrar, converting to CBZ, and deleting original .cbr...`);
            }

            try {
                const formData = new FormData();
                formData.append('urls', JSON.stringify(targetUrls));
                formData.append('file_path', item.full_path);
                formData.append('delete_original', deleteCbr);

                const res = await fetch('/api/embed', {
                    method: 'POST',
                    body: formData
                });
                const data = await res.json();

                if (!res.ok || data.error) {
                    throw new Error(data.error || 'Failed to process comic file.');
                }

                item.comic = data.comic; // Cache scraped metadata
                successCount++;
                const delMsg = data.deleted_original ? ' (Original .cbr deleted)' : '';
                appendLog('success', `[${i+1}/${total}] ✅ Successfully embedded ComicInfo.xml into '${item.filename}'${delMsg}!`);

                if (rowBadge) {
                    rowBadge.className = targetUrls.length > 1 ? 'tbl-badge tpb' : 'tbl-badge ready';
                    rowBadge.textContent = targetUrls.length > 1 ? `COLLECTED (${targetUrls.length} ISSUES)` : 'TAGGED';
                }
            } catch (err) {
                appendLog('error', `[${i+1}/${total}] ❌ Failed to tag '${item.filename}': ${err.message}`);
                if (rowBadge) {
                    rowBadge.className = 'tbl-badge unmatched';
                    rowBadge.textContent = 'FAILED';
                }
            }
        }

        updateProgress(total, total);
        appendLog('success', `🎉 Batch processing complete! ${successCount}/${total} files tagged successfully.`);
        showStatus('success', 'Batch Processing Finished', `Successfully tagged ${successCount} of ${total} files.`);

        btnBatchPreview.disabled = false;
        btnBatchEmbed.disabled = false;
    });
});
