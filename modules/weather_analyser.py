import pandas as pd
from pathlib import Path
import requests
import os
from datetime import datetime, timedelta
from typing import Dict, Tuple, Optional, List



def geocode_postal_code(cp: str, country: str = "FR"):
    url = (
        "https://geocoding-api.open-meteo.com/v1/search?"
        f"name={cp}&count=1&language=fr&format=json&country={country}"
    )
    r = requests.get(url, timeout=10)
    if r.status_code != 200:
        return None
    data = r.json()
    if not data.get("results"):
        return None
    res = data["results"][0]
    return res["latitude"], res["longitude"]

def fetch_noon_temperature(lat: float, lon: float, forecast_days: int = 5):
    """
    Prédit uniquement la température à 12h locale (Europe/Paris) pour les prochains jours.
    Retourne un dict avec deux listes parallèles: "time" et "temperature_2m" (valeurs à 12h).
    
    Args:
        lat: latitude
        lon: longitude
        forecast_days: nombre de jours à prédire (max 16 pour Open-Meteo, défaut 5)
    """
    forecast_days = min(max(1, int(forecast_days)), 16)
    url = (
        "https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}"
        f"&hourly=temperature_2m"
        f"&timezone=Europe%2FParis&forecast_days={forecast_days}"
    )
    r = requests.get(url, timeout=15)
    if r.status_code != 200:
        return None
    data = r.json().get("hourly")
    if not data:
        return None

    times = data.get("time", [])
    temps = data.get("temperature_2m", [])
    if not times or not temps or len(times) != len(temps):
        return None

    # Filtrer les points à 12:00
    noon_times = []
    noon_temps = []
    for t, v in zip(times, temps):
        # format attendu: "YYYY-MM-DDTHH:MM"
        if t.endswith("T12:00"):
            noon_times.append(t)
            noon_temps.append(v)

    return {"time": noon_times, "temperature_2m": noon_temps}


def fetch_noon_precipitation(lat: float, lon: float, forecast_days: int = 5):
    """
    Prédit les précipitations (mm) à 12h locale pour les prochains jours.
    Retourne un dict avec "time" et "precipitation".
    
    Args:
        lat: latitude
        lon: longitude
        forecast_days: nombre de jours à prédire (max 16 pour Open-Meteo, défaut 5)
    """
    forecast_days = min(max(1, int(forecast_days)), 16)
    url = (
        "https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}"
        f"&hourly=precipitation"
        f"&timezone=Europe%2FParis&forecast_days={forecast_days}"
    )
    r = requests.get(url, timeout=15)
    if r.status_code != 200:
        return None
    data = r.json().get("hourly")
    if not data:
        return None

    times = data.get("time", [])
    precip = data.get("precipitation", [])
    if not times or not precip or len(times) != len(precip):
        return None

    noon_times = []
    noon_precip = []
    for t, v in zip(times, precip):
        if t.endswith("T12:00"):
            noon_times.append(t)
            noon_precip.append(v)

    return {"time": noon_times, "precipitation": noon_precip}


def fetch_noon_wind_speed(lat: float, lon: float, forecast_days: int = 5):
    """
    Prédit la vitesse du vent à 10m (km/h) à 12h locale pour les prochains jours.
    Retourne un dict avec "time" et "windspeed_10m".
    
    Args:
        lat: latitude
        lon: longitude
        forecast_days: nombre de jours à prédire (max 16 pour Open-Meteo, défaut 5)
    """
    forecast_days = min(max(1, int(forecast_days)), 16)
    url = (
        "https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}"
        f"&hourly=windspeed_10m"
        f"&timezone=Europe%2FParis&forecast_days={forecast_days}"
    )
    r = requests.get(url, timeout=15)
    if r.status_code != 200:
        return None
    data = r.json().get("hourly")
    if not data:
        return None

    times = data.get("time", [])
    winds = data.get("windspeed_10m", [])
    if not times or not winds or len(times) != len(winds):
        return None

    noon_times = []
    noon_winds = []
    for t, v in zip(times, winds):
        if t.endswith("T12:00"):
            noon_times.append(t)
            noon_winds.append(v)

    return {"time": noon_times, "windspeed_10m": noon_winds}


def fetch_daily_forecast(lat: float, lon: float):
    """
    Compat: alias vers fetch_noon_temperature.
    """
    return fetch_noon_temperature(lat, lon)

