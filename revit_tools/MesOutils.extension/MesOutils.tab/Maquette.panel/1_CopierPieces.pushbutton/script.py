# -*- coding: utf-8 -*-
__title__ = u"Copier\npièces"
__doc__ = (u"Copie dans la maquette active les pièces MANQUANTES d'une autre maquette ouverte "
           u"(même position) : séparations de pièces + pièces, sans murs.")

import traceback

from pyrevit import revit, forms, script
from Autodesk.Revit.DB import (
    BuiltInCategory, BuiltInParameter, CurveArray, FailureProcessingResult, FailureSeverity,
    FilteredElementCollector, IFailuresPreprocessor, Level, Plane, SketchPlane,
    SpatialElementBoundaryLocation, SpatialElementBoundaryOptions, Transaction, Transform,
    UV, ViewFamily, ViewFamilyType, ViewPlan, ViewType, XYZ,
)

import arep_revit as ar

doc = revit.doc
output = script.get_output()

TOL_LEVEL = 0.01      # pieds (~3 mm) : tolérance pour reconnaître le même niveau
SQFT_TO_M2 = 0.09290304


class WarningSwallower(IFailuresPreprocessor):
    """Supprime les avertissements (ex. séparations qui se recouvrent) pour ne pas bloquer."""

    def PreprocessFailures(self, accessor):
        for msg in accessor.GetFailureMessages():
            if msg.GetSeverity() == FailureSeverity.Warning:
                accessor.DeleteWarning(msg)
        return FailureProcessingResult.Continue


def last_error():
    lines = [l for l in traceback.format_exc().strip().splitlines() if l.strip()]
    return u" | ".join(lines[-3:])


def room_label(room):
    return u"{} {}".format(ar.param_text(room, BuiltInParameter.ROOM_NUMBER),
                           ar.param_text(room, BuiltInParameter.ROOM_NAME)).strip()


def point_in_polygon(x, y, poly):
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def candidate_points(poly, location_pt):
    """Points d'insertion à essayer : emplacement d'origine, centre, puis grille intérieure."""
    cands = []
    if location_pt is not None:
        cands.append((location_pt.X, location_pt.Y))
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    cands.append(((x0 + x1) / 2.0, (y0 + y1) / 2.0))
    n = 8
    for i in range(1, n):
        for j in range(1, n):
            cands.append((x0 + (x1 - x0) * i / float(n), y0 + (y1 - y0) * j / float(n)))
    return [c for c in cands if point_in_polygon(c[0], c[1], poly)]


def key_of(curve):
    a, b = curve.GetEndPoint(0), curve.GetEndPoint(1)
    ka = (round(a.X, 3), round(a.Y, 3))
    kb = (round(b.X, 3), round(b.Y, 3))
    return tuple(sorted([ka, kb])) + (curve.GetType().Name,)


def plan_view_for(level):
    for v in FilteredElementCollector(doc).OfClass(ViewPlan):
        if (not v.IsTemplate and v.ViewType == ViewType.FloorPlan
                and v.GenLevel is not None and v.GenLevel.Id == level.Id):
            return v
    for vft in FilteredElementCollector(doc).OfClass(ViewFamilyType):
        if vft.ViewFamily == ViewFamily.FloorPlan:
            return ViewPlan.Create(doc, vft.Id, level.Id)
    return None


def copy_params(src, dst):
    for bip in (BuiltInParameter.ROOM_NAME, BuiltInParameter.ROOM_NUMBER,
                BuiltInParameter.ROOM_DEPARTMENT):
        ps, pd = src.get_Parameter(bip), dst.get_Parameter(bip)
        if ps is not None and pd is not None and not pd.IsReadOnly and ps.AsString() is not None:
            try:
                pd.Set(ps.AsString())
            except Exception:
                pass
    for ps in src.Parameters:
        try:
            if not ps.IsShared or ps.IsReadOnly or not ps.HasValue:
                continue
            pd = dst.get_Parameter(ps.GUID)
            if pd is None or pd.IsReadOnly or pd.StorageType != ps.StorageType:
                continue
            kind = ps.StorageType.ToString()
            if kind == "String":
                pd.Set(ps.AsString())
            elif kind == "Integer":
                pd.Set(ps.AsInteger())
            elif kind == "Double":
                pd.Set(ps.AsDouble())
        except Exception:
            pass


# ------------------------------------------------------------------ choix de la maquette source
others = [d for d in doc.Application.Documents
          if d.Title != doc.Title and not d.IsLinked and not d.IsFamilyDocument]
if not others:
    forms.alert(u"Aucune autre maquette ouverte.\nOuvrez la maquette source dans Revit "
                u"(Fichier > Ouvrir), puis relancez.", exitscript=True)

labels = dict((d.Title, d) for d in others)
choice = forms.SelectFromList.show(sorted(labels), title=u"Maquette SOURCE des pièces (ouverte)",
                                   multiselect=False, button_name=u"Choisir")
if not choice:
    script.exit()
src_doc = labels[choice]

# ------------------------------------------------------------------ niveaux cibles
target_levels = list(FilteredElementCollector(doc).OfClass(Level))


def target_level_for(src_level):
    for lv in target_levels:
        if abs(lv.Elevation - src_level.Elevation) <= TOL_LEVEL:
            return lv
    for lv in target_levels:
        if ar.norm(ar.get_name(lv)) == ar.norm(ar.get_name(src_level)):
            return lv
    return None


