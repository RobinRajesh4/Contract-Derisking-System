import os
from typing import Any, Dict, Optional
import json
import urllib.request


class MCPConfig:
    def __init__(self) -> None:
        self.base_url = os.getenv("MCP_BASE_URL")  # e.g., https://windsurf-mcp.example.com
        self.api_key = os.getenv("MCP_API_KEY")
        self.model = os.getenv("MCP_MODEL", "gpt-4o-mini")

    def is_configured(self) -> bool:
        return bool(self.base_url and self.api_key)


def mcp_post(path: str, payload: Dict[str, Any], cfg: MCPConfig) -> Optional[Dict[str, Any]]:
    if not cfg.is_configured():
        return None
    url = cfg.base_url.rstrip("/") + path
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cfg.api_key}",
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw)