def _check_conditions_single_day(row):
    """
    Vérifie si les conditions météo d'UN JOUR sont RESPECTÉES (dans les seuils).
    Retourne True si TOUTES les conditions sont respectées (pas de dépassement).
    
    Logique: valeur >= min ET valeur <= max (si définis).
    Supports keys:
      - temp_min / temp_max
      - precipitations_min / precipitations_max
      - vitesse_vent_min / vitesse_vent_max
      - uv_min / uv_max
    """
    cond = row.get("conditions_meteo")
    if not isinstance(cond, dict):
        return False

    def _to_float(value):
        try:
            if value is None:
                return None
            if isinstance(value, (float, int)):
                return float(value)
            v = float(value)
            return v
        except Exception:
            return None

    def _within_thresholds(actual, min_key, max_key):
        """
        Retourne True si la valeur est DANS les seuils (>= min et <= max).
        Si un seuil n'est pas défini, on l'ignore.
        """
        actual_val = _to_float(actual)
        if actual_val is None:
            return True  # Pas de valeur = on considère OK (pas de contrainte)
        try:
            if pd.isna(actual_val):  # type: ignore[attr-defined]
                return True
        except Exception:
            pass

        min_threshold = _to_float(cond.get(min_key)) if min_key else None
        max_threshold = _to_float(cond.get(max_key)) if max_key else None

        # Si min défini et valeur < min → échec
        if min_threshold is not None and actual_val < min_threshold:
            return False
        # Si max défini et valeur > max → échec
        if max_threshold is not None and actual_val > max_threshold:
            return False
        # Sinon OK
        return True

    temp_actual = row.get("temp")
    if temp_actual is None:
        temp_actual = row.get("temp_max") or row.get("temp_min")

    precip_actual = row.get("precipitations") or row.get("precipitation_sum")
    wind_actual = row.get("vitesse_vent") or row.get("windspeed_10m")

    # Toutes les conditions doivent être respectées
    all_ok = (
        _within_thresholds(temp_actual, "temp_min", "temp_max") and
        _within_thresholds(precip_actual, "precipitations_min", "precipitations_max") and
        _within_thresholds(wind_actual, "vitesse_vent_min", "vitesse_vent_max")
    )

    return all_ok



def _check_conditions_window(df_window: pd.DataFrame, target_date: str = None) -> bool:
    """
    Vérifie si TOUTES les journées d'une fenêtre respectent les conditions.
    
    Args:
        df_window: DataFrame avec une ligne par jour de la fenêtre
        target_date: date cible (optionnel, pour logging)
    
    Returns:
        True si TOUS les jours respectent les conditions, False sinon
    """
    if df_window.empty:
        return False
    
    # Vérifier chaque journée
    for idx, row in df_window.iterrows():
        if not _check_conditions_single_day(row):
            return False
    
    return True


def _check_conditions(row):
    """
    Compatibilité: alias vers _check_conditions_single_day pour rétrocompatibilité.
    """
    return _check_conditions_single_day(row)


def evaluate_conditions_window(
    code_postal: str,
    conditions_meteo: dict,
    jours_avant: int = 0,
    jours_apres: int = 0,
    target_date: Optional[str] = None,
) -> Tuple[bool, pd.DataFrame]:
    """
    Évalue les conditions météo sur une fenêtre de jours et retourne un DataFrame détaillé.
    
    Args:
        code_postal: Code postal pour géolocalisation
        conditions_meteo: Dict des seuils (temp_min, temp_max, precip_min, precip_max, 
                         vent_min, vent_max, uv_min, uv_max)
        jours_avant: Nombre de jours avant aujourd'hui (max 5)
        jours_apres: Nombre de jours après aujourd'hui (max 5)
        target_date: Date de référence "YYYY-MM-DD" (défaut: aujourd'hui)
    
    Returns:
        Tuple (toutes_conditions_ok: bool, df_details: DataFrame)
        - toutes_conditions_ok: True si TOUS les jours respectent TOUTES les conditions
        - df_details: DataFrame avec détails jour par jour
    """
    # 1. Définir la date de référence (aujourd'hui par défaut)
    if target_date is None:
        reference_date = datetime.now()
    else:
        reference_date = datetime.strptime(target_date, "%Y-%m-%d")
    
    # 2. Limiter les délais
    jours_avant = min(max(0, int(jours_avant)), 5)
    jours_apres = min(max(0, int(jours_apres)), 5)
    
    # 3. Calculer la fenêtre temporelle
    date_debut = reference_date - timedelta(days=jours_avant)
    date_fin = reference_date + timedelta(days=jours_apres)
    
    # 4. Générer la liste des dates à vérifier
    dates_a_verifier = []
    current_date = date_debut
    while current_date <= date_fin:
        dates_a_verifier.append(current_date.strftime("%Y-%m-%d"))
        current_date += timedelta(days=1)
    
    # 5. Géolocalisation
    coords = geocode_postal_code(code_postal)
    if not coords:
        return False, _create_error_dataframe(dates_a_verifier, "Géolocalisation impossible")
    
    lat, lon = coords
    
    # 6. Calculer le nombre de jours de prévision nécessaires
    today = datetime.now().date()
    end_date_only = date_fin.date()
    forecast_days_needed = (end_date_only - today).days + 1
    
    # Vérifier si on demande des données du passé
    if forecast_days_needed < 0:
        return False, _create_error_dataframe(dates_a_verifier, "Dates dans le passé")
    
    forecast_days = min(max(forecast_days_needed, 1), 16)
    
    # 7. Récupérer toutes les données météo
    meteo_data = _fetch_all_weather_data(lat, lon, forecast_days)
    
    if not meteo_data:
        return False, _create_error_dataframe(dates_a_verifier, "Erreur API météo")
    if jours_avant > 0:
        historical_data = fetch_past_days_at_noon(
            lat=lat,
            lon=lon,
            reference_date=reference_date.strftime("%Y-%m-%d"),
            days_before=jours_avant
        )
        
        if historical_data:
            # Fusionner: historique AVANT prévisions (ordre chronologique)
            meteo_data["times"] = historical_data["time"] + meteo_data["times"]
            meteo_data["temperatures"] = historical_data["temperature_2m"] + meteo_data["temperatures"]
            meteo_data["precipitations"] = historical_data["precipitation"] + meteo_data["precipitations"]
            meteo_data["wind_speeds"] = historical_data["windspeed_10m"] + meteo_data["wind_speeds"]
            print(f"✅ Données historiques fusionnées: {len(historical_data['time'])} jours passés")
    # 8. Construire le DataFrame détaillé jour par jour
    df_details = _build_daily_dataframe(
        dates_a_verifier=dates_a_verifier,
        meteo_data=meteo_data,
        conditions_meteo=conditions_meteo,
        reference_date=reference_date.strftime("%Y-%m-%d")
    )
    
    # 9. Vérifier la conformité avec tolérance (1/3 de la fenêtre, arrondi à l'inférieur)
    if df_details.empty or "conformite_globale" not in df_details.columns:
        return False, df_details

    window_size = len(df_details)
    tolerance = window_size // 3  # tolérance = 1/3 de la fenêtre
    non_conformes = int((~df_details["conformite_globale"]).sum())
    toutes_conditions_ok = non_conformes <= tolerance

    return toutes_conditions_ok, df_details


