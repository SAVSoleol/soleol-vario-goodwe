# Soleol EMS VARIO — historique + GoodWe

Cette version ajoute un mode **Historique Groupe E VARIO** au prototype existant.

Fonctions principales :
- tarifs VARIO actuels ou période historique choisie ;
- pas de 15 minutes ;
- profil PV/consommation théorique exprimé en kWh/jour sur les backtests ;
- import CSV réel `timestamp,pv_kwh,load_kwh` ;
- simulation batterie sur toute la période ;
- coût sans EMS / avec EMS / gain total et moyen journalier ;
- résumé journalier ;
- envoi GoodWe désactivé automatiquement en mode historique.

## Lancer

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Remarque

L'API Groupe E a renvoyé dans les tests un historique continu à partir du 11.12.2025. Si une date antérieure est demandée, l'application affichera simplement les créneaux réellement retournés par l'API.

## Strategie tarifaire

Deux modes sont disponibles :

- **Automatique VARIO** : logique d'arbitrage automatique selon les prix futurs et la marge minimale.
- **Seuils manuels** : quatre seuils visibles en ct/kWh : achat minimum, achat maximum, vente minimum et vente maximum.

En mode manuel :
- charge reseau lorsque le prix d'achat est inferieur ou egal au seuil achat minimum ;
- decharge pour alimenter la charge lorsque le prix d'achat est superieur ou egal au seuil achat maximum ;
- stockage prioritaire du surplus PV lorsque le prix de vente est inferieur ou egal au seuil vente minimum ;
- injection prioritaire lorsque le prix de vente est superieur ou egal au seuil vente maximum ;
- entre les seuils de vente, la logique d'arbitrage automatique reste utilisee.

L'ecran principal affiche egalement les prix d'achat et de vente minimum/maximum observes sur la periode analysee, en ct/kWh.
