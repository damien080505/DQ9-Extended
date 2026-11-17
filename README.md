# DQ9 Extended

Mod de *Dragon Quest IX : Sentinels of the Starry Skies* (Nintendo DS, version US), langue française.

## Structure

| Dossier | Contenu |
|---|---|
| `patches/01_deblocage_dlc/` | `dq9_dlc_unlock_v1.xdelta` : déblocage des quêtes DLC |
| `patches/02_dq9_extended/` | `dq9_extended_v8_voc17.xdelta` : le mod complet (version v8 voc17) |
| `configs/specifications/` | Fiches de contenu en texte : armes, équipements, objets, boss, butin, vocations |
| `configs/production/` | Entrées JSON des scripts de construction (lots d'objets, boss legacy, vocations) |

## Appliquer un patch

ROM de départ : **Dragon Quest IX - Sentinels of the Starry Skies (USA) (En,Fr,Es)**, non modifiée.

| Fichier | SHA-1 |
|---|---|
| ROM US d'origine | `c7c3014c237900c8281289b8bc76a781969b6278` |
| après `dq9_dlc_unlock_v1.xdelta` | `1be94bdc7da50b8509f154e0f836dc2d6b44bc5e` |
| après `dq9_extended_v8_voc17.xdelta` | `44d58c4ed03084822594bca963286088674ba655` |

Chaque patch s'applique **séparément** sur la ROM US d'origine (ils ne se cumulent pas).

Avec xdelta3 :

```
xdelta3 -d -s "<ROM US d'origine>.nds" patches/02_dq9_extended/dq9_extended_v8_voc17.xdelta dq9_extended.nds
```

Ou avec un outil graphique (Delta Patcher, xdelta UI) : ROM source = ROM US d'origine, patch = le fichier `.xdelta`.
Vérifier ensuite le SHA-1 du résultat avec le tableau ci-dessus. Langue de la console ou de l'émulateur : français.

## Ce que fait chaque patch

**`dq9_dlc_unlock_v1.xdelta`** : rend accessibles les quêtes distribuées à l'origine en téléchargement, sans connexion.

**`dq9_extended_v8_voc17.xdelta`** : le mod complet, notamment :
- nouveaux objets et équipements (armes, boucliers, armures), avec modèles 3D et icônes recolorés, recettes d'alchimie, raretés « 5 étoiles rouges » ;
- extension de capacité de certaines listes du sac et de la sauvegarde (code ARM9/ITCM) ;
- boss « legacy » supplémentaires (Corvus, Corvus final, Roi Govin, Govin final), avec stats par niveau, actions et verrous de niveau ;
- vocation Sommité remplacée par Héros (stats, sorts, arbre de compétences, équipement) ;
- corrections du compteur de recettes de l'Alchimanach.

Limite : le projet de base n'est pas dans ce dépôt. Il contient le code du jeu extrait de la ROM, qui ne peut pas être partagé. De même, enemy_recomp.gp2 (archive des modèles de monstres recompressée) est dérivée de la ROM.