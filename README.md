# euc_diag_analysis

Outils d'analyse des fichiers de diagnostic InMotion (roues gyro unicycles, testé sur V9).

Le fichier `log.bin` récupéré via l'app EUCRAW (Wheel Settings › Log DL › Download Log) est un buffer circulaire en flash d'enregistrements de 64 octets. Ces outils le décodent intégralement en local, sans upload.

## Outils

| Fichier | Rôle | Dépendances |
|---|---|---|
| `im_diag.html` | Web app offline monofichier : dépose un `.bin` (ou dump xxd) et obtiens un tableau de bord interactif (zoom/pan sur les graphiques, filtres, event analyzer par capture) | aucune — ouvrir dans un navigateur |
| `report_ods.py` | Génère un classeur ODS multi-feuilles : Synthèse, Sorties, Allumages, Événements, Journal, Types, Graphiques. Exporte aussi les PNG dans `<rapport>_graphiques/` | `pip install odfpy matplotlib` |

```bash
python3 report_ods.py diag.bin [rapport.ods]
```

## Format binaire (64 octets/enregistrement)

Tous les entiers sont en little-endian. Un enregistrement commence par `02 00 00 00` (u32 version) ; les slots effacés sont à `0xFF` complets.

| Offset | Taille | Champ |
|---|---|---|
| 0x00 | 4 | Version (= 2, u32 LE) |
| 0x04 | 1 | Compteur 8 bits +1 par échantillon périodique (wrap 256 ; 0 sur les événements ; stall d'écriture flash de 100 ms à chaque wrap) |
| 0x05 | 2 | Temps de fonctionnement cumulé persistant, u16 LE en dixièmes de seconde (+1 par tick de 100 ms, continue entre allumages, wrap 65536 ≈ 1 h 49 min) |
| 0x07 | 1 | Réservé (0xFF) |
| 0x08 | 4 | Horloge RTC packée (u32 LE, voir ci-dessous) |
| 0x0C | 4 | Uptime de la session en ms (u32 LE) |
| 0x10 | 1 | Type d'événement |
| 0x11 | 7 | Paramètres d'événement : constantes par type (codes d'état, quasi toujours 0). Type 3 = (8,1,50), type 4 = (4,7,38), type 5 = (4,1,16), type 17 = (12,2,1,1), types 8 et 76 = 1 en 0x12 |
| 0x18 | 2 | Tension pack 1 (cV) |
| 0x1A | 2 | Courant batterie (0,01 A, signé) |
| 0x1C | 2 | Vitesse (0,01 km/h, signé) |
| 0x1E | 2 | Commande type duty/modulation : ~800 à l'arrêt, ~18500 à 34 km/h, suit aussi le courant instantané (FEM + chute ohmique). Vraisemblablement Vq (tension q) |
| 0x20 | 2 | Miroir négatif de 0x1E/0x22 (corr. −0,94 avec le courant) — vraisemblablement Vd (tension d) |
| 0x20 | 2 | ≈ −4,2 × le champ 0x22 (signé) |
| 0x22 | 2 | Courant de phase/q : pente vs courant batterie variant de 0,19 (0-10 km/h) à 1,30 (30-45 km/h), corr. 0,98 |
| 0x24 | 2 | Courant d (désexcitation) : ≈ 0 sous 20 km/h, de plus en plus négatif avec la vitesse (≈ −7 A à 34 km/h) |
| 0x26 | 2 | Tangage (0,01°, signé) |
| 0x28 | 2 | Consigne de tangage (0,01°, signé) |
| 0x2A | 2 | Roulis (0,01°, signé) |
| 0x2E | 2 | Vitesse de tiltback (0,01 km/h) |
| 0x30 | 2 | Limite de vitesse active, dynamique : 1500/1800/3000/4000 (15/18/30/40 km/h configurés) et valeurs intermédiaires (1931, 1467, 2997) probablement de derating (batterie faible : 29,97 km/h relevé à 14 % de SOC) |
| 0x32 | 2 | T° MOSFET ((raw − 50000)/100) |
| 0x34 | 2 | T° carte ((raw − 50000)/100) |
| 0x36 | 2 | T° batterie (raw/2) |
| 0x38 | 2 | État de charge (%) |
| 0x3A | 2 | T° moteur 1 ((raw − 50000)/100) |
| 0x3C | 2 | T° moteur 2 ((raw − 50000)/100) |
| 0x3E | 2 | Tension pack 2 (cV) |

