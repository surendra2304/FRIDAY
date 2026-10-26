"""Robin-compatible MCP JSON-RPC stdio surface backed by IntelX's real pipeline.

Run on the operator host with:
  PYTHONPATH=.:FRIDAY/apps/core/src python3 -m friday_core.real_research_mcp
A local Tor SOCKS5 daemon and an explicit research-preset choice are required
for live searches. Cloud inference is optional and uses the configured Groq key.
"""
from __future__ import annotations

import json
import sys
from urllib.parse import unquote, urlsplit


class ResearchMCPServer:
    def __init__(self, investigation) -> None:
        self.investigation = investigation
        self.tools = {
            "robin_refine": ("Refine a user question to a five-word search query; cloud use must be explicit.", {
                "type": "object", "properties": {"query": {"type": "string"}, "use_cloud_model": {"type": "boolean"}}, "required": ["query"]}),
            "robin_search": ("Federated search over configured onion engines. User must select a domain.", {
                "type": "object", "properties": {"query": {"type": "string"}, "preset": {"type": "string"},
                    "user_chose_preset": {"type": "boolean"}, "max_results": {"type": "integer"},
                    "per_host_limit": {"type": "integer"}, "threads": {"type": "integer"},
                    "allow_clearweb": {"type": "boolean"}, "use_cloud_model": {"type": "boolean"}},
                "required": ["query", "preset", "user_chose_preset"]}),
            "robin_filter": ("Filter results to the requested topic; only returned IDs can be scraped.", {
                "type": "object", "properties": {"search_id": {"type": "string"}, "query": {"type": "string"},
                    "max_scrape": {"type": "integer"}, "use_cloud_model": {"type": "boolean"}}, "required": ["search_id", "query"]}),
            "robin_scrape": ("Fetch only relevance-approved result IDs through the configured Tor proxy.", {
                "type": "object", "properties": {"search_id": {"type": "string"}, "result_ids": {"type": "array", "items": {"type": "string"}},
                    "threads": {"type": "integer"}, "content_chars": {"type": "integer"}}, "required": ["search_id"]}),
            "robin_investigate": ("Run refine, search, filter, scrape, analyze, summarize, pivot and persist.", {
                "type": "object", "properties": {"query": {"type": "string"}, "preset": {"type": "string"},
                    "user_chose_preset": {"type": "boolean"}, "custom_instructions": {"type": "string"},
                    "max_results": {"type": "integer"}, "max_scrape": {"type": "integer"},
                    "threads": {"type": "integer"}, "content_chars": {"type": "integer"},
                    "per_host_limit": {"type": "integer"}, "allow_clearweb": {"type": "boolean"},
                    "use_cloud_model": {"type": "boolean"}},
                "required": ["query", "preset", "user_chose_preset"]}),
            "robin_list_models": ("List operator-configured model identifiers without revealing credentials.", {"type": "object", "properties": {}}),
            "robin_health": ("Check configured search engines, local Tor SOCKS and optional model availability.", {"type": "object", "properties": {}}),
            "robin_list_investigations": ("List locally saved reports.", {"type": "object", "properties": {
                "query": {"type": "string"}, "limit": {"type": "integer"}}}),
            "robin_save_investigation": ("Save a bounded host-written report and source metadata; no source text is persisted.", {
                "type": "object", "properties": {"query": {"type": "string"}, "preset": {"type": "string"},
                    "summary": {"type": "string"}, "sources": {"type": "array", "items": {"type": "object"}},
                    "pivots": {"type": "array", "items": {"type": "string"}}, "allow_clearweb": {"type": "boolean"}},
                "required": ["query", "preset", "summary", "sources"]}),
        }

    def _read_resource(self, uri: str) -> dict:
        prefix = "robin://investigations/"
        if not uri.startswith(prefix):
            raise KeyError(uri)
        case_id = unquote(urlsplit(uri).path.rsplit("/", 1)[-1])
        record = self.investigation.store.get(case_id)
        return {"contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps(record)}]}

    def dispatch(self, request: dict) -> dict | None:
        request_id = request.get("id")
        if "id" not in request:
            return None
        response = {"jsonrpc": "2.0", "id": request_id}
        method = request.get("method")
        try:
            if request.get("jsonrpc") != "2.0":
                return {**response, "error": {"code": -32600, "message": "Invalid JSON-RPC request"}}
            if method == "initialize":
                result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}, "resources": {"subscribe": False, "listChanged": False}},
                          "serverInfo": {"name": "friday-intelx-robin", "version": "1.1.0"}}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": [{"name": n, "description": d, "inputSchema": schema} for n, (d, schema) in self.tools.items()]}
            elif method == "resources/list":
                result = {"resources": [{"uri": "robin://investigations/", "name": "Saved IntelX investigations",
                    "description": "Use robin_list_investigations and read a case URI.", "mimeType": "application/json"}]}
            elif method == "resources/read":
                result = self._read_resource(request.get("params", {}).get("uri", ""))
            elif method == "tools/call":
                params = request.get("params", {})
                name, arguments = params.get("name"), params.get("arguments", {})
                handlers = {
                    "robin_refine": lambda **a: {"refined_query": self.investigation.refine_query(a["query"], a.get("use_cloud_model", False))},
                    "robin_search": self.investigation.search,
                    "robin_filter": self.investigation.filter,
                    "robin_scrape": self.investigation.scrape,
                    "robin_investigate": self.investigation.run,
                    "robin_list_models": lambda **_a: self.investigation.list_models(),
                    "robin_health": lambda **_a: self.investigation.health(),
                    "robin_list_investigations": lambda **a: self.investigation.store.list(a.get("query", ""), a.get("limit", 50)),
                    "robin_save_investigation": self.investigation.save_external,
                }
                if name not in handlers:
                    return {**response, "error": {"code": -32602, "message": "Unknown tool"}}
                try:
                    value = handlers[name](**arguments)
                    output = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
                    result = {"content": [{"type": "text", "text": output}]}
                except (KeyError, ValueError, TypeError):
                    result = {"content": [{"type": "text", "text": "Tool failed: invalid arguments, consent, or case not found"}], "isError": True}
            else:
                return {**response, "error": {"code": -32601, "message": "Method not found"}}
            return {**response, "result": result}
        except (KeyError, ValueError, TypeError, AttributeError):
            return {**response, "error": {"code": -32602, "message": "Invalid parameters or case not found"}}

    def serve(self, input_stream, output_stream) -> None:
        for line in input_stream:
            if len(line) > 1_000_000:
                response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Request too large"}}
            else:
                try:
                    request = json.loads(line)
                    if not isinstance(request, dict):
                        raise ValueError("object required")
                    response = self.dispatch(request)
                except ValueError:
                    response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
            if response is not None:
                output_stream.write(json.dumps(response, ensure_ascii=False) + "\n")
                output_stream.flush()


if __name__ == "__main__":
    from friday_core.real_cross_agent_engine import CrossAgentEngine
    ResearchMCPServer(CrossAgentEngine().investigation_engine()).serve(sys.stdin, sys.stdout)
