# Soleol EMS — Groupe E VARIO → GoodWe EzManager

Prototype Streamlit pour récupérer les tarifs dynamiques Groupe E VARIO, calculer une stratégie de charge/décharge et préparer l'envoi des consignes `BatteryCD` vers GoodWe OpenAPI.

## Installation

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Variables d'environnement

Créer un fichier `.env` local :

```env
GOODWE_BASE_URL=https://openapi.goodwe.com
GOODWE_AUTHORIZATION=Bearer xxx
GOODWE_APP_IDENTIFIER=xxx
```

Ne pas publier `.env` sur GitHub.

## Fonctionnement

1. Récupération des 96 prix Groupe E VARIO.
2. Sélection des plages les moins chères pour charger.
3. Sélection des plages les plus chères pour décharger.
4. Génération du payload GoodWe `BatteryCD`.
5. Envoi optionnel à GoodWe si le mode test est désactivé.

## GoodWe

Fonctions utilisées :

- `setEmsDispatchMode` avec `dispatchMode = 1` pour activer le dispatch tiers sur l'EzManager.
- `BatteryCD` pour envoyer une fenêtre de charge/décharge.

À valider sur une installation de test avant tout déploiement client.
