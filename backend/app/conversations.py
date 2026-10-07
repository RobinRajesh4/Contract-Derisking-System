"""
Saved chat conversations, so a conversation can be reopened after the
browser tab is closed.

One JSON file next to analyses.json (same atomic writes). Conversations
hold questions, answers and quoted clause text, so the file is as
sensitive as the contracts and is not committed.

There are no user accounts: everyone who can reach the backend sees the
same list.
"""
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Dict, List, Optional

from . import store as store_module
from .store import _replace_with_retry

MAX_CONVERSATIONS = 200          # oldest are dropped beyond this
MAX_MESSAGES = 200               # per conversation (the newest are kept)
MAX_MESSAGE_CHARS = 20000        # one question or answer
MAX_SOURCE_CHARS = 600           # quoted clause text per reference
MAX_TITLE_CHARS = 80
_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_LOCK = RLock()


def valid_id(conversation_id: str) -> bool:
    return bool(_ID.match(conversation_id or ""))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _clean_message(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Keep the fields the chat page uses; cut anything oversized."""
    role = message.get("role")
    content = message.get("content")
    if role not in ("user", "assistant") or not isinstance(content, str) or not content.strip():
        return None
    out: Dict[str, Any] = {"role": role, "content": content[:MAX_MESSAGE_CHARS]}
    for key in ("coverage", "route", "model", "routerModel", "citations", "querySpec"):
        if message.get(key) is not None:
            out[key] = message[key]
    sources = message.get("sources")
    if isinstance(sources, list):
        cleaned = []
        for src in sources[:100]:
            if not isinstance(src, dict):
                continue
            src = dict(src)
            if isinstance(src.get("text"), str) and len(src["text"]) > MAX_SOURCE_CHARS:
                src["text"] = src["text"][:MAX_SOURCE_CHARS] + " …"
            cleaned.append(src)
        out["sources"] = cleaned
    return out


def title_for(messages: List[Dict[str, Any]]) -> str:
    """The first question, shortened."""
    for m in messages:
        if m.get("role") == "user" and str(m.get("content", "")).strip():
            text = " ".join(str(m["content"]).split())
            return text if len(text) <= MAX_TITLE_CHARS else text[: MAX_TITLE_CHARS - 1].rstrip() + "…"
    return "New conversation"


class ConversationStore:
    def __init__(self) -> None:
        self.path = os.path.join(store_module.DATA_DIR, "conversations.json")

    def _read(self) -> Dict[str, Any]:
        with _LOCK:
            if not os.path.exists(self.path):
                return {}
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data if isinstance(data, dict) else {}
            except (OSError, ValueError):
                # An unreadable history must not break the chat itself.
                return {}

    def _write(self, data: Dict[str, Any]) -> None:
        with _LOCK:
            folder = os.path.dirname(self.path)
            os.makedirs(folder, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(dir=folder, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
                _replace_with_retry(tmp_path, self.path)
            except Exception:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                raise

    def list(self) -> List[Dict[str, Any]]:
        """Newest first, without the messages."""
        items = [
            {
                "id": cid,
                "title": c.get("title") or "Conversation",
                "created_at": c.get("created_at"),
                "updated_at": c.get("updated_at"),
                "messages": len(c.get("messages") or []),
                "analysis_id": c.get("analysis_id"),
            }
            for cid, c in self._read().items()
        ]
        items.sort(key=lambda c: c.get("updated_at") or "", reverse=True)
        return items

    def get(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        c = self._read().get(conversation_id)
        return {"id": conversation_id, **c} if c else None

    def save(self, conversation_id: str, messages: List[Dict[str, Any]],
             analysis_id: Optional[str] = None) -> Dict[str, Any]:
        cleaned = [m for m in (_clean_message(m) for m in messages if isinstance(m, dict)) if m][-MAX_MESSAGES:]
        with _LOCK:
            data = self._read()
            existing = data.get(conversation_id) or {}
            now = _now()
            data[conversation_id] = {
                "title": title_for(cleaned),
                "created_at": existing.get("created_at") or now,
                "updated_at": now,
                "analysis_id": analysis_id,
                "messages": cleaned,
            }
            if len(data) > MAX_CONVERSATIONS:
                oldest = sorted(data, key=lambda k: data[k].get("updated_at") or "")
                for key in oldest[: len(data) - MAX_CONVERSATIONS]:
                    del data[key]
            self._write(data)
            saved = data[conversation_id]
        return {"id": conversation_id, "title": saved["title"], "updated_at": saved["updated_at"],
                "messages": len(saved["messages"])}

    def delete(self, conversation_id: str) -> bool:
        with _LOCK:
            data = self._read()
            if conversation_id not in data:
                return False
            del data[conversation_id]
            self._write(data)
            return True
