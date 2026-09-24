"""
LLM provider abstraction (Ollama, Groq).

Two model "tiers" are used, selected per task:
- "bulk":    many small calls per contract (clause classification,
             policy compliance, check applicability). Speed matters.
- "quality": one call per contract or per chat question (contract
             metadata extraction, executive summary, chat answers,
             chat question routing). Accuracy matters more than speed.
"""
from typing import Optional, Dict, Any
from abc import ABC, abstractmethod
import json
import os
import threading
import time

import requests


# Global settings stored in memory (persisted to settings.json)
_settings: Dict[str, Any] = {
    "provider": "ollama",  # "groq" or "ollama"
    "ollama_url": "http://localhost:11434",
    # Model for the many small per-clause calls.
    "ollama_model": "qwen3:8b",
    # Model for per-contract extraction, summaries and chat.
    "ollama_quality_model": "qwen3:32b",
    "groq_model": "llama-3.1-70b-versatile",
    # Set to false only for a trusted internal server whose certificate
    # your OS/Python doesn't trust (e.g. a corporate self-signed CA).
    # Prefer installing the company's root CA instead of disabling this.
    "ollama_verify_ssl": True,
    # How many LLM calls run at once for the per-clause loops. A shared
    # server may queue rather than parallelize extra requests; lower
    # this if raising it doesn't help or causes timeouts.
    "llm_concurrency": 4,
    # Ollama's default context window is only 2048 tokens. Anything
    # past it is silently cut off, and the model then answers without
    # the data it needed. Keep this comfortably above the longest
    # prompt (the chat prompt grows with the number of contracts).
    "ollama_num_ctx": 16384,
    # Seconds to wait for one LLM response before giving up.
    "llm_timeout_sec": 240,
    # Embeddings for clause search. Leave embedding_url empty to use
    # ollama_url. Changing the model needs a re-index
    # (POST /admin/reindex); each model gets its own collection, so
    # switching back and forth never mixes incompatible vectors.
    "embedding_url": "",
    "embedding_model": "qwen3-embedding:8b",
}

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "settings.json")

# Keys the /settings endpoint may change.
EDITABLE_SETTINGS = [
    "provider",
    "ollama_url",
    "ollama_model",
    "ollama_quality_model",
    "groq_model",
    "ollama_verify_ssl",
    "llm_concurrency",
    "ollama_num_ctx",
    "llm_timeout_sec",
    "embedding_url",
    "embedding_model",
]


class LLMError(RuntimeError):
    """An LLM call failed or returned nothing usable."""


def load_settings() -> Dict[str, Any]:
    """Load settings from file."""
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r") as f:
                _settings.update(json.load(f))
    except Exception as e:
        print(f"Error loading settings: {e}")
    return _settings


def save_settings(settings: Dict[str, Any]) -> None:
    """Save settings to file."""
    _settings.update(settings)
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(_settings, f, indent=2)
    except Exception as e:
        print(f"Error saving settings: {e}")


def get_settings() -> Dict[str, Any]:
    """Get current settings."""
    return _settings.copy()


# Load settings on module import
load_settings()


def verify_ssl() -> bool:
    return bool(_settings.get("ollama_verify_ssl", True))


_warned_insecure = False


def silence_insecure_warning_if_needed() -> None:
    """When certificate checks are deliberately off for an internal
    server, urllib3 prints a warning on every single request, burying
    the useful log lines. Silence it once, and say so once."""
    global _warned_insecure
    if verify_ssl() or _warned_insecure:
        return
    try:
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass
    print(
        "[settings] ollama_verify_ssl is false: HTTPS certificate checks "
        "are disabled for the Ollama server."
    )
    _warned_insecure = True


def model_for_task(task: str = "bulk") -> str:
    if task == "quality":
        return str(
            _settings.get("ollama_quality_model")
            or _settings.get("ollama_model")
        )
    return str(_settings.get("ollama_model"))


def _think_value(model: str) -> Optional[Any]:
    """Reasoning models think out loud by default, which slows every
    call and can put text ahead of the JSON. Turn it off where the
    model allows it. gpt-oss cannot switch reasoning off, only lower
    it; other models don't take the field at all."""
    name = (model or "").lower()
    if "gpt-oss" in name:
        return "low"
    if any(tag in name for tag in ("qwen3", "deepseek-r1")):
        return False
    return None


