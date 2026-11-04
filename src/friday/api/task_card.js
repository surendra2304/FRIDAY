/**
 * FRIDAY Task Card Component
 * Animated task cards for displaying delegated tasks with expandable details
 * 
 * Usage:
 *   import { TaskCardManager } from './task_card.js';
 *   const taskCards = new TaskCardManager();
 *   await taskCards.init(document.getElementById('task-container'));
 *   taskCards.addTask('stratex', { description: 'Running backtest', input: {...} });
 *   taskCards.updateStatus('task-123', 'running', { progress: 0.5 });
 * 
 * Dependencies: GSAP (for animations)
 */

class TaskCardManager {
  constructor(options = {}) {
    this.options = Object.assign({
      // Container configuration
      basePath: '',
      
      // Animation settings
      staggerDelay: 0.08,
      slideInDuration: 0.5,
      slideOutDuration: 0.3,
      ease: 'cubic-bezier(.16,1,.3,1)',
      
      // Auto-dismiss
      autoDismissDelay: 5000, // ms after completion
      autoDismissEnabled: true,
      
      // Task configuration
      maxVisibleTasks: 10,
      
      // Callbacks
      onTaskClick: null,        // (taskId, taskData) => void
      onTaskExpand: null,       // (taskId) => void
      onTaskDismiss: null,      // (taskId) => void
      onTaskRunAgain: null,     // (taskId, originalTask) => void
      onCopyInput: null,        // (taskId, input) => void
      onCopyOutput: null,       // (taskId, output) => void
      onError: (msg) => console.warn('[TaskCard]', msg)
    }, options);

    // DOM references
    this.container = null;
    this.taskList = null;
    this.taskCards = new Map(); // taskId -> card element
    this.taskData = new Map();  // taskId -> full task data
    this.expandedTaskId = null;
    this.expandedPanel = null;
    this.expandedOverlay = null;

    // Animation
    this.gsap = null;
    this.animationTimeline = null;

    // Task counter for IDs
    this.taskCounter = 0;

    // Reduced motion
    this.prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    this._reducedMotionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    this._onReducedMotionChange = (e) => {
      this.prefersReducedMotion = e.matches;
    };
    this._reducedMotionQuery.addEventListener('change', this._onReducedMotionChange);

    // Agent configurations for icons/colors
    this.agents = {
      friday:       { name: 'FRIDAY',       icon: '⬟', accent: '#b4f46b', role: 'Orchestrator' },
      inference:    { name: 'Inference',    icon: '◈', accent: '#6bc9e8', role: 'LLM Gateway' },
      memora:       { name: 'Memora',       icon: '◆', accent: '#b7a7ff', role: 'Memory' },
      stratex:      { name: 'Stratex',      icon: '▲', accent: '#b4f46b', role: 'Trading' },
      futuris:      { name: 'Futuris',      icon: '◆', accent: '#f2c679', role: 'Forecasting' },
      intelx:       { name: 'IntelX',       icon: '⬢', accent: '#ff7c86', role: 'Security' },
      forge:        { name: 'Forge',        icon: '⬡', accent: '#7ee0b5', role: 'Coding' },
      sentinel:     { name: 'Sentinel',     icon: '⬠', accent: '#ff7c86', role: 'SecOps' },
      cortex:       { name: 'Cortex',       icon: '◉', accent: '#b7a7ff', role: 'CRM/Ops' },
      vyralx:       { name: 'VyralX',       icon: '▼', accent: '#f2c679', role: 'Video' }
    };

    // Status configurations
    this.statusConfig = {
      pending:  { label: 'Pending',  class: 'status-pending',  color: '#7a8a99', pulse: false },
      running:  { label: 'Running',  class: 'status-running',  color: '#6bc9e8', pulse: true  },
      done:     { label: 'Complete', class: 'status-done',     color: '#85f0bf', pulse: false },
      failed:   { label: 'Failed',   class: 'status-failed',   color: '#f87a7a', pulse: false },
      cancelled:{ label: 'Cancelled',class: 'status-cancelled',color: '#f0c068', pulse: false }
    };
  }

  // ==================== Public API ====================

  /**
   * Initialize the task card manager
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
      await this._loadGSAP();
      this._buildDOM();
      this._cacheElements();
      this._bindEvents();
      console.log('[TaskCard] Initialized');
    } catch (error) {
      this.options.onError('Initialization failed: ' + error.message);
      throw error;
    }
  }

  /**
   * Add a new task card
   * @param {string} agentId - Agent identifier (e.g., 'stratex')
   * @param {Object} task - Task data { description, input, meta }
   * @returns {string} taskId - Generated task ID
   */
  addTask(agentId, task) {
    const taskId = `task-${Date.now()}-${++this.taskCounter}`;
    const agent = this.agents[agentId] || { name: agentId, icon: '⬟', accent: '#7a8a99', role: 'Agent' };

    const taskData = {
      id: taskId,
      agentId,
      agent,
      description: task.description || 'Task',
      input: task.input || {},
      meta: task.meta || {},
      status: 'pending',
      progress: 0,
      logs: [],
      timeline: [],
      output: null,
      error: null,
      startedAt: Date.now(),
      completedAt: null,
      dismissed: false
    };

    this.taskData.set(taskId, taskData);

    // Create and insert card
    const card = this._createTaskCard(taskData);
    this.taskCards.set(taskId, card);

    // Insert at top (newest first)
    if (this.taskList.firstChild) {
      this.taskList.insertBefore(card, this.taskList.firstChild);
    } else {
      this.taskList.appendChild(card);
    }

    // Enforce max visible tasks
    this._enforceMaxTasks();

    // Animate entrance
    this._animateCardEntrance(card);

    return taskId;
  }

