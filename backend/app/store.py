import json
import os
import tempfile
from typing import Dict, Any, List, Optional
from uuid import uuid4
from threading import RLock
from datetime import datetime


DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DATA_FILE = os.path.join(DATA_DIR, "analyses.json")

# One lock shared by every Store instance in the process. Each write
# rewrites the whole JSON file, so a read-modify-write that isn't held
# under a single lock from start to finish lets two concurrent updates
# each read the old file and the second write silently erase the
# first. That happened in practice once uploads, analysis and the
# metadata backfill started running on worker threads.
_LOCK = RLock()


class Store:
    def __init__(self) -> None:
        os.makedirs(DATA_DIR, exist_ok=True)
        with _LOCK:
            if not os.path.exists(DATA_FILE):
                self._write({})

    def _read(self) -> Dict[str, Any]:
        with _LOCK:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)

    def _write(self, data: Dict[str, Any]) -> None:
        """Write atomically: a crash or kill mid-write leaves the old
        file intact instead of a truncated, unreadable one."""
        with _LOCK:
            fd, tmp_path = tempfile.mkstemp(dir=DATA_DIR, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, DATA_FILE)
            except Exception:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                raise

    def save_analysis(self, payload: Dict[str, Any]) -> str:
        with _LOCK:
            data = self._read()
            analysis_id = payload.get("analysis_id") or uuid4().hex
            payload["analysis_id"] = analysis_id
            data[analysis_id] = payload
            self._write(data)
            return analysis_id

    def update_analysis(self, analysis_id: str, updates: Dict[str, Any]) -> None:
        with _LOCK:
            data = self._read()
            if analysis_id not in data:
                return
            current = data[analysis_id]
            current.update(updates)
            current["updated_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
            data[analysis_id] = current
            self._write(data)

    def delete_analysis(self, analysis_id: str) -> bool:
        with _LOCK:
            data = self._read()
            if analysis_id not in data:
                return False
            del data[analysis_id]
            self._write(data)
            return True

    def get_analysis(self, analysis_id: str) -> Optional[Dict[str, Any]]:
        data = self._read()
        return data.get(analysis_id)

    def find_by_content_hash(self, content_hash: str) -> Optional[Dict[str, Any]]:
        if not content_hash:
            return None
        for a in self._read().values():
            if a.get("content_hash") == content_hash:
                return a
        return None

    def list_analyses(self) -> List[Dict[str, Any]]:
        data = self._read()
        analyses = list(data.values())
        # Sort by updated_at or created_at, newest first
        analyses.sort(
            key=lambda x: x.get('updated_at') or x.get('created_at') or '',
            reverse=True
        )
        return analyses
