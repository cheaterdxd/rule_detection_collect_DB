// Constants & State
let activeSearchMode = 'hybrid';
let activeTag = null;
let currentRule = null;
let currentTranslationCache = {};
let currentOffset = 0;
let currentTags = [];
let syncInterval = null;
const PAGE_LIMIT = 60;

// Elements
const searchInput = document.getElementById('search-input');
const searchBtn = document.getElementById('search-btn');
const modeBtns = document.querySelectorAll('.mode-btn');
const rulesList = document.getElementById('rules-list');
const resultsCount = document.getElementById('results-count');
const popularTagsContainer = document.getElementById('popular-tags');

// Modals & detail view elements
const ruleModal = document.getElementById('rule-modal');
const closeModalBtn = document.getElementById('close-modal-btn');
const modalRuleType = document.getElementById('modal-rule-type');
const modalRuleTitle = document.getElementById('modal-rule-title');
const modalRuleLevel = document.getElementById('modal-rule-level');
const modalRuleAuthor = document.getElementById('modal-rule-author');
const modalRuleSource = document.getElementById('modal-rule-source');
const modalRuleTags = document.getElementById('modal-rule-tags');
const modalRuleDesc = document.getElementById('modal-rule-desc');
const codeTabs = document.getElementById('code-tabs');
const codeDisplay = document.getElementById('code-display');
const copyCodeBtn = document.getElementById('copy-code-btn');

// Settings Elements
const settingsModal = document.getElementById('settings-modal');
const settingsBtn = document.getElementById('settings-btn');
const closeSettingsBtn = document.getElementById('close-settings-btn');
const sourcesList = document.getElementById('sources-list');
const addSourceForm = document.getElementById('add-source-form');
const syncNowBtn = document.getElementById('sync-now-btn');
const syncStatusMsg = document.getElementById('sync-status-msg');
const addTagInput = document.getElementById('add-tag-input');
const addTagBtn = document.getElementById('add-tag-btn');

// Start Init
document.addEventListener('DOMContentLoaded', () => {
    loadStats();
    setupEventListeners();
});

function setupEventListeners() {
    // Search Action
    searchBtn.addEventListener('click', () => triggerSearch());
    searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            triggerSearch();
        }
    });

    // Search Mode Selection
    modeBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
            modeBtns.forEach(b => b.classList.remove('active'));
            const target = e.currentTarget;
            target.classList.add('active');
            activeSearchMode = target.dataset.mode;
            
            const sortIndicator = document.getElementById('sort-indicator');
            if (activeSearchMode === 'hybrid') {
                sortIndicator.textContent = 'Sorted by Hybrid Relevance Score';
            } else if (activeSearchMode === 'semantic') {
                sortIndicator.textContent = 'Sorted by AI Semantic Match';
            } else if (activeSearchMode === 'raw') {
                sortIndicator.textContent = 'Sorted by Substring Match in Raw Code';
            } else {
                sortIndicator.textContent = 'Sorted by Text Rank Score';
            }
            
            triggerSearch();
        });
    });

    // Sidebar Filters triggers
    document.querySelectorAll('.sidebar-filters input[type="checkbox"]').forEach(checkbox => {
        checkbox.addEventListener('change', () => triggerSearch());
    });

    // Modal Close
    closeModalBtn.addEventListener('click', closeModal);
    window.addEventListener('click', (e) => {
        if (e.target === ruleModal) closeModal();
    });

    // Code Translation Tabs Selection
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            e.currentTarget.classList.add('active');
            renderCodeTab(e.currentTarget.dataset.tab);
        });
    });

    // Copy to clipboard
    copyCodeBtn.addEventListener('click', copyCodeToClipboard);

    // Load More Action
    const loadMoreBtn = document.getElementById('load-more-btn');
    if (loadMoreBtn) {
        loadMoreBtn.addEventListener('click', () => {
            const query = searchInput.value.trim();
            searchRules(query, true);
        });
    }

    // Settings Modal Listeners
    settingsBtn.addEventListener('click', () => {
        loadSources();
        pollSyncStatus(); // check current sync status on load
        settingsModal.style.display = 'flex';
    });
    closeSettingsBtn.addEventListener('click', closeSettings);
    window.addEventListener('click', (e) => {
        if (e.target === settingsModal) closeSettings();
    });

    // Add Source Form Submit
    addSourceForm.addEventListener('submit', (e) => {
        e.preventDefault();
        const extensions = document.getElementById('source-extensions').value
            .split(',')
            .map(ext => ext.trim())
            .filter(ext => ext.length > 0);
            
        const sourceData = {
            name: document.getElementById('source-name').value.trim(),
            type: document.getElementById('source-type').value,
            repo_url: document.getElementById('source-url').value.trim(),
            relative_rules_path: document.getElementById('source-rules-path').value.trim(),
            target_extensions: extensions
        };
        addSource(sourceData);
    });

    // Sync Now Trigger
    syncNowBtn.addEventListener('click', triggerSync);

    // Tag Editor Inputs
    addTagBtn.addEventListener('click', addRuleTag);
    addTagInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            addRuleTag();
        }
    });
}

