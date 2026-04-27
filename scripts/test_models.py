from pathlib import Path

from dotenv import load_dotenv

load_dotenv(
    Path(
        r"C:\Users\vokor\Documents\Projects\chronos-ai\.env"
    )
)

import os
import time

import requests

API_KEY = os.getenv("OPENROUTER_API_KEY", "")
MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-3-27b-it:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
    "deepseek/deepseek-r1:free",
    "google/gemma-3-12b-it:free",
]

PROMPT = '{"test": true}'
SYSTEM = "Return only valid JSON. No explanation."

results: dict[str, str] = {}
for model in MODELS:
    print(f"Testing {model}...")
    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": PROMPT},
                ],
                "max_tokens": 50,
                "temperature": 0.0,
                "response_format": {"type": "json_object"},
            },
            timeout=30,
        )
        if r.status_code == 200:
            data = r.json()
            content = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            if content and content.strip():
                results[model] = "WORKS"
                print(f"  WORKS: {content[:60]}")
            else:
                results[model] = "200_EMPTY"
                print("  200 but EMPTY content")
        else:
            results[model] = f"HTTP_{r.status_code}"
            print(f"  FAIL: HTTP {r.status_code}")
    except Exception as e:
        results[model] = f"ERROR: {str(e)[:40]}"
        print(f"  ERROR: {e}")

    time.sleep(4)

print()
print("=== SUMMARY ===")
for model, status in results.items():
    name = model.split("/")[-1].replace(":free", "")
    print(f"  {status:15} {name}")

working = [m for m, s in results.items() if s == "WORKS"]
print(
    f"\nWorking models: {len(working)}/{len(MODELS)}"
)
