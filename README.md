# euc_diag_analysis

Outils d'analyse des fichiers de diagnostic InMotion (roues gyro unicycles, testé sur V9).

Le fichier `log.bin` récupéré via l'app EUCRAW (Wheel Settings › Log DL › Download Log) est un buffer circulaire en flash d'enregistrements de 64 octets. Ces outils le décodent intégralement en local, sans upload.

## Outils

| Fichier | Rôle | Dépendances |
|---|---|---|
| `im_diag.html` | Web app offline monofichier : dépose un `.bin` (ou dump xxd) et obtiens un tableau de bord interactif (zoom/pan sur les graphiques, filtres, event analyzer par capture) | aucune — ouvrir dans un navigateur |
| `report_ods.py` | Génère un classeur ODS multi-feuilles : Synthèse, Sorties, Allumages, Événements, Journal, Types, Graphiques. Exporte aussi les PNG dans `<rapport>_graphiques/` | `pip install odfpy matplotlib` |
| `lk_diag.html` | Web app offline monofichier pour les logs d'événements LeaperKim **page 32** (Lynx OG etc.) : dépose un `.txt` (texte `#N time=… code=… values=[…]` ou dump hex) et obtiens synthèse, sorties, tensions, journal | aucune — ouvrir dans un navigateur |

```bash
python3 report_ods.py diag.bin [rapport.ods]
```

## Format binaire (64 octets/enregistrement)

Tous les entiers sont en little-endian. Un enregistrement commence par `02 00 00 00` (u32 version) ; les slots effacés sont à `0xFF` complets.

| Offset | Taille | Champ |
|---|---|---|
| 0x00 | 4 | Version (= 2, u32 LE) |
| 0x04 | 3 | Compteur d'échantillons (rôle exact non élucidé) |
| 0x07 | 1 | Réservé (0xFF) |
| 0x08 | 4 | Horloge RTC packée (u32 LE, voir ci-dessous) |
| 0x0C | 4 | Uptime de la session en ms (u32 LE) |
| 0x10 | 1 | Type d'événement |
| 0x11 | 7 | Paramètres d'événement (sens par type inconnu) |
| 0x18 | 2 | Tension pack 1 (cV) |
| 0x1A | 2 | Courant batterie (0,01 A, signé) |
| 0x1C | 2 | Vitesse (0,01 km/h, signé) |
| 0x1E | 2 | Courant de phase (brut, signé) |
| 0x26 | 2 | Tangage (0,01°, signé) |
| 0x28 | 2 | Consigne de tangage (0,01°, signé) |
| 0x2A | 2 | Roulis (0,01°, signé) |
| 0x2E | 2 | Vitesse de tiltback (0,01 km/h) |
| 0x30 | 2 | Limite de vitesse (0,01 km/h) |
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
| 8, 11, 12, 13, 17, 18, 20, 21, 23, 35, 36, 42, 68, 76 | Non élucidés |

### Captures d'événements

Les types 81/83 encadrent un flux 10 Hz continu. Une « capture » est reconstruite en fusionnant les échantillons périodiques autour d'une rupture du flux (gap > 1,5 s) : échantillons d'avant + d'après, avec l'entrée non-périodique présente dans le gap comme déclencheur. Les captures sans déclencheur correspondent à des coupures d'alimentation ou des arrêts log.

## Logs LeaperKim « page 32 » (Lynx OG, anciens firmwares)

Deuxième génération d'outils : `lk_diag.html` analyse les logs d'événements LeaperKim de l'ancien protocole « page 32 » (loeuc-core : `parseLeaperKimLogPage32Records`). Le format récent « page 33 » (Lynx S, Sherman S…) porte le nom des événements et jusqu'à 8 valeurs 32 bits ; la page 32 n'a **ni nom ni compteur** : 5 octets bruts signés par événement. `lk_diag.html` décode les deux formes de fichier (texte brut ou dump hex).

Chaque ligne du log :
- `#index` : position dans le buffer circulaire (le fichier va du **plus récent au plus ancien**)
- `time` : secondes Unix BE, ou `0.0.0.0` / petit nombre = horloge non réglée (juste après boot, avant synchro app)
- `code` : code d'événement u16
- `values` : 5 octets signés

| Code | Signification |
|---|---|
| 0 | Empreinte roue écrite avant chaque événement : [ID processeur ×2, modèle FW, minor, patch] — constante pour une roue donnée |
| 1 | BtnOff (extinction par bouton). Deux variantes : **résumé** `[0, dist_hi, dist_lo, 0, temp?]` avec distance = `v1<<8 \| (v2&0xFF)` mètres ; **tension** `[0,0,0, V_hi, V_lo]` avec V = u16 BE en centivolts |
| 2 | UnPlugCharger — chargeur débranché ; `v3,v4` = tension au débranchement |
| 40 | Inconnu — `v0` ≈ tension pack (hypothèse) |
| 65535 | Slot de flash effacé (fin de buffer) |

Décodages validés sur le log d'une **Lynx OG** (5 semaines) : 89 sorties, 297,7 km, commute de ~2120 m visible deux fois par jour ; tensions de repos 120–128 V ; distance = `v1<<8 | (v2&0xFF)` m confirmée par la répétition du trajet quotidien. Restent à élucider : `v0` (toujours 0 sur BtnOff), le sens exact de `v4` (-6..+7, probablement température °C) et le code 40.

## Champs non élucidés

- Octets 0x04-0x06 (compteur)
- Paramètres 0x11-0x17 par type
- Signification fine de certains types mineurs

## Licence

Voir [LICENSE](LICENSE).
