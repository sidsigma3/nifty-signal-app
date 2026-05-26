"""Plain-English explanation via LiteLLM proxy."""
from __future__ import annotations

import os
import requests
from dotenv import load_dotenv

load_dotenv(override=True)

LITELLM_BASE_URL = os.getenv("LITELLM_BASE_URL", "http://localhost:4000")
LITELLM_API_KEY = os.getenv("LITELLM_API_KEY", "")
LITELLM_MODEL = os.getenv("LITELLM_MODEL", "gemini/gemini-2.0-flash")


def explain_signal(indicators: dict, prediction: str, confidence: float) -> str:
    prompt = f"""You are a Nifty 50 options trading assistant.

Current indicators: {indicators}
Model prediction: {prediction} (confidence: {confidence:.0%})

Give a 2-3 line plain English trade recommendation with entry, target, and stop-loss.
Be concise. Mention the dominant indicator driving the call.
"""
    try:
        response = requests.post(
            f"{LITELLM_BASE_URL}/v1/chat/completions",
            headers={"Authorization": f"Bearer {LITELLM_API_KEY}"},
            json={
                "model": LITELLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
            },
            timeout=20,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        return f"[LLM explanation unavailable: {exc}]"
