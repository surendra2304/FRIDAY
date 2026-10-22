# FRIDAY External Agent Integrations

This bundle prepares FRIDAY to integrate four external ecosystems without importing their agent runtimes wholesale.

## Recommended implementations

| Repository | FRIDAY role | What to extract |
|---|---|---|
| `browser-use/browser-use` | Browser execution | Navigate, click, type, extract, browser state and recovery |
| `mem0ai/mem0` | Long-term memory provider | Personalized persistent memory, semantic retrieval, memory updates |
| `modelcontextprotocol/python-sdk` | Universal tool protocol | Discover and invoke MCP tools/resources/prompts through FRIDAY's ToolRegistry |
| `SWE-agent/mini-swe-agent` | Software-engineering specialist | Delegate coding/debugging tasks to a focused coding executor |

## Explicitly do NOT merge as separate runtimes

- LangGraph: FRIDAY already has orchestration/task infrastructure; borrow durability/checkpointing ideas only if useful.
- AutoGPT: overlaps heavily with FRIDAY's agent/orchestration mission.
- Open Interpreter: overlaps with FRIDAY's computer/tool execution and introduces broad arbitrary-code execution risk.

The implementation should treat these projects as capability/reference sources, not as competing brains.

## Safety boundaries

External agents must not bypass FRIDAY's authorization, audit, timeout, cancellation, or tool validation systems. Browser automation, memory writes, repository edits, and external side effects remain subject to FRIDAY policy.
