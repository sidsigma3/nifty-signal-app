"""Probe every model the LiteLLM proxy exposes; report which actually answer.

Run: python -m backend.test_litellm
"""
from __future__ import annotations

import os
import time

import requests
from dotenv import load_dotenv

load_dotenv(override=True)

BASE = os.getenv("LITELLM_BASE_URL", "http://127.0.0.1:4000").rstrip("/")
KEY = os.getenv("LITELLM_API_KEY", "sk-1234")
HEADERS = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}


def list_models() -> list[str]:
    r = requests.get(f"{BASE}/v1/models", headers=HEADERS, timeout=10)
    r.raise_for_status()
    return [m["id"] for m in r.json().get("data", [])]


def test_model(name: str, timeout: int = 20) -> tuple[bool, str]:
    body = {
        "model": name,
        "messages": [{"role": "user", "content": "Reply with the single word: OK"}],
        "max_tokens": 8,
        "temperature": 0,
    }
    t0 = time.time()
    try:
        r = requests.post(f"{BASE}/v1/chat/completions", headers=HEADERS, json=body, timeout=timeout)
        dt = time.time() - t0
        if r.status_code == 200:
            content = r.json()["choices"][0]["message"]["content"].strip()
            return True, f"{dt:.1f}s  reply={content!r}"
        return False, f"HTTP {r.status_code}  {r.text[:120]}"
    except Exception as exc:
        return False, f"exception: {exc}"


def main() -> None:
    print(f"Probing LiteLLM at {BASE}\n")
    try:
        models = list_models()
    except Exception as exc:
        print(f"Cannot list models: {exc}")
        return

    print(f"Found {len(models)} models. Testing each (<=20s timeout)...\n")
    working: list[str] = []
    for name in models:
        ok, info = test_model(name)
        flag = "OK " if ok else "FAIL"
        print(f"  [{flag}] {name:40s}  {info}")
        if ok:
            working.append(name)

    print("\n--- Working models ---")
    for w in working:
        print(f"  {w}")
    if working:
        print(f"\nSet one in .env, e.g.:\n  LITELLM_MODEL={working[0]}")


if __name__ == "__main__":
    main()
