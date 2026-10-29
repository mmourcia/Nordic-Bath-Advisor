# Changelog

## 1.0.0 — 2026-10-29
Refonte complète (remplace la v0.8 « bûches / mode rapide »).
- Sonde d'eau quelconque ; température extérieure par capteur **ou** entité météo ; vent optionnel.
- Apprentissage du maintien électrique, des pertes (avec effet du vent), de la courbe du feu habituel et du délai d'allumage.
- Relecture de l'historique du recorder à l'installation et à chaque redémarrage (reprise d'un feu en cours).
- Détection automatique des feux, des baignades et de la sonde sortie de l'eau.
- Prévisions « si feu maintenant » et pendant le feu, avec fourchette.
- Statistiques : nombre de feux, temps moyens jusqu'à 38 / 39 °C, vitesse de montée, pertes.
- Sonde ESPHome sur secteur (plus de deep sleep).
