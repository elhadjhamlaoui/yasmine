# -*- coding: utf-8 -*-
__title__ = u"Classes\nIFC"
__doc__ = (u"Force la classe IFC des objets d'après un Excel de n'importe quelle forme : "
           u"le script repère les cellules « IfcXxx » et les autres cellules de la ligne "
           u"(catégorie, famille, type) pour savoir quels objets sont visés.")

import re
import traceback

from pyrevit import revit, forms, script
from Autodesk.Revit.DB import BuiltInCategory, Transaction

import arep_revit as ar
import arep_xlsx

doc = revit.doc
output = script.get_output()

IFC_CELL = re.compile(r"^(ifc[a-z0-9]+)(?:\s*[.(:/\- ]\s*([A-Za-z_]+)\)?)?$", re.IGNORECASE)

# Si la ligne ne cite aucune catégorie/famille/type : on déduit la catégorie Revit de la classe IFC
IFC_DEFAULT_CATEGORY = {
    "ifcwall": ["OST_Walls"], "ifcwallstandardcase": ["OST_Walls"],
    "ifcslab": ["OST_Floors"], "ifcroof": ["OST_Roofs"],
    "ifccovering": ["OST_Ceilings"], "ifccolumn": ["OST_Columns", "OST_StructuralColumns"],
    "ifcbeam": ["OST_StructuralFraming"], "ifcmember": ["OST_StructuralFraming"],
    "ifcdoor": ["OST_Doors"], "ifcwindow": ["OST_Windows"],
    "ifcstair": ["OST_Stairs"], "ifcrailing": ["OST_StairsRailing"],
    "ifcfooting": ["OST_StructuralFoundation"], "ifcfurnishingelement": ["OST_Furniture"],
    "ifcpipesegment": ["OST_PipeCurves"], "ifcpipefitting": ["OST_PipeFitting"],
    "ifcvalve": ["OST_PipeAccessory"], "ifcductsegment": ["OST_DuctCurves"],
    "ifcductfitting": ["OST_DuctFitting"], "ifcairterminal": ["OST_DuctTerminal"],
    "ifcsanitaryterminal": ["OST_PlumbingFixtures"], "ifclightfixture": ["OST_LightingFixtures"],
    "ifccablecarriersegment": ["OST_CableTray"], "ifccablecarrierfitting": ["OST_CableTrayFitting"],
    "ifcbuildingelementproxy": ["OST_GenericModel"],
}

CLASS_BIP = {"Type": ["IFC_EXPORT_ELEMENT_TYPE_AS"], "Instance": ["IFC_EXPORT_ELEMENT_AS"]}
PREDEF_BIP = {"Type": ["IFC_EXPORT_PREDEFINEDTYPE_TYPE"], "Instance": ["IFC_EXPORT_PREDEFINEDTYPE"]}
CLASS_NAMES = {
    "Type": [u"Export Type to IFC As", u"Exporter le type vers IFC en tant que",
             u"Exporter le type en tant que IFC", u"IfcExportAs"],
    "Instance": [u"Export to IFC As", u"Exporter vers IFC en tant que", u"IfcExportAs"],
}
PREDEF_NAMES = {
    "Type": [u"Type IFC Predefined Type", u"Type d'IFC prédéfini du type", u"IfcExportType"],
    "Instance": [u"IFC Predefined Type", u"Type prédéfini IFC", u"IfcExportType"],
}


def last_error():
    lines = [l for l in traceback.format_exc().strip().splitlines() if l.strip()]
    return u" | ".join(lines[-2:])


def ifc_param_names(el):
    return u", ".join(sorted(set(p.Definition.Name for p in el.Parameters
                                 if u"ifc" in p.Definition.Name.lower())))


path = forms.pick_file(file_ext="xlsx")
if not path:
    script.exit()
grid = arep_xlsx.read_xlsx_grid(path)

index = ar.ElementIndex(doc, model_only=True)
families = set(it[2] for it in index.items)
type_names = set(it[3] for it in index.items)

# noms de catégories : nom local + nom anglais interne (ex. "Walls")
cat_alias = {}
for cat in doc.Settings.Categories:
    local = ar.norm(cat.Name)
    cat_alias[local] = local
    try:
        bic = BuiltInCategory(ar.eid_int(cat.Id)).ToString()
        if bic.startswith("OST_"):
            cat_alias[ar.norm(bic[4:].replace("_", " "))] = local
            cat_alias[ar.norm(bic[4:])] = local
    except Exception:
        pass
