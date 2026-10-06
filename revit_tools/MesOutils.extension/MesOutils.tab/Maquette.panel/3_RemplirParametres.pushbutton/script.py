# -*- coding: utf-8 -*-
__title__ = u"Remplir\nparamètres"
__doc__ = (u"Remplit des paramètres depuis un Excel. Identifiant : colonne ElementId ou UniqueId, "
           u"ou bien Categorie/Famille/Type (vide = tous). Les autres colonnes = noms de paramètres.")

from pyrevit import revit, forms, script
from Autodesk.Revit.DB import Transaction

import arep_revit as ar
import arep_xlsx

doc = revit.doc
output = script.get_output()

RESERVED = [u"ElementId", u"UniqueId", u"Categorie", u"Famille", u"Type"]

path = forms.pick_file(file_ext="xlsx")
if not path:
    script.exit()

headers, rows = arep_xlsx.read_xlsx(path)
param_cols = [h for h in headers if h and h not in RESERVED]
by_id = u"ElementId" in headers or u"UniqueId" in headers
if not param_cols:
    forms.alert(u"Aucune colonne de paramètre trouvée.", exitscript=True)
if not by_id and not any(h in headers for h in (u"Categorie", u"Famille", u"Type")):
    forms.alert(u"Il faut une colonne ElementId, UniqueId ou Categorie/Famille/Type.", exitscript=True)

index = None if by_id else ar.ElementIndex(doc)


def elements_of(row):
    if by_id:
        el = None
        if row.get(u"ElementId"):
            el = doc.GetElement(ar.make_eid(int(float(row[u"ElementId"]))))
        elif row.get(u"UniqueId"):
            el = doc.GetElement(row[u"UniqueId"])
        return [el] if el is not None else []
    return [it[0] for it in index.match(row.get(u"Categorie", u""), row.get(u"Famille", u""),
                                        row.get(u"Type", u""))]


written, type_written, errors, no_element = 0, 0, [], []
t = Transaction(doc, u"Remplir paramètres depuis Excel")
t.Start()
try:
    for n, row in enumerate(rows, start=2):
        els = elements_of(row)
        if not els:
            no_element.append(n)
            continue
        for el in els:
            for col in param_cols:
                value = row.get(col, u"")
                if value == u"":
                    continue      # cellule vide = on ne touche à rien
                p = el.LookupParameter(col)
                target = el
                if p is None:
                    type_el = doc.GetElement(el.GetTypeId()) if ar.eid_int(el.GetTypeId()) > 0 else None
                    p = type_el.LookupParameter(col) if type_el is not None else None
                    target = type_el
                if p is None:
                    errors.append(u"ligne {} : paramètre « {} » absent de {} (id {})".format(
                        n, col, el.Category.Name if el.Category else u"?", ar.eid_int(el.Id)))
                    continue
                ok, msg = ar.set_param(p, value)
                if ok:
                    if target is el:
                        written += 1
                    else:
                        type_written += 1
                else:
                    errors.append(u"ligne {} : « {} » sur id {} : {}".format(
                        n, col, ar.eid_int(target.Id), msg))
    t.Commit()
except Exception as ex:
    t.RollBack()
    forms.alert(u"Erreur, rien n'a été modifié :\n{}".format(ex), exitscript=True)

output.print_md(u"## Paramètres remplis : {} sur instances, {} sur types".format(written, type_written))
if no_element:
    output.print_md(u"### Lignes Excel sans objet correspondant : {}".format(
        u", ".join(str(n) for n in no_element[:100])))
if errors:
    output.print_md(u"### Erreurs ({})".format(len(errors)))
    for e in errors[:300]:
        output.print_md(u"- " + e)
