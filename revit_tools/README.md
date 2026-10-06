# MesOutils — boutons pyRevit

Installation : copier `MesOutils.extension` dans `%APPDATA%\pyRevit\Extensions`, puis pyRevit > Reload.
Un onglet **MesOutils** > panneau **Maquette** apparaît avec 4 boutons.

1. **Copier pièces** : lier la maquette source (mêmes coordonnées), cliquer, choisir le lien.
   Crée les séparations de pièces + les pièces au même emplacement (sans murs), copie nom, numéro, service et paramètres partagés.
2. **Classes IFC** : Excel `Categorie | Famille | Type | ClasseIFC | TypePredefini | Cible` (voir `modele_classes_ifc.xlsx`).
   Cellule vide = « tous ». La règle la plus précise gagne. Cible = Type (défaut) ou Instance.
3. **Remplir paramètres** : Excel avec `ElementId` (ou `UniqueId`, ou `Categorie/Famille/Type`) + une colonne par paramètre (voir `modele_parametres.xlsx`).
   Cellule vide = on ne touche pas. Les valeurs numériques sont lues dans les unités du projet.
4. **Renommer param. partagé** : choisir le paramètre, saisir le nouveau nom ; le GUID est vérifié inchangé.
   Propose de mettre à jour le fichier de paramètres partagés (copie .bak).

Tester d'abord sur une copie de la maquette. Tout est fait dans une seule transaction (Ctrl+Z pour annuler).
