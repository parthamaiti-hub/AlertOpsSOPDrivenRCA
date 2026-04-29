import random
from datetime import UTC, datetime, timedelta


def mcp_client(server_url: str, tool_name: str, arguments: dict = None) -> dict:
    """Stub MCP (Model Context Protocol) client. Calls a named tool on a remote MCP server."""
    if arguments is None:
        arguments = {}

    now = datetime.now(UTC)

    # Simulate different MCP tool response shapes based on tool_name
    if "read_file" in tool_name or "file" in tool_name.lower():
        content = (
            "Container logs show repeated OOMKilled events.\n"
            "RestartCount: 7\nReason: OOMKilled\nExitCode: 137\n"
            "Last restart: " + (now - timedelta(minutes=random.randint(2, 30))).isoformat() + "Z"
        )
        result = {"type": "text", "text": content}
    elif "search" in tool_name.lower() or "query" in tool_name.lower():
        hits = [
            {"id": f"doc-{i}", "score": round(random.uniform(0.7, 0.99), 3), "snippet": f"Relevant context snippet {i}"}
            for i in range(1, random.randint(3, 6))
        ]
        result = {"type": "search_results", "hits": hits, "total": len(hits)}
    elif "list" in tool_name.lower():
        items = [f"resource-{i:03d}" for i in range(1, random.randint(3, 8))]
        result = {"type": "list", "items": items}
    else:
        result = {
            "type": "json",
            "data": {
                "status": "ok",
                "tool": tool_name,
                "executed_at": now.isoformat() + "Z",
                "sample_metric": round(random.uniform(10, 100), 2),
            },
        }

    return {
        "server_url": server_url,
        "tool_name": tool_name,
        "arguments": arguments,
        "result": result,
        "latency_ms": random.randint(12, 350),
        "timestamp": now.isoformat() + "Z",
    }


# Alias used by registry loader (looks for function named 'execute' first)
execute = mcp_client
