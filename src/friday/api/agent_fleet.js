/**
 * FRIDAY Agent Fleet Sidebar
 * Left slide-in panel showing all 10 agents with real-time status, WebSocket updates, and expandable detail views
 * 
 * Usage:
 *   import { AgentFleet } from './agent_fleet.js';
 *   const fleet = new AgentFleet();
 *   await fleet.init(document.getElementById('fleet-container'));
 *   fleet.updateAgent('stratex', { status: 'busy', task: 'Running backtest', progress: 0.65 });
 * 
 * Dependencies: GSAP (for animations), WebSocket for real-time updates
 */

class AgentFleet {
  constructor(options = {}) {
    this.options = Object.assign({
      // Container configuration
      basePath: '', // e.g., '/friday' for proxied deployments
      wsEndpoint: '/ws/agents', // WebSocket endpoint for real-time updates
      
      // Agent definitions (10 agents in the FRIDAY Universe)
      agents: [
        { id: 'friday', name: 'FRIDAY', role: 'Orchestrator', icon: '⬟', accent: '#b4f46b', port: 10000 },
        { id: 'inference', name: 'Inference', role: 'LLM Gateway', icon: '◈', accent: '#6bc9e8', port: 8001 },
        { id: 'memora', name: 'Memora', role: 'Memory', icon: '◆', accent: '#b7a7ff', port: 8002 },
        { id: 'stratex', name: 'Stratex', role: 'Trading', icon: '▲', accent: '#b4f46b', port: 8003 },
        { id: 'futuris', name: 'Futuris', role: 'Forecasting', icon: '◆', accent: '#f2c679', port: 8004 },
        { id: 'intelx', name: 'IntelX', role: 'Security', icon: '⬢', accent: '#ff7c86', port: 8005 },
        { id: 'forge', name: 'Forge', role: 'Coding', icon: '⬡', accent: '#7ee0b5', port: 8006 },
        { id: 'sentinel', name: 'Sentinel', role: 'SecOps', icon: '⬠', accent: '#ff7c86', port: 8008 },
        { id: 'cortex', name: 'Cortex', role: 'CRM/Ops', icon: '◉', accent: '#b7a7ff', port: 8009 },
        { id: 'vyralx', name: 'VyralX', role: 'Video', icon: '▼', accent: '#f2c679', port: 8010 }
      ],
      
      // Animation
      staggerDelay: 0.06,
      panelWidth: 320,
      transitionDuration: 0.5,
      ease: 'cubic-bezier(.16,1,.3,1)',
      
      // WebSocket
      autoConnect: true,
      reconnectInterval: 5000,
      maxReconnectAttempts: 10,
      
      // Callbacks
      onAgentClick: null, // (agentId, agentData) => void
      onAgentFocus: null, // (agentId) => void - for workflow canvas focus
      onStatusChange: null, // (agentId, status) => void
      onError: (msg) => console.warn('[AgentFleet]', msg)
    }, options);
    
    // DOM references
    this.container = null;
    this.panel = null;
    this.agentCards = new Map();
    this.expandedAgent = null;
    this.isExpanded = false;
    this.isPanelOpen = true;
    
    // WebSocket
    this.ws = null;
    this.reconnectAttempts = 0;
    this.reconnectTimer = null;
    
    // Agent state
    this.agentStates = new Map();
    this.agents.forEach(agent => {
      this.agentStates.set(agent.id, {
        status: 'offline', // online, offline, busy, error
        task: 'Idle',
        progress: 0,
        lastUpdate: Date.now(),
        logs: [],
        timeline: [],
        output: null
      });
    });
    
    // Animation
    this.gsap = null;
    this.animationTimeline = null;
    
    // Bind methods
    this._handleResize = this._handleResize.bind(this);
    this._handleKeydown = this._handleKeydown.bind(this);
    this._onWSOpen = this._onWSOpen.bind(this);
    this._onWSMessage = this._onWSMessage.bind(this);
    this._onWSClose = this._onWSClose.bind(this);
    this._onWSError = this._onWSError.bind(this);
    
    // Reduced motion
    this.prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    this._reducedMotionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    this._onReducedMotionChange = (e) => {
      this.prefersReducedMotion = e.matches;
    };
    this._reducedMotionQuery.addEventListener('change', this._onReducedMotionChange);
  }
  
  // ==================== Public API ====================
  
  /**
   * Initialize the agent fleet sidebar
   * @param {HTMLElement|string} container - Container element or selector
   * @returns {Promise<void>}
   */
  async init(container) {
    if (typeof container === 'string') {
      container = document.querySelector(container);
    }
    if (!container) {
      throw new Error('Container element is required');
    }
    
    this.container = container;
    
    try {
      // Load CSS if not already loaded
      this._loadCSS();
      
      // Load GSAP if not available
      await this._loadGSAP();
      
      // Build DOM structure
      this._buildDOM();
      
      // Cache elements
      this._cacheElements();
      
      // Bind events
      this._bindEvents();
      
      // Initial render
      this._renderAgents();
      
      // Animate entrance
      this._animateEntrance();
      
      // Connect WebSocket
      if (this.options.autoConnect) {
        this._connectWS();
      }
      
      console.log('[AgentFleet] Initialized with', this.agents.length, 'agents');
    } catch (error) {
      this.options.onError('Initialization failed: ' + error.message);
      throw error;
    }
  }
  
