"""
LLM provider abstraction (R3, 愿景 #3 BYOK + 本地模型).

Two capabilities the rest of the app depends on:
  - generate(...) → text  (summaries, briefings, planning)
  - embed(texts) → vectors (relevance / dedup / clustering — the cheap workhorse)

Backends:
  - GeminiProvider          — the current default (google-genai).
  - OpenAICompatibleProvider — one impl for OpenAI AND every local runtime that
                               speaks the OpenAI REST dialect (Ollama, LM Studio,
                               vLLM, llama.cpp server). Raw `requests`, no new dep.
  - FallbackEmbedder         — deterministic hashing embedding when no model/key
                               is configured, so relevance/dedup still work in
                               pure-RSS mode (the permanent floor). Never used for
                               generation — generation degrades to "no AI".

Selection via env: LLM_PROVIDER (gemini|openai_compatible), LLM_BASE_URL,
LLM_API_KEY / GEMINI_API_KEY, LLM_MODEL, LLM_EMBED_MODEL.
"""
import os
import math
import hashlib
import re
from typing import List, Optional, Tuple

from services.log_service import get_logger

logger = get_logger("llm_provider")

_FALLBACK_DIM = 256
_TOKEN_RE = re.compile(r"[0-9a-zA-Z一-鿿぀-ヿ가-힣]+")

# One genai Client per api_key, held at module scope. Keeping a strong reference
# is not an optimization — it's required: an inline `genai.Client().models.
# generate_content(...)` let the temporary Client be garbage-collected during the
# blocking HTTP send, and its __del__ closed the underlying httpx client, so every
# generation failed with "Cannot send a request, as the client has been closed."
_GEMINI_CLIENTS: dict = {}

# Embedding resilience (P0.3). google-genai embeds one content per call, so a
# batch of N pending articles is N sequential HTTP calls. A rapid burst tripped
# the embedding RPM quota; a single 429 aborted the whole batch and NOTHING was
# persisted, so the same batch was retried every cycle forever — the semantic
# layer froze at 100/1101 articles. Pace between calls, retry transient errors,
# and skip (return None for) an item that permanently fails so one bad item never
# blocks the rest. Surfacing fatal auth/config errors is intentional — those are
# not "skip and continue" situations.
_EMBED_PACING_S = float(os.environ.get("EMBED_PACING_SECONDS", "0.15"))
_EMBED_RETRIES = int(os.environ.get("EMBED_RETRIES", "4"))
_EMBED_BACKOFF_S = float(os.environ.get("EMBED_BACKOFF_SECONDS", "2.0"))


def _embed_error_kind(msg: str) -> str:
    """Classify an embedding error: 'fatal' (auth/config — raise), 'transient'
    (rate/quota/network — retry), or 'item' (this content — skip just this one)."""
    m = (msg or "").lower()
    if any(s in m for s in ("api key", "api_key", "unauthenticated", "permission",
                            "401", "403", "invalid api", "not found", "invalid argument model")):
        return "fatal"
    if any(s in m for s in ("429", "rate", "quota", "resource_exhausted", "exhausted",
                            "timeout", "deadline", "unavailable", "503", "500", "internal")):
        return "transient"
    return "item"


