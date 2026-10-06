# -*- coding: utf-8 -*-
__title__ = u"Renommer\nparam. partagé"
__doc__ = (u"Renomme un paramètre partagé du projet en gardant son GUID : sauvegarde les valeurs, "
           u"retire le paramètre, le réinsère sous le nouveau nom (même GUID, mêmes catégories/groupe) "
           u"et restaure les valeurs.")

import shutil
import traceback

from pyrevit import revit, forms, script
from Autodesk.Revit.DB import (
    ElementId, ElementMulticategoryFilter, FilteredElementCollector, InstanceBinding,
    ParameterElement, SharedParameterElement, StorageType, Transaction, TransactionGroup,
)
from System.Collections.Generic import List

import arep_revit as ar

doc = revit.doc
app = doc.Application
output = script.get_output()


def last_error():
    lines = [l for l in traceback.format_exc().strip().splitlines() if l.strip()]
    return u" | ".join(lines[-2:])


# ------------------------------------------------------------- fichier .txt des paramètres partagés
def read_sp_file(path):
    raw = open(path, "rb").read()
    encoding = "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
    text = raw.decode(encoding)
    newline = u"\r\n" if u"\r\n" in text else u"\n"
    return encoding, newline, text.split(newline)


def rename_in_sp_file(path, guid, new_name):
    """Renomme la ligne PARAM du GUID. Retourne (ok, message). Fait une copie .bak."""
    encoding, newline, lines = read_sp_file(path)
    guid_s = str(guid).lower()
    found = False
    for i, line in enumerate(lines):
        parts = line.split(u"\t")
        if len(parts) > 3 and parts[0] == u"PARAM":
            if parts[1].lower() == guid_s:
                found = True
            elif ar.norm(parts[2]) == ar.norm(new_name):
                return False, u"le fichier contient déjà un autre paramètre « {} »".format(new_name)
    if not found:
        return False, u"GUID absent du fichier de paramètres partagés"
    for i, line in enumerate(lines):
        parts = line.split(u"\t")
        if len(parts) > 3 and parts[0] == u"PARAM" and parts[1].lower() == guid_s:
            parts[2] = new_name
            lines[i] = u"\t".join(parts)
    shutil.copyfile(path, path + ".bak")
    import codecs
    with codecs.open(path, "w", encoding) as f:
        f.write(newline.join(lines))
    return True, u""


def restore_sp_file(path):
    try:
        shutil.copyfile(path + ".bak", path)
    except Exception:
        pass


def find_definition_by_guid(guid):
    sp_file = app.SharedParametersFilename
    app.SharedParametersFilename = sp_file          # force la relecture du fichier
    deffile = app.OpenSharedParameterFile()
    for group in deffile.Groups:
        for d in group.Definitions:
            if d.GUID == guid:
                return d
    return None


# ------------------------------------------------------------- choix
shared = list(FilteredElementCollector(doc).OfClass(SharedParameterElement))
if not shared:
    forms.alert(u"Aucun paramètre partagé dans ce projet.", exitscript=True)

labels = dict((u"{}   [{}]".format(ar.get_name(p), p.GuidValue), p) for p in shared)
choice = forms.SelectFromList.show(sorted(labels), title=u"Paramètre partagé à renommer",
                                   multiselect=False, button_name=u"Choisir")
if not choice:
    script.exit()
spe = labels[choice]
old_name, guid = ar.get_name(spe), spe.GuidValue

new_name = forms.ask_for_string(default=old_name, prompt=u"Nouveau nom (le GUID reste {})".format(guid),
                                title=u"Renommer le paramètre partagé")
if not new_name or new_name.strip() == old_name:
    script.exit()
new_name = new_name.strip()

used = set(ar.norm(ar.get_name(p)) for p in FilteredElementCollector(doc).OfClass(ParameterElement)
           if p.Id != spe.Id)
if ar.norm(new_name) in used:
    forms.alert(u"Un paramètre nommé « {} » existe déjà dans le projet.".format(new_name), exitscript=True)

sp_file = app.SharedParametersFilename
if not sp_file:
    forms.alert(u"Aucun fichier de paramètres partagés défini (Gérer > Paramètres partagés).", exitscript=True)

# ------------------------------------------------------------- liaison actuelle du paramètre
old_def = binding = None
it = doc.ParameterBindings.ForwardIterator()
while it.MoveNext():
    if ar.eid_int(it.Key.Id) == ar.eid_int(spe.Id):
        old_def, binding = it.Key, it.Current
        break
if old_def is None:
    forms.alert(u"Ce paramètre n'est pas un paramètre de projet lié à des catégories "
                u"(il vient uniquement de familles). Il doit être renommé dans les familles.",
                exitscript=True)

categories = [c for c in binding.Categories]
is_instance = isinstance(binding, InstanceBinding)
try:
    group = old_def.GetGroupTypeId()
except Exception:
    group = old_def.ParameterGroup
