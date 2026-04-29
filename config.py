"""
config.py – Configuration centrale de BittensorDiscordAI
---------------------------------------------------------
Charge les variables d'environnement depuis .env (via python-dotenv)
et expose des constantes utilisables dans tout le projet.

Usage :
    from config import DISCORD_TOKEN, OPENROUTER_API_KEY, GUILD_ID
"""

import os
import sys
from pathlib import Path

# Charge automatiquement le fichier .env situé à la racine du projet
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).parent / ".env"
    load_dotenv(dotenv_path=_env_path)
except ImportError:
    pass  # python-dotenv facultatif ; les vars peuvent être définies dans le shell

# ── Credentials ──────────────────────────────────────────────────────────────

DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

# ── Discord ───────────────────────────────────────────────────────────────────

# ID du serveur Discord Bittensor (guild)
GUILD_ID: str = os.getenv("DISCORD_GUILD_ID", "799672011265015819")

# ── Chemins ───────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent

# Répertoire de dépôt des JSON scrapés
IMPORTS_DIR: str = os.getenv("IMPORTS_DIR", str(BASE_DIR / "imports"))

# Répertoire tmp (écriture atomique avant move vers IMPORTS_DIR)
TMP_DIR: str = os.getenv("TMP_DIR", str(BASE_DIR / "imports" / "tmp"))

# Chemin vers DiscordChatExporter CLI
EXPORTER_PATH: str = os.getenv(
    "EXPORTER_PATH",
    str(BASE_DIR / "DiscordChatExporter.Cli")
)

# Fichier de mapping channel_id → nom
CHANNELS_FILE: str = os.getenv("CHANNELS_FILE", str(BASE_DIR / "channels.json"))

# ── Scraper ───────────────────────────────────────────────────────────────────

# Nombre de jours en arrière pour le premier scrape d'un subnet (fallback)
SCRAPE_LOOKBACK_DAYS: int = int(os.getenv("SCRAPE_LOOKBACK_DAYS", "7"))

# ── IA ────────────────────────────────────────────────────────────────────────

# Nombre de messages passés à l'IA pour le contexte historique
AI_CONTEXT_MESSAGES: int = int(os.getenv("AI_CONTEXT_MESSAGES", "150"))

# Nombre de messages récents utilisés EXCLUSIVEMENT pour le score de sentiment
AI_SENTIMENT_WINDOW: int = int(os.getenv("AI_SENTIMENT_WINDOW", "30"))

# Modèle LLM utilisé via OpenRouter
LLM_MODEL: str = os.getenv("LLM_MODEL", "meta-llama/llama-3.1-8b-instruct")

# ── Validation (appelée au démarrage de l'app) ────────────────────────────────

def validate():
    """
    Vérifie que les variables critiques sont définies.
    Affiche un avertissement (pas d'arrêt) si une variable est manquante.
    """
    required = {
        "DISCORD_TOKEN": DISCORD_TOKEN,
        "OPENROUTER_API_KEY": OPENROUTER_API_KEY,
    }
    missing = [name for name, val in required.items() if not val]
    if missing:
        print(
            f"⚠️  [config] Variables d'environnement manquantes : {', '.join(missing)}\n"
            f"   Créez un fichier .env à partir de .env.example et renseignez ces valeurs.",
            file=sys.stderr,
        )
    else:
        print(f"✅ [config] Toutes les variables d'environnement sont définies.")
    return len(missing) == 0
