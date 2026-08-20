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

### Phase 8.3 — Temporal & Environmental Context [COMPLETE]
- Implemented `TemporalEnvironmentTracker`, `TemporalObservation`, `EnvironmentalChange`, and `EnvironmentalChangeType` (APPLICATION_FOCUS_SWITCH, WINDOW_TITLE_CHANGED, DIALOG_OPENED, DIALOG_CLOSED, ERROR_APPEARED, ERROR_RESOLVED, UI_ELEMENTS_MODIFIED, INSIGNIFICANT_NOISE, NO_CHANGE).
- Supported tracking of CURRENT_STATE vs PREVIOUS_STATE, meaningful change identification, confidence handling, task context association, and prompt formatting.
- Integrated sliding window temporal history with configurable max entries to maintain memory bounds without persisting raw screenshots.
- **Files Created/Modified**: `src/friday/vision/temporal.py`, `src/friday/vision/__init__.py`, `tests/test_temporal_environment.py` (7/7 tests passing).

### Phase 8.4 — Local Text & Perceptual Region Pre-Filtering (Quota Saver)
- Add local image slicing and region-of-interest (ROI) hashing to avoid full-screen re-analysis when only a subregion (e.g., terminal window) changes.
- Implement heuristic OCR/text density estimators to categorize screen complexity before dispatching API requests.
- Feed structured temporal deltas into `ActiveTaskContext` as verified visual observations.

### Phase 8.5 — Visual Memory & Episodic Environmental Memory [COMPLETE]
- Implemented `EpisodicEnvironmentalMemoryManager`, `EpisodicEnvironmentalFact`, and `MemoryImportance` (LOW, MEDIUM, HIGH, CRITICAL) in `src/friday/vision/episodic_memory.py`.
- Stored derived structured observations (application context, UI state changes, verified facts) without raw screenshots.
- Implemented relevance ranking, duplicate suppression, fact correction/superseding, deactivation/forgetting, and cross-task isolation.
- Integrated automatic fallback to SQLite memory search (FTS5 / Semantic) with secret/credential redaction.
- **Files Created/Modified**: `src/friday/vision/episodic_memory.py`, `src/friday/vision/__init__.py`, `tests/test_episodic_environmental_memory.py` (7/7 tests passing).

### Phase 8.6 — Active Perception & Information Seeking [COMPLETE]
- Implemented `ActivePerceptionEngine`, `ObservationDecision`, and `ObservationNecessity` (SUFFICIENT, UNCERTAIN_STATE, ENVIRONMENT_CHANGED, ACTION_VERIFICATION, BOUND_EXCEEDED) in `src/friday/vision/active_perception.py`.
- Evaluated context sufficiency before dispatching screen captures or vision model queries, skipping redundant calls.
- Enforced strict consecutive observation bounds (`max_consecutive_observations`) preventing infinite loop cycles.
- Hardened against visual prompt injection attempting to command continuous observation loops.
- **Files Created/Modified**: `src/friday/vision/active_perception.py`, `src/friday/vision/__init__.py`, `tests/test_active_perception.py` (7/7 tests passing).

### Phase 8.7 — Advanced Voice + Vision Interaction [COMPLETE]
- Implemented `VoicePerceptionResolver`, `VoicePerceptionResolution`, and `SpokenVisualIntentType` (CURRENT_SCREEN, CHANGE_INQUIRY, ERROR_INVESTIGATION, ELEMENT_ACTION, HISTORICAL_REFERENCE, NON_VISUAL) in `src/friday/voice/perception_resolver.py`.
- Resolved spoken contextual expressions against active context, `TemporalEnvironmentTracker`, and episodic memory to prevent redundant vision calls.
- Preserved `gemini-3.1-flash-live-preview` Live voice model and turn stability.
- Verified task state preservation during voice barge-ins and hard safety authorization boundaries.
- **Files Created/Modified**: `src/friday/voice/perception_resolver.py`, `tests/test_voice_vision_advanced.py` (7/7 tests passing).

### Phase 8.8 — Perception-Driven Safe Action Preparation [COMPLETE]
- Implemented `PerceptionActionPreparer`, `GroundedElementTarget`, `ActionPreparationResult`, and `GroundingStatus` (GROUNDED, AMBIGUOUS, NOT_FOUND, LOW_CONFIDENCE, MALICIOUS_REJECTED, STALE_SCREEN) in `src/friday/vision/action_preparer.py`.
- Enforced perception -> candidate target -> structured proposal -> authorization -> execution -> verification pipeline.
- Implemented ambiguity detection and user clarification prompts when multiple UI elements match semantic target.
- Added stale-screen detection before action execution and strict defense against visual injection text commanding action execution.
- **Files Created/Modified**: `src/friday/vision/action_preparer.py`, `src/friday/vision/__init__.py`, `tests/test_perception_action_preparation.py` (6/6 tests passing).

### Phase 8.9 — Perception Reliability, Caching & Cost Optimization [COMPLETE]
- Implemented `PerceptionCacheManager`, `CachedObservation`, and `PerceptionCacheTelemetry` in `src/friday/vision/cache_manager.py`.
- Multi-level caching with TTL expiration, exact SHA256 byte matching, and Mean Absolute Difference (MAD) perceptual image hashing.
- State-aware invalidations based on screen image differences, application focus switching, and task ID transitions.
- Cost telemetry instrumentation tracking suppressed API calls, cache hit ratios, and quota protection.
- **Files Created/Modified**: `src/friday/vision/cache_manager.py`, `src/friday/vision/__init__.py`, `tests/test_perception_caching.py` (7/7 tests passing).

### Phase 8.10 — Full Phase 8 Multimodal Perception Acceptance Gate
- Build end-to-end acceptance suite (`tests/test_phase8_acceptance_gate.py`).
- Validate: Screen Capture → ROI Crop → Structured UI Grounding → Element Resolution → Action Proposal → Authorization Gate → Execution → Visual Verification → Memory Fusion.

---

## 5. Safety, Quota & Provider Independence Contract

1. **Proposal != Execution**: Grounded visual resolution generates `ComputerActionProposal` instances with verified coordinates, but NEVER auto-executes without confirmation.
2. **Quota & Cost Guardrails**: Pre-filtering, perceptual hash diffing, and ROI cropping ensure Gemini Vision calls are dispatched ONLY when genuine visual state changes occur.
3. **Offline Testability**: 100% of Phase 8 components must run offline with `MockVisionProvider`, `MockScreenCaptureProvider`, and `MockLLMProvider`. Real Gemini API calls are reserved for optional manual hardware smoke tests.
4. **IBM Quantum Status**: Reserved for Phase 9+. Zero quantum code or dependencies in Phase 8.
