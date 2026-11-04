/**
 * FRIDAY 3D Character Component
 * Three.js-based interactive avatar with voice state visualization
 * 
 * States:
 * - idle: mint color, slow rotation
 * - listening: cyan pulse + waveform ring
 * - speaking: violet + lip-sync via shader
 * - thinking: amber rotation with particle focus
 */

import * as THREE from 'three';
import { gsap } from 'gsap';

export class FridayCharacter {
  constructor() {
    // Core Three.js objects
    this.scene = null;
    this.camera = null;
    this.renderer = null;
    this.container = null;
    this.animationId = null;
    
    // Character meshes
    this.coreSphere = null;
    this.coreMaterial = null;
    this.glowMesh = null;
    this.glowMaterial = null;
    this.particleSystem = null;
    this.particleMaterial = null;
    this.particlePositions = null;
    this.particleVelocities = null;
    this.particleSizes = null;
    this.particleColors = null;
    this.waveformRing = null;
    this.waveformMaterial = null;
    
    // State management
    this.currentState = 'idle';
    this.targetState = 'idle';
    this.isTransitioning = false;
    this.audioLevel = 0;
    this.targetAudioLevel = 0;
    this.smoothedAudioLevel = 0;
    
    // Animation parameters
    this.time = 0;
    this.rotationSpeed = 0.15;
    this.particleTime = 0;
    
    // State configurations
    this.stateConfigs = {
      idle: {
        coreColor: new THREE.Color(0x7ee0b5),      // mint
        glowColor: new THREE.Color(0x7ee0b5),
        particleColor: new THREE.Color(0x7ee0b5),
        particleIntensity: 0.3,
        rotationSpeed: 0.15,
        pulseSpeed: 0,
        scale: 1.0,
        glowIntensity: 0.4,
        waveformVisible: false,
        lipSyncAmount: 0
      },
      listening: {
        coreColor: new THREE.Color(0x00ffff),      // cyan
        glowColor: new THREE.Color(0x00ffff),
        particleColor: new THREE.Color(0x00ffff),
        particleIntensity: 0.8,
        rotationSpeed: 0.3,
        pulseSpeed: 2.5,
        scale: 1.05,
        glowIntensity: 0.8,
        waveformVisible: true,
        lipSyncAmount: 0
      },
      speaking: {
        coreColor: new THREE.Color(0xb7a7ff),      // violet
        glowColor: new THREE.Color(0xb7a7ff),
        particleColor: new THREE.Color(0xb7a7ff),
        particleIntensity: 1.0,
        rotationSpeed: 0.2,
        pulseSpeed: 4.0,
        scale: 1.1,
        glowIntensity: 1.0,
        waveformVisible: true,
        lipSyncAmount: 1.0
      },
      thinking: {
        coreColor: new THREE.Color(0xf2c679),      // amber
        glowColor: new THREE.Color(0xf2c679),
        particleColor: new THREE.Color(0xf2c679),
        particleIntensity: 0.5,
        rotationSpeed: 0.5,
        pulseSpeed: 1.0,
        scale: 1.02,
        glowIntensity: 0.6,
        waveformVisible: false,
        lipSyncAmount: 0
      }
    };
    
    // Current interpolated config
    this.currentConfig = { ...this.stateConfigs.idle };
    this.targetConfig = { ...this.stateConfigs.idle };
    
    // Mouse interaction
    this.mouse = new THREE.Vector2(0, 0);
    this.mouseTarget = new THREE.Vector2(0, 0);
    this.mouseInfluence = 0;
    this.maxMouseInfluence = 0.15;
    
    // Lip-sync
    this.lipSyncPhase = 0;
    this.lipSyncTarget = 0;
    
    // Performance
    this.lastFrameTime = 0;
    this.targetFPS = 60;
    this.frameInterval = 1000 / this.targetFPS;
    
    // Resize handler
    this.resizeHandler = this.handleResize.bind(this);
    
    // Reduced motion
    this.prefersReducedMotion = false;
    this.checkReducedMotion();
  }
  
  checkReducedMotion() {
    if (typeof window !== 'undefined') {
      const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
      this.prefersReducedMotion = mediaQuery.matches;
      mediaQuery.addEventListener('change', (e) => {
        this.prefersReducedMotion = e.matches;
      });
    }
  }
  
