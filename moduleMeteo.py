import pickle
import pandas as pd
from pathlib import Path
import requests


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

def fetch_daily_forecast(lat: float, lon: float):
    url = (
        "https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}"
        f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum"
        f"&timezone=Europe%2FParis&forecast_days=5"
    )
    r = requests.get(url, timeout=15)
    if r.status_code != 200:
        return None
    return r.json().get("daily")

def _check_conditions(row):
    """
    Vérification des conditions météo avec la nouvelle logique :
    - temp_min < conditions_meteo[temp_min]
    - temp_max > conditions_meteo[temp_max] 
    - precipitation_sum == conditions_meteo[precipitation] ± 0.2
    """
    cond = row.get("conditions_meteo")
    if not isinstance(cond, dict):
        return False
    
    # Vérification temp_min : temp_min < conditions_meteo[temp_min]
    temp_min_ok = True
    if "temp_min" in cond and row.get("temp_min") is not None:
        temp_min_threshold = cond["temp_min"]
        actual_temp_min = row.get("temp_min")
        temp_min_ok = actual_temp_min < temp_min_threshold
    
    # Vérification temp_max : temp_max > conditions_meteo[temp_max]
    temp_max_ok = True
    if "temp_max" in cond and row.get("temp_max") is not None:
        temp_max_threshold = cond["temp_max"]
        actual_temp_max = row.get("temp_max")
        temp_max_ok = actual_temp_max > temp_max_threshold
    
    # Vérification precipitation : precipitation_sum == conditions_meteo[precipitation] ± 0.2
    precipitation_ok = True
    if "precipitation" in cond and row.get("precipitation_sum") is not None:
        precipitation_threshold = cond["precipitation"]
        actual_precipitation = row.get("precipitation_sum")
        # Tolérance de ± 0.2
        precipitation_ok = abs(actual_precipitation - precipitation_threshold) <= 0.2
    
    # Retourner True si toutes les conditions sont satisfaites
    if temp_min_ok and temp_max_ok and precipitation_ok:
        return True
    else:
        return False
    
def send_sms(DB):
    for index, row in DB.iterrows():
        if row["conditions_ok_j5"] == True:
            print(f"envoyer un sms d'avertissement à: {row['magasin']}")
        else:
            pass