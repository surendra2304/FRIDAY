# FRIDAY First-Principles Performance & Resource Utilization Report

**Date**: 2026-08-21 09:42:51  
**Auditor**: FRIDAY Engineering Agent  
**Methodology**: First-principles physical RSS, Python tracemalloc heap peak, multi-core CPU time normalization, and p50/p95 latency distributions.  

---

## 1. Resource Utilization & Benchmark Matrix

| Scenario | Samples | Median Latency | p95 Latency | Peak Latency | Peak Process RSS | Peak Python Heap | Avg CPU % | Target & Justification | Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- | :---: |
| **Cold Start (Subprocess)** | 3 | **1757.62 ms** | 1808.04 ms | 1808.04 ms | 78.82 MB | 0.04 MB | 0.02% | Cold start < 2500ms target for responsive CLI invocation. | **PASS** |
| **Warm Start (In-Process)** | 5 | **1003.46 ms** | 1057.13 ms | 1057.13 ms | 174.38 MB | 0.04 MB | 8.19% | Warm start < 1500ms target for in-process agent re-initialization. | **PASS** |
| **Idle Runtime (Daemon Loop)** | 10 | **20.53 ms** | 20.78 ms | 20.78 ms | 174.38 MB | 0.00 MB | 0.00% | Idle loop CPU < 5%, zero RSS drift during inactivity. | **PASS** |
| **Voice Audio I/O Runtime** | 10 | **0.30 ms** | 0.31 ms | 0.31 ms | 174.38 MB | 0.00 MB | 0.00% | Voice audio processing < 10ms per 10-chunk batch to prevent audio underruns. | **PASS** |
| **Vision Perceptual Diffing Runtime** | 10 | **3.20 ms** | 3.40 ms | 3.40 ms | 174.66 MB | 0.01 MB | 7.91% | Vision diffing < 15ms target to sustain real-time 60fps screen evaluation. | **PASS** |
| **Single Task Execution (DAG Wave)** | 10 | **2.48 ms** | 3.46 ms | 3.46 ms | 174.75 MB | 0.01 MB | 9.55% | Single task execution < 25ms local overhead (excluding external I/O). | **PASS** |
| **Long Task (10-Step Execution)** | 10 | **13.48 ms** | 15.40 ms | 15.40 ms | 84.39 MB | 0.08 MB | 8.30% | 10-step plan < 100ms local execution overhead. | **PASS** |
| **Memory Query & Retrieval** | 10 | **6.85 ms** | 12.00 ms | 12.00 ms | 89.66 MB | 0.08 MB | 8.52% | Memory retrieval < 10ms for instantaneous context injection. | **PASS** |
| **Screen Capture Simulation** | 5 | **324.45 ms** | 328.23 ms | 328.23 ms | 90.02 MB | 0.42 MB | 8.31% | Screen snapshot generation & checksumming < 500ms per 5-frame batch. | **PASS** |
| **Concurrent Tasks (5 Parallel SAFE Steps)** | 10 | **7.36 ms** | 9.96 ms | 9.96 ms | 86.03 MB | 0.05 MB | 10.15% | Concurrent wave execution < 50ms total latency. | **PASS** |

---

## 2. Measurement Methodology & Definitions

1. **Physical Process RSS (Resident Set Size)**:
   - Measured directly from the operating system kernel via `psutil.Process().memory_info().rss`.
   - Represents actual physical RAM mapped into the process working set, avoiding artificial under-reporting.

2. **Python Heap Peak**:
   - Measured via `tracemalloc.get_traced_memory()[1]` for the duration of the benchmark iteration.
   - Distinguishes Python object allocation overhead from C-extensions, runtime binaries, and OS-level memory mappings.

3. **True CPU Utilization**:
   - Calculated as: `(delta_process_cpu_time / (delta_wall_time * num_logical_cpus)) * 100%`.
   - Avoids the mathematical invalidity of subtracting successive `psutil.cpu_percent()` instantaneous snapshots.

4. **Child-Process & GPU Tracking**:
   - Child processes are enumerated and tracked via `psutil.Process().children(recursive=True)`.
   - GPU memory is recorded when hardware accelerators are active; otherwise marked `N/A (CPU-Only)`.

---

## 3. Scenario-by-Scenario Detailed Analysis

### Cold Start (Subprocess)
- **Methodology**: Spawn isolated Python subprocess importing FRIDAY core, registering default tools and initializing FridayAgent.
- **Latency Distribution**: Min = 1733.81 ms, Median = 1757.62 ms, p95 = 1808.04 ms, Peak = 1808.04 ms.
- **Memory Profile**: Process RSS Peak = 78.82 MB | Python Heap Peak = 0.04 MB.
- **CPU Impact**: 0.02% average core load.
- **Target Justification**: Cold start < 2500ms target for responsive CLI invocation.
- **Compliance**: **MEETS TARGET**

