# -*- coding: utf-8 -*-
"""Fonctions communes aux boutons MesOutils (Revit 2020 -> 2026, pyRevit)."""
import unicodedata

from Autodesk.Revit.DB import (
    BuiltInParameter,
    ElementId,
    FilteredElementCollector,
    CategoryType,
    StorageType,
)


# ----------------------------------------------------------------- texte
def norm(text):
    """Texte comparable : sans accents, sans casse, sans espaces autour."""
    if text is None:
        return u""
    if not isinstance(text, type(u"")):
        try:
            text = text.decode("utf-8")
        except Exception:
            text = u"%s" % text
    text = unicodedata.normalize("NFKD", text)
    text = u"".join(c for c in text if not unicodedata.combining(c))
    return text.strip().lower()


# ------------------------------------------------------------ ElementId
def eid_int(eid):
    """Valeur entiere d'un ElementId (Revit <= 2023 : IntegerValue, >= 2024 : Value)."""
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


def make_eid(number):
    try:
        return ElementId(int(number))
    except Exception:
        return ElementId(long(number))  # noqa: F821  (IronPython / Revit 2024+)


def get_name(element):
    try:
        return element.Name
    except Exception:
        pass
    for bip in (BuiltInParameter.ALL_MODEL_TYPE_NAME, BuiltInParameter.SYMBOL_NAME_PARAM,
                BuiltInParameter.DATUM_TEXT, BuiltInParameter.ROOM_NAME):
        try:
            p = element.get_Parameter(bip)
            if p is not None and p.AsString():
                return p.AsString()
        except Exception:
            pass
    return u""


def param_text(element, bip):
    """Texte d'un parametre integre (ex. ROOM_NUMBER), u"" si absent."""
    p = element.get_Parameter(bip)
    return (p.AsString() or u"") if p is not None else u""


# ------------------------------------------------------------ parametres
def set_param(p, text):
    """Ecrit `text` dans le parametre selon son type. Retourne (ok, message)."""
    if p is None:
        return False, u"parametre introuvable"
    if p.IsReadOnly:
        return False, u"parametre en lecture seule"
    st = p.StorageType
    try:
        if st == StorageType.String:
            return bool(p.Set(text)), u""
        if st == StorageType.Integer:
            low = norm(text)
            if low in (u"oui", u"yes", u"true", u"vrai", u"x"):
                value = 1
            elif low in (u"non", u"no", u"false", u"faux"):
                value = 0
            else:
                value = int(float(text.replace(u",", u".")))
            return bool(p.Set(value)), u""
        if st == StorageType.Double:
            # SetValueString : la valeur est lue dans les unites d'affichage du projet
            if p.SetValueString(text):
                return True, u""
            return bool(p.SetValueString(text.replace(u",", u"."))), u"valeur numerique refusee"
        if st == StorageType.ElementId:
            return bool(p.Set(make_eid(int(float(text))))), u""
    except Exception as ex:
        return False, u"%s" % ex
    return False, u"type de parametre non gere"


def lookup_param(element, names=(), bip_names=()):
    """Cherche un parametre par BuiltInParameter (noms en texte) puis par nom."""
    for bip_name in bip_names:
        bip = getattr(BuiltInParameter, bip_name, None)
        if bip is not None:
            p = element.get_Parameter(bip)
            if p is not None:
                return p
    for name in names:
        p = element.LookupParameter(name)
        if p is not None:
            return p
    return None


# ----------------------------------------------------------- index elements
class ElementIndex(object):
    """Liste (element, categorie, famille, type) normalises, pour filtrer sans relire Revit."""

    def __init__(self, doc, model_only=False):
        self.doc = doc
        self.items = []
        collector = FilteredElementCollector(doc).WhereElementIsNotElementType()
        for el in collector:
            cat = el.Category
            if cat is None:
                continue
            if model_only and cat.CategoryType != CategoryType.Model:
                continue
            tid = el.GetTypeId()
            if eid_int(tid) < 0:
                continue
            t = doc.GetElement(tid)
            if t is None:
                continue
            family = getattr(t, "FamilyName", u"") or u""
            self.items.append(
                (el, norm(cat.Name), norm(family), norm(get_name(t)), t)
            )

    def match(self, categorie=u"", famille=u"", type_name=u""):
        c, f, t = norm(categorie), norm(famille), norm(type_name)
        return [
            it for it in self.items
            if (not c or it[1] == c) and (not f or it[2] == f) and (not t or it[3] == t)
        ]
