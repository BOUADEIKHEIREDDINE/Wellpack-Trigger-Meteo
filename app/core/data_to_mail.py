import os
import re
import json
from datetime import datetime
from typing import Dict, List, Tuple, Optional

import pandas as pd

from app.config.settings import CACHE_FILE, CONDITIONS_FILE
from .weather_analyser import decision_maker_daily
from .mail_sending import envoyer_email

CACHE_PATH = str(CACHE_FILE)

MAX_CONSECUTIVE_FAILURES = 7
FAILURE_THRESHOLD_ENABLED = True

def validate_smtp_config() -> Tuple[Optional[str], Optional[str], str, int]:

    smtp_email = os.getenv("SMTP_EMAIL")
    smtp_password = os.getenv("SMTP_PASSWORD")
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port_raw = os.getenv("SMTP_PORT", "587")

    if not smtp_email:
        raise ValueError(
            "Variable d'environnement SMTP_EMAIL manquante.\n"
            "En local: créez un fichier .env à la racine avec SMTP_EMAIL=votre_email@gmail.com\n"
            "En production: définissez-la via GitHub Secrets"
        )
    if not smtp_password:
        raise ValueError(
            "Variable d'environnement SMTP_PASSWORD manquante.\n"
            "En local: créez un fichier .env à la racine avec SMTP_PASSWORD=votre_mot_de_passe\n"
            "En production: définissez-la via GitHub Secrets"
        )

    try:
        smtp_port = int(smtp_port_raw)
    except (TypeError, ValueError):
        smtp_port = 587

    return smtp_email, smtp_password, smtp_server, smtp_port

def load_env_file(path: str) -> None:
    if not os.path.isfile(path):
        return
    try:
        loaded_count = 0
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
                    loaded_count += 1
        if loaded_count > 0:
            print(f"[INFO] {loaded_count} variable(s) chargee(s) depuis .env")
    except Exception as e:
        print(f"[WARNING] Erreur lors du chargement du fichier .env: {e}")

def load_failure_counters() -> Dict[str, int]:
    try:
        if CACHE_FILE.exists():
            with CACHE_FILE.open("r", encoding="utf-8") as f:
                cache = json.load(f)
                return cache.get("failure_counters", {})
    except Exception:
        pass
    return {}

def save_failure_counters(counters: Dict[str, int]) -> None:
    try:
        cache = {}
        if CACHE_FILE.exists():
            with CACHE_FILE.open("r", encoding="utf-8") as f:
                cache = json.load(f)
        
        cache["failure_counters"] = counters
        
        with CACHE_FILE.open("w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Erreur sauvegarde compteurs: {e}")

def update_failure_counter(store_label: str, success: bool) -> Tuple[int, bool]:
    if not FAILURE_THRESHOLD_ENABLED:
        return 0, True
    
    counters = load_failure_counters()
    
    if success:
        if store_label in counters:
            del counters[store_label]
        save_failure_counters(counters)
        return 0, True
    else:
        current_count = counters.get(store_label, 0) + 1
        counters[store_label] = current_count
        save_failure_counters(counters)
        
        should_notify = current_count < MAX_CONSECUTIVE_FAILURES
        return current_count, should_notify

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

def _parse_precip_cell(value) -> Tuple[bool, List[str]]:
    if value in (None, "", " "):
        return False, []

    text = str(value).strip().lower()
    wants_rain = True
    levels: List[str] = []

    if "tout" in text:
        levels = ["weak", "moderate", "strong"]
    else:
        if "faible" in text:
            levels.append("weak")
        if "modér" in text or "modere" in text:
            levels.append("moderate")
        if "forte" in text or "fort" in text:
            levels.append("strong")

    if not levels:
        return False, []

    return wants_rain, levels

_THRESHOLD_RE = re.compile(r"([<>]=?)\s*([-+]?\d+(?:[.,]\d+)?)")

def _parse_threshold_cell(value) -> Tuple[Optional[str], Optional[float]]:
    if value in (None, "", " "):
        return None, None

    s = str(value).strip()
    m = _THRESHOLD_RE.match(s)
    if not m:
        return None, None

    op, num = m.groups()
    try:
        val = float(str(num).replace(",", "."))
    except (TypeError, ValueError):
        return None, None

    threshold_type = "minimum" if ">" in op else "maximum"
    return threshold_type, val

