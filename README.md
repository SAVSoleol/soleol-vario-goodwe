# Soleol — Analyse tarifaire Groupe E

Outil volontairement simple pour répondre à une seule question :

**Combien un client aurait-il économisé en passant du tarif Double à VARIO, sans modifier son profil de consommation ?**

## Principe

1. Import du profil de soutirage réseau du client.
2. Sélection des colonnes date/heure et consommation.
3. Récupération des prix historiques VARIO Groupe E correspondant à la période.
4. Calcul quart d'heure par quart d'heure du coût Double et du coût VARIO.
5. Affichage de l'économie en CHF et en %.

Aucune simulation batterie, PV ou GoodWe n'est incluse.

## Lancer

```bash
pip install -r requirements.txt
streamlit run app.py
```

## CSV

Le fichier doit contenir au minimum :
- une colonne date/heure ;
- une colonne de soutirage/consommation.

L'interface permet de choisir l'unité : kWh, Wh, kW ou W.
