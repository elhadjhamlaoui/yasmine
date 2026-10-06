# MesOutils — boutons pyRevit

Installation : copier `MesOutils.extension` dans `%APPDATA%\pyRevit\Extensions`, puis pyRevit > Reload.
Un onglet **MesOutils** > panneau **Maquette** apparaît avec 4 boutons.

1. **Copier pièces** : ouvrir la maquette source dans Revit (pas de lien), activer la maquette à compléter, cliquer, choisir la source.
   Copie uniquement les pièces MANQUANTES (même numéro/niveau ou pièce déjà présente à l'emplacement = ignorée) : séparations de pièces + pièces, sans murs.
2. **Classes IFC** : Excel de forme libre. Le script cherche les cellules `IfcXxx` (ex. IfcWall, IfcPipeSegment.USERDEFINED) et lit les autres cellules de la ligne
   (catégorie, famille, type) pour savoir quels objets sont visés. Sans autre cellule, la catégorie est déduite de la classe (IfcWall = Murs...). Le rapport détaille la lecture.
3. **Remplir paramètres** : Excel avec `ElementId` (ou `UniqueId`, ou `Categorie/Famille/Type`) + une colonne par paramètre (voir `modele_parametres.xlsx`).
   Cellule vide = on ne touche pas. Les valeurs numériques sont lues dans les unités du projet.
4. **Renommer param. partagé** : choisir le paramètre, saisir le nouveau nom ; le GUID est vérifié inchangé.
   Renommage forcé : sauvegarde des valeurs, retrait puis réinsertion avec le même GUID, restauration. Met à jour le fichier de paramètres partagés (copie .bak). Peut casser nomenclatures/filtres : tester sur une copie.

Tester d'abord sur une copie de la maquette. Tout est fait dans une seule transaction (Ctrl+Z pour annuler).
