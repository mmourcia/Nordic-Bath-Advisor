# Changelog

## 1.2.2 — 2026-10-29
- Le délai d'allumage retrouve sa classe d'état « mesure ». Cela fait disparaître la correction
  « n'a plus de classe d'état » quand le capteur reprend l'identifiant d'une ancienne version.
- La capture du README s'affiche aussi dans HACS (adresse absolue).
- La carte est déclarée comme ressource Lovelace et sa version est tenue à jour : l'application
  mobile la charge de façon fiable. En mode YAML, le chargement automatique reste utilisé.

## 1.2.1 — 2026-10-29
- Correctif : la relecture de l'historique plantait avec les états du recorder (`LazyState` sans
  attribut `domain`), et l'intégration restait bloquée en « Lecture de l'historique… » sans rien
  apprendre. Un échec de relecture ne bloque plus le fonctionnement en direct.
- Test avec le vrai recorder.

## 1.2.0 — 2026-10-29
- La carte affiche le vent (km/h) à côté de la température extérieure quand une source de vent est configurée.
- Capture de la carte dans le README.

## 1.1.0 — 2026-10-29
- Carte Lovelace `custom:bain-nordique-card` intégrée et chargée automatiquement : température,
  état, cible réglable, prévision, courbe mesurée + prévue, boutons et statistiques.
- Le capteur d'état expose la liste des entités et des sondes (attributs `entites`, `sonde_eau`).

## 1.0.0 — 2026-10-29
Refonte complète (remplace la v0.8 « bûches / mode rapide »).
- Sonde d'eau quelconque ; température extérieure par capteur **ou** entité météo ; vent optionnel.
- Apprentissage du maintien électrique, des pertes (avec effet du vent), de la courbe du feu habituel et du délai d'allumage.
- Relecture de l'historique du recorder à l'installation et à chaque redémarrage (reprise d'un feu en cours).
- Détection automatique des feux, des baignades et de la sonde sortie de l'eau.
- Prévisions « si feu maintenant » et pendant le feu, avec fourchette.
- Statistiques : nombre de feux, temps moyens jusqu'à 38 / 39 °C, vitesse de montée, pertes.
- Sonde ESPHome sur secteur (plus de deep sleep).
