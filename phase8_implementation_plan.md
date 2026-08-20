# FRIDAY — PHASE 8 IMPLEMENTATION PLAN
## Advanced Multimodal Perception, Visual Reasoning & Grounded UI Understanding

**Document Version**: 1.0.0  
**Phase Status**: PLANNING & AUDIT (Subphase 8.1)  
**Baseline Commit**: `5f67bf3ce700688632208b3ef4e2d768b42a8371` (Phase 7 Complete & 100% Verified)  
**Next Subphases**: 8.2 through 8.10  
**IBM Quantum Status**: RESERVED FOR FUTURE SPECIALIZED COMPUTE PHASE (Phase 9+)  

---

## 1. Executive Summary & Goals

Phase 7 delivered complete multi-step autonomous planning, state machines, tool orchestration, failure recovery, task memory, and long-running execution.
Phase 8 focuses on **upgrading FRIDAY's multimodal perception from coarse whole-screen text summaries to fine-grained, structured visual scene understanding, grounded UI element detection, temporal perceptual delta tracking, and multimodal context fusion** — while **strictly bounding cloud API usage through local perceptual pre-filters**.

---

## 2. Audit of Existing Perception & Multimodal Capabilities

### What Already Exists (Phases 5, 6 & 7):
1. **Screen Capture Engine** (`src/friday/vision/windows_screen.py`):
   - Win32 GDI direct desktop capture (GetDIBits 64-bit ctypes argtypes configured).
   - Multi-monitor detection, coordinate scaling, and PNG compression.
   - `MockScreenCaptureProvider` for deterministic offline testing.
2. **Coarse Screen Understanding** (`src/friday/vision/screen_analyzer.py`):
   - Single-turn Gemini 3.7 Flash screen analysis with untrusted prompt delimiters.
   - Summarization of active applications, visible text, error messages, and buttons.
3. **Change Detection & Rate Limiting** (`src/friday/vision/change_detector.py`, `screen_awareness.py`):
   - Luminance hash and Mean Absolute Difference (MAD) subsampling to suppress unchanged frames.
   - Configurable awareness interval (default 10s) and change threshold (default 5%).
4. **Visual Memory & Secret Redaction** (`src/friday/vision/vision_memory.py`):
   - Redacts API keys, passwords, tokens, credit card numbers, and SSNs.
   - Stores derived textual summaries in SQLite conversation memory; never stores raw screenshots.
5. **Computer Action Proposal Layer** (`src/friday/vision/actions.py`, `computer_control.py`):
   - `ComputerActionProposal` and `ProposalBuilder` enforcing `Proposal != Execution`.
   - `ComputerActionExecutor` with hard-block security policies and confirmation gating.
6. **Task Context & Checkpoints** (`src/friday/memory/task_context.py`, `src/friday/agent/checkpoint.py`):
   - Ephemeral working memory recording step results and scrubbing secrets/binary buffers.
   - Pause/resume state serialization with duplicate step suppression.

### What is Genuinely Missing (Phase 8 Focus):
1. **Structured UI Element Grounding & Bounding Box Detection**:
   - Currently, UI elements are returned as unstructured strings (`buttons: List[str]`). There is no precise bounding box coordinates `[ymin, xmin, ymax, xmax]` or normalized element hierarchy (buttons, inputs, dropdowns, tables, tabs).
2. **Local Pre-OCR & Hybrid Text Extraction**:
   - Currently, all OCR requires a full cloud vision call to Gemini. We lack lightweight local text bounding or fast pre-classification to extract screen text cheaply.
3. **Temporal Visual Delta & Window Transition Tracking**:
   - Change detection only outputs a scalar MAD float (e.g. `0.12`). It cannot identify *what* changed (e.g., "Dialog box opened", "Tab switched to VS Code", "Loading spinner disappeared").
4. **Grounded Perception-to-Action Mapping**:
   - When FRIDAY proposes an action like `click(x, y)`, the coordinates are currently coarse or manual. Grounded perception should resolve semantic intents like "Click the Save button" into verified element bounding box centers with high confidence.
5. **Multimodal Working Context Fusion**:
   - Voice audio events, task progress, and visual screen observations exist in separate modules. FRIDAY needs a unified multimodal perception buffer that synchronizes what the user is saying, what is on the screen, and what the agent is doing.
6. **Visual Verification Engine**:
   - Verification in Phase 7.4 inspects text tool outputs. Visual verification must inspect post-action screen state (e.g., verifying a file dialog actually closed after clicking Save).

---

## 3. Subphase Plan for Phase 8

