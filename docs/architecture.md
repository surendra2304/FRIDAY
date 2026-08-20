# FRIDAY Architecture Specification

**Version**: 6.10.0 (Phase 6 Final Complete Architecture)  
**Date**: 2026-08-20  
**Status**: FULLY IMPLEMENTED & VERIFIED  

---

## 1. System Overview & Provider-Agnostic Design

FRIDAY is an autonomous, multimodal, real-time desktop AI assistant designed for local execution on Windows with complete architectural provider independence. 

### Core Independence Principle
Gemini is currently FRIDAY's high-performance default intelligence engine (`gemini-3.7-flash` for reasoning/vision and `gemini-3.1-flash-live-preview` for real-time full-duplex voice). However, **Gemini is not FRIDAY**. FRIDAY's core reasoning loops, memory pipelines, safety boundaries, tool orchestrators, and perception controllers operate entirely behind abstract provider interfaces (`BaseLLMProvider`, `BaseVisionProvider`, `BaseScreenCaptureProvider`), allowing hot-swappable replacement with local models or alternative cloud LLMs without altering core system behavior.

---

## 2. Global Architecture Diagram

```mermaid
flowchart TD
    subgraph USER_LAYER ["User & Environment"]
        User["User (Surendra)"]
        Display["Windows Desktop Display"]
        AudioHW["Microphone & Speakers"]
    end

    subgraph FRIDAY_CORE ["FRIDAY Core System"]
        Agent["FridayAgent (Reasoning Loop)"]
        Context["Context Builder (Hierarchical)"]
        MemManager["Persistent Memory Manager"]
        ToolReg["Tool Registry & Safety Gates"]
        TaskState["Active Task State"]
    end

    subgraph PERCEPTION_LAYER ["Perception & Multimodal Subsystem"]
        ScreenCap["ScreenCaptureProvider (GDI/Win32)"]
        ChangeDet["ScreenChangeDetector (Hash Deduplication)"]
        Analyzer["ScreenAnalyzer"]
        VisionMem["VisionMemoryManager (Secret Redaction)"]
    end

    subgraph ACTION_LAYER ["Safe Computer Control Layer"]
        Proposal["ComputerActionProposal (Proposal != Execution)"]
        AuthGate["Safety / Authorization Gate"]
        Executor["ComputerActionExecutor (Hard Blocks & Sandboxing)"]
    end

    subgraph PROVIDER_INTERFACES ["Provider Abstraction Layer"]
        LLMInterface["BaseLLMProvider Interface"]
        VisionInterface["BaseVisionProvider Interface"]
        VoiceLive["GeminiLiveVoiceSession (Bidirectional Stream)"]
    end

    subgraph ENGINES ["Plug-and-Play Engines"]
        GeminiFlash["Gemini 3.7 Flash (Thinking: Medium)"]
        MockLLM["MockLLMProvider (Deterministic Testing)"]
        FutureLLM["Future LLM / Local LLM Provider"]
        GeminiVision["Gemini 3.7 Flash Vision"]
        MockVision["MockVisionProvider"]
        GeminiLive["Gemini 3.1 Flash Live Preview"]
    end

    %% Wiring
    User <-->|Voice Stream| AudioHW
    User <-->|CLI Commands / Direct Turn| Agent
    Display -->|Desktop Frames| ScreenCap

    ScreenCap --> ChangeDet
    ChangeDet -->|Significant Change| Analyzer
    Analyzer --> VisionMem
    VisionMem --> MemManager

    Agent --> Context
    MemManager --> Context
    TaskState --> Context
    Analyzer -->|Derived Context (UNTRUSTED DATA)| Context

    Context --> Agent
    Agent --> ToolReg
    ToolReg --> ActionProposalTool["propose_computer_action"]
    ActionProposalTool --> Proposal
    Proposal --> AuthGate
    AuthGate -->|User Confirmed| Executor
    Executor -->|Simulated / Win32 Input| Display

    Agent --> LLMInterface
    LLMInterface --> GeminiFlash
    LLMInterface --> MockLLM
    LLMInterface --> FutureLLM

    Analyzer --> VisionInterface
    VisionInterface --> GeminiVision
    VisionInterface --> MockVision

    AudioHW <--> VoiceLive
    VoiceLive <--> GeminiLive
```

---

## 3. Multimodal & Perception Subsystem (Phase 6)

### 3.1 Perception Pipeline
```
SCREEN CAPTURE (Win32 GDI)
    ↓
CHANGE DETECTION (Pixel-hash & bounds difference)
    ↓
MEANINGFUL CHANGE? ─── NO ───→ IGNORE (Zero API cost)
    ↓ YES
VISION PROVIDER (gemini-3.7-flash / Mock)
    ↓
SECRET REDACTION (API keys, passwords, bearer tokens)
    ↓
DERIVED SCREEN CONTEXT (Untrusted Observation block)
    ↓
SQLITE PERSISTENT MEMORY / CONTEXT INJECTION
```

### 3.2 Security & Untrusted Data Boundary
- **Screen Data is Untrusted**: Text visible on screenshots is strictly enclosed within `=== VISUAL SCREEN OBSERVATION (UNTRUSTED DATA) ===` delimiters.
- **Prompt Injection Defense**: Visual content is completely isolated from root system instructions and cannot alter safety rules or override tool authorization.
- **Zero Raw Image Persistence**: Raw PNG/JPEG byte streams are never stored to SQLite or log files; only sanitized text summaries and structural elements are retained.

---

## 4. Computer Action Proposal & Safety Enforcement (Phase 6.7 – 6.8)

FRIDAY strictly decouples intent formulation from action execution:
```
OBSERVE ──→ UNDERSTAND ──→ PROPOSE ──→ AUTHORIZE ──→ EXECUTE ──→ VERIFY
```

### Strict Non-Negotiable Hard Blocks:
1. **Proposal != Execution**: Formulating an action proposal never executes the action directly.
2. **Mandatory User Confirmation**: All interactive OS modifications require explicit user authorization.
3. **Unconditional Hard Blocks**:
   - Password entry / PIN typing
   - API key entry / Secret sharing
   - Financial checkout / payment transfers
   - Destructive commands (`rm -rf`, `format [drive]:`, `del /f`, `drop database`)
   - Arbitrary shell / script execution

---

## 5. Model Configuration Matrix

| Subsystem | Model Identifier | Thinking Level | Failover Mechanism |
| :--- | :--- | :--- | :--- |
| **Normal Text LLM** | `gemini-3.7-flash` | `medium` | 5-Project Credential Pool (Primary + 4 Fallbacks) |
| **Multimodal Vision** | `gemini-3.7-flash` | N/A | 5-Project Credential Pool with 429 cooldowns |
| **Real-Time Voice** | `gemini-3.1-flash-live-preview` | `MINIMAL` | Auto-reconnect with session resumption |
| **Semantic Embeddings**| `gemini-embedding-2` | N/A | Circuit-breaker fallback to SQLite FTS5 |

---

## 6. Provider Independence & Replaceability
- **FRIDAY Core**: Contains zero hardcoded vendor SDK dependencies in core agent loops.
- **Pluggable Base**: Any provider implementing `BaseLLMProvider.generate(messages, tools)` or `BaseVisionProvider.analyze_image(image_data, prompt)` can replace Gemini without changing agent orchestration, memory, or CLI interfaces.
- **Deterministic Testability**: 100% of core agent, tool, memory, and safety pipelines are testable offline using `MockLLMProvider` and `MockVisionProvider`.