def build_entries_from_excel(file_obj) -> List[dict]:

    df = pd.read_excel(file_obj, header=None)

    email_global = ""
    try:
        val = df.iat[1, 2]
        if val is not None and not (isinstance(val, float) and pd.isna(val)):
            email_global = str(val).strip()
    except Exception:
        email_global = ""

    entries: List[dict] = []

    for row_idx in range(3, len(df)):
        try:
            store_name = df.iat[row_idx, 2]
            postal_code = df.iat[row_idx, 3]
        except Exception:
            continue

        if (store_name is None or (isinstance(store_name, float) and pd.isna(store_name))) and (
            postal_code is None or (isinstance(postal_code, float) and pd.isna(postal_code))
        ):
            continue

        store_name_str = "" if store_name is None else str(store_name).strip()
        postal_code_str = "" if postal_code is None else str(postal_code).strip()

        if not store_name_str and not postal_code_str:
            continue

        days_past_raw = df.iat[row_idx, 4] if df.shape[1] > 4 else 0
        days_future_raw = df.iat[row_idx, 5] if df.shape[1] > 5 else 0
        days_past = parse_int(days_past_raw or 0, default=0, minimum=0, maximum=5)
        days_future = parse_int(days_future_raw or 0, default=0, minimum=0, maximum=5)

        precip_raw = df.iat[row_idx, 6] if df.shape[1] > 6 else None
        wants_rain, rain_levels = _parse_precip_cell(precip_raw)

        wind_raw = df.iat[row_idx, 7] if df.shape[1] > 7 else None
        wind_type, wind_value = _parse_threshold_cell(wind_raw)
        wind_value_str = "" if wind_value is None else str(wind_value)
        if wind_type is None:
            wind_type = "minimum"
            wind_value_str = "0"

        temp_raw = df.iat[row_idx, 8] if df.shape[1] > 8 else None
        temp_type, temp_value = _parse_threshold_cell(temp_raw)
        temp_value_str = "" if temp_value is None else str(temp_value)
        if temp_type is None:
            temp_type = "minimum"
            temp_value_str = "0"

        uv_raw = df.iat[row_idx, 9] if df.shape[1] > 9 else None
        _, uv_value = _parse_threshold_cell(uv_raw)
        uv_value_str = "" if uv_value is None else str(uv_value)

        entry = {
            "store_name": store_name_str,
            "postal_code": postal_code_str,
            "contact_email": email_global,
            "analyze_past": days_past > 0,
            "days_past": days_past,
            "days_future": days_future,
            "wants_rain": wants_rain,
            "rain_levels": rain_levels,
            "wind_type": wind_type,
            "wind_value": wind_value_str,
            "temperature_type": temp_type,
            "temperature_value": temp_value_str,
            "uv_min": uv_value_str,
        }

        entries.append(entry)

    return entries

def build_conditions(entry: dict, temp_value: float, precip_value: Optional[float], wind_value: float, uv_value: Optional[float]
                     ) -> Tuple[Dict[str, float], Dict[str, float]]:
    conditions: Dict[str, float] = {}
    display: Dict[str, float] = {}

    enable_temperature = entry.get("enable_temperature", True)
    enable_precipitation = entry.get("enable_precipitation", True)
    enable_wind = entry.get("enable_wind", True)
    enable_uv = entry.get("enable_uv", True)

    conditions["_enable_temperature"] = enable_temperature
    conditions["_enable_precipitation"] = enable_precipitation
    conditions["_enable_wind"] = enable_wind
    conditions["_enable_uv"] = enable_uv

    if enable_temperature:
    temp_type = entry.get("temperature_type", "minimum")
    if temp_type == "minimum":
        conditions["temp_min"] = temp_value
        display["temp_min"] = temp_value
    else:
        conditions["temp_max"] = temp_value
        display["temp_max"] = temp_value

    if enable_precipitation:
    wants_rain = entry.get("wants_rain", False)
    rain_levels = entry.get("rain_levels", [])
    
    if isinstance(rain_levels, str):
        rain_levels = [rain_levels] if rain_levels else []
    
    if wants_rain and rain_levels:
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
                max_precip = None
        
        if min_precip is not None:
            conditions["precip_min"] = min_precip
            conditions["precipitations_min"] = min_precip
            display["precip_min"] = min_precip
        
        if max_precip is not None:
            conditions["precip_max"] = max_precip
            conditions["precipitations_max"] = max_precip
            display["precip_max"] = max_precip
        else:
            if "strong" in rain_levels and len(rain_levels) == 1:
                conditions["precip_min"] = 8.0
                conditions["precipitations_min"] = 8.0
                display["precip_min"] = 8.0
    elif not wants_rain:
        conditions["precip_max"] = 0.0
        conditions["precipitations_max"] = 0.0
        display["precip_max"] = 0.0
    else:
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

    if enable_wind:
    wind_type = entry.get("wind_type", "minimum")
    if wind_type == "minimum":
        conditions["vent_min"] = wind_value
        conditions["vitesse_vent_min"] = wind_value
        display["vent_min"] = wind_value
    else:
        conditions["vent_max"] = wind_value
        conditions["vitesse_vent_max"] = wind_value
        display["vent_max"] = wind_value

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

        errors = []
        if not store_name:
            errors.append("nom du magasin manquant")
        if not postal_code:
            errors.append("code postal manquant")
        if not contact_email or "@" not in contact_email:
            errors.append("email invalide")

        enable_temperature = entry.get("enable_temperature", True)
        enable_precipitation = entry.get("enable_precipitation", True)
        enable_wind = entry.get("enable_wind", True)
        enable_uv = entry.get("enable_uv", True)

        temp_value = parse_float(entry.get("temperature_value"))
        if enable_temperature and temp_value is None:
            errors.append("température invalide")

        wants_rain = entry.get("wants_rain")
        rain_levels = entry.get("rain_levels", [])
        
        precip_value = parse_float(entry.get("precipitation_value"))
        
        if enable_precipitation:
        if wants_rain is None:
            if precip_value is None:
                errors.append("précipitations invalides")
        else:
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

        non_conformes = store_daily[~store_daily.get("state", False)] if not store_daily.empty else pd.DataFrame()
        if not non_conformes.empty:
            lines.append("")
            lines.append("Jours non conformes tolérés :")
            for _, row in non_conformes.iterrows():
                date_str = row.get("date") or "N/A"
                jour = row.get("jour_relatif") or "-"
                temp = format_number(row.get("temp_12h"))
                vent = format_number(row.get("vent_12h"))
                precip = format_number(row.get("precipitations_12h"))
                lines.append(f" • {jour} ({date_str}) — Temp {temp}°C · Vent {vent} km/h · Précip {precip} mm")

    lines.extend([
        "",
        "Cordialement,",
        "L'équipe Wellpack",
    ])
    return "\n".join(lines)