```
Phase 8.1: Advanced Perception Audit & Foundation Plan (CURRENT)
Phase 8.2: Structured UI Element Grounding & Bounding Box Models
Phase 8.3: Local Text & Perceptual Region Pre-Filtering (Quota Saver)
Phase 8.4: Temporal Visual State & UI Delta Tracker (What Changed?)
Phase 8.5: Grounded Visual Element Resolver (Semantic Action Grounding)
Phase 8.6: Visual Step Verification & State Assertion Engine
Phase 8.7: Unified Multimodal Context Buffer (Voice + Vision + Task State)
Phase 8.8: Dynamic Multi-Resolution & Region-of-Interest (ROI) Cropping
Phase 8.9: Advanced Perception Security & Visual Injection Hardening
Phase 8.10: Full Phase 8 Multimodal Perception Acceptance Gate
```

---

## 4. Detailed Subphase Specifications

### Phase 8.2 — Structured UI Element Grounding & Bounding Box Models [COMPLETE]
- Introduced `UIElement`, `ElementType` (BUTTON, INPUT_FIELD, TEXT_REGION, WINDOW, APPLICATION_REGION, DIALOG, MODAL, MENU, MENU_ITEM, TAB, TABLE, NOTIFICATION, ICON, CHECKBOX, DROPDOWN, CODE_EDITOR, TERMINAL, CHART, UNKNOWN), and `BoundingBox` normalized to 0–1000 coordinate scale with pixel conversions.
- Upgraded `ScreenAnalyzer` to request structured JSON schemas from vision providers and parse UI elements, confidence ratings, and bounding coordinates.
- Added confidence-aware element query methods on `ScreenContext` (`find_element_by_label`, `get_elements_by_type`).
- Enforced untrusted visual data delimiters preventing visual text from overriding system policies.
- **Files Created/Modified**: `src/friday/vision/ui_elements.py`, `src/friday/vision/screen_context.py`, `src/friday/vision/screen_analyzer.py`, `src/friday/vision/__init__.py`, `tests/test_advanced_screen_understanding.py` (7/7 tests passing).

### Phase 8.3 — Local Text & Perceptual Region Pre-Filtering
- Add local image slicing and region-of-interest (ROI) hashing to avoid full-screen re-analysis when only a subregion (e.g., terminal window) changes.
- Implement heuristic OCR/text density estimators to categorize screen complexity before dispatching API requests.

### Phase 8.4 — Temporal Visual State & UI Delta Tracker
- Implement `VisualStateDelta` comparing consecutive `ScreenContext` snapshots.
- Track application window transitions, active focus shifts, and appearing/disappearing UI elements.
- Feed structured temporal deltas into `ActiveTaskContext` as verified visual observations.

### Phase 8.5 — Grounded Visual Element Resolver
- Bridge `ProposalBuilder` and structured perception: resolve natural language target ("Click the blue Deploy button") to verified `UIElement` coordinates `(x, y)`.
- Enforce confidence thresholds and fallback strategies if target element is ambiguous or obscured.

### Phase 8.6 — Visual Step Verification & State Assertion Engine
- Enhance `StepVerifier` to support visual assertions (e.g., `visual_contains: "Build Succeeded"`, `element_gone: "Loading Spinner"`, `window_active: "Terminal"`).
- Connect post-action visual inspection directly to Phase 7.4 self-correction loops.

### Phase 8.7 — Unified Multimodal Context Buffer
- Implement `MultimodalContextBuffer` fusing voice transcriptions, visual element states, and task state machine events with synchronized monotonic timestamps.
- Ensure context window budget is strictly preserved with sliding window eviction and token budgeting.

### Phase 8.8 — Dynamic Multi-Resolution & ROI Cropping
- Support adaptive image scaling and targeted high-resolution crops for dense code or terminal text without sending 4K full-frame images repeatedly.
- Reduce token consumption and latency by up to 60% on localized screen operations.

### Phase 8.9 — Advanced Perception Security & Visual Injection Hardening
- Audit and harden visual element resolution against visual prompt injection (e.g., deceptive buttons, invisible text, adversarial background patterns).
- Strictly enforce `Proposal != Execution` and BaseAuthorizer confirmation gates across all grounded computer control proposals.

### Phase 8.10 — Full Phase 8 Multimodal Perception Acceptance Gate
- Build end-to-end acceptance suite (`tests/test_phase8_acceptance_gate.py`).
- Validate: Screen Capture → ROI Crop → Structured UI Grounding → Element Resolution → Action Proposal → Authorization Gate → Execution → Visual Verification → Memory Fusion.

---

## 5. Safety, Quota & Provider Independence Contract

1. **Proposal != Execution**: Grounded visual resolution generates `ComputerActionProposal` instances with verified coordinates, but NEVER auto-executes without confirmation.
2. **Quota & Cost Guardrails**: Pre-filtering, perceptual hash diffing, and ROI cropping ensure Gemini Vision calls are dispatched ONLY when genuine visual state changes occur.
3. **Offline Testability**: 100% of Phase 8 components must run offline with `MockVisionProvider`, `MockScreenCaptureProvider`, and `MockLLMProvider`. Real Gemini API calls are reserved for optional manual hardware smoke tests.
4. **IBM Quantum Status**: Reserved for Phase 9+. Zero quantum code or dependencies in Phase 8.