def _fetch_all_weather_data(lat: float, lon: float, forecast_days: int) -> Optional[Dict]:
    """
    Récupère toutes les données météo nécessaires à 12h (noon).
    
    Returns:
        Dict contenant times, temperatures, precipitations, wind_speeds, uv_indices
    """
    try:
        hourly_noon = fetch_noon_temperature(lat, lon, forecast_days)
        precip_noon = fetch_noon_precipitation(lat, lon, forecast_days) or {}
        wind_noon = fetch_noon_wind_speed(lat, lon, forecast_days) or {}
        
        if not hourly_noon:
            return None
        
        return {
            "times": hourly_noon.get("time", []),
            "temperatures": hourly_noon.get("temperature_2m", []),
            "precipitations": precip_noon.get("precipitation", []),
            "wind_speeds": wind_noon.get("windspeed_10m", []),
        }
    except Exception as e:
        print(f"Erreur lors de la récupération des données météo: {e}")
        return None


def _build_daily_dataframe(
    dates_a_verifier: List[str],
    meteo_data: Dict,
    conditions_meteo: Dict,
    reference_date: str
) -> pd.DataFrame:
    """
    Construit un DataFrame détaillé avec une ligne par jour.
    
    Colonnes du DataFrame:
        - date: Date au format YYYY-MM-DD
        - jour_relatif: J-2, J-1, J, J+1, etc.
        - temperature_12h: Température prévue à 12h
        - temp_min_requis / temp_max_requis: Seuils de température
        - temp_ok: Conformité température
        - precipitations_12h: Précipitations prévues à 12h
        - precip_min_requis / precip_max_requis: Seuils précipitations
        - precip_ok: Conformité précipitations
        - vent_12h: Vitesse du vent à 12h
        - vent_min_requis / vent_max_requis: Seuils vent
        - vent_ok: Conformité vent
        - uv_12h: Indice UV à 12h
        - uv_min_requis / uv_max_requis: Seuils UV
        - uv_ok: Conformité UV
        - conformite_globale: True si toutes les conditions OK
    """
    records = []
    
    # Créer un mapping date -> données météo
    meteo_by_date = {}
    for i, time_str in enumerate(meteo_data["times"]):
        date_str = time_str.split("T")[0]
        meteo_by_date[date_str] = {
            "temperature": meteo_data["temperatures"][i] if i < len(meteo_data["temperatures"]) else None,
            "precipitation": meteo_data["precipitations"][i] if i < len(meteo_data["precipitations"]) else None,
            "wind_speed": meteo_data["wind_speeds"][i] if i < len(meteo_data["wind_speeds"]) else None,
        }
    
    # Calculer le jour relatif (J-2, J-1, J, J+1, etc.)
    ref_dt = datetime.strptime(reference_date, "%Y-%m-%d")
    
    for date_str in dates_a_verifier:
        # Calculer le jour relatif
        current_dt = datetime.strptime(date_str, "%Y-%m-%d")
        delta_days = (current_dt - ref_dt).days
        if delta_days == 0:
            jour_relatif = "J"
        elif delta_days > 0:
            jour_relatif = f"J+{delta_days}"
        else:
            jour_relatif = f"J{delta_days}"
        
        # Récupérer les données météo pour ce jour
        meteo = meteo_by_date.get(date_str, {})
        temp = meteo.get("temperature")
        precip = meteo.get("precipitation")
        wind = meteo.get("wind_speed")
        
        # Extraire les seuils des conditions
        temp_min = conditions_meteo.get("temp_min")
        temp_max = conditions_meteo.get("temp_max")
        precip_min = conditions_meteo.get("precip_min")
        precip_max = conditions_meteo.get("precip_max")
        vent_min = conditions_meteo.get("vent_min")
        vent_max = conditions_meteo.get("vent_max")
        
        # Vérifier chaque condition
        temp_ok = _check_value_in_range(temp, temp_min, temp_max)
        precip_ok = _check_value_in_range(precip, precip_min, precip_max)
        vent_ok = _check_value_in_range(wind, vent_min, vent_max)
        
        # Conformité globale: toutes les conditions doivent être OK
        conformite_globale = all([temp_ok, precip_ok, vent_ok])
        
        # Construire l'enregistrement
        record = {
            "date": date_str,
            "jour_relatif": jour_relatif,
            "temperature_12h": temp,
            "temp_min_requis": temp_min,
            "temp_max_requis": temp_max,
            "temp_ok": temp_ok,
            "precipitations_12h": precip,
            "precip_min_requis": precip_min,
            "precip_max_requis": precip_max,
            "precip_ok": precip_ok,
            "vent_12h": wind,
            "vent_min_requis": vent_min,
            "vent_max_requis": vent_max,
            "vent_ok": vent_ok,
            "conformite_globale": conformite_globale
        }
        
        records.append(record)
    
    return pd.DataFrame(records)