class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers."""

    model: str = ""

    @abstractmethod
    def invoke(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0,
        json_schema: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Return the model's text reply. When json_schema is given,
        providers that support it constrain the output to that schema.
        Raises LLMError on failure instead of returning an empty
        string, so callers can't mistake a failure for an answer."""

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this provider is configured and reachable."""


class GroqProvider(BaseLLMProvider):
    """Groq API provider using LangChain."""

    def __init__(self, model: Optional[str] = None):
        self.api_key = os.getenv("GROQ_API_KEY")
        self.model = model or _settings.get("groq_model", "llama-3.1-70b-versatile")

    def invoke(self, prompt, system=None, temperature=0, json_schema=None) -> str:
        from langchain_groq import ChatGroq

        llm = ChatGroq(model=self.model, temperature=temperature)
        full_prompt = f"{system}\n{prompt}" if system else prompt
        out = llm.invoke(full_prompt)
        text = getattr(out, "content", "") or ""
        if not text.strip():
            raise LLMError("Groq returned an empty response")
        return text

    def is_available(self) -> bool:
        return bool(self.api_key)


# Remembered once per process: an older Ollama server that rejects
# JSON-schema "format" or the "think" field is retried without them,
# and later calls skip straight to what works.
_server_caps = {"format_schema": True, "think": True}
_availability_cache: Dict[str, Any] = {"url": None, "ok": False, "at": 0.0}
_availability_lock = threading.Lock()


class OllamaProvider(BaseLLMProvider):
    """Ollama over its HTTP /api/chat endpoint."""

    def __init__(self, model: Optional[str] = None):
        self.base_url = str(_settings.get("ollama_url", "http://localhost:11434")).rstrip("/")
        self.model = model or model_for_task("bulk")
        self.verify = verify_ssl()
        silence_insecure_warning_if_needed()

    def _payload(self, prompt, system, temperature, json_schema, use_format, use_think):
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        options: Dict[str, Any] = {
            "temperature": float(temperature),
            "num_ctx": int(_settings.get("ollama_num_ctx", 8192)),
        }
        if float(temperature) == 0.0:
            options["seed"] = 0

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": options,
        }
        think = _think_value(self.model)
        if use_think and think is not None:
            payload["think"] = think
        if json_schema is not None:
            payload["format"] = json_schema if use_format else "json"
        return payload

    def invoke(self, prompt, system=None, temperature=0, json_schema=None) -> str:
        timeout = float(_settings.get("llm_timeout_sec", 240))
        use_format = _server_caps["format_schema"]
        use_think = _server_caps["think"]
        last_error: Optional[str] = None

        for attempt in range(3):
            payload = self._payload(prompt, system, temperature, json_schema, use_format, use_think)
            try:
                r = requests.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                    timeout=timeout,
                    verify=self.verify,
                )
            except requests.Timeout:
                raise LLMError(
                    f"Ollama model {self.model} did not answer within {timeout:.0f}s"
                )
            except requests.RequestException as e:
                last_error = f"network error: {e}"
                time.sleep(1.5)
                continue

            if r.status_code == 400:
                body = r.text.lower()
                # Older servers: retry without the newer request fields.
                if "format" in payload and use_format and "format" in body:
                    _server_caps["format_schema"] = False
                    use_format = False
                    continue
                if "think" in payload and "think" in body:
                    _server_caps["think"] = False
                    use_think = False
                    continue
            if r.status_code >= 400:
                raise LLMError(
                    f"Ollama returned HTTP {r.status_code} for model "
                    f"{self.model}: {r.text[:300]}"
                )

            try:
                data = r.json()
            except ValueError:
                raise LLMError("Ollama returned a non-JSON response")

            # Ollama silently cuts prompts that don't fit the context
            # window, and the model then answers without that part.
            # A prompt that used every slot was almost certainly cut.
            num_ctx = int(_settings.get("ollama_num_ctx", 8192))
            evaluated = int(data.get("prompt_eval_count") or 0)
            if evaluated >= num_ctx - 8:
                raise LLMError(
                    f"The request to {self.model} filled the whole context window "
                    f"({num_ctx} tokens), so part of it was cut off and the answer "
                    "could not be trusted. Increase ollama_num_ctx in settings.json."
                )

            message = data.get("message") or {}
            content = message.get("content") or ""
            if content.strip():
                return content
            if message.get("tool_calls"):
                raise LLMError(
                    f"{self.model} returned a tool call instead of an answer"
                )
            if message.get("thinking"):
                raise LLMError(
                    f"{self.model} returned only reasoning and no answer"
                )
            raise LLMError(f"{self.model} returned an empty response")

        raise LLMError(f"Could not reach Ollama at {self.base_url} ({last_error})")

    def is_available(self) -> bool:
        """Checked before every call, so cache the result briefly
        instead of listing every model on the server each time."""
        with _availability_lock:
            now = time.time()
            if (
                _availability_cache["url"] == self.base_url
                and now - _availability_cache["at"] < 30
            ):
                return _availability_cache["ok"]
            try:
                r = requests.get(
                    f"{self.base_url}/api/tags", timeout=5, verify=self.verify
                )
                ok = r.status_code == 200
            except requests.RequestException:
                ok = False
            _availability_cache.update({"url": self.base_url, "ok": ok, "at": now})
            return ok


def get_llm_provider(task: str = "bulk") -> BaseLLMProvider:
    """Provider for a task tier: "bulk" or "quality"."""
    if _settings.get("provider", "ollama") == "ollama":
        return OllamaProvider(model=model_for_task(task))
    return GroqProvider()


def get_provider_status() -> Dict[str, Any]:
    """Get status of all providers."""
    groq = GroqProvider()
    ollama = OllamaProvider()
    return {
        "current_provider": _settings.get("provider", "groq"),
        "groq": {"available": groq.is_available(), "model": groq.model},
        "ollama": {
            "available": ollama.is_available(),
            "url": ollama.base_url,
            "model": model_for_task("bulk"),
            "quality_model": model_for_task("quality"),
            "embedding_model": _settings.get("embedding_model"),
        },
    }
