"""
Check Gemini API key: available models, token limits, and connectivity.

NOTE: The app now defaults to the Groq provider (Llama 4 Scout) for meal analysis.
This script only covers the Gemini *fallback* models, not Groq.

Usage:
    python check_gemini_limits.py <your_api_key>
    python check_gemini_limits.py          # reads GEMINI_API_KEY env var
"""

import sys
import os

try:
    from google import genai
except ImportError:
    print("ERROR: google-genai not installed.")
    print("Run: pip install google-genai")
    sys.exit(1)


APP_MODEL = "gemma-4-31b-it"

HIGHLIGHT_MODELS = {
    "gemma-4-31b-it",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
    "gemini-1.0-pro",
}

FREE_TIER_LIMITS = {
    "gemma-4-31b-it":    {"rpm": 30, "rpd": 14400},
    "gemini-2.5-pro":    {"rpm": 5,  "rpd": 25},
    "gemini-2.5-flash":  {"rpm": 10, "rpd": 500},
    "gemini-2.0-flash":  {"rpm": 15, "rpd": 1500},
    "gemini-1.5-pro":    {"rpm": 2,  "rpd": 50},
    "gemini-1.5-flash":  {"rpm": 15, "rpd": 1500},
    "gemini-1.0-pro":    {"rpm": 15, "rpd": 1500},
}


def short_name(full_name: str) -> str:
    return full_name.replace("models/", "")


def check(api_key: str):
    client = genai.Client(api_key=api_key)

    print("\n=== Fetching available models... ===\n")
    try:
        all_models = list(client.models.list())
    except Exception as e:
        print(f"ERROR: Could not list models — {e}")
        print("Check that your API key is correct.")
        sys.exit(1)

    # Filter to models that support generateContent (google-genai exposes this as
    # `supported_actions`, replacing the old SDK's `supported_generation_methods`).
    generative = [
        m for m in all_models
        if "generateContent" in (m.supported_actions or [])
    ]

    # Sort: highlighted models first, then alphabetical
    def sort_key(m):
        name = short_name(m.name)
        return (0 if name in HIGHLIGHT_MODELS else 1, name)

    generative.sort(key=sort_key)

    col = "{:<35} {:>12} {:>13} {:>6} {:>7}"
    header = col.format("Model", "Input tokens", "Output tokens", "RPM*", "RPD*")
    print(header)
    print("-" * len(header))

    for m in generative:
        name = short_name(m.name)
        limits = FREE_TIER_LIMITS.get(name, {})
        rpm = str(limits.get("rpm", "?"))
        rpd = str(limits.get("rpd", "?"))
        flag = "  <-- app uses this" if name == APP_MODEL else ""
        print(col.format(
            name,
            f"{m.input_token_limit:,}" if m.input_token_limit else "—",
            f"{m.output_token_limit:,}" if m.output_token_limit else "—",
            rpm,
            rpd,
        ) + flag)

    print()
    print("* RPM/RPD = free tier requests-per-minute / per-day (approximate).")
    print("  Paid tier limits are much higher — check console.cloud.google.com for exact quotas.\n")

    # Quick connectivity test
    print(f"=== Testing key with {APP_MODEL}... ===\n")
    try:
        resp = client.models.generate_content(
            model=APP_MODEL, contents="Reply with just the word: OK"
        )
        print(f"  Response: {resp.text.strip()}")
        print(f"  API key is valid and {APP_MODEL} is reachable.\n")
    except Exception as e:
        err = str(e)
        if "quota" in err.lower() or "resource_exhausted" in err.lower():
            print(f"  Daily quota exhausted — resets at UTC midnight. ({e})\n")
        elif "429" in err or "rate" in err.lower():
            print(f"  Rate limited — wait 60s and retry. ({e})\n")
        elif "api_key" in err.lower() or "invalid" in err.lower() or "403" in err:
            print(f"  Invalid API key. ({e})\n")
        else:
            print(f"  Error: {e}\n")


if __name__ == "__main__":
    key = None
    if len(sys.argv) > 1:
        key = sys.argv[1]
    else:
        key = os.environ.get("GEMINI_API_KEY")

    if not key:
        # Try reading from the app's .env file
        env_path = os.path.join(os.path.dirname(__file__), "backend", ".env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if line.startswith("GEMINI_API_KEY="):
                        key = line.split("=", 1)[1].strip().strip('"').strip("'")
                        print("(Using key from backend/.env)")
                        break

    if not key:
        print(__doc__)
        sys.exit(1)

    check(key)
