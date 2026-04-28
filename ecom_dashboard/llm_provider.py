"""
Multi-provider LLM abstraction with env-based switching.

Environment variables:
  - LLM_PROVIDER: "gemini" | "openai" | "claude"  (default: gemini)
  - GEMINI_API_KEY
  - OPENAI_API_KEY
  - ANTHROPIC_API_KEY

Behavior:
  - generate_response(prompt) routes to the selected provider
  - If provider=gemini fails, it falls back to OpenAI (if OPENAI_API_KEY exists)
  - Includes logging + timeout protection
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass
from typing import Callable, Optional

logger = logging.getLogger("llm_provider")
if not logger.handlers:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


class LLMProviderError(RuntimeError):
    pass


class LLMConfigurationError(LLMProviderError):
    pass


class LLMTimeoutError(LLMProviderError):
    pass


@dataclass(frozen=True)
class ProviderResult:
    provider: str
    text: str
    latency_s: float


def _run_with_timeout(fn: Callable[[], str], timeout_s: float) -> str:
    # Thread timeout is the most portable option on Windows.
    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(fn)
        try:
            return fut.result(timeout=timeout_s)
        except FuturesTimeout as e:
            raise LLMTimeoutError(f"LLM request timed out after {timeout_s}s") from e


def _is_transient_error(msg: str) -> bool:
    m = (msg or "").lower()
    return any(
        k in m
        for k in (
            "rate limit",
            "429",
            "timeout",
            "temporarily unavailable",
            "unavailable",
            "overloaded",
            "connection reset",
            "connection error",
        )
    )


def _call_gemini(prompt: str, api_key: str, timeout_s: float) -> ProviderResult:
    t0 = time.time()

    def _do() -> str:
        import google.generativeai as genai  # type: ignore

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(os.getenv("GEMINI_MODEL", "gemini-1.5-flash"))
        # generate_content is a blocking network call
        resp = model.generate_content(prompt)
        text = getattr(resp, "text", None) or ""
        return str(text).strip()

    text = _run_with_timeout(_do, timeout_s=timeout_s)
    return ProviderResult(provider="gemini", text=text, latency_s=time.time() - t0)


def _call_openai(prompt: str, api_key: str, timeout_s: float) -> ProviderResult:
    t0 = time.time()

    def _do() -> str:
        from openai import OpenAI  # type: ignore

        client = OpenAI(api_key=api_key, timeout=timeout_s)
        model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        # Responses API (OpenAI python >= 1.x)
        resp = client.responses.create(model=model, input=prompt)
        text = getattr(resp, "output_text", None)
        if text:
            return str(text).strip()

        # Fallback for any edge case where output_text isn't set
        out = []
        for item in getattr(resp, "output", []) or []:
            for c in getattr(item, "content", []) or []:
                if getattr(c, "type", "") == "output_text":
                    out.append(getattr(c, "text", ""))
        return ("\n".join(out)).strip()

    text = _run_with_timeout(_do, timeout_s=timeout_s)
    return ProviderResult(provider="openai", text=text, latency_s=time.time() - t0)


def _call_claude(prompt: str, api_key: str, timeout_s: float) -> ProviderResult:
    t0 = time.time()

    def _do() -> str:
        from anthropic import Anthropic  # type: ignore

        client = Anthropic(api_key=api_key, timeout=timeout_s)
        model = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
        msg = client.messages.create(
            model=model,
            max_tokens=int(os.getenv("ANTHROPIC_MAX_TOKENS", "1024")),
            messages=[{"role": "user", "content": prompt}],
        )
        # msg.content is a list of content blocks
        parts = []
        for blk in getattr(msg, "content", []) or []:
            if getattr(blk, "type", "") == "text":
                parts.append(getattr(blk, "text", ""))
        return ("\n".join(parts)).strip()

    text = _run_with_timeout(_do, timeout_s=timeout_s)
    return ProviderResult(provider="claude", text=text, latency_s=time.time() - t0)


def generate_response(prompt: str) -> str:
    """
    Common function for the rest of the codebase.
    Uses env-based provider switching + Gemini→OpenAI fallback.
    """
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt must be a non-empty string")

    provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    timeout_s = float(os.getenv("LLM_TIMEOUT_S", "30"))

    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()

    def _try(provider_name: str) -> ProviderResult:
        logger.info("LLM provider=%s", provider_name)
        if provider_name == "gemini":
            if not gemini_key:
                raise LLMConfigurationError("GEMINI_API_KEY is missing")
            return _call_gemini(prompt, api_key=gemini_key, timeout_s=timeout_s)
        if provider_name == "openai":
            if not openai_key:
                raise LLMConfigurationError("OPENAI_API_KEY is missing")
            return _call_openai(prompt, api_key=openai_key, timeout_s=timeout_s)
        if provider_name in ("claude", "anthropic"):
            if not anthropic_key:
                raise LLMConfigurationError("ANTHROPIC_API_KEY is missing")
            return _call_claude(prompt, api_key=anthropic_key, timeout_s=timeout_s)
        raise LLMConfigurationError(f"Unknown LLM_PROVIDER='{provider_name}' (use gemini|openai|claude)")

    try:
        res = _try(provider)
        logger.info("LLM success provider=%s latency=%.2fs", res.provider, res.latency_s)
        return res.text
    except Exception as e:
        msg = str(e)
        logger.warning("LLM failure provider=%s error=%s", provider, msg)

        # Required fallback: Gemini → OpenAI (only if OpenAI key exists)
        if provider == "gemini" and openai_key:
            try:
                res2 = _try("openai")
                logger.info("LLM fallback success provider=%s latency=%.2fs", res2.provider, res2.latency_s)
                return res2.text
            except Exception as e2:
                raise LLMProviderError(f"Gemini failed, OpenAI fallback failed: {e2}") from e2

        # If no fallback is configured, raise a clear error
        if _is_transient_error(msg):
            raise LLMProviderError(f"LLM temporarily unavailable: {msg}") from e
        raise LLMProviderError(msg) from e

