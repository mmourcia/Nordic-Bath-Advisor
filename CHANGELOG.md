# Changelog

## 1.4.1 — 2026-11-03
- La carte affiche la **puissance instantanée** de la prise du maintien, à côté des pertes : en orange
  avec « chauffe » quand la résistance tourne. Si la prise est configurée avec son compteur d'énergie,
  le capteur de puissance du même appareil est trouvé tout seul. Un clic ouvre son historique.

## 1.4.0 — 2026-11-02
- **Feux manqués** : quand la sonde hésitait entre deux paliers de 0,0625 °C, le départ de la
  montée était mal repéré. Le feu paraissait alors trop faible et était ignoré (feu relancé du 30/10 au
  soir). Le creux de départ est maintenant cherché sur des moyennes de 10 min.
- Sur une eau encore chaude (au-dessus du maintien), une montée lente mais durable
  (> 0,6 °C/h pendant 30 min) suffit à détecter un feu : environ 35 min plus tôt sur un feu relancé.
- **Coût du maintien électrique** : nouvelle option pour choisir le capteur d'énergie (kWh) ou de
  puissance (W) de la prise de la résistance, et le prix du kWh. Trois nouveaux capteurs : énergie du
  jour, coût du jour et coût moyen par jour sur les 7 derniers jours complets (avec l'historique
  journalier et la température extérieure moyenne). La carte affiche le coût par jour.

## 1.3.1 — 2026-10-30
- L'intégration apparaît désormais dans l'onglet **Intégrations** (et dans sa recherche) au lieu de
  l'onglet **Entrées** : elle est déclarée comme service et non plus comme entrée. Rien ne change pour
  les entités, l'historique ou les réglages.
- Les options permettent aussi de changer la **sonde d'eau** (remplacement de la sonde) sans réinstaller :
  l'apprentissage (maintien, courbe de feu, pertes) est conservé.

## 1.3.0 — 2026-10-29
- Nouveaux capteurs **Température extérieure** et **Vent** (si une source de vent est configurée), qui
  recopient la source choisie. Ils ont une courbe et des statistiques long terme, même quand la source
  est une entité météo.
- Dans la carte, la température extérieure, le vent et les pertes sont cliquables : un clic ouvre leur
  historique.

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
