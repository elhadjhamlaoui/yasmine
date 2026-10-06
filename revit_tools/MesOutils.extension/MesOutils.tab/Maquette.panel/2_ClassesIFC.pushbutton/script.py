# -*- coding: utf-8 -*-
__title__ = u"Classes\nIFC"
__doc__ = (u"Force la classe IFC (« Exporter vers IFC en tant que ») des objets selon un Excel : "
           u"colonnes Categorie | Famille | Type | ClasseIFC | TypePredefini | Cible.")

from pyrevit import revit, forms, script
from Autodesk.Revit.DB import Transaction

import arep_revit as ar
import arep_xlsx

doc = revit.doc
output = script.get_output()

# Parametres IFC : BuiltInParameter (selon version) puis noms usuels, FR/EN
CLASS_BIP = {
    "Type": ["IFC_EXPORT_ELEMENT_TYPE_AS"],
    "Instance": ["IFC_EXPORT_ELEMENT_AS"],
}
PREDEF_BIP = {
    "Type": ["IFC_EXPORT_PREDEFINEDTYPE_TYPE"],
    "Instance": ["IFC_EXPORT_PREDEFINEDTYPE"],
}
CLASS_NAMES = {
    "Type": [u"Export Type to IFC As", u"Exporter le type vers IFC en tant que",
             u"Exporter le type en tant que IFC", u"IfcExportAs"],
    "Instance": [u"Export to IFC As", u"Exporter vers IFC en tant que", u"IfcExportAs"],
}
PREDEF_NAMES = {
    "Type": [u"Type IFC Predefined Type", u"Type d'IFC prédéfini du type", u"IfcExportType"],
    "Instance": [u"IFC Predefined Type", u"Type prédéfini IFC", u"IfcExportType"],
}

path = forms.pick_file(file_ext="xlsx")
if not path:
    script.exit()

headers, rows = arep_xlsx.read_xlsx(path)
if u"ClasseIFC" not in headers:
    forms.alert(u"Colonne « ClasseIFC » absente. Colonnes lues : {}".format(u", ".join(headers)),
                exitscript=True)

index = ar.ElementIndex(doc, model_only=True)

# les règles les plus précises passent en dernier et l'emportent
rows.sort(key=lambda r: sum(1 for k in (u"Categorie", u"Famille", u"Type") if r.get(k)))

targets = {}   # (cible, id element) -> (element, classe, predefini)
rows_without_match = []
for r in rows:
    cible = u"Instance" if ar.norm(r.get(u"Cible", u"")) == u"instance" else u"Type"
    found = index.match(r.get(u"Categorie", u""), r.get(u"Famille", u""), r.get(u"Type", u""))
    if not found:
        rows_without_match.append(r)
        continue
    for el, _c, _f, _t, type_el in found:
        holder = el if cible == u"Instance" else type_el
        targets[(cible, ar.eid_int(holder.Id))] = (
            holder, cible, r[u"ClasseIFC"], r.get(u"TypePredefini", u""))

ok_count, errors = 0, []
t = Transaction(doc, u"Classes IFC depuis Excel")
t.Start()
try:
    for holder, cible, classe, predef in targets.values():
        p = ar.lookup_param(holder, CLASS_NAMES[cible], CLASS_BIP[cible])
        if p is None:
            errors.append(u"{} (id {}) : paramètre « Exporter vers IFC en tant que » introuvable".format(
                ar.get_name(holder), ar.eid_int(holder.Id)))
            continue
        done, msg = ar.set_param(p, classe)
        if not done:
            errors.append(u"{} (id {}) : {}".format(ar.get_name(holder), ar.eid_int(holder.Id), msg))
            continue
        if predef:
            pp = ar.lookup_param(holder, PREDEF_NAMES[cible], PREDEF_BIP[cible])
            done, msg = ar.set_param(pp, predef)
            if not done:
                errors.append(u"{} : type prédéfini non écrit ({})".format(ar.get_name(holder), msg))
        ok_count += 1
    t.Commit()
except Exception as ex:
    t.RollBack()
    forms.alert(u"Erreur, rien n'a été modifié :\n{}".format(ex), exitscript=True)

output.print_md(u"## Classes IFC : {} types/objets mis à jour".format(ok_count))
if rows_without_match:
    output.print_md(u"### Lignes Excel sans correspondance dans la maquette")
    for r in rows_without_match:
        output.print_md(u"- {} / {} / {}".format(r.get(u"Categorie", u"*"), r.get(u"Famille", u"*"),
                                                  r.get(u"Type", u"*")))
if errors:
    output.print_md(u"### Erreurs ({})".format(len(errors)))
    for e in errors[:200]:
        output.print_md(u"- " + e)
