# -*- coding: utf-8 -*-
__title__ = u"Remplir\nparamètres"
__doc__ = (u"Assistant : vous choisissez la feuille Excel, la colonne qui identifie les objets, "
           u"ce qu'elle correspond dans Revit, puis le paramètre Revit à remplir pour chaque colonne.")

import re
import traceback

from pyrevit import revit, forms, script
from Autodesk.Revit.DB import StorageType, Transaction

import arep_revit as ar
import arep_xlsx

doc = revit.doc
output = script.get_output()

MATCH_ID = u"ElementId Revit"
MATCH_UID = u"UniqueId Revit"
MATCH_PARAM = u"Valeur d'un paramètre Revit (à choisir ensuite)"


def last_error():
    lines = [l for l in traceback.format_exc().strip().splitlines() if l.strip()]
    return u" | ".join(lines[-2:])


def pick(options, title, multiselect=False, button=u"Valider"):
    res = forms.SelectFromList.show(options, title=title, multiselect=multiselect, button_name=button)
    if not res:
        script.exit()
    return res


def key_norm(value):
    """Clé comparable : 12.0 -> 12, espaces et accents/casse ignorés."""
    v = (value or u"").strip()
    if re.match(r"^-?\d+\.0+$", v):
        v = v.split(u".")[0]
    return ar.norm(v)


def param_text_value(p):
    if p is None or not p.HasValue:
        return u""
    return (p.AsString() or p.AsValueString() or u"").strip()


# ------------------------------------------------------------- 1) Excel
path = forms.pick_file(file_ext="xlsx")
if not path:
    script.exit()
sheets = arep_xlsx.sheet_names(path)
sheet = sheets[0] if len(sheets) == 1 else pick(sheets, u"Feuille Excel à utiliser")
headers, rows = arep_xlsx.read_xlsx(path, sheets.index(sheet))
headers = [h for h in headers if h]
if not rows:
    forms.alert(u"Aucune ligne de données (la 1re ligne doit contenir les titres de colonnes).",
                exitscript=True)

# ------------------------------------------------------------- 2) colonne d'identification
key_col = pick(headers, u"Colonne Excel qui IDENTIFIE les objets (ex. ElementId, nom, numéro...)")
match_mode = pick([MATCH_ID, MATCH_UID, MATCH_PARAM],
                  u"Cette colonne « {} » correspond, dans Revit, à :".format(key_col))

index = ar.ElementIndex(doc)

# noms de paramètres disponibles (échantillon : quelques éléments par catégorie + leur type)
all_names, writable_names = set(), set()
seen_per_cat = {}
for el, cat, _f, _t, type_el in index.items:
    n = seen_per_cat.get(cat, 0)
    if n >= 3:
        continue
    seen_per_cat[cat] = n + 1
    for holder in (el, type_el):
        for p in holder.Parameters:
            name = p.Definition.Name
            all_names.add(name)
            if not p.IsReadOnly:
                writable_names.add(name)

key_param = None
if match_mode == MATCH_PARAM:
    key_param = pick(sorted(all_names, key=ar.norm), u"Paramètre Revit qui contient la valeur de « {} »".format(key_col))

# ------------------------------------------------------------- 3) colonnes -> paramètres
value_cols = pick([h for h in headers if h != key_col],
                  u"Colonnes Excel à ÉCRIRE dans Revit (plusieurs possibles)",
                  multiselect=True, button=u"Suivant")

mapping = {}   # colonne Excel -> nom du paramètre Revit
writable_sorted = sorted(writable_names, key=ar.norm)
for col in value_cols:
    same = [n for n in writable_sorted if ar.norm(n) == ar.norm(col)]
    options = same + [n for n in writable_sorted if n not in same]
    mapping[col] = pick(options, u"Colonne Excel « {} » → paramètre Revit à remplir".format(col))

overwrite = forms.alert(u"Si le paramètre Revit contient déjà une valeur, l'écraser ?\n"
                        u"(Les cellules Excel vides ne modifient jamais rien.)",
                        yes=True, no=True)

# ------------------------------------------------------------- 4) correspondance objets <-> lignes
lookup = {}   # clé normalisée -> [elements]
if match_mode == MATCH_PARAM:
    for el, _c, _f, _t, type_el in index.items:
        p = el.LookupParameter(key_param) or type_el.LookupParameter(key_param)
        v = param_text_value(p)
        if v:
            lookup.setdefault(key_norm(v), []).append(el)

matches = []   # (ligne, [elements])
unmatched = []
for n, row in enumerate(rows, start=2):
    k = row.get(key_col, u"")
    els = []
    try:
        if match_mode == MATCH_ID and k:
            el = doc.GetElement(ar.make_eid(int(float(k))))
            els = [el] if el is not None else []
        elif match_mode == MATCH_UID and k:
            el = doc.GetElement(k)
            els = [el] if el is not None else []
        elif k:
            els = lookup.get(key_norm(k), [])
    except Exception:
        els = []
    if els:
        matches.append((n, row, els))
    else:
        unmatched.append(n)

total_elements = sum(len(m[2]) for m in matches)
summary = u"\n".join(u"  {}  →  {}".format(c, p) for c, p in mapping.items())
if not matches:
    forms.alert(u"Aucune ligne Excel ne correspond à un objet Revit.\n"
                u"Vérifiez la colonne d'identification choisie.", exitscript=True)
if not forms.alert(u"{} lignes Excel sur {} correspondent à {} objets Revit.\n\n{}\n\nÉcrire dans la maquette ?".format(
        len(matches), len(rows), total_elements, summary), yes=True, no=True):
    script.exit()

# ------------------------------------------------------------- 5) écriture
written, skipped_existing, errors = 0, 0, []
t = Transaction(doc, u"Remplir paramètres depuis Excel")
t.Start()
try:
    for n, row, els in matches:
        for el in els:
            for col, pname in mapping.items():
                value = row.get(col, u"")
                if value == u"":
                    continue
                p = el.LookupParameter(pname)
                if p is None:
                    try:
                        type_el = doc.GetElement(el.GetTypeId())
                        p = type_el.LookupParameter(pname) if type_el is not None else None
                    except Exception:
                        p = None
                if p is None:
                    errors.append(u"ligne {} : « {} » absent de l'objet {}".format(n, pname, ar.eid_int(el.Id)))
                    continue
                if not overwrite and param_text_value(p):
                    skipped_existing += 1
                    continue
                ok, msg = ar.set_param(p, value)
                if ok:
                    written += 1
                else:
                    errors.append(u"ligne {} : « {} » sur {} : {}".format(n, pname, ar.eid_int(el.Id), msg))
    t.Commit()
except Exception:
    t.RollBack()
    forms.alert(u"Erreur, rien n'a été modifié :\n{}".format(last_error()), exitscript=True)

output.print_md(u"## {} valeurs écrites".format(written))
if skipped_existing:
    output.print_md(u"{} valeurs déjà renseignées conservées.".format(skipped_existing))
if unmatched:
    output.print_md(u"### Lignes Excel sans objet correspondant ({})\n{}".format(
        len(unmatched), u", ".join(str(n) for n in unmatched[:150])))
if errors:
    output.print_md(u"### Erreurs ({})".format(len(errors)))
    for e in errors[:300]:
        output.print_md(u"- " + e)
