"""One-shot test of the chosen LLM with the actual trade-rationale prompt."""
import os
import requests
from dotenv import load_dotenv

load_dotenv(override=True)

base = os.getenv("LITELLM_BASE_URL")
key = os.getenv("LITELLM_API_KEY")
model = os.getenv("LITELLM_MODEL")

prompt = (
    "You are a Nifty 50 options trading assistant.\n"
    "Indicators: RSI=58, MACD_hist=0.4, EMA9>EMA21, ATR=120, BB pct_b=0.65.\n"
    "Model prediction: BUY_CALL (confidence: 62%).\n"
    "Give a 2-3 line plain English trade recommendation with entry, target, stop-loss. Be concise."
)

r = requests.post(
    f"{base}/v1/chat/completions",
    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    json={
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
    },
    timeout=30,
)
print(f"Model:  {model}")
print(f"Status: {r.status_code}")
print("--- Reply ---")
print(r.json()["choices"][0]["message"]["content"])
