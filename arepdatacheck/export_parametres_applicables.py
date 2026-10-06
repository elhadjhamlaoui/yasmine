# -*- coding: utf-8 -*-
# A lancer UNE FOIS dans Revit (pyRevit, IronPython) sur la maquette auditee.
# Exporte les liaisons de parametres : quelle categorie porte quel parametre
# (cases cochees dans Gerer > Parametres du projet / partages).
import codecs
import os

doc = __revit__.ActiveUIDocument.Document

OUTPUT = os.path.join(
    r"C:\Users\bompoloe\Desktop\Projets\CFL LUX\AUDITS\2026_09_17\PLB",
    "parametres_applicables.csv",
)

rows = []
it = doc.ParameterBindings.ForwardIterator()
while it.MoveNext():
    definition = it.Key
    binding = it.Current
    for cat in binding.Categories:
        rows.append((cat.Name, definition.Name))

with codecs.open(OUTPUT, "w", "utf-8-sig") as f:
    f.write(u"Categorie;Parametre\n")
    for cat, param in sorted(set(rows)):
        f.write(u"%s;%s\n" % (cat, param))

print("{} liaisons exportees vers {}".format(len(set(rows)), OUTPUT))