def _record_embed_usage(model: str, texts) -> None:
    """Embedding calls don't return token counts; estimate (~chars/4, input only)
    so embedding spend is visible to billing and the daily-budget brake instead
    of silently counting as $0 (docs/semantic_layer_audit.md §1.2)."""
    try:
        est = sum(max(1, len(t) // 4) for t in texts)
        from llm.processor import _record_usage
        _record_usage(model, "Embedding", {
            "prompt_tokens": est, "completion_tokens": 0, "total_tokens": est, "model": model})
    except Exception:
        pass


def _l2_normalize(vec: List[float]) -> List[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0:
        return vec
    return [x / norm for x in vec]


def hashing_embed(text: str, dim: int = _FALLBACK_DIM) -> List[float]:
    """Deterministic feature-hashing embedding (the 'hashing trick'). Shared
    tokens → high cosine. Language-agnostic per-token (won't bridge languages —
    that's the model embedder's job), zero deps, reproducible. The floor that
    keeps semantic ops working with no model configured."""
    vec = [0.0] * dim
    tokens = _TOKEN_RE.findall((text or "").lower())
    for tok in tokens:
        h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
        idx = h % dim
        sign = 1.0 if (h >> 8) & 1 else -1.0
        vec[idx] += sign
    return _l2_normalize(vec)


class LLMProvider:
    name = "base"
    supports_generation = False

    def generate(self, prompt: str, *, system: Optional[str] = None, schema=None,
                 temperature: float = 0.2, model: Optional[str] = None) -> Tuple[str, dict]:
        raise NotImplementedError

    def embed(self, texts: List[str]) -> List[List[float]]:
        raise NotImplementedError


class FallbackEmbedder(LLMProvider):
    name = "fallback"
    supports_generation = False

    def generate(self, *a, **k):
        raise RuntimeError("No generation model configured (pure-RSS / no key). "
                           "Configure a provider to enable AI summaries.")

    def embed(self, texts: List[str]) -> List[List[float]]:
        return [hashing_embed(t) for t in texts]


class GeminiProvider(LLMProvider):
    name = "gemini"
    supports_generation = True

    def __init__(self, api_key: str, model: str = "gemini-3.8-flash",
                 embed_model: str = "gemini-embedding-2"):
        self.api_key = api_key
        self.model = model
        self.embed_model = embed_model

    def _client(self):
        c = _GEMINI_CLIENTS.get(self.api_key)
        if c is None:
            from google import genai
            c = genai.Client(api_key=self.api_key)
            _GEMINI_CLIENTS[self.api_key] = c
        return c

    def generate(self, prompt, *, system=None, schema=None, temperature=0.2, model=None):
        from google.genai import types
        cfg = {"temperature": temperature}
        if system:
            cfg["system_instruction"] = system
        if schema is not None:
            cfg["response_mime_type"] = "application/json"
            cfg["response_schema"] = schema
        client = self._client()  # hold a ref through the blocking send (see _client)
        resp = client.models.generate_content(
            model=model or self.model, contents=prompt,
            config=types.GenerateContentConfig(**cfg))
        usage = {}
        if getattr(resp, "usage_metadata", None):
            usage = {
                "prompt_tokens": resp.usage_metadata.prompt_token_count or 0,
                "completion_tokens": resp.usage_metadata.candidates_token_count or 0,
                "total_tokens": resp.usage_metadata.total_token_count or 0,
            }
        usage["model"] = model or self.model  # so billing attributes the real model
        return resp.text, usage

    def embed(self, texts: List[str]) -> List[Optional[List[float]]]:
        """Embed each text, one API call per text (google-genai simple API).
        Resilient (P0.3): paces calls, retries transient errors, and returns
        None for an item that permanently fails so one bad item can't abort the
        batch. Fatal auth/config errors are raised (not masked). Callers MUST
        tolerate None entries."""
        import time
        client = self._client()
        out: List[Optional[List[float]]] = []
        for idx, t in enumerate(texts):
            if idx:
                time.sleep(_EMBED_PACING_S)
            emb = None
            for attempt in range(_EMBED_RETRIES):
                try:
                    r = client.models.embed_content(model=self.embed_model, contents=t)
                    emb = r.embeddings[0].values if getattr(r, "embeddings", None) else r["embedding"]
                    break
                except Exception as e:
                    kind = _embed_error_kind(str(e))
                    if kind == "fatal":
                        raise
                    if kind == "transient" and attempt < _EMBED_RETRIES - 1:
                        time.sleep(_EMBED_BACKOFF_S * (attempt + 1))
                        continue
                    logger.warning(f"Embedding skipped one item ({kind}) after {attempt + 1} tr"
                                   f"ies: {str(e)[:160]}")
                    emb = None
                    break
            out.append(_l2_normalize(list(emb)) if emb is not None else None)
        _record_embed_usage(self.embed_model, texts)
        return out


class OpenAICompatibleProvider(LLMProvider):
    """OpenAI REST dialect: covers OpenAI and local runtimes (Ollama/LM Studio/
    vLLM/llama.cpp). base_url points at the server (e.g. http://localhost:11434/v1
    for Ollama). Uses requests directly — no openai package needed."""
    name = "openai_compatible"
    supports_generation = True

    def __init__(self, base_url: str, api_key: str = "", model: str = "gpt-4o-mini",
                 embed_model: str = "text-embedding-3-small"):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.embed_model = embed_model

    def _headers(self):
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def generate(self, prompt, *, system=None, schema=None, temperature=0.2, model=None):
        import requests
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {"model": model or self.model, "messages": messages, "temperature": temperature}
        if schema is not None:
            payload["response_format"] = {"type": "json_object"}
        r = requests.post(f"{self.base_url}/chat/completions", json=payload,
                          headers=self._headers(), timeout=120)
        r.raise_for_status()
        data = r.json()
        text = data["choices"][0]["message"]["content"]
        u = data.get("usage", {}) or {}
        _mdl = model or self.model
        usage = {
            "prompt_tokens": u.get("prompt_tokens", 0),
            "completion_tokens": u.get("completion_tokens", 0),
            "total_tokens": u.get("total_tokens", 0),
            "model": _mdl,
        }
        return text, usage

    def embed(self, texts: List[str]) -> List[List[float]]:
        import requests
        r = requests.post(f"{self.base_url}/embeddings",
                          json={"model": self.embed_model, "input": texts},
                          headers=self._headers(), timeout=120)
        r.raise_for_status()
        data = r.json()
        _record_embed_usage(self.embed_model, texts)
        return [_l2_normalize(list(item["embedding"])) for item in data["data"]]


def get_provider() -> LLMProvider:
    """Resolve the configured provider. Falls back to the deterministic embedder
    (no generation) when nothing is configured."""
    kind = os.environ.get("LLM_PROVIDER", "gemini").lower()
    if kind == "openai_compatible":
        base_url = os.environ.get("LLM_BASE_URL", "").strip()
        if not base_url:
            logger.warning("LLM_PROVIDER=openai_compatible but LLM_BASE_URL unset; using fallback embedder.")
            return FallbackEmbedder()
        return OpenAICompatibleProvider(
            base_url=base_url,
            api_key=os.environ.get("LLM_API_KEY", ""),
            model=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
            embed_model=os.environ.get("LLM_EMBED_MODEL", "text-embedding-3-small"),
        )
    # Default: Gemini.
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("LLM_API_KEY")
    if not api_key:
        return FallbackEmbedder()
    return GeminiProvider(
        api_key=api_key,
        model=os.environ.get("LLM_MODEL", "gemini-3.8-flash"),
        embed_model=os.environ.get("LLM_EMBED_MODEL", "gemini-embedding-2"),
    )


def get_embedder() -> LLMProvider:
    """Provider for embeddings. Always available: the fallback embedder needs no
    key, so relevance/dedup/clustering work even in pure-RSS mode."""
    try:
        p = get_provider()
        # Fallback embedder is fine; other providers must expose embed().
        return p
    except Exception as e:
        logger.warning(f"Provider init failed ({e}); using fallback embedder.")
        return FallbackEmbedder()
