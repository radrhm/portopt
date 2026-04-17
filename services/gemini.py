"""Shared Gemini API client with timeout, caching, and JSON parsing."""

import concurrent.futures
import json
import logging

import requests

import config
from .cache import TTLCache

logger = logging.getLogger(__name__)

_URL_TMPL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)

_CACHE = TTLCache(maxsize=config.GEMINI_CACHE_MAXSIZE, ttl=config.GEMINI_CACHE_TTL)


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```", 2)
        if len(parts) >= 2:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
        text = text.rsplit("```", 1)[0]
    return text.strip()


def generate_json(
    prompt: str,
    *,
    cache_key: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 2048,
) -> dict | None:
    """Call Gemini and parse the response as JSON.

    Returns the parsed dict, or None on any failure (missing key, timeout,
    HTTP error, invalid JSON). Safe to use as a fallback source of text.

    If *cache_key* is provided, successful responses are cached for
    GEMINI_CACHE_TTL seconds.
    """
    api_key = config.GEMINI_API_KEY
    if not api_key:
        logger.info("GEMINI_API_KEY not configured; skipping call")
        return None

    if cache_key:
        hit = _CACHE.get(cache_key)
        if hit is not None:
            return hit

    url = _URL_TMPL.format(model=config.GEMINI_MODEL) + f"?key={api_key}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": temperature,
        },
    }

    def _call() -> dict | None:
        try:
            resp = requests.post(url, json=body, timeout=config.GEMINI_REQUEST_TIMEOUT)
            resp.raise_for_status()
            payload = resp.json()
            text = payload["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(_strip_code_fence(text))
        except requests.RequestException as exc:
            logger.warning("Gemini HTTP error: %s", exc)
        except (KeyError, IndexError, ValueError) as exc:
            logger.warning("Gemini response parsing failed: %s", exc)
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(_call)
        try:
            result = future.result(timeout=config.GEMINI_OVERALL_TIMEOUT)
        except concurrent.futures.TimeoutError:
            logger.warning("Gemini call exceeded %ss — aborting",
                           config.GEMINI_OVERALL_TIMEOUT)
            return None

    if result is not None and cache_key:
        _CACHE.set(cache_key, result)
    return result
