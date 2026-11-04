/**
 * FRIDAY Conversation History Panel
 * 
 * Shows chronological list of all interactions with Friday
 * Each entry: timestamp, user input (voice/text), Friday's reply, agents involved, status
 * Search/filter by date, agent, status
 * Click entry → expand to show full details, agents involved, output
 * Export conversation as JSON/Markdown
 * Auto-load recent on startup
 * Infinite scroll for older history
 */

(function() {
    'use strict';

    // ========================================================================
    // CSS Styles (injected on init)
    // ========================================================================

    const STYLES = `
        <style id="conversation-history-styles">
        .conversation-history-panel {
            display: flex;
            flex-direction: column;
            height: 100%;
            min-height: 400px;
            background: var(--panel, #0b1218);
            border: 1px solid var(--line, #1b2833);
            border-radius: var(--r-lg, 16px);
            overflow: hidden;
            font-family: var(--mono, ui-monospace, SFMono-Regular, "Cascadia Mono", Menlo, Consolas, monospace);
        }

        /* Header */
        .ch-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: var(--sp-3, 12px) var(--sp-4, 16px);
            border-bottom: 1px solid var(--line-soft, #141f27);
            background: rgba(6,9,13,.6);
            backdrop-filter: blur(8px);
            flex-wrap: wrap;
            gap: var(--sp-2, 8px);
        }

        .ch-title {
            display: flex;
            align-items: center;
            gap: var(--sp-2, 8px);
        }

        .ch-title h2 {
            margin: 0;
            font-size: 14px;
            font-weight: 700;
            letter-spacing: -.02em;
            color: var(--text, #e9f0f6);
        }

        .ch-count {
            font-family: var(--mono);
            font-size: 10.5px;
            color: var(--muted, #8195a5);
            border: 1px solid var(--line, #1b2833);
            padding: 1px 7px;
            border-radius: 99px;
            font-variant-numeric: tabular-nums;
        }

        .ch-actions {
            display: flex;
            align-items: center;
            gap: var(--sp-2, 8px);
        }

        /* Filters */
        .ch-filters {
            padding: var(--sp-3, 12px) var(--sp-4, 16px);
            border-bottom: 1px solid var(--line-soft, #141f27);
            background: rgba(6,9,13,.4);
        }

        .ch-filter-row {
            display: flex;
            align-items: center;
            gap: var(--sp-3, 12px);
            flex-wrap: wrap;
            margin-bottom: var(--sp-2, 8px);
        }

        .ch-filter-row:last-child {
            margin-bottom: 0;
        }

        .ch-filter-group {
            display: flex;
            align-items: center;
            gap: var(--sp-1, 4px);
            flex: 1;
            min-width: 140px;
        }

        .ch-filter-group label {
            font-size: 9px;
            font-weight: 600;
            letter-spacing: .1em;
            text-transform: uppercase;
            color: var(--mint, #7cf0b8);
            white-space: nowrap;
        }

        .ch-filter-group input,
        .ch-filter-group select {
            flex: 1;
            background: var(--bg, #06090d);
            border: 1px solid var(--line, #1b2833);
            border-radius: var(--r-sm, 8px);
            padding: 6px 10px;
            color: var(--text, #e9f0f6);
            font-size: 11px;
            font-family: inherit;
        }

        .ch-filter-group input:focus,
        .ch-filter-group select:focus {
            outline: none;
            border-color: var(--mint, #7cf0b8);
            box-shadow: 0 0 0 2px rgba(124, 240, 184, 0.15);
        }

        .ch-filter-group select {
            cursor: pointer;
        }

        /* Buttons */
        .ch-btn {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            border: 1px solid var(--line, #1b2833);
            border-radius: var(--r-sm, 8px);
            padding: 6px 12px;
            font-size: 10.5px;
            font-weight: 600;
            font-family: inherit;
            cursor: pointer;
            transition: all 0.15s ease;
            white-space: nowrap;
        }

        .ch-btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        .ch-btn-primary {
            background: linear-gradient(145deg, #14352b, #0a1a15);
            border-color: #2f6a55;
            color: var(--mint, #7cf0b8);
        }

        .ch-btn-primary:hover:not(:disabled) {
            border-color: var(--mint, #7cf0b8);
            box-shadow: 0 0 12px rgba(124, 240, 184, 0.2);
        }

        .ch-btn-secondary {
            background: #0a1117;
            color: var(--muted, #8195a5);
        }

        .ch-btn-secondary:hover:not(:disabled) {
            color: var(--text, #e9f0f6);
            border-color: var(--line-soft, #141f27);
            background: #0d161d;
        }

        /* Entries Container */
        .ch-entries {
            flex: 1;
            overflow-y: auto;
            padding: var(--sp-3, 12px) var(--sp-4, 16px);
        }

        .ch-loading,
        .ch-empty,
        .ch-error {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: var(--sp-8, 32px);
            color: var(--muted-2, #5c6f7e);
            text-align: center;
            gap: var(--sp-2, 8px);
        }

        .ch-spinner {
            width: 24px;
            height: 24px;
            border: 2px solid var(--line, #1b2833);
            border-top-color: var(--mint, #7cf0b8);
            border-radius: 50%;
            animation: ch-spin 1s linear infinite;
        }

        .ch-spinner-sm {
            width: 14px;
            height: 14px;
            border: 1.5px solid var(--line, #1b2833);
            border-top-color: var(--mint, #7cf0b8);
            border-radius: 50%;
            animation: ch-spin 1s linear infinite;
        }

        @keyframes ch-spin {
            to { transform: rotate(360deg); }
        }

        .ch-empty svg,
        .ch-error svg {
            opacity: 0.4;
        }

        .ch-error {
            color: var(--danger, #ff7d7d);
        }

        /* Entry */
        .ch-entry {
            border: 1px solid var(--line, #1b2833);
            border-radius: var(--r-md, 12px);
            background: var(--panel-2, #0f1820);
            margin-bottom: var(--sp-2, 8px);
            overflow: hidden;
            transition: border-color 0.15s, box-shadow 0.15s;
        }

        .ch-entry:hover {
            border-color: var(--line-soft, #141f27);
        }

        .ch-entry.expanded {
            border-color: var(--mint, #7cf0b8);
            box-shadow: 0 0 0 1px var(--mint, #7cf0b8), 0 8px 24px rgba(0,0,0,0.3);
        }

        .ch-entry-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: var(--sp-2, 8px) var(--sp-3, 12px);
            gap: var(--sp-2, 8px);
            flex-wrap: wrap;
        }

        .ch-entry-meta {
            display: flex;
            align-items: center;
            gap: var(--sp-2, 8px);
        }

        .ch-timestamp {
            font-family: var(--mono);
            font-size: 10px;
            color: var(--muted-2, #5c6f7e);
            font-variant-numeric: tabular-nums;
        }

        .ch-input-type {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            font-size: 9px;
            font-weight: 600;
            letter-spacing: .05em;
            text-transform: uppercase;
            padding: 2px 6px;
            border-radius: 99px;
            background: rgba(255,255,255,.03);
            color: var(--muted, #8195a5);
        }

        .ch-input-type.voice {
            color: var(--violet, #b6a4ff);
            background: rgba(182, 164, 255, 0.1);
        }

        .ch-entry-status {
            display: flex;
            align-items: center;
            gap: var(--sp-1, 4px);
            margin-left: auto;
        }

        .ch-status-badge {
            display: inline-flex;
            align-items: center;
            padding: 2px 8px;
            border-radius: 99px;
            font-size: 9px;
            font-weight: 700;
            letter-spacing: .05em;
            text-transform: uppercase;
            border: 1px solid;
        }

        .ch-expand-btn {
            display: flex;
            align-items: center;
            justify-content: center;
            width: 28px;
            height: 28px;
            border: none;
            background: transparent;
            border-radius: var(--r-sm, 8px);
            color: var(--muted-2, #5c6f7e);
            cursor: pointer;
            transition: all 0.15s;
        }

        .ch-expand-btn:hover {
            background: rgba(255,255,255,.05);
            color: var(--text, #e9f0f6);
        }

        .ch-entry.expanded .ch-expand-btn svg {
            transform: rotate(180deg);
        }

        .ch-expand-btn svg {
            transition: transform 0.2s ease;
        }

        /* Entry Preview */
        .ch-entry-preview {
            padding: 0 var(--sp-3, 12px) var(--sp-2, 8px);
            border-bottom: 1px solid var(--line-soft, #141f27);
        }

        .ch-entry.expanded .ch-entry-preview {
            border-bottom: none;
        }

        .ch-preview-row {
            display: flex;
            gap: var(--sp-2, 8px);
            margin-bottom: var(--sp-1, 4px);
            min-height: 20px;
        }

        .ch-preview-row:last-of-type {
            margin-bottom: var(--sp-1, 4px);
        }

        .ch-preview-label {
            flex: 0 0 50px;
            font-size: 11px;
            font-weight: 600;
            color: var(--mint, #7cf0b8);
            font-family: var(--mono);
        }

        .ch-preview-text {
            flex: 1;
            font-size: 11.5px;
            color: var(--text, #e9f0f6);
            line-height: 1.5;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .ch-preview-agents {
            display: flex;
            flex-wrap: wrap;
            gap: 4px;
            margin-top: var(--sp-1, 4px);
            padding-top: var(--sp-1, 4px);
            border-top: 1px dashed var(--line-soft, #141f27);
        }

        .ch-agent-badge {
            display: inline-flex;
            align-items: center;
            padding: 2px 8px;
            border-radius: 99px;
            font-size: 8.5px;
            font-weight: 700;
            letter-spacing: .05em;
            text-transform: uppercase;
        }

        /* Entry Details */
        .ch-entry-details {
            padding: var(--sp-3, 12px) var(--sp-4, 16px);
            animation: ch-slide-down 0.2s ease;
        }

        @keyframes ch-slide-down {
            from { opacity: 0; transform: translateY(-8px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .ch-details-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: var(--sp-4, 16px);
        }

        .ch-details-section {
            background: rgba(255,255,255,.02);
            border: 1px solid var(--line, #1b2833);
            border-radius: var(--r-sm, 8px);
            overflow: hidden;
        }

        .ch-details-section h4 {
            margin: 0;
            padding: var(--sp-2, 8px) var(--sp-3, 12px);
            font-size: 10px;
            font-weight: 700;
            letter-spacing: .1em;
            text-transform: uppercase;
            color: var(--mint, #7cf0b8);
            background: rgba(124, 240, 184, 0.05);
            border-bottom: 1px solid var(--line-soft, #141f27);
        }

        .ch-details-content {
            margin: 0;
            padding: var(--sp-3, 12px);
            font-family: var(--mono);
            font-size: 10.5px;
            line-height: 1.6;
            color: var(--text, #e9f0f6);
            white-space: pre-wrap;
            word-wrap: break-word;
            max-height: 400px;
            overflow-y: auto;
        }

        .ch-agents-list {
            display: flex;
            flex-direction: column;
            gap: 4px;
            padding: var(--sp-3, 12px);
        }

        .ch-agent-detail {
            display: flex;
            align-items: center;
            gap: var(--sp-2, 8px);
            padding: var(--sp-1, 4px) var(--sp-2, 8px);
            border-left: 3px solid;
            background: rgba(255,255,255,.02);
            border-radius: 0 var(--r-sm, 8px) var(--r-sm, 8px) 0;
        }

        .ch-agent-name {
            font-family: var(--mono);
            font-size: 10px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: .05em;
            color: var(--text, #e9f0f6);
            min-width: 100px;
        }

        .ch-agent-role {
            font-size: 10.5px;
            color: var(--muted, #8195a5);
        }

        /* Load More */
        .ch-load-more {
            display: flex;
            justify-content: center;
            padding: var(--sp-3, 12px) var(--sp-4, 16px);
            border-top: 1px solid var(--line-soft, #141f27);
        }

        /* Responsive */
        @media (max-width: 768px) {
            .ch-filter-group {
                min-width: 100%;
            }
            .ch-details-grid {
                grid-template-columns: 1fr;
            }
            .ch-entry-header {
                flex-direction: column;
                align-items: flex-start;
            }
            .ch-entry-status {
                margin-left: 0;
                width: 100%;
                justify-content: space-between;
            }
        }
        </style>
    `;

    // ========================================================================
    // Conversation History Panel Class
    // ========================================================================

    class ConversationHistoryPanel {
        constructor() {
            this.container = null;
            this.entries = [];
            this.filteredEntries = [];
            this.currentPage = 0;
            this.pageSize = 50;
            this.hasMore = true;
            this.isLoading = false;
            this.filters = {
                dateFrom: null,
                dateTo: null,
                agent: '',
                status: '',
                search: ''
            };
            this.expandedEntryId = null;
            this.agentColors = {
                'friday': '#7cf0b8',
                'stratex': '#f3c46a',
                'vyralx': '#b6a4ff',
                'cortex': '#6bc9e8',
                'inference': '#ff7d7d',
                'forge': '#7cf0b8',
                'memora': '#f3c46a',
                'intelx': '#b6a4ff',
                'futuris': '#6bc9e8',
                'sentinel': '#ff7d7d'
            };
            this.statusColors = {
                'success': '#7cf0b8',
                'failed': '#ff7d7d',
                'pending': '#f3c46a',
                'running': '#6bc9e8',
                'cancelled': '#8195a5'
            };
        }

        // ========================================================================
        // Public API Methods
        // ========================================================================

        /**
         * Initialize the conversation history panel
         * @param {HTMLElement|string} container - Container element or selector
         */
        init(container) {
            this.container = typeof container === 'string' ? document.querySelector(container) : container;
            if (!this.container) {
                console.error('ConversationHistoryPanel: Container not found');
                return this;
            }

            // Inject styles once
            if (!document.getElementById('conversation-history-styles')) {
                const styleEl = document.createElement('div');
                styleEl.innerHTML = STYLES;
                document.head.appendChild(styleEl.firstElementChild);
            }

            this.render();
            this.bindEvents();
            this.loadHistory();
            return this;
        }

        /**
         * Load conversation history from API
         * @param {boolean} append - Whether to append to existing entries (for infinite scroll)
         */
        async loadHistory(append = false) {
            if (this.isLoading) return;
            this.isLoading = true;

            try {
                const params = new URLSearchParams({
                    limit: this.pageSize,
                    offset: append ? this.entries.length : 0,
                    ...this._buildFilterParams()
                });

                const response = await fetch(`/api/v1/conversation/history?${params}`, {
                    headers: this._getAuthHeaders()
                });

                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }

                const data = await response.json();
                const newEntries = data.entries || [];

                if (append) {
                    this.entries = [...this.entries, ...newEntries];
                } else {
                    this.entries = newEntries;
                }

                this.hasMore = data.has_more || false;
                this.currentPage = append ? this.currentPage + 1 : 0;
                this.applyFilters();
                this.renderEntries();

            } catch (error) {
                console.error('Failed to load conversation history:', error);
                this._showError('Failed to load conversation history');
            } finally {
                this.isLoading = false;
                this._updateLoadMoreButton();
            }
        }

        /**
         * Add a new conversation entry
         * @param {Object} entry - Conversation entry object
         */
        addEntry(entry) {
            const normalizedEntry = this._normalizeEntry(entry);
            this.entries.unshift(normalizedEntry);
            this.applyFilters();
            this.renderEntries();
        }

        /**
         * Filter history by criteria
         * @param {Object} criteria - Filter criteria
         */
        filterHistory(criteria) {
            this.filters = { ...this.filters, ...criteria };
            this.currentPage = 0;
            this.applyFilters();
            this.renderEntries();
        }

        /**
         * Export conversation history
         * @param {string} format - Export format ('json' or 'markdown')
         * @returns {Promise<string>} - Exported content
         */
        async exportHistory(format = 'json') {
            try {
                const params = new URLSearchParams({
                    format,
                    ...this._buildFilterParams()
                });

                const response = await fetch(`/api/v1/conversation/export?${params}`, {
                    headers: this._getAuthHeaders()
                });

                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }

                if (format === 'json') {
                    return await response.json();
                } else {
                    return await response.text();
                }
            } catch (error) {
                console.error('Failed to export conversation history:', error);
                throw error;
            }
        }

        // ========================================================================
        // Private Methods - Rendering
        // ========================================================================

        render() {
            this.container.innerHTML = `
                <div class="conversation-history-panel">
                    ${this._renderHeader()}
                    ${this._renderFilters()}
                    ${this._renderEntriesContainer()}
                    ${this._renderLoadMore()}
                </div>
            `;
        }

        _renderHeader() {
            return `
                <div class="ch-header">
                    <div class="ch-title">
                        <h2>Conversation History</h2>
                        <span class="ch-count" id="ch-entry-count">0 entries</span>
                    </div>
                    <div class="ch-actions">
                        <button class="ch-btn ch-btn-secondary" id="ch-export-json" title="Export as JSON">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                                <polyline points="17 8 12 3 7 8"/>
                                <line x1="12" y1="3" x2="12" y2="15"/>
                            </svg>
                            JSON
                        </button>
                        <button class="ch-btn ch-btn-secondary" id="ch-export-md" title="Export as Markdown">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                                <polyline points="14 2 14 8 20 8"/>
                                <line x1="16" y1="13" x2="8" y2="13"/>
                                <line x1="16" y1="17" x2="8" y2="17"/>
                                <polyline points="10 9 9 9 8 9"/>
                            </svg>
                            Markdown
                        </button>
                        <button class="ch-btn ch-btn-primary" id="ch-refresh" title="Refresh">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <polyline points="23 4 23 10 17 10"/>
                                <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
                            </svg>
                        </button>
                    </div>
                </div>
            `;
        }

        _renderFilters() {
            return `
                <div class="ch-filters" id="ch-filters">
                    <div class="ch-filter-row">
                        <div class="ch-filter-group">
                            <label for="ch-search">Search</label>
                            <input type="text" id="ch-search" placeholder="Search conversations..." value="${this.filters.search || ''}">
                        </div>
                        <div class="ch-filter-group">
                            <label for="ch-agent-filter">Agent</label>
                            <select id="ch-agent-filter">
                                <option value="">All Agents</option>
                                <option value="friday" ${this.filters.agent === 'friday' ? 'selected' : ''}>FRIDAY</option>
                                <option value="stratex" ${this.filters.agent === 'stratex' ? 'selected' : ''}>Stratex</option>
                                <option value="vyralx" ${this.filters.agent === 'vyralx' ? 'selected' : ''}>VyralX</option>
                                <option value="cortex" ${this.filters.agent === 'cortex' ? 'selected' : ''}>Cortex</option>
                                <option value="inference" ${this.filters.agent === 'inference' ? 'selected' : ''}>Inference</option>
                                <option value="forge" ${this.filters.agent === 'forge' ? 'selected' : ''}>Forge</option>
                                <option value="memora" ${this.filters.agent === 'memora' ? 'selected' : ''}>Memora</option>
                                <option value="intelx" ${this.filters.agent === 'intelx' ? 'selected' : ''}>IntelX</option>
                                <option value="futuris" ${this.filters.agent === 'futuris' ? 'selected' : ''}>Futuris</option>
                                <option value="sentinel" ${this.filters.agent === 'sentinel' ? 'selected' : ''}>Sentinel</option>
                            </select>
                        </div>
                        <div class="ch-filter-group">
                            <label for="ch-status-filter">Status</label>
                            <select id="ch-status-filter">
                                <option value="">All Statuses</option>
                                <option value="success" ${this.filters.status === 'success' ? 'selected' : ''}>Success</option>
                                <option value="failed" ${this.filters.status === 'failed' ? 'selected' : ''}>Failed</option>
                                <option value="pending" ${this.filters.status === 'pending' ? 'selected' : ''}>Pending</option>
                                <option value="running" ${this.filters.status === 'running' ? 'selected' : ''}>Running</option>
                                <option value="cancelled" ${this.filters.status === 'cancelled' ? 'selected' : ''}>Cancelled</option>
                            </select>
                        </div>
                    </div>
                    <div class="ch-filter-row">
                        <div class="ch-filter-group">
                            <label for="ch-date-from">From</label>
                            <input type="datetime-local" id="ch-date-from" value="${this.filters.dateFrom || ''}">
                        </div>
                        <div class="ch-filter-group">
                            <label for="ch-date-to">To</label>
                            <input type="datetime-local" id="ch-date-to" value="${this.filters.dateTo || ''}">
                        </div>
                        <div class="ch-filter-group">
                            <button class="ch-btn ch-btn-secondary" id="ch-clear-filters">Clear Filters</button>
                        </div>
                    </div>
                </div>
            `;
        }

        _renderEntriesContainer() {
            return `
                <div class="ch-entries" id="ch-entries">
                    <div class="ch-loading" id="ch-loading" style="display: none;">
                        <div class="ch-spinner"></div>
                        <span>Loading conversations...</span>
                    </div>
                    <div class="ch-empty" id="ch-empty" style="display: none;">
                        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                            <rect x="2" y="3" width="20" height="14" rx="2" ry="2"/>
                            <path d="M8 21h8"/>
                            <path d="M12 17v4"/>
                        </svg>
                        <p>No conversations found</p>
                    </div>
                </div>
            `;
        }

        _renderLoadMore() {
            return `
                <div class="ch-load-more" id="ch-load-more" style="display: none;">
                    <button class="ch-btn ch-btn-primary" id="ch-load-more-btn">Load More</button>
                </div>
            `;
        }

        renderEntries() {
            const entriesContainer = this.container.querySelector('#ch-entries');
            const countEl = this.container.querySelector('#ch-entry-count');
            const emptyEl = this.container.querySelector('#ch-empty');
            const loadingEl = this.container.querySelector('#ch-loading');

            if (this.filteredEntries.length === 0) {
                entriesContainer.querySelectorAll('.ch-entry').forEach(el => el.remove());
                emptyEl.style.display = 'flex';
                countEl.textContent = '0 entries';
            } else {
                emptyEl.style.display = 'none';
                countEl.textContent = `${this.filteredEntries.length} ${this.filteredEntries.length === 1 ? 'entry' : 'entries'}`;

                // Render entries
                const entriesHtml = this.filteredEntries.map(entry => this._renderEntry(entry)).join('');
                entriesContainer.innerHTML = entriesHtml + entriesContainer.innerHTML.replace(/<div class="ch-loading.*?<\/div>/, '').replace(/<div class="ch-empty.*?<\/div>/, '');
            }

            this._updateLoadMoreButton();
        }

        _renderEntry(entry) {
            const timestamp = this._formatTimestamp(entry.timestamp);
            const inputType = entry.input_type || 'text';
            const status = entry.status || 'pending';
            const agents = entry.agents_involved || [];
            const userInput = this._truncate(entry.user_input || '', 120);
            const fridayReply = this._truncate(entry.friday_reply || '', 120);

            const agentBadges = agents.map(agent => 
                `<span class="ch-agent-badge" style="background: ${this.agentColors[agent] || '#1b2833'}; color: #06090d;">${agent.toUpperCase()}</span>`
            ).join('');

            const statusColor = this.statusColors[status] || '#8195a5';

            return `
                <article class="ch-entry ${this.expandedEntryId === entry.id ? 'expanded' : ''}" data-entry-id="${entry.id}">
                    <div class="ch-entry-header">
                        <div class="ch-entry-meta">
                            <time class="ch-timestamp" datetime="${entry.timestamp}">${timestamp}</time>
                            <span class="ch-input-type ${inputType}">
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    ${inputType === 'voice' 
                                        ? '<path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/>'
                                        : '<path d="M4 21h16"/><path d="M6 9H4"/><path d="M10 9h.01"/><path d="M14 9h.01"/><path d="M18 9h.01"/><path d="M6 14H4"/><path d="M10 14h.01"/><path d="M14 14h.01"/>'
                                    }
                                </svg>
                                ${inputType}
                            </span>
                        </div>
                        <div class="ch-entry-status">
                            <span class="ch-status-badge" style="background: ${statusColor}22; color: ${statusColor}; border-color: ${statusColor}44;">
                                ${status.toUpperCase()}
                            </span>
                            <button class="ch-expand-btn" aria-label="Expand">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <polyline points="6 9 12 15 18 9"/>
                                </svg>
                            </button>
                        </div>
                    </div>

                    <div class="ch-entry-preview">
                        <div class="ch-preview-row">
                            <span class="ch-preview-label">You:</span>
                            <span class="ch-preview-text">${this._escapeHtml(userInput)}</span>
                        </div>
                        <div class="ch-preview-row">
                            <span class="ch-preview-label">FRIDAY:</span>
                            <span class="ch-preview-text">${this._escapeHtml(fridayReply)}</span>
                        </div>
                        ${agents.length > 0 ? `
                        <div class="ch-preview-agents">
                            ${agentBadges}
                        </div>
                        ` : ''}
                    </div>

                    <div class="ch-entry-details" style="display: ${this.expandedEntryId === entry.id ? 'block' : 'none'};">
                        ${this._renderEntryDetails(entry)}
                    </div>
                </article>
            `;
        }

        _renderEntryDetails(entry) {
            const agents = entry.agents_involved || [];
            const metadata = entry.metadata || {};
            const fullUserInput = entry.user_input || '';
            const fullFridayReply = entry.friday_reply || '';

            return `
                <div class="ch-details-grid">
                    <div class="ch-details-section">
                        <h4>User Input</h4>
                        <pre class="ch-details-content">${this._escapeHtml(fullUserInput)}</pre>
                    </div>
                    <div class="ch-details-section">
                        <h4>FRIDAY's Reply</h4>
                        <pre class="ch-details-content">${this._escapeHtml(fullFridayReply)}</pre>
                    </div>
                    ${agents.length > 0 ? `
                    <div class="ch-details-section">
                        <h4>Agents Involved</h4>
                        <div class="ch-agents-list">
                            ${agents.map(agent => `
                                <div class="ch-agent-detail" style="border-left-color: ${this.agentColors[agent] || '#1b2833'}">
                                    <span class="ch-agent-name">${agent.toUpperCase()}</span>
                                    <span class="ch-agent-role">${this._getAgentRole(agent)}</span>
                                </div>
                            `).join('')}
                        </div>
                    </div>
                    ` : ''}
                    ${Object.keys(metadata).length > 0 ? `
                    <div class="ch-details-section">
                        <h4>Metadata</h4>
                        <pre class="ch-details-content">${this._escapeHtml(JSON.stringify(metadata, null, 2))}</pre>
                    </div>
                    ` : ''}
                    <div class="ch-details-section">
                        <h4>Raw Entry</h4>
                        <pre class="ch-details-content">${this._escapeHtml(JSON.stringify(entry, null, 2))}</pre>
                    </div>
                </div>
            `;
        }

        // ========================================================================
        // Private Methods - Event Binding
        // ========================================================================

        bindEvents() {
            // Search input
            this.container.addEventListener('input', (e) => {
                if (e.target.id === 'ch-search') {
                    this.filters.search = e.target.value;
                    this._debounceFilter();
                }
            });

            // Filter selects
            this.container.addEventListener('change', (e) => {
                if (e.target.id === 'ch-agent-filter') {
                    this.filters.agent = e.target.value;
                    this.applyFilters();
                    this.renderEntries();
                } else if (e.target.id === 'ch-status-filter') {
                    this.filters.status = e.target.value;
                    this.applyFilters();
                    this.renderEntries();
                } else if (e.target.id === 'ch-date-from') {
                    this.filters.dateFrom = e.target.value;
                    this._debounceFilter();
                } else if (e.target.id === 'ch-date-to') {
                    this.filters.dateTo = e.target.value;
                    this._debounceFilter();
                }
            });

            // Clear filters
            this.container.addEventListener('click', (e) => {
                if (e.target.id === 'ch-clear-filters') {
                    this.filters = {
                        dateFrom: null,
                        dateTo: null,
                        agent: '',
                        status: '',
                        search: ''
                    };
                    this._updateFilterInputs();
                    this.applyFilters();
                    this.renderEntries();
                }
            });

            // Export buttons
            this.container.addEventListener('click', async (e) => {
                if (e.target.id === 'ch-export-json' || e.target.closest('#ch-export-json')) {
                    await this._handleExport('json');
                } else if (e.target.id === 'ch-export-md' || e.target.closest('#ch-export-md')) {
                    await this._handleExport('markdown');
                }
            });

            // Refresh button
            this.container.addEventListener('click', (e) => {
                if (e.target.id === 'ch-refresh' || e.target.closest('#ch-refresh')) {
                    this.loadHistory(false);
                }
            });

            // Load more button
            this.container.addEventListener('click', (e) => {
                if (e.target.id === 'ch-load-more-btn' || e.target.closest('#ch-load-more-btn')) {
                    this.loadHistory(true);
                }
            });

            // Entry expand/collapse
            this.container.addEventListener('click', (e) => {
                const entryEl = e.target.closest('.ch-entry');
                const expandBtn = e.target.closest('.ch-expand-btn');
                
                if (expandBtn && entryEl) {
                    const entryId = entryEl.dataset.entryId;
                    this.expandedEntryId = this.expandedEntryId === entryId ? null : entryId;
                    this.renderEntries();
                }
            });

            // Infinite scroll
            const entriesContainer = this.container.querySelector('#ch-entries');
            if (entriesContainer) {
                entriesContainer.addEventListener('scroll', () => {
                    if (entriesContainer.scrollTop + entriesContainer.clientHeight >= entriesContainer.scrollHeight - 100) {
                        if (this.hasMore && !this.isLoading) {
                            this.loadHistory(true);
                        }
                    }
                });
            }
        }

        // ========================================================================
        // Private Methods - Filtering & Data
        // ========================================================================

        applyFilters() {
            this.filteredEntries = this.entries.filter(entry => {
                // Search filter
                if (this.filters.search) {
                    const search = this.filters.search.toLowerCase();
                    const userInput = (entry.user_input || '').toLowerCase();
                    const fridayReply = (entry.friday_reply || '').toLowerCase();
                    if (!userInput.includes(search) && !fridayReply.includes(search)) {
                        return false;
                    }
                }

                // Agent filter
                if (this.filters.agent) {
                    const agents = entry.agents_involved || [];
                    if (!agents.includes(this.filters.agent)) {
                        return false;
                    }
                }

                // Status filter
                if (this.filters.status) {
                    if ((entry.status || 'pending') !== this.filters.status) {
                        return false;
                    }
                }

                // Date filters
                if (this.filters.dateFrom) {
                    const entryDate = new Date(entry.timestamp);
                    const fromDate = new Date(this.filters.dateFrom);
                    if (entryDate < fromDate) return false;
                }

                if (this.filters.dateTo) {
                    const entryDate = new Date(entry.timestamp);
                    const toDate = new Date(this.filters.dateTo);
                    toDate.setHours(23, 59, 59, 999);
                    if (entryDate > toDate) return false;
                }

                return true;
            });
        }

        _debounceFilter() {
            clearTimeout(this._filterTimeout);
            this._filterTimeout = setTimeout(() => {
                this.currentPage = 0;
                this.applyFilters();
                this.renderEntries();
            }, 300);
        }

        _updateFilterInputs() {
            const searchInput = this.container.querySelector('#ch-search');
            const agentSelect = this.container.querySelector('#ch-agent-filter');
            const statusSelect = this.container.querySelector('#ch-status-filter');
            const dateFromInput = this.container.querySelector('#ch-date-from');
            const dateToInput = this.container.querySelector('#ch-date-to');

            if (searchInput) searchInput.value = this.filters.search || '';
            if (agentSelect) agentSelect.value = this.filters.agent || '';
            if (statusSelect) statusSelect.value = this.filters.status || '';
            if (dateFromInput) dateFromInput.value = this.filters.dateFrom || '';
            if (dateToInput) dateToInput.value = this.filters.dateTo || '';
        }

        _updateLoadMoreButton() {
            const loadMoreContainer = this.container.querySelector('#ch-load-more');
            const loadMoreBtn = this.container.querySelector('#ch-load-more-btn');
            
            if (loadMoreContainer) {
                loadMoreContainer.style.display = this.hasMore ? 'flex' : 'none';
            }
            if (loadMoreBtn) {
                loadMoreBtn.disabled = this.isLoading;
                loadMoreBtn.textContent = this.isLoading ? 'Loading...' : 'Load More';
            }
        }

        _showError(message) {
            const entriesContainer = this.container.querySelector('#ch-entries');
            entriesContainer.innerHTML = `
                <div class="ch-error">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <circle cx="12" cy="12" r="10"/>
                        <line x1="12" y1="8" x2="12" y2="12"/>
                        <line x1="12" y1="16" x2="12.01" y2="16"/>
                    </svg>
                    <p>${this._escapeHtml(message)}</p>
                </div>
            `;
        }

        // ========================================================================
        // Private Methods - Export
        // ========================================================================

        async _handleExport(format) {
            const btn = this.container.querySelector(format === 'json' ? '#ch-export-json' : '#ch-export-md');
            const originalText = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = '<div class="ch-spinner-sm"></div> Exporting...';

            try {
                const content = await this.exportHistory(format);
                this._downloadFile(content, format);
            } catch (error) {
                alert(`Export failed: ${error.message}`);
            } finally {
                btn.disabled = false;
                btn.innerHTML = originalText;
            }
        }

        _downloadFile(content, format) {
            const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
            const filename = `friday-conversation-${timestamp}.${format === 'json' ? 'json' : 'md'}`;
            const blob = new Blob([typeof content === 'string' ? content : JSON.stringify(content, null, 2)], {
                type: format === 'json' ? 'application/json' : 'text/markdown'
            });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        }

        // ========================================================================
        // Private Methods - Helpers
        // ========================================================================

        _buildFilterParams() {
            const params = {};
            if (this.filters.dateFrom) params.date_from = this.filters.dateFrom;
            if (this.filters.dateTo) params.date_to = this.filters.dateTo;
            if (this.filters.agent) params.agent = this.filters.agent;
            if (this.filters.status) params.status = this.filters.status;
            if (this.filters.search) params.search = this.filters.search;
            return params;
        }

        _getAuthHeaders() {
            const token = localStorage.getItem('friday_control_token') || 
                         document.cookie.split('; ').find(row => row.startsWith('friday_control_token='))?.split('=')[1];
            return token ? { 'X-FRIDAY-Control-Token': token } : {};
        }

        _normalizeEntry(entry) {
            return {
                id: entry.id || `entry-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
                timestamp: entry.timestamp || new Date().toISOString(),
                user_input: entry.user_input || entry.input || '',
                friday_reply: entry.friday_reply || entry.reply || entry.response || '',
                input_type: entry.input_type || entry.type || 'text',
                status: entry.status || 'success',
                agents_involved: entry.agents_involved || entry.agents || [],
                metadata: entry.metadata || {}
            };
        }

        _formatTimestamp(isoString) {
            const date = new Date(isoString);
            const now = new Date();
            const diff = now - date;

            if (diff < 60000) return 'Just now';
            if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
            if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
            if (diff < 604800000) return `${Math.floor(diff / 86400000)}d ago`;

            return date.toLocaleDateString(undefined, {
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
            });
        }

        _truncate(str, maxLen) {
            if (str.length <= maxLen) return str;
            return str.slice(0, maxLen) + '…';
        }

        _escapeHtml(str) {
            const div = document.createElement('div');
            div.textContent = str;
            return div.innerHTML;
        }

        _getAgentRole(agent) {
            const roles = {
                'friday': 'Orchestrator',
                'stratex': 'Trading Intelligence',
                'vyralx': 'Video Content Intelligence',
                'cortex': 'CRM & Web Operations',
                'inference': 'LLM Gateway & Model Router',
                'forge': 'Autonomous Coding Agent',
                'memora': 'Memory Intelligence',
                'intelx': 'Threat Intelligence',
                'futuris': 'Predictive Intelligence',
                'sentinel': 'Security Operations'
            };
            return roles[agent] || 'Specialist Agent';
        }
    }

    // ========================================================================
    // Export for module systems
    // ========================================================================

    if (typeof module !== 'undefined' && module.exports) {
        module.exports = ConversationHistoryPanel;
    } else if (typeof define === 'function' && define.amd) {
        define([], () => ConversationHistoryPanel);
    } else {
        window.ConversationHistoryPanel = ConversationHistoryPanel;
    }
})();