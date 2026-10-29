# Nordic Bath Advisor — Bain nordique pour Home Assistant

Intégration Home Assistant (HACS) pour un bain nordique chauffé au poêle à bois,
avec ou sans maintien électrique. Elle répond à :

- **Quelle est la température de l'eau, et que se passe-t-il ?** (maintien électrique, feu, refroidissement, sonde hors de l'eau)
- **Si j'allume maintenant, à quelle heure l'eau sera à 38 °C ?** Et quel sera le pic ?
- **Pendant un feu :** à quelle heure la cible sera atteinte, pic prévu, intensité du feu.
- **Statistiques :** nombre de feux (donc de bains), temps moyen pour atteindre 38 / 39 °C,
  vitesse de montée, pertes selon la température extérieure et le vent.

Tout est appris à partir des courbes, sans réglage : il suffit de choisir les entités.

![Carte Bain nordique pendant un feu, thèmes clair et sombre](https://raw.githubusercontent.com/mmourcia/Nordic-Bath-Advisor/main/docs/carte.png)

*La carte livrée avec l'intégration, pendant un feu : température, cible, heure d'arrivée à 38 °C avec sa fourchette, pic prévu, courbe mesurée et prévue, statistiques.*

## Installation

### Via HACS
1. *HACS → ⋮ → Dépôts personnalisés* : `https://github.com/mmourcia/Nordic-Bath-Advisor`, catégorie **Intégration**.
2. Installer **Bain nordique**, puis redémarrer Home Assistant.
3. *Paramètres → Appareils et services → Ajouter une intégration → Bain nordique*.

### À la main
Copier `custom_components/bain_nordique/` dans `/config/custom_components/`, redémarrer, puis ajouter l'intégration.

### Configuration
| Champ | Choix possibles |
|---|---|
| Température de l'eau | n'importe quel capteur de température (ESPHome, Zigbee…) |
| Température extérieure | un capteur de température **ou** une entité météo (`weather.*`) |
| Vent (optionnel) | une entité météo ou un capteur de vitesse du vent |

Les sources extérieures se changent ensuite dans *Configurer* sans réinstaller.
Une entité météo complète (Met.no, Météo-France…) fournit les deux : température et vent.

> **Mise à jour depuis la v0.8** : l'entrée existante est migrée (la sonde d'eau et la
> température extérieure sont conservées). Les anciennes entités (bûches, mode rapide,
> heure de baignade…) deviennent « indisponibles » : les supprimer depuis la page de l'intégration.

## Comment ça apprend

Dès l'installation, l'intégration **relit l'historique du recorder** (jusqu'à 60 jours) et
en tire tout ce qu'elle peut. Ensuite elle apprend en continu ; le bouton
*Réapprendre depuis l'historique* repart de zéro sur l'historique disponible.

| Ce qui est appris | Comment |
|---|---|
| **Maintien électrique** | plateaux de 6 h où l'eau oscille peu, bien au-dessus de l'air (ex. 33,1–33,8 °C). Si tu changes la consigne, elle est réapprise ; sans plateau depuis 3 jours, le maintien est considéré éteint. |
| **Pertes** `k = k0 + kw·vent` | refroidissements sans feu, au-dessus du maintien, par fenêtres de 2 h (oubli progressif pour suivre les saisons). |
| **Courbe du feu** | apport de chaleur (°C/h) par pas de 5 min depuis le début de la montée, moyennée feu après feu : c'est la signature de ton feu inversé habituel. |
| **Délai d'allumage** | temps entre *Feu allumé* et le début de la montée (inertie du poêle). |

### Détection des feux
Un feu est détecté quand l'eau monte nettement (> 1 °C/h, au-dessus du cycle du maintien).
Le bouton **Feu allumé** est facultatif : il rend la détection plus sensible et permet
d'apprendre le délai d'allumage. **Pas de feu** annule une fausse détection.
Un feu se termine 1 h après la dernière montée ; une chute rapide après le pic est notée comme baignade.

### Pendant un feu
Le feu en cours est comparé au feu habituel : plus de chaleur (a) et/ou plus lent (s).
Au début on ne voit que la vitesse ; l'ajustement s'affine au fil de la montée.
Le capteur *Intensité du feu* vaut 100 % pour un feu habituel.

### Sonde hors de l'eau
Une chute brutale (> 3 °C en moins de 30 min) met en pause l'apprentissage jusqu'au retour de la sonde dans l'eau.

### Précision observée sur l'historique d'octobre 2026
Au démarrage d'un feu, l'heure des 38 °C est prévue à ± 45 min environ et le pic à ± 1,5 °C
(les feux varient beaucoup d'une fois sur l'autre). Après 1 h de chauffe, l'erreur sur le pic
descend autour de ± 1 °C. Le capteur *Heure d'atteinte de la cible* donne une fourchette
(`au_plus_tot`, `au_plus_tard`).

## Entités

Les identifiants dépendent de la langue de Home Assistant ; ceux ci-dessous sont ceux d'une installation en français.