bic_to_local = {}
for cat in doc.Settings.Categories:
    try:
        bic_to_local[BuiltInCategory(ar.eid_int(cat.Id)).ToString()] = ar.norm(cat.Name)
    except Exception:
        pass

# ------------------------------------------------------------- lecture des lignes
rules = []        # (specificite, classe, predefini, cats, fams, types, texte_ligne)
ignored = []
for row in grid:
    classe = predef = None
    others = []
    for cell in row:
        if not cell:
            continue
        m = IFC_CELL.match(cell.strip())
        if m and classe is None:
            classe = m.group(1)
            predef = (m.group(2) or u"").upper()
        else:
            others.append(cell)
    if classe is None:
        continue

    cats, fams, types = set(), set(), set()
    for cell in others:
        n = ar.norm(cell)
        if n in cat_alias:
            cats.add(cat_alias[n])
        elif n in families:
            fams.add(n)
        elif n in type_names:
            types.add(n)
    from_default = False
    if not (cats or fams or types):
        for bic in IFC_DEFAULT_CATEGORY.get(classe.lower(), []):
            if bic in bic_to_local:
                cats.add(bic_to_local[bic])
                from_default = True
    if not (cats or fams or types):
        ignored.append(u" | ".join(c for c in row if c))
        continue
    rules.append((len([s for s in (cats, fams, types) if s]), classe, predef,
                  cats, fams, types, u" | ".join(c for c in row if c), from_default))

if not rules:
    forms.alert(u"Aucune ligne exploitable : je n'ai trouvé aucune cellule de type « IfcXxx » "
                u"associée à un objet du projet.", exitscript=True)

rules.sort(key=lambda r: r[0])   # les règles précises passent en dernier et l'emportent

# ------------------------------------------------------------- application
targets = {}   # id du type -> [type, classe, predefini, [instances]]
rule_hits = []
for spec, classe, predef, cats, fams, types, text, from_default in rules:
    hits = [it for it in index.items
            if (not cats or it[1] in cats) and (not fams or it[2] in fams) and (not types or it[3] in types)]
    rule_hits.append((text, classe, len(hits), from_default))
    for el, _c, _f, _t, type_el in hits:
        entry = targets.setdefault(ar.eid_int(type_el.Id), [type_el, classe, predef, []])
        entry[1], entry[2] = classe, predef
        entry[3].append(el)

ok_count, errors = 0, []
t = Transaction(doc, u"Classes IFC depuis Excel")
t.Start()
try:
    for type_el, classe, predef, instances in targets.values():
        name = ar.get_name(type_el)
        try:
            p = ar.lookup_param(type_el, CLASS_NAMES["Type"], CLASS_BIP["Type"])
            if p is not None:
                holders, kind = [type_el], "Type"
            else:
                holders, kind = instances, "Instance"
            done_any = False
            for h in holders:
                p = ar.lookup_param(h, CLASS_NAMES[kind], CLASS_BIP[kind])
                if p is None:
                    continue
                done, msg = ar.set_param(p, classe)
                if not done:
                    errors.append(u"{} : {}".format(name, msg))
                    continue
                done_any = True
                if predef:
                    pp = ar.lookup_param(h, PREDEF_NAMES[kind], PREDEF_BIP[kind])
                    ar.set_param(pp, predef)
            if done_any:
                ok_count += 1
            else:
                errors.append(u"{} : paramètre IFC introuvable. Paramètres IFC présents : {}".format(
                    name, ifc_param_names(type_el) or u"aucun"))
        except Exception:
            errors.append(u"{} : {}".format(name, last_error()))
    t.Commit()
except Exception:
    t.RollBack()
    forms.alert(u"Erreur, rien n'a été modifié :\n{}".format(last_error()), exitscript=True)

output.print_md(u"## Classes IFC : {} types mis à jour".format(ok_count))
output.print_md(u"### Lecture de l'Excel")
for text, classe, n, from_default in rule_hits:
    how = u" (catégorie déduite de la classe)" if from_default else u""
    output.print_md(u"- `{}` → **{}** : {} objet(s){}".format(text, classe, n, how))
if ignored:
    output.print_md(u"### Lignes avec une classe IFC mais sans objet reconnu")
    for r in ignored:
        output.print_md(u"- " + r)
if errors:
    output.print_md(u"### Erreurs ({})".format(len(errors)))
    for e in errors[:200]:
        output.print_md(u"- " + e)
