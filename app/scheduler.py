import json
from datetime import datetime
from typing import List, Tuple

import pandas as pd

from app.config.settings import CACHE_FILE
from app.core.data_to_mail import executeAnalysis, markRun, transformEntries
from app.core.weather_analyser import decisionMakerDaily

def evaluateConditions(entries_raw: str) -> Tuple[bool, List[str]]:
    try:
        entries = json.loads(entries_raw or "[]")
    except json.JSONDecodeError as exc:
        return False, [f"Entrées invalides (JSON): {exc}"]

    module_rows, _, issues = transformEntries(entries)
    if not module_rows:
        return False, issues or ["Aucune entrée exploitable pour l'analyse."]

    df_input = pd.DataFrame(module_rows)
    try:
        decisions, _ = decisionMakerDaily(df_input)
    except Exception as exc:
        issues = issues or []
        issues.append(f"Erreur lors de l'évaluation des conditions: {exc}")
        return False, issues

    return bool(decisions), issues

def shouldSendMail(previous_state: bool, conditions_ok: bool, first_run: bool) -> bool:
    if first_run:
        return conditions_ok

    if conditions_ok and not previous_state:
        return True
    if not conditions_ok and previous_state:
        return True
    return False

def main():
    if not CACHE_FILE.exists():
        print("Cache file not found.")
        return

    try:
        with CACHE_FILE.open("r", encoding="utf-8") as f:
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

    previous_state = bool(cache.get("state")) if "state" in cache else False
    first_run = "state" not in cache

    conditions_ok, eval_issues = evaluateConditions(entries_raw)
    if eval_issues:
        print("Evaluation issues:")
        for issue in eval_issues:
            print(f"- {issue}")

    send_mail = shouldSendMail(previous_state, conditions_ok, first_run)

    if send_mail:
        print(f"Starting weather analysis at {datetime.now().isoformat(timespec='seconds')}")
        summary, _, issues, _ = executeAnalysis(entries_raw)

        if issues:
            print("Issues during analysis:")
            for issue in issues:
                print(f"- {issue}")

        print(f"Analysis summary: {json.dumps(summary, ensure_ascii=False, indent=2)}")
        print(f"Weather analysis completed at {datetime.now().isoformat(timespec='seconds')}")
    else:
        print("No state change detected. Skipping email dispatch.")

    cache["state"] = conditions_ok
    markRun(cache)

if __name__ == "__main__":
    main()