def send_alerts(decisions: dict, stores_meta: Dict[str, dict], df_daily: pd.DataFrame) -> Tuple[Dict[str, dict], dict]:
    try:
        smtp_email, smtp_password, smtp_server, smtp_port = validate_smtp_config()
        smtp_configured = True
    except ValueError as e:
        smtp_configured = False
        smtp_email = None
        smtp_password = None
        smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        smtp_port_raw = os.getenv("SMTP_PORT", "587")
    try:
        smtp_port = int(smtp_port_raw)
    except (TypeError, ValueError):
        smtp_port = 587
        print("[WARNING] Configuration SMTP incomplète. Les emails ne seront pas envoyés.")

    reports: Dict[str, dict] = {}

    for store_label in stores_meta.keys():
        alert_triggered = store_label in decisions
        failure_count, should_notify = update_failure_counter(store_label, alert_triggered)
        
        if not alert_triggered:
            if not should_notify:
                reports[store_label] = {
                    "sent": False,
                    "message": f"Notifications désactivées après {failure_count} échecs consécutifs.",
                    "silenced": True,
                    "failure_count": failure_count
                }
                print(f"[SILENCED] {store_label}: seuil atteint ({failure_count}/{MAX_CONSECUTIVE_FAILURES})")
                continue
            else:
                reports[store_label] = {
                    "sent": False,
                    "message": f"Conditions non respectées ({failure_count}/{MAX_CONSECUTIVE_FAILURES}).",
                    "silenced": False,
                    "failure_count": failure_count
                }
                continue
    
    active_decisions = {k: v for k, v in decisions.items() if k in stores_meta and not reports.get(k, {}).get("silenced", False)}
    
    if not active_decisions:
        smtp_context = {
            "configured": smtp_configured,
            "sender": smtp_email,
            "server": smtp_server,
            "port": smtp_port,
        }
        return reports, smtp_context

    global_recipient: Optional[str] = None
    for meta in stores_meta.values():
        candidate = meta.get("email")
        if candidate and str(candidate).lower() != "nan":
            global_recipient = str(candidate).strip()
            break

    if not global_recipient:
        for store_label in stores_meta.keys():
            reports[store_label] = {
                "sent": False,
                "message": "Aucune adresse e-mail globale trouvée pour envoyer la synthèse."
            }
        smtp_context = {
            "configured": smtp_configured,
            "sender": smtp_email,
            "server": smtp_server,
            "port": smtp_port,
        }
        return reports, smtp_context

    if not smtp_configured:
        for store_label in stores_meta.keys():
            reports[store_label] = {
                "sent": False,
                "message": "Identifiants SMTP manquants (variables SMTP_EMAIL et SMTP_PASSWORD)."
            }
        smtp_context = {
            "configured": smtp_configured,
            "sender": smtp_email,
            "server": smtp_server,
            "port": smtp_port,
        }
        return reports, smtp_context

    conforming_labels = [lbl for lbl in stores_meta.keys() if lbl in active_decisions]

    lines: List[str] = [
        "Bonjour,",
        "",
        "Les conditions météorologiques configurées ont été vérifiées pour les filiales suivantes :",
    ]

    for store_label in conforming_labels:
        lines.append(f"• Filiale {store_label}")

    lines.extend([
        "",
        "Les détails par filiale figurent ci-dessous.",
        "",
        "🌦️ Détails des filiales conformes",
        "",
    ])

    for store_label in conforming_labels:
        meta = stores_meta.get(store_label, {})
        window = meta.get("window", {"avant": 0, "apres": 0})
        periode = f"J-{window.get('avant', 0)} → J+{window.get('apres', 0)}"

        lines.append(f"{store_label} – {meta.get('postal_code', '')}")
        lines.append(f"Période analysée : {periode}")
        lines.append("Seuils configurés :")

        raw_conditions = meta.get("raw_conditions", {})
        temp_min = raw_conditions.get("temp_min")
        precip_max = raw_conditions.get("precip_max", raw_conditions.get("precipitations_max"))
        vent_min = raw_conditions.get("vent_min", raw_conditions.get("vitesse_vent_min"))

        if temp_min is not None:
            lines.append(f"• Température min : {format_number(temp_min)}°C")
        if precip_max is not None:
            lines.append(f"• Précipitations max : {format_number(precip_max)} mm")
        if vent_min is not None:
            lines.append(f"• Vent min : {format_number(vent_min)} km/h")

        lines.append("")

        store_daily = pd.DataFrame()
        if not df_daily.empty:
            store_daily = df_daily[df_daily["magasin"] == store_label].copy()

        if store_daily.empty:
            lines.append("⚠️ Les données météo détaillées n'ont pas pu être récupérées.")
            lines.append("")
            continue

        selected_row = None
        j_rows = store_daily[store_daily.get("jour_relatif") == "J"]
        if not j_rows.empty:
            selected_row = j_rows.iloc[0]
        else:
            conformes = store_daily[store_daily.get("state") == True]
            if not conformes.empty:
                selected_row = conformes.iloc[0]
            else:
                selected_row = store_daily.iloc[0]

        date_str = selected_row.get("date") or "N/A"
        temp = format_number(selected_row.get("temp_12h"))
        vent = format_number(selected_row.get("vent_12h"))
        precip = format_number(selected_row.get("precipitations_12h"))

        lines.append(f"Prévision du {date_str} :")
        lines.append("✅ Conforme")
        lines.append(f"→ Température : {temp}°C")
        lines.append(f"→ Vent : {vent} km/h")
        lines.append(f"→ Précipitations : {precip} mm")
        lines.append("")

    lines.extend([
        "",
        "Cordialement,",
        "L'équipe Wellpack",
    ])

    subject = "Synthèse météo – Filiales conformes"
    body = "\n".join(lines)

    success = envoyer_email(
        expediteur_email=smtp_email,
        expediteur_password=smtp_password,
        destinataire_email=global_recipient,
        sujet=subject,
        corps_message=body,
        serveur_smtp=smtp_server,
        port_smtp=smtp_port,
    )

    for store_label in conforming_labels:
        if store_label not in reports:
            reports[store_label] = {
                "sent": bool(success),
                "message": (
                    f"Synthèse globale envoyée à {global_recipient}."
                    if success else
                    "Erreur lors de l'envoi de l'email de synthèse."
                ),
                "silenced": False,
                "failure_count": 0
            }
        else:
            reports[store_label]["sent"] = bool(success)
            if success:
                reports[store_label]["message"] = f"Synthèse globale envoyée à {global_recipient}."
    
    for store_label in stores_meta.keys():
        if store_label not in reports:
            counters = load_failure_counters()
            failure_count = counters.get(store_label, 0)
            reports[store_label] = {
                "sent": False,
                "message": "Aucune notification envoyée.",
                "silenced": False,
                "failure_count": failure_count
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
        
        if "failure_count" not in email_status:
            counters = load_failure_counters()
            failure_count = counters.get(store_label, 0)
            email_status["failure_count"] = failure_count
        
        if not alert_triggered and not email_status.get("silenced", False):
            email_status["failure_info"] = {
                "count": email_status.get("failure_count", 0)
            }

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
    silenced_count = sum(1 for store in stores_results if store["email_status"].get("silenced", False))

    summary = {
        "total": total_points,
        "alerts": triggered_points,
        "emails_sent": emails_sent,
        "silenced_count": silenced_count,
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
        with CACHE_FILE.open("w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

