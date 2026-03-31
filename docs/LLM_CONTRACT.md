# LLM Contract

## Providers

Supported providers (configured via `LLM_PROVIDER`):
- `openai` — OpenAI API (default)
- `ollama` — Local Ollama instance
- `github_models` — GitHub Models (OpenAI-compatible, uses GitHub PAT)

All providers use the OpenAI Python SDK. Provider selection happens in `LLMService._get_client()`.

## Multi-Model Support

When `LLM_AUTO_MODE=true`, requests are routed by purpose:
- `fast` — normalize, rewrite_title → uses `LLM_FAST_MODEL`
- `quality` — classify, disambiguate, description, steps → uses `LLM_QUALITY_MODEL`
- `default` — uses `LLM_MODEL` (primary)

When a tier model is not configured, falls back to the primary model.

## Fallback Behavior

If the primary model fails all retries and `LLM_FALLBACK_MODEL` is configured (and differs from primary), a single retry is attempted with the fallback model.

Each pipeline step also has hardcoded fallback heuristics (e.g. `_fallback_normalization`, `_fallback_classification`) as a last resort.

## Config Resolution

1. DB-persisted settings (`model_settings` in `app_settings` table) — highest priority
2. Environment variables (`.env`) — fallback
3. Resolved via `get_effective_llm_config(session, settings)` → `EffectiveLLMConfig`

Production call sites use `LLMService.from_effective_config(config)`.

## Pipeline

1. normalize (fast)
2. classify + route (quality)
3. description (quality)
4. disambiguate — if low confidence (quality)
5. steps — if requested (quality)

## Rules

- strict JSON responses
- retry on failure (2 attempts per model)
- fallback heuristics when LLM unavailable
- short outputs

## Title

- <= 12 words
- actionable
- English

## Next Action

- executable
- specific

Low confidence must be explicit.