try:
    varies = old_def.VariesAcrossGroups
except Exception:
    varies = None

if not forms.alert(
        u"Renommage forcé de « {} » en « {} » (GUID conservé).\n\n"
        u"Le paramètre va être retiré puis recréé : les valeurs sont sauvegardées et restaurées, "
        u"mais les NOMENCLATURES, FILTRES DE VUE et étiquettes qui l'utilisent peuvent perdre "
        u"la référence.\n\nFaites-le sur une copie de la maquette. Continuer ?".format(old_name, new_name),
        yes=True, no=True):
    script.exit()

# ------------------------------------------------------------- sauvegarde des valeurs
cat_ids = List[ElementId]()
for c in categories:
    cat_ids.Add(c.Id)
collector = FilteredElementCollector(doc).WherePasses(ElementMulticategoryFilter(cat_ids))
holders = collector.WhereElementIsNotElementType() if is_instance else collector.WhereElementIsElementType()

backup = []   # (id, type de stockage, valeur)
for el in holders:
    p = el.get_Parameter(guid)
    if p is None or not p.HasValue:
        continue
    st = p.StorageType
    if st == StorageType.String:
        backup.append((ar.eid_int(el.Id), st, p.AsString()))
    elif st == StorageType.Integer:
        backup.append((ar.eid_int(el.Id), st, p.AsInteger()))
    elif st == StorageType.Double:
        backup.append((ar.eid_int(el.Id), st, p.AsDouble()))
    elif st == StorageType.ElementId:
        backup.append((ar.eid_int(el.Id), st, ar.eid_int(p.AsElementId())))

# ------------------------------------------------------------- fichier .txt puis projet
ok, msg = rename_in_sp_file(sp_file, guid, new_name)
if not ok:
    forms.alert(u"Fichier de paramètres partagés non modifié : {}\nRien n'a été changé.".format(msg),
                exitscript=True)

restored, lost = 0, []
tg = TransactionGroup(doc, u"Renommer paramètre partagé")
tg.Start()
try:
    new_def = find_definition_by_guid(guid)
    if new_def is None or new_def.Name != new_name:
        raise Exception(u"définition « {} » introuvable dans le fichier de paramètres partagés".format(new_name))

    t1 = Transaction(doc, u"Retirer ancien paramètre")
    t1.Start()
    doc.ParameterBindings.Remove(old_def)
    t1.Commit()

    if any(p.GuidValue == guid for p in FilteredElementCollector(doc).OfClass(SharedParameterElement)):
        raise Exception(u"le paramètre est aussi utilisé DANS des familles chargées : "
                        u"il faut le renommer dans ces familles (même GUID) puis les recharger")

    t2 = Transaction(doc, u"Réinsérer paramètre")
    t2.Start()
    cats = app.Create.NewCategorySet()
    for c in categories:
        cats.Insert(c)
    new_binding = app.Create.NewInstanceBinding(cats) if is_instance else app.Create.NewTypeBinding(cats)
    if not doc.ParameterBindings.Insert(new_def, new_binding, group):
        raise Exception(u"réinsertion refusée par Revit")
    t2.Commit()

    if varies is not None:
        it2 = doc.ParameterBindings.ForwardIterator()
        while it2.MoveNext():
            if ar.get_name(it2.Key) == new_name:
                t3 = Transaction(doc, u"Variation par groupe")
                t3.Start()
                try:
                    it2.Key.SetAllowVaryBetweenGroups(doc, varies)
                except Exception:
                    pass
                t3.Commit()
                break

    t4 = Transaction(doc, u"Restaurer valeurs")
    t4.Start()
    for eid, st, value in backup:
        el = doc.GetElement(ar.make_eid(eid))
        p = el.get_Parameter(guid) if el is not None else None
        if p is None or p.IsReadOnly:
            lost.append(eid)
            continue
        try:
            p.Set(ar.make_eid(value) if st == StorageType.ElementId else value)
            restored += 1
        except Exception:
            lost.append(eid)
    t4.Commit()
    tg.Assimilate()
except Exception:
    tg.RollBack()
    restore_sp_file(sp_file)
    forms.alert(u"Échec, le projet et le fichier de paramètres partagés ont été remis dans leur état "
                u"d'origine :\n{}".format(last_error()), exitscript=True)

output.print_md(u"## « {} » → « {} »".format(old_name, new_name))
output.print_md(u"GUID conservé : `{}`".format(guid))
output.print_md(u"Valeurs restaurées : **{}** sur {}".format(restored, len(backup)))
if lost:
    output.print_md(u"Valeurs non restaurées (id des éléments) : {}".format(
        u", ".join(str(i) for i in lost[:100])))
output.print_md(u"Fichier de paramètres partagés mis à jour (sauvegarde `.bak`).")
output.print_md(u"> Vérifiez les nomenclatures et filtres qui utilisaient ce paramètre.")