### Warm Start (In-Process)
- **Methodology**: Construct FridayAgent instance in an already initialized Python runtime with full tool registry schema inspection.
- **Latency Distribution**: Min = 992.12 ms, Median = 1003.46 ms, p95 = 1057.13 ms, Peak = 1057.13 ms.
- **Memory Profile**: Process RSS Peak = 174.38 MB | Python Heap Peak = 0.04 MB.
- **CPU Impact**: 8.19% average core load.
- **Target Justification**: Warm start < 1500ms target for in-process agent re-initialization.
- **Compliance**: **MEETS TARGET**

### Idle Runtime (Daemon Loop)
- **Methodology**: Measure 20ms resting interval checking memory growth and CPU baseline during idle daemon state.
- **Latency Distribution**: Min = 20.20 ms, Median = 20.53 ms, p95 = 20.78 ms, Peak = 20.78 ms.
- **Memory Profile**: Process RSS Peak = 174.38 MB | Python Heap Peak = 0.00 MB.
- **CPU Impact**: 0.00% average core load.
- **Target Justification**: Idle loop CPU < 5%, zero RSS drift during inactivity.
- **Compliance**: **MEETS TARGET**

### Voice Audio I/O Runtime
- **Methodology**: Process 10 consecutive 16kHz PCM chunks, compute RMS energy, and execute speaker buffer flush.
- **Latency Distribution**: Min = 0.29 ms, Median = 0.30 ms, p95 = 0.31 ms, Peak = 0.31 ms.
- **Memory Profile**: Process RSS Peak = 174.38 MB | Python Heap Peak = 0.00 MB.
- **CPU Impact**: 0.00% average core load.
- **Target Justification**: Voice audio processing < 10ms per 10-chunk batch to prevent audio underruns.
- **Compliance**: **MEETS TARGET**

### Vision Perceptual Diffing Runtime
- **Methodology**: Execute 10 perceptual image difference and byte hash evaluations on 100x100 PNG frames.
- **Latency Distribution**: Min = 3.07 ms, Median = 3.20 ms, p95 = 3.40 ms, Peak = 3.40 ms.
- **Memory Profile**: Process RSS Peak = 174.66 MB | Python Heap Peak = 0.01 MB.
- **CPU Impact**: 7.91% average core load.
- **Target Justification**: Vision diffing < 15ms target to sustain real-time 60fps screen evaluation.
- **Compliance**: **MEETS TARGET**

### Single Task Execution (DAG Wave)
- **Methodology**: Schedule and execute a single-step TaskPlan through TaskExecutionEngine with state transitions and verification.
- **Latency Distribution**: Min = 2.27 ms, Median = 2.48 ms, p95 = 3.46 ms, Peak = 3.46 ms.
- **Memory Profile**: Process RSS Peak = 174.75 MB | Python Heap Peak = 0.01 MB.
- **CPU Impact**: 9.55% average core load.
- **Target Justification**: Single task execution < 25ms local overhead (excluding external I/O).
- **Compliance**: **MEETS TARGET**

### Long Task (10-Step Execution)
- **Methodology**: Execute a 10-step sequential TaskPlan with checkpointing, status updates, and postcondition checks.
- **Latency Distribution**: Min = 13.37 ms, Median = 13.48 ms, p95 = 15.40 ms, Peak = 15.40 ms.
- **Memory Profile**: Process RSS Peak = 84.39 MB | Python Heap Peak = 0.08 MB.
- **CPU Impact**: 8.30% average core load.
- **Target Justification**: 10-step plan < 100ms local execution overhead.
- **Compliance**: **MEETS TARGET**

### Memory Query & Retrieval
- **Methodology**: Execute indexed SQLite query retrieving latest 20 dialogue turns from active memory store.
- **Latency Distribution**: Min = 6.62 ms, Median = 6.85 ms, p95 = 12.00 ms, Peak = 12.00 ms.
- **Memory Profile**: Process RSS Peak = 89.66 MB | Python Heap Peak = 0.08 MB.
- **CPU Impact**: 8.52% average core load.
- **Target Justification**: Memory retrieval < 10ms for instantaneous context injection.
- **Compliance**: **MEETS TARGET**

### Screen Capture Simulation
- **Methodology**: Generate 5 full-screen PNG snapshots in memory and compute checksums.
- **Latency Distribution**: Min = 317.65 ms, Median = 324.45 ms, p95 = 328.23 ms, Peak = 328.23 ms.
- **Memory Profile**: Process RSS Peak = 90.02 MB | Python Heap Peak = 0.42 MB.
- **CPU Impact**: 8.31% average core load.
- **Target Justification**: Screen snapshot generation & checksumming < 500ms per 5-frame batch.
- **Compliance**: **MEETS TARGET**

### Concurrent Tasks (5 Parallel SAFE Steps)
- **Methodology**: Execute 5 independent SAFE tasks in parallel across worker threads within a single topological DAG wave.
- **Latency Distribution**: Min = 7.21 ms, Median = 7.36 ms, p95 = 9.96 ms, Peak = 9.96 ms.
- **Memory Profile**: Process RSS Peak = 86.03 MB | Python Heap Peak = 0.05 MB.
- **CPU Impact**: 10.15% average core load.
- **Target Justification**: Concurrent wave execution < 50ms total latency.
- **Compliance**: **MEETS TARGET**