# ------------------------------------------------------------------ pièces source / existantes
opts = SpatialElementBoundaryOptions()
opts.SpatialElementBoundaryLocation = SpatialElementBoundaryLocation.Finish

src_rooms = []
for r in FilteredElementCollector(src_doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType():
    if r.Area > 0 and r.Location is not None and r.Level is not None:
        src_rooms.append(r)
if not src_rooms:
    forms.alert(u"Aucune pièce placée dans « {} ».".format(src_doc.Title), exitscript=True)

existing_numbers = set()
for r in FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType():
    if r.Level is not None and r.Area > 0:
        existing_numbers.add((ar.eid_int(r.Level.Id), ar.param_text(r, BuiltInParameter.ROOM_NUMBER)))

# ------------------------------------------------------------------ travail
skipped, failed, created = [], [], []
tolerance = doc.Application.ShortCurveTolerance

t = Transaction(doc, u"Copier pièces manquantes")
t.Start()
fo = t.GetFailureHandlingOptions()
fo.SetFailuresPreprocessor(WarningSwallower())
t.SetFailureHandlingOptions(fo)

try:
    jobs = []             # (room_src, level, contour_pts, location_pt)
    lines_by_level = {}   # id niveau -> (level, [courbes], set(cles))
    for room in src_rooms:
        label = room_label(room)
        try:
            lv = target_level_for(room.Level)
            if lv is None:
                skipped.append(label + u" : niveau « {} » absent de la maquette active".format(
                    ar.get_name(room.Level)))
                continue
            number = ar.param_text(room, BuiltInParameter.ROOM_NUMBER)
            if (ar.eid_int(lv.Id), number) in existing_numbers:
                skipped.append(label + u" : déjà présente (même numéro, même niveau)")
                continue
            probe = XYZ(room.Location.Point.X, room.Location.Point.Y, lv.Elevation + 3.0)
            if doc.GetRoomAtPoint(probe) is not None:
                skipped.append(label + u" : une pièce existe déjà à cet emplacement")
                continue

            segs = room.GetBoundarySegments(opts)
            if not segs:
                skipped.append(label + u" : pas de contour")
                continue

            entry = lines_by_level.setdefault(ar.eid_int(lv.Id), (lv, [], set()))
            outer_pts = []
            for i, loop in enumerate(segs):
                pts = []
                for seg in loop:
                    crv = seg.GetCurve()
                    dz = lv.Elevation - crv.GetEndPoint(0).Z
                    if abs(dz) > 1e-9:
                        crv = crv.CreateTransformed(Transform.CreateTranslation(XYZ(0, 0, dz)))
                    if crv.Length < tolerance:
                        continue
                    for q in crv.Tessellate():
                        pts.append((q.X, q.Y))
                    k = key_of(crv)
                    if k not in entry[2]:
                        entry[2].add(k)
                        entry[1].append(crv)
                if i == 0:
                    outer_pts = pts
            jobs.append((room, lv, outer_pts, room.Location.Point))
        except Exception:
            failed.append(label + u" : lecture du contour impossible : " + last_error())

    for lv, curves, _keys in lines_by_level.values():
        try:
            view = plan_view_for(lv)
            if view is None:
                failed.append(u"Niveau {} : aucune vue en plan disponible".format(ar.get_name(lv)))
                continue
            sketch = SketchPlane.Create(doc, Plane.CreateByNormalAndOrigin(XYZ.BasisZ, XYZ(0, 0, lv.Elevation)))
            arr = CurveArray()
            for c in curves:
                arr.Append(c)
            doc.Create.NewRoomBoundaryLines(sketch, arr, view)
        except Exception:
            failed.append(u"Niveau {} : séparations non créées : {}".format(ar.get_name(lv), last_error()))

    doc.Regenerate()

    for room, lv, outer_pts, loc in jobs:
        label = room_label(room)
        try:
            new_room = None
            for (x, y) in candidate_points(outer_pts, loc):
                cand = doc.Create.NewRoom(lv, UV(x, y))
                if cand is None:
                    continue
                doc.Regenerate()
                if cand.Area > 0:
                    new_room = cand
                    break
                doc.Delete(cand.Id)
            if new_room is None:
                failed.append(label + u" : contour non fermé, pièce non créée")
                continue
            copy_params(room, new_room)
            created.append((label, room.Area, new_room.Area))
        except Exception:
            failed.append(label + u" : création impossible : " + last_error())

    t.Commit()
except Exception:
    t.RollBack()
    forms.alert(u"Erreur, rien n'a été modifié :\n{}".format(last_error()), exitscript=True)

# ------------------------------------------------------------------ rapport
output.print_md(u"## Pièces manquantes copiées depuis « {} »".format(src_doc.Title))
output.print_md(u"**{} créées**, {} ignorées, {} en échec".format(len(created), len(skipped), len(failed)))
diff = [(l, a * SQFT_TO_M2, b * SQFT_TO_M2) for l, a, b in created if abs(a - b) > 0.01 * a]
if diff:
    output.print_md(u"### Surface différente de plus de 1 % (à vérifier)")
    for l, a, b in diff:
        output.print_md(u"- {} : source {:.2f} m², créée {:.2f} m²".format(l, a, b))
if failed:
    output.print_md(u"### En échec")
    for s in failed:
        output.print_md(u"- " + s)
if skipped:
    output.print_md(u"### Ignorées (déjà présentes ou sans correspondance)")
    for s in skipped:
        output.print_md(u"- " + s)
