import os
import re
import json
from datetime import datetime
from typing import Dict, List, Tuple, Optional
import pandas as pd
from modules.weather_analyser import decision_maker_daily
from modules.mail_sending_module import envoyer_email


# BASE_DIR pointe vers la racine du projet (un niveau au-dessus de modules/)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_PATH = os.path.join(BASE_DIR, "data", "cache.json")


def load_env_file(path: str) -> None:
    """
    Charge un fichier .env (clé=valeur) pour garantir la présence des
    identifiants SMTP lorsque l'application est lancée manuellement ou
    par un planificateur externe.
    """
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as env_file:
            for raw_line in env_file:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and value and key not in os.environ:
                    os.environ[key] = value
    except Exception:
        pass


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


def build_conditions(entry: dict, temp_value: Optional[float], precip_value: Optional[float], wind_value: Optional[float], uv_value: Optional[float]
                     ) -> Tuple[Dict[str, float], Dict[str, float]]:
    conditions: Dict[str, float] = {}
    display: Dict[str, float] = {}

    # Flags d'activation par condition (par défaut: toutes actives pour compatibilité)
    enable_temperature = bool(entry.get("enable_temperature", True))
    enable_precipitation = bool(entry.get("enable_precipitation", True))
    enable_wind = bool(entry.get("enable_wind", True))
    enable_uv = bool(entry.get("enable_uv", True))

    # Température
    if enable_temperature and temp_value is not None:
        temp_type = entry.get("temperature_type", "minimum")
        if temp_type == "minimum":
            conditions["temp_min"] = temp_value
            display["temp_min"] = temp_value
        else:
            conditions["temp_max"] = temp_value
            display["temp_max"] = temp_value

    # Précipitations (ne rien ajouter si la condition est désactivée)
    if enable_precipitation:
        wants_rain = entry.get("wants_rain", False)
        rain_levels = entry.get("rain_levels", [])

        if isinstance(rain_levels, str):
            # Si c'est une chaîne, la convertir en liste
            rain_levels = [rain_levels] if rain_levels else []

        if wants_rain and rain_levels:
            # Calculer les plages de précipitations selon les seuils sélectionnés
            # weak: 1-3 mm/h, moderate: 4-7 mm/h, strong: >=8 mm/h
            min_precip = None
            max_precip = None

            if "weak" in rain_levels:
                min_precip = 1.0 if min_precip is None else min(min_precip, 1.0)
                max_precip = 3.0 if max_precip is None else max(max_precip, 3.0)

            if "moderate" in rain_levels:
                min_precip = 4.0 if min_precip is None else min(min_precip, 4.0)
                max_precip = 7.0 if max_precip is None else max(max_precip, 7.0)

            if "strong" in rain_levels:
                min_precip = 8.0 if min_precip is None else min(min_precip, 8.0)
                max_precip = None  # Pas de limite supérieure pour la pluie forte

            if min_precip is not None:
                conditions["precip_min"] = min_precip
                conditions["precipitations_min"] = min_precip
                display["precip_min"] = min_precip

            if max_precip is not None:
                conditions["precip_max"] = max_precip
                conditions["precipitations_max"] = max_precip
                display["precip_max"] = max_precip
            else:
                # Si seule la pluie forte est sélectionnée, on définit seulement le minimum
                if "strong" in rain_levels and len(rain_levels) == 1:
                    conditions["precip_min"] = 8.0
                    conditions["precipitations_min"] = 8.0
                    display["precip_min"] = 8.0
        elif wants_rain is False:
            # Si l'utilisateur ne veut pas de pluie, définir un maximum à 0
            conditions["precip_max"] = 0.0
            conditions["precipitations_max"] = 0.0
            display["precip_max"] = 0.0
        else:
            # Compatibilité avec l'ancien format (precipitation_type/precipitation_value)
            precip_type = entry.get("precipitation_type", "minimum")
            if precip_value is not None:
                if precip_type == "minimum":
                    conditions["precip_min"] = precip_value
                    conditions["precipitations_min"] = precip_value
                    display["precip_min"] = precip_value
                else:
                    conditions["precip_max"] = precip_value
                    conditions["precipitations_max"] = precip_value
                    display["precip_max"] = precip_value

    # Vent
    if enable_wind and wind_value is not None:
        wind_type = entry.get("wind_type", "minimum")
        if wind_type == "minimum":
            conditions["vent_min"] = wind_value
            conditions["vitesse_vent_min"] = wind_value
            display["vent_min"] = wind_value
        else:
            conditions["vent_max"] = wind_value
            conditions["vitesse_vent_max"] = wind_value
            display["vent_max"] = wind_value

    # UV
    if enable_uv and uv_value is not None:
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

        enable_temperature = bool(entry.get("enable_temperature", True))
        enable_precipitation = bool(entry.get("enable_precipitation", True))
        enable_wind = bool(entry.get("enable_wind", True))
        enable_uv = bool(entry.get("enable_uv", True))

        errors = []
        if not store_name:
            errors.append("nom du magasin manquant")
        if not postal_code:
            errors.append("code postal manquant")
        if not contact_email or "@" not in contact_email:
            errors.append("email invalide")

        temp_value = parse_float(entry.get("temperature_value"))
        if enable_temperature and temp_value is None:
            errors.append("température invalide")

        # Gérer les précipitations avec la nouvelle structure, seulement si la condition est activée
        wants_rain = entry.get("wants_rain")
        rain_levels = entry.get("rain_levels", [])

        # Compatibilité avec l'ancien format
        precip_value = parse_float(entry.get("precipitation_value"))

        if enable_precipitation:
            if wants_rain is None:
                # Ancien format : utiliser precipitation_value
                if precip_value is None:
                    errors.append("précipitations invalides")
            else:
                # Nouveau format : vérifier que si wants_rain est True, au moins un seuil est sélectionné
                if wants_rain:
                    if isinstance(rain_levels, str):
                        rain_levels = [rain_levels] if rain_levels else []
                    if not rain_levels or len(rain_levels) == 0:
                        errors.append("si vous voulez de la pluie, sélectionnez au moins un seuil")

        wind_value = parse_float(entry.get("wind_value"))
        if enable_wind and wind_value is None:
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
        "L'équipe Wellpack",
    ])
    return "\n".join(lines)


