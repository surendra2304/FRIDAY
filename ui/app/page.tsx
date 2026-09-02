"use client";

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { HandLandmarker, FilesetResolver } from "@mediapipe/tasks-vision";

export default function UltronUI() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [status, setStatus] = useState("INITIALIZING FRIDAY PROTOCOL...");
  const [gesture, setGesture] = useState("None");
  const wsRef = useRef<WebSocket | null>(null);

  // Shared ref bridging real-time camera hand tracking with the 3D WebGL renderer
  const handStateRef = useRef({
    detected: false,
    x: 0.5,
    y: 0.5,
    isPinching: false,
    isOpen: false,
    gestureName: "None",
  });

  // Initialize WebGL Holographic Orb
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });

    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

    // Outer Holographic Sphere (Cyan Wireframe)
    const outerGeo = new THREE.IcosahedronGeometry(2.2, 3);
    const outerMat = new THREE.MeshBasicMaterial({
      color: 0x00ffff,
      wireframe: true,
      transparent: true,
      opacity: 0.85,
    });
    const outerOrb = new THREE.Mesh(outerGeo, outerMat);
    scene.add(outerOrb);

    // Inner Counter-Rotating Holographic Sphere (Deep Blue / Teal)
    const innerGeo = new THREE.IcosahedronGeometry(1.6, 2);
    const innerMat = new THREE.MeshBasicMaterial({
      color: 0x0088ff,
      wireframe: true,
      transparent: true,
      opacity: 0.70,
    });
    const innerOrb = new THREE.Mesh(innerGeo, innerMat);
    scene.add(innerOrb);

    // Central Glowing Geometric Core
    const coreGeo = new THREE.SphereGeometry(0.75, 16, 16);
    const coreMat = new THREE.MeshBasicMaterial({
      color: 0x88ffff,
      wireframe: true,
      transparent: true,
      opacity: 0.50,
    });
    const coreOrb = new THREE.Mesh(coreGeo, coreMat);
    scene.add(coreOrb);

    camera.position.z = 5;

    let frameId: number;
    let running = true;

    const animate = () => {
      if (!running) return;

      const now = performance.now() * 0.001;
      const hand = handStateRef.current;

      if (hand.detected) {
        // Hand coordinates: (0, 0) top-left, (1, 1) bottom-right
        // Target 3D coordinates: X [-4, +4], Y [-3, +3]
        const targetX = (hand.x - 0.5) * 5.5;
        const targetY = -(hand.y - 0.5) * 4.0;

        // Smoothly glide the entire holographic orb towards your hand!
        outerOrb.position.x += (targetX - outerOrb.position.x) * 0.12;
        outerOrb.position.y += (targetY - outerOrb.position.y) * 0.12;
        innerOrb.position.x = outerOrb.position.x;
        innerOrb.position.y = outerOrb.position.y;
        coreOrb.position.x = outerOrb.position.x;
        coreOrb.position.y = outerOrb.position.y;

        // Tilt dynamically towards hand angle
        outerOrb.rotation.y += (targetX * 0.4 - outerOrb.rotation.y) * 0.1 + 0.025;
        outerOrb.rotation.x += (-targetY * 0.4 - outerOrb.rotation.x) * 0.1 + 0.020;
        innerOrb.rotation.y -= 0.035;
        innerOrb.rotation.x -= 0.025;
        coreOrb.rotation.y += 0.045;

        // Hand Gesture Reactions:
        // Open Palm = Expand & energize (1.4x)
        // Pinch = Compress & concentrate (0.65x)
        const targetScale = hand.isOpen ? 1.4 : (hand.isPinching ? 0.65 : 1.05);
        const pulse = (1 + Math.sin(now * 5) * 0.07) * targetScale;
        outerOrb.scale.set(pulse, pulse, pulse);
        innerOrb.scale.set(1.1 / pulse, 1.1 / pulse, 1.1 / pulse);
        coreOrb.scale.set(pulse * 0.8, pulse * 0.8, pulse * 0.8);
      } else {
        // No hand in frame: glide smoothly back to center
        outerOrb.position.x += (0 - outerOrb.position.x) * 0.06;
        outerOrb.position.y += (0 - outerOrb.position.y) * 0.06;
        innerOrb.position.x = outerOrb.position.x;
        innerOrb.position.y = outerOrb.position.y;
        coreOrb.position.x = outerOrb.position.x;
        coreOrb.position.y = outerOrb.position.y;

        outerOrb.rotation.x += 0.015;
        outerOrb.rotation.y += 0.020;
        innerOrb.rotation.x -= 0.022;
        innerOrb.rotation.y -= 0.018;
        coreOrb.rotation.y += 0.030;

        const pulse = 1 + Math.sin(now * 3) * 0.08;
        outerOrb.scale.set(pulse, pulse, pulse);
        innerOrb.scale.set(1.05 / pulse, 1.05 / pulse, 1.05 / pulse);
        coreOrb.scale.set(0.7, 0.7, 0.7);
      }

      renderer.render(scene, camera);
      frameId = requestAnimationFrame(animate);
    };

    frameId = requestAnimationFrame(animate);

    const handleResize = () => {
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
    };
    window.addEventListener("resize", handleResize);

    return () => {
      running = false;
      cancelAnimationFrame(frameId);
      window.removeEventListener("resize", handleResize);
      renderer.dispose();
      outerGeo.dispose();
      outerMat.dispose();
      innerGeo.dispose();
      innerMat.dispose();
      coreGeo.dispose();
      coreMat.dispose();
    };
  }, []);

  // Initialize WebSocket for real-time backend coordination
  useEffect(() => {
    const ws = new WebSocket("ws://127.0.0.1:8001/api/ws/voice");
    ws.onopen = () => {
      setStatus("SYSTEM ONLINE");
    };
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === "status") {
        setStatus(data.message);
      }
    };
    ws.onclose = () => {
      setStatus("CONNECTION LOST");
    };
    wsRef.current = ws;

    return () => {
      ws.close();
    };
  }, []);

  // Initialize MediaPipe Hand Landmark Detection
  useEffect(() => {
    let handLandmarker: HandLandmarker | null = null;
    let animationFrameId: number;
    let active = true;

    const initializeMediaPipe = async () => {
      try {
        const vision = await FilesetResolver.forVisionTasks(
          "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.3/wasm"
        );
        if (!active) return;
        
        handLandmarker = await HandLandmarker.createFromOptions(vision, {
          baseOptions: {
            modelAssetPath: "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task",
            delegate: "GPU",
          },
          runningMode: "VIDEO",
          numHands: 1,
        });

        // Request Webcam Stream
        if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
          const stream = await navigator.mediaDevices.getUserMedia({
            video: { width: 640, height: 480 },
          });
          if (!active) return;

          if (videoRef.current) {
            videoRef.current.srcObject = stream;
            videoRef.current.onloadeddata = () => {
              if (active) predictWebcam();
            };
            if (videoRef.current.readyState >= 2) {
              predictWebcam();
            }
          }
        }
      } catch (err) {
        console.error("MediaPipe initialization failed:", err);
      }
    };

    let lastVideoTime = -1;
    let lastGestureTime = 0;

    const predictWebcam = () => {
      if (!active) return;

      if (videoRef.current && handLandmarker && videoRef.current.readyState >= 2) {
        const startTimeMs = performance.now();
        if (lastVideoTime !== videoRef.current.currentTime) {
          lastVideoTime = videoRef.current.currentTime;
          try {
            const results = handLandmarker.detectForVideo(videoRef.current, startTimeMs);
            if (results && results.landmarks && results.landmarks.length > 0) {
              const landmarks = results.landmarks[0];
              const wrist = landmarks[0];
              const thumbTip = landmarks[4];
              const indexTip = landmarks[8];
              const middleTip = landmarks[12];

              // Mirror X so natural hand movement matches the screen
              const handX = 1 - indexTip.x;
              const handY = indexTip.y;

              // Detect Pinch (Distance between Thumb Tip and Index Tip)
              const pinchDist = Math.hypot(thumbTip.x - indexTip.x, thumbTip.y - indexTip.y);
              const isPinching = pinchDist < 0.08;

              // Detect Open Palm (Distance between Wrist and Middle Tip)
              const handSpan = Math.hypot(middleTip.x - wrist.x, middleTip.y - wrist.y);
              const isOpen = handSpan > 0.36;

              let currentGesture = "Tracking Hand";
              if (isPinching) {
                currentGesture = "Pinch (Compressing)";
              } else if (isOpen) {
                currentGesture = "Open Palm (Expanding)";
              }

              // Swipe Gestures: Left side of camera frame vs Right side
              const now = Date.now();
              if (now - lastGestureTime > 2000) {
                if (handX < 0.22) {
                  currentGesture = "Swipe Left ➔ Notepad";
                  lastGestureTime = now;
                  if (wsRef.current?.readyState === WebSocket.OPEN) {
                    wsRef.current.send(JSON.stringify({ type: "gesture", gesture: "swipe_left" }));
                  }
                } else if (handX > 0.78) {
                  currentGesture = "Swipe Right ➔ Chrome";
                  lastGestureTime = now;
                  if (wsRef.current?.readyState === WebSocket.OPEN) {
                    wsRef.current.send(JSON.stringify({ type: "gesture", gesture: "swipe_right" }));
                  }
                }
              }

              handStateRef.current = {
                detected: true,
                x: handX,
                y: handY,
                isPinching,
                isOpen,
                gestureName: currentGesture,
              };
              setGesture(currentGesture);
            } else {
              handStateRef.current.detected = false;
              setGesture("None");
            }
          } catch (e) {
            console.error("detectForVideo error:", e);
          }
        }
      }
      animationFrameId = window.requestAnimationFrame(predictWebcam);
    };

    initializeMediaPipe();

    return () => {
      active = false;
      if (animationFrameId) window.cancelAnimationFrame(animationFrameId);
      if (handLandmarker) handLandmarker.close();
    };
  }, []);

  const sendCommand = async (command: string) => {
    setStatus(`Executing: ${command}...`);
    try {
      const res = await fetch("http://127.0.0.1:8001/api/command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command }),
      });
      const data = await res.json();
      setStatus(`Response: ${data.reply}`);
    } catch {
      setStatus("Error executing command.");
    }
  };

  return (
    <main>
      <div id="canvas-container">
        <canvas ref={canvasRef} className="w-full h-full block" />
      </div>

      <div id="ui-layer">
        {/* Top Header */}
        <header className="flex justify-between items-center glass-panel w-full">
          <div>
            <h1 className="text-3xl font-bold hud-text tracking-widest">F.R.I.D.A.Y.</h1>
            <p className="hud-text opacity-70">FRIDAY UI CORE v2.0</p>
          </div>
          <div className="text-right">
            <p className="hud-text opacity-70">STATUS</p>
            <p className="hud-text font-bold">{status}</p>
          </div>
        </header>

        {/* Center Canvas area is completely unobstructed so the orb can follow hand gestures! */}
        <div className="flex-1 pointer-events-none" />

        {/* Bottom Control Bar */}
        <footer className="flex justify-between items-end gap-6 w-full">
          {/* Camera Feed & Manual Action Buttons */}
          <div className="flex items-end gap-4">
            <div className="glass-panel w-56 aspect-video overflow-hidden relative">
              <p className="hud-text text-xs absolute top-1.5 left-2 z-10 bg-black/60 px-2 py-0.5 rounded">
                Camera Feed
              </p>
              <video
                ref={videoRef}
                className="w-full h-full object-cover transform scale-x-[-1]"
                autoPlay
                playsInline
                muted
              />
            </div>

            <div className="flex flex-col gap-2">
              <div className="flex gap-2">
                <button
                  onClick={() => sendCommand("open notepad")}
                  className="glass-panel hud-text hover:bg-cyan-900 transition px-3 py-1.5 text-xs"
                >
                  Notepad
                </button>
                <button
                  onClick={() => sendCommand("open chrome")}
                  className="glass-panel hud-text hover:bg-cyan-900 transition px-3 py-1.5 text-xs"
                >
                  Chrome
                </button>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => sendCommand("swipe left")}
                  className="glass-panel hud-text hover:bg-cyan-900 transition px-3 py-1.5 text-xs"
                >
                  Swipe Left
                </button>
                <button
                  onClick={() => sendCommand("swipe right")}
                  className="glass-panel hud-text hover:bg-cyan-900 transition px-3 py-1.5 text-xs"
                >
                  Swipe Right
                </button>
              </div>
            </div>
          </div>

          {/* Gesture Tracking Status Badge */}
          <div className="glass-panel text-right px-6 py-3">
            <p className="hud-text opacity-70 text-xs tracking-wider uppercase">Gesture Tracking</p>
            <p className="hud-text text-xl font-bold mt-1 text-cyan-300">{gesture}</p>
          </div>
        </footer>
      </div>
    </main>
  );
}