def _check_value_in_range(
    value: Optional[float],
    min_threshold: Optional[float],
    max_threshold: Optional[float]
) -> bool:
    """
    Vérifie si une valeur respecte les seuils min/max.
    
    Logique:
        - Si la valeur est None ou manquante: considéré comme NON conforme
        - Si min_threshold est None: pas de vérification de minimum
        - Si max_threshold est None: pas de vérification de maximum
        - Sinon: min_threshold <= value <= max_threshold
    """
    if value is None:
        return False
    
    if min_threshold is not None and value < min_threshold:
        return False
    
    if max_threshold is not None and value > max_threshold:
        return False
    
    return True


def _create_error_dataframe(dates: List[str], error_message: str) -> pd.DataFrame:
    """
    Crée un DataFrame d'erreur avec les dates demandées.
    """
    records = [{"date": d, "erreur": error_message, "conformite_globale": False} for d in dates]
    return pd.DataFrame(records)


def display_weather_check_summary(result: bool, df: pd.DataFrame) -> None:
    """
    Affiche un résumé visuel de la vérification météo.
    
    Args:
        result: Résultat global (True/False)
        df: DataFrame détaillé
    """
    print("\n" + "="*80)
    print("📊 RÉSULTAT DE LA VÉRIFICATION MÉTÉO SUR FENÊTRE TEMPORELLE")
    print("="*80)
    
    if result:
        print("✅ TOUTES les conditions sont respectées sur TOUS les jours !")
    else:
        print("❌ Au moins une condition n'est PAS respectée")
    
    print("\n" + "-"*80)
    print("📅 DÉTAIL JOUR PAR JOUR:")
    print("-"*80)
    
    if df.empty:
        print("⚠️ Aucune donnée disponible")
        return
    
    # Afficher le DataFrame avec mise en forme
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', None)
    pd.set_option('display.max_colwidth', None)
    
    print(df.to_string(index=False))
    
    print("\n" + "-"*80)
    print(f"📈 STATISTIQUES:")
    print(f"   • Nombre de jours vérifiés: {len(df)}")
    
    if "conformite_globale" in df.columns:
        nb_jours_ok = df["conformite_globale"].sum()
        print(f"   • Jours conformes: {nb_jours_ok}/{len(df)}")
        print(f"   • Taux de conformité: {nb_jours_ok/len(df)*100:.1f}%")
    
    print("="*80 + "\n")


# ============================================================================
# EXEMPLE D'UTILISATION
# ============================================================================

