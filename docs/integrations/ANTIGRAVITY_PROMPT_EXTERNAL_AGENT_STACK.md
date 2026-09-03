# FRIDAY — EXTERNAL AGENT CAPABILITY STACK IMPLEMENTATION PROMPT

Use the provided FRIDAY repository as the source of truth.

Integrate the following reference repositories into FRIDAY as native capability providers, NOT as separate assistant architectures:

- Microsoft JARVIS: https://github.com/microsoft/JARVIS
- Practical J.A.R.V.I.S: https://github.com/GauravSingh9356/J.A.R.V.I.S
- Browser Use: https://github.com/browser-use/browser-use
- Mem0: https://github.com/mem0ai/mem0
- MCP Python SDK: https://github.com/modelcontextprotocol/python-sdk
- mini-SWE-agent: https://github.com/SWE-agent/mini-swe-agent

Also use the Sagar Tamang FRIDAY references previously supplied for UX direction.

## NON-NEGOTIABLE RULE

FRIDAY remains the only primary assistant, only security authority, only canonical tool registry, and only user-facing identity.

Do not import or create a second agent framework that competes with FRIDAY.

Do not replace FRIDAY's memory, voice, planning, computer control, or security systems.

Extend the existing systems.

## IMPLEMENT THESE CAPABILITIES

### 1. Browser Use integration

Use Browser Use as a specialized browser executor.

FRIDAY should be able to plan browser subtasks such as:

- open a page
- navigate
- click
- type
- submit forms
- extract structured information
- inspect browser state
- take screenshots
- verify browser-side outcomes

Prefer the Browser Use tool/action integration where FRIDAY's reasoning drives individual browser actions. Do not hand the entire conversation to a second autonomous assistant unless there is a strong technical reason.

All browser actions must go through FRIDAY authorization, timeouts, cancellation, domain restrictions, and audit logging.

### 2. Mem0 integration

Use Mem0 as an optional memory provider behind FRIDAY's existing BaseMemory abstraction.

Do not create a second memory policy.

FRIDAY remains responsible for:

- what gets stored
- user/session identity
- privacy policy
- deletion
- retention
- sensitive-memory restrictions
- access control

Mem0 may provide the memory storage/retrieval implementation where configured.

Gracefully fall back to existing FRIDAY memory when Mem0 is unavailable.

### 3. MCP integration

Add MCP client support so FRIDAY can discover external tools and expose them through the existing ToolRegistry.

MCP should provide interoperability, not a duplicate tool registry.

Implement:

- server configuration
- server connection
- tool discovery
- schema translation
- invocation
- result normalization
- error handling
- disconnect/reconnect
- timeouts
- cancellation where supported
- authorization before sensitive execution
- auditing

Map external MCP tools into FRIDAY's canonical tool abstraction.

### 4. mini-SWE-agent integration

Use mini-SWE-agent as a specialist executor for software-engineering tasks.

Good tasks include:

- inspect a repository
- investigate a failing test
- diagnose a bug
- propose a patch
- implement a bounded change
- run tests
- summarize changes

FRIDAY remains the planner and security layer.

The coding executor must operate in a controlled workspace and must not be given unrestricted repository/system access by default.

Respect:

- allowed workspaces
- command restrictions
- file restrictions
- Git safety
- confirmation for destructive actions
- timeouts
- cancellation
- audit logs

### 5. Microsoft JARVIS orchestration

Use the Microsoft JARVIS/HuggingGPT concepts already requested:

- task decomposition
- model/executor selection
- dependency graph
- execution
- result synthesis
- replanning

Do not copy its old server or model deployment architecture.

### 6. Practical J.A.R.V.I.S capabilities

Continue integrating useful capabilities from the previously supplied J.A.R.V.I.S repository through FRIDAY-native tools:

- email
- news
- weather
- Wikipedia
- dictionary
- YouTube
- Maps/location
- applications
- system information
- screenshots
- media
- tasks/todos
- face/identity features where appropriate

Do not copy its hard-coded command matching.

## FINAL ORCHESTRATION MODEL

The ideal system is:

USER
→ FRIDAY UNDERSTANDS
→ FRIDAY PLANS
→ TASK GRAPH
→ SELECT EXECUTOR
→ EXECUTE
→ OBSERVE
→ VALIDATE
→ REPLAN IF NEEDED
→ SYNTHESIZE
→ RESPOND

Possible executors:

- existing FRIDAY tools
- browser-use
- MCP tools
- local/cloud LLMs
- vision models
- mini-SWE-agent
- computer-control tools
- existing specialist agents

## IMPORTANT

Do not add LangGraph or AutoGPT as another orchestration framework unless a clearly isolated feature cannot be implemented cleanly in FRIDAY's existing architecture. Prefer extracting concepts rather than adding another runtime.

Do not directly embed Open Interpreter's unrestricted `exec()` model into FRIDAY. FRIDAY already has controlled computer/command capabilities and these must remain security-gated.

## TESTING

Add tests for:

- Browser Use unavailable/available
- browser command timeout
- browser result normalization
- Mem0 unavailable/fallback
- memory add/search
- MCP tool discovery
- MCP schema conversion
- MCP tool execution/error
- mini-SWE-agent unavailable
- coding task timeout
- workspace restrictions
- planner selecting the right executor
- multi-executor workflows
- failure/replanning
- security/authorization
- cancellation

Run the full FRIDAY test suite and fix regressions.

## DOCUMENTATION

Document installation/configuration for each optional dependency, how FRIDAY discovers the capability, what safety controls apply, and example natural-language requests.

Do not mark a capability complete merely because an adapter imports. Test the real integration path when dependencies are installed, and clearly report any environment-limited tests.

## FINAL ACCEPTANCE CRITERIA

A user can naturally ask FRIDAY to:

"Research these websites, compare the results, remember my preferences, open the browser and complete the required steps, then fix the code in my project if the research reveals a bug."

FRIDAY should dynamically combine the appropriate existing FRIDAY tools plus Browser Use, Mem0, MCP tools, and mini-SWE-agent while keeping one coherent plan, one security boundary, one memory policy, and one user-facing assistant.
