/**
 * FRIDAY API Client - Unified integration layer for all backend communication
 * 
 * Usage:
 *   import { FridayAPI } from './api_client.js';
 *   const api = new FridayAPI({ basePath: '/friday' });
 *   await api.init();
 *   const goal = await api.submitGoal('Analyze market trends', 10);
 * 
 * @module api_client
 */

class FridayAPI {
  /**
   * @param {Object} options
   * @param {string} [options.basePath=''] - Base path prefix (e.g., '/friday' or '')
   * @param {number} [options.tokenRefreshMargin=30000] - Refresh token this many ms before expiry
   * @param {number} [options.maxRetries=3] - Max retry attempts for failed requests
   * @param {number} [options.retryDelay=1000] - Base delay between retries (ms)
   * @param {Function} [options.onError] - Global error handler
   * @param {Function} [options.onTokenRefresh] - Called when token is refreshed
   * @param {boolean} [options.debug=false] - Enable debug logging
   */
  constructor(options = {}) {
    this.basePath = this._normalizeBasePath(options.basePath || '');
    this.tokenRefreshMargin = options.tokenRefreshMargin || 30000; // 30 seconds
    this.maxRetries = options.maxRetries ?? 3;
    this.retryDelay = options.retryDelay || 1000;
    this.onError = options.onError || ((msg) => console.error('[FridayAPI]', msg));
    this.onTokenRefresh = options.onTokenRefresh || (() => {});
    this.debug = options.debug || false;

    // Token management
    this._controlToken = null;
    this._tokenExpiry = 0;
    this._tokenRefreshPromise = null;
    this._tokenRefreshTimer = null;

    // Request/response interceptors
    this._requestInterceptors = [];
    this._responseInterceptors = [];

    // WebSocket
    this._ws = null;
    this._wsUrl = null;
    this._wsReconnectAttempts = 0;
    this._wsMaxReconnectAttempts = 10;
    this._wsReconnectDelay = 2000;
    this._wsMessageHandlers = new Set();
    this._wsReconnectTimer = null;
    this._wsShouldReconnect = false;
    this._wsToken = null;

    // Default headers
    this._defaultHeaders = {
      'Content-Type': 'application/json',
      'Accept': 'application/json'
    };

    // Bind methods
    this._handleWsOpen = this._handleWsOpen.bind(this);
    this._handleWsMessage = this._handleWsMessage.bind(this);
    this._handleWsClose = this._handleWsClose.bind(this);
    this._handleWsError = this._handleWsError.bind(this);
  }

  /**
   * Normalize base path to ensure consistent format
   * @private
   */
  _normalizeBasePath(path) {
    if (!path) return '';
    // Ensure starts with / and doesn't end with /
    const normalized = path.startsWith('/') ? path : '/' + path;
    return normalized.endsWith('/') ? normalized.slice(0, -1) : normalized;
  }

  /**
   * Build full URL for an endpoint
   * @private
   */
  _buildUrl(endpoint) {
    // Handle absolute URLs
    if (endpoint.startsWith('http://') || endpoint.startsWith('https://')) {
      return endpoint;
    }
    // Ensure endpoint starts with /
    const normalizedEndpoint = endpoint.startsWith('/') ? endpoint : '/' + endpoint;
    return `${this.basePath}${normalizedEndpoint}`;
  }

  /**
   * Get current control token, refreshing if needed
   * @returns {Promise<string>}
   */
  async getToken() {
    const now = Date.now();
    
    // Return cached token if still valid (with margin)
    if (this._controlToken && this._tokenExpiry > now + this.tokenRefreshMargin) {
      return this._controlToken;
    }

    // If refresh already in progress, wait for it
    if (this._tokenRefreshPromise) {
      return this._tokenRefreshPromise;
    }

    // Start token refresh
    this._tokenRefreshPromise = this._refreshToken();
    try {
      const token = await this._tokenRefreshPromise;
      return token;
    } finally {
      this._tokenRefreshPromise = null;
    }
  }

