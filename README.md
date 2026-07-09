# Soleol VARIO → GoodWe EzManager

Prototype Python/Streamlit pour :

1. récupérer les 96 prix VARIO Groupe E ;
2. calculer des plages de charge/décharge batterie ;
3. préparer/enregistrer les commandes GoodWe `BatteryCD` ;
4. envoyer les consignes via l'OpenAPI GoodWe lorsque les accès sont configurés.

## Installation

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
streamlit run app.py
```

## Variables d'environnement

Créer un fichier `.env` local :

```env
GOODWE_BASE_URL=https://openapi.goodwe.com
GOODWE_AUTHORIZATION=Bearer VOTRE_TOKEN_OU_VALEUR_GOODWE
GOODWE_APP_IDENTIFIER=VOTRE_APP_IDENTIFIER_OPTIONNEL
```

Ne jamais mettre `.env` sur GitHub.

## Notes importantes

- L'envoi GoodWe est bloqué par défaut avec le mode test.
- Le format exact des headers GoodWe doit être confirmé avec votre compte OpenAPI.
- Tester uniquement sur une installation de démonstration avant un client réel.
