# Soleol EMS VARIO — v4

Prototype Streamlit manuel pour :

- récupérer les 96 tarifs Groupe E VARIO ;
- créer une prévision PV/consommation théorique ou importer un CSV ;
- simuler la batterie sur 96 pas de 15 minutes ;
- comparer le coût sans et avec EMS ;
- convertir le résultat en fenêtres GoodWe `BatteryCD` ;
- envoyer manuellement les commandes en mode réel.

## Lancer

```bash
pip install -r requirements.txt
streamlit run app.py
```

## CSV de prévision

Colonnes obligatoires :

```text
timestamp,pv_kwh,load_kwh
2026-07-09T00:00:00+02:00,0,0.8
```

Une ligne par quart d'heure, alignée sur les tarifs Groupe E.

## GoodWe

Créer un fichier `.env` local :

```env
GOODWE_BASE_URL=https://openapi.goodwe.com
GOODWE_AUTHORIZATION=Bearer ...
GOODWE_APP_IDENTIFIER=...
```

Le mode test est activé par défaut. Vérifier les noms exacts des champs GoodWe sur une installation pilote avant tout envoi réel.
