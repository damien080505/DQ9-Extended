# DQ9 Extended

Mod de *Dragon Quest IX : Sentinels of the Starry Skies* (Nintendo DS, version US), langue française.

## Structure

| Dossier | Contenu |
|---|---|
| `patches/01_deblocage_dlc/` | `dq9_dlc_unlock_v1.xdelta` : déblocage des quêtes DLC |
| `patches/02_dq9_extended/` | `dq9_extended_v8.xdelta` : le mod complet (version v8) |
| `configs/specifications/` | Fiches de contenu en texte : armes, équipements, objets, boss, butin, vocations |
| `configs/production/` | Entrées JSON des scripts de construction (lots d'objets, boss legacy, vocations) |

## Appliquer un patch

ROM de départ : **Dragon Quest IX - Sentinels of the Starry Skies (USA) (En,Fr,Es)**, non modifiée.

| Fichier | SHA-1 |
|---|---|
| ROM US d'origine | `c7c3014c237900c8281289b8bc76a781969b6278` |
| après `dq9_dlc_unlock_v1.xdelta` | `1be94bdc7da50b8509f154e0f836dc2d6b44bc5e` |
| après `dq9_extended_v8.xdelta` | `ddbdd16c2747309ea36ab852c25bd286e20513f8` |

Chaque patch s'applique **séparément** sur la ROM US d'origine (ils ne se cumulent pas).

Avec xdelta3 :

```
xdelta3 -d -s "<ROM US d'origine>.nds" patches/02_dq9_extended/dq9_extended_v8.xdelta dq9_extended.nds
```

Ou avec un outil graphique (Delta Patcher, xdelta UI) : ROM source = ROM US d'origine, patch = le fichier `.xdelta`.
Vérifier ensuite le SHA-1 du résultat avec le tableau ci-dessus. Langue de la console ou de l'émulateur : français.

## Ce que fait chaque patch

**`dq9_dlc_unlock_v1.xdelta`** : rend accessibles les quêtes distribuées à l'origine en téléchargement, sans connexion.

**`dq9_extended_v8.xdelta`** : le mod complet, notamment :
- nouveaux objets et équipements (armes, boucliers, armures), avec modèles 3D et icônes recolorés, recettes d'alchimie, raretés « 5 étoiles rouges » ;
- extension de capacité de certaines listes du sac et de la sauvegarde (code ARM9/ITCM) ;
- boss « legacy » supplémentaires (Corvus, Corvus final, Roi Govin, Govin final), avec stats par niveau, actions et verrous de niveau ;
- vocation Sommité remplacée par Héros (stats, sorts, arbre de compétences, équipement) ;
- corrections du compteur de recettes de l'Alchimanach.

Limite : le projet de base n'est pas dans ce dépôt. Il contient le code du jeu extrait de la ROM, qui ne peut pas être partagé. De même, enemy_recomp.gp2 (archive des modèles de monstres recompressée) est dérivée de la ROM.
## Chaîne de production

`configs/production/*.json` → `scripts/` → données binaires du jeu → patch xdelta.

1. **Configuration (JSON)** : chaque objet, recette, boss et vocation est décrit dans un fichier de `configs/production/` (statistiques, noms, descriptions, recettes, couleurs, actions, niveaux).
2. **Scripts d'injection** :
   - `objets_build.py` lit les lots d'objets (`lot1.json` à `lot8.json`) et écrit les tables d'objets, de recettes, de combat, de tri et de boutiques, ainsi que les modèles et icônes recolorés ;
   - `boss_legacy_build.py` lit `boss_legacy.json` et écrit les fiches des monstres, leurs actions, leurs verrous de niveau et les tables des antres ;
   - `vocations_build.py` lit `vocations.json` et écrit les tables de niveau, de sorts, d'équipement et les noms des vocations.
3. **Données binaires** : les scripts réécrivent les archives et fichiers de données de la ROM (format `.gp2`, `.nat`, `.bin`) puis la ROM elle-même.
4. **Patch xdelta** : la ROM obtenue est comparée à la ROM US d'origine pour produire le fichier `.xdelta` de `patches/`.

Les trois scripts s'appuient sur des modules utilitaires (lecture des archives `.gp2`, couleurs, en-tête de ROM, tables à étiquettes) qui ne sont pas inclus dans ce dépôt.
