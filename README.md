# Soleol — Analyse VARIO + batterie

Application Streamlit autonome pour comparer le tarif Double de Groupe E, le tarif dynamique VARIO et l'effet d'une batterie.

## Lancement

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Fichiers

- `app.py` : interface Streamlit principale, y compris le pilotage journalier graphique.
- `battery_opt.py` : optimisation économique par programmation linéaire.
- `battery_sim.py` : simulateur historique simple conservé comme module auxiliaire.
- `billing.py` : calcul Double / VARIO.
- `groupe_e_api.py` : récupération des prix VARIO.
- `meter_loader.py` : import et normalisation des courbes client.
- `reprise_groupe_e.py` : reprise PV Groupe E.
- `report_vario.py` : génération du rapport PDF.

Le point d'entrée Streamlit doit être **`app.py`**.
