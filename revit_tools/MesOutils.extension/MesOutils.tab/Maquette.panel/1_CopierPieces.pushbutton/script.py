# -*- coding: utf-8 -*-
__title__ = u"Copier\npièces"
__doc__ = (u"Redessine dans la maquette active les pièces d'une maquette liée : "
           u"séparations de pièces + pièces au même emplacement, sans murs.")

from pyrevit import revit, forms, script
from Autodesk.Revit.DB import (
    BuiltInCategory, BuiltInParameter, FailureProcessingResult, FailureSeverity,
    FilteredElementCollector, IFailuresPreprocessor, Level, Line, Plane,
    RevitLinkInstance, SketchPlane, SpatialElementBoundaryLocation,
    SpatialElementBoundaryOptions, Transaction, UV, View, ViewFamily,
    ViewFamilyType, ViewPlan, ViewType, XYZ, Transform, CurveArray,
)

import arep_revit as ar

doc = revit.doc
output = script.get_output()

TOL_LEVEL = 0.01      # pieds (~3 mm) : tolérance pour reconnaître le même niveau
COPIED_BIP = [
    BuiltInParameter.ROOM_NAME, BuiltInParameter.ROOM_NUMBER,
    BuiltInParameter.ROOM_DEPARTMENT,
]


class WarningSwallower(IFailuresPreprocessor):
    """Supprime les avertissements (ex. séparations qui se recouvrent) pour ne pas bloquer."""

    def PreprocessFailures(self, accessor):
        for msg in accessor.GetFailureMessages():
            if msg.GetSeverity() == FailureSeverity.Warning:
                accessor.DeleteWarning(msg)
        return FailureProcessingResult.Continue


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