if __name__ == "__main__":
    # Définir les conditions météo attendues (seuils de la BDD)
    conditions_bdd = {
        "temp_min": 15.0,      # °C
        "temp_max": 28.0,      # °C
        "precip_min": 0.0,     # mm
        "precip_max": 2.0,     # mm
        "vent_min": 0.0,       # km/h
        "vent_max": 20.0,      # km/h
    }
    
    # Exemple 1: Vérifier J-2 à J+3
    print("EXEMPLE 1: Vérification sur J-2 à J+3")
    resultat, df_details = evaluate_conditions_window(
        code_postal="75001",
        conditions_meteo=conditions_bdd,
        jours_avant=2,
        jours_apres=3
    )
    
    display_weather_check_summary(resultat, df_details)
    
    # Exemple 2: Vérifier uniquement J et J+1
    print("\n\nEXEMPLE 2: Vérification sur J et J+1")
    resultat2, df_details2 = evaluate_conditions_window(
        code_postal="75001",
        conditions_meteo=conditions_bdd,
        jours_avant=0,
        jours_apres=1
    )
    
    display_weather_check_summary(resultat2, df_details2)
    
    # Accès aux données pour traitement ultérieur
    print("\n\n📊 ACCÈS AUX DONNÉES:")
    print(f"Résultat global: {resultat}")
    print(f"Type du DataFrame: {type(df_details)}")
    print(f"Colonnes disponibles: {df_details.columns.tolist()}")
    
    # Filtrer les jours non conformes
    if not df_details.empty and "conformite_globale" in df_details.columns:
        jours_non_conformes = df_details[~df_details["conformite_globale"]]
        if not jours_non_conformes.empty:
            print(f"\n⚠️ Jours NON conformes:")
            print(jours_non_conformes[["date", "jour_relatif", "temp_ok", "precip_ok", "vent_ok", "uv_ok"]])    

def load_user_csv(csv_path: str) -> pd.DataFrame:
    """
    Charge un CSV utilisateur au format:
      - code postal
      - conditions_meteo (json/dict ou str JSON)
      - numero du magasin

    Retourne un DataFrame harmonisé avec colonnes au moins:
      magasin, code_postal, conditions_meteo, delai_jours, derniere_campagne
    """
    df = pd.read_csv(csv_path)
    # Normaliser noms de colonnes (insensible à la casse/espaces)
    rename_map = {}
    for col in list(df.columns):
        lc = col.strip().lower().replace(" ", "_")
        if lc in ("code_postal", "codepostal", "code_postaux"):
            rename_map[col] = "code_postal"
        elif lc in ("conditions_meteo", "conditions", "regles", "rules"):
            rename_map[col] = "conditions_meteo"
        elif lc in ("numero_du_magasin", "numero_magasin", "magasin", "id_magasin", "store_id"):
            rename_map[col] = "magasin"
    if rename_map:
        df = df.rename(columns=rename_map)

    # Cas 1: format "large" (colonnes de seuils à plat) sans colonne conditions_meteo
    wide_threshold_cols = [
        "temp_min", "temp_max",
        "precipitations_min", "precipitations_max",
        "vitesse_vent_min", "vitesse_vent_max",
        "uv_min", "uv_max",
    ]
    has_wide = any(c in df.columns for c in wide_threshold_cols)

    # Si l'utilisateur fournit seulement un code postal par ligne sous 'codes_postaux', renommer en 'code_postal'
    if "code_postal" not in df.columns and "codes_postaux" in df.columns:
        df = df.rename(columns={"codes_postaux": "code_postal"})

    # Si pas de colonne magasin, créer une étiquette par défaut (franchise/filiale)
    if "magasin" not in df.columns:
        # Utiliser numero du magasin si fourni, sinon dériver de code_postal
        if "numero_du_magasin" in df.columns:
            df["magasin"] = df["numero_du_magasin"].astype(str)
        else:
            # Fallback: Magasin-{code_postal}
            df["magasin"] = df.get("code_postal", pd.Series([None]*len(df))).astype(str).radd("Magasin-")

    # Construire conditions_meteo si format large
    if has_wide:
        def _row_to_conditions(s: pd.Series) -> dict:
            cond: dict = {}
            for k in wide_threshold_cols:
                if k in s and pd.notna(s[k]):
                    cond[k] = s[k]
            return cond
        df["conditions_meteo"] = df.apply(_row_to_conditions, axis=1)

    # Conserver aussi un champ `mail` (nouveau) et/ou `numero` séparé si fournis
    # Utiliser `mail` comme identifiant de magasin si présent, sinon `numero`
    if "magasin" not in df.columns or df["magasin"].isna().all():
        if "mail" in df.columns:
            df["magasin"] = df["mail"].astype(str)
        elif "numero" in df.columns:
            df["magasin"] = df["numero"].astype(str)

    # Validation minimale
    for needed in ["code_postal", "magasin"]:
        if needed not in df.columns:
            raise ValueError(f"Colonne requise absente dans le CSV: {needed}")
    # Si aucune des deux formes n'apporte conditions_meteo, créer vide
    if "conditions_meteo" not in df.columns:
        df["conditions_meteo"] = [{} for _ in range(len(df))]

    # Parse conditions_meteo si str JSON-like
    def _parse_cond(x):
        if isinstance(x, dict):
            return x
        if pd.isna(x):
            return {}
        if isinstance(x, str):
            s = x.strip()
            # Essayer JSON
            try:
                import json
                return json.loads(s)
            except Exception:
                # Essayer eval safe pour dict-like
                try:
                    import ast
                    val = ast.literal_eval(s)
                    return val if isinstance(val, dict) else {}
                except Exception:
                    return {}
        return {}

    if not has_wide:
        df["conditions_meteo"] = df["conditions_meteo"].apply(_parse_cond)

    # Colonnes supplémentaires: delai_jours_avant et delai_jours_apres (obligatoires)
    # Migration depuis ancien format: si delai_jours existe, le convertir
    if "delai_jours_avant" not in df.columns:
        if "delai_jours" in df.columns:
            # Migration: ancien delai_jours → delai_jours_avant (apres=0)
            df["delai_jours_avant"] = df["delai_jours"].fillna(0).astype(int).clip(0, 5)
            df["delai_jours_apres"] = 0
            # Supprimer l'ancienne colonne
            df = df.drop(columns=["delai_jours"])
        else:
            df["delai_jours_avant"] = 0
            df["delai_jours_apres"] = 0
    else:
        df["delai_jours_avant"] = df["delai_jours_avant"].fillna(0).astype(int).clip(0, 5)
        # Supprimer delai_jours si présent
        if "delai_jours" in df.columns:
            df = df.drop(columns=["delai_jours"])
    
    if "delai_jours_apres" not in df.columns:
        df["delai_jours_apres"] = 0
    else:
        df["delai_jours_apres"] = df["delai_jours_apres"].fillna(0).astype(int).clip(0, 5)
    
    if "derniere_campagne" not in df.columns:
        df["derniere_campagne"] = pd.NaT

    # Types
    df["magasin"] = df["magasin"].astype(str)
    if "code_postal" in df.columns:
        df["code_postal"] = df["code_postal"].astype(str)

    # Retourne juste les colonnes clés utilisées en aval
    cols = [
        "magasin",
        "code_postal",
        "conditions_meteo",
        "delai_jours_avant",
        "delai_jours_apres",
        "derniere_campagne",
    ]
    extra_cols = [c for c in df.columns if c not in cols]
    return df[cols + extra_cols]

