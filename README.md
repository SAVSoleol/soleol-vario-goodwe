# Soleol — Double vs VARIO + batterie

Programme indépendant du Battery Sizer.

Compare 4 scénarios :
1. Tarif Double
2. VARIO
3. Tarif Double + batterie autoconsommation
4. VARIO + batterie pilotée selon les prix

Le fichier Groupe E fournit import/soutirage et surplus/export. Les valeurs kW sont converties en kWh par intervalle.
Le mode 2025 -> 2026 permet de tester les vrais prix VARIO 2026 avec un profil mesuré en 2025.

La stratégie VARIO stocke le surplus PV et décharge la batterie pendant les prix élevés.
Aucune charge depuis le réseau n'est autorisée dans cette version.
