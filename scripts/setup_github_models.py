#!/usr/bin/env python3
"""Interactive setup for GitHub Models as Chiefly LLM provider.

Usage:
    python scripts/setup_github_models.py

Validates the PAT against the GitHub Models catalog, lets you pick
models for each tier, and writes the result into your .env file.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

CATALOG_URL = "https://models.github.ai/catalog/models"
INFERENCE_URL = "https://models.github.ai/inference"


def _read_env() -> list[str]:
    if ENV_FILE.exists():
        return ENV_FILE.read_text(encoding="utf-8").splitlines(keepends=True)
    return []


def _upsert_env(lines: list[str], key: str, value: str) -> list[str]:
    prefix = f"{key}="
    replaced = False
    result: list[str] = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith(prefix):
            result.append(f"{key}={value}\n")
            replaced = True
        else:
            result.append(line)
    if not replaced:
        if result and not result[-1].endswith("\n"):
            result.append("\n")
        result.append(f"{key}={value}\n")
    return result


def _fetch_catalog(pat: str) -> list[dict]:
    import urllib.request
    import json

    req = urllib.request.Request(
        CATALOG_URL,
        headers={"Authorization": f"Bearer {pat}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            if isinstance(data, list):
                return data
            return data.get("models", data.get("items", []))
    except Exception as exc:
        print(f"\n❌ Failed to fetch model catalog: {exc}")
        return []


def _test_inference(pat: str, model_id: str) -> bool:
    import urllib.request
    import json

    body = json.dumps(
        {
            "model": model_id,
            "messages": [{"role": "user", "content": "Say hi in one word."}],
            "max_tokens": 5,
        }
    ).encode()
    req = urllib.request.Request(
        f"{INFERENCE_URL}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {pat}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return bool(content)
    except Exception as exc:
        print(f"  ⚠ Inference test failed: {exc}")
        return False


def _pick_model(models: list[dict], tier: str, default: str = "") -> str:
    print(f"\n{'─' * 40}")
    print(f"Select model for {tier} tier:")
    if default:
        print(f"  (press Enter for default: {default})")

    for i, m in enumerate(models, 1):
        name = m.get("name") or m.get("id", "?")
        publisher = m.get("publisher", "")
        label = f"{publisher}/{name}" if publisher else name
        print(f"  {i:>3}. {label}")

    while True:
        choice = input(f"\n{tier} model [#/name/Enter=skip]: ").strip()
        if not choice:
            return default
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(models):
                m = models[idx]
                name = m.get("name") or m.get("id", "?")
                publisher = m.get("publisher", "")
                return f"{publisher}/{name}" if publisher else name
            print("  Invalid number, try again.")
            continue
        return choice


def main() -> None:
    print("=" * 50)
    print("  Chiefly — GitHub Models Setup")
    print("=" * 50)
    print()
    print("This script configures GitHub Models as your LLM provider.")
    print("You need a GitHub PAT with the 'models:read' scope.")
    print("Create one at: https://github.com/settings/tokens")
    print()

    pat = input("GitHub PAT (ghp_...): ").strip()
    if not pat:
        print("No token entered, aborting.")
        sys.exit(1)

    print("\nValidating token against GitHub Models catalog...")
    models = _fetch_catalog(pat)
    if not models:
        print("Could not fetch models. Check your token and try again.")
        sys.exit(1)

    chat_models = [
        m
        for m in models
        if "chat" in str(m.get("task", "")).lower()
        or "completion" in str(m.get("task", "")).lower()
        or "text-generation" in str(m.get("task", "")).lower()
        or not m.get("task")
    ]
    if not chat_models:
        chat_models = models

    print(f"\n✅ Token valid! Found {len(chat_models)} chat-capable models.")

    primary = _pick_model(chat_models, "primary (default)")
    if not primary:
        print("No primary model selected, aborting.")
        sys.exit(1)

    print(f"\nTesting inference with {primary}...")
    if _test_inference(pat, primary):
        print("✅ Inference test passed!")
    else:
        print(
            "⚠ Inference test failed — continuing anyway (model might need different permissions)."
        )

    enable_auto = input("\nEnable auto mode (fast/quality model tiers)? [y/N]: ").strip().lower()
    fast_model = ""
    quality_model = ""
    fallback_model = ""
    auto_mode = "false"

    if enable_auto == "y":
        auto_mode = "true"
        fast_model = _pick_model(chat_models, "fast (lightweight tasks)", primary)
        quality_model = _pick_model(chat_models, "quality (complex reasoning)", primary)

    fallback_model = _pick_model(chat_models, "fallback (when primary fails)", "")

    print(f"\n{'─' * 50}")
    print("Configuration summary:")
    print(f"  Provider:       github_models")
    print(f"  Primary model:  {primary}")
    print(f"  API key:        {pat[:8]}...{pat[-4:]}")
    print(f"  Auto mode:      {auto_mode}")
    if auto_mode == "true":
        print(f"  Fast model:     {fast_model}")
        print(f"  Quality model:  {quality_model}")
    if fallback_model:
        print(f"  Fallback model: {fallback_model}")
    print(f"{'─' * 50}")

    confirm = input("\nWrite to .env? [Y/n]: ").strip().lower()
    if confirm == "n":
        print("Aborted.")
        sys.exit(0)

    lines = _read_env()
    lines = _upsert_env(lines, "LLM_PROVIDER", "github_models")
    lines = _upsert_env(lines, "LLM_MODEL", primary)
    lines = _upsert_env(lines, "LLM_API_KEY", pat)
    lines = _upsert_env(lines, "LLM_BASE_URL", "")
    lines = _upsert_env(lines, "LLM_FAST_MODEL", fast_model)
    lines = _upsert_env(lines, "LLM_QUALITY_MODEL", quality_model)
    lines = _upsert_env(lines, "LLM_FALLBACK_MODEL", fallback_model)
    lines = _upsert_env(lines, "LLM_AUTO_MODE", auto_mode)

    ENV_FILE.write_text("".join(lines), encoding="utf-8")
    print(f"\n✅ Written to {ENV_FILE}")
    print("Restart Chiefly to apply the new configuration.")


if __name__ == "__main__":
    main()