def decision_maker_daily(DB: pd.DataFrame, target_date: str = None) -> Tuple[dict, pd.DataFrame]:
    """
    Évalue les conditions météo pour chaque magasin avec un format détaillé JOUR PAR JOUR.
    
    Args:
        DB: DataFrame avec colonnes: code_postal, conditions_meteo, delai_jours_avant, 
            delai_jours_apres, magasin, mail
        target_date: date cible au format "YYYY-MM-DD" (optionnel, aujourd'hui par défaut)
    
    Returns:
        Tuple[dict, DataFrame]:
            - dict: {magasin: mail} pour les magasins qui déclenchent une alerte
            - DataFrame: résultats détaillés JOUR PAR JOUR avec colonnes:
                * magasin
                * mail
                * code_postal
                * date (une ligne par jour)
                * jour_relatif (J-2, J-1, J, J+1, etc.)
                * conditions (dict des seuils)
                * temp_12h
                * vent_12h
                * precipitations_12h
                * uv_12h
                * state (True/False pour CE jour)
    """
    if target_date is None:
        target_date = datetime.now().strftime("%Y-%m-%d")
    
    decisions: dict = {}
    daily_records = []
    has_mail = "mail" in DB.columns
    
    for _, row in DB.iterrows():
        code_postal = str(row.get("code_postal", ""))
        conditions_meteo = row.get("conditions_meteo", {})
        delai_jours_avant = int(row.get("delai_jours_avant", 0))
        delai_jours_apres = int(row.get("delai_jours_apres", 0))
        magasin = str(row.get("magasin", ""))
        mail = row.get("mail") if has_mail else None
        
        if not code_postal or not isinstance(conditions_meteo, dict):
            # Ajouter une ligne d'erreur
            daily_records.append({
                "magasin": magasin,
                "mail": mail,
                "code_postal": code_postal,
                "date": None,
                "jour_relatif": None,
                "conditions": conditions_meteo,
                "temp_12h": None,
                "vent_12h": None,
                "precipitations_12h": None,
                "state": False,
                "erreur": "Code postal ou conditions invalides"
            })
            continue
        
        try:
            # Évaluer la fenêtre complète
            conditions_ok, df_details = evaluate_conditions_window(
                code_postal=code_postal,
                conditions_meteo=conditions_meteo,
                jours_avant=delai_jours_avant,
                jours_apres=delai_jours_apres,
                target_date=target_date,
            )
            
            # Extraire les données jour par jour du df_details
            if not df_details.empty:
                for _, day_row in df_details.iterrows():
                    daily_record = {
                        "magasin": magasin,
                        "mail": mail,
                        "code_postal": code_postal,
                        "date": day_row.get("date"),
                        "jour_relatif": day_row.get("jour_relatif"),
                        "conditions": conditions_meteo,  # Les seuils requis
                        "temp_12h": day_row.get("temperature_12h"),
                        "vent_12h": day_row.get("vent_12h"),
                        "precipitations_12h": day_row.get("precipitations_12h"),
                        "state": day_row.get("conformite_globale", False),
                        "erreur": None
                    }
                    daily_records.append(daily_record)
            else:
                # Si pas de données, ajouter une ligne d'erreur
                daily_records.append({
                    "magasin": magasin,
                    "mail": mail,
                    "code_postal": code_postal,
                    "date": None,
                    "jour_relatif": None,
                    "conditions": conditions_meteo,
                    "temp_12h": None,
                    "vent_12h": None,
                    "precipitations_12h": None,
                    "uv_12h": None,
                    "state": False,
                    "erreur": "Données météo indisponibles"
                })
            
            # Ajouter aux décisions si TOUTES les conditions OK
            if conditions_ok:
                decisions[magasin] = None if mail is None else str(mail)
            
        except Exception as e:
            daily_records.append({
                "magasin": magasin,
                "mail": mail,
                "code_postal": code_postal,
                "date": None,
                "jour_relatif": None,
                "conditions": conditions_meteo,
                "temp_12h": None,
                "vent_12h": None,
                "precipitations_12h": None,
                "state": False,
                "erreur": str(e)
            })
            print(f"⚠️ Erreur pour {magasin} (CP: {code_postal}): {e}")
    
    # Créer le DataFrame avec format jour par jour
    df_daily = pd.DataFrame(daily_records)
    
    return decisions, df_daily


