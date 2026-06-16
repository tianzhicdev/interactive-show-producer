"""Tiered LLM routing for the harness."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx


@dataclass(frozen=True)
class ModelRoute:
    provider: str
    model: str | None
    fallbacks: tuple[str, ...] = ()
    source: str = ""


def _config_path() -> Path:
    override = os.environ.get("HARNESS_TIERS_CONFIG", "").strip()
    if override:
        return Path(override)
    return Path(__file__).with_name("tiers.json")


@lru_cache(maxsize=1)
def load_tier_config() -> dict[str, Any]:
    path = _config_path()
    if not path.exists():
        return {"version": 1, "tiers": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def _tier_role_spec(tier: str, role: str) -> dict[str, Any]:
    cfg = load_tier_config().get("tiers", {})
    tier_cfg = cfg.get(tier, {})
    roles = tier_cfg.get("roles", {})
    spec = roles.get(role)
    if not spec:
        raise KeyError(f"Unknown tier/role combination: {tier!r}/{role!r}")
    return spec


def _openrouter_api_key() -> str:
    return os.environ.get("OPENROUTER_API_KEY", "").strip()


def _zero_price(v: Any) -> bool:
    try:
        return float(v or 0) == 0.0
    except (TypeError, ValueError):
        return False


def _is_free_model(model: dict[str, Any]) -> bool:
    pricing = model.get("pricing") or {}
    return all(_zero_price(pricing.get(k)) for k in ("prompt", "completion", "request"))


def _context_length(model: dict[str, Any]) -> int:
    for key in ("context_length",):
        val = model.get(key)
        if isinstance(val, int):
            return val
    top = model.get("top_provider") or {}
    val = top.get("context_length")
    return int(val) if isinstance(val, int) else 0


def _supports_structured(model: dict[str, Any]) -> bool:
    params = model.get("supported_parameters") or []
    if isinstance(params, str):
        params = [params]
    text = {str(p).lower() for p in params if p is not None}
    return bool(text & {"json_schema", "response_format", "structured_outputs", "structured_output"})


def _fetch_openrouter_models(min_context: int, sort: str) -> list[dict[str, Any]]:
    key = _openrouter_api_key()
    if not key:
        return []
    params = {
        "max_price": 0,
        "output_modalities": "text",
        "sort": sort,
    }
    if min_context > 0:
        params["context"] = min_context
    resp = httpx.get(
        "https://openrouter.ai/api/v1/models",
        headers={"Authorization": f"Bearer {key}"},
        params=params,
        timeout=httpx.Timeout(30.0, connect=10.0),
    )
    resp.raise_for_status()
    data = resp.json()
    models = data.get("data", [])
    if not isinstance(models, list):
        return []
    free_models = [
        m for m in models
        if isinstance(m, dict)
        and _is_free_model(m)
        and _context_length(m) >= min_context
    ]
    return free_models


def _pick_free_candidates(models: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    structured = [m for m in models if _supports_structured(m)]
    others = [m for m in models if not _supports_structured(m)]
    pool = structured + others
    return pool[:count]


def _role_route(tier: str, role: str) -> ModelRoute:
    spec = _tier_role_spec(tier, role)
    provider = spec.get("provider", "")
    if provider == "claude_code":
        return ModelRoute(provider="claude_code", model=None, fallbacks=(), source=f"{tier}:{role}")
    if provider != "openrouter":
        raise ValueError(f"Unsupported provider in tier config: {provider!r}")

    min_context = int(spec.get("min_context", 0) or 0)
    sort = str(spec.get("sort", "throughput-high-to-low"))
    free_count = max(1, int(spec.get("free_candidate_count", 3) or 3))
    router_fallbacks = tuple(str(x) for x in spec.get("router_fallbacks", ["openrouter/free", "openrouter/auto"]))
    ttl = int(load_tier_config().get("tiers", {}).get(tier, {}).get("cache_ttl_s", 900) or 900)
    bucket = int(time.time() // max(1, ttl))
    models = _cached_free_models(tier, role, min_context, sort, bucket)
    candidates = _pick_free_candidates(list(models), free_count)

    if candidates:
        primary = candidates[0]
        fallbacks = tuple(m["id"] for m in candidates[1:]) + router_fallbacks
        return ModelRoute(provider="openrouter", model=str(primary["id"]), fallbacks=fallbacks,
                          source=f"{tier}:{role}:openrouter-free")

    fallback = router_fallbacks[0] if router_fallbacks else "openrouter/free"
    return ModelRoute(provider="openrouter", model=fallback,
                      fallbacks=tuple(router_fallbacks[1:]), source=f"{tier}:{role}:openrouter-fallback")


@lru_cache(maxsize=64)
def _cached_free_models(tier: str, role: str, min_context: int, sort: str, bucket: int) -> tuple[dict[str, Any], ...]:
    # bucket is the TTL window; it makes the cache refresh without needing manual invalidation.
    return tuple(_fetch_openrouter_models(min_context=min_context, sort=sort))


def get_coding_llm_model(tier: str) -> ModelRoute:
    return _role_route(tier, "coding")


def get_writing_llm_model(tier: str) -> ModelRoute:
    return _role_route(tier, "writing")


def get_eval_model(tier: str) -> ModelRoute:
    return _role_route(tier, "eval")