  /**
   * Fetch new control token from backend
   * @private
   */
  async _refreshToken() {
    try {
      const url = this._buildUrl('/api/control/session');
      const res = await fetch(url, {
        method: 'GET',
        headers: this._defaultHeaders,
        credentials: 'include' // Include cookies for session
      });

      if (!res.ok) {
        throw new Error(`Token refresh failed: ${res.status} ${res.statusText}`);
      }

      const data = await res.json();
      
      if (!data.token) {
        throw new Error('No token in response');
      }

      this._controlToken = data.token;
      
      // Calculate expiry from expires_in (seconds) or default to 1 hour
      const expiresIn = data.expires_in ? data.expires_in * 1000 : 3600000;
      this._tokenExpiry = Date.now() + expiresIn;

      // Schedule auto-refresh before expiry
      this._scheduleTokenRefresh(expiresIn);

      this.onTokenRefresh(this._controlToken);
      this._log('Token refreshed, expires in', Math.round(expiresIn / 1000), 'seconds');
      
      return this._controlToken;
    } catch (error) {
      this.onError('Token refresh failed: ' + error.message);
      throw error;
    }
  }

  /**
   * Schedule automatic token refresh
   * @private
   */
  _scheduleTokenRefresh(expiresIn) {
    // Clear existing timer
    if (this._tokenRefreshTimer) {
      clearTimeout(this._tokenRefreshTimer);
    }

    // Refresh at (expiry - margin) or at 50% of lifetime, whichever is sooner
    const refreshAt = Math.min(
      expiresIn - this.tokenRefreshMargin,
      expiresIn * 0.5
    );

    if (refreshAt > 0) {
      this._tokenRefreshTimer = setTimeout(() => {
        this.getToken().catch(err => this.onError('Auto token refresh failed: ' + err.message));
      }, refreshAt);
    }
  }

  /**
   * Add request interceptor
   * @param {Function} interceptor - Function(requestConfig) => requestConfig
   * @returns {Function} - Function to remove the interceptor
   */
  addRequestInterceptor(interceptor) {
    this._requestInterceptors.push(interceptor);
    return () => {
      const idx = this._requestInterceptors.indexOf(interceptor);
      if (idx > -1) this._requestInterceptors.splice(idx, 1);
    };
  }

  /**
   * Add response interceptor
   * @param {Function} interceptor - Function(response, requestConfig) => response
   * @returns {Function} - Function to remove the interceptor
   */
  addResponseInterceptor(interceptor) {
    this._responseInterceptors.push(interceptor);
    return () => {
      const idx = this._responseInterceptors.indexOf(interceptor);
      if (idx > -1) this._responseInterceptors.splice(idx, 1);
    };
  }

