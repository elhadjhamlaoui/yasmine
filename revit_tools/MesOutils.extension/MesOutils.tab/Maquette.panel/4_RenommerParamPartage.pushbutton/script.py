# -*- coding: utf-8 -*-
__title__ = u"Renommer\nparam. partagé"
__doc__ = u"Renomme un paramètre partagé du projet en conservant son GUID."

import codecs
import shutil

from pyrevit import revit, forms, script
from Autodesk.Revit.DB import (
    FilteredElementCollector, ParameterElement, SharedParameterElement, Transaction,
)

import arep_revit as ar

doc = revit.doc
output = script.get_output()

shared = list(FilteredElementCollector(doc).OfClass(SharedParameterElement))
if not shared:
    forms.alert(u"Aucun paramètre partagé dans ce projet.", exitscript=True)

labels = dict((u"{}   [{}]".format(ar.get_name(p), p.GuidValue), p) for p in shared)
choice = forms.SelectFromList.show(sorted(labels), title=u"Paramètre partagé à renommer",
                                   multiselect=False, button_name=u"Choisir")
if not choice:
    script.exit()
spe = labels[choice]
old_name = ar.get_name(spe)
guid = spe.GuidValue

new_name = forms.ask_for_string(default=old_name, prompt=u"Nouveau nom (le GUID reste {})".format(guid),
                                title=u"Renommer le paramètre partagé")
if not new_name or new_name.strip() == old_name:
    script.exit()
new_name = new_name.strip()

used = set(ar.norm(ar.get_name(p)) for p in FilteredElementCollector(doc).OfClass(ParameterElement)
           if p.Id != spe.Id)
if ar.norm(new_name) in used:
    forms.alert(u"Un paramètre nommé « {} » existe déjà dans le projet.".format(new_name), exitscript=True)

t = Transaction(doc, u"Renommer paramètre partagé")
t.Start()
try:
    spe.Name = new_name
    t.Commit()
except Exception as ex:
    t.RollBack()
    forms.alert(u"Revit refuse de renommer ce paramètre directement :\n{}\n\nRien n'a été modifié."
                .format(ex), exitscript=True)

# vérification : le GUID doit être inchangé
spe_after = [p for p in FilteredElementCollector(doc).OfClass(SharedParameterElement)
             if p.GuidValue == guid]
if not spe_after or ar.get_name(spe_after[0]) != new_name:
    forms.alert(u"Le renommage n'a pas été pris en compte. Rien n'a changé.", exitscript=True)

output.print_md(u"## « {} » → « {} »".format(old_name, new_name))
output.print_md(u"GUID conservé : `{}`".format(guid))

# ----------------------------------------------------- fichier de paramètres partagés (.txt)
sp_file = doc.Application.SharedParametersFilename
if sp_file and forms.alert(
        u"Mettre aussi à jour le nom dans le fichier de paramètres partagés ?\n{}\n"
        u"(une copie .bak est faite avant)".format(sp_file), yes=True, no=True):
    try:
        raw = open(sp_file, "rb").read()
        encoding = "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
        text = raw.decode(encoding)
        newline = u"\r\n" if u"\r\n" in text else u"\n"
        out, changed = [], 0
        for line in text.split(newline):
            parts = line.split(u"\t")
            if len(parts) > 3 and parts[0] == u"PARAM" and parts[1].lower() == str(guid).lower():
                parts[2] = new_name
                changed += 1
            out.append(u"\t".join(parts))
        if changed:
            shutil.copyfile(sp_file, sp_file + ".bak")
            with codecs.open(sp_file, "w", encoding) as f:
                f.write(newline.join(out))
            output.print_md(u"Fichier de paramètres partagés mis à jour (sauvegarde : `.bak`).")
        else:
            output.print_md(u"GUID non trouvé dans ce fichier de paramètres partagés : inchangé.")
    except Exception as ex:
        output.print_md(u"Fichier de paramètres partagés non modifié : {}".format(ex))

output.print_md(u"> Les **familles chargées** gardent leur ancien nom en interne : "
                u"renommez aussi le paramètre dans les familles (même GUID) puis rechargez-les.")