  /**
   * Update task status
   * @param {string} taskId - Task identifier
   * @param {string} status - Status: 'pending' | 'running' | 'done' | 'failed' | 'cancelled'
   * @param {Object} [data] - Additional data { progress, logs, output, error, timeline }
   */
  updateStatus(taskId, status, data = {}) {
    const taskData = this.taskData.get(taskId);
    const card = this.taskCards.get(taskId);
    if (!taskData || !card) return;

    const prevStatus = taskData.status;
    const prevProgress = taskData.progress;

    // Update task data
    taskData.status = status;
    if (data.progress !== undefined) taskData.progress = Math.max(0, Math.min(1, data.progress));
    if (data.logs !== undefined) taskData.logs = data.logs;
    if (data.output !== undefined) taskData.output = data.output;
    if (data.error !== undefined) taskData.error = data.error;
    if (data.timeline !== undefined) taskData.timeline = data.timeline;

    if (status === 'done' || status === 'failed' || status === 'cancelled') {
      taskData.completedAt = Date.now();
    }

    // Update DOM
    this._updateTaskCard(taskId, card, taskData);

    // If expanded, update detail view
    if (this.expandedTaskId === taskId) {
      this._updateExpandedView(taskId);
    }

    // Animate progress ring if changed
    if (data.progress !== undefined && data.progress !== prevProgress) {
      this._animateProgressRing(taskId, prevProgress, data.progress);
    }

    // Handle completion auto-dismiss
    if ((status === 'done' || status === 'failed') && prevStatus !== status) {
      this._handleCompletion(taskId, status);
    }
  }

  /**
   * Expand task to show full details
   * @param {string} taskId - Task identifier
   */
  expand(taskId) {
    if (this.expandedTaskId === taskId) return;

    // Collapse current if any
    if (this.expandedTaskId) {
      this._collapseExpanded();
    }

    const card = this.taskCards.get(taskId);
    const taskData = this.taskData.get(taskId);
    if (!card || !taskData) return;

    this.expandedTaskId = taskId;

    // Create expanded panel
    this._createExpandedPanel(taskData, card);

    // Animate expansion
    this._animateExpand(taskId, card);

    // Callback
    if (this.options.onTaskExpand) {
      this.options.onTaskExpand(taskId, taskData);
    }
  }

  /**
   * Dismiss/remove a task card
   * @param {string} taskId - Task identifier
   * @param {boolean} [animate=true] - Whether to animate removal
   */
  dismiss(taskId, animate = true) {
    const card = this.taskCards.get(taskId);
    const taskData = this.taskData.get(taskId);
    if (!card || !taskData) return;

    taskData.dismissed = true;

    // If this is the expanded task, collapse first
    if (this.expandedTaskId === taskId) {
      this._collapseExpanded(true); // immediate
    }

    // Animate removal
    if (animate && !this.prefersReducedMotion && this.gsap) {
      this.gsap.to(card, {
        x: 30,
        opacity: 0,
        height: 0,
        marginTop: 0,
        marginBottom: 0,
        paddingTop: 0,
        paddingBottom: 0,
        duration: this.options.slideOutDuration,
        ease: this.options.ease,
        onComplete: () => this._removeCard(taskId)
      });
    } else {
      this._removeCard(taskId);
    }

    // Callback
    if (this.options.onTaskDismiss) {
      this.options.onTaskDismiss(taskId, taskData);
    }
  }

  /**
   * Get task data
   * @param {string} taskId - Task identifier
   * @returns {Object|null}
   */
  getTask(taskId) {
    return this.taskData.get(taskId) || null;
  }

  /**
   * Get all tasks
   * @returns {Array<Object>}
   */
  getAllTasks() {
    return Array.from(this.taskData.values());
  }

  /**
   * Clear all tasks
   */
  clearAll() {
    this.taskCards.forEach((card, taskId) => {
      this.dismiss(taskId, false);
    });
    this.taskCards.clear();
    this.taskData.clear();
  }

