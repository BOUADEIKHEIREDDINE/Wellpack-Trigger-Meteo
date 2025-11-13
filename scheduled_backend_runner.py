import json
import os
from datetime import datetime

# Import the necessary functions from frontend.py and moduleMeteo.py
from frontend import CACHE_PATH, execute_analysis, mark_run


def main():
    if not os.path.exists(CACHE_PATH):
        print("Cache file not found.")
        return

    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            cache = json.load(f)
    except json.JSONDecodeError:
        print("Error decoding cache.json. It might be empty or malformed.")
        return
    except Exception as e:
        print(f"An unexpected error occurred while reading cache.json: {e}")
        return

    entries_raw = cache.get("last_input", "[]")

    if not entries_raw or entries_raw == "[]":
        print("No entries found in cache for analysis.")
        return

    print(f"Starting weather analysis at {datetime.now().isoformat(timespec='seconds')}")
    summary, _, issues, _ = execute_analysis(entries_raw)
    mark_run(cache)  # Mark the run to update 'last_run' timestamp in cache.json

    if issues:
        print("Issues during analysis:")
        for issue in issues:
            print(f"- {issue}")

    print(f"Analysis summary: {json.dumps(summary, ensure_ascii=False, indent=2)}")
    print(f"Weather analysis completed at {datetime.now().isoformat(timespec='seconds')}")


if __name__ == "__main__":
    main()
