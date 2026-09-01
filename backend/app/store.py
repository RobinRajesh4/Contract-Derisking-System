import json
import os
from typing import Dict, Any, List, Optional
from uuid import uuid4
from threading import RLock
from datetime import datetime


DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DATA_FILE = os.path.join(DATA_DIR, "analyses.json")


class Store:
    def __init__(self) -> None:
        os.makedirs(DATA_DIR, exist_ok=True)
        if not os.path.exists(DATA_FILE):
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump({}, f)
        self._lock = RLock()

    def _read(self) -> Dict[str, Any]:
        with self._lock:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)

    def _write(self, data: Dict[str, Any]) -> None:
        with self._lock:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def save_analysis(self, payload: Dict[str, Any]) -> str:
        data = self._read()
        analysis_id = payload.get("analysis_id") or uuid4().hex
        payload["analysis_id"] = analysis_id
        data[analysis_id] = payload
        self._write(data)
        return analysis_id

    def update_analysis(self, analysis_id: str, updates: Dict[str, Any]) -> None:
        data = self._read()
        if analysis_id not in data:
            return
        current = data[analysis_id]
        current.update(updates)
        # Add updated_at timestamp
        current["updated_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        data[analysis_id] = current
        self._write(data)

    def get_analysis(self, analysis_id: str) -> Optional[Dict[str, Any]]:
        data = self._read()
        return data.get(analysis_id)

    def list_analyses(self) -> List[Dict[str, Any]]:
        data = self._read()
        analyses = list(data.values())
        # Sort by updated_at or created_at, newest first
        analyses.sort(
            key=lambda x: x.get('updated_at') or x.get('created_at') or '',
            reverse=True
        )
        return analyses
