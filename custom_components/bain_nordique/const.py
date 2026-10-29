"""Constantes de l'intégration Bain nordique."""
from datetime import timedelta

DOMAIN = "bain_nordique"
VERSION = "1.2.0"
CARD_URL = f"/{DOMAIN}/bain-nordique-card.js"
CONF_WATER = "water_sensor"
CONF_OUTDOOR = "outdoor_sensor"      # capteur de température ou entité météo
CONF_WIND = "wind_sensor"            # optionnel : capteur de vent ou entité météo

DEFAULT_TARGET = 38.0
STAT_TARGETS = (38.0, 39.0)          # temps moyens publiés en capteurs
SHOWN_TARGETS = [36.0, 37.0, 38.0, 39.0, 40.0, 41.0]
BOOTSTRAP_DAYS = 60                  # historique relu à la première installation
RESUME_OVERLAP = timedelta(hours=14)  # relu à chaque démarrage pour reprendre un feu
EVENT = f"{DOMAIN}_event"
