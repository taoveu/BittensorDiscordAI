# Bittensor Subnet Cockpit (BSC) - Web Edition

Une application web responsive permettant de monitorer les subnets Bittensor via l'analyse IA de fichiers JSON Discord. Mobile-first design avec Dark Mode premium (Glassmorphism), analyse de sentiment, et synthèse IA propulsée par Gemini 1.5 Pro.

## Prérequis

- Python 3.10+
- Clé d'API Google Gemini

## Installation

1. Clonez ce dépôt ou rendez-vous dans le dossier du projet.
2. Créez un environnement virtuel et installez les dépendances :
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
3. Créez un fichier `.env` à la racine du projet et ajoutez votre clé d'API Gemini (ou utilisez le modèle `.env.example`) :
   ```env
   GEMINI_API_KEY=votre_cle_api_ici
   ```

## Démarrage du serveur local

Pour lancer l'application en mode développement, utilisez `uvicorn` depuis la racine du projet :

```bash
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

Le serveur sera accessible sur : `http://localhost:8000`

## Exposer l'URL locale sur votre mobile

Pour tester le design "Mobile-First" directement sur votre téléphone depuis un autre réseau, vous pouvez exposer le serveur local sur internet via **Ngrok** ou **Cloudflare Tunnels**.

### Solution 1 : Ngrok (Le plus simple)

1. Installez Ngrok : [https://ngrok.com/download](https://ngrok.com/download)
2. Connectez votre compte Ngrok via la commande `ngrok config add-authtoken <VOTRE_TOKEN>` (voir le site).
3. Une fois votre serveur FastAPI lancé sur le port 8000, ouvrez un nouveau terminal et lancez :
   ```bash
   ngrok http 8000
   ```
4. Ngrok vous fournira une URL temporaire en HTTPS (ex: `https://abcd-12-34-56-78.ngrok-free.app`). Ouvrez cette URL sur le navigateur de votre smartphone !

### Solution 2 : Cloudflare Tunnels (Meilleur pour du long terme)

1. Installez `cloudflared` : [https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)
2. Lancez un tunnel rapide (sans compte) pointant vers votre port local :
   ```bash
   cloudflared tunnel --url http://localhost:8000
   ```
3. Cloudflare affichera une URL générée aléatoirement (ex: `https://example-tunnel.trycloudflare.com`). Ouvrez-la sur votre mobile.

## Fonctionnement de l'ingestion de données

Le backend de cette application surveille automatiquement le dossier `imports/`. 
Lorsque vous déposez ou mettez à jour un fichier JSON contenant des historiques Discord de subnets dans ce dossier, le système l'analyse, l'envoie à l'API Gemini 1.5 Pro, et stocke en base SQLite :
1. Le score de sentiment (-1 à 1)
2. La synthèse Executive (max 300 caractères)
3. Les 3 points techniques critiques

Rechargez simplement la page web de votre cockpit pour voir les dernières analyses !

Synthèse démarrage

# 1. Activer l'environnement virtuel du projet
source venv/bin/activate
# 2. (Optionnel mais recommandé) S'assurer que tout est à jour
pip install -r requirements.txt
# 3. Démarrer le serveur
uvicorn app:app --reload --host 0.0.0.0 --port 8000