  /**
   * Destroy the component and clean up
   */
  destroy() {
    // Kill animations
    if (this.animationTimeline) {
      this.animationTimeline.kill();
      this.animationTimeline = null;
    }
    if (this.gsap) {
      this.gsap.killTweensOf('*');
    }

    // Collapse expanded view
    if (this.expandedTaskId) {
      this._collapseExpanded(true);
    }

    // Remove event listeners
    this._unbindEvents();
    window.removeEventListener('resize', this._handleResize);
    document.removeEventListener('keydown', this._handleKeydown);
    this._reducedMotionQuery.removeEventListener('change', this._onReducedMotionChange);

    // Remove DOM
    if (this.expandedOverlay && this.expandedOverlay.parentNode) {
      this.expandedOverlay.parentNode.removeChild(this.expandedOverlay);
    }
    if (this.expandedPanel && this.expandedPanel.parentNode) {
      this.expandedPanel.parentNode.removeChild(this.expandedPanel);
    }

    // Clear references
    this.container = null;
    this.taskList = null;
    this.taskCards.clear();
    this.taskData.clear();
    this.expandedTaskId = null;
    this.expandedPanel = null;
    this.expandedOverlay = null;

    console.log('[TaskCard] Destroyed');
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
   * Build the DOM structure
   * @private
   */
  _buildDOM() {
    const html = `
      <div class="task-card-container" role="region" aria-label="Active tasks">
        <div class="task-card-header">
          <h2 class="task-card-title">
            <span class="task-card-icon" aria-hidden="true">⬟</span>
            Active Tasks
          </h2>
          <div class="task-card-controls">
            <button class="task-card-btn task-card-btn-clear" aria-label="Clear all tasks" title="Clear all">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="3 6 5 6 21 6"></polyline>
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
              </svg>
            </button>
            <button class="task-card-btn task-card-btn-auto" aria-label="Toggle auto-dismiss" title="Auto-dismiss completed" aria-pressed="true">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
              </svg>
            </button>
          </div>
        </div>
        <div class="task-card-list" role="list" aria-label="Task cards">
          <!-- Task cards injected here -->
        </div>
        <div class="task-card-empty" hidden>
          <svg class="task-empty-icon" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
            <path d="M9 11l3 3L22 4"></path>
            <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"></path>
          </svg>
          <p class="task-empty-text">No active tasks</p>
          <p class="task-empty-subtext">Tasks delegated by FRIDAY will appear here</p>
        </div>
      </div>
      <div class="task-expanded-overlay" hidden></div>
      <div class="task-expanded-panel" hidden role="dialog" aria-label="Task details" aria-modal="true">
        <div class="task-expanded-header">
          <div class="task-expanded-agent">
            <span class="task-expanded-icon" aria-hidden="true"></span>
            <div>
              <strong class="task-expanded-agent-name"></strong>
              <span class="task-expanded-agent-role"></span>
            </div>
          </div>
          <div class="task-expanded-status">
            <span class="task-expanded-badge"></span>
          </div>
          <button class="task-expanded-close" aria-label="Close details">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>
        <div class="task-expanded-content">
          <div class="task-expanded-tabs" role="tablist">
            <button role="tab" data-tab="overview" aria-selected="true">Overview</button>
            <button role="tab" data-tab="logs" aria-selected="false">Logs</button>
            <button role="tab" data-tab="timeline" aria-selected="false">Timeline</button>
            <button role="tab" data-tab="io" aria-selected="false">Input / Output</button>
          </div>
          <div class="task-expanded-panels">
            <div role="tabpanel" data-tab="overview" class="task-tab-panel active">
              <div class="task-overview-grid">
                <div class="task-overview-item">
                  <span class="task-overview-label">Status</span>
                  <span class="task-overview-value task-status-badge"></span>
                </div>
                <div class="task-overview-item">
                  <span class="task-overview-label">Description</span>
                  <span class="task-overview-value task-description"></span>
                </div>
                <div class="task-overview-item">
                  <span class="task-overview-label">Progress</span>
                  <div class="task-progress-container">
                    <div class="task-progress-bar" style="width: 0%"></div>
                  </div>
                  <span class="task-progress-text">0%</span>
                </div>
                <div class="task-overview-item">
                  <span class="task-overview-label">Started</span>
                  <span class="task-overview-value task-started-at"></span>
                </div>
                <div class="task-overview-item">
                  <span class="task-overview-label">Duration</span>
                  <span class="task-overview-value task-duration"></span>
                </div>
                <div class="task-overview-item task-overview-full">
                  <span class="task-overview-label">Task ID</span>
                  <span class="task-overview-value task-id-value"></span>
                </div>
              </div>
            </div>
            <div role="tabpanel" data-tab="logs" class="task-tab-panel" hidden>
              <div class="task-logs-container">
                <div class="task-logs-header">
                  <span class="task-logs-title">Execution Logs</span>
                  <button class="task-logs-clear" type="button">Clear</button>
                </div>
                <div class="task-logs-list" role="log" aria-live="polite"></div>
              </div>
            </div>
            <div role="tabpanel" data-tab="timeline" class="task-tab-panel" hidden>
              <div class="task-timeline-container">
                <div class="task-timeline-list"></div>
              </div>
            </div>
            <div role="tabpanel" data-tab="io" class="task-tab-panel" hidden>
              <div class="task-io-container">
                <div class="task-io-section">
                  <div class="task-io-header">
                    <span class="task-io-label">Input</span>
                    <button class="task-io-copy" data-copy="input" type="button" aria-label="Copy input">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                      </svg>
                      <span>Copy</span>
                    </button>
                  </div>
                  <pre class="task-io-content task-input-content"></pre>
                </div>
                <div class="task-io-section">
                  <div class="task-io-header">
                    <span class="task-io-label">Output</span>
                    <button class="task-io-copy" data-copy="output" type="button" aria-label="Copy output">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                      </svg>
                      <span>Copy</span>
                    </button>
                  </div>
                  <pre class="task-io-content task-output-content"></pre>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div class="task-expanded-actions">
          <button class="task-btn task-btn-secondary task-btn-run-again" type="button">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="1 4 1 10 7 10"></polyline>
              <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"></path>
            </svg>
            <span>Run Again</span>
          </button>
          <button class="task-btn task-btn-primary task-btn-dismiss" type="button">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
            <span>Dismiss</span>
          </button>
        </div>
      </div>
    `;

    this.container.insertAdjacentHTML('beforeend', html);
  }

  /**
   * Cache DOM elements
   * @private
   */
  _cacheElements() {
    this.taskList = this.container.querySelector('.task-card-list');
    this.emptyState = this.container.querySelector('.task-card-empty');
    this.clearBtn = this.container.querySelector('.task-card-btn-clear');
    this.autoDismissBtn = this.container.querySelector('.task-card-btn-auto');
    this.expandedOverlay = this.container.querySelector('.task-expanded-overlay');
    this.expandedPanel = this.container.querySelector('.task-expanded-panel');
    this.expandedClose = this.container.querySelector('.task-expanded-close');
    this.expandedTabs = this.container.querySelector('.task-expanded-tabs');
    this.runAgainBtn = this.container.querySelector('.task-btn-run-again');
    this.dismissBtn = this.container.querySelector('.task-btn-dismiss');
    this.logsClearBtn = this.container.querySelector('.task-logs-clear');
  }

  /**
   * Bind event listeners
   * @private
   */
  _bindEvents() {
    // Clear all
    this.clearBtn.addEventListener('click', () => this.clearAll());

    // Auto-dismiss toggle
    this.autoDismissBtn.addEventListener('click', () => {
      const enabled = this.autoDismissBtn.getAttribute('aria-pressed') === 'true';
      this.autoDismissBtn.setAttribute('aria-pressed', !enabled);
      this.autoDismissBtn.querySelector('svg').style.opacity = enabled ? '0.4' : '1';
    });

    // Expanded panel events
    this.expandedClose.addEventListener('click', () => this._collapseExpanded());
    this.expandedOverlay.addEventListener('click', () => this._collapseExpanded());

    // Tab switching
    this.expandedTabs.addEventListener('click', (e) => {
      const tabBtn = e.target.closest('[data-tab]');
      if (tabBtn) this._switchTab(tabBtn.dataset.tab);
    });

    // Action buttons
    this.runAgainBtn.addEventListener('click', () => this._handleRunAgain());
    this.dismissBtn.addEventListener('click', () => this._handleDismiss());

    // Copy buttons
    this.expandedPanel.querySelectorAll('.task-io-copy').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const type = btn.dataset.copy;
        this._handleCopy(type);
      });
    });

    // Logs clear
    this.logsClearBtn.addEventListener('click', () => {
      if (this.expandedTaskId) {
        const taskData = this.taskData.get(this.expandedTaskId);
        taskData.logs = [];
        this._updateExpandedView(this.expandedTaskId);
      }
    });

    // Keyboard
    document.addEventListener('keydown', this._handleKeydown.bind(this));

    // Resize
    window.addEventListener('resize', this._handleResize.bind(this));
  }

  /**
   * Unbind event listeners
   * @private
   */
  _unbindEvents() {
    this.clearBtn.removeEventListener('click', () => this.clearAll());
    this.autoDismissBtn.removeEventListener('click', () => {});
    this.expandedClose.removeEventListener('click', () => this._collapseExpanded());
    this.expandedOverlay.removeEventListener('click', () => this._collapseExpanded());
    this.expandedTabs.removeEventListener('click', this._switchTab);
    this.runAgainBtn.removeEventListener('click', () => this._handleRunAgain());
    this.dismissBtn.removeEventListener('click', () => this._handleDismiss());
    this.logsClearBtn.removeEventListener('click', () => {});
    document.removeEventListener('keydown', this._handleKeydown.bind(this));
    window.removeEventListener('resize', this._handleResize.bind(this));
  }

  /**
   * Create a single task card element
   * @private
   */
  _createTaskCard(taskData) {
    const { id, agent, description, status, progress, startedAt } = taskData;
    const statusConfig = this.statusConfig[status] || this.statusConfig.pending;
    const progressPercent = Math.round(progress * 100);
    const index = this.taskCards.size;

    const card = document.createElement('button');
    card.className = 'task-card';
    card.dataset.taskId = id;
    card.style.setProperty('--agent-accent', agent.accent);
    card.style.setProperty('--status-color', statusConfig.color);
    card.style.setProperty('--stagger-delay', `${index * this.options.staggerDelay}s`);
    card.setAttribute('role', 'listitem');
    card.setAttribute('tabindex', '0');
    card.setAttribute('aria-expanded', 'false');

    card.innerHTML = `
      <div class="task-card-agent" style="background: linear-gradient(135deg, ${agent.accent}22, ${agent.accent}08); border-color: ${agent.accent}44;">
        <span aria-hidden="true" style="color: ${agent.accent};">${agent.icon}</span>
      </div>
      <div class="task-card-main">
        <div class="task-card-header-row">
          <div class="task-card-agent-info">
            <strong class="task-card-agent-name">${agent.name}</strong>
            <span class="task-card-agent-role">${agent.role}</span>
          </div>
          <div class="task-card-status ${statusConfig.class}" aria-label="Status: ${statusConfig.label}">
            <span class="task-status-dot" aria-hidden="true" style="background: ${statusConfig.color}; ${statusConfig.pulse ? 'animation: task-pulse 1.5s ease-in-out infinite;' : ''}"></span>
            <span class="task-status-text">${statusConfig.label}</span>
          </div>
        </div>
        <div class="task-card-description" title="${description}">${description}</div>
        <div class="task-card-progress-row">
          <div class="task-card-progress-ring" aria-label="Progress: ${progressPercent}%">
            <svg class="task-progress-svg" viewBox="0 0 40 40" aria-hidden="true">
              <circle class="task-progress-bg" cx="20" cy="20" r="16" fill="none" stroke="currentColor" stroke-width="3" stroke-opacity="0.15"/>
              <circle class="task-progress-fg" cx="20" cy="20" r="16" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"
                stroke-dasharray="100.53" stroke-dashoffset="${100.53 * (1 - progress)}"
                style="color: ${statusConfig.color}; transition: stroke-dashoffset 0.4s cubic-bezier(.16,1,.3,1);"/>
            </svg>
          </div>
          <div class="task-card-progress-info">
            <span class="task-card-progress-value">${progressPercent}%</span>
            <span class="task-card-progress-time">${this._formatTimeAgo(startedAt)}</span>
          </div>
        </div>
        ${status === 'running' ? `
          <div class="task-card-output-preview">
            <span class="task-output-label">Working...</span>
            <span class="task-output-dots"><span>.</span><span>.</span><span>.</span></span>
          </div>
        ` : status === 'done' && taskData.output ? `
          <div class="task-card-output-preview">
            <span class="task-output-label">Output:</span>
            <span class="task-output-preview-text">${this._truncateOutput(taskData.output)}</span>
          </div>
        ` : status === 'failed' && taskData.error ? `
          <div class="task-card-output-preview task-output-error">
            <span class="task-output-label">Error:</span>
            <span class="task-output-preview-text">${this._escapeHtml(String(taskData.error))}</span>
          </div>
        ` : ''}
      </div>
      <button class="task-card-expand" aria-label="Expand task details" tabindex="-1">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <polyline points="9 18 15 12 9 6"></polyline>
        </svg>
      </button>
    `;

    // Click handlers
    card.addEventListener('click', (e) => {
      if (!e.target.closest('.task-card-expand')) {
        this.expand(id);
        if (this.options.onTaskClick) {
          this.options.onTaskClick(id, taskData);
        }
      }
    });

    card.querySelector('.task-card-expand').addEventListener('click', (e) => {
      e.stopPropagation();
      this.expand(id);
    });

    // Keyboard support
    card.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        this.expand(id);
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
   * Update a single task card
   * @private
   */
  _updateTaskCard(taskId, card, taskData) {
    const { status, progress, agent, output, error } = taskData;
    const statusConfig = this.statusConfig[status] || this.statusConfig.pending;
    const progressPercent = Math.round(progress * 100);

    // Update status badge
    const statusEl = card.querySelector('.task-card-status');
    statusEl.className = `task-card-status ${statusConfig.class}`;
    statusEl.setAttribute('aria-label', `Status: ${statusConfig.label}`);
    statusEl.querySelector('.task-status-text').textContent = statusConfig.label;
    const statusDot = statusEl.querySelector('.task-status-dot');
    statusDot.style.background = statusConfig.color;
    statusDot.style.animation = statusConfig.pulse ? 'task-pulse 1.5s ease-in-out infinite' : 'none';

    // Update progress ring
    const fgCircle = card.querySelector('.task-progress-fg');
    fgCircle.style.strokeDashoffset = 100.53 * (1 - progress);
    fgCircle.style.color = statusConfig.color;
    card.querySelector('.task-card-progress-value').textContent = `${progressPercent}%`;
    card.querySelector('.task-card-progress-ring').setAttribute('aria-label', `Progress: ${progressPercent}%`);

    // Update output preview
    const previewContainer = card.querySelector('.task-card-output-preview');
    if (previewContainer) {
      previewContainer.remove();
    }

    const mainEl = card.querySelector('.task-card-main');
    if (status === 'running') {
      const preview = document.createElement('div');
      preview.className = 'task-card-output-preview';
      preview.innerHTML = `
        <span class="task-output-label">Working...</span>
        <span class="task-output-dots"><span>.</span><span>.</span><span>.</span></span>
      `;
      mainEl.appendChild(preview);
    } else if (status === 'done' && output) {
      const preview = document.createElement('div');
      preview.className = 'task-card-output-preview';
      preview.innerHTML = `
        <span class="task-output-label">Output:</span>
        <span class="task-output-preview-text">${this._truncateOutput(output)}</span>
      `;
      mainEl.appendChild(preview);
    } else if (status === 'failed' && error) {
      const preview = document.createElement('div');
      preview.className = 'task-card-output-preview task-output-error';
      preview.innerHTML = `
        <span class="task-output-label">Error:</span>
        <span class="task-output-preview-text">${this._escapeHtml(String(error))}</span>
      `;
      mainEl.appendChild(preview);
    }

    // Update time
    card.querySelector('.task-card-progress-time').textContent = this._formatTimeAgo(taskData.startedAt);

    // Update empty state visibility
    this._updateEmptyState();
  }

  /**
   * Animate card entrance
   * @private
   */
  _animateCardEntrance(card) {
    if (this.prefersReducedMotion || !this.gsap) {
      card.style.opacity = '1';
      card.style.transform = 'translateX(0)';
      this._updateEmptyState();
      return;
    }

    this.gsap.from(card, {
      x: -40,
      opacity: 0,
      duration: this.options.slideInDuration,
      ease: this.options.ease,
      delay: parseFloat(card.style.getPropertyValue('--stagger-delay')) || 0
    });

    this._updateEmptyState();
  }

  /**
   * Enforce maximum visible tasks
   * @private
   */
  _enforceMaxTasks() {
    const cards = Array.from(this.taskCards.values());
    if (cards.length > this.options.maxVisibleTasks) {
      const toRemove = cards.slice(this.options.maxVisibleTasks);
      toRemove.forEach(card => {
        const taskId = card.dataset.taskId;
        this.dismiss(taskId, true);
      });
    }
  }

  /**
   * Update empty state visibility
   * @private
   */
  _updateEmptyState() {
    const hasTasks = this.taskCards.size > 0;
    this.emptyState.hidden = hasTasks;
    this.taskList.style.display = hasTasks ? '' : 'none';
  }

  /**
   * Handle task completion (auto-dismiss)
   * @private
   */
  _handleCompletion(taskId, status) {
    const taskData = this.taskData.get(taskId);
    if (!taskData) return;

    // Add completion animation to card
    const card = this.taskCards.get(taskId);
    if (card && !this.prefersReducedMotion && this.gsap) {
      const statusConfig = this.statusConfig[status];
      this.gsap.to(card.querySelector('.task-card-agent'), {
        boxShadow: `0 0 20px ${statusConfig.color}66`,
        duration: 0.5,
        yoyo: true,
        repeat: 2
      });
    }

    // Auto-dismiss if enabled
    const autoDismissEnabled = this.autoDismissBtn.getAttribute('aria-pressed') === 'true';
    if (autoDismissEnabled && this.options.autoDismissEnabled) {
      setTimeout(() => {
        if (this.taskCards.has(taskId)) {
          this.dismiss(taskId, true);
        }
      }, this.options.autoDismissDelay);
    }
  }

  /**
   * Create expanded panel for task
   * @private
   */
  _createExpandedPanel(taskData, card) {
    const { id, agent, description, status, progress, startedAt, completedAt } = taskData;
    const statusConfig = this.statusConfig[status] || this.statusConfig.pending;

    // Update header
    this.expandedPanel.querySelector('.task-expanded-icon').textContent = agent.icon;
    this.expandedPanel.querySelector('.task-expanded-icon').style.color = agent.accent;
    this.expandedPanel.querySelector('.task-expanded-agent-name').textContent = agent.name;
    this.expandedPanel.querySelector('.task-expanded-agent-role').textContent = agent.role;

    // Update status badge
    const badge = this.expandedPanel.querySelector('.task-expanded-badge');
    badge.className = `task-expanded-badge ${statusConfig.class}`;
    badge.innerHTML = `<span class="task-status-dot" style="background: ${statusConfig.color}; ${statusConfig.pulse ? 'animation: task-pulse 1.5s ease-in-out infinite;' : ''}"></span>${statusConfig.label}`;

    // Update content
    this._updateExpandedView(id);

    // Show overlay and panel
    this.expandedOverlay.hidden = false;
    this.expandedPanel.hidden = false;

    // Set initial state for animation
    this.expandedPanel.style.transform = 'translateY(20px) scale(0.98)';
    this.expandedPanel.style.opacity = '0';
    this.expandedOverlay.style.opacity = '0';

    // Update card aria-expanded
    card.setAttribute('aria-expanded', 'true');
  }

  /**
   * Update expanded view content
   * @private
   */
  _updateExpandedView(taskId) {
    const taskData = this.taskData.get(taskId);
    if (!taskData) return;

    const { status, progress, description, startedAt, completedAt, logs, timeline, output, input, error, id } = taskData;
    const statusConfig = this.statusConfig[status] || this.statusConfig.pending;
    const progressPercent = Math.round(progress * 100);

    // Status badge
    const badge = this.expandedPanel.querySelector('.task-status-badge');
    badge.className = `task-overview-value task-status-badge ${statusConfig.class}`;
    badge.innerHTML = `<span class="task-status-dot" style="background: ${statusConfig.color}; ${statusConfig.pulse ? 'animation: task-pulse 1.5s ease-in-out infinite;' : ''}"></span>${statusConfig.label}`;

    // Description
    this.expandedPanel.querySelector('.task-description').textContent = description;

    // Progress
    this.expandedPanel.querySelector('.task-progress-bar').style.width = `${progressPercent}%`;
    this.expandedPanel.querySelector('.task-progress-text').textContent = `${progressPercent}%`;
    this.expandedPanel.querySelector('.task-progress-bar').style.background = statusConfig.color;

    // Started at
    this.expandedPanel.querySelector('.task-started-at').textContent = new Date(startedAt).toLocaleString();

    // Duration
    const endTime = completedAt || Date.now();
    this.expandedPanel.querySelector('.task-duration').textContent = this._formatDuration(endTime - startedAt);

    // Task ID
    this.expandedPanel.querySelector('.task-id-value').textContent = id;

    // Logs
    this._renderLogs(logs);

    // Timeline
    this._renderTimeline(timeline);

    // Input / Output
    this._renderIO(input, output, error);
  }

  /**
   * Render logs in expanded view
   * @private
   */
  _renderLogs(logs) {
    const container = this.expandedPanel.querySelector('.task-logs-list');
    if (!logs || logs.length === 0) {
      container.innerHTML = '<div class="task-empty-state">No logs available</div>';
      return;
    }

    container.innerHTML = logs.slice(-200).map(log => `
      <div class="task-log-entry task-log-${log.level || 'info'}">
        <span class="task-log-time">${new Date(log.timestamp).toLocaleTimeString()}</span>
        <span class="task-log-level">${(log.level || 'info').toUpperCase()}</span>
        <span class="task-log-message">${this._escapeHtml(log.message)}</span>
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
    const container = this.expandedPanel.querySelector('.task-timeline-list');
    if (!timeline || timeline.length === 0) {
      container.innerHTML = '<div class="task-empty-state">No timeline events</div>';
      return;
    }

    container.innerHTML = timeline.map((event, index) => `
      <div class="task-timeline-item" style="--accent: ${event.color || 'var(--lime)'};">
        <div class="task-timeline-marker" aria-hidden="true"></div>
        <div class="task-timeline-content">
          <div class="task-timeline-header">
            <span class="task-timeline-title">${this._escapeHtml(event.title)}</span>
            <span class="task-timeline-time">${new Date(event.timestamp).toLocaleTimeString()}</span>
          </div>
          <div class="task-timeline-description">${this._escapeHtml(event.description || '')}</div>
          ${event.duration ? `<div class="task-timeline-duration">Duration: ${this._formatDuration(event.duration)}</div>` : ''}
        </div>
      </div>
    `).join('');
  }

  /**
   * Render Input/Output in expanded view
   * @private
   */
  _renderIO(input, output, error) {
    const inputEl = this.expandedPanel.querySelector('.task-input-content');
    const outputEl = this.expandedPanel.querySelector('.task-output-content');

    inputEl.textContent = input && Object.keys(input).length > 0 ? JSON.stringify(input, null, 2) : 'No input data';

    if (error) {
      outputEl.textContent = `Error: ${String(error)}`;
      outputEl.classList.add('task-output-error');
    } else if (output !== null && output !== undefined) {
      outputEl.textContent = typeof output === 'object' ? JSON.stringify(output, null, 2) : String(output);
      outputEl.classList.remove('task-output-error');
    } else {
      outputEl.textContent = 'No output available';
      outputEl.classList.remove('task-output-error');
    }
  }

  /**
   * Animate expanded panel entrance
   * @private
   */
  _animateExpand(taskId, card) {
    if (this.prefersReducedMotion || !this.gsap) {
      this.expandedPanel.style.transform = 'translateY(0) scale(1)';
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
      y: 0,
      scale: 1,
      opacity: 1,
      duration: this.options.slideInDuration,
      ease: this.options.ease,
      onComplete: () => this._focusFirstTab()
    });
  }

  /**
   * Collapse expanded panel
   * @private
   */
  _collapseExpanded(immediate = false) {
    if (!this.expandedTaskId) return;

    const card = this.taskCards.get(this.expandedTaskId);

    if (immediate || this.prefersReducedMotion || !this.gsap) {
      this.expandedPanel.hidden = true;
      this.expandedOverlay.hidden = true;
      if (card) card.setAttribute('aria-expanded', 'false');
      this.expandedTaskId = null;
      return;
    }

    this.gsap.to(this.expandedOverlay, {
      opacity: 0,
      duration: 0.2,
      ease: 'power2.in'
    });

    this.gsap.to(this.expandedPanel, {
      y: 20,
      scale: 0.98,
      opacity: 0,
      duration: 0.3,
      ease: 'power2.in',
      onComplete: () => {
        this.expandedPanel.hidden = true;
        this.expandedOverlay.hidden = true;
      }
    });

    if (card) card.setAttribute('aria-expanded', 'false');
    this.expandedTaskId = null;
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
    this.expandedPanel.querySelectorAll('.task-tab-panel').forEach(panel => {
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
   * Handle Run Again button
   * @private
   */
  _handleRunAgain() {
    if (!this.expandedTaskId) return;
    const taskData = this.taskData.get(this.expandedTaskId);
    if (!taskData) return;

    if (this.options.onTaskRunAgain) {
      this.options.onTaskRunAgain(this.expandedTaskId, taskData);
    }
  }

  /**
   * Handle Dismiss button in expanded view
   * @private
   */
  _handleDismiss() {
    if (this.expandedTaskId) {
      this.dismiss(this.expandedTaskId, true);
    }
  }

  /**
   * Handle copy input/output
   * @private
   */
  async _handleCopy(type) {
    if (!this.expandedTaskId) return;
    const taskData = this.taskData.get(this.expandedTaskId);
    if (!taskData) return;

    const content = type === 'input' ? taskData.input : taskData.output;
    const text = content !== null && content !== undefined 
      ? (typeof content === 'object' ? JSON.stringify(content, null, 2) : String(content))
      : '';

    try {
      await navigator.clipboard.writeText(text);
      // Visual feedback
      const btn = this.expandedPanel.querySelector(`.task-io-copy[data-copy="${type}"]`);
      const originalText = btn.innerHTML;
      btn.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="20 6 9 17 4 12"></polyline>
        </svg>
        <span>Copied!</span>
      `;
      btn.style.color = '#85f0bf';
      setTimeout(() => {
        btn.innerHTML = originalText;
        btn.style.color = '';
      }, 1500);

      if (type === 'input' && this.options.onCopyInput) {
        this.options.onCopyInput(this.expandedTaskId, taskData.input);
      } else if (type === 'output' && this.options.onCopyOutput) {
        this.options.onCopyOutput(this.expandedTaskId, taskData.output);
      }
    } catch (e) {
      this.options.onError('Copy failed: ' + e.message);
    }
  }

  /**
   * Handle keyboard events
   * @private
   */
  _handleKeydown(e) {
    // Escape to collapse expanded view
    if (e.key === 'Escape' && this.expandedTaskId) {
      this._collapseExpanded();
    }

    // Arrow keys for navigation between cards
    if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && !this.expandedTaskId) {
      const focusedCard = this.container.querySelector('.task-card:focus');
      if (focusedCard) {
        e.preventDefault();
        const cards = Array.from(this.taskCards.values()).filter(c => c.style.display !== 'none');
        const index = cards.indexOf(focusedCard);
        const nextIndex = e.key === 'ArrowDown' 
          ? (index + 1) % cards.length 
          : (index - 1 + cards.length) % cards.length;
        cards[nextIndex].focus();
      }
    }

    // Tab navigation in expanded view
    if (e.key === 'Tab' && this.expandedTaskId && !this.expandedPanel.hidden) {
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
    // Adjust expanded panel position if needed
  }

  /**
   * Remove card from DOM and maps
   * @private
   */
  _removeCard(taskId) {
    const card = this.taskCards.get(taskId);
    if (card && card.parentNode) {
      card.parentNode.removeChild(card);
    }
    this.taskCards.delete(taskId);
    this.taskData.delete(taskId);
    this._updateEmptyState();
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
   * Format time ago for card display
   * @private
   */
  _formatTimeAgo(timestamp) {
    const diff = Date.now() - timestamp;
    if (diff < 1000) return 'just now';
    if (diff < 60000) return `${Math.floor(diff / 1000)}s`;
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h`;
    return `${Math.floor(diff / 86400000)}d`;
  }

  /**
   * Format duration in ms
   * @private
   */
  _formatDuration(ms) {
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    if (ms < 3600000) return `${(ms / 60000).toFixed(1)}m`;
    return `${(ms / 3600000).toFixed(1)}h`;
  }

  /**
   * Truncate output for preview
   * @private
   */
  _truncateOutput(output) {
    const text = typeof output === 'object' ? JSON.stringify(output) : String(output);
    return text.length > 80 ? text.slice(0, 77) + '...' : text;
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
  module.exports = { TaskCardManager };
}

if (typeof window !== 'undefined') {
  window.TaskCardManager = TaskCardManager;
}

export { TaskCardManager };