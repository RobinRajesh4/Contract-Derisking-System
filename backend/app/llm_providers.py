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
    # Set to false only for a trusted internal server whose certificate
    # your OS/Python doesn't trust (e.g. a corporate self-signed CA).
    # Prefer installing the company's root CA instead of disabling this.
    "ollama_verify_ssl": True,
    # How many LLM calls this app fires at once against Ollama, for the
    # per-clause classification and compliance loops. Higher can cut
    # wall-clock time a lot on a server with spare capacity, but a
    # single shared box may just queue extra concurrent requests
    # rather than truly parallelize them - tune this down if raising it
    # doesn't help, or if it starts causing timeouts under load.
    "llm_concurrency": 4,
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


def _ollama_text(resp) -> str:
    """Extract generated text from an ollama client response.

    Handles both plain dicts (chat: {"message": {"content": ...}},
    generate: {"response": ...}) and the pydantic response objects that
    newer ollama client versions return.

    Raises ValueError if no usable text is found, rather than falling
    back to str(resp) - a raw response repr (e.g. from a gpt-oss reply
    that routed its answer into a hallucinated tool_calls field instead
    of content) is not a valid chat answer, and dumping it as one is
    worse than surfacing a clear failure so invoke() can try its next
    fallback tier (HTTP /api/generate, which uses a plain completion
    call rather than a chat template and is less prone to this).
    """
    if isinstance(resp, dict):
        msg = resp.get("message")
        if isinstance(msg, dict) and msg.get("content"):
            return msg["content"]
        text = resp.get("response") or resp.get("content") or resp.get("text")
        if text:
            return text
        raise ValueError(
            "Ollama response had no usable text field "
            f"(keys present: {list(resp.keys())})"
        )

    msg = getattr(resp, "message", None)
    content = getattr(msg, "content", None) if msg is not None else None
    if content:
        return content

    generate_text = getattr(resp, "response", None)
    if generate_text:
        return generate_text

    # Nothing in content/response - check whether the model routed its
    # answer into a tool call instead (observed with gpt-oss on Ollama),
    # so the failure is diagnosable rather than a silent empty string.
    tool_calls = getattr(msg, "tool_calls", None) if msg is not None else None
    if tool_calls:
        raise ValueError(
            "Ollama model returned an empty content field and instead "
            f"emitted tool_calls it was never asked to make: {tool_calls!r}. "
            "This model likely needs 'think: False' and/or an explicit "
            "\"you have no tools\" instruction in the system prompt."
        )

    raise ValueError("Ollama response had no usable text field")


def _ollama_options(temperature: float) -> Dict[str, Any]:
    """Ollama only honours sampling params inside an `options` object;
    a top-level `temperature` is silently ignored. A fixed seed makes
    temperature=0 runs reproducible."""
    opts: Dict[str, Any] = {"temperature": float(temperature)}
    if float(temperature) == 0.0:
        opts["seed"] = 0
    return opts


def _ollama_think_kwarg(model: str) -> Dict[str, Any]:
    """"Thinking" models (Qwen3, DeepSeek-R1, gpt-oss, ...) reason out
    loud by default, which is pure overhead for the strict-JSON
    micro-tasks this app runs and can also leak <think> text ahead of
    the JSON (parse_llm_json strips that as a safety net regardless).
    Ollama's `think` request param turns it off on models that support
    it; unsupported models simply ignore the field."""
    name = (model or "").lower()
    if any(tag in name for tag in ("qwen3", "deepseek-r1", "gpt-oss")):
        return {"think": False}
    return {}


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
        self.verify_ssl = bool(_settings.get("ollama_verify_ssl", True))

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

        # 1) Try using the ollama python client, pointed explicitly at
        # base_url. The module-level ollama.chat()/generate() functions
        # always talk to localhost (or $OLLAMA_HOST) and ignore any URL
        # we pass in, so we must build an ollama.Client bound to
        # base_url instead - otherwise a non-default ollama_url setting
        # (like a company server) is silently never used here.
        if OLLAMA_PY_AVAILABLE and _ollama_module is not None:
            try:
                def _call_client():
                    client_kwargs: Dict[str, Any] = {"host": self.base_url}
                    if not self.verify_ssl:
                        client_kwargs["verify"] = False

                    if hasattr(_ollama_module, "Client"):
                        client = _ollama_module.Client(**client_kwargs)
                    elif hasattr(_ollama_module, "Ollama"):
                        client = _ollama_module.Ollama(**client_kwargs)
                    else:
                        raise RuntimeError("No usable client class on ollama module")

                    messages = []
                    if system:
                        messages.append({"role": "system", "content": system})
                    messages.append({"role": "user", "content": prompt})

                    think_kwarg = _ollama_think_kwarg(self.model)
                    if hasattr(client, "chat"):
                        resp = client.chat(model=self.model, messages=messages, options=_ollama_options(temperature), **think_kwarg)
                        return _ollama_text(resp)
                    if hasattr(client, "generate"):
                        resp = client.generate(model=self.model, prompt=full_prompt, options=_ollama_options(temperature), **think_kwarg)
                        return _ollama_text(resp)

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
                payload = {"model": self.model, "prompt": full_prompt, "options": _ollama_options(temperature), "stream": False, **_ollama_think_kwarg(self.model)}

                def _call_http():
                    r = _requests_module.post(url, json=payload, timeout=TIMEOUT_SEC, verify=self.verify_ssl)
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
                kwargs: Dict[str, Any] = {
                    "model": self.model,
                    "base_url": self.base_url,
                    "temperature": temperature,
                }
                if not self.verify_ssl:
                    # Supported on recent langchain_ollama; older
                    # versions ignore unknown kwargs via **kwargs.
                    kwargs["client_kwargs"] = {"verify": False}
                llm = ChatOllama(**kwargs)
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
            import ssl
            req = urllib.request.Request(f"{self.base_url}/api/tags", method="GET")
            context = None
            if not self.verify_ssl:
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(req, timeout=5, context=context) as resp:
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

