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

    // Inner Counter-Rotating Holographic Sphere (Deep Teal)
    const innerGeo = new THREE.IcosahedronGeometry(1.6, 2);
    const innerMat = new THREE.MeshBasicMaterial({
      color: 0x00aaff,
      wireframe: true,
      transparent: true,
      opacity: 0.65,
    });
    const innerOrb = new THREE.Mesh(innerGeo, innerMat);
    scene.add(innerOrb);

    // Central Pulsing Core
    const coreGeo = new THREE.SphereGeometry(0.7, 16, 16);
    const coreMat = new THREE.MeshBasicMaterial({
      color: 0x88ffff,
      wireframe: true,
      transparent: true,
      opacity: 0.45,
    });
    const coreOrb = new THREE.Mesh(coreGeo, coreMat);
    scene.add(coreOrb);

    camera.position.z = 5;

    let frameId: number;
    let running = true;

    const animate = () => {
      if (!running) return;

      const now = performance.now() * 0.001;

      // Noticeable, smooth dynamic rotation
      outerOrb.rotation.x += 0.015;
      outerOrb.rotation.y += 0.020;

      innerOrb.rotation.x -= 0.022;
      innerOrb.rotation.y -= 0.018;

      coreOrb.rotation.y += 0.030;

      // Audio pulse simulation
      const pulse = 1 + Math.sin(now * 3) * 0.08;
      outerOrb.scale.set(pulse, pulse, pulse);
      innerOrb.scale.set(1.05 / pulse, 1.05 / pulse, 1.05 / pulse);

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

  // Initialize WebSocket
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

  // Initialize MediaPipe
  useEffect(() => {
    let handLandmarker: HandLandmarker;
    let animationFrameId: number;

    const initializeMediaPipe = async () => {
      try {
        const vision = await FilesetResolver.forVisionTasks(
          "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.3/wasm"
        );
        handLandmarker = await HandLandmarker.createFromOptions(vision, {
          baseOptions: {
            modelAssetPath: "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task",
            delegate: "GPU",
          },
          runningMode: "VIDEO",
          numHands: 1,
        });

        // Request Webcam
        if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
          const stream = await navigator.mediaDevices.getUserMedia({ video: true });
          if (videoRef.current) {
            videoRef.current.srcObject = stream;
            videoRef.current.addEventListener("loadeddata", predictWebcam);
          }
        }
      } catch (err) {
        console.error("MediaPipe initialization failed:", err);
      }
    };

    let lastVideoTime = -1;
    let lastGestureTime = 0;
    const predictWebcam = async () => {
      if (videoRef.current && handLandmarker) {
        const startTimeMs = performance.now();
        if (lastVideoTime !== videoRef.current.currentTime) {
          lastVideoTime = videoRef.current.currentTime;
          const results = handLandmarker.detectForVideo(videoRef.current, startTimeMs);
          
          if (results.landmarks.length > 0) {
            const indexFingerTip = results.landmarks[0][8]; // Index finger tip
            // Basic gesture logic: Swipe Left vs Right
            const now = Date.now();
            if (now - lastGestureTime > 2000) { // 2-second cooldown
              if (indexFingerTip.x < 0.3) {
                 setGesture("Swipe Left");
                 lastGestureTime = now;
                 if (wsRef.current?.readyState === WebSocket.OPEN) {
                   wsRef.current.send(JSON.stringify({ type: "gesture", gesture: "swipe_left" }));
                 }
              } else if (indexFingerTip.x > 0.7) {
                 setGesture("Swipe Right");
                 lastGestureTime = now;
                 if (wsRef.current?.readyState === WebSocket.OPEN) {
                   wsRef.current.send(JSON.stringify({ type: "gesture", gesture: "swipe_right" }));
                 }
              } else {
                 setGesture("Tracking");
              }
            } else {
              setGesture("Cooldown...");
            }
          } else {
            setGesture("None");
          }
        }
      }
      animationFrameId = window.requestAnimationFrame(predictWebcam);
    };

    initializeMediaPipe();

    return () => {
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

        <div className="flex flex-wrap gap-4">
          <button onClick={() => sendCommand("open notepad")} className="glass-panel hud-text hover:bg-cyan-900 transition px-4 py-2">
            Test: Open Notepad
          </button>
          <button onClick={() => sendCommand("open chrome")} className="glass-panel hud-text hover:bg-cyan-900 transition px-4 py-2">
            Test: Open Chrome
          </button>
          <button onClick={() => sendCommand("swipe left")} className="glass-panel hud-text hover:bg-cyan-900 transition px-4 py-2">
            Test: Swipe Left (Notepad)
          </button>
          <button onClick={() => sendCommand("swipe right")} className="glass-panel hud-text hover:bg-cyan-900 transition px-4 py-2">
            Test: Swipe Right (Chrome)
          </button>
        </div>

        <footer className="flex justify-between items-end">
          <div className="glass-panel w-64 aspect-video overflow-hidden relative">
            <p className="hud-text text-sm absolute top-2 left-2 z-10 bg-black/50 px-2 py-1 rounded">Camera Feed</p>
            <video ref={videoRef} className="w-full h-full object-cover transform scale-x-[-1]" autoPlay playsInline></video>
          </div>
          
          <div className="glass-panel text-right">
            <p className="hud-text opacity-70 text-sm">GESTURE TRACKING</p>
            <p className="hud-text text-2xl font-bold">{gesture}</p>
          </div>
        </footer>
      </div>
    </main>
  );
}