def display_daily_results(decisions: dict, df_daily: pd.DataFrame) -> None:
    """
    Affiche les résultats jour par jour de manière structurée.
    
    Args:
        decisions: Dictionnaire {magasin: mail} des alertes
        df_daily: DataFrame avec résultats jour par jour
    """
    print("\n" + "="*120)
    print("📊 RÉSULTATS DÉTAILLÉS JOUR PAR JOUR")
    print("="*120)
    
    # Statistiques globales
    print(f"\n🎯 ALERTES DÉCLENCHÉES: {len(decisions)} magasin(s)")
    if decisions:
        for magasin, mail in decisions.items():
            print(f"  ✅ {magasin} → {mail if mail else 'Pas de mail'}")
    else:
        print("  ❌ Aucune alerte déclenchée")
    
    print("\n" + "-"*120)
    print("📅 DÉTAIL PAR MAGASIN ET PAR JOUR:")
    print("-"*120 + "\n")
    
    if df_daily.empty:
        print("⚠️ Aucun résultat disponible")
        return
    
    # Configurer pandas pour affichage propre
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 120)
    pd.set_option('display.precision', 2)
    
    # Arrondir les valeurs numériques
    numeric_cols = ['temp_12h', 'vent_12h', 'precipitations_12h']
    df_display = df_daily.copy()
    for col in numeric_cols:
        if col in df_display.columns:
            df_display[col] = df_display[col].round(2)
    
    # Colonnes à afficher (sans la colonne conditions qui est trop longue)
    display_cols = ['magasin', 'mail', 'code_postal', 'date', 'jour_relatif', 
                    'temp_12h', 'vent_12h', 'precipitations_12h', 'state']
    
    # Filtrer les colonnes existantes
    available_cols = [col for col in display_cols if col in df_display.columns]
    df_to_show = df_display[available_cols]
    
    # Afficher par magasin pour plus de clarté
    for magasin in df_to_show['magasin'].unique():
        df_magasin = df_to_show[df_to_show['magasin'] == magasin]
        
        print(f"\n🏪 {magasin}")
        print("-" * 120)
        
        # Afficher sans répéter magasin, mail, code_postal
        cols_to_display = ['date', 'jour_relatif', 'temp_12h', 'vent_12h', 
                          'precipitations_12h', 'state']
        df_magasin_display = df_magasin[cols_to_display]
        print(df_magasin_display.to_string(index=False))
        
        # Statistiques pour ce magasin
        nb_jours = len(df_magasin)
        nb_conformes = df_magasin['state'].sum()
        print(f"\n   📊 Jours conformes: {nb_conformes}/{nb_jours} ({nb_conformes/nb_jours*100:.1f}%)")
        print()
    

    print("="*120 + "\n")


# ============================================================================
# FONCTION POUR EXPORTER EN CSV
# ============================================================================

def export_daily_results(df_daily: pd.DataFrame, filename: str = "resultats_meteo_jour_par_jour.csv"):
    """
    Exporte les résultats jour par jour en CSV.
    
    Args:
        df_daily: DataFrame avec résultats jour par jour
        filename: Nom du fichier de sortie
    """
    # Convertir la colonne conditions en string pour CSV
    df_export = df_daily.copy()
    if 'conditions' in df_export.columns:
        df_export['conditions'] = df_export['conditions'].astype(str)
    
    df_export.to_csv(filename, index=False, encoding='utf-8')
    print(f"✅ Résultats exportés dans: {filename}")