  /**
   * Execute request with interceptors, retries, and error handling
   * @param {Object} config - Request configuration
   * @returns {Promise<Response>}
   */
  async request(config) {
    const { method = 'GET', endpoint, body, headers = {}, params, signal, responseType = 'json' } = config;
    
    // Build URL with query params
    let url = this._buildUrl(endpoint);
    if (params) {
      const searchParams = new URLSearchParams();
      for (const [key, value] of Object.entries(params)) {
        if (value !== undefined && value !== null) {
          searchParams.append(key, String(value));
        }
      }
      const query = searchParams.toString();
      if (query) url += '?' + query;
    }

    // Get auth token
    const token = await this.getToken();

    // Prepare request config for interceptors
    let requestConfig = {
      method: method.toUpperCase(),
      url,
      headers: {
        ...this._defaultHeaders,
        ...headers,
        'X-FRIDAY-Control-Token': token
      },
      body: body ? JSON.stringify(body) : undefined,
      signal,
      credentials: 'include'
    };

    // Apply request interceptors
    for (const interceptor of this._requestInterceptors) {
      requestConfig = await interceptor(requestConfig) || requestConfig;
    }

    // Log request
    this._log('Request:', requestConfig.method, requestConfig.url);

    // Execute with retry logic
    let lastError;
    for (let attempt = 0; attempt <= this.maxRetries; attempt++) {
      try {
        const response = await fetch(requestConfig.url, {
          method: requestConfig.method,
          headers: requestConfig.headers,
          body: requestConfig.body,
          signal: requestConfig.signal,
          credentials: requestConfig.credentials
        });

        // Apply response interceptors
        let finalResponse = response;
        for (const interceptor of this._responseInterceptors) {
          finalResponse = await interceptor(finalResponse, requestConfig) || finalResponse;
        }

        // Log response
        this._log('Response:', finalResponse.status, finalResponse.statusText, requestConfig.url);

        // Handle HTTP errors
        if (!finalResponse.ok) {
          const errorData = await finalResponse.clone().json().catch(() => ({}));
          const error = new Error(
            errorData.detail || errorData.error || finalResponse.statusText || 'Request failed'
          );
          error.status = finalResponse.status;
          error.data = errorData;
          error.response = finalResponse;
          
          // Don't retry on client errors (4xx) except 429
          if (finalResponse.status >= 400 && finalResponse.status < 500 && finalResponse.status !== 429) {
            throw error;
          }
          
          throw error;
        }

        // Return appropriate response based on responseType
        switch (responseType) {
          case 'json':
            return finalResponse.json();
          case 'blob':
            return finalResponse.blob();
          case 'text':
            return finalResponse.text();
          case 'arrayBuffer':
            return finalResponse.arrayBuffer();
          default:
            return finalResponse;
        }
      } catch (error) {
        lastError = error;
        
        // Don't retry on abort
        if (error.name === 'AbortError') {
          throw error;
        }

        // Check if we should retry
        const isRetryable = error.status >= 500 || error.status === 429 || !error.status;
        const hasRetriesLeft = attempt < this.maxRetries;
        
        if (isRetryable && hasRetriesLeft) {
          const delay = this.retryDelay * Math.pow(2, attempt) + Math.random() * 100;
          this._log(`Request failed (attempt ${attempt + 1}/${this.maxRetries + 1}), retrying in ${Math.round(delay)}ms:`, error.message);
          await this._sleep(delay);
          continue;
        }
        
        throw error;
      }
    }

    throw lastError;
  }

  /**
   * Sleep utility
   * @private
   */
  _sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  /**
   * Debug logging
   * @private
   */
  _log(...args) {
    if (this.debug) {
      console.log('[FridayAPI]', new Date().toISOString(), ...args);
    }
  }

  /**
   * Initialize the API client (fetch initial token)
   * @returns {Promise<void>}
   */
  async init() {
    this._log('Initializing FridayAPI with basePath:', this.basePath);
    await this.getToken();
    this._log('FridayAPI initialized');
  }

  // ==================== REST API Methods ====================

  /**
   * Submit an autonomous goal
   * @param {string} goal - Goal description
   * @param {number} [priority=5] - Priority (1-10, higher = more important)
   * @returns {Promise<Object>} - Created goal object with goal_id
   */
  async submitGoal(goal, priority = 5) {
    const res = await this.request({
      method: 'POST',
      endpoint: '/api/autonomous/goals',
      body: { goal, priority: Math.max(1, Math.min(10, priority)) }
    });
    return res.json();
  }

  /**
   * Get goal status by ID
   * @param {string} goalId - Goal ID
   * @returns {Promise<Object>} - Goal object with status, steps, summary
   */
  async getGoal(goalId) {
    const res = await this.request({
      method: 'GET',
      endpoint: `/api/autonomous/goals/${encodeURIComponent(goalId)}`
    });
    return res.json();
  }

  /**
   * Get all agents status
   * @returns {Promise<Array>} - Array of agent status objects
   */
  async getAgents() {
    const res = await this.request({
      method: 'GET',
      endpoint: '/api/agents/status'
    });
    return res.json();
  }

  /**
   * Submit a direct command
   * @param {string} command - Command text
   * @returns {Promise<Object>} - Command response with reply
   */
  async submitCommand(command) {
    const res = await this.request({
      method: 'POST',
      endpoint: '/api/command',
      body: { command }
    });
    return res.json();
  }

