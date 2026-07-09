# Soleol EMS — Groupe E VARIO → GoodWe EzManager

Prototype Streamlit pour récupérer les tarifs Groupe E VARIO et préparer une stratégie GoodWe `BatteryCD`.

## Points clés v3

- Utilise les deux prix de l'API Groupe E :
  - `integrated_chf_kwh` = achat VARIO PLUS
  - `grid_chf_kwh` = revente / grid VARIO
- Optimisation économique avec rendement batterie.
- Modes de charge : réseau, surplus PV, ou automatique.
- Prépare les payloads GoodWe `BatteryCD`.
- Mode test activé par défaut.

## Installation

```bash
pip install -r requirements.txt
streamlit run app.py
```

## GoodWe

Renseigner les variables d'environnement dans `.env` :

```env
GOODWE_BASE_URL=https://openapi.goodwe.com
GOODWE_AUTHORIZATION=Bearer ...
GOODWE_APP_IDENTIFIER=...
```

Ne jamais mettre `.env` sur GitHub.
