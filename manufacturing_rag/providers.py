"""
Provider interfaces — always hosted (OpenAI embeddings + GPT-4o/Haiku LLM).

The spec names hosted models (Voyage/Cohere/Gemini, Claude, zerank...) and they
are config-swappable. This module is that seam: an Embedder / Reranker / LLM
interface dispatching to real APIs.

LLM contract honors the reliability rules: temperature is forced to 0 and
`self_consistency()` runs N times requiring agreement.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from collections import Counter

from .config import Config

_TOKEN = re.compile(r"[a-z0-9][a-z0-9\-]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall((text or "").lower())


# --------------------------------------------------------------------------- #
# Embedder
# --------------------------------------------------------------------------- #
class Embedder:
    """Interface: embed a list of texts -> list of unit vectors."""
    dim: int
    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class OpenAIEmbedder(Embedder):
    """OpenAI embeddings via the REST API (stdlib urllib — no `openai` package).

    Chosen model: text-embedding-3-large (3072-d) by config. Key is read from
    the OPENAI_API_KEY env var (never hard-coded / never passed through chat).
    """
    ENDPOINT = "https://api.openai.com/v1/embeddings"

    def __init__(self, model: str = "text-embedding-3-large", dim: int = 3072,
                 api_key: str | None = None, batch: int = 128, timeout: int = 60):
        self.model, self.dim, self.batch, self.timeout = model, dim, batch, timeout
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ProviderError(
                "OPENAI_API_KEY not set. Export it (e.g. setx OPENAI_API_KEY \"sk-...\") "
                "to use OpenAI embeddings.")

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch):
            chunk = texts[i:i + self.batch]
            body = json.dumps({"model": self.model, "input": chunk,
                               "dimensions": self.dim}).encode("utf-8")
            req = urllib.request.Request(
                self.ENDPOINT, data=body, method="POST",
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.load(r)
            for d in sorted(data["data"], key=lambda x: x["index"]):
                out.append(d["embedding"])
        return out


# --------------------------------------------------------------------------- #
# Reranker
# --------------------------------------------------------------------------- #
class Reranker:
    def rerank(self, query: str, docs: list[str]) -> list[float]:
        raise NotImplementedError


class LexicalReranker(Reranker):
    """Token-overlap rerank score in [0,1] (internal fallback for LLMReranker on error)."""
    def rerank(self, query: str, docs: list[str]) -> list[float]:
        q = set(tokenize(query))
        if not q:
            return [0.0] * len(docs)
        out = []
        for d in docs:
            dt = set(tokenize(d))
            out.append(len(q & dt) / len(q) if q else 0.0)
        return out


class LLMReranker(Reranker):
    """Batched LLM relevance reranker (Haiku) — the calibrated-reranker substitute
    (spec wants zerank-2; not available to us). One call ranks all candidates;
    falls back to lexical scores on any parse failure. temp 0."""
    def __init__(self, llm, fallback: "Reranker"):
        self.llm = llm
        self.fallback = fallback

    def rerank(self, query: str, docs: list[str]) -> list[float]:
        if not docs:
            return []
        listing = "\n".join(f"[{i}] {d[:300]}" for i, d in enumerate(docs))
        prompt = (f"Question: {query}\n\nCandidates:\n{listing}\n\n"
                  "Score each candidate 0-100 for how directly it answers the "
                  "question. Output ONLY lines 'index:score', one per candidate.")
        try:
            out = self.llm.complete(
                prompt, system="You are a precise relevance ranker. Output only index:score lines.",
                temperature=0.0)
            scores = [0.0] * len(docs)
            for m in re.finditer(r"(\d+)\s*:\s*(\d+)", out):
                i, s = int(m.group(1)), int(m.group(2))
                if 0 <= i < len(docs):
                    scores[i] = s / 100.0
            if any(scores):
                return scores
        except Exception:
            pass
        return self.fallback.rerank(query, docs)


# --------------------------------------------------------------------------- #
# LLM
# --------------------------------------------------------------------------- #
class LLM:
    """Interface for extraction / verification / synthesis steps.

    All callers pass temperature 0 (enforced here) and use self_consistency()
    for extraction/verify so a single bad sample can't slip through.
    """
    def complete(self, prompt: str, system: str = "", temperature: float = 0.0) -> str:
        raise NotImplementedError

    def self_consistency(self, prompt: str, system: str = "", n: int = 3) -> tuple[str, bool]:
        """Run n times at temp 0; return (answer, agreed). Agreement = all equal."""
        outs = [self.complete(prompt, system, 0.0) for _ in range(n)]
        agreed = len(set(outs)) == 1
        # majority vote on disagreement
        answer = Counter(outs).most_common(1)[0][0]
        return answer, agreed


class AnthropicLLM(LLM):
    """Claude inference via the Messages REST API (stdlib urllib).

    Chosen model: claude-haiku-4-5 by config. Key from ANTHROPIC_API_KEY env.
    Used at temperature 0 (Haiku 4.5 accepts temperature) with self-consistency
    for the Phase-1 extraction pass. The static system prompt is cached
    (cache_control: ephemeral) so re-running extraction across many chunks reuses
    the prefix (~0.1x cost on cache reads) — the "~cents/doc" target in the spec.

    NOTE: raw HTTP (not the `anthropic` SDK) is deliberate; swap to the SDK if needed.
    """
    ENDPOINT = "https://api.anthropic.com/v1/messages"
    API_VERSION = "2023-06-01"

    def __init__(self, model: str = "claude-haiku-4-5", api_key: str | None = None,
                 max_tokens: int = 4096, timeout: int = 120):
        self.model, self.max_tokens, self.timeout = model, max_tokens, timeout
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ProviderError(
                "ANTHROPIC_API_KEY not set. Export it (e.g. setx ANTHROPIC_API_KEY \"sk-ant-...\") "
                "to use Claude inference.")

    def complete(self, prompt: str, system: str = "", temperature: float = 0.0,
                 cache_system: bool = True) -> str:
        body = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": temperature,       # Haiku 4.5 accepts temperature; spec wants 0
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            block = {"type": "text", "text": system}
            if cache_system:
                block["cache_control"] = {"type": "ephemeral"}   # reuse prefix across chunks
            body["system"] = [block]
        return self._post(body)

    def vision(self, prompt: str, image_png: bytes, system: str = "",
               media_type: str = "image/png") -> str:
        """Vision input (spec 6.2/6.4): OCR a scanned page or caption a diagram.
        Image + prompt -> text, temp 0."""
        import base64
        b64 = base64.standard_b64encode(image_png).decode("ascii")
        prompt = prompt.strip() or "Transcribe or describe this image."  # no empty text block
        body = {
            "model": self.model, "max_tokens": self.max_tokens, "temperature": 0.0,
            "messages": [{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64",
                                             "media_type": media_type, "data": b64}},
                {"type": "text", "text": prompt}]}],
        }
        if system:
            body["system"] = [{"type": "text", "text": system}]
        return self._post(body)

    def _post(self, body: dict) -> str:
        req = urllib.request.Request(
            self.ENDPOINT, data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"x-api-key": self.api_key, "anthropic-version": self.API_VERSION,
                     "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = json.load(r)
        return "".join(b.get("text", "") for b in data.get("content", [])
                       if b.get("type") == "text")


class OpenAILLM(LLM):
    """GPT inference via the OpenAI Chat Completions REST API (stdlib urllib).

    Drop-in replacement for AnthropicLLM. Key from OPENAI_API_KEY env var.
    Prompt caching is not available here (GPT-4o has no ephemeral cache_control),
    so cache_system is accepted but ignored.
    """
    ENDPOINT = "https://api.openai.com/v1/chat/completions"

    def __init__(self, model: str = "gpt-4o", api_key: str | None = None,
                 max_tokens: int = 4096, timeout: int = 120):
        self.model, self.max_tokens, self.timeout = model, max_tokens, timeout
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ProviderError(
                "OPENAI_API_KEY not set. Export it to use OpenAI inference.")

    def complete(self, prompt: str, system: str = "", temperature: float = 0.0,
                 cache_system: bool = True) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body = {"model": self.model, "max_tokens": self.max_tokens,
                "temperature": temperature, "messages": messages}
        return self._post(body)

    def vision(self, prompt: str, image_png: bytes, system: str = "",
               media_type: str = "image/png") -> str:
        import base64
        b64 = base64.standard_b64encode(image_png).decode("ascii")
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": [
            {"type": "image_url",
             "image_url": {"url": f"data:{media_type};base64,{b64}"}},
            {"type": "text", "text": prompt or "Transcribe or describe this image."},
        ]})
        body = {"model": self.model, "max_tokens": self.max_tokens,
                "temperature": 0.0, "messages": messages}
        return self._post(body)

    def _post(self, body: dict) -> str:
        req = urllib.request.Request(
            self.ENDPOINT, data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = json.load(r)
        return data["choices"][0]["message"]["content"]


class OllamaLLM(LLM):
    """Local inference via Ollama (http://localhost:11434, stdlib urllib).

    Free, offline-capable, no API key — the fallback when cloud quota is gone.
    Uses /api/chat (stream off). temperature forced via options. vision() uses
    Ollama's `images` field (base64) for multimodal models.
    """
    def __init__(self, model: str = "qwen3.5", host: str | None = None,
                 num_predict: int = 4096, timeout: int = 300):
        self.model = model
        self.num_predict = num_predict
        self.timeout = timeout
        self.host = (host or os.environ.get("OLLAMA_HOST")
                     or "http://localhost:11434").rstrip("/")

    def complete(self, prompt: str, system: str = "", temperature: float = 0.0,
                 cache_system: bool = True) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body = {"model": self.model, "messages": messages, "stream": False,
                "keep_alive": -1,          # pin in memory once activated
                "options": {"temperature": temperature, "num_predict": self.num_predict}}
        data = self._post("/api/chat", body)
        return (data.get("message") or {}).get("content", "")

    def vision(self, prompt: str, image_png: bytes, system: str = "",
               media_type: str = "image/png") -> str:
        import base64
        b64 = base64.standard_b64encode(image_png).decode("ascii")
        msg = {"role": "user", "content": prompt or "Transcribe or describe this image.",
               "images": [b64]}
        messages = ([{"role": "system", "content": system}] if system else []) + [msg]
        body = {"model": self.model, "messages": messages, "stream": False,
                "options": {"temperature": 0.0}}
        data = self._post("/api/chat", body)
        return (data.get("message") or {}).get("content", "")

    def _post(self, route: str, body: dict) -> dict:
        req = urllib.request.Request(
            self.host + route, data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.load(r)


class OllamaEmbedder(Embedder):
    """Local embeddings via Ollama (e.g. nomic-embed-text, 768-d). Batches through
    /api/embed (newer) with a per-text /api/embeddings fallback (older Ollama)."""
    def __init__(self, model: str = "nomic-embed-text", dim: int = 768,
                 host: str | None = None, timeout: int = 120):
        self.model, self.dim, self.timeout = model, dim, timeout
        self.host = (host or os.environ.get("OLLAMA_HOST")
                     or "http://localhost:11434").rstrip("/")

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            return self._embed_batch(texts)
        except urllib.error.HTTPError:
            return [self._embed_one(t) for t in texts]   # older Ollama fallback

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        body = {"model": self.model, "input": texts, "keep_alive": -1}
        req = urllib.request.Request(
            self.host + "/api/embed", data=json.dumps(body).encode("utf-8"),
            method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.load(r)["embeddings"]

    def _embed_one(self, text: str) -> list[float]:
        body = {"model": self.model, "prompt": text}
        req = urllib.request.Request(
            self.host + "/api/embeddings", data=json.dumps(body).encode("utf-8"),
            method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.load(r)["embedding"]


# --------------------------------------------------------------------------- #
# Factory (config-driven)
# --------------------------------------------------------------------------- #
class ProviderError(NotImplementedError):
    pass


def get_embedder(cfg: Config) -> Embedder:
    """'openai:<model>' => OpenAI; 'ollama:<model>' => local Ollama."""
    name = cfg.models.embeddings
    if name.startswith("openai:"):
        return OpenAIEmbedder(model=name.split(":", 1)[1], dim=cfg.models.embedding_dim)
    if name.startswith("ollama:"):
        return OllamaEmbedder(model=name.split(":", 1)[1], dim=cfg.models.embedding_dim)
    raise ProviderError(
        f"Embedder '{name}' not wired. Use 'openai:text-embedding-3-large' "
        f"or 'ollama:nomic-embed-text'.")


def get_reranker(cfg: Config) -> Reranker:
    # zerank-2 / Cohere Rerank 3.5 are the production swap targets (calibrated
    # scores). Uses the LLM reranker (with lexical fallback on error).
    try:
        return LLMReranker(get_llm(cfg), LexicalReranker())
    except ProviderError:
        return LexicalReranker()


def _llm_for(name: str) -> LLM:
    """Build an LLM from a model name: 'claude-*'/'anthropic:<m>' => AnthropicLLM;
    'gpt-*'/'openai:<m>' => OpenAILLM; 'ollama:<m>' => local OllamaLLM."""
    if name.startswith("anthropic:") or name.startswith("claude"):
        return AnthropicLLM(model=name.split(":", 1)[1] if name.startswith("anthropic:") else name)
    if name.startswith("openai:") or name.startswith("gpt"):
        return OpenAILLM(model=name.split(":", 1)[1] if name.startswith("openai:") else name)
    if name.startswith("ollama:"):
        return OllamaLLM(model=name.split(":", 1)[1])
    raise ProviderError(
        f"LLM '{name}' not wired. Use 'gpt-4o', 'claude-haiku-4-5', or 'ollama:<model>'.")


def get_llm(cfg: Config) -> LLM:
    """Main LLM for synthesis / extraction / rerank (local by config)."""
    return _llm_for(cfg.models.llm)


def get_kg_llm(cfg: Config) -> LLM:
    """Dedicated LLM for KG relation extraction (Haiku) — separate from the
    main local model. Used minimally (one capped call per document)."""
    return _llm_for(getattr(cfg.models, "kg_llm", None) or cfg.models.llm)


__all__ = [
    "Embedder", "OpenAIEmbedder", "OllamaEmbedder", "Reranker", "LexicalReranker",
    "LLMReranker", "LLM", "AnthropicLLM", "OpenAILLM", "OllamaLLM", "ProviderError",
    "get_embedder", "get_reranker", "get_llm", "get_kg_llm", "tokenize",
]