  /**
   * Speak text using TTS
   * @param {string} text - Text to speak
   * @param {string} [voice='en-IN-NeerjaNeural'] - Voice ID
   * @param {string} [lang='en'] - Language code
   * @returns {Promise<Blob>} - Audio blob
   */
  async speak(text, voice = 'en-IN-NeerjaNeural', lang = 'en') {
    return this.request({
      method: 'POST',
      endpoint: '/api/voice/speak',
      body: { text, voice, lang },
      responseType: 'blob'
    });
  }

  /**
   * Get autonomous daemon status
   * @returns {Promise<Object>} - Daemon status object
   */
  async getDaemonStatus() {
    const res = await this.request({
      method: 'GET',
      endpoint: '/api/autonomous/daemon'
    });
    return res.json();
  }

  // ==================== WebSocket Methods ====================

  /**
   * Connect to WebSocket
   * @param {string} [token] - Optional control token (will fetch if not provided)
   * @returns {Promise<void>}
   */
  async wsConnect(token) {
    // If already connected, return resolved promise
    if (this._ws && this._ws.readyState === WebSocket.OPEN) {
      this._log('WebSocket already connected');
      return Promise.resolve();
    }

    // If connecting, wait for existing connection attempt
    if (this._ws && this._ws.readyState === WebSocket.CONNECTING) {
      this._log('WebSocket connection in progress, waiting...');
      return new Promise((resolve, reject) => {
        const checkConnection = () => {
          if (this._ws.readyState === WebSocket.OPEN) {
            resolve();
          } else if (this._ws.readyState === WebSocket.CLOSED || this._ws.readyState === WebSocket.CLOSING) {
            reject(new Error('WebSocket connection failed'));
          } else {
            setTimeout(checkConnection, 50);
          }
        };
        checkConnection();
      });
    }

    this._wsToken = token || await this.getToken();
    this._wsShouldReconnect = true;
    this._wsReconnectAttempts = 0;

    // Build WebSocket URL (convert http/https to ws/wss)
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    this._wsUrl = `${protocol}//${host}${this.basePath}/ws?token=${encodeURIComponent(this._wsToken)}`;

    this._log('Connecting to WebSocket:', this._wsUrl);

    return new Promise((resolve, reject) => {
      try {
        this._ws = new WebSocket(this._wsUrl);
        
        this._ws.onopen = this._handleWsOpen;
        this._ws.onmessage = this._handleWsMessage;
        this._ws.onclose = this._handleWsClose;
        this._ws.onerror = this._handleWsError;

        // Timeout for connection
        const timeout = setTimeout(() => {
          if (this._ws && this._ws.readyState !== WebSocket.OPEN) {
            this._ws.close();
            reject(new Error('WebSocket connection timeout'));
          }
        }, 10000);

        // One-time wrapper to resolve on first open
        const onOpenWrapper = (event) => {
          clearTimeout(timeout);
          this._ws.onopen = this._handleWsOpen; // Restore original handler
          this._handleWsOpen(event);
          resolve();
        };
        this._ws.onopen = onOpenWrapper;
      } catch (error) {
        reject(error);
      }
    });
  }

  /**
   * WebSocket open handler
   * @private
   */
  _handleWsOpen(event) {
    this._log('WebSocket connected');
    this._wsReconnectAttempts = 0;
    
    // Send initial ping to verify connection
    this._wsSend({ type: 'ping', timestamp: Date.now() });
  }

  /**
   * WebSocket message handler
   * @private
   */
  _handleWsMessage(event) {
    try {
      const data = JSON.parse(event.data);
      this._log('WebSocket message:', data.type || 'unknown');
      
      // Handle pong
      if (data.type === 'pong') {
        return;
      }

      // Dispatch to all message handlers
      for (const handler of this._wsMessageHandlers) {
        try {
          handler(data, this);
        } catch (err) {
          this.onError('WebSocket message handler error: ' + err.message);
        }
      }
    } catch (err) {
      this.onError('WebSocket message parse error: ' + err.message);
    }
  }

