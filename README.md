# Soleol — Comparateur Groupe E Double vs VARIO + batterie

Cette version répond en priorité à la question commerciale : **combien un client aurait-il payé avec le tarif Double et combien avec VARIO pour exactement le même profil de consommation ?**

Elle affiche trois scénarios :

1. Tarif Double sans batterie
2. Tarif VARIO sans batterie
3. Tarif VARIO + batterie optimisée

## Données nécessaires

Le meilleur résultat est obtenu avec un CSV au pas de 15 minutes :

```text
timestamp,pv_kwh,load_kwh
2026-01-01T00:00:00+01:00,0.0,0.8
```

Sans CSV, un profil théorique journalier peut être utilisé pour tester l'interface.

## Paramètres tarifaires

Les plages horaires Double 2026 sont :
- haut tarif : 07:00–12:00 et 17:00–23:00
- bas tarif : 12:00–17:00 et 23:00–07:00

Les montants HT/BT sont **modifiables dans l'interface**. Les valeurs par défaut du prototype sont 31 et 21 ct/kWh et doivent être adaptées au produit/client si nécessaire.

Le champ `grid` de l'API Groupe E VARIO représente la composante réseau dynamique. Il ne s'agit pas du prix de reprise PV. Le prix d'injection est donc un paramètre séparé.

## Lancer

```bash
pip install -r requirements.txt
streamlit run app.py
```

Le mode historique désactive tout envoi de commande GoodWe.