  /**
   * Initialize the character in a container element
   * @param {HTMLElement} container - DOM element to host the canvas
   */
  async init(container) {
    if (!container) {
      throw new Error('Container element is required');
    }
    
    this.container = container;
    
    // Create scene
    this.scene = new THREE.Scene();
    
    // Create camera
    const aspect = container.clientWidth / container.clientHeight;
    this.camera = new THREE.PerspectiveCamera(45, aspect, 0.1, 100);
    this.camera.position.set(0, 0, 3.5);
    this.camera.lookAt(0, 0, 0);
    
    // Create renderer
    this.renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: true,
      powerPreference: 'high-performance',
      preserveDrawingBuffer: false
    });
    this.renderer.setSize(container.clientWidth, container.clientHeight);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setClearColor(0x000000, 0);
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.2;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    
    container.appendChild(this.renderer.domElement);
    
    // Build character components
    this.createCoreSphere();
    this.createGlow();
    this.createParticleField();
    this.createWaveformRing();
    
    // Add lights
    this.setupLights();
    
    // Event listeners
    window.addEventListener('resize', this.resizeHandler);
    container.addEventListener('mousemove', this.onMouseMove.bind(this));
    container.addEventListener('mouseleave', this.onMouseLeave.bind(this));
    container.addEventListener('mouseenter', this.onMouseEnter.bind(this));
    
    // Start render loop
    this.animate();
    
    // Initial state
    this.setState('idle');
    
    return this;
  }
  
  createCoreSphere() {
    // Main sphere geometry - slightly flattened for "mouth" area
    const geometry = new THREE.SphereGeometry(1, 64, 64);
    
    // Custom shader for core with lip-sync displacement
    this.coreMaterial = new THREE.ShaderMaterial({
      uniforms: {
        uTime: { value: 0 },
        uColor: { value: this.currentConfig.coreColor },
        uGlowColor: { value: this.currentConfig.glowColor },
        uAudioLevel: { value: 0 },
        uLipSync: { value: 0 },
        uPulseSpeed: { value: 0 },
        uState: { value: 0 }, // 0=idle, 1=listening, 2=speaking, 3=thinking
        uMouseInfluence: { value: 0 },
        uMouseDirection: { value: new THREE.Vector2(0, 0) }
      },
      vertexShader: `
        varying vec3 vNormal;
        varying vec3 vPosition;
        varying vec2 vUv;
        uniform float uTime;
        uniform float uAudioLevel;
        uniform float uLipSync;
        uniform float uPulseSpeed;
        uniform float uState;
        uniform float uMouseInfluence;
        uniform vec2 uMouseDirection;
        
        // Simplex noise for organic deformation
        vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
        vec4 mod289(vec4 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
        vec4 permute(vec4 x) { return mod289(((x * 34.0) + 1.0) * x); }
        vec4 taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }
        
        float snoise(vec3 v) {
          const vec2 C = vec2(1.0/6.0, 1.0/3.0);
          const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);
          vec3 i  = floor(v + dot(v, C.yyy));
          vec3 x0 = v - i + dot(i, C.xxx);
          vec3 g = step(x0.yzx, x0.xyz);
          vec3 l = 1.0 - g;
          vec3 i1 = min(g.xyz, l.zxy);
          vec3 i2 = max(g.xyz, l.zxy);
          vec3 x1 = x0 - i1 + C.xxx;
          vec3 x2 = x0 - i2 + C.yyy;
          vec3 x3 = x0 - D.yyy;
          i = mod289(i);
          vec4 p = permute(permute(permute(
            i.z + vec4(0.0, i1.z, i2.z, 1.0))
            + i.y + vec4(0.0, i1.y, i2.y, 1.0))
            + i.x + vec4(0.0, i1.x, i2.x, 1.0));
          float n_ = 1.0/7.0;
          vec3 ns = n_ * D.wyz - D.xzx;
          vec4 j = p - 49.0 * floor(p * ns.z * ns.z);
          vec4 x_ = floor(j * ns.z);
          vec4 y_ = floor(j - 7.0 * x_);
          vec4 x = x_ * ns.x + ns.yyyy;
          vec4 y = y_ * ns.x + ns.yyyy;
          vec4 h = 1.0 - abs(x) - abs(y);
          vec4 b0 = vec4(x.xy, y.xy);
          vec4 b1 = vec4(x.zw, y.zw);
          vec4 s0 = floor(b0) * 2.0 + 1.0;
          vec4 s1 = floor(b1) * 2.0 + 1.0;
          vec4 sh = -step(h, vec4(0.0));
          vec4 a0 = b0.xzyw + s0.xzyw * sh.xxyy;
          vec4 a1 = b1.xzyw + s1.xzyw * sh.zzww;
          vec3 p0 = vec3(a0.xy, h.x);
          vec3 p1 = vec3(a0.zw, h.y);
          vec3 p2 = vec3(a1.xy, h.z);
          vec3 p3 = vec3(a1.zw, h.w);
          vec4 norm = taylorInvSqrt(vec4(dot(p0,p0), dot(p1,p1), dot(p2,p2), dot(p3,p3)));
          p0 *= norm.x; p1 *= norm.y; p2 *= norm.z; p3 *= norm.w;
          vec4 m = max(0.6 - vec4(dot(x0,x0), dot(x1,x1), dot(x2,x2), dot(x3,x3)), 0.0);
          m = m * m;
          return 42.0 * dot(m*m, vec4(dot(p0,x0), dot(p1,x1), dot(p2,x2), dot(p3,x3)));
        }
        
        void main() {
          vNormal = normalize(normalMatrix * normal);
          vPosition = position;
          vUv = uv;
          
          vec3 pos = position;
          float noise = snoise(pos * 0.5 + uTime * 0.3);
          
          // Base breathing animation
          float breath = sin(uTime * 0.8) * 0.02;
          
          // State-specific deformations
          float stateDeform = 0.0;
          float pulse = sin(uTime * uPulseSpeed) * 0.05;
          
          // Lip-sync deformation (mouth opening at bottom of sphere)
          float lipSyncDeform = 0.0;
          if (uLipSync > 0.5) {
            // Mouth area: negative Y (bottom of sphere)
            float mouthMask = smoothstep(-0.3, -0.7, pos.y);
            lipSyncDeform = uLipSync * uAudioLevel * 0.15 * mouthMask;
            pos.y -= lipSyncDeform;
          }
          
          // Waveform ring influence on sphere surface
          float waveformDeform = 0.0;
          if (uState == 1.0 || uState == 2.0) { // listening or speaking
            float ringMask = smoothstep(0.8, 1.0, length(pos.xz));
            waveformDeform = sin(atan(pos.z, pos.x) * 8.0 + uTime * 6.0) * 0.02 * uAudioLevel * ringMask;
          }
          
          // Mouse magnetic attraction
          vec3 mousePull = vec3(uMouseDirection * uMouseInfluence * 0.3, 0.0);
          
          // Combine all deformations
          float totalDeform = noise * 0.015 + breath + pulse + stateDeform + lipSyncDeform + waveformDeform;
          pos = pos * (1.0 + totalDeform) + mousePull;
          
          vec4 mvPosition = modelViewMatrix * vec4(pos, 1.0);
          gl_Position = projectionMatrix * mvPosition;
        }
      `,
      fragmentShader: `
        varying vec3 vNormal;
        varying vec3 vPosition;
        varying vec2 vUv;
        uniform float uTime;
        uniform vec3 uColor;
        uniform vec3 uGlowColor;
        uniform float uAudioLevel;
        uniform float uLipSync;
        uniform float uState;
        uniform float uGlowIntensity;
        
        // Fresnel effect
        float fresnel(vec3 viewDir, vec3 normal, float power) {
          return pow(1.0 - max(dot(viewDir, normal), 0.0), power);
        }
        
        void main() {
          vec3 viewDir = normalize(-vPosition);
          float f = fresnel(viewDir, normalize(vNormal), 3.0);
          
          // Base color with subtle variation
          vec3 baseColor = uColor;
          
          // Add iridescent shift
          float iridescence = sin(vUv.x * 20.0 + uTime) * 0.02;
          baseColor += vec3(iridescence, iridescence * 0.5, -iridescence);
          
          // Audio reactive brightness
          float audioBrightness = 1.0 + uAudioLevel * 0.3;
          baseColor *= audioBrightness;
          
          // Glow from fresnel
          vec3 glow = uGlowColor * f * uGlowIntensity * 0.5;
          
          // Inner glow pulse
          float innerPulse = sin(uTime * 2.0) * 0.1 + 0.9;
          vec3 innerGlow = uGlowColor * (1.0 - f) * 0.15 * innerPulse;
          
          // State-specific effects
          if (uState == 1.0) { // listening - cyan scan lines
            float scan = sin(vUv.y * 40.0 - uTime * 8.0) * 0.5 + 0.5;
            baseColor += uGlowColor * scan * 0.1 * uAudioLevel;
          } else if (uState == 2.0) { // speaking - violet energy
            float energy = sin(vPosition.y * 10.0 + uTime * 10.0) * 0.5 + 0.5;
            baseColor += uGlowColor * energy * 0.15 * uAudioLevel;
          } else if (uState == 3.0) { // thinking - amber rotation trails
            float trail = sin(atan(vPosition.z, vPosition.x) * 3.0 - uTime * 2.0) * 0.5 + 0.5;
            baseColor += uGlowColor * trail * 0.08;
          }
          
          vec3 finalColor = baseColor + glow + innerGlow;
          
          // Metallic sheen
          float metallic = f * 0.3;
          finalColor = mix(finalColor, vec3(1.0), metallic * 0.2);
          
          gl_FragColor = vec4(finalColor, 1.0);
        }
      `,
      transparent: false,
      depthWrite: true
    });
    
    this.coreSphere = new THREE.Mesh(geometry, this.coreMaterial);
    this.coreSphere.castShadow = true;
    this.coreSphere.receiveShadow = true;
    this.scene.add(this.coreSphere);
  }
  
  createGlow() {
    // Outer glow sphere
    const geometry = new THREE.SphereGeometry(1.35, 32, 32);
    
    this.glowMaterial = new THREE.ShaderMaterial({
      uniforms: {
        uTime: { value: 0 },
        uColor: { value: this.currentConfig.glowColor },
        uIntensity: { value: this.currentConfig.glowIntensity },
        uAudioLevel: { value: 0 },
        uPulseSpeed: { value: 0 },
        uState: { value: 0 }
      },
      vertexShader: `
        varying vec3 vNormal;
        varying vec3 vPosition;
        uniform float uTime;
        uniform float uAudioLevel;
        uniform float uPulseSpeed;
        
        void main() {
          vNormal = normalize(normalMatrix * normal);
          vPosition = position;
          
          // Pulsing glow size
          float pulse = sin(uTime * uPulseSpeed) * 0.05 + 1.0;
          float audioPulse = uAudioLevel * 0.15;
          vec3 pos = position * (pulse + audioPulse);
          
          vec4 mvPosition = modelViewMatrix * vec4(pos, 1.0);
          gl_Position = projectionMatrix * mvPosition;
        }
      `,
      fragmentShader: `
        varying vec3 vNormal;
        varying vec3 vPosition;
        uniform float uTime;
        uniform vec3 uColor;
        uniform float uIntensity;
        uniform float uAudioLevel;
        uniform float uState;
        
        void main() {
          vec3 viewDir = normalize(-vPosition);
          float f = pow(1.0 - max(dot(viewDir, vNormal), 0.0), 2.0);
          
          // State-specific glow patterns
          float pattern = 1.0;
          if (uState == 1.0) { // listening - pulsing rings
            pattern = sin(length(vPosition.xz) * 30.0 - uTime * 10.0) * 0.5 + 0.5;
          } else if (uState == 2.0) { // speaking - energy spikes
            pattern = sin(vPosition.y * 20.0 + uTime * 15.0) * 0.5 + 0.5;
          } else if (uState == 3.0) { // thinking - spiral
            pattern = sin(atan(vPosition.z, vPosition.x) * 5.0 - uTime * 3.0) * 0.5 + 0.5;
          }
          
          float alpha = f * uIntensity * (0.5 + pattern * 0.5) * (0.6 + uAudioLevel * 0.4);
          alpha *= smoothstep(0.0, 0.3, f);
          
          gl_FragColor = vec4(uColor, alpha);
        }
      `,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      side: THREE.BackSide
    });
    
    this.glowMesh = new THREE.Mesh(geometry, this.glowMaterial);
    this.scene.add(this.glowMesh);
  }
  
  createParticleField() {
    const particleCount = 5000;
    const geometry = new THREE.BufferGeometry();
    
    this.particlePositions = new Float32Array(particleCount * 3);
    this.particleVelocities = new Float32Array(particleCount * 3);
    this.particleSizes = new Float32Array(particleCount);
    this.particleColors = new Float32Array(particleCount * 3);
    this.particleInitialRadii = new Float32Array(particleCount);
    this.particleInitialAngles = new Float32Array(particleCount * 2);
    this.particlePhases = new Float32Array(particleCount);
    this.particleSpeeds = new Float32Array(particleCount);
    this.particleOrbitSpeeds = new Float32Array(particleCount);
    
    for (let i = 0; i < particleCount; i++) {
      // Spherical distribution with multiple shells
      const shell = Math.floor(i / (particleCount / 4)); // 4 shells
      const baseRadius = 1.5 + shell * 0.4;
      const radiusVariation = (Math.random() - 0.5) * 0.3;
      const radius = baseRadius + radiusVariation;
      
      this.particleInitialRadii[i] = radius;
      
      // Random spherical position
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      
      this.particleInitialAngles[i * 2] = theta;
      this.particleInitialAngles[i * 2 + 1] = phi;
      
      // Initial position
      const x = radius * Math.sin(phi) * Math.cos(theta);
      const y = radius * Math.sin(phi) * Math.sin(theta);
      const z = radius * Math.cos(phi);
      
      this.particlePositions[i * 3] = x;
      this.particlePositions[i * 3 + 1] = y;
      this.particlePositions[i * 3 + 2] = z;
      
      // Orbital velocity
      this.particleOrbitSpeeds[i] = (0.02 + Math.random() * 0.08) * (Math.random() > 0.5 ? 1 : -1);
      this.particleSpeeds[i] = 0.5 + Math.random() * 1.5;
      this.particlePhases[i] = Math.random() * Math.PI * 2;
      
      // Size based on distance (closer = larger)
      this.particleSizes[i] = 2.0 + (2.0 - radius) * 3.0 + Math.random() * 1.5;
      
      // Color will be set by state
      this.particleColors[i * 3] = 0.5;
      this.particleColors[i * 3 + 1] = 0.8;
      this.particleColors[i * 3 + 2] = 0.7;
    }
    
    geometry.setAttribute('position', new THREE.BufferAttribute(this.particlePositions, 3));
    geometry.setAttribute('size', new THREE.BufferAttribute(this.particleSizes, 1));
    geometry.setAttribute('color', new THREE.BufferAttribute(this.particleColors, 3));
    geometry.setAttribute('initialRadius', new THREE.BufferAttribute(this.particleInitialRadii, 1));
    geometry.setAttribute('initialAngles', new THREE.BufferAttribute(this.particleInitialAngles, 2));
    geometry.setAttribute('phase', new THREE.BufferAttribute(this.particlePhases, 1));
    geometry.setAttribute('orbitSpeed', new THREE.BufferAttribute(this.particleOrbitSpeeds, 1));
    geometry.setAttribute('speed', new THREE.BufferAttribute(this.particleSpeeds, 1));
    
    this.particleMaterial = new THREE.ShaderMaterial({
      uniforms: {
        uTime: { value: 0 },
        uColor: { value: this.currentConfig.particleColor },
        uAudioLevel: { value: 0 },
        uIntensity: { value: this.currentConfig.particleIntensity },
        uState: { value: 0 },
        uPixelRatio: { value: this.renderer.getPixelRatio() },
        uMouseInfluence: { value: 0 },
        uMouseDirection: { value: new THREE.Vector2(0, 0) }
      },
      vertexShader: `
        attribute float size;
        attribute vec3 color;
        attribute float initialRadius;
        attribute vec2 initialAngles;
        attribute float phase;
        attribute float orbitSpeed;
        attribute float speed;
        
        varying vec3 vColor;
        varying float vAlpha;
        varying float vSize;
        
        uniform float uTime;
        uniform float uAudioLevel;
        uniform float uIntensity;
        uniform float uState;
        uniform float uPixelRatio;
        uniform float uMouseInfluence;
        uniform vec2 uMouseDirection;
        
        void main() {
          vColor = color;
          
          float theta = initialAngles.x + uTime * orbitSpeed;
          float phi = initialAngles.y + uTime * orbitSpeed * 0.3;
          
          // State-specific motion
          float radius = initialRadius;
          float audioReact = 0.0;
          
          if (uState == 1.0) { // listening - particles pulled inward
            audioReact = uAudioLevel * 0.3;
            radius -= audioReact;
            // Wave motion
            radius += sin(theta * 6.0 + uTime * 4.0) * 0.05 * uAudioLevel;
          } else if (uState == 2.0) { // speaking - explosive outward
            audioReact = uAudioLevel * 0.5;
            radius += audioReact;
            // Energy spikes
            radius += sin(phi * 10.0 + uTime * 8.0) * 0.1 * uAudioLevel;
          } else if (uState == 3.0) { // thinking - spiral convergence
            radius += sin(uTime * 2.0 + phase) * 0.08;
            theta += uTime * 0.1;
          } else { // idle - gentle float
            radius += sin(uTime * speed + phase) * 0.05;
          }
          
          // Mouse attraction
          vec3 mousePull = vec3(uMouseDirection * uMouseInfluence * (2.0 - radius) * 0.5, 0.0);
          
          // Calculate position
          float x = radius * sin(phi) * cos(theta);
          float y = radius * sin(phi) * sin(theta);
          float z = radius * cos(phi);
          
          vec3 pos = vec3(x, y, z) + mousePull;
          
          // Audio-reactive size
          float sizeMult = 1.0 + uAudioLevel * 0.5;
          if (uState == 2.0) sizeMult += uAudioLevel * 0.5; // speaking = bigger
          
          vec4 mvPosition = modelViewMatrix * vec4(pos, 1.0);
          gl_PointSize = size * sizeMult * uIntensity * uPixelRatio * (300.0 / -mvPosition.z);
          gl_Position = projectionMatrix * mvPosition;
          
          // Alpha based on distance and state
          float distFactor = smoothstep(2.5, 1.0, length(pos));
          vAlpha = distFactor * uIntensity * (0.4 + uAudioLevel * 0.4);
          vSize = size * sizeMult;
        }
      `,
      fragmentShader: `
        varying vec3 vColor;
        varying float vAlpha;
        varying float vSize;
        uniform vec3 uColor;
        
        void main() {
          // Circular particle with soft edge
          vec2 center = gl_PointCoord - 0.5;
          float dist = length(center);
          float alpha = smoothstep(0.5, 0.0, dist) * vAlpha;
          
          // Color gradient from center to edge
          vec3 particleColor = mix(uColor, vColor, 0.5);
          
          // Add sparkle
          float sparkle = sin(dist * 50.0) * 0.1 + 0.9;
          particleColor *= sparkle;
          
          gl_FragColor = vec4(particleColor, alpha);
        }
      `,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      vertexColors: true
    });
    
    this.particleSystem = new THREE.Points(geometry, this.particleMaterial);
    this.particleSystem.sortParticles = true;
    this.scene.add(this.particleSystem);
  }
  
  createWaveformRing() {
    // Ring geometry for listening/speaking visualization
    const ringCount = 3;
    const segments = 128;
    
    const positions = new Float32Array(ringCount * segments * 3);
    const uvs = new Float32Array(ringCount * segments * 2);
    const ringIndices = new Float32Array(ringCount * segments);
    
    for (let r = 0; r < ringCount; r++) {
      const radius = 1.15 + r * 0.08;
      for (let i = 0; i < segments; i++) {
        const angle = (i / segments) * Math.PI * 2;
        const idx = (r * segments + i) * 3;
        
        positions[idx] = Math.cos(angle) * radius;
        positions[idx + 1] = Math.sin(angle) * radius;
        positions[idx + 2] = 0;
        
        uvs[(r * segments + i) * 2] = i / segments;
        uvs[(r * segments + i) * 2 + 1] = r / ringCount;
        
        ringIndices[r * segments + i] = r;
      }
    }
    
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('uv', new THREE.BufferAttribute(uvs, 2));
    geometry.setAttribute('ringIndex', new THREE.BufferAttribute(ringIndices, 1));
    
    this.waveformMaterial = new THREE.ShaderMaterial({
      uniforms: {
        uTime: { value: 0 },
        uColor: { value: this.currentConfig.particleColor },
        uAudioLevel: { value: 0 },
        uState: { value: 0 },
        uVisible: { value: 0 }
      },
      vertexShader: `
        attribute float ringIndex;
        varying float vRingIndex;
        varying vec2 vUv;
        uniform float uTime;
        uniform float uAudioLevel;
        uniform float uState;
        
        void main() {
          vRingIndex = ringIndex;
          vUv = uv;
          
          vec3 pos = position;
          
          // Waveform deformation based on audio
          float wave = 0.0;
          if (uState == 1.0) { // listening - smooth waves
            wave = sin(vUv.x * 16.0 + uTime * 4.0) * 0.05 * uAudioLevel;
            wave += sin(vUv.x * 32.0 + uTime * 8.0) * 0.02 * uAudioLevel;
          } else if (uState == 2.0) { // speaking - sharp spikes
            wave = sin(vUv.x * 24.0 + uTime * 12.0) * 0.08 * uAudioLevel;
            wave += sin(vUv.x * 48.0 + uTime * 24.0) * 0.04 * uAudioLevel;
            // Add noise for grit
            wave += sin(vUv.x * 100.0 + uTime * 30.0) * 0.02 * uAudioLevel;
          }
          
          pos.z = wave;
          
          // Pulse scale
          float pulse = 1.0 + sin(uTime * 3.0 + ringIndex * 2.0) * 0.02 * uAudioLevel;
          pos.xy *= pulse;
          
          vec4 mvPosition = modelViewMatrix * vec4(pos, 1.0);
          gl_Position = projectionMatrix * mvPosition;
        }
      `,
      fragmentShader: `
        varying float vRingIndex;
        varying vec2 vUv;
        uniform float uTime;
        uniform vec3 uColor;
        uniform float uAudioLevel;
        uniform float uState;
        uniform float uVisible;
        
        void main() {
          if (uVisible < 0.5) discard;
          
          // Ring intensity varies by ring index (outer = fainter)
          float ringAlpha = 1.0 - vRingIndex * 0.25;
          
          // Audio-reactive brightness
          float brightness = 0.5 + uAudioLevel * 0.8;
          
          // State-specific coloring
          vec3 color = uColor;
          if (uState == 2.0) { // speaking - hotter center
            float heat = 1.0 - vUv.y;
            color = mix(uColor, vec3(1.0, 0.8, 1.0), heat * uAudioLevel * 0.5);
          }
          
          // Soft edges
          float edgeFade = smoothstep(0.0, 0.1, vUv.y) * smoothstep(1.0, 0.9, vUv.y);
          
          float alpha = ringAlpha * brightness * edgeFade * uVisible;
          
          gl_FragColor = vec4(color, alpha);
        }
      `,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      side: THREE.DoubleSide
    });
    
    this.waveformRing = new THREE.Mesh(geometry, this.waveformMaterial);
    this.waveformRing.rotation.x = -Math.PI / 2; // Lay flat
    this.scene.add(this.waveformRing);
  }
  
  setupLights() {
    // Ambient light
    const ambient = new THREE.AmbientLight(0xffffff, 0.3);
    this.scene.add(ambient);
    
    // Main directional light
    const mainLight = new THREE.DirectionalLight(0xffffff, 0.8);
    mainLight.position.set(2, 3, 2);
    this.scene.add(mainLight);
    
    // Rim light
    const rimLight = new THREE.DirectionalLight(0xb7a7ff, 0.4);
    rimLight.position.set(-2, -1, -2);
    this.scene.add(rimLight);
    
    // Accent light (color changes with state)
    this.accentLight = new THREE.PointLight(0x7ee0b5, 0.5, 5);
    this.accentLight.position.set(0, 0, 0);
    this.scene.add(this.accentLight);
  }
  
  /**
   * Set character state with smooth transition
   * @param {'idle'|'listening'|'speaking'|'thinking'} state 
   */
  setState(state) {
    if (!this.stateConfigs[state]) {
      console.warn(`Unknown state: ${state}`);
      return;
    }
    
    if (this.currentState === state && !this.isTransitioning) return;
    
    this.targetState = state;
    this.targetConfig = { ...this.stateConfigs[state] };
    this.isTransitioning = true;
    
    // GSAP transition for smooth interpolation
    const duration = this.prefersReducedMotion ? 0.01 : 0.6;
    
    gsap.to(this.currentConfig, {
      coreColor: this.targetConfig.coreColor,
      glowColor: this.targetConfig.glowColor,
      particleColor: this.targetConfig.particleColor,
      particleIntensity: this.targetConfig.particleIntensity,
      rotationSpeed: this.targetConfig.rotationSpeed,
      pulseSpeed: this.targetConfig.pulseSpeed,
      scale: this.targetConfig.scale,
      glowIntensity: this.targetConfig.glowIntensity,
      waveformVisible: this.targetConfig.waveformVisible ? 1 : 0,
      lipSyncAmount: this.targetConfig.lipSyncAmount,
      duration,
      ease: 'power2.out',
      onUpdate: () => {
        this.updateMaterialUniforms();
      },
      onComplete: () => {
        this.currentState = this.targetState;
        this.isTransitioning = false;
      }
    });
    
    // Scale transition for core sphere
    gsap.to(this.coreSphere.scale, {
      x: this.targetConfig.scale,
      y: this.targetConfig.scale,
      z: this.targetConfig.scale,
      duration,
      ease: 'power2.out'
    });
    
    gsap.to(this.glowMesh.scale, {
      x: this.targetConfig.scale,
      y: this.targetConfig.scale,
      z: this.targetConfig.scale,
      duration,
      ease: 'power2.out'
    });
    
    // Waveform ring visibility
    if (this.targetConfig.waveformVisible) {
      gsap.to(this.waveformMaterial.uniforms.uVisible, {
        value: 1,
        duration: 0.3,
        ease: 'power2.out'
      });
    } else {
      gsap.to(this.waveformMaterial.uniforms.uVisible, {
        value: 0,
        duration: 0.4,
        ease: 'power2.in'
      });
    }
    
    // Accent light color transition
    gsap.to(this.accentLight.color, {
      r: this.targetConfig.glowColor.r,
      g: this.targetConfig.glowColor.g,
      b: this.targetConfig.glowColor.b,
      duration,
      ease: 'power2.out'
    });
  }
  
  updateMaterialUniforms() {
    if (this.coreMaterial) {
      this.coreMaterial.uniforms.uColor.value.copy(this.currentConfig.coreColor);
      this.coreMaterial.uniforms.uGlowColor.value.copy(this.currentConfig.glowColor);
      this.coreMaterial.uniforms.uPulseSpeed.value = this.currentConfig.pulseSpeed;
      this.coreMaterial.uniforms.uLipSync.value = this.currentConfig.lipSyncAmount;
      this.coreMaterial.uniforms.uGlowIntensity.value = this.currentConfig.glowIntensity;
      
      // State as float for shader
      const stateMap = { idle: 0, listening: 1, speaking: 2, thinking: 3 };
      this.coreMaterial.uniforms.uState.value = stateMap[this.currentState] || 0;
    }
    
    if (this.glowMaterial) {
      this.glowMaterial.uniforms.uColor.value.copy(this.currentConfig.glowColor);
      this.glowMaterial.uniforms.uIntensity.value = this.currentConfig.glowIntensity;
      this.glowMaterial.uniforms.uPulseSpeed.value = this.currentConfig.pulseSpeed;
      this.glowMaterial.uniforms.uState.value = stateMap[this.currentState] || 0;
    }
    
    if (this.particleMaterial) {
      this.particleMaterial.uniforms.uColor.value.copy(this.currentConfig.particleColor);
      this.particleMaterial.uniforms.uIntensity.value = this.currentConfig.particleIntensity;
      this.particleMaterial.uniforms.uState.value = stateMap[this.currentState] || 0;
    }
    
    if (this.waveformMaterial) {
      this.waveformMaterial.uniforms.uColor.value.copy(this.currentConfig.particleColor);
      this.waveformMaterial.uniforms.uState.value = stateMap[this.currentState] || 0;
    }
  }
  
  /**
   * Trigger lip-sync with audio amplitude
   * @param {number} amplitude - Audio amplitude (0-1)
   */
  speak(amplitude) {
    this.targetAudioLevel = Math.max(0, Math.min(1, amplitude));
    
    // Only do lip-sync in speaking state
    if (this.currentState === 'speaking') {
      this.lipSyncTarget = this.targetAudioLevel;
    }
  }
  
  /**
   * Update audio level for reactive visualizations
   * @param {number} level - Audio level (0-1)
   */
  updateAudioLevel(level) {
    this.targetAudioLevel = Math.max(0, Math.min(1, level));
  }
  
  onMouseMove(event) {
    if (!this.container) return;
    
    const rect = this.container.getBoundingClientRect();
    this.mouseTarget.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    this.mouseTarget.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    this.mouseInfluence = 1;
  }
  
  onMouseEnter() {
    this.mouseInfluence = 1;
  }
  
  onMouseLeave() {
    this.mouseInfluence = 0;
    this.mouseTarget.set(0, 0);
  }
  
  handleResize() {
    if (!this.container || !this.camera || !this.renderer) return;
    
    const width = this.container.clientWidth;
    const height = this.container.clientHeight;
    
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    
    this.renderer.setSize(width, height);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    
    if (this.particleMaterial) {
      this.particleMaterial.uniforms.uPixelRatio.value = this.renderer.getPixelRatio();
    }
  }
  
  animate(currentTime = 0) {
    this.animationId = requestAnimationFrame(this.animate.bind(this));
    
    // Frame rate limiting for consistent 60fps
    const delta = currentTime - this.lastFrameTime;
    if (delta < this.frameInterval) return;
    this.lastFrameTime = currentTime - (delta % this.frameInterval);
    
    this.time += delta * 0.001;
    this.particleTime += delta * 0.001;
    
    // Smooth audio level interpolation
    this.smoothedAudioLevel += (this.targetAudioLevel - this.smoothedAudioLevel) * 0.15;
    
    // Smooth lip-sync
    this.lipSyncPhase += (this.lipSyncTarget - this.lipSyncPhase) * 0.25;
    
    // Smooth mouse follow
    this.mouse.x += (this.mouseTarget.x - this.mouse.x) * 0.1;
    this.mouse.y += (this.mouseTarget.y - this.mouse.y) * 0.1;
    
    // Update core sphere rotation
    if (this.coreSphere) {
      this.coreSphere.rotation.y += this.currentConfig.rotationSpeed * 0.01;
      this.coreSphere.rotation.x = Math.sin(this.time * 0.3) * 0.05;
    }
    
    // Update glow rotation (opposite direction)
    if (this.glowMesh) {
      this.glowMesh.rotation.y -= this.currentConfig.rotationSpeed * 0.005;
      this.glowMesh.rotation.z = Math.cos(this.time * 0.2) * 0.03;
    }
    
    // Waveform ring rotation
    if (this.waveformRing) {
      this.waveformRing.rotation.z += this.currentConfig.rotationSpeed * 0.008;
    }
    
    // Update shader uniforms
    if (this.coreMaterial) {
      this.coreMaterial.uniforms.uTime.value = this.time;
      this.coreMaterial.uniforms.uAudioLevel.value = this.smoothedAudioLevel;
      this.coreMaterial.uniforms.uLipSync.value = this.lipSyncPhase;
      this.coreMaterial.uniforms.uMouseInfluence.value = this.mouseInfluence * this.maxMouseInfluence;
      this.coreMaterial.uniforms.uMouseDirection.value.set(this.mouse.x, this.mouse.y);
    }
    
    if (this.glowMaterial) {
      this.glowMaterial.uniforms.uTime.value = this.time;
      this.glowMaterial.uniforms.uAudioLevel.value = this.smoothedAudioLevel;
      this.glowMaterial.uniforms.uMouseInfluence.value = this.mouseInfluence * this.maxMouseInfluence;
      this.glowMaterial.uniforms.uMouseDirection.value.set(this.mouse.x, this.mouse.y);
    }
    
    if (this.particleMaterial) {
      this.particleMaterial.uniforms.uTime.value = this.particleTime;
      this.particleMaterial.uniforms.uAudioLevel.value = this.smoothedAudioLevel;
      this.particleMaterial.uniforms.uMouseInfluence.value = this.mouseInfluence * this.maxMouseInfluence;
      this.particleMaterial.uniforms.uMouseDirection.value.set(this.mouse.x, this.mouse.y);
    }
    
    if (this.waveformMaterial) {
      this.waveformMaterial.uniforms.uTime.value = this.time;
      this.waveformMaterial.uniforms.uAudioLevel.value = this.smoothedAudioLevel;
    }
    
    // Accent light pulse
    if (this.accentLight) {
      this.accentLight.intensity = 0.5 + this.smoothedAudioLevel * 0.5 + Math.sin(this.time * 2) * 0.1;
    }
    
    // Render
    if (this.renderer && this.scene && this.camera) {
      this.renderer.render(this.scene, this.camera);
    }
  }
  
  /**
   * Destroy the character and clean up resources
   */
  destroy() {
    // Stop animation loop
    if (this.animationId) {
      cancelAnimationFrame(this.animationId);
      this.animationId = null;
    }
    
    // Remove event listeners
    window.removeEventListener('resize', this.resizeHandler);
    if (this.container) {
      this.container.removeEventListener('mousemove', this.onMouseMove.bind(this));
      this.container.removeEventListener('mouseleave', this.onMouseLeave.bind(this));
      this.container.removeEventListener('mouseenter', this.onMouseEnter.bind(this));
    }
    
    // Kill GSAP animations
    gsap.killTweensOf(this.currentConfig);
    gsap.killTweensOf(this.coreSphere?.scale);
    gsap.killTweensOf(this.glowMesh?.scale);
    gsap.killTweensOf(this.waveformMaterial?.uniforms.uVisible);
    gsap.killTweensOf(this.accentLight?.color);
    
    // Dispose Three.js resources
    if (this.coreSphere) {
      this.coreSphere.geometry.dispose();
      this.coreMaterial.dispose();
      this.scene.remove(this.coreSphere);
    }
    
    if (this.glowMesh) {
      this.glowMesh.geometry.dispose();
      this.glowMaterial.dispose();
      this.scene.remove(this.glowMesh);
    }
    
    if (this.particleSystem) {
      this.particleSystem.geometry.dispose();
      this.particleMaterial.dispose();
      this.scene.remove(this.particleSystem);
    }
    
    if (this.waveformRing) {
      this.waveformRing.geometry.dispose();
      this.waveformMaterial.dispose();
      this.scene.remove(this.waveformRing);
    }
    
    if (this.accentLight) {
      this.scene.remove(this.accentLight);
    }
    
    // Remove renderer from DOM
    if (this.renderer && this.container) {
      this.container.removeChild(this.renderer.domElement);
      this.renderer.dispose();
      this.renderer.forceContextLoss();
    }
    
    // Clear references
    this.scene = null;
    this.camera = null;
    this.renderer = null;
    this.container = null;
    this.coreSphere = null;
    this.coreMaterial = null;
    this.glowMesh = null;
    this.glowMaterial = null;
    this.particleSystem = null;
    this.particleMaterial = null;
    this.waveformRing = null;
    this.waveformMaterial = null;
    this.accentLight = null;
  }
}

// State map for shader uniform
const stateMap = { idle: 0, listening: 1, speaking: 2, thinking: 3 };

export default FridayCharacter;