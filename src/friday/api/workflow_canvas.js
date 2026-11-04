/**
 * FRIDAY Workflow Canvas - Visual n8n-style workflow showing FRIDAY delegating to agents
 * Right slide-in panel with SVG canvas, pan/zoom, mini-map, real-time WebSocket updates
 * Aligned with Stratex Design System (docs/design-system.md)
 */
(function () {
  "use strict";

  const WorkflowCanvas = (function () {
    // ─────────────────────────────────────────────────────────────
    // Configuration & Constants — Design System Tokens
    // ─────────────────────────────────────────────────────────────
    const AGENTS = [
      { id: "friday", label: "FRIDAY", role: "Orchestrator", icon: "⬟", accent: "var(--mint)", isCenter: true },
      { id: "inference", label: "Inference", role: "LLM Gateway", icon: "◈", accent: "var(--cyan)" },
      { id: "memora", label: "Memora", role: "Memory", icon: "◉", accent: "var(--violet)" },
      { id: "stratex", label: "Stratex", role: "Trading", icon: "▲", accent: "var(--warn)" },
      { id: "intelx", label: "IntelX", role: "Threat Intel", icon: "◎", accent: "var(--danger)" },
      { id: "futuris", label: "Futuris", role: "Forecasting", icon: "◇", accent: "#8bd8ff" },
      { id: "cortex", label: "Cortex", role: "Web Ops", icon: "▣", accent: "#a8ff78" },
      { id: "forge", label: "Forge", role: "Code Gen", icon: "⬢", accent: "#ffb347" },
      { id: "sentinel", label: "Sentinel", role: "Security", icon: "⛨", accent: "#ff6b9d" },
      { id: "vyralx", label: "VyralX", role: "Video", icon: "▶", accent: "#c77dff" }
    ];

    const NODE_RADIUS = 48;
    const EDGE_LABEL = "hands context";
    const STATES = {
      idle: { fill: "var(--panel)", stroke: "var(--line)", pulse: false, label: "idle" },
      running: { fill: "rgba(13,33,47,0.95)", stroke: "var(--mint-dim)", pulse: true, label: "running" },
      done: { fill: "rgba(11,27,22,0.95)", stroke: "#2b5f4b", pulse: false, label: "done" },
      failed: { fill: "rgba(26,13,13,0.95)", stroke: "#5c2c2c", pulse: false, label: "failed" }
    };

    const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const EASE = "cubic-bezier(0.16,1,0.3,1)";

    // ─────────────────────────────────────────────────────────────
    // Private State
    // ─────────────────────────────────────────────────────────────
    let container = null;
    let svg = null;
    let g = null;
    let miniMap = null;
    let miniMapG = null;
    let nodes = new Map();
    let edges = new Map();
    let nodePositions = new Map();
    let websocket = null;
    let wsReconnectTimer = null;
    let animationFrameId = null;
    let selectedNode = null;
    let onNodeClickCallback = null;
    let onNodeDetailsCallback = null;
    let panel = null;
    let canvasArea = null;

    // Viewport transform
    let transform = { x: 0, y: 0, k: 1 };
    let isPanning = false;
    let panStart = { x: 0, y: 0 };
    let lastPanTransform = { x: 0, y: 0 };

    // ─────────────────────────────────────────────────────────────
    // Utility Functions
    // ─────────────────────────────────────────────────────────────
    function createSVGElement(tag, attrs = {}) {
      const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
      Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v));
      return el;
    }

    function polarToCartesian(cx, cy, radius, angleDeg) {
      const angleRad = (angleDeg - 90) * Math.PI / 180;
      return { x: cx + radius * Math.cos(angleRad), y: cy + radius * Math.sin(angleRad) };
    }

    function getQuadraticCurvePoint(p0, p1, p2, t) {
      return {
        x: Math.pow(1 - t, 2) * p0.x + 2 * (1 - t) * t * p1.x + Math.pow(t, 2) * p2.x,
        y: Math.pow(1 - t, 2) * p0.y + 2 * (1 - t) * t * p1.y + Math.pow(t, 2) * p2.y
      };
    }

    function getCurveLength(p0, p1, p2, samples = 50) {
      let length = 0;
      let prev = p0;
      for (let i = 1; i <= samples; i++) {
        const t = i / samples;
        const curr = getQuadraticCurvePoint(p0, p1, p2, t);
        length += Math.hypot(curr.x - prev.x, curr.y - prev.y);
        prev = curr;
      }
      return length;
    }

    function getPointAtLength(p0, p1, p2, targetLength, samples = 100) {
      let length = 0;
      let prev = p0;
      for (let i = 1; i <= samples; i++) {
        const t = i / samples;
        const curr = getQuadraticCurvePoint(p0, p1, p2, t);
        const segment = Math.hypot(curr.x - prev.x, curr.y - prev.y);
        if (length + segment >= targetLength) {
          const ratio = (targetLength - length) / segment;
          return {
            x: prev.x + (curr.x - prev.x) * ratio,
            y: prev.y + (curr.y - prev.y) * ratio
          };
        }
        length += segment;
        prev = curr;
      }
      return p2;
    }

    function distance(a, b) {
      return Math.hypot(a.x - b.x, a.y - b.y);
    }

    function clamp(val, min, max) {
      return Math.max(min, Math.min(max, val));
    }

    // ─────────────────────────────────────────────────────────────
    // Layout Calculation
    // ─────────────────────────────────────────────────────────────
    function calculateLayout(containerWidth, containerHeight) {
      const centerX = containerWidth / 2;
      const centerY = containerHeight / 2;
      const positions = new Map();

      // FRIDAY at center
      positions.set("friday", { x: centerX, y: centerY });

      // Other agents in a circle around FRIDAY
      const agentIds = AGENTS.filter(a => !a.isCenter).map(a => a.id);
      const radius = Math.min(containerWidth, containerHeight) * 0.32;
      const angleStep = (2 * Math.PI) / agentIds.length;

      agentIds.forEach((id, i) => {
        const angle = i * angleStep - Math.PI / 2; // Start from top
        positions.set(id, {
          x: centerX + radius * Math.cos(angle),
          y: centerY + radius * Math.sin(angle)
        });
      });

      return positions;
    }

    // ─────────────────────────────────────────────────────────────
    // SVG Construction — Defs with Design System Tokens
    // ─────────────────────────────────────────────────────────────
    function createDefs() {
      const defs = createSVGElement("defs");

      // Gradient for edges — uses design system lime/mint
      const edgeGradient = createSVGElement("linearGradient", { id: "edgeGradient", x1: "0%", y1: "0%", x2: "100%", y2: "0%" });
      edgeGradient.appendChild(createSVGElement("stop", { offset: "0%", "stop-color": "var(--line)" }));
      edgeGradient.appendChild(createSVGElement("stop", { offset: "50%", "stop-color": "var(--mint)" }));
      edgeGradient.appendChild(createSVGElement("stop", { offset: "100%", "stop-color": "var(--line)" }));
      defs.appendChild(edgeGradient);

      // Gradient for running node pulse
      const pulseGradient = createSVGElement("radialGradient", { id: "pulseGradient", cx: "50%", cy: "50%", r: "50%" });
      pulseGradient.appendChild(createSVGElement("stop", { offset: "0%", "stop-color": "rgba(124,240,184,0.4)", "stop-opacity": "0.8" }));
      pulseGradient.appendChild(createSVGElement("stop", { offset: "70%", "stop-color": "rgba(124,240,184,0.1)", "stop-opacity": "0.3" }));
      pulseGradient.appendChild(createSVGElement("stop", { offset: "100%", "stop-color": "rgba(124,240,184,0)", "stop-opacity": "0" }));
      defs.appendChild(pulseGradient);

      // Marker for arrowheads — mint accent
      const marker = createSVGElement("marker", {
        id: "arrowhead",
        markerWidth: "10",
        markerHeight: "7",
        refX: "9",
        refY: "3.5",
        orient: "auto",
        markerUnits: "strokeWidth"
      });
      marker.appendChild(createSVGElement("path", { d: "M0,0 L0,7 L9,3.5 Z", fill: "var(--mint)" }));
      defs.appendChild(marker);

      // Flow animation marker
      const flowMarker = createSVGElement("marker", {
        id: "flowMarker",
        markerWidth: "8",
        markerHeight: "8",
        refX: "4",
        refY: "4",
        orient: "auto",
        markerUnits: "strokeWidth"
      });
      flowMarker.appendChild(createSVGElement("circle", { cx: "4", cy: "4", r: "3.5", fill: "var(--mint)" }));
      defs.appendChild(flowMarker);

      // Mini-map styles
      const minimapStyle = createSVGElement("style", { type: "text/css" });
      minimapStyle.textContent = `
        .minimap-node { cursor: pointer; transition: transform 0.15s ${EASE}; }
        .minimap-node:hover { transform: scale(1.5); }
        .minimap-viewport { fill: rgba(124,240,184,0.15); stroke: var(--mint); stroke-width: 1; }
      `;
      defs.appendChild(minimapStyle);

      // Main canvas styles (injected via style element for reduced-motion support)
      const canvasStyle = createSVGElement("style", { type: "text/css" });
      canvasStyle.textContent = `
        .workflow-node { cursor: pointer; transition: filter 0.2s ${EASE}; }
        .workflow-node:hover .node-bg { stroke-width: 3; }
        .workflow-node:hover .node-accent-ring { opacity: 1; }
        @keyframes pulseRing {
          0% { r: 56; opacity: 0.6; stroke-width: 2; }
          100% { r: 72; opacity: 0; stroke-width: 0.5; }
        }
        .node-pulse-ring { animation: pulseRing 2s ease-out infinite; }
        @media (prefers-reduced-motion: reduce) {
          .node-pulse-ring { animation: none; display: none; }
          .workflow-node { transition: none; }
        }
        .edge-flow { transition: stroke-dashoffset 0.016s linear; }
      `;
      defs.appendChild(canvasStyle);

      return defs;
    }

    function createNodeElement(agent, state = "idle") {
      const pos = nodePositions.get(agent.id) || { x: 0, y: 0 };
      const stateConfig = STATES[state] || STATES.idle;
      const gEl = createSVGElement("g", {
        class: "workflow-node",
        "data-agent-id": agent.id,
        transform: `translate(${pos.x}, ${pos.y})`
      });

      // Pulse ring for running state
      if (stateConfig.pulse && !REDUCED_MOTION) {
        const pulseRing = createSVGElement("circle", {
          class: "node-pulse-ring",
          cx: "0", cy: "0",
          r: NODE_RADIUS + 8,
          fill: "none",
          stroke: agent.accent,
          "stroke-width": "2",
          "stroke-dasharray": "12,12",
          opacity: "0.6"
        });
        pulseRing.style.animation = "pulseRing 2s ease-out infinite";
        gEl.appendChild(pulseRing);
      }

      // Node background circle — uses CSS custom properties
      const bgCircle = createSVGElement("circle", {
        class: "node-bg",
        cx: "0", cy: "0",
        r: NODE_RADIUS,
        fill: stateConfig.fill,
        stroke: stateConfig.stroke,
        "stroke-width": "2.5"
      });
      gEl.appendChild(bgCircle);

      // Inner accent ring
      const accentRing = createSVGElement("circle", {
        class: "node-accent-ring",
        cx: "0", cy: "0",
        r: NODE_RADIUS - 4,
        fill: "none",
        stroke: agent.accent,
        "stroke-width": "1.5",
        opacity: state === "running" ? "1" : "0.4"
      });
      gEl.appendChild(accentRing);

      // Icon
      const icon = createSVGElement("text", {
        x: "0", y: "6",
        "text-anchor": "middle",
        "dominant-baseline": "central",
        "font-size": "28",
        "font-family": "system-ui, sans-serif",
        fill: agent.accent,
        "pointer-events": "none"
      });
      icon.textContent = agent.icon;
      gEl.appendChild(icon);

      // Label
      const label = createSVGElement("text", {
        x: "0", y: NODE_RADIUS + 18,
        "text-anchor": "middle",
        "font-size": "11",
        "font-weight": "600",
        "font-family": "Inter, system-ui, sans-serif",
        fill: "var(--text)",
        "pointer-events": "none"
      });
      label.textContent = agent.label;
      gEl.appendChild(label);

      // Role
      const role = createSVGElement("text", {
        x: "0", y: NODE_RADIUS + 32,
        "text-anchor": "middle",
        "font-size": "9",
        "font-family": "Inter, system-ui, sans-serif",
        fill: "var(--muted)",
        "pointer-events": "none"
      });
      role.textContent = agent.role;
      gEl.appendChild(role);

      // State indicator dot
      const stateDot = createSVGElement("circle", {
        class: "node-state-dot",
        cx: NODE_RADIUS - 8,
        cy: -NODE_RADIUS + 8,
        r: 7,
        fill: stateConfig.stroke
      });
      gEl.appendChild(stateDot);

      // Store reference
      nodes.set(agent.id, { element: gEl, bgCircle, accentRing, stateDot, state });

      return gEl;
    }

    function createEdgeElement(fromId, toId, label = EDGE_LABEL) {
      const fromPos = nodePositions.get(fromId);
      const toPos = nodePositions.get(toId);
      if (!fromPos || !toPos) return null;

      // Calculate control point for curved edge
      const midX = (fromPos.x + toPos.x) / 2;
      const midY = (fromPos.y + toPos.y) / 2;
      const dx = toPos.x - fromPos.x;
      const dy = toPos.y - fromPos.y;
      const dist = Math.hypot(dx, dy);
      const perpX = -dy / dist * 60;
      const perpY = dx / dist * 60;
      const ctrlX = midX + perpX;
      const ctrlY = midY + perpY;

      // Path from node edge to node edge (accounting for radius)
      const fromAngle = Math.atan2(toPos.y - fromPos.y, toPos.x - fromPos.x);
      const toAngle = Math.atan2(fromPos.y - toPos.y, fromPos.x - toPos.x);

      const fromEdge = {
        x: fromPos.x + Math.cos(fromAngle) * NODE_RADIUS,
        y: fromPos.y + Math.sin(fromAngle) * NODE_RADIUS
      };
      const toEdge = {
        x: toPos.x + Math.cos(toAngle) * NODE_RADIUS,
        y: toPos.y + Math.sin(toAngle) * NODE_RADIUS
      };

      const pathD = `M ${fromEdge.x} ${fromEdge.y} Q ${ctrlX} ${ctrlY} ${toEdge.x} ${toEdge.y}`;

      const gEl = createSVGElement("g", { class: "workflow-edge", "data-from": fromId, "data-to": toId });

      // Main path
      const path = createSVGElement("path", {
        class: "edge-path",
        d: pathD,
        fill: "none",
        stroke: "var(--line)",
        "stroke-width": "2.5",
        "stroke-linecap": "round",
        "marker-end": "url(#arrowhead)"
      });
      gEl.appendChild(path);

      // Animated flow path (initially hidden)
      const flowPath = createSVGElement("path", {
        class: "edge-flow",
        d: pathD,
        fill: "none",
        stroke: "url(#edgeGradient)",
        "stroke-width": "3",
        "stroke-linecap": "round",
        "stroke-dasharray": "1000",
        "stroke-dashoffset": "1000",
        opacity: "0",
        "marker-end": "url(#flowMarker)"
      });
      gEl.appendChild(flowPath);

      // Label background
      const labelBg = createSVGElement("rect", {
        class: "edge-label-bg",
        x: midX - 45, y: midY - 14,
        width: 90, height: 20,
        rx: 10,
        fill: "rgba(6,9,13,0.95)",
        stroke: "var(--line)",
        "stroke-width": "1",
        "pointer-events": "none"
      });
      gEl.appendChild(labelBg);

      // Label text
      const labelText = createSVGElement("text", {
        class: "edge-label",
        x: midX, y: midY + 3,
        "text-anchor": "middle",
        "font-size": "9",
        "font-weight": "600",
        "font-family": "Inter, system-ui, sans-serif",
        fill: "var(--mint)",
        "pointer-events": "none",
        "letter-spacing": "0.04em"
      });
      labelText.textContent = label;
      gEl.appendChild(labelText);

      // Store for animation
      edges.set(`${fromId}->${toId}`, {
        element: gEl,
        path,
        flowPath,
        pathD,
        length: getCurveLength(fromEdge, { x: ctrlX, y: ctrlY }, toEdge),
        fromEdge,
        toEdge,
        ctrl: { x: ctrlX, y: ctrlY },
        labelBg,
        labelText,
        animating: false,
        progress: 0
      });

      return gEl;
    }

    function createMiniMap(containerWidth, containerHeight) {
      const scale = 0.12;
      const mmWidth = containerWidth * scale;
      const mmHeight = containerHeight * scale;
      const mmX = containerWidth - mmWidth - 16;
      const mmY = 16;

      const gEl = createSVGElement("g", { class: "minimap", transform: `translate(${mmX}, ${mmY}) scale(${scale})` });

      // Background
      const bg = createSVGElement("rect", {
        x: 0, y: 0, width: containerWidth, height: containerHeight,
        fill: "var(--bg)", stroke: "var(--line)", "stroke-width": "1"
      });
      gEl.appendChild(bg);

      // Viewport indicator
      const viewport = createSVGElement("rect", {
        class: "minimap-viewport",
        x: 0, y: 0, width: containerWidth, height: containerHeight,
        fill: "rgba(124,240,184,0.15)", stroke: "var(--mint)", "stroke-width": "1"
      });
      gEl.appendChild(viewport);

      // Nodes
      AGENTS.forEach(agent => {
        const pos = nodePositions.get(agent.id);
        if (!pos) return;

        const circle = createSVGElement("circle", {
          class: "minimap-node",
          cx: pos.x, cy: pos.y,
          r: agent.isCenter ? 14 : 10,
          fill: agent.isCenter ? "var(--mint)" : "var(--panel)",
          stroke: agent.accent,
          "stroke-width": "1.5",
          "data-agent-id": agent.id
        });
        circle.addEventListener("click", () => centerOnNode(agent.id));
        gEl.appendChild(circle);
      });

      return { element: gEl, viewport, scale, mmX, mmY, mmWidth, mmHeight };
    }

    // ─────────────────────────────────────────────────────────────
    // Animation Loop
    // ─────────────────────────────────────────────────────────────
    let flowAnimationTime = 0;

    function animateFlow() {
      if (REDUCED_MOTION) return;

      flowAnimationTime += 0.016; // ~60fps

      edges.forEach(edge => {
        if (!edge.animating) return;

        edge.progress += 0.008; // Speed of flow
        if (edge.progress >= 1) {
          edge.progress = 0;
        }

        const offset = edge.length * edge.progress;
        const dashoffset = edge.length - offset;

        edge.flowPath.setAttribute("stroke-dashoffset", dashoffset);
        edge.flowPath.setAttribute("opacity", "1");
      });

      // Update mini-map viewport
      if (miniMap && miniMap.viewport) {
        const mmX = -transform.x / transform.k * miniMap.scale;
        const mmY = -transform.y / transform.k * miniMap.scale;
        const mmW = (canvasArea.clientWidth) / transform.k * miniMap.scale;
        const mmH = (canvasArea.clientHeight) / transform.k * miniMap.scale;

        miniMap.viewport.setAttribute("x", mmX);
        miniMap.viewport.setAttribute("y", mmY);
        miniMap.viewport.setAttribute("width", mmW);
        miniMap.viewport.setAttribute("height", mmH);
      }

      animationFrameId = requestAnimationFrame(animateFlow);
    }

    function startFlowAnimation(fromId, toId) {
      const key = `${fromId}->${toId}`;
      const edge = edges.get(key);
      if (edge) {
        edge.animating = true;
        edge.progress = 0;
        edge.flowPath.setAttribute("stroke-dashoffset", edge.length);
        edge.flowPath.setAttribute("opacity", "1");
      }
    }

    function stopFlowAnimation(fromId, toId) {
      const key = `${fromId}->${toId}`;
      const edge = edges.get(key);
      if (edge) {
        edge.animating = false;
        edge.flowPath.setAttribute("opacity", "0");
      }
    }

    function stopAllFlowAnimations() {
      edges.forEach(edge => {
        edge.animating = false;
        edge.flowPath.setAttribute("opacity", "0");
      });
    }

    // ─────────────────────────────────────────────────────────────
    // Viewport Controls (Pan/Zoom)
    // ─────────────────────────────────────────────────────────────
    function applyTransform() {
      if (g) {
        g.setAttribute("transform", `translate(${transform.x}, ${transform.y}) scale(${transform.k})`);
      }
      updateMiniMapViewport();
    }

    function updateMiniMapViewport() {
      if (!miniMap || !canvasArea) return;
      const mmX = -transform.x / transform.k * miniMap.scale;
      const mmY = -transform.y / transform.k * miniMap.scale;
      const mmW = canvasArea.clientWidth / transform.k * miniMap.scale;
      const mmH = canvasArea.clientHeight / transform.k * miniMap.scale;
      miniMap.viewport.setAttribute("x", mmX);
      miniMap.viewport.setAttribute("y", mmY);
      miniMap.viewport.setAttribute("width", mmW);
      miniMap.viewport.setAttribute("height", mmH);
    }

    function zoomTo(scale, centerX, centerY) {
      const newScale = clamp(scale, 0.3, 3);
      const rect = svg.getBoundingClientRect();

      const cx = centerX !== undefined ? centerX : rect.width / 2;
      const cy = centerY !== undefined ? centerY : rect.height / 2;

      const mouseSvgX = (cx - transform.x) / transform.k;
      const mouseSvgY = (cy - transform.y) / transform.k;

      transform.k = newScale;
      transform.x = cx - mouseSvgX * transform.k;
      transform.y = cy - mouseSvgY * transform.k;

      applyTransform();
    }

    function fitView() {
      if (!canvasArea) return;
      const rect = canvasArea.getBoundingClientRect();
      const padding = 60;

      // Calculate bounds of all nodes
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      nodePositions.forEach(pos => {
        minX = Math.min(minX, pos.x - NODE_RADIUS);
        maxX = Math.max(maxX, pos.x + NODE_RADIUS);
        minY = Math.min(minY, pos.y - NODE_RADIUS);
        maxY = Math.max(maxY, pos.y + NODE_RADIUS);
      });

      const contentWidth = maxX - minX;
      const contentHeight = maxY - minY;

      const scaleX = (rect.width - padding * 2) / contentWidth;
      const scaleY = (rect.height - padding * 2) / contentHeight;
      const scale = Math.min(scaleX, scaleY, 1.5);

      const centerX = minX + contentWidth / 2;
      const centerY = minY + contentHeight / 2;

      transform.k = scale;
      transform.x = rect.width / 2 - centerX * scale;
      transform.y = rect.height / 2 - centerY * scale;

      applyTransform();
    }

    function centerOnNode(agentId) {
      const pos = nodePositions.get(agentId);
      if (!pos || !canvasArea) return;

      const rect = canvasArea.getBoundingClientRect();
      const targetScale = Math.min(transform.k, 1.2);

      transform.k = targetScale;
      transform.x = rect.width / 2 - pos.x * targetScale;
      transform.y = rect.height / 2 - pos.y * targetScale;

      applyTransform();
    }

    // ─────────────────────────────────────────────────────────────
    // Event Handlers
    // ─────────────────────────────────────────────────────────────
    function onWheel(e) {
      e.preventDefault();
      const rect = svg.getBoundingClientRect();
      const delta = e.deltaY > 0 ? 0.9 : 1.1;
      zoomTo(transform.k * delta, e.clientX - rect.left, e.clientY - rect.top);
    }

    function onMouseDown(e) {
      if (e.button !== 0) return;
      if (e.target.closest(".workflow-node")) return; // Let node handle click
      if (e.target.closest(".minimap")) return;
      if (e.target.closest(".edge-label")) return;

      isPanning = true;
      panStart = { x: e.clientX, y: e.clientY };
      lastPanTransform = { ...transform };
      svg.style.cursor = "grabbing";
    }

    function onMouseMove(e) {
      if (!isPanning) return;
      const dx = e.clientX - panStart.x;
      const dy = e.clientY - panStart.y;
      transform.x = lastPanTransform.x + dx;
      transform.y = lastPanTransform.y + dy;
      applyTransform();
    }

    function onMouseUp() {
      isPanning = false;
      svg.style.cursor = "";
    }

    function onNodeClick(e) {
      const nodeGroup = e.target.closest(".workflow-node");
      if (!nodeGroup) return;

      const agentId = nodeGroup.getAttribute("data-agent-id");
      if (!agentId) return;

      selectedNode = agentId;
      highlightNode(agentId);

      if (onNodeClickCallback) {
        onNodeClickCallback(agentId);
      }
      if (onNodeDetailsCallback) {
        const agent = AGENTS.find(a => a.id === agentId);
        onNodeDetailsCallback(agentId, agent);
      }
    }

    function highlightNode(agentId) {
      nodes.forEach((node, id) => {
        const isSelected = id === agentId;
        node.element.style.filter = isSelected ? "drop-shadow(0 0 12px rgba(124,240,184,0.6))" : "none";
        node.element.style.zIndex = isSelected ? "10" : "1";
      });
    }

    function onKeyDown(e) {
      if (e.key === "Escape") {
        selectedNode = null;
        highlightNode(null);
      }
      if (e.key === "0" || e.key === "f") {
        fitView();
      }
      if (e.key === "+" || e.key === "=") {
        zoomTo(transform.k * 1.2);
      }
      if (e.key === "-") {
        zoomTo(transform.k / 1.2);
      }
    }

    // ─────────────────────────────────────────────────────────────
    // WebSocket Connection
    // ─────────────────────────────────────────────────────────────
    function connectWebSocket() {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const wsUrl = `${protocol}//${window.location.host}/friday/ws/workflow`;

      try {
        websocket = new WebSocket(wsUrl);

        websocket.onopen = () => {
          console.log("[WorkflowCanvas] WebSocket connected");
          clearTimeout(wsReconnectTimer);
        };

        websocket.onmessage = (event) => {
          try {
            const msg = JSON.parse(event.data);
            handleWebSocketMessage(msg);
          } catch (e) {
            console.warn("[WorkflowCanvas] Invalid WS message:", e);
          }
        };

        websocket.onclose = () => {
          console.log("[WorkflowCanvas] WebSocket disconnected, reconnecting...");
          wsReconnectTimer = setTimeout(connectWebSocket, 3000);
        };

        websocket.onerror = (err) => {
          console.error("[WorkflowCanvas] WebSocket error:", err);
        };
      } catch (e) {
        console.error("[WorkflowCanvas] Failed to create WebSocket:", e);
        wsReconnectTimer = setTimeout(connectWebSocket, 5000);
      }
    }

    function handleWebSocketMessage(msg) {
      switch (msg.type) {
        case "node_state":
          updateNodeState(msg.agentId, msg.state, false);
          break;
        case "edge_flow_start":
          startFlowAnimation(msg.from, msg.to);
          break;
        case "edge_flow_stop":
          stopFlowAnimation(msg.from, msg.to);
          break;
        case "mission_start":
          // Reset all to idle, set friday to running
          AGENTS.forEach(a => updateNodeState(a.id, "idle", false));
          updateNodeState("friday", "running", false);
          break;
        case "mission_step":
          // from agent hands off to next agent
          if (msg.from && msg.to) {
            startFlowAnimation(msg.from, msg.to);
            updateNodeState(msg.to, "running", false);
            updateNodeState(msg.from, "done", false);
          }
          break;
        case "mission_complete":
          stopAllFlowAnimations();
          updateNodeState("friday", "done", false);
          break;
        case "mission_failed":
          stopAllFlowAnimations();
          if (msg.agentId) updateNodeState(msg.agentId, "failed", false);
          updateNodeState("friday", "failed", false);
          break;
        case "full_state":
          // Initial state sync
          if (msg.nodes) {
            Object.entries(msg.nodes).forEach(([id, state]) => updateNodeState(id, state, false));
          }
          break;
      }
    }

    function sendWebSocketMessage(msg) {
      if (websocket && websocket.readyState === WebSocket.OPEN) {
        websocket.send(JSON.stringify(msg));
      }
    }

    // ─────────────────────────────────────────────────────────────
    // Panel Construction — Design System Compliant
    // ─────────────────────────────────────────────────────────────
    function buildPanel() {
      const panelEl = document.createElement("div");
      panelEl.className = "workflow-canvas-panel";
      panelEl.setAttribute("role", "dialog");
      panelEl.setAttribute("aria-modal", "true");
      panelEl.setAttribute("aria-label", "Workflow Canvas");

      panelEl.innerHTML = `
        <style>
          .workflow-canvas-panel {
            position: fixed;
            top: 0; right: 0; bottom: 0;
            width: 100%;
            max-width: 480px;
            min-width: 320px;
            background: linear-gradient(180deg, var(--panel), var(--bg));
            border-left: 1px solid var(--line);
            box-shadow: -30px 0 70px rgba(0,0,0,0.5);
            z-index: 90;
            display: flex;
            flex-direction: column;
            transform: translateX(100%);
            transition: transform 0.32s ${EASE};
            font-family: Inter, system-ui, sans-serif;
          }
          .workflow-canvas-panel.open { transform: none; }
          .workflow-canvas-header {
            display: flex; align-items: center; justify-content: space-between;
            padding: 16px 18px; border-bottom: 1px solid var(--line);
            background: rgba(255,255,255,0.012);
            flex-shrink: 0;
          }
          .workflow-canvas-title { display: flex; align-items: center; gap: 10px; }
          .workflow-canvas-title h3 { margin: 0; font-size: 15px; font-weight: 650; letter-spacing: -0.02em; }
          .workflow-canvas-title .icon { width: 32px; height: 32px; border-radius: 8px; display: grid; place-items: center;
            border: 1px solid var(--mint-dim); background: var(--panel); color: var(--mint); font-size: 14px; font-weight: 800; }
          .workflow-canvas-controls { display: flex; gap: 6px; }
          .workflow-canvas-btn {
            border: 1px solid var(--line); background: var(--panel); color: var(--muted);
            padding: 6px 10px; border-radius: 8px; font-size: 11px; cursor: pointer;
            transition: all 0.16s ${EASE}; display: flex; align-items: center; gap: 4px;
          }
          .workflow-canvas-btn:hover { color: var(--mint); border-color: var(--mint-dim); background: var(--panel-2); }
          .workflow-canvas-btn:focus-visible { outline: 2px solid var(--mint); outline-offset: 2px; }
          .workflow-canvas-btn svg { width: 14px; height: 14px; }
          .workflow-canvas-canvas { flex: 1; position: relative; overflow: hidden; }
          .workflow-canvas-canvas svg { width: 100%; height: 100%; display: block; cursor: grab; }
          .workflow-canvas-canvas svg:active { cursor: grabbing; }
        </style>
        <div class="workflow-canvas-header">
          <div class="workflow-canvas-title">
            <span class="icon" aria-hidden="true">⬟</span>
            <h3>Workflow Canvas</h3>
          </div>
          <div class="workflow-canvas-controls">
            <button class="workflow-canvas-btn" data-action="fit" title="Fit View (F)" aria-label="Fit view">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M3 3h18v18H3z"/><path d="M7 7h10v10H7z"/></svg>
            </button>
            <button class="workflow-canvas-btn" data-action="zoom-in" title="Zoom In (+)" aria-label="Zoom in">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/><path d="M11 8v6"/><path d="M8 11h6"/></svg>
            </button>
            <button class="workflow-canvas-btn" data-action="zoom-out" title="Zoom Out (-)" aria-label="Zoom out">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/><path d="M8 11h6"/></svg>
            </button>
            <button class="workflow-canvas-btn" data-action="close" title="Close (Esc)" aria-label="Close workflow canvas">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M18 6L6 18M6 6l12 12"/></svg>
            </button>
          </div>
        </div>
        <div class="workflow-canvas-canvas" id="workflowCanvasArea"></div>
      `;

      return panelEl;
    }

    // ─────────────────────────────────────────────────────────────
    // Public API
    // ─────────────────────────────────────────────────────────────
    function init(targetContainer, options = {}) {
      container = typeof targetContainer === "string"
        ? document.querySelector(targetContainer)
        : targetContainer;

      if (!container) {
        console.error("[WorkflowCanvas] Container not found");
        return;
      }

      onNodeClickCallback = options.onNodeClick || null;
      onNodeDetailsCallback = options.onNodeDetails || null;

      // Build and attach panel
      panel = buildPanel();
      document.body.appendChild(panel);

      canvasArea = panel.querySelector("#workflowCanvasArea");
      const rect = canvasArea.getBoundingClientRect();

      // Create SVG
      svg = createSVGElement("svg", {
        viewBox: `0 0 ${canvasArea.clientWidth} ${canvasArea.clientHeight}`,
        preserveAspectRatio: "none",
        style: "width: 100%; height: 100%;"
      });
      svg.setAttribute("xmlns", "http://www.w3.org/2000/svg");
      canvasArea.appendChild(svg);

      // Add defs
      svg.appendChild(createDefs());

      // Main group for transform
      g = createSVGElement("g", { class: "workflow-main" });
      svg.appendChild(g);

      // Calculate initial layout
      nodePositions = calculateLayout(canvasArea.clientWidth, canvasArea.clientHeight);

      // Create edges first (so they're behind nodes)
      const edgeLayer = createSVGElement("g", { class: "edge-layer" });
      g.appendChild(edgeLayer);

      AGENTS.forEach(agent => {
        if (agent.id !== "friday") {
          createEdgeElement("friday", agent.id, EDGE_LABEL);
          edgeLayer.appendChild(edges.get(`friday->${agent.id}`).element);
        }
      });

      // Create nodes
      const nodeLayer = createSVGElement("g", { class: "node-layer" });
      g.appendChild(nodeLayer);

      AGENTS.forEach(agent => {
        const nodeEl = createNodeElement(agent, "idle");
        nodeLayer.appendChild(nodeEl);
        nodeEl.addEventListener("click", onNodeClick);
      });

      // Create mini-map
      miniMap = createMiniMap(canvasArea.clientWidth, canvasArea.clientHeight);
      g.appendChild(miniMap.element);

      // Event listeners
      svg.addEventListener("wheel", onWheel, { passive: false });
      svg.addEventListener("mousedown", onMouseDown);
      window.addEventListener("mousemove", onMouseMove);
      window.addEventListener("mouseup", onMouseUp);
      window.addEventListener("keydown", onKeyDown);

      // Control buttons
      panel.querySelector('[data-action="fit"]').addEventListener("click", fitView);
      panel.querySelector('[data-action="zoom-in"]').addEventListener("click", () => zoomTo(transform.k * 1.2));
      panel.querySelector('[data-action="zoom-out"]').addEventListener("click", () => zoomTo(transform.k / 1.2));
      panel.querySelector('[data-action="close"]').addEventListener("click", () => close());

      // Handle resize
      const resizeObserver = new ResizeObserver(() => {
        const w = canvasArea.clientWidth;
        const h = canvasArea.clientHeight;
        svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
        // Recalculate layout on significant resize
        nodePositions = calculateLayout(w, h);
        rebuild();
      });
      resizeObserver.observe(canvasArea);

      // Initial fit
      setTimeout(fitView, 100);

      // Start animation loop
      if (!REDUCED_MOTION) {
        animateFlow();
      }

      // Connect WebSocket
      connectWebSocket();

      // Store reference for cleanup
      panel._workflowCanvas = {
        panel, svg, g, nodes, edges, nodePositions, transform,
        destroy: () => destroy()
      };

      return panel;
    }

    function rebuild() {
      // Rebuild edges
      const edgeLayer = g.querySelector(".edge-layer");
      if (edgeLayer) {
        edgeLayer.innerHTML = "";
        AGENTS.forEach(agent => {
          if (agent.id !== "friday") {
            createEdgeElement("friday", agent.id, EDGE_LABEL);
            edgeLayer.appendChild(edges.get(`friday->${agent.id}`).element);
          }
        });
      }

      // Rebuild nodes
      const nodeLayer = g.querySelector(".node-layer");
      if (nodeLayer) {
        nodeLayer.innerHTML = "";
        AGENTS.forEach(agent => {
          const pos = nodePositions.get(agent.id);
          const nodeData = nodes.get(agent.id);
          if (nodeData && pos) {
            nodeData.element.setAttribute("transform", `translate(${pos.x}, ${pos.y})`);
            nodeLayer.appendChild(nodeData.element);
          }
        });
      }

      // Rebuild mini-map
      const oldMinimap = g.querySelector(".minimap");
      if (oldMinimap) oldMinimap.remove();
      miniMap = createMiniMap(canvasArea.clientWidth, canvasArea.clientHeight);
      g.appendChild(miniMap.element);

      fitView();
    }

    function open() {
      if (panel) {
        panel.classList.add("open");
        document.body.style.overflow = "hidden";
        setTimeout(fitView, 100);
      }
    }

    function close() {
      if (panel) {
        panel.classList.remove("open");
        document.body.style.overflow = "";
      }
    }

    function toggle() {
      if (panel) {
        panel.classList.toggle("open");
        if (panel.classList.contains("open")) {
          document.body.style.overflow = "hidden";
          setTimeout(fitView, 100);
        } else {
          document.body.style.overflow = "";
        }
      }
    }

    function addNode(agentId, position) {
      const agent = AGENTS.find(a => a.id === agentId);
      if (!agent) return;

      nodePositions.set(agentId, position);
      const nodeEl = createNodeElement(agent, "idle");
      const nodeLayer = g.querySelector(".node-layer");
      if (nodeLayer) {
        nodeEl.addEventListener("click", onNodeClick);
        nodeLayer.appendChild(nodeEl);
      }
      nodes.set(agentId, { ...nodes.get(agentId), element: nodeEl });
    }

    function addEdge(fromId, toId, label = EDGE_LABEL) {
      createEdgeElement(fromId, toId, label);
      const edgeLayer = g.querySelector(".edge-layer");
      const edge = edges.get(`${fromId}->${toId}`);
      if (edgeLayer && edge) {
        edgeLayer.appendChild(edge.element);
      }
    }

    function updateNodeState(agentId, state, broadcast = true) {
      const nodeData = nodes.get(agentId);
      if (!nodeData) return;

      const stateConfig = STATES[state] || STATES.idle;
      nodeData.state = state;

      // Update visual elements
      nodeData.bgCircle.setAttribute("fill", stateConfig.fill);
      nodeData.bgCircle.setAttribute("stroke", stateConfig.stroke);
      nodeData.stateDot.setAttribute("fill", stateConfig.stroke);

      // Handle pulse ring
      const pulseRing = nodeData.element.querySelector(".node-pulse-ring");
      if (stateConfig.pulse) {
        if (!pulseRing && !REDUCED_MOTION) {
          const agent = AGENTS.find(a => a.id === agentId);
          const newPulse = createSVGElement("circle", {
            class: "node-pulse-ring",
            cx: "0", cy: "0",
            r: NODE_RADIUS + 8,
            fill: "none",
            stroke: agent?.accent || "var(--mint)",
            "stroke-width": "2",
            "stroke-dasharray": "12,12",
            opacity: "0.6"
          });
          newPulse.style.animation = "pulseRing 2s ease-out infinite";
          nodeData.element.insertBefore(newPulse, nodeData.bgCircle);
        }
      } else if (pulseRing) {
        pulseRing.remove();
      }

      // Update accent ring opacity
      nodeData.accentRing.setAttribute("opacity", state === "running" ? "1" : "0.4");

      // Broadcast to WebSocket
      if (broadcast) {
        sendWebSocketMessage({ type: "node_state", agentId, state });
      }
    }

    function getNodeState(agentId) {
      const nodeData = nodes.get(agentId);
      return nodeData ? nodeData.state : "idle";
    }

    function setOnNodeClick(callback) {
      onNodeClickCallback = callback;
    }

    function setOnNodeDetails(callback) {
      onNodeDetailsCallback = callback;
    }

    function destroy() {
      // Stop animation
      if (animationFrameId) cancelAnimationFrame(animationFrameId);

      // Close WebSocket
      if (websocket) {
        websocket.close();
        websocket = null;
      }
      clearTimeout(wsReconnectTimer);

      // Remove event listeners
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
      window.removeEventListener("keydown", onKeyDown);
      if (svg) {
        svg.removeEventListener("wheel", onWheel);
        svg.removeEventListener("mousedown", onMouseDown);
      }

      // Remove panel
      if (panel) panel.remove();

      // Clear state
      nodes.clear();
      edges.clear();
      nodePositions.clear();
      container = null;
      svg = null;
      g = null;
      miniMap = null;
      panel = null;
      canvasArea = null;
    }

    // ─────────────────────────────────────────────────────────────
    // Expose Public API
    // ─────────────────────────────────────────────────────────────
    return {
      init,
      open,
      close,
      toggle,
      addNode,
      addEdge,
      updateNodeState,
      getNodeState,
      fitView,
      centerOnNode,
      zoomTo,
      setOnNodeClick,
      setOnNodeDetails,
      destroy,
      // Expose internals for advanced use
      _internals: {
        get nodes() { return nodes; },
        get edges() { return edges; },
        get transform() { return transform; },
        get nodePositions() { return nodePositions; },
        AGENTS
      }
    };
  })();

  // Export for module systems
  if (typeof module !== "undefined" && module.exports) {
    module.exports = WorkflowCanvas;
  }

  // Global for browser
  window.WorkflowCanvas = WorkflowCanvas;
})();