def send_alerts(decisions: dict, stores_meta: Dict[str, dict], df_daily: pd.DataFrame) -> Tuple[Dict[str, dict], dict]:
    smtp_email = os.environ.get("SMTP_EMAIL")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
    smtp_port_raw = os.environ.get("SMTP_PORT", "587")
    try:
        smtp_port = int(smtp_port_raw)
    except (TypeError, ValueError):
        smtp_port = 587

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
            serveur_smtp=smtp_server,
            port_smtp=smtp_port,
        )

        reports[store_label] = {
            "sent": bool(success),
            "message": "Email envoyé avec succès." if success else "Erreur lors de l'envoi de l'email."
        }

    smtp_context = {
        "configured": smtp_configured,
        "sender": smtp_email,
        "server": smtp_server,
        "port": smtp_port,
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


def execute_analysis(entries_raw: str) -> Tuple[dict, List[dict], List[str], dict]:
    try:
        entries = json.loads(entries_raw or "[]")
    except json.JSONDecodeError:
        entries = []

    module_rows, stores_meta, issues = transform_entries(entries)

    if not module_rows:
        summary = {
            "total": 0,
            "alerts": 0,
            "emails_sent": 0,
            "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "smtp_configured": False,
            "sender": None,
        }
        smtp_context = {"configured": False, "sender": None}
        return summary, [], issues or ["Aucune entrée valide à analyser."], smtp_context

    df_input = pd.DataFrame(module_rows)

    try:
        decisions, df_daily = decision_maker_daily(df_input)
    except Exception as exc:
        summary = {
            "total": 0,
            "alerts": 0,
            "emails_sent": 0,
            "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "smtp_configured": False,
            "sender": None,
        }
        message = f"Erreur lors de l'analyse météo : {exc}"
        smtp_context = {"configured": False, "sender": None}
        return summary, [], issues + [message], smtp_context

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

    return summary, stores_results, issues, smtp_context


def should_run_now(cache: dict) -> bool:
    return True


def mark_run(cache: dict) -> None:
    try:
        cache = dict(cache or {})
        cache["last_run"] = datetime.now().isoformat(timespec="seconds")
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