| Entité | Rôle |
|---|---|
| `sensor.bain_nordique_etat` | maintien électrique / refroidissement / feu allumé / feu en cours / sonde hors de l'eau |
| `sensor.bain_nordique_conseil` | phrase prête à afficher (« 33,4 °C · feu maintenant → 38 °C vers 18h10 ») |
| `number.bain_nordique_temperature_visee` | cible (38 °C par défaut) |
| `sensor.bain_nordique_heure_d_atteinte_de_la_cible` | si feu maintenant, ou pour le feu en cours ; attributs : fourchette, passages 36…41 °C, trajectoire |
| `sensor.bain_nordique_duree_avant_la_cible` | idem en minutes |
| `sensor.bain_nordique_pic_prevu`, `…_heure_du_pic` | pic (fourchette en attributs) |
| `sensor.bain_nordique_intensite_du_feu` | pendant un feu, 100 % = habituel |
| `sensor.bain_nordique_sous_la_cible_a` | après un feu : heure à laquelle l'eau repassera sous la cible |
| `sensor.bain_nordique_nombre_de_feux`, `…_feux_sur_30_jours` | compteurs (attributs : par mois, baignades détectées) |
| `sensor.bain_nordique_temps_moyen_jusqu_a_38_degc`, `…_39_degc`, `…_jusqu_a_la_cible` | moyenne des 10 derniers feux partis du maintien, depuis l'allumage |
| `sensor.bain_nordique_vitesse_de_montee_moyenne`, `…_pic_du_dernier_feu` | stats de chauffe ; le dernier feu détaillé en attributs |
| `sensor.bain_nordique_pertes_actuelles` | °C/h perdus maintenant |
| `sensor.bain_nordique_coefficient_de_pertes`, `…_sensibilite_au_vent` | diagnostic (vent : % de pertes en plus par 10 km/h) |
| `sensor.bain_nordique_consigne_du_maintien_electrique`, `…_delai_d_allumage`, `…_chaleur_du_feu_habituel` | diagnostic |
| `binary_sensor.bain_nordique_feu_en_cours`, `…_bain_pret`, `…_sonde_hors_de_l_eau` | |
| `button.bain_nordique_feu_allume`, `…_pas_de_feu`, `…_reapprendre_depuis_l_historique` | |

### Événements
`bain_nordique_event` avec `type` : `fire_start`, `fire_end` (détail du feu), `fire_discarded`,
`target_reached`, `opened` (baignade), `probe_out`, `probe_back`, `hold_learned`, `ignition`,
`late_declaration`, `fire_failed`, `fire_cancelled`, `relearn_started`.
Exemples de notifications : [`examples/automations.yaml`](examples/automations.yaml).

## Carte Lovelace

L'intégration embarque sa propre carte, chargée automatiquement (aucune ressource à déclarer).
Une seule ligne suffit, les entités sont trouvées seules :

```yaml
type: custom:bain-nordique-card
```

Elle est aussi proposée dans le sélecteur de cartes (« Bain nordique »). Elle affiche :
la température de l'eau et l'état, la cible réglable (− / +), la température extérieure et le vent (si une source de vent est configurée), la prévision (si feu maintenant
ou feu en cours, avec fourchette et pic), une courbe des dernières heures prolongée par la
prévision, les boutons *J'allume le feu* / *Pas de feu* et les statistiques. Un clic sur une
valeur ouvre l'historique de l'entité.

Options :
```yaml
type: custom:bain-nordique-card
title: Bain nordique     # titre
hours: 12                # heures d'historique sur la courbe
entity: sensor.bain_nordique_etat   # seulement si plusieurs bains
```

Après une mise à jour, si l'ancienne carte reste affichée, vide le cache du navigateur
(ou tire vers le bas pour rafraîchir dans l'application mobile).

## Tableau de bord avec les cartes standard

```yaml
type: vertical-stack
cards:
  - type: tile
    entity: sensor.bain_nordique_conseil
    name: Bain nordique
  - type: entities
    entities:
      - sensor.sonde_bain_nordique_temperature_eau
      - sensor.bain_nordique_etat
      - number.bain_nordique_temperature_visee
      - sensor.bain_nordique_heure_d_atteinte_de_la_cible
      - sensor.bain_nordique_pic_prevu
      - button.bain_nordique_feu_allume
  - type: glance
    entities:
      - sensor.bain_nordique_feux_sur_30_jours
      - sensor.bain_nordique_temps_moyen_jusqu_a_38_degc
      - sensor.bain_nordique_temps_moyen_jusqu_a_39_degc
      - sensor.bain_nordique_pertes_actuelles
```

Courbe prévue avec [apexcharts-card](https://github.com/RomRider/apexcharts-card) :

```yaml
type: custom:apexcharts-card
graph_span: 12h
span:
  offset: +4h
now:
  show: true
series:
  - entity: sensor.sonde_bain_nordique_temperature_eau
    name: Mesurée
  - entity: sensor.bain_nordique_heure_d_atteinte_de_la_cible
    name: Prévue
    stroke_dash: 4
    data_generator: |
      return (entity.attributes.trajectoire || [])
        .map(p => [new Date(p[0]).getTime(), p[1]]);
```

## Sonde ESPHome (secteur)
[`esphome/sonde-bain-nordique.yaml`](esphome/sonde-bain-nordique.yaml) : DS18B20 lue toutes les 30 s,
sans deep sleep. Home Assistant n'enregistre que les changements, l'historique reste léger.

## Développement
Publier une version : changer `version` dans `custom_components/bain_nordique/manifest.json`
(et `VERSION` dans `const.py`), ajouter sa section au `CHANGELOG.md`, puis fusionner dans `main`.
Le workflow *Release* crée alors la release GitHub `vX.Y.Z` avec les notes du changelog, et HACS la propose.

```bash
pip install pytest-homeassistant-custom-component
pytest -q
```
Tester le modèle sur un export de l'historique (*Historique → ⋮ → Télécharger les données*) :
```bash
python tools/replay_csv.py history.csv --target 38
```
Logs de debug :
```yaml
logger:
  logs:
    custom_components.bain_nordique: debug
```
