/**
 * FRIDAY Memory Panel — Memora Integration
 * 
 * Shows current conversation context and stored memories with search,
 * store, preview, copy, and delete functionality.
 * 
 * API Endpoints (Memora /v1/context):
 * - GET  /search?q=&level=&limit=  → Search memories
 * - POST /remember                  → Store a memory
 * - POST /sessions/commit           → Store current conversation
 * - GET  /read?uri=&level=          → Read memory content
 * - DELETE /write?uri=              → Delete memory (if supported)
 */

(function () {
  "use strict";

  // ────────────────────────────────────────────────────────────────────────
  // Configuration
  // ────────────────────────────────────────────────────────────────────────

  const API_BASE = (function () {
    const p = window.location.pathname;
    if (p === "/friday" || p.indexOf("/friday/") === 0) return "/friday";
    return "";
  })() + "/api/v1/memora/context";  // Proxied through FRIDAY gateway

  const DEBOUNCE_MS = 250;
  const MAX_MEMORIES_DISPLAY = 50;
  const PREVIEW_MAX_CHARS = 500;

  // ────────────────────────────────────────────────────────────────────────
  // State
  // ────────────────────────────────────────────────────────────────────────

  let memoryPanel = null;
  let searchInput = null;
  let memoriesContainer = null;
  let currentConversationEl = null;
  let storedMemoriesEl = null;
  let relevantContextEl = null;
  let searchDebounceTimer = null;
  let currentQuery = "";
  let isLoading = false;
  let conversationTurns = [];  // Current session turns
  let selectedMemory = null;

  // ────────────────────────────────────────────────────────────────────────
  // Utility Functions
  // ────────────────────────────────────────────────────────────────────────

  function $(id) { return document.getElementById(id); }

  function escapeHtml(str) {
    return String(str == null ? "" : str)
      .replace(/&/g, "&")
      .replace(/</g, "<")
      .replace(/>/g, ">")
      .replace(/"/g, """)
      .replace(/'/g, "'");
  }

  function formatTimestamp(iso) {
    if (!iso) return "—";
    try {
      const d = new Date(iso);
      const now = new Date();
      const diff = now - d;
      if (diff < 60000) return "just now";
      if (diff < 3600000) return Math.floor(diff / 60000) + "m ago";
      if (diff < 86400000) return Math.floor(diff / 3600000) + "h ago";
      if (diff < 604800000) return Math.floor(diff / 86400000) + "d ago";
      return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
    } catch { return iso; }
  }

  function truncate(str, max) {
    if (!str || str.length <= max) return str;
    return str.slice(0, max).trim() + "…";
  }

  function showToast(message, type = "info") {
    const toast = $("toast");
    if (!toast) return;
    toast.textContent = message;
    toast.className = "toast show " + (type === "error" ? "bad" : type === "warn" ? "warn" : "");
    clearTimeout(toast._hideTimer);
    toast._hideTimer = setTimeout(() => toast.classList.remove("show"), 3000);
  }

  async function apiRequest(path, options = {}) {
    const token = window.fridayToken || (await ensureControlToken());
    const headers = Object.assign({ "Content-Type": "application/json" }, options.headers || {});
    if (token) headers["X-FRIDAY-Control-Token"] = token;

    const res = await fetch(API_BASE + path, Object.assign({}, options, { headers, cache: "no-store" }));
    if (res.status === 401 || res.status === 403) {
      window.fridayToken = null;
      throw new Error("Authentication required");
    }
    const text = await res.text();
    let body = null;
    try { body = text ? JSON.parse(text) : null; } catch { body = { raw: text }; }
    if (!res.ok) {
      const detail = body && (body.detail || body.error || body.message);
      throw new Error(typeof detail === "string" ? detail : (res.status + " " + res.statusText));
    }
    return body;
  }

  async function ensureControlToken() {
    if (window.fridayToken && Date.now() / 1000 < (window.fridayTokenExpiry || 0) - 30) {
      return window.fridayToken;
    }
    const base = (function () {
      const p = window.location.pathname;
      if (p === "/friday" || p.indexOf("/friday/") === 0) return "/friday";
      return "";
    })();
    const r = await fetch(base + "/api/control/session", { cache: "no-store" });
    if (!r.ok) throw new Error("control session " + r.status);
    const d = await r.json();
    window.fridayToken = d.token;
    window.fridayTokenExpiry = Number(d.expires_at || 0) || (Date.now() / 1000 + 600);
    return window.fridayToken;
  }

  // ────────────────────────────────────────────────────────────────────────
  // Memory Panel Class
  // ────────────────────────────────────────────────────────────────────────

  class MemoryPanel {
    constructor(container) {
      this.container = typeof container === "string" ? $(container) : container;
      if (!this.container) throw new Error("Memory panel container not found");
      this.render();
      this.bindEvents();
      this.loadInitialData();
    }

    render() {
      this.container.innerHTML = `
        <div class="memory-panel" role="region" aria-label="Memory & Context">
          <!-- Search Bar -->
          <div class="memory-search">
            <label class="sr-only" for="memorySearch">Search memories</label>
            <div class="search-wrapper">
              <svg class="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
                <circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>
              </svg>
              <input type="search" id="memorySearch" class="search-input" placeholder="Search memories…" aria-label="Search memories" autocomplete="off">
              <button type="button" class="search-clear" id="memorySearchClear" aria-label="Clear search" hidden>✕</button>
            </div>
            <div class="search-hint">Press <kbd>/</kbd> to focus</div>
          </div>

          <!-- Three Sections -->
          <div class="memory-sections">
            <!-- Section 1: Current Conversation -->
            <section class="memory-section" data-section="conversation">
              <header class="section-header">
                <h3 class="section-title">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
                    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
                  </svg>
                  Current Conversation
                </h3>
                <div class="section-actions">
                  <button type="button" class="btn sm" id="storeConversationBtn" title="Store this conversation in memory">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><path d="M17 21v-5a2 2 0 0 1 2-2h2"/></svg>
                    Store
                  </button>
                </div>
              </header>
              <div class="section-body" id="currentConversation">
                <div class="empty-state">No active conversation yet. Send a command to start.</div>
              </div>
            </section>

            <!-- Section 2: Stored Memories -->
            <section class="memory-section" data-section="stored">
              <header class="section-header">
                <h3 class="section-title">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
                    <path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/>
                    <path d="M3 6h18"/><path d="M16 10a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2h10z"/>
                  </svg>
                  Stored Memories
                </h3>
                <span class="memory-count" id="storedCount">0</span>
              </header>
              <div class="section-body memories-grid" id="storedMemories">
                <div class="empty-state">No memories stored yet.</div>
              </div>
            </section>

            <!-- Section 3: Relevant Context -->
            <section class="memory-section" data-section="relevant">
              <header class="section-header">
                <h3 class="section-title">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
                    <circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>
                  </svg>
                  Relevant Context
                </h3>
                <span class="section-sub">Auto-loaded for current goal</span>
              </header>
              <div class="section-body memories-grid" id="relevantContext">
                <div class="empty-state">Submit a goal to see relevant memories.</div>
              </div>
            </section>
          </div>

          <!-- Memory Preview Modal -->
          <div class="memory-preview-overlay" id="memoryPreviewOverlay" role="dialog" aria-modal="true" aria-labelledby="previewTitle" hidden>
            <div class="memory-preview">
              <header class="preview-header">
                <h3 id="previewTitle">Memory Preview</h3>
                <button type="button" class="btn icon" id="previewClose" aria-label="Close preview">✕</button>
              </header>
              <div class="preview-body" id="previewBody"></div>
              <footer class="preview-footer">
                <div class="preview-meta" id="previewMeta"></div>
                <div class="preview-actions">
                  <button type="button" class="btn sm" id="previewCopy">Copy</button>
                  <button type="button" class="btn sm danger" id="previewDelete">Delete</button>
                </div>
              </footer>
            </div>
          </div>
        </div>

        <style>
          /* Memory Panel Styles */
          .memory-panel {
            display: grid;
            grid-template-rows: auto 1fr;
            gap: var(--sp-3);
            height: 100%;
            min-height: 400px;
            font-family: inherit;
          }

          /* Search */
          .memory-search {
            position: relative;
          }
          .search-wrapper {
            position: relative;
            display: flex;
            align-items: center;
          }
          .search-icon {
            position: absolute;
            left: 12px;
            width: 18px; height: 18px;
            color: var(--muted-2);
            pointer-events: none;
          }
          .search-input {
            width: 100%;
            padding: 10px 12px 10px 42px;
            border: 1px solid var(--line);
            border-radius: var(--r-md);
            background: var(--bg);
            color: var(--text);
            font: inherit;
            font-size: 13px;
            transition: border-color .16s, box-shadow .16s;
          }
          .search-input:focus {
            outline: none;
            border-color: var(--mint);
            box-shadow: 0 0 0 3px rgba(124,240,184,.1);
          }
          .search-clear {
            position: absolute;
            right: 10px;
            width: 24px; height: 24px;
            border: none;
            background: transparent;
            color: var(--muted-2);
            font-size: 14px;
            cursor: pointer;
            border-radius: 6px;
            display: flex; align-items: center; justify-content: center;
          }
          .search-clear:hover { background: var(--panel-2); color: var(--text); }
          .search-hint {
            margin-top: 6px;
            font-size: 10px;
            color: var(--muted-2);
          }
          .search-hint kbd {
            font-family: var(--mono);
            font-size: 9px;
            padding: 1px 5px;
            background: var(--panel-2);
            border: 1px solid var(--line);
            border-radius: 4px;
          }

          /* Sections */
          .memory-sections {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: var(--sp-3);
            overflow: hidden;
          }
          @media (max-width: 1100px) {
            .memory-sections { grid-template-columns: 1fr; }
          }

          .memory-section {
            display: flex;
            flex-direction: column;
            border: 1px solid var(--line);
            border-radius: var(--r-md);
            background: var(--panel);
            overflow: hidden;
            min-height: 0;
          }

          .section-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: var(--sp-2);
            padding: var(--sp-3) var(--sp-4);
            border-bottom: 1px solid var(--line-soft);
            background: rgba(255,255,255,.01);
            flex-wrap: wrap;
          }
          .section-title {
            display: flex;
            align-items: center;
            gap: 8px;
            margin: 0;
            font-size: 13px;
            font-weight: 650;
          }
          .section-title svg { width: 16px; height: 16px; color: var(--muted); flex-shrink: 0; }
          .section-sub { font-size: 10.5px; color: var(--muted-2); }
          .memory-count {
            font-family: var(--mono);
            font-size: 10.5px;
            color: var(--muted);
            border: 1px solid var(--line);
            padding: 2px 8px;
            border-radius: 99px;
          }
          .section-actions { display: flex; gap: 6px; }

          .section-body {
            flex: 1;
            overflow: auto;
            padding: var(--sp-3);
            min-height: 0;
          }

          /* Empty State */
          .empty-state {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 100%;
            min-height: 120px;
            color: var(--muted-2);
            font-size: 12px;
            text-align: center;
            padding: var(--sp-5);
          }
          .empty-state::before {
            content: "";
            width: 32px; height: 32px;
            margin-bottom: 10px;
            border: 1px dashed var(--line);
            border-radius: 10px;
            display: block;
          }

          /* Memories Grid */
          .memories-grid {
            display: grid;
            gap: var(--sp-2);
          }

          /* Memory Card */
          .memory-card {
            border: 1px solid var(--line);
            border-radius: var(--r-sm);
            background: var(--panel-2);
            padding: var(--sp-3);
            cursor: pointer;
            transition: border-color .16s, background .16s, transform .16s;
            position: relative;
          }
          .memory-card:hover {
            border-color: var(--mint-dim);
            background: var(--panel);
            transform: translateY(-1px);
          }
          .memory-card:focus-visible {
            outline: 2px solid var(--mint);
            outline-offset: 2px;
          }
          .memory-card.selected {
            border-color: var(--mint);
            background: rgba(124,240,184,.05);
            box-shadow: inset 2px 0 0 var(--mint);
          }

          .memory-card-header {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: var(--sp-2);
            margin-bottom: var(--sp-2);
          }
          .memory-card-meta {
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
          }
          .memory-card-kind {
            font-family: var(--mono);
            font-size: 8.5px;
            font-weight: 600;
            letter-spacing: .08em;
            text-transform: uppercase;
            color: var(--mint);
            border: 1px solid var(--mint-dim);
            background: rgba(124,240,184,.1);
            padding: 1px 6px;
            border-radius: 99px;
          }
          .memory-card-score {
            font-family: var(--mono);
            font-size: 10px;
            color: var(--mint);
            font-weight: 600;
          }
          .memory-card-time {
            font-family: var(--mono);
            font-size: 9.5px;
            color: var(--muted-2);
          }
          .memory-card-tags {
            display: flex;
            flex-wrap: wrap;
            gap: 4px;
            margin-top: 4px;
          }
          .memory-tag {
            font-family: var(--mono);
            font-size: 8px;
            letter-spacing: .05em;
            color: var(--muted);
            border: 1px solid var(--line);
            background: var(--bg);
            padding: 1px 6px;
            border-radius: 99px;
          }
          .memory-card-content {
            font-size: 12px;
            line-height: 1.55;
            color: var(--text);
            overflow-wrap: anywhere;
            display: -webkit-box;
            -webkit-line-clamp: 4;
            -webkit-box-orient: vertical;
            overflow: hidden;
          }
          .memory-card-footer {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-top: var(--sp-2);
            padding-top: var(--sp-2);
            border-top: 1px dashed var(--line-soft);
            font-size: 10px;
            color: var(--muted-2);
          }
          .memory-card-uri {
            font-family: var(--mono);
            font-size: 9px;
            color: var(--muted-2);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            max-width: 70%;
          }

          /* Conversation Turns */
          .conversation-turn {
            border: 1px solid var(--line);
            border-radius: var(--r-sm);
            background: var(--panel-2);
            padding: var(--sp-3);
            margin-bottom: var(--sp-2);
          }
          .conversation-turn:last-child { margin-bottom: 0; }
          .turn-header {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 6px;
            font-size: 11px;
          }
          .turn-role {
            font-family: var(--mono);
            font-size: 8.5px;
            font-weight: 700;
            letter-spacing: .08em;
            text-transform: uppercase;
            padding: 1px 6px;
            border-radius: 99px;
          }
          .turn-role.user { color: var(--cyan); background: rgba(107,201,232,.1); border: 1px solid #2a4c5a; }
          .turn-role.assistant { color: var(--mint); background: rgba(124,240,184,.1); border: 1px solid #2b5f4b; }
          .turn-role.system { color: var(--violet); background: rgba(182,164,255,.1); border: 1px solid #3b3a63; }
          .turn-time { margin-left: auto; font-family: var(--mono); font-size: 9px; color: var(--muted-2); }
          .turn-content {
            font-size: 12.5px;
            line-height: 1.55;
            color: var(--text);
            white-space: pre-wrap;
            overflow-wrap: anywhere;
          }

          /* Preview Modal */
          .memory-preview-overlay {
            position: fixed;
            inset: 0;
            z-index: 90;
            background: rgba(2,5,8,.7);
            backdrop-filter: blur(3px);
            display: flex;
            align-items: center;
            justify-content: center;
            padding: var(--sp-4);
            animation: fadeIn .2s var(--ease);
          }
          .memory-preview-overlay[hidden] { display: none; }
          @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }

          .memory-preview {
            width: 100%;
            max-width: 640px;
            max-height: 85vh;
            border: 1px solid var(--line);
            border-radius: var(--r-lg);
            background: linear-gradient(180deg, var(--panel), var(--panel-2));
            box-shadow: var(--shadow);
            display: flex;
            flex-direction: column;
            overflow: hidden;
            animation: slideUp .3s var(--ease);
          }
          @keyframes slideUp { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: none; } }

          .preview-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: var(--sp-3) var(--sp-4);
            border-bottom: 1px solid var(--line-soft);
          }
          .preview-header h3 { margin: 0; font-size: 14px; font-weight: 650; }
          .preview-header .btn.icon { width: 32px; height: 32px; }

          .preview-body {
            flex: 1;
            overflow: auto;
            padding: var(--sp-4);
          }
          .preview-content {
            font-family: var(--mono);
            font-size: 12px;
            line-height: 1.65;
            color: var(--text);
            white-space: pre-wrap;
            overflow-wrap: anywhere;
          }
          .preview-meta {
            display: flex;
            flex-wrap: wrap;
            gap: var(--sp-3);
            font-size: 10.5px;
            color: var(--muted);
          }
          .preview-meta-item {
            display: flex;
            align-items: center;
            gap: 6px;
          }
          .preview-meta-label { font-family: var(--mono); color: var(--muted-2); }
          .preview-meta-value { font-weight: 500; }

          .preview-footer {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: var(--sp-3);
            padding: var(--sp-3) var(--sp-4);
            border-top: 1px solid var(--line-soft);
            flex-wrap: wrap;
          }
          .preview-actions { display: flex; gap: 8px; }

          /* Loading State */
          .loading-skeleton {
            height: 80px;
            border-radius: var(--r-sm);
            background: linear-gradient(90deg, var(--panel-2), var(--line-soft), var(--panel-2));
            background-size: 200% 100%;
            animation: shimmer 1.5s infinite;
          }
          @keyframes shimmer { 100% { background-position: -200% 0; } }

          /* Reduced Motion */
          @media (prefers-reduced-motion: reduce) {
            .memory-preview-overlay, .memory-preview, .memory-card { animation: none; transition: none; }
            .loading-skeleton { animation: none; background: var(--line-soft); }
          }
        </style>
      `;

      // Cache elements
      searchInput = this.container.querySelector("#memorySearch");
      memoriesContainer = this.container.querySelector("#storedMemories");
      currentConversationEl = this.container.querySelector("#currentConversation");
      storedMemoriesEl = this.container.querySelector("#storedMemories");
      relevantContextEl = this.container.querySelector("#relevantContext");
    }

    bindEvents() {
      // Search input with debounce
      searchInput.addEventListener("input", (e) => this.onSearchInput(e.target.value));
      searchInput.addEventListener("keydown", (e) => {
        if (e.key === "Escape") { searchInput.blur(); searchInput.value = ""; this.onSearchInput(""); }
      });

      // Clear search
      this.container.querySelector("#memorySearchClear").addEventListener("click", () => {
        searchInput.value = "";
        this.onSearchInput("");
        searchInput.focus();
      });

      // Show/hide clear button
      searchInput.addEventListener("input", () => {
        this.container.querySelector("#memorySearchClear").hidden = !searchInput.value;
      });

      // Store conversation button
      this.container.querySelector("#storeConversationBtn").addEventListener("click", () => this.storeCurrentContext());

      // Preview modal events
      const overlay = this.container.querySelector("#memoryPreviewOverlay");
      overlay.addEventListener("click", (e) => { if (e.target === overlay) this.closePreview(); });
      this.container.querySelector("#previewClose").addEventListener("click", () => this.closePreview());
      this.container.querySelector("#previewCopy").addEventListener("click", () => this.copyMemory());
      this.container.querySelector("#previewDelete").addEventListener("click", () => this.deleteMemory());

      // Keyboard: / to focus search
      document.addEventListener("keydown", (e) => {
        if (e.key === "/" && e.target !== searchInput && !e.target.matches("input, textarea")) {
          e.preventDefault();
          searchInput.focus();
        }
        if (e.key === "Escape") this.closePreview();
      });

      // Listen for new conversation turns from the main dashboard
      window.addEventListener("friday:conversation", (e) => this.onConversationUpdate(e.detail));
      window.addEventListener("friday:goal", (e) => this.onGoalSubmitted(e.detail));
    }

    async loadInitialData() {
      await Promise.all([
        this.loadMemories(""),
        this.loadRelevantContext()
      ]);
    }

    // ────────────────────────────────────────────────────────────────────
    // Search
    // ────────────────────────────────────────────────────────────────────

    onSearchInput(query) {
      currentQuery = query.trim();
      clearTimeout(searchDebounceTimer);
      searchDebounceTimer = setTimeout(() => this.loadMemories(currentQuery), DEBOUNCE_MS);
    }

    async loadMemories(query) {
      if (isLoading) return;
      isLoading = true;
      this.showLoading(storedMemoriesEl);

      try {
        const params = new URLSearchParams();
        if (query) params.set("q", query);
        params.set("limit", String(MAX_MEMORIES_DISPLAY));
        params.set("level", "L0");  // Abstracts first for list view

        const data = await apiRequest("/search?" + params.toString());
        this.renderMemories(data.hits || [], storedMemoriesEl, "stored");
        this.updateCount(data.hits?.length || 0);
      } catch (err) {
        console.error("Failed to load memories:", err);
        this.showError(storedMemoriesEl, "Failed to load memories");
        showToast("Failed to load memories", "error");
      } finally {
        isLoading = false;
      }
    }

    // ────────────────────────────────────────────────────────────────────
    // Current Conversation
    // ────────────────────────────────────────────────────────────────────

    onConversationUpdate(detail) {
      if (!detail || !detail.turns) return;
      conversationTurns = detail.turns;
      this.renderConversation();
    }

    renderConversation() {
      if (!conversationTurns.length) {
        currentConversationEl.innerHTML = '<div class="empty-state">No active conversation yet. Send a command to start.</div>';
        return;
      }

      currentConversationEl.innerHTML = conversationTurns.map((turn, i) => `
        <div class="conversation-turn" data-index="${i}">
          <div class="turn-header">
            <span class="turn-role ${escapeHtml(turn.role || "user")}">${escapeHtml((turn.role || "user").toUpperCase())}</span>
            <span class="turn-time">${formatTimestamp(turn.timestamp)}</span>
          </div>
          <div class="turn-content">${escapeHtml(turn.content || "")}</div>
        </div>
      `).join("");
    }

    async storeCurrentContext() {
      if (!conversationTurns.length) {
        showToast("No conversation to store", "warn");
        return;
      }

      const btn = this.container.querySelector("#storeConversationBtn");
      const originalText = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = `<svg class="spinner" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px;animation:spin 1s linear infinite"><circle cx="12" cy="12" r="10" stroke-opacity="0.25"/><path d="M12 2a10 10 0 0 1 10 10" stroke-opacity="1" stroke-linecap="round"/></svg> Storing…`;

      try {
        const sessionId = "friday-" + Date.now();
        const turns = conversationTurns.map(t => ({ role: t.role, content: t.content }));
        await apiRequest("/sessions/commit", {
          method: "POST",
          body: JSON.stringify({ session_id: sessionId, turns })
        });
        showToast("Conversation stored in memory", "success");
        // Refresh memories list
        this.loadMemories(currentQuery);
      } catch (err) {
        console.error("Failed to store conversation:", err);
        showToast("Failed to store conversation: " + err.message, "error");
      } finally {
        btn.disabled = false;
        btn.innerHTML = originalText;
      }
    }

    // ────────────────────────────────────────────────────────────────────
    // Relevant Context (auto-loaded on goal)
    // ────────────────────────────────────────────────────────────────────

    onGoalSubmitted(detail) {
      if (!detail || !detail.goal) return;
      this.loadRelevantContext(detail.goal);
    }

    async loadRelevantContext(query = "") {
      try {
        const params = new URLSearchParams();
        if (query) params.set("q", query);
        params.set("limit", "10");
        params.set("level", "L1");  // Subtree overviews for context

        const data = await apiRequest("/search?" + params.toString());
        this.renderMemories(data.hits || [], relevantContextEl, "relevant");
      } catch (err) {
        console.error("Failed to load relevant context:", err);
        this.showError(relevantContextEl, "Failed to load relevant context");
      }
    }

    // ────────────────────────────────────────────────────────────────────
    // Memory Cards Rendering
    // ────────────────────────────────────────────────────────────────────

    renderMemories(hits, container, type) {
      if (!hits.length) {
        container.innerHTML = `<div class="empty-state">${type === "stored" ? "No memories stored yet." : "No relevant memories found."}</div>`;
        return;
      }

      container.innerHTML = hits.map((hit, i) => this.createMemoryCard(hit, type, i)).join("");

      // Bind click events
      container.querySelectorAll(".memory-card").forEach((card, i) => {
        card.addEventListener("click", () => this.openPreview(hits[i], card));
        card.addEventListener("keydown", (e) => {
          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); this.openPreview(hits[i], card); }
        });
        card.setAttribute("tabindex", "0");
        card.setAttribute("role", "button");
        card.setAttribute("aria-label", `View memory: ${escapeHtml(hits[i].abstract || hits[i].uri)}`);
      });
    }

    createMemoryCard(hit, type, index) {
      const score = hit.score != null ? (hit.score * 100).toFixed(0) + "%" : "—";
      const kind = hit.kind || "memory";
      const time = formatTimestamp(hit.timestamp || hit.created_at);
      const tags = hit.tags ? hit.tags.slice(0, 4).map(t => `<span class="memory-tag">${escapeHtml(t)}</span>`).join("") : "";
      const uri = hit.uri || "";
      const content = escapeHtml(truncate(hit.abstract || hit.content || "", PREVIEW_MAX_CHARS));

      return `
        <article class="memory-card" data-index="${index}" data-uri="${escapeHtml(uri)}">
          <div class="memory-card-header">
            <div class="memory-card-meta">
              <span class="memory-card-kind">${escapeHtml(kind)}</span>
              ${type !== "relevant" ? `<span class="memory-card-time">${escapeHtml(time)}</span>` : ""}
            </div>
            ${type === "relevant" && hit.score != null ? `<span class="memory-card-score">${escapeHtml(score)} relevance</span>` : ""}
          </div>
          <div class="memory-card-content">${content}</div>
          ${tags ? `<div class="memory-card-tags">${tags}</div>` : ""}
          <div class="memory-card-footer">
            <span class="memory-card-uri" title="${escapeHtml(uri)}">${escapeHtml(uri)}</span>
            <span class="hint"><kbd>Enter</kbd> to preview</span>
          </div>
        </article>
      `;
    }

    updateCount(count) {
      const el = this.container.querySelector("#storedCount");
      if (el) el.textContent = count;
    }

    // ────────────────────────────────────────────────────────────────────
    // Preview Modal
    // ────────────────────────────────────────────────────────────────────

    async openPreview(hit, cardEl) {
      selectedMemory = hit;
      // Update selected state
      cardEl.closest(".section-body").querySelectorAll(".memory-card").forEach(c => c.classList.remove("selected"));
      cardEl.classList.add("selected");

      const overlay = this.container.querySelector("#memoryPreviewOverlay");
      const titleEl = this.container.querySelector("#previewTitle");
      const bodyEl = this.container.querySelector("#previewBody");
      const metaEl = this.container.querySelector("#previewMeta");

      titleEl.textContent = hit.title || hit.uri || "Memory";
      overlay.hidden = false;
      bodyEl.innerHTML = '<div class="loading-skeleton"></div>';
      metaEl.innerHTML = "";

      try {
        // Fetch full content (L2)
        const uri = hit.uri;
        if (!uri) throw new Error("No URI");
        const data = await apiRequest("/read?uri=" + encodeURIComponent(uri) + "&level=L2");

        const content = data.content || data.abstract || "(empty)";
        bodyEl.innerHTML = `<pre class="preview-content">${escapeHtml(content)}</pre>`;

        metaEl.innerHTML = `
          <span class="preview-meta-item"><span class="preview-meta-label">Kind:</span><span class="preview-meta-value">${escapeHtml(hit.kind || "—")}</span></span>
          <span class="preview-meta-item"><span class="preview-meta-label">Score:</span><span class="preview-meta-value">${hit.score != null ? (hit.score * 100).toFixed(1) + "%" : "—"}</span></span>
          <span class="preview-meta-item"><span class="preview-meta-label">Created:</span><span class="preview-meta-value">${formatTimestamp(hit.timestamp || hit.created_at)}</span></span>
          <span class="preview-meta-item"><span class="preview-meta-label">URI:</span><span class="preview-meta-value" style="font-family:var(--mono);font-size:9px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:inline-block;vertical-align:middle">${escapeHtml(uri)}</span></span>
          ${hit.tags?.length ? `<span class="preview-meta-item"><span class="preview-meta-label">Tags:</span><span class="preview-meta-value">${hit.tags.map(t => `<span class="memory-tag" style="margin-left:4px">${escapeHtml(t)}</span>`).join("")}</span></span>` : ""}
        `;
      } catch (err) {
        console.error("Failed to load memory preview:", err);
        bodyEl.innerHTML = `<div class="empty-state" style="padding:var(--sp-3);color:var(--danger)">Failed to load: ${escapeHtml(err.message)}</div>`;
      }
    }

    closePreview() {
      const overlay = this.container.querySelector("#memoryPreviewOverlay");
      overlay.hidden = true;
      selectedMemory = null;
      // Clear selection
      this.container.querySelectorAll(".memory-card.selected").forEach(c => c.classList.remove("selected"));
    }

    async copyMemory() {
      if (!selectedMemory) return;
      try {
        const uri = selectedMemory.uri;
        const data = await apiRequest("/read?uri=" + encodeURIComponent(uri) + "&level=L2");
        const content = data.content || data.abstract || "";
        await navigator.clipboard.writeText(content);
        showToast("Copied to clipboard", "success");
      } catch (err) {
        showToast("Failed to copy: " + err.message, "error");
      }
    }

    async deleteMemory() {
      if (!selectedMemory) return;
      if (!confirm("Delete this memory? This cannot be undone.")) return;

      try {
        const uri = selectedMemory.uri;
        // Try DELETE first, fall back to POST with _method override if needed
        let res;
        try {
          res = await apiRequest("/write?uri=" + encodeURIComponent(uri), { method: "DELETE" });
        } catch (e) {
          // Some proxies don't support DELETE, try POST with _method
          res = await apiRequest("/write", {
            method: "POST",
            body: JSON.stringify({ uri, _method: "DELETE" })
          });
        }
        showToast("Memory deleted", "success");
        this.closePreview();
        this.loadMemories(currentQuery);
        this.loadRelevantContext();
      } catch (err) {
        console.error("Failed to delete memory:", err);
        showToast("Delete not supported or failed: " + err.message, "error");
      }
    }

    // ────────────────────────────────────────────────────────────────────
    // Loading/Error States
    // ────────────────────────────────────────────────────────────────────

    showLoading(container) {
      container.innerHTML = `
        <div class="loading-skeleton" style="margin-bottom:8px"></div>
        <div class="loading-skeleton" style="margin-bottom:8px;height:60px"></div>
        <div class="loading-skeleton" style="height:60px"></div>
      `;
    }

    showError(container, message) {
      container.innerHTML = `<div class="empty-state" style="color:var(--danger)">${escapeHtml(message)}</div>`;
    }

    // ────────────────────────────────────────────────────────────────────
    // Public API
    // ────────────────────────────────────────────────────────────────────

    /** Initialize the panel in a container element */
    static init(container) {
      if (memoryPanel) memoryPanel.destroy();
      memoryPanel = new MemoryPanel(container);
      MemoryPanel._instance = memoryPanel;
      return memoryPanel;
    }

    /** Load memories with optional query */
    loadMemories(query) {
      return this.loadMemories(query);
    }

    /** Store current conversation context */
    storeCurrentContext() {
      return this.storeCurrentContext();
    }

    /** Display a specific memory in the preview */
    displayMemory(memory) {
      // Find the card and trigger preview
      const cards = this.container.querySelectorAll(".memory-card");
      cards.forEach((card, i) => {
        if (card.dataset.uri === memory.uri) {
          this.openPreview(memory, card);
        }
      });
    }

    /** Clean up */
    destroy() {
      clearTimeout(searchDebounceTimer);
      this.container.innerHTML = "";
      memoryPanel = null;
    }
  }

  // ────────────────────────────────────────────────────────────────────────
  // Export
  // ────────────────────────────────────────────────────────────────────────

  window.MemoryPanel = MemoryPanel;

  // Auto-init if container exists
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      const container = document.getElementById("memoryPanel");
      if (container) MemoryPanel.init(container);
    });
  } else {
    const container = document.getElementById("memoryPanel");
    if (container) MemoryPanel.init(container);
  }

})();