Valeurs invalides : `0xFFFF` ou hors plage physique → ignorées.

### Horloge RTC packée (offset 0x08)

u32 LE, bits (origine 2020) :

`(année−2020)` bits 0-5 · `mois` bits 6-9 · `jour` bits 10-14 · `heure` bits 15-19 · `minute` bits 20-25 · `seconde` bits 26-31

### Types d'événement

| Type | Signification |
|---|---|
| 1-5 | Boot / mise sous tension (les sessions sont comptées dessus) |
| 6 | Bouton / changement de mode |
| 7 | Début de roulage |
| 82 | Échantillon télémétrie 10 Hz (en roulage) |
| 101 | Échantillon télémétrie (à l'arrêt) |
| 81 / 83 | Début / fin de capture d'événement |
| 35 / 36 | Enregistrements de boot pré-télémétrie : IMU non calibré (tangage == roulis bruts identiques), températures invalides, pack 1 absent sur le type 35 (0x18 = 50). Sur le type 36, 0x30 montre la limite de vitesse montant par paliers de 0,10 km/h (rampe de démarrage) |
| 76 | Première alerte batterie faible : unique occurrence à 12 km/h, SOC 14 %, 68,2 V |
| 11 / 42 | Étapes de derating de la limite de vitesse (alternance) — hypothèse |
| 17 / 18 / 23 | Étapes de re-rating de la limite quand la tension revient — hypothèse |
| 8, 11, 12, 13, 17, 18, 20, 21, 23, 42, 68 | Non élucidés (les types 8 et 42 encadrent souvent des changements de limite de vitesse, mais pas systématiquement) |

### Derating batterie faible (épisode du 2026-07-13, hypothèse)

À SOC 14 % (68 V), la limite de vitesse 0x30 descend par étapes, chaque étape journalisée comme événement : 29,97 (type 76) → 21,40 (11) → 19,31 (42) → 16,12 (11) → 14,67 (42) en ~20 s, puis 12,74 (17) → 14,90 (23) → 15,00 (18) après remontée à SOC 15 %. Le tiltback 0x2E suit légèrement (34,34 → 35,00). Au boot suivant (types 36), la limite remonte par paliers de 0,10 km/h — confirmation que 0x30 est la limite active, pas un réglage statique.

### Commande moteur (0x1E-0x25, hypothèse FOC)

- 0x1E : commande croissant avec la vitesse (~800 à l'arrêt, ~18 500 à 34 km/h) et le courant instantané — vraisemblablement Vq ou l'indice de modulation. Un fit linéaire Vq = a·vitesse + b·Iq ne donne que R² ≈ 0,5, donc l'échelle exacte reste inconnue
- 0x20 : miroir négatif (corr. −0,94 avec le courant) — vraisemblablement Vd
- 0x22 : courant de phase/q, pente vs courant batterie variant de 0,19 (0-10 km/h) à 1,30 (30-45 km/h)
- 0x24 : courant d de désexcitation — ≈ 0 sous 20 km/h, ≈ −7 A à 34 km/h, corrélé à la vitesse même à courant contrôlé



Les types 81/83 encadrent un flux 10 Hz continu. Une « capture » est reconstruite en fusionnant les échantillons périodiques autour d'une rupture du flux (gap > 1,5 s) : échantillons d'avant + d'après, avec l'entrée non-périodique présente dans le gap comme déclencheur. Les captures sans déclencheur correspondent à des coupures d'alimentation ou des arrêts log.

## Champs non élucidés

- Signification exacte des types mineurs restants (8, 11-13, 17-23, 42, 68)
- Échelle exacte des commandes FOC (0x1E-0x25)
- Valeurs intermédiaires de la limite 0x30 (derating ?)

## Licence

Voir [LICENSE](LICENSE).
