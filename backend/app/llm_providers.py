"""
LLM Provider abstraction for supporting multiple AI backends (Groq, Ollama).
"""
from typing import Optional, Dict, Any
from abc import ABC, abstractmethod
import os
import json

try:
    import ollama as _ollama_module  # optional python client for Ollama
    OLLAMA_PY_AVAILABLE = True
except Exception:
    _ollama_module = None
    OLLAMA_PY_AVAILABLE = False

try:
    import requests as _requests_module  # used for HTTP fallback to Ollama API
    REQUESTS_AVAILABLE = True
except Exception:
    _requests_module = None
    REQUESTS_AVAILABLE = False


# Global settings stored in memory (persisted to settings.json)
_settings: Dict[str, Any] = {
    "provider": "ollama",  # "groq" or "ollama"
    "ollama_url": "http://localhost:11434",
    "ollama_model": "deepseek-r1:14b",
    "groq_model": "llama-3.1-70b-versatile",
}

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "settings.json")


def load_settings() -> Dict[str, Any]:
    """Load settings from file."""
    global _settings
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r") as f:
                saved = json.load(f)
                _settings.update(saved)
    except Exception as e:
        print(f"Error loading settings: {e}")
    return _settings


def save_settings(settings: Dict[str, Any]) -> None:
    """Save settings to file."""
    global _settings
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


class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers."""
    
    @abstractmethod
    def invoke(self, prompt: str, system: Optional[str] = None, temperature: float = 0) -> str:
        """Invoke the LLM with a prompt and return the response content."""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if this provider is configured and available."""
        pass


class GroqProvider(BaseLLMProvider):
    """Groq API provider using LangChain."""
    
    def __init__(self):
        self.api_key = os.getenv("GROQ_API_KEY")
        self.model = _settings.get("groq_model", "llama-3.1-70b-versatile")
    
    def invoke(self, prompt: str, system: Optional[str] = None, temperature: float = 0) -> str:
        from langchain_groq import ChatGroq
        llm = ChatGroq(model=self.model, temperature=temperature)
        full_prompt = f"{system}\n{prompt}" if system else prompt
        out = llm.invoke(full_prompt)
        return getattr(out, "content", "")
    
    def is_available(self) -> bool:
        return bool(self.api_key)


class OllamaProvider(BaseLLMProvider):
    """Ollama local provider. Tries: (1) local `ollama` python client, (2) HTTP /api/generate, (3) langchain_ollama."""

    def __init__(self):
        self.base_url = _settings.get("ollama_url", "http://localhost:11434")
        # ensure default selects the exact offline model tag with :latest
        self.model = _settings.get("ollama_model", "llama3.2:latest")

    def invoke(self, prompt: str, system: Optional[str] = None, temperature: float = 0) -> str:
        """Invoke Ollama. Prefer the `ollama` python client if available, then HTTP, then LangChain wrapper.
        All external calls are constrained with a short timeout so server endpoints don't hang."""
        import concurrent.futures

        full_prompt = f"{system}\n{prompt}" if system else prompt
        TIMEOUT_SEC = 120

        def _run_with_timeout(fn, timeout=TIMEOUT_SEC):
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(fn)
                try:
                    return fut.result(timeout=timeout)
                except concurrent.futures.TimeoutError:
                    raise TimeoutError("Ollama invocation timed out")

        # 1) Try using the ollama python client if installed
        if OLLAMA_PY_AVAILABLE and _ollama_module is not None:
            try:
                def _call_client():
                    # top-level convenience functions
                    if hasattr(_ollama_module, "chat"):
                        messages = []
                        if system:
                            messages.append({"role": "system", "content": system})
                        messages.append({"role": "user", "content": prompt})
                        resp = _ollama_module.chat(model=self.model, messages=messages, temperature=temperature)
                        if isinstance(resp, dict):
                            return resp.get("content") or resp.get("text") or str(resp)
                        return str(resp)

                    if hasattr(_ollama_module, "generate"):
                        resp = _ollama_module.generate(model=self.model, prompt=full_prompt, temperature=temperature)
                        if isinstance(resp, dict):
                            return resp.get("text") or json.dumps(resp)
                        return str(resp)

                    if hasattr(_ollama_module, "Ollama"):
                        client = _ollama_module.Ollama()
                        if hasattr(client, "chat"):
                            messages = []
                            if system:
                                messages.append({"role": "system", "content": system})
                            messages.append({"role": "user", "content": prompt})
                            resp = client.chat(model=self.model, messages=messages, temperature=temperature)
                            if isinstance(resp, dict):
                                return resp.get("response") or resp.get("text") or str(resp)
                            return str(resp)

                    raise RuntimeError("No usable method found on ollama client")

                return _run_with_timeout(_call_client, TIMEOUT_SEC)
            except TimeoutError:
                # Timeout - move to HTTP fallback
                pass
            except Exception:
                # Other error - move to HTTP fallback
                pass

        # 2) HTTP fallback to Ollama local API
        if REQUESTS_AVAILABLE and _requests_module is not None:
            try:
                url = f"{self.base_url}/api/generate"
                payload = {"model": self.model, "prompt": full_prompt, "temperature": float(temperature),"stream":False}

                def _call_http():
                    r = _requests_module.post(url, json=payload, timeout=TIMEOUT_SEC)
                    r.raise_for_status()
                    # try to parse JSON if present
                    try:
                        j = r.json()
                        if isinstance(j, dict):
                            return j.get("text") or j.get("response") or json.dumps(j)
                        return str(j)
                    except Exception:
                        return r.text

                return _run_with_timeout(_call_http, TIMEOUT_SEC)
            except TimeoutError:
                pass
            except Exception:
                pass

        # 3) Fallback to langchain_ollama (existing behavior) with timeout
        try:
            from langchain_ollama import ChatOllama

            def _call_langchain():
                llm = ChatOllama(
                    model=self.model,
                    base_url=self.base_url,
                    temperature=temperature,
                )
                out = llm.invoke(full_prompt)
                return getattr(out, "content", "")

            return _run_with_timeout(_call_langchain, TIMEOUT_SEC)
        except TimeoutError:
            return ""
        except Exception:
            return ""

    def is_available(self) -> bool:
        """Check if Ollama is running and the model is available."""
        try:
            import urllib.request
            req = urllib.request.Request(f"{self.base_url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception:
            return False


def get_llm_provider() -> BaseLLMProvider:
    """Get the currently configured LLM provider."""
    provider_name = _settings.get("provider", "groq")
    
    if provider_name == "ollama":
        return OllamaProvider()
    else:
        return GroqProvider()


def get_provider_status() -> Dict[str, Any]:
    """Get status of all providers."""
    groq = GroqProvider()
    ollama = OllamaProvider()
    
    return {
        "current_provider": _settings.get("provider", "groq"),
        "groq": {
            "available": groq.is_available(),
            "model": groq.model,
        },
        "ollama": {
            "available": ollama.is_available(),
            "url": ollama.base_url,
            "model": ollama.model,
        }
    }

