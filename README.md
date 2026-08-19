# Soleol — Comparateur Groupe E Double vs VARIO

Application totalement indépendante du Battery Sizer.

## Objectif
Comparer la facture variable du même profil de soutirage réseau :
- Tarif Double Groupe E (HT/BT)
- Tarif VARIO Groupe E historique au quart d'heure

## Import
Formats : XLSX, XLS, CSV.

Le programme détecte automatiquement :
- la ligne d'en-tête ;
- la colonne date/heure ;
- la colonne soutirage/import ;
- l'unité kW/kWh/W/Wh ;
- le pas de temps.

Les fichiers Groupe E Excel sont reconnus spécifiquement. Leur horodatage est traité comme
une fin d'intervalle (00:15 = intervalle 00:00–00:15) afin de l'aligner sur l'API VARIO.

## Lancer
pip install -r requirements.txt
streamlit run app.py

## Important
Les prix HT/BT saisis doivent être les prix variables totaux pertinents pour l'année/contrat
analysé. Les frais fixes identiques aux deux options ne modifient pas l'écart Double vs VARIO.