  /**
   * WebSocket close handler
   * @private
   */
  _handleWsClose(event) {
    this._log('WebSocket closed:', event.code, event.reason);
    
    if (this._wsShouldReconnect && !event.wasClean) {
      this._scheduleWsReconnect();
    }
  }

  /**
   * WebSocket error handler
   * @private
   */
  _handleWsError(event) {
    this._log('WebSocket error:', event);
    this.onError('WebSocket error occurred');
  }

  /**
   * Schedule WebSocket reconnection with exponential backoff
   * @private
   */
  _scheduleWsReconnect() {
    if (this._wsReconnectTimer) {
      clearTimeout(this._wsReconnectTimer);
    }

    if (this._wsReconnectAttempts >= this._wsMaxReconnectAttempts) {
      this._log('Max reconnection attempts reached');
      this.onError('WebSocket: Max reconnection attempts reached');
      return;
    }

    this._wsReconnectAttempts++;
    const delay = this._wsReconnectDelay * Math.pow(1.5, this._wsReconnectAttempts - 1) + Math.random() * 500;
    
    this._log(`Scheduling WebSocket reconnect (attempt ${this._wsReconnectAttempts}/${this._wsMaxReconnectAttempts}) in ${Math.round(delay)}ms`);

    this._wsReconnectTimer = setTimeout(async () => {
      try {
        // Refresh token before reconnecting
        this._wsToken = await this.getToken();
        await this.wsConnect(this._wsToken);
      } catch (err) {
        this.onError('WebSocket reconnect failed: ' + err.message);
        this._scheduleWsReconnect();
      }
    }, delay);
  }

  /**
   * Send message over WebSocket
   * @param {Object} message - Message object to send
   * @returns {boolean} - True if sent successfully
   */
  _wsSend(message) {
    if (this._ws && this._ws.readyState === WebSocket.OPEN) {
      this._ws.send(JSON.stringify(message));
      return true;
    }
    return false;
  }

  /**
   * Register a WebSocket message handler
   * @param {Function} handler - Function(message, api) => void
   * @returns {Function} - Function to unregister the handler
   */
  onMessage(handler) {
    this._wsMessageHandlers.add(handler);
    return () => {
      this._wsMessageHandlers.delete(handler);
    };
  }

  /**
   * Disconnect WebSocket
   */
  wsDisconnect() {
    this._wsShouldReconnect = false;
    
    if (this._wsReconnectTimer) {
      clearTimeout(this._wsReconnectTimer);
      this._wsReconnectTimer = null;
    }

    if (this._ws) {
      this._ws.onopen = null;
      this._ws.onmessage = null;
      this._ws.onclose = null;
      this._ws.onerror = null;
      
      if (this._ws.readyState === WebSocket.OPEN || this._ws.readyState === WebSocket.CONNECTING) {
        this._ws.close(1000, 'Client disconnect');
      }
      this._ws = null;
    }

    this._wsMessageHandlers.clear();
    this._log('WebSocket disconnected');
  }

  /**
   * Check if WebSocket is connected
   * @returns {boolean}
   */
  isWsConnected() {
    return this._ws && this._ws.readyState === WebSocket.OPEN;
  }

  /**
   * Send a message over WebSocket (public method)
   * @param {Object} message
   * @returns {boolean}
   */
  wsSend(message) {
    return this._wsSend(message);
  }

  // ==================== Cleanup ====================

  /**
   * Destroy the API client and clean up resources
   */
  destroy() {
    // Clear token refresh timer
    if (this._tokenRefreshTimer) {
      clearTimeout(this._tokenRefreshTimer);
      this._tokenRefreshTimer = null;
    }

    // Disconnect WebSocket
    this.wsDisconnect();

    // Clear interceptors
    this._requestInterceptors = [];
    this._responseInterceptors = [];

    // Clear token
    this._controlToken = null;
    this._tokenExpiry = 0;

    this._log('FridayAPI destroyed');
  }
}

// Export for different module systems
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { FridayAPI };
}

if (typeof window !== 'undefined') {
  window.FridayAPI = FridayAPI;
}

// ES6 module export
export { FridayAPI };