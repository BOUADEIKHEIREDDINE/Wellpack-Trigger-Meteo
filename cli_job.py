import json
import os
from datetime import datetime

# Réutilise la logique existante depuis l'app Flask
from frontend import CACHE_PATH, execute_analysis, should_run_now, mark_run


def main():
    if not os.path.exists(CACHE_PATH):
        print("no_cache")
        return

    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:
        print("bad_cache")
        return

    if not should_run_now(cache):
        print("not_due")
        return

    entries_raw = cache.get("last_input", "[]")
    summary, _, issues, _ = execute_analysis(entries_raw)
    mark_run(cache)
    print(json.dumps({"ok": True, "ran": True, "at": datetime.now().isoformat(timespec="seconds"), "issues": issues, "summary": summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
*** End Patch  \n```"``` to=functions.apply_patch  буданд ***!