def fetch_historical_weather(
    lat: float, 
    lon: float, 
    start_date: str, 
    end_date: str,
    params: list = None
) -> Optional[Dict]:
    """
    Récupère les données météorologiques historiques depuis l'API Open-Meteo Archive.
    
    Args:
        lat: Latitude
        lon: Longitude
        start_date: Date de début au format "YYYY-MM-DD"
        end_date: Date de fin au format "YYYY-MM-DD"
        params: Liste des paramètres à récupérer. Par défaut: 
                ['temperature_2m', 'precipitation', 'windspeed_10m', 'uv_index']
    
    Returns:
        Dict avec les données horaires, ou None en cas d'erreur
        Format: {
            "time": [...],
            "temperature_2m": [...],
            "precipitation": [...],
            "windspeed_10m": [...],
            "uv_index": [...]
        }
    
    Exemple:
        >>> data = fetch_historical_weather(
        ...     lat=50.6292,
        ...     lon=3.0573,
        ...     start_date="2025-11-06",
        ...     end_date="2025-11-07",
        ...     params=['temperature_2m', 'precipitation']
        ... )
    """
    if params is None:
        params = ['temperature_2m', 'precipitation', 'windspeed_10m']
    
    # Construire l'URL de l'API Archive
    params_str = ','.join(params)
    url = (
        "https://archive-api.open-meteo.com/v1/archive?"
        f"latitude={lat}&longitude={lon}"
        f"&start_date={start_date}&end_date={end_date}"
        f"&hourly={params_str}"
        f"&timezone=Europe%2FParis"
    )
    
    try:
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            print(f"❌ Erreur API historique: status {r.status_code}")
            return None
        
        data = r.json()
        hourly_data = data.get("hourly")
        
        if not hourly_data:
            print(f"⚠️  Aucune donnée historique disponible pour {start_date} à {end_date}")
            return None
        
        return hourly_data
        
    except Exception as e:
        print(f"❌ Erreur lors de la récupération des données historiques: {e}")
        return None


def fetch_historical_noon_data(
    lat: float,
    lon: float,
    start_date: str,
    end_date: str,
    params: list = None
) -> Optional[Dict]:
    """
    Récupère les données météorologiques historiques à 12h (midi) uniquement.
    
    Args:
        lat: Latitude
        lon: Longitude
        start_date: Date de début "YYYY-MM-DD"
        end_date: Date de fin "YYYY-MM-DD"
        params: Paramètres à récupérer
    
    Returns:
        Dict avec données filtrées à 12h:
        {
            "time": ["2025-11-06T12:00", "2025-11-07T12:00", ...],
            "temperature_2m": [10.5, 11.2, ...],
            "precipitation": [0.0, 0.5, ...],
            ...
        }
    """
    # Récupérer toutes les données horaires
    hourly_data = fetch_historical_weather(lat, lon, start_date, end_date, params)
    
    if not hourly_data:
        return None
    
    times = hourly_data.get("time", [])
    if not times:
        return None
    
    # Filtrer uniquement les données à 12h
    noon_data = {"time": []}
    
    # Initialiser les listes pour chaque paramètre
    for param in hourly_data.keys():
        if param != "time":
            noon_data[param] = []
    
    # Filtrer les points à 12:00
    for i, time_str in enumerate(times):
        if time_str.endswith("T12:00"):
            noon_data["time"].append(time_str)
            for param, values in hourly_data.items():
                if param != "time":
                    noon_data[param].append(values[i] if i < len(values) else None)
    
    return noon_data


def fetch_past_days_at_noon(
    lat: float,
    lon: float,
    reference_date: str,
    days_before: int = 2
) -> Optional[Dict]:
    """
    Récupère les données météorologiques des jours précédant une date de référence (à 12h).
    
    Args:
        lat: Latitude
        lon: Longitude
        reference_date: Date de référence "YYYY-MM-DD"
        days_before: Nombre de jours avant la date de référence
    
    Returns:
        Dict avec données historiques à 12h
    
    Exemple:
        >>> # Pour récupérer J-2 et J-1 par rapport au 2025-11-08
        >>> data = fetch_past_days_at_noon(
        ...     lat=50.6292,
        ...     lon=3.0573,
        ...     reference_date="2025-11-08",
        ...     days_before=2
        ... )
        >>> # Retourne données pour 2025-11-06 et 2025-11-07 à 12h
    """
    from datetime import datetime, timedelta
    
    # Calculer les dates
    ref_dt = datetime.strptime(reference_date, "%Y-%m-%d")
    start_dt = ref_dt - timedelta(days=days_before)
    end_dt = ref_dt - timedelta(days=1)  # Jusqu'à J-1
    
    start_date = start_dt.strftime("%Y-%m-%d")
    end_date = end_dt.strftime("%Y-%m-%d")
    
    print(f"📅 Récupération données historiques: {start_date} à {end_date} (J-{days_before} à J-1)")
    
    # Récupérer les données à 12h
    noon_data = fetch_historical_noon_data(
        lat=lat,
        lon=lon,
        start_date=start_date,
        end_date=end_date,
        params=['temperature_2m', 'precipitation', 'windspeed_10m']
    )
    
    return noon_data