// Ingest current filters and hit search endpoint
async function searchRules(query, append = false) {
    if (!append) {
        currentOffset = 0;
        document.getElementById('load-more-container').style.display = 'none';
    }

    const hasExistingCards = rulesList.querySelector('.rule-card') !== null;
    if (!append) {
        if (hasExistingCards) {
            rulesList.classList.add('loading-fade');
        } else {
            rulesList.innerHTML = `
                <div class="feed-placeholder">
                    <i class="fa-solid fa-spinner fa-spin logo-icon"></i>
                    <p>Analyzing and retrieving rules...</p>
                </div>
            `;
        }
    } else {
        const loadMoreBtn = document.getElementById('load-more-btn');
        loadMoreBtn.disabled = true;
        loadMoreBtn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Loading...`;
    }

    // Type filters
    const selectedTypes = [];
    document.querySelectorAll('#type-filters input:checked').forEach(cb => {
        selectedTypes.push(cb.value);
    });

    // Severity level filters
    const selectedLevels = [];
    document.querySelectorAll('#level-filters input:checked').forEach(cb => {
        selectedLevels.push(cb.value);
    });

    // Build URL Query Params
    let url = `/api/rules?mode=${activeSearchMode}&limit=${PAGE_LIMIT}&offset=${currentOffset}`;
    if (query) {
        url += `&q=${encodeURIComponent(query)}`;
    }
    // Filter type: backend now accepts a list of types
    selectedTypes.forEach(type => {
        url += `&type=${type}`;
    });
    // Filter level
    selectedLevels.forEach(level => {
        url += `&level=${level}`;
    });

    try {
        const response = await fetch(url);
        if (!response.ok) throw new Error('API search failed');
        let rules = await response.json();

        renderRulesFeed(rules, append);

        const loadMoreContainer = document.getElementById('load-more-container');
        const loadMoreBtn = document.getElementById('load-more-btn');
        loadMoreBtn.disabled = false;
        loadMoreBtn.innerHTML = `<i class="fa-solid fa-angles-down"></i> Load More Rules`;

        // If returned rules count is exactly PAGE_LIMIT, show the Load More button
        if (rules.length === PAGE_LIMIT) {
            loadMoreContainer.style.display = 'flex';
        } else {
            loadMoreContainer.style.display = 'none';
        }

        currentOffset += rules.length;
    } catch (e) {
        console.error(e);
        const loadMoreBtn = document.getElementById('load-more-btn');
        loadMoreBtn.disabled = false;
        loadMoreBtn.innerHTML = `<i class="fa-solid fa-angles-down"></i> Load More Rules`;
        
        if (!append) {
            rulesList.innerHTML = `
                <div class="feed-placeholder">
                    <i class="fa-solid fa-triangle-exclamation text-critical"></i>
                    <p>Failed to query rule database. Make sure the backend is active.</p>
                </div>
            `;
        } else {
            alert('Failed to load more rules.');
        }
    }
}

function triggerSearch() {
    const query = searchInput.value.trim();
    if (!query) {
        resultsCount.textContent = `Showing 0 rules`;
        rulesList.innerHTML = `
            <div class="feed-placeholder">
                <i class="fa-solid fa-shield-halved pulse"></i>
                <p>Enter a query above to scan the ruleset</p>
            </div>
        `;
        document.getElementById('load-more-container').style.display = 'none';
        return;
    }
    searchRules(query);
}

// Stats panel loader
async function loadStats() {
    try {
        const response = await fetch('/api/stats');
        if (!response.ok) throw new Error('API stats fetch failed');
        const stats = await response.json();

        document.getElementById('stat-total').textContent = stats.total.toLocaleString();
        document.getElementById('stat-sigma').textContent = (stats.types.Sigma || 0).toLocaleString();
        document.getElementById('stat-yara').textContent = (stats.types.Yara || 0).toLocaleString();
        document.getElementById('stat-elastic').textContent = (stats.types.Elastic || 0).toLocaleString();
        document.getElementById('stat-kql').textContent = (stats.types.KQL || 0).toLocaleString();

        // Render popular tags
        popularTagsContainer.innerHTML = '';
        if (stats.top_tags && stats.top_tags.length > 0) {
            stats.top_tags.forEach(item => {
                const tagEl = document.createElement('span');
                tagEl.className = 'tag-pill';
                tagEl.textContent = `${item.tag} (${item.count})`;
                tagEl.addEventListener('click', () => {
                    if (activeTag === item.tag) {
                        activeTag = null;
                        tagEl.classList.remove('active');
                        searchInput.value = '';
                    } else {
                        // Deactivate other tag pills
                        document.querySelectorAll('.tag-pill').forEach(p => p.classList.remove('active'));
                        activeTag = item.tag;
                        tagEl.classList.add('active');
                        searchInput.value = item.tag;
                    }
                    triggerSearch();
                });
                popularTagsContainer.appendChild(tagEl);
            });
        } else {
            popularTagsContainer.innerHTML = '<span class="tag-loading">No tags found.</span>';
        }
    } catch (e) {
        console.error("Failed to load statistics: ", e);
    }
}

function renderRulesFeed(rules, append = false) {
    // Remove loading indicator overlay
    rulesList.classList.remove('loading-fade');
    
    let totalDisplayed = rules.length;
    if (append) {
        const existingCards = rulesList.querySelectorAll('.rule-card').length;
        totalDisplayed = existingCards + rules.length;
    }
    
    resultsCount.textContent = `Showing ${totalDisplayed} rules`;

    if (!append) {
        rulesList.innerHTML = '';
    }

    if (totalDisplayed === 0) {
        rulesList.innerHTML = `
            <div class="feed-placeholder">
                <i class="fa-solid fa-folder-open"></i>
                <p>No matching rules found. Try adjusting your query or filters.</p>
            </div>
        `;
        return;
    }

    rules.forEach(rule => {
        const lvl = (rule.level || 'medium').toLowerCase();
        const levelClass = getLevelClass(lvl);
        const cardSevClass = getCardSevClass(lvl);

        const card = document.createElement('div');
        card.className = `rule-card ${cardSevClass}`;
        card.addEventListener('click', () => openRuleInspector(rule.id));

        const typeBadgeClass = getBadgeClass(rule.type);

        // Score logic
        let scoreDisplay = '';
        if (activeSearchMode === 'semantic' || activeSearchMode === 'hybrid') {
            const pct = Math.round(rule.score * 100);
            scoreDisplay = `<span class="card-score">${pct}% Match</span>`;
        }

        // Render card content
        card.innerHTML = `
            <div class="card-header">
                <div class="card-title-block">
                    <span class="badge ${typeBadgeClass}">${rule.type}</span>
                    <h3>${escapeHtml(rule.title)}</h3>
                </div>
                ${scoreDisplay}
            </div>
            <p class="card-description">${escapeHtml(rule.description || 'No description provided.')}</p>
            <div class="card-footer">
                <div class="card-meta">
                    <span class="level-pill ${levelClass}">${lvl}</span>
                    <span>• By ${escapeHtml(rule.author || 'Unknown')}</span>
                </div>
                <div class="card-meta source-repo-label">
                    <i class="fa-brands fa-github"></i>
                    <span>${escapeHtml(rule.source_repo)}</span>
                </div>
            </div>
        `;
        rulesList.appendChild(card);
    });
}

// Rule inspector modal loader
async function openRuleInspector(ruleId) {
    try {
        const response = await fetch(`/api/rules/${ruleId}`);
        if (!response.ok) throw new Error('Failed to load rule detail');
        currentRule = await response.json();
        currentTranslationCache = {}; // reset cache

        // Title and header
        modalRuleTitle.textContent = currentRule.title;
        modalRuleType.textContent = currentRule.type;
        
        // Remove old badge classes and apply new
        modalRuleType.className = `badge ${getBadgeClass(currentRule.type)}`;

        // Severity
        const lvl = (currentRule.level || 'medium').toLowerCase();
        modalRuleLevel.textContent = lvl;
        modalRuleLevel.className = `level-pill ${getLevelClass(lvl)}`;

        // Metadata
        modalRuleAuthor.textContent = currentRule.author || 'Unknown';
        modalRuleSource.textContent = currentRule.source_repo;
        modalRuleDesc.textContent = currentRule.description || 'No description available.';

        // Render Tags
        renderTagsEditor(currentRule.tags);

        // Translation Tabs visibility: ONLY Sigma rules can be translated to Splunk/KQL/Elastic
        const tabSplunk = document.getElementById('tab-splunk');
        const tabElastic = document.getElementById('tab-elastic');
        const tabSentinel = document.getElementById('tab-sentinel');

        if (currentRule.type === 'Sigma') {
            tabSplunk.style.display = 'block';
            tabElastic.style.display = 'block';
            tabSentinel.style.display = 'block';
        } else {
            tabSplunk.style.display = 'none';
            tabElastic.style.display = 'none';
            tabSentinel.style.display = 'none';
        }

        // Set default raw tab active
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelector('.tab-btn[data-tab="raw"]').classList.add('active');

        // Render Raw Code
        renderCodeTab('raw');

        // Open Modal
        ruleModal.style.display = 'flex';
    } catch (e) {
        console.error(e);
        alert('Could not retrieve rule specifications.');
    }
}

function closeModal() {
    ruleModal.style.display = 'none';
    currentRule = null;
}

// Logic to render selected code tab (and trigger API translations)
async function renderCodeTab(tabType) {
    if (!currentRule) return;

    if (tabType === 'raw') {
        codeDisplay.textContent = currentRule.raw_content;
        return;
    }

    // Check Cache first to avoid hitting server
    if (currentTranslationCache[tabType]) {
        codeDisplay.textContent = currentTranslationCache[tabType];
        return;
    }

    codeDisplay.textContent = `Translating rule to ${tabType.toUpperCase()} query logic... Please wait.`;

    try {
        const response = await fetch('/api/rules/translate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                sigma_yaml: currentRule.raw_content,
                target: tabType
            })
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Translation failed');
        }

        const data = await response.json();
        const translatedQuery = data.query || 'Translation returned empty query.';
        
        // Cache result
        currentTranslationCache[tabType] = translatedQuery;
        codeDisplay.textContent = translatedQuery;

    } catch (e) {
        codeDisplay.textContent = `[ERROR] Failed to convert Sigma rule: ${e.message}\n\nMake sure your Sigma rule contains a valid YAML format structure.`;
    }
}

// Copy query helpers
function copyCodeToClipboard() {
    const text = codeDisplay.textContent;
    navigator.clipboard.writeText(text).then(() => {
        const originalText = copyCodeBtn.innerHTML;
        copyCodeBtn.innerHTML = '<i class="fa-solid fa-check"></i> Copied!';
        setTimeout(() => {
            copyCodeBtn.innerHTML = originalText;
        }, 1500);
    }).catch(err => {
        console.error('Failed to copy text: ', err);
    });
}

// Simple HTML escaping helper
function escapeHtml(str) {
    if (!str) return '';
    return str
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

// --- Tag Editor Helpers ---
function renderTagsEditor(tags) {
    currentTags = tags || [];
    modalRuleTags.innerHTML = '';
    if (currentTags.length > 0) {
        currentTags.forEach(tag => {
            const tagEl = document.createElement('span');
            tagEl.className = 'tag-pill';
            tagEl.innerHTML = `${escapeHtml(tag)} <span class="delete-tag-btn" data-tag="${escapeHtml(tag)}">&times;</span>`;
            tagEl.querySelector('.delete-tag-btn').addEventListener('click', (e) => {
                e.stopPropagation();
                removeRuleTag(tag);
            });
            modalRuleTags.appendChild(tagEl);
        });
    } else {
        modalRuleTags.innerHTML = '<span class="tag-loading">No tags</span>';
    }
}

async function addRuleTag() {
    const val = addTagInput.value.trim();
    if (!val || !currentRule) return;
    
    if (currentTags.includes(val)) {
        addTagInput.value = '';
        return;
    }
    
    const updatedTags = [...currentTags, val];
    
    try {
        const response = await fetch(`/api/rules/${currentRule.id}/tags`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tags: updatedTags })
        });
        if (!response.ok) throw new Error('Failed to add tag');
        
        currentTags = updatedTags;
        renderTagsEditor(currentTags);
        addTagInput.value = '';
        
        // Refresh rule feed to reflect tags
        loadStats();
    } catch (e) {
        console.error(e);
        alert('Failed to save tag to rule.');
    }
}

async function removeRuleTag(tagToRemove) {
    if (!currentRule) return;
    const updatedTags = currentTags.filter(t => t !== tagToRemove);
    
    try {
        const response = await fetch(`/api/rules/${currentRule.id}/tags`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tags: updatedTags })
        });
        if (!response.ok) throw new Error('Failed to remove tag');
        
        currentTags = updatedTags;
        renderTagsEditor(currentTags);
        
        // Refresh rule feed to reflect tags
        loadStats();
    } catch (e) {
        console.error(e);
        alert('Failed to remove tag.');
    }
}

// --- Settings and Repository Source Config Helpers ---
async function loadSources() {
    sourcesList.innerHTML = '<div style="font-size:0.85rem; color:var(--text-muted);">Loading rule sources...</div>';
    try {
        const response = await fetch('/api/sources');
        if (!response.ok) throw new Error('Failed to load sources');
        const sources = await response.json();
        
        sourcesList.innerHTML = '';
        if (sources.length === 0) {
            sourcesList.innerHTML = '<div style="font-size:0.85rem; color:var(--text-muted);">No configured repositories.</div>';
            return;
        }
        
        sources.forEach(source => {
            const item = document.createElement('div');
            item.className = 'source-item';
            
            const typeBadgeClass = getBadgeClass(source.type);
            
            item.innerHTML = `
                <div class="source-info">
                    <div class="source-title">
                        <span class="badge ${typeBadgeClass}">${source.type}</span>
                        <span>${escapeHtml(source.name)}</span>
                    </div>
                    <div class="source-meta">
                        <strong>Git:</strong> ${escapeHtml(source.repo_url)}<br>
                        <strong>Path:</strong> ${escapeHtml(source.relative_rules_path)} (Exts: ${source.target_extensions.join(', ')})
                    </div>
                </div>
                <button type="button" class="delete-source-btn" title="Delete Repository Source" data-name="${escapeHtml(source.name)}">
                    <i class="fa-solid fa-trash-can"></i>
                </button>
            `;
            
            item.querySelector('.delete-source-btn').addEventListener('click', (e) => {
                e.stopPropagation();
                if (confirm(`Are you sure you want to delete source '${source.name}'?`)) {
                    deleteSource(source.name);
                }
            });
            
            sourcesList.appendChild(item);
        });
    } catch (e) {
        console.error(e);
        sourcesList.innerHTML = '<div style="color:var(--color-critical); font-size:0.85rem;">Failed to load sources config.</div>';
    }
}

async function addSource(sourceData) {
    try {
        const response = await fetch('/api/sources', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(sourceData)
        });
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Failed to add source');
        }
        
        // Reset form
        addSourceForm.reset();
        // Reload list
        loadSources();
        loadStats(); // refresh database counts
    } catch (e) {
        console.error(e);
        alert(`Error: ${e.message}`);
    }
}

async function deleteSource(name) {
    try {
        const response = await fetch(`/api/sources/${encodeURIComponent(name)}`, {
            method: 'DELETE'
        });
        if (!response.ok) throw new Error('Failed to delete source');
        
        loadSources();
        loadStats(); // refresh database counts
    } catch (e) {
        console.error(e);
        alert('Failed to delete repository source.');
    }
}

// --- Ingest Subprocess Sync Helpers ---
async function triggerSync() {
    syncNowBtn.disabled = true;
    syncNowBtn.innerHTML = '<i class="fa-solid fa-rotate fa-spin"></i> Triggering Sync...';
    syncStatusMsg.innerHTML = 'Sending sync request...';
    
    try {
        const response = await fetch('/api/sources/sync', { method: 'POST' });
        if (!response.ok) throw new Error('Failed to trigger sync');
        
        const data = await response.json();
        syncStatusMsg.innerHTML = data.message;
        
        // Start polling immediately
        pollSyncStatus();
    } catch (e) {
        console.error(e);
        syncStatusMsg.innerHTML = `<span style="color:var(--color-critical);">Failed to start sync: ${e.message}</span>`;
        syncNowBtn.disabled = false;
        syncNowBtn.innerHTML = '<i class="fa-solid fa-rotate"></i> Sync Repositories Now';
    }
}

async function pollSyncStatus() {
    if (syncInterval) clearInterval(syncInterval);
    
    const checkStatus = async () => {
        try {
            const response = await fetch('/api/sources/sync/status');
            if (!response.ok) throw new Error('Failed to fetch status');
            const data = await response.json();
            
            if (data.status === 'running') {
                syncNowBtn.disabled = true;
                syncNowBtn.innerHTML = '<i class="fa-solid fa-rotate fa-spin"></i> Syncing...';
                syncStatusMsg.innerHTML = `<span style="color:var(--color-medium); font-weight:600;"><i class="fa-solid fa-spinner fa-spin"></i> Running Ingest:</span> ${escapeHtml(data.message)}`;
            } else {
                // Not running (idle, success, error)
                syncNowBtn.disabled = false;
                syncNowBtn.innerHTML = '<i class="fa-solid fa-rotate"></i> Sync Repositories Now';
                
                if (data.status === 'success') {
                    syncStatusMsg.innerHTML = `<span style="color:var(--color-low); font-weight:600;"><i class="fa-solid fa-check-circle"></i> Success:</span> ${escapeHtml(data.message)}`;
                    loadStats(); // reload stats since rules count changed
                    if (syncInterval) clearInterval(syncInterval);
                } else if (data.status === 'error') {
                    syncStatusMsg.innerHTML = `<span style="color:var(--color-critical); font-weight:600;"><i class="fa-solid fa-exclamation-triangle"></i> Error:</span> ${escapeHtml(data.message)}`;
                    if (syncInterval) clearInterval(syncInterval);
                } else {
                    syncStatusMsg.innerHTML = escapeHtml(data.message);
                    if (syncInterval) clearInterval(syncInterval);
                }
            }
        } catch (e) {
            console.error('Error polling status:', e);
            if (syncInterval) clearInterval(syncInterval);
        }
    };
    
    // Check once immediately
    await checkStatus();
    // Poll every 3 seconds
    syncInterval = setInterval(checkStatus, 3000);
}

// --- Common Helper Functions ---
function getBadgeClass(type) {
    const badgeClasses = {
        Yara: 'yara-badge',
        Elastic: 'elastic-badge',
        KQL: 'kql-badge'
    };
    return badgeClasses[type] || 'sigma-badge';
}

function getLevelClass(lvl) {
    lvl = (lvl || 'medium').toLowerCase();
    if (lvl === 'critical') return 'level-critical';
    if (lvl === 'high') return 'level-high';
    if (lvl === 'low' || lvl === 'informational' || lvl === 'info') return 'level-low';
    return 'level-medium';
}

function getCardSevClass(lvl) {
    lvl = (lvl || 'medium').toLowerCase();
    if (lvl === 'critical') return 'sev-critical';
    if (lvl === 'high') return 'sev-high';
    if (lvl === 'low' || lvl === 'informational' || lvl === 'info') return 'sev-low';
    return 'sev-medium';
}

function closeSettings() {
    settingsModal.style.display = 'none';
    if (syncInterval) clearInterval(syncInterval);
}
