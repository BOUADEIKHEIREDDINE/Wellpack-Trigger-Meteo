from flask import Flask, render_template, request
import os
import threading
import time
import webbrowser
import re
import json
from datetime import datetime
from typing import Dict, List, Tuple, Optional

import pandas as pd

from moduleMeteo import decision_maker_daily
from mailSendingModule import envoyer_email


BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# Les templates sont situés dans le même dossier que ce script
app = Flask(__name__, template_folder=BASE_DIR)


def sanitize_store_name(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").lower()
    return slug or "magasin"


def parse_float(value) -> Optional[float]:
    if value in (None, "", " ", "null"):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None


def parse_int(
    value,
    *,
    default: int = 0,
    minimum: Optional[int] = None,
    maximum: Optional[int] = None,
) -> int:
    try:
        result = int(float(value))
    except (TypeError, ValueError):
        result = default
    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result


def build_conditions(entry: dict, temp_value: float, precip_value: float, wind_value: float, uv_value: Optional[float]
                     ) -> Tuple[Dict[str, float], Dict[str, float]]:
    conditions: Dict[str, float] = {}
    display: Dict[str, float] = {}

    temp_type = entry.get("temperature_type", "minimum")
    if temp_type == "minimum":
        conditions["temp_min"] = temp_value
        display["temp_min"] = temp_value
    else:
        conditions["temp_max"] = temp_value
        display["temp_max"] = temp_value

    precip_type = entry.get("precipitation_type", "minimum")
    if precip_type == "minimum":
        conditions["precip_min"] = precip_value
        conditions["precipitations_min"] = precip_value
        display["precip_min"] = precip_value
    else:
        conditions["precip_max"] = precip_value
        conditions["precipitations_max"] = precip_value
        display["precip_max"] = precip_value

    wind_type = entry.get("wind_type", "minimum")
    if wind_type == "minimum":
        conditions["vent_min"] = wind_value
        conditions["vitesse_vent_min"] = wind_value
        display["vent_min"] = wind_value
    else:
        conditions["vent_max"] = wind_value
        conditions["vitesse_vent_max"] = wind_value
        display["vent_max"] = wind_value

    if uv_value is not None:
        conditions["uv_min"] = uv_value
        display["uv_min"] = uv_value

    return conditions, display


def transform_entries(entries: List[dict]) -> Tuple[List[dict], Dict[str, dict], List[str]]:
    modules_rows: List[dict] = []
    stores_meta: Dict[str, dict] = {}
    issues: List[str] = []
    seen_labels: set[str] = set()

    for idx, entry in enumerate(entries, start=1):
        store_name = (entry.get("store_name") or "").strip()
        postal_code = str(entry.get("postal_code") or "").strip()
        contact_email = (entry.get("contact_email") or "").strip()
        analyze_past = bool(entry.get("analyze_past"))

        errors = []
        if not store_name:
            errors.append("nom du magasin manquant")
        if not postal_code:
            errors.append("code postal manquant")
        if not contact_email or "@" not in contact_email:
            errors.append("email invalide")

        temp_value = parse_float(entry.get("temperature_value"))
        if temp_value is None:
            errors.append("température invalide")

        precip_value = parse_float(entry.get("precipitation_value"))
        if precip_value is None:
            errors.append("précipitations invalides")

        wind_value = parse_float(entry.get("wind_value"))
        if wind_value is None:
            errors.append("vitesse du vent invalide")

        uv_value = parse_float(entry.get("uv_min"))

        days_future = parse_int(entry.get("days_future", 0), default=0, minimum=0, maximum=5)
        days_past = parse_int(entry.get("days_past", 0), default=0, minimum=0, maximum=5) if analyze_past else 0

        if errors:
            issues.append(f"Ligne {idx}: " + ", ".join(errors))
            continue

        base_label = f"{store_name} ({postal_code})"
        label = base_label
        suffix = 2
        while label in seen_labels:
            label = f"{base_label} #{suffix}"
            suffix += 1
        seen_labels.add(label)

        conditions, display_conditions = build_conditions(entry, temp_value, precip_value, wind_value, uv_value)

        modules_rows.append({
            "magasin": label,
            "code_postal": postal_code,
            "conditions_meteo": conditions,
            "delai_jours_avant": days_past,
            "delai_jours_apres": days_future,
            "mail": contact_email,
        })

        stores_meta[label] = {
            "store_name": store_name,
            "postal_code": postal_code,
            "email": contact_email,
            "conditions": display_conditions,
            "raw_conditions": conditions,
            "window": {"avant": days_past, "apres": days_future},
        }

    return modules_rows, stores_meta, issues


def format_conditions_display(conditions: Dict[str, float]) -> List[dict]:
    mapping = [
        ("temp_min", "Température min.", "°C"),
        ("temp_max", "Température max.", "°C"),
        ("precip_min", "Précipitations min.", "mm"),
        ("precip_max", "Précipitations max.", "mm"),
        ("vent_min", "Vent min.", "km/h"),
        ("vent_max", "Vent max.", "km/h"),
        ("uv_min", "Indice UV min.", ""),
    ]
    items = []
    for key, label, unit in mapping:
        value = conditions.get(key)
        if value is None:
            continue
        formatted = f"{value:.1f}".rstrip("0").rstrip(".")
        if unit:
            formatted = f"{formatted} {unit}"
        items.append({"label": label, "value": formatted})
    if not items:
        items.append({"label": "Conditions", "value": "Aucune contrainte définie"})
    return items


def format_number(value, decimals: int = 1) -> str:
    if value in (None, "", "nan"):
        return "—"
    try:
        formatted = f"{float(value):.{decimals}f}"
        formatted = formatted.rstrip("0").rstrip(".")
        return formatted or "0"
    except (TypeError, ValueError):
        return str(value)


def build_email_body(store_label: str, store_meta: dict, store_daily: pd.DataFrame) -> str:
    window = store_meta.get("window", {"avant": 0, "apres": 0})
    conditions_display = format_conditions_display(store_meta.get("conditions", {}))

    lines = [
        "Bonjour,",
        "",
        f"Les conditions météorologiques définies pour {store_label} sont réunies sur la période "
        f"J-{window.get('avant', 0)} à J+{window.get('apres', 0)}.",
        "",
        "Seuils configurés :",
    ]
    for cond in conditions_display:
        lines.append(f" • {cond['label']} : {cond['value']}")

    lines.append("")
    if store_daily.empty:
        lines.append("⚠️ Les données météo détaillées n'ont pas pu être récupérées.")
    else:
        lines.append("Prévision détaillée :")
        for _, row in store_daily.iterrows():
            day_status = "✅ Conforme" if bool(row.get("state")) else "⚠️ Non conforme"
            date_str = row.get("date") or "N/A"
            jour = row.get("jour_relatif") or "-"
            temp = format_number(row.get("temp_12h"))
            vent = format_number(row.get("vent_12h"))
            precip = format_number(row.get("precipitations_12h"))
            lines.append(
                f"{day_status} · {jour} ({date_str}) — Temp {temp}°C · Vent {vent} km/h · Précip {precip} mm"
            )

    lines.extend([
        "",
        "Cordialement,",
        "L’équipe Wellpack",
    ])
    return "\n".join(lines)


def send_alerts(decisions: dict, stores_meta: Dict[str, dict], df_daily: pd.DataFrame) -> Tuple[Dict[str, dict], dict]:
    smtp_email = os.environ.get("SMTP_EMAIL")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    smtp_configured = bool(smtp_email and smtp_password)

    reports: Dict[str, dict] = {}

    for store_label, meta in stores_meta.items():
        if store_label not in decisions:
            reports[store_label] = {
                "sent": False,
                "message": "Conditions météo non respectées sur toute la période."
            }
            continue

        recipient = decisions.get(store_label)
        if not recipient or str(recipient).lower() == "nan":
            reports[store_label] = {
                "sent": False,
                "message": "Aucune adresse e-mail renseignée pour ce point de vente."
            }
            continue

        if not smtp_configured:
            reports[store_label] = {
                "sent": False,
                "message": "Identifiants SMTP manquants (variables SMTP_EMAIL et SMTP_PASSWORD)."
            }
            continue

        store_daily = pd.DataFrame()
        if not df_daily.empty:
            store_daily = df_daily[df_daily["magasin"] == store_label].copy()

        subject = f"Alerte météo déclenchée - {store_label}"
        body = build_email_body(store_label, meta, store_daily)

        success = envoyer_email(
            expediteur_email=smtp_email,
            expediteur_password=smtp_password,
            destinataire_email=recipient,
            sujet=subject,
            corps_message=body,
        )

        reports[store_label] = {
            "sent": bool(success),
            "message": "Email envoyé avec succès." if success else "Erreur lors de l'envoi de l'email."
        }

    smtp_context = {
        "configured": smtp_configured,
        "sender": smtp_email,
    }

    return reports, smtp_context


def build_results_payload(
    stores_meta: Dict[str, dict],
    decisions: dict,
    df_daily: pd.DataFrame,
    email_reports: Dict[str, dict],
) -> List[dict]:
    results = []
    for store_label, meta in stores_meta.items():
        store_days = []
        if not df_daily.empty:
            subset = df_daily[df_daily["magasin"] == store_label].copy()
            for _, row in subset.iterrows():
                store_days.append({
                    "date": row.get("date"),
                    "jour": row.get("jour_relatif"),
                    "temp": format_number(row.get("temp_12h")),
                    "vent": format_number(row.get("vent_12h")),
                    "precip": format_number(row.get("precipitations_12h")),
                    "state": bool(row.get("state")),
                    "error": row.get("erreur"),
                })

        alert_triggered = store_label in decisions
        email_status = email_reports.get(store_label, {"sent": False, "message": "Aucune notification envoyée."})

        results.append({
            "label": store_label,
            "store_name": meta["store_name"],
            "postal_code": meta["postal_code"],
            "email": meta["email"],
            "window": meta["window"],
            "conditions": format_conditions_display(meta.get("conditions", {})),
            "raw_conditions": meta.get("conditions", {}),
            "days": store_days,
            "alert_triggered": alert_triggered,
            "email_status": email_status,
        })
    return results


@app.route("/", methods=["GET"]) 
def index():
    return render_template("index.html")


@app.route("/submit", methods=["POST"]) 
def submit():
    entries_raw = request.form.get("entries_payload", "[]")

    try:
        entries = json.loads(entries_raw)
    except json.JSONDecodeError:
        entries = []

    module_rows, stores_meta, issues = transform_entries(entries)

    if not module_rows:
        error_message = "Ajoutez au moins un point de vente avant de lancer l'analyse."
        if issues:
            error_message = issues[0]
        return render_template(
            "index.html",
            error_message=error_message,
            form_data={"entries_payload": entries_raw},
        )

    df_input = pd.DataFrame(module_rows)

    try:
        decisions, df_daily = decision_maker_daily(df_input)
    except Exception as exc:
        return render_template(
            "index.html",
            error_message=f"Erreur lors de l'analyse météo : {exc}",
            form_data={"entries_payload": entries_raw},
        )

    df_daily = df_daily if isinstance(df_daily, pd.DataFrame) else pd.DataFrame()
    email_reports, smtp_context = send_alerts(decisions, stores_meta, df_daily)
    stores_results = build_results_payload(stores_meta, decisions, df_daily, email_reports)

    total_points = len(stores_results)
    triggered_points = sum(1 for store in stores_results if store["alert_triggered"])
    emails_sent = sum(1 for store in stores_results if store["email_status"].get("sent"))

    summary = {
        "total": total_points,
        "alerts": triggered_points,
        "emails_sent": emails_sent,
        "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "smtp_configured": smtp_context.get("configured", False),
        "sender": smtp_context.get("sender"),
    }

    return render_template(
        "results.html",
        summary=summary,
        stores=stores_results,
        issues=issues,
        smtp=smtp_context,
    )


if __name__ == "__main__":
    # Ouvre automatiquement le navigateur en HTTP simple
    def open_browser():
        time.sleep(1)
        webbrowser.open_new("http://127.0.0.1:5000")

    threading.Thread(target=open_browser, daemon=True).start()

    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)


