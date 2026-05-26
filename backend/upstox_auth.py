"""Interactive Upstox V3 OAuth helper.

Run: python -m backend.upstox_auth

Steps:
1. Prints a Login URL — open it in your browser, log in with your Upstox account.
2. Upstox redirects to your registered redirect URI with ?code=XXX in the URL.
   The browser will likely show an SSL warning or "site can't be reached" — that's
   expected (you have no server listening there). Look at the URL bar instead.
3. Copy the code value from the URL bar, paste it here.
4. Script exchanges the code for an access token and writes it into .env.
5. Verifies the token by calling /v2/user/profile.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv

load_dotenv(override=True)

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
REDIRECT_URI = "http://127.0.0.1:8000/upstox/callback"

API_KEY = os.getenv("UPSTOX_API_KEY", "").strip()
SECRET = os.getenv("UPSTOX_SECRET", "").strip()

if not API_KEY or not SECRET:
    raise SystemExit("UPSTOX_API_KEY and UPSTOX_SECRET must be set in .env")


def build_login_url() -> str:
    params = {
        "response_type": "code",
        "client_id": API_KEY,
        "redirect_uri": REDIRECT_URI,
    }
    return f"https://api.upstox.com/v2/login/authorization/dialog?{urlencode(params)}"


def exchange_code_for_token(code: str) -> dict:
    resp = requests.post(
        "https://api.upstox.com/v2/login/authorization/token",
        headers={
            "accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "code": code,
            "client_id": API_KEY,
            "client_secret": SECRET,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise SystemExit(f"Token exchange failed: HTTP {resp.status_code}\n{resp.text}")
    return resp.json()


def verify_token(token: str) -> dict:
    resp = requests.get(
        "https://api.upstox.com/v2/user/profile",
        headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
        timeout=15,
    )
    if resp.status_code != 200:
        raise SystemExit(f"Profile fetch failed: HTTP {resp.status_code}\n{resp.text}")
    return resp.json()


def write_token_to_env(token: str) -> None:
    text = ENV_PATH.read_text(encoding="utf-8")
    if re.search(r"^UPSTOX_ACCESS_TOKEN=.*$", text, flags=re.MULTILINE):
        text = re.sub(r"^UPSTOX_ACCESS_TOKEN=.*$", f"UPSTOX_ACCESS_TOKEN={token}", text, flags=re.MULTILINE)
    else:
        text += f"\nUPSTOX_ACCESS_TOKEN={token}\n"
    ENV_PATH.write_text(text, encoding="utf-8")


def main() -> None:
    print("Upstox V3 OAuth helper\n" + "=" * 40)
    login_url = build_login_url()
    print("\nStep 1 — open this URL in your browser and log in:")
    print(f"\n  {login_url}\n")
    print("Step 2 — after login, Upstox redirects to a URL like:")
    print(f"  {REDIRECT_URI}?code=ABCDEFG...&state=...")
    print("Your browser may show an SSL warning or 'cannot connect' — IGNORE IT.")
    print("Look at the URL bar and copy ONLY the code value (between code= and &).\n")

    code = input("Paste the code here: ").strip()
    if not code:
        raise SystemExit("No code provided.")

    print("\nExchanging code for access token...")
    payload = exchange_code_for_token(code)
    token = payload.get("access_token")
    if not token:
        raise SystemExit(f"No access_token in response: {payload}")
    print("  Token received.")

    print("\nVerifying token via /v2/user/profile...")
    profile = verify_token(token)
    data = profile.get("data", {})
    print(f"  User: {data.get('user_name', '?')}  ({data.get('email', '?')})")
    print(f"  Broker: {data.get('broker', '?')}")
    print(f"  Products enabled: {data.get('products', '?')}")

    write_token_to_env(token)
    print(f"\nAccess token written to {ENV_PATH}")
    print("Token is valid until ~03:30 IST tomorrow. Re-run this script daily.")


if __name__ == "__main__":
    main()