  /**
   * Update agent status and data
   * @param {string} agentId - Agent identifier
   * @param {Object} data - Status data { status, task, progress, logs, output, timeline }
   */
  updateAgent(agentId, data) {
    const state = this.agentStates.get(agentId);
    if (!state) return;
    
    const prevStatus = state.status;
    const prevProgress = state.progress;
    
    // Update state
    if (data.status !== undefined) state.status = data.status;
    if (data.task !== undefined) state.task = data.task;
    if (data.progress !== undefined) state.progress = Math.max(0, Math.min(1, data.progress));
    if (data.logs !== undefined) state.logs = data.logs;
    if (data.output !== undefined) state.output = data.output;
    if (data.timeline !== undefined) state.timeline = data.timeline;
    state.lastUpdate = Date.now();
    
    // Update DOM
    this._updateAgentCard(agentId);
    
    // If expanded, update detail view
    if (this.expandedAgent === agentId) {
      this._updateExpandedView(agentId);
    }
    
    // Callback
    if (data.status !== undefined && data.status !== prevStatus && this.options.onStatusChange) {
      this.options.onStatusChange(agentId, data.status);
    }
    
    // Animate progress ring if changed
    if (data.progress !== undefined && data.progress !== prevProgress) {
      this._animateProgressRing(agentId, prevProgress, data.progress);
    }
  }
  
  /**
   * Expand agent to full detail view
   * @param {string} agentId - Agent identifier
   */
  expandAgent(agentId) {
    if (this.expandedAgent === agentId) return;
    
    // Collapse current if any
    if (this.expandedAgent) {
      this._collapseAgent(this.expandedAgent);
    }
    
    this.expandedAgent = agentId;
    const card = this.agentCards.get(agentId);
    if (!card) return;
    
    // Create expanded view
    this._createExpandedView(agentId, card);
    
    // Animate expansion
    this._animateExpand(agentId, card);
    
    // Callback
    if (this.options.onAgentFocus) {
      const agent = this.agents.find(a => a.id === agentId);
      this.options.onAgentFocus(agentId, agent);
    }
  }
  
  /**
   * Collapse expanded agent view
   */
  collapse() {
    if (this.expandedAgent) {
      this._collapseAgent(this.expandedAgent);
      this.expandedAgent = null;
    }
  }
  
  /**
   * Toggle panel open/closed
   * @param {boolean} [force] - Force open (true) or closed (false)
   */
  togglePanel(force) {
    const shouldOpen = force !== undefined ? force : !this.isPanelOpen;
    this.isPanelOpen = shouldOpen;
    
    this._animatePanelToggle(shouldOpen);
  }
  
  /**
   * Get current agent states
   * @returns {Map<string, Object>}
   */
  getAgentStates() {
    return new Map(this.agentStates);
  }
  
  /**
   * Get agent configuration
   * @param {string} agentId 
   * @returns {Object|null}
   */
  getAgent(agentId) {
    return this.agents.find(a => a.id === agentId) || null;
  }
  
  /**
   * Manually trigger WebSocket reconnection
   */
  reconnect() {
    this._connectWS();
  }
  
  /**
   * Destroy the component and clean up
   */
  destroy() {
    // Disconnect WebSocket
    this._disconnectWS();
    
    // Kill animations
    if (this.animationTimeline) {
      this.animationTimeline.kill();
      this.animationTimeline = null;
    }
    if (this.gsap) {
      this.gsap.killTweensOf('*');
    }
    
    // Remove event listeners
    this._unbindEvents();
    window.removeEventListener('resize', this._handleResize);
    document.removeEventListener('keydown', this._handleKeydown);
    this._reducedMotionQuery.removeEventListener('change', this._onReducedMotionChange);
    
    // Remove DOM
    if (this.panel && this.panel.parentNode) {
      this.panel.parentNode.removeChild(this.panel);
    }
    
    // Clear references
    this.container = null;
    this.panel = null;
    this.agentCards.clear();
    this.agentStates.clear();
    this.expandedAgent = null;
    
    console.log('[AgentFleet] Destroyed');
  }
  
  // ==================== Private Methods ====================
  