def candidate_points(loop_pts, location_pt):
    """Points d'insertion à essayer : emplacement d'origine, centre, puis grille intérieure."""
    cands = []
    if location_pt is not None:
        cands.append((location_pt.X, location_pt.Y))
    xs = [p[0] for p in loop_pts]
    ys = [p[1] for p in loop_pts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    cands.append(((x0 + x1) / 2.0, (y0 + y1) / 2.0))
    n = 8
    for i in range(1, n):
        for j in range(1, n):
            cands.append((x0 + (x1 - x0) * i / float(n), y0 + (y1 - y0) * j / float(n)))
    return [c for c in cands if point_in_polygon(c[0], c[1], loop_pts)]


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
    for bip in COPIED_BIP:
        ps, pd = src.get_Parameter(bip), dst.get_Parameter(bip)
        if ps is not None and pd is not None and ps.HasValue and not pd.IsReadOnly:
            try:
                pd.Set(ps.AsString() if ps.AsString() is not None else ps.AsValueString())
            except Exception:
                pass
    for ps in src.Parameters:
        if not ps.IsShared or ps.IsReadOnly or not ps.HasValue:
            continue
        pd = dst.get_Parameter(ps.GUID)
        if pd is None or pd.IsReadOnly or pd.StorageType != ps.StorageType:
            continue
        try:
            st = ps.StorageType.ToString()
            if st == "String":
                pd.Set(ps.AsString())
            elif st == "Integer":
                pd.Set(ps.AsInteger())
            elif st == "Double":
                pd.Set(ps.AsDouble())
        except Exception:
            pass


# ------------------------------------------------------------------ choix de la maquette source
links = [l for l in FilteredElementCollector(doc).OfClass(RevitLinkInstance)
         if l.GetLinkDocument() is not None]
if not links:
    forms.alert(u"Aucune maquette liée chargée.\nInsérez d'abord la maquette source "
                u"(Insérer > Lier Revit), au même point de base / mêmes coordonnées.",
                exitscript=True)

labels = dict((u"{} (id {})".format(l.Name, ar.eid_int(l.Id)), l) for l in links)
choice = forms.SelectFromList.show(sorted(labels), title=u"Maquette source des pièces",
                                   multiselect=False, button_name=u"Copier les pièces")
if not choice:
    script.exit()
link = labels[choice]
link_doc = link.GetLinkDocument()
xform = link.GetTotalTransform()

# ------------------------------------------------------------------ niveaux cibles
target_levels = list(FilteredElementCollector(doc).OfClass(Level))


def target_level_for(src_level):
    z = xform.OfPoint(XYZ(0, 0, src_level.Elevation)).Z
    for lv in target_levels:
        if abs(lv.Elevation - z) <= TOL_LEVEL:
            return lv
    for lv in target_levels:
        if ar.norm(lv.Name) == ar.norm(src_level.Name):
            return lv
    return None


# ------------------------------------------------------------------ lecture des pièces source
opts = SpatialElementBoundaryOptions()
opts.SpatialElementBoundaryLocation = SpatialElementBoundaryLocation.Finish

src_rooms = []
for r in FilteredElementCollector(link_doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType():
    if r.Area > 0 and r.Location is not None and r.Level is not None:
        src_rooms.append(r)

if not src_rooms:
    forms.alert(u"Aucune pièce placée dans la maquette liée.", exitscript=True)
if not forms.alert(u"{} pièces trouvées dans « {} ».\nElles seront redessinées dans la maquette active "
                   u"(lignes de séparation + pièces).\nContinuer ?".format(len(src_rooms), link_doc.Title),
                   yes=True, no=True):
    script.exit()

existing = set()
for r in FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType():
    if r.Level is not None:
        p = r.get_Parameter(BuiltInParameter.ROOM_NUMBER)
        existing.add((ar.eid_int(r.Level.Id), p.AsString() if p else u""))

# ------------------------------------------------------------------ travail
report_skipped, report_failed, created = [], [], []
tolerance = doc.Application.ShortCurveTolerance

t = Transaction(doc, u"Copier pièces depuis maquette liée")
t.Start()
fo = t.GetFailureHandlingOptions()
fo.SetFailuresPreprocessor(WarningSwallower())
t.SetFailureHandlingOptions(fo)

try:
    # 1) contours -> lignes de séparation, par niveau
    jobs = []          # (room_src, level, loops_pts, location_pt)
    lines_by_level = {}  # level id -> (level, [curves], set(keys))
    for room in src_rooms:
        lv = target_level_for(room.Level)
        label = u"{} {}".format(room.Number, room.Name)
        if lv is None:
            report_skipped.append(label + u" : niveau « {} » introuvable".format(room.Level.Name))
            continue
        num_key = (ar.eid_int(lv.Id), room.Number)
        if num_key in existing:
            report_skipped.append(label + u" : numéro déjà présent sur ce niveau")
            continue

        segs = room.GetBoundarySegments(opts)
        if not segs:
            report_skipped.append(label + u" : pas de contour")
            continue

        entry = lines_by_level.setdefault(ar.eid_int(lv.Id), (lv, [], set()))
        loops_pts = []
        for loop in segs:
            pts = []
            for seg in loop:
                crv = seg.GetCurve().CreateTransformed(xform)
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
            loops_pts.append(pts)
        loc = xform.OfPoint(room.Location.Point)
        jobs.append((room, lv, loops_pts, loc))

    for lv, curves, _ in lines_by_level.values():
        view = plan_view_for(lv)
        if view is None:
            report_failed.append(u"Niveau {} : aucune vue en plan disponible".format(lv.Name))
            continue
        sketch = SketchPlane.Create(doc, Plane.CreateByNormalAndOrigin(XYZ.BasisZ, XYZ(0, 0, lv.Elevation)))
        arr = CurveArray()
        for c in curves:
            arr.Append(c)
        doc.Create.NewRoomBoundaryLines(sketch, arr, view)

    doc.Regenerate()

    # 2) pièces
    for room, lv, loops_pts, loc in jobs:
        label = u"{} {}".format(room.Number, room.Name)
        outer = max(loops_pts, key=len) if loops_pts else []
        new_room = None
        for (x, y) in candidate_points(outer, loc):
            cand = doc.Create.NewRoom(lv, UV(x, y))
            if cand is None:
                continue
            doc.Regenerate()
            if cand.Area > 0:
                new_room = cand
                break
            doc.Delete(cand.Id)
        if new_room is None:
            report_failed.append(label + u" : contour non fermé dans la maquette active")
            continue
        copy_params(room, new_room)
        created.append((label, room.Area, new_room.Area))

    t.Commit()
except Exception as ex:
    t.RollBack()
    forms.alert(u"Erreur, rien n'a été modifié :\n{}".format(ex), exitscript=True)

# ------------------------------------------------------------------ rapport
output.print_md(u"## Copie des pièces depuis « {} »".format(link_doc.Title))
output.print_md(u"**{} pièces créées**, {} ignorées, {} en échec".format(
    len(created), len(report_skipped), len(report_failed)))

SQFT_TO_M2 = 0.09290304
diff = [(l, a * SQFT_TO_M2, b * SQFT_TO_M2) for l, a, b in created if abs(a - b) > 0.01 * a]
if diff:
    output.print_md(u"### Surfaces différentes de plus de 1 % (à vérifier)")
    for l, a, b in diff:
        output.print_md(u"- {} : source {:.2f} m², créée {:.2f} m²".format(l, a, b))
if report_skipped:
    output.print_md(u"### Ignorées")
    for s in report_skipped:
        output.print_md(u"- " + s)
if report_failed:
    output.print_md(u"### En échec")
    for s in report_failed:
        output.print_md(u"- " + s)
