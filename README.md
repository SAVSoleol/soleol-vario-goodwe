# Soleol — Double / VARIO + batterie optimisée

Programme indépendant du Battery Sizer.

Scénarios :
1. Double
2. VARIO
3. Double + batterie PV
4. VARIO + batterie PV optimisée économiquement
5. Option : VARIO + arbitrage réseau

La stratégie batterie est calculée par programmation linéaire sur toute la période historique.
Objectif : minimiser la facture (import x prix - export x reprise) sous contraintes de capacité,
puissance, rendement et SOC. Le SOC final est remis au SOC initial pour éviter un gain artificiel.

La projection annuelle est indicative et annualise simplement la période couverte.