  /**
   * Load GSAP from CDN if not available
   * @private
   */
  async _loadGSAP() {
    if (window.gsap) {
      this.gsap = window.gsap;
      return;
    }
    
    return new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = 'https://cdn.jsdelivr.net/npm/gsap@3.12.5/dist/gsap.min.js';
      script.onload = () => {
        this.gsap = window.gsap;
        resolve();
      };
      script.onerror = () => reject(new Error('Failed to load GSAP'));
      document.head.appendChild(script);
    });
  }
  
  /**
   * Load CSS stylesheet
   * @private
   */
  _loadCSS() {
    const cssPath = `${this.options.basePath || ''}/src/friday/api/agent_fleet.css`;
    if (document.querySelector(`link[href="${cssPath}"]`)) return;
    
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = cssPath;
    document.head.appendChild(link);
  }
  
  /**
   * Build the DOM structure
   * @private
   */
  _buildDOM() {
    const panelHTML = `
      <aside class="fleet-panel" role="complementary" aria-label="Agent Fleet">
        <div class="fleet-header">
          <div class="fleet-brand">
            <span class="fleet-brand-icon" aria-hidden="true">⬟</span>
            <span class="fleet-brand-text">AGENT FLEET</span>
          </div>
          <button class="fleet-toggle" aria-label="Collapse fleet panel" aria-expanded="true">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="15 18 9 12 15 6"></polyline>
            </svg>
          </button>
        </div>
        <div class="fleet-search" hidden>
          <label for="fleet-search-input" class="visually-hidden">Filter agents</label>
          <svg class="fleet-search-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <circle cx="11" cy="11" r="8"></circle>
            <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
          </svg>
          <input type="search" id="fleet-search-input" placeholder="Filter agents..." autocomplete="off" spellcheck="false">
        </div>
        <div class="fleet-list" role="list" aria-label="Agents">
          <!-- Agent cards injected here -->
        </div>
        <div class="fleet-footer">
          <div class="fleet-legend">
            <span class="fleet-legend-item"><span class="fleet-legend-dot" data-status="online"></span>Online</span>
            <span class="fleet-legend-item"><span class="fleet-legend-dot" data-status="busy"></span>Busy</span>
            <span class="fleet-legend-item"><span class="fleet-legend-dot" data-status="offline"></span>Offline</span>
            <span class="fleet-legend-item"><span class="fleet-legend-dot" data-status="error"></span>Error</span>
          </div>
          <div class="fleet-summary">
            <span id="fleet-online-count" class="fleet-count online">0</span>
            <span class="fleet-count-sep">/</span>
            <span id="fleet-total-count" class="fleet-count total">${this.agents.length}</span>
          </div>
        </div>
      </aside>
      <div class="fleet-expanded-overlay" hidden></div>
      <div class="fleet-expanded-panel" hidden role="dialog" aria-label="Agent details" aria-modal="true">
        <div class="fleet-expanded-header">
          <div class="fleet-expanded-agent-info">
            <span class="fleet-expanded-icon" aria-hidden="true"></span>
            <div>
              <strong class="fleet-expanded-name"></strong>
              <span class="fleet-expanded-role"></span>
            </div>
          </div>
          <button class="fleet-expanded-close" aria-label="Close details">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>
        <div class="fleet-expanded-content">
          <div class="fleet-expanded-tabs" role="tablist">
            <button role="tab" data-tab="overview" aria-selected="true">Overview</button>
            <button role="tab" data-tab="logs" aria-selected="false">Logs</button>
            <button role="tab" data-tab="timeline" aria-selected="false">Timeline</button>
            <button role="tab" data-tab="output" aria-selected="false">Output</button>
          </div>
          <div class="fleet-expanded-panels">
            <div role="tabpanel" data-tab="overview" class="fleet-tab-panel active">
              <div class="fleet-overview-grid">
                <div class="fleet-overview-item">
                  <span class="fleet-overview-label">Status</span>
                  <span class="fleet-overview-value fleet-status-badge"></span>
                </div>
                <div class="fleet-overview-item">
                  <span class="fleet-overview-label">Current Task</span>
                  <span class="fleet-overview-value fleet-current-task"></span>
                </div>
                <div class="fleet-overview-item">
                  <span class="fleet-overview-label">Progress</span>
                  <div class="fleet-progress-container">
                    <div class="fleet-progress-bar" style="width: 0%"></div>
                  </div>
                  <span class="fleet-progress-text">0%</span>
                </div>
                <div class="fleet-overview-item">
                  <span class="fleet-overview-label">Last Update</span>
                  <span class="fleet-overview-value fleet-last-update"></span>
                </div>
                <div class="fleet-overview-item fleet-overview-full">
                  <span class="fleet-overview-label">Port</span>
                  <span class="fleet-overview-value fleet-port"></span>
                </div>
                <div class="fleet-overview-item fleet-overview-full">
                  <span class="fleet-overview-label">Endpoint</span>
                  <span class="fleet-overview-value fleet-endpoint"></span>
                </div>
              </div>
            </div>
            <div role="tabpanel" data-tab="logs" class="fleet-tab-panel" hidden>
              <div class="fleet-logs-container">
                <div class="fleet-logs-header">
                  <span class="fleet-logs-title">Recent Logs</span>
                  <button class="fleet-logs-clear" type="button">Clear</button>
                </div>
                <div class="fleet-logs-list" role="log" aria-live="polite"></div>
              </div>
            </div>
            <div role="tabpanel" data-tab="timeline" class="fleet-tab-panel" hidden>
              <div class="fleet-timeline-container">
                <div class="fleet-timeline-list"></div>
              </div>
            </div>
            <div role="tabpanel" data-tab="output" class="fleet-tab-panel" hidden>
              <div class="fleet-output-container">
                <pre class="fleet-output-content"></pre>
              </div>
            </div>
          </div>
        </div>
      </div>
    `;
    
    this.container.insertAdjacentHTML('beforeend', panelHTML);
  }
  
  /**
   * Cache DOM elements
   * @private
   */
  _cacheElements() {
    this.panel = this.container.querySelector('.fleet-panel');
    this.fleetList = this.container.querySelector('.fleet-list');
    this.fleetToggle = this.container.querySelector('.fleet-toggle');
    this.fleetSearch = this.container.querySelector('.fleet-search');
    this.fleetSearchInput = this.container.querySelector('#fleet-search-input');
    this.expandedOverlay = this.container.querySelector('.fleet-expanded-overlay');
    this.expandedPanel = this.container.querySelector('.fleet-expanded-panel');
    this.expandedClose = this.container.querySelector('.fleet-expanded-close');
    this.expandedTabs = this.container.querySelector('.fleet-expanded-tabs');
    this.onlineCountEl = this.container.querySelector('#fleet-online-count');
    this.totalCountEl = this.container.querySelector('#fleet-total-count');
  }
  
  /**
   * Bind event listeners
   * @private
   */
  _bindEvents() {
    // Panel toggle
    this.fleetToggle.addEventListener('click', () => this.togglePanel());
    
    // Search
    this.fleetSearchInput.addEventListener('input', (e) => this._filterAgents(e.target.value));
    
    // Expanded panel
    this.expandedClose.addEventListener('click', () => this.collapse());
    this.expandedOverlay.addEventListener('click', () => this.collapse());
    
    // Tab switching
    this.expandedTabs.addEventListener('click', (e) => {
      const tabBtn = e.target.closest('[data-tab]');
      if (tabBtn) this._switchTab(tabBtn.dataset.tab);
    });
    
    // Keyboard
    document.addEventListener('keydown', this._handleKeydown);
    
    // Resize
    window.addEventListener('resize', this._handleResize);
    
    // Logs clear
    this.container.querySelector('.fleet-logs-clear').addEventListener('click', () => {
      if (this.expandedAgent) {
        const state = this.agentStates.get(this.expandedAgent);
        state.logs = [];
        this._updateExpandedView(this.expandedAgent);
      }
    });
  }
  
  /**
   * Unbind event listeners
   * @private
   */
  _unbindEvents() {
    if (this.fleetToggle) this.fleetToggle.removeEventListener('click', () => this.togglePanel());
    if (this.fleetSearchInput) this.fleetSearchInput.removeEventListener('input', this._filterAgents);
    if (this.expandedClose) this.expandedClose.removeEventListener('click', () => this.collapse());
    if (this.expandedOverlay) this.expandedOverlay.removeEventListener('click', () => this.collapse());
    if (this.expandedTabs) this.expandedTabs.removeEventListener('click', this._switchTab);
    document.removeEventListener('keydown', this._handleKeydown);
    window.removeEventListener('resize', this._handleResize);
  }
  
  /**
   * Render all agent cards
   * @private
   */
  _renderAgents() {
    this.fleetList.innerHTML = '';
    this.agentCards.clear();
    
    this.agents.forEach((agent, index) => {
      const card = this._createAgentCard(agent, index);
      this.fleetList.appendChild(card);
      this.agentCards.set(agent.id, card);
    });
    
    this._updateSummary();
  }
  
  /**
   * Create a single agent card
   * @private
   */
  _createAgentCard(agent, index) {
    const state = this.agentStates.get(agent.id);
    const card = document.createElement('button');
    card.className = 'fleet-agent-card';
    card.dataset.agentId = agent.id;
    card.style.setProperty('--agent-accent', agent.accent);
    card.style.setProperty('--stagger-delay', `${index * this.options.staggerDelay}s`);
    card.setAttribute('role', 'listitem');
    card.setAttribute('tabindex', '0');
    card.setAttribute('aria-expanded', 'false');
    
    const statusClass = `fleet-status-${state.status}`;
    const progressPercent = Math.round(state.progress * 100);
    
    card.innerHTML = `
      <div class="fleet-agent-icon" style="background: linear-gradient(135deg, ${agent.accent}22, ${agent.accent}08); border-color: ${agent.accent}44;">
        <span aria-hidden="true" style="color: ${agent.accent};">${agent.icon}</span>
      </div>
      <div class="fleet-agent-info">
        <div class="fleet-agent-header">
          <strong class="fleet-agent-name">${agent.name}</strong>
          <span class="fleet-agent-status ${statusClass}" aria-label="Status: ${state.status}">
            <span class="fleet-status-dot" aria-hidden="true"></span>
            <span class="fleet-status-text">${state.status}</span>
          </span>
        </div>
        <span class="fleet-agent-role">${agent.role}</span>
        <div class="fleet-agent-task" title="${state.task}">${state.task}</div>
      </div>
      <div class="fleet-agent-progress" aria-label="Progress: ${progressPercent}%">
        <svg class="fleet-progress-ring" viewBox="0 0 48 48" aria-hidden="true">
          <circle class="fleet-progress-bg" cx="24" cy="24" r="20" fill="none" stroke="currentColor" stroke-width="3" stroke-opacity="0.15"/>
          <circle class="fleet-progress-fg" cx="24" cy="24" r="20" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"
            stroke-dasharray="125.66" stroke-dashoffset="${125.66 * (1 - state.progress)}"
            style="color: ${agent.accent}; transition: stroke-dashoffset 0.4s cubic-bezier(.16,1,.3,1);"/>
        </svg>
        <span class="fleet-progress-value">${progressPercent}%</span>
      </div>
      <button class="fleet-agent-expand" aria-label="Expand ${agent.name}" tabindex="-1">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <polyline points="9 18 15 12 9 6"></polyline>
        </svg>
      </div>
    `;
    
    // Click handlers
    card.addEventListener('click', (e) => {
      if (!e.target.closest('.fleet-agent-expand')) {
        this.expandAgent(agent.id);
        if (this.options.onAgentClick) {
          this.options.onAgentClick(agent.id, agent);
        }
      }
    });
    
    card.querySelector('.fleet-agent-expand').addEventListener('click', (e) => {
      e.stopPropagation();
      this.expandAgent(agent.id);
    });
    
    // Keyboard support
    card.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        this.expandAgent(agent.id);
      }
    });
    
    // Hover effect
    card.addEventListener('mouseenter', () => {
      if (!this.prefersReducedMotion && this.gsap) {
        this.gsap.to(card, { x: 4, duration: 0.15, ease: 'power2.out' });
      }
    });
    card.addEventListener('mouseleave', () => {
      if (!this.prefersReducedMotion && this.gsap) {
        this.gsap.to(card, { x: 0, duration: 0.2, ease: 'power2.out' });
      }
    });
    
    return card;
  }
  
  /**
   * Update a single agent card
   * @private
   */
  _updateAgentCard(agentId) {
    const card = this.agentCards.get(agentId);
    const state = this.agentStates.get(agentId);
    const agent = this.agents.find(a => a.id === agentId);
    if (!card || !state || !agent) return;
    
    // Update status badge
    const statusEl = card.querySelector('.fleet-agent-status');
    statusEl.className = `fleet-agent-status fleet-status-${state.status}`;
    statusEl.querySelector('.fleet-status-text').textContent = state.status;
    statusEl.setAttribute('aria-label', `Status: ${state.status}`);
    
    // Update task
    card.querySelector('.fleet-agent-task').textContent = state.task;
    card.querySelector('.fleet-agent-task').title = state.task;
    
    // Update progress ring
    const progressPercent = Math.round(state.progress * 100);
    const fgCircle = card.querySelector('.fleet-progress-fg');
    fgCircle.style.strokeDashoffset = 125.66 * (1 - state.progress);
    card.querySelector('.fleet-progress-value').textContent = `${progressPercent}%`;
    card.querySelector('.fleet-agent-progress').setAttribute('aria-label', `Progress: ${progressPercent}%`);
    
    // Update accent color on progress ring
    fgCircle.style.color = agent.accent;
    
    this._updateSummary();
  }
  
  /**
   * Update fleet summary counts
   * @private
   */
  _updateSummary() {
    let online = 0;
    this.agentStates.forEach(state => {
      if (state.status === 'online' || state.status === 'busy') online++;
    });
    
    if (this.onlineCountEl) this.onlineCountEl.textContent = online;
    if (this.totalCountEl) this.totalCountEl.textContent = this.agents.length;
  }
  
  /**
   * Animate progress ring change
   * @private
   */
  _animateProgressRing(agentId, fromProgress, toProgress) {
    if (this.prefersReducedMotion || !this.gsap) return;
    
    const card = this.agentCards.get(agentId);
    if (!card) return;
    
    const fgCircle = card.querySelector('.fleet-progress-fg');
    const progressValue = card.querySelector('.fleet-progress-value');
    
    // Animate stroke dashoffset
    this.gsap.to(fgCircle, {
      strokeDashoffset: 125.66 * (1 - toProgress),
      duration: 0.6,
      ease: 'cubic-bezier(.16,1,.3,1)'
    });
    
    // Animate percentage text
    const obj = { val: Math.round(fromProgress * 100) };
    this.gsap.to(obj, {
      val: Math.round(toProgress * 100),
      duration: 0.6,
      ease: 'cubic-bezier(.16,1,.3,1)',
      onUpdate: () => {
        progressValue.textContent = `${Math.round(obj.val)}%`;
      }
    });
  }
  
  /**
   * Animate entrance of all agent cards
   * @private
   */
  _animateEntrance() {
    if (this.prefersReducedMotion || !this.gsap) {
      this.panel.style.opacity = '1';
      this.panel.style.transform = 'translateX(0)';
      return;
    }
    
    this.animationTimeline = this.gsap.timeline();
    
    // Panel slide in
    this.gsap.from(this.panel, {
      x: -this.options.panelWidth,
      opacity: 0,
      duration: this.options.transitionDuration,
      ease: this.options.ease
    });
    
    // Staggered card entrance
    const cards = Array.from(this.agentCards.values());
    this.gsap.from(cards, {
      x: -30,
      opacity: 0,
      duration: 0.4,
      ease: 'power3.out',
      stagger: this.options.staggerDelay
    }, '-=0.3');
  }
  
  /**
   * Animate panel toggle (collapse/expand)
   * @private
   */
  _animatePanelToggle(open) {
    if (this.prefersReducedMotion || !this.gsap) {
      this.panel.style.transform = open ? 'translateX(0)' : `translateX(-${this.options.panelWidth}px)`;
      this.fleetToggle.setAttribute('aria-expanded', open);
      return;
    }
    
    this.gsap.to(this.panel, {
      x: open ? 0 : -this.options.panelWidth,
      duration: this.options.transitionDuration,
      ease: this.options.ease
    });
    
    // Rotate toggle icon
    this.gsap.to(this.fleetToggle.querySelector('svg'), {
      rotation: open ? 0 : 180,
      duration: 0.3,
      ease: 'power2.out'
    });
    
    this.fleetToggle.setAttribute('aria-expanded', open);
  }
  
  /**
   * Create expanded view for agent
   * @private
   */
  _createExpandedView(agentId, card) {
    const agent = this.agents.find(a => a.id === agentId);
    const state = this.agentStates.get(agentId);
    if (!agent || !state) return;
    
    // Position expanded panel near the card
    const cardRect = card.getBoundingClientRect();
    const panelRect = this.panel.getBoundingClientRect();
    
    // Update header
    this.expandedPanel.querySelector('.fleet-expanded-icon').textContent = agent.icon;
    this.expandedPanel.querySelector('.fleet-expanded-icon').style.color = agent.accent;
    this.expandedPanel.querySelector('.fleet-expanded-name').textContent = agent.name;
    this.expandedPanel.querySelector('.fleet-expanded-role').textContent = agent.role;
    
    // Update overview
    this._updateExpandedView(agentId);
    
    // Show overlay and panel
    this.expandedOverlay.hidden = false;
    this.expandedPanel.hidden = false;
    
    // Set initial state for animation
    this.expandedPanel.style.transform = 'translateX(20px)';
    this.expandedPanel.style.opacity = '0';
    this.expandedOverlay.style.opacity = '0';
  }
  
  /**
   * Update expanded view content
   * @private
   */
  _updateExpandedView(agentId) {
    const agent = this.agents.find(a => a.id === agentId);
    const state = this.agentStates.get(agentId);
    if (!agent || !state) return;
    
    // Status badge
    const statusBadge = this.expandedPanel.querySelector('.fleet-status-badge');
    statusBadge.className = `fleet-overview-value fleet-status-badge fleet-status-${state.status}`;
    statusBadge.innerHTML = `<span class="fleet-status-dot" aria-hidden="true"></span>${state.status}`;
    
    // Current task
    this.expandedPanel.querySelector('.fleet-current-task').textContent = state.task || 'Idle';
    
    // Progress
    const progressPercent = Math.round(state.progress * 100);
    this.expandedPanel.querySelector('.fleet-progress-bar').style.width = `${progressPercent}%`;
    this.expandedPanel.querySelector('.fleet-progress-text').textContent = `${progressPercent}%`;
    this.expandedPanel.querySelector('.fleet-progress-bar').style.background = agent.accent;
    
    // Last update
    const lastUpdate = new Date(state.lastUpdate);
    this.expandedPanel.querySelector('.fleet-last-update').textContent = 
      lastUpdate.toLocaleTimeString() + ' (' + this._timeAgo(state.lastUpdate) + ')';
    
    // Port and endpoint
    this.expandedPanel.querySelector('.fleet-port').textContent = agent.port;
    this.expandedPanel.querySelector('.fleet-endpoint').textContent = 
      `${this.options.basePath || ''}/api/v1/${agent.id}/*`;
    
    // Logs
    this._renderLogs(state.logs);
    
    // Timeline
    this._renderTimeline(state.timeline);
    
    // Output
    this._renderOutput(state.output);
  }
  
  /**
   * Render logs in expanded view
   * @private
   */
  _renderLogs(logs) {
    const container = this.expandedPanel.querySelector('.fleet-logs-list');
    if (!logs || logs.length === 0) {
      container.innerHTML = '<div class="fleet-empty-state">No logs available</div>';
      return;
    }
    
    container.innerHTML = logs.slice(-100).map(log => `
      <div class="fleet-log-entry fleet-log-${log.level || 'info'}">
        <span class="fleet-log-time">${new Date(log.timestamp).toLocaleTimeString()}</span>
        <span class="fleet-log-level">${(log.level || 'info').toUpperCase()}</span>
        <span class="fleet-log-message">${this._escapeHtml(log.message)}</span>
      </div>
    `).join('');
    
    // Auto-scroll to bottom
    container.scrollTop = container.scrollHeight;
  }
  
  /**
   * Render timeline in expanded view
   * @private
   */
  _renderTimeline(timeline) {
    const container = this.expandedPanel.querySelector('.fleet-timeline-list');
    if (!timeline || timeline.length === 0) {
      container.innerHTML = '<div class="fleet-empty-state">No timeline events</div>';
      return;
    }
    
    container.innerHTML = timeline.map((event, index) => `
      <div class="fleet-timeline-item" style="--accent: ${event.color || 'var(--lime)'};">
        <div class="fleet-timeline-marker" aria-hidden="true"></div>
        <div class="fleet-timeline-content">
          <div class="fleet-timeline-header">
            <span class="fleet-timeline-title">${this._escapeHtml(event.title)}</span>
            <span class="fleet-timeline-time">${new Date(event.timestamp).toLocaleTimeString()}</span>
          </div>
          <div class="fleet-timeline-description">${this._escapeHtml(event.description || '')}</div>
          ${event.duration ? `<div class="fleet-timeline-duration">Duration: ${this._formatDuration(event.duration)}</div>` : ''}
        </div>
      </div>
    `).join('');
  }
  
  /**
   * Render output in expanded view
   * @private
   */
  _renderOutput(output) {
    const container = this.expandedPanel.querySelector('.fleet-output-content');
    if (!output) {
      container.textContent = 'No output available';
      return;
    }
    
    container.textContent = typeof output === 'object' ? JSON.stringify(output, null, 2) : String(output);
  }
  
  /**
   * Animate expanded panel entrance
   * @private
   */
  _animateExpand(agentId, card) {
    if (this.prefersReducedMotion || !this.gsap) {
      this.expandedPanel.style.transform = 'translateX(0)';
      this.expandedPanel.style.opacity = '1';
      this.expandedOverlay.style.opacity = '1';
      this._focusFirstTab();
      return;
    }
    
    this.gsap.to(this.expandedOverlay, {
      opacity: 1,
      duration: 0.2,
      ease: 'power2.out'
    });
    
    this.gsap.to(this.expandedPanel, {
      x: 0,
      opacity: 1,
      duration: this.options.transitionDuration,
      ease: this.options.ease,
      onComplete: () => this._focusFirstTab()
    });
    
    // Update card aria-expanded
    card.setAttribute('aria-expanded', 'true');
  }
  
  /**
   * Collapse agent detail view
   * @private
   */
  _collapseAgent(agentId) {
    const card = this.agentCards.get(agentId);
    
    if (this.prefersReducedMotion || !this.gsap) {
      this.expandedPanel.hidden = true;
      this.expandedOverlay.hidden = true;
      if (card) card.setAttribute('aria-expanded', 'false');
      return;
    }
    
    this.gsap.to(this.expandedOverlay, {
      opacity: 0,
      duration: 0.2,
      ease: 'power2.in'
    });
    
    this.gsap.to(this.expandedPanel, {
      x: 20,
      opacity: 0,
      duration: 0.3,
      ease: 'power2.in',
      onComplete: () => {
        this.expandedPanel.hidden = true;
        this.expandedOverlay.hidden = true;
      }
    });
    
    if (card) card.setAttribute('aria-expanded', 'false');
  }
  
  /**
   * Switch tab in expanded view
   * @private
   */
  _switchTab(tabName) {
    // Update tab buttons
    this.expandedTabs.querySelectorAll('[data-tab]').forEach(btn => {
      const isActive = btn.dataset.tab === tabName;
      btn.setAttribute('aria-selected', isActive);
    });
    
    // Update panels
    this.expandedPanel.querySelectorAll('.fleet-tab-panel').forEach(panel => {
      const isActive = panel.dataset.tab === tabName;
      panel.hidden = !isActive;
      if (isActive) panel.classList.add('active');
      else panel.classList.remove('active');
    });
  }
  
  /**
   * Focus first tab for accessibility
   * @private
   */
  _focusFirstTab() {
    const firstTab = this.expandedTabs.querySelector('[data-tab][aria-selected="true"]');
    if (firstTab) firstTab.focus();
  }
  
  /**
   * Filter agents by search query
   * @private
   */
  _filterAgents(query) {
    const lowerQuery = query.toLowerCase().trim();
    
    this.agentCards.forEach((card, agentId) => {
      const agent = this.agents.find(a => a.id === agentId);
      const state = this.agentStates.get(agentId);
      
      const matches = !lowerQuery || 
        agent.name.toLowerCase().includes(lowerQuery) ||
        agent.role.toLowerCase().includes(lowerQuery) ||
        state.status.toLowerCase().includes(lowerQuery) ||
        state.task.toLowerCase().includes(lowerQuery);
      
      card.style.display = matches ? '' : 'none';
    });
  }
  
  /**
   * Connect to WebSocket for real-time updates
   * @private
   */
  _connectWS() {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }
    
    try {
      const wsUrl = this._getWSUrl();
      this.ws = new WebSocket(wsUrl);
      
      this.ws.onopen = this._onWSOpen;
      this.ws.onmessage = this._onWSMessage;
      this.ws.onclose = this._onWSClose;
      this.ws.onerror = this._onWSError;
    } catch (e) {
      this.options.onError('WebSocket connection failed: ' + e.message);
      this._scheduleReconnect();
    }
  }
  
  /**
   * Get WebSocket URL
   * @private
   */
  _getWSUrl() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    return `${protocol}//${host}${this.options.basePath}${this.options.wsEndpoint}`;
  }
  
  /**
   * WebSocket open handler
   * @private
   */
  _onWSOpen() {
    console.log('[AgentFleet] WebSocket connected');
    this.reconnectAttempts = 0;
    
    // Subscribe to agent updates
    this.ws.send(JSON.stringify({
      type: 'subscribe',
      channel: 'agents'
    }));
  }
  
  /**
   * WebSocket message handler
   * @private
   */
  _onWSMessage(event) {
    try {
      const data = JSON.parse(event.data);
      
      switch (data.type) {
        case 'agent_status':
          this.updateAgent(data.agentId, data.payload);
          break;
        case 'agent_batch':
          data.payload.forEach(update => this.updateAgent(update.agentId, update));
          break;
        case 'heartbeat':
          // Keep alive
          break;
        default:
          console.debug('[AgentFleet] Unknown WS message:', data.type);
      }
    } catch (e) {
      this.options.onError('WS message parse error: ' + e.message);
    }
  }
  
  /**
   * WebSocket close handler
   * @private
   */
  _onWSClose() {
    console.log('[AgentFleet] WebSocket disconnected');
    this._scheduleReconnect();
  }
  
  /**
   * WebSocket error handler
   * @private
   */
  _onWSError(error) {
    this.options.onError('WebSocket error: ' + error.message);
  }
  
  /**
   * Schedule WebSocket reconnection
   * @private
   */
  _scheduleReconnect() {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    
    if (this.reconnectAttempts >= this.options.maxReconnectAttempts) {
      console.warn('[AgentFleet] Max reconnect attempts reached');
      return;
    }
    
    this.reconnectAttempts++;
    const delay = Math.min(this.options.reconnectInterval * Math.pow(1.5, this.reconnectAttempts - 1), 30000);
    
    this.reconnectTimer = setTimeout(() => {
      this._connectWS();
    }, delay);
  }
  
  /**
   * Disconnect WebSocket
   * @private
   */
  _disconnectWS() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    
    if (this.ws) {
      this.ws.onopen = null;
      this.ws.onmessage = null;
      this.ws.onclose = null;
      this.ws.onerror = null;
      
      if (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING) {
        this.ws.close();
      }
      this.ws = null;
    }
  }
  
  /**
   * Handle keyboard events
   * @private
   */
  _handleKeydown(e) {
    // Escape to collapse expanded view
    if (e.key === 'Escape' && this.expandedAgent) {
      this.collapse();
    }
    
    // Arrow keys for navigation when panel is focused
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      const focusedCard = this.panel.querySelector('.fleet-agent-card:focus');
      if (focusedCard) {
        e.preventDefault();
        const cards = Array.from(this.agentCards.values()).filter(c => c.style.display !== 'none');
        const index = cards.indexOf(focusedCard);
        const nextIndex = e.key === 'ArrowDown' ? 
          (index + 1) % cards.length : 
          (index - 1 + cards.length) % cards.length;
        cards[nextIndex].focus();
      }
    }
    
    // Tab navigation in expanded view
    if (e.key === 'Tab' && this.expandedAgent && !this.expandedPanel.hidden) {
      const focusableElements = this.expandedPanel.querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      );
      const firstElement = focusableElements[0];
      const lastElement = focusableElements[focusableElements.length - 1];
      
      if (e.shiftKey && document.activeElement === firstElement) {
        e.preventDefault();
        lastElement.focus();
      } else if (!e.shiftKey && document.activeElement === lastElement) {
        e.preventDefault();
        firstElement.focus();
      }
    }
  }
  
  /**
   * Handle resize
   * @private
   */
  _handleResize() {
    // Adjust panel width on mobile
    const isMobile = window.innerWidth <= 900;
    if (isMobile && this.isPanelOpen) {
      this.panel.style.width = '100%';
      this.panel.style.maxWidth = '360px';
    } else {
      this.panel.style.width = '';
      this.panel.style.maxWidth = '';
    }
  }
  
  // ==================== Utility Methods ====================
  
  /**
   * Format time ago
   * @private
   */
  _timeAgo(timestamp) {
    const diff = Date.now() - timestamp;
    if (diff < 1000) return 'just now';
    if (diff < 60000) return `${Math.floor(diff / 1000)}s ago`;
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
    return `${Math.floor(diff / 86400000)}d ago`;
  }
  
  /**
   * Format duration in ms
   * @private
   */
  _formatDuration(ms) {
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    return `${(ms / 60000).toFixed(1)}m`;
  }
  
  /**
   * Escape HTML
   * @private
   */
  _escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
}

// Export for different module systems
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { AgentFleet };
}

if (typeof window !== 'undefined') {
  window.AgentFleet = AgentFleet;
}

export { AgentFleet };