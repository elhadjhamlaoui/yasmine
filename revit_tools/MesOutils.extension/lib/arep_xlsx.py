# -*- coding: utf-8 -*-
"""Lecteur .xlsx minimal (sans Excel, sans openpyxl) : compatible IronPython 2.7 et CPython 3.

read_xlsx(path) -> (entetes, lignes)
  entetes : liste des titres de la 1re ligne
  lignes  : liste de dict {titre: texte}. Toutes les valeurs sont du texte (cellule vide = u"").
"""
import re
import zipfile
import xml.etree.ElementTree as ET

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NS_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
NS_PKG = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _col_index(ref):
    letters = re.match(r"[A-Za-z]+", ref).group(0).upper()
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _text_of(node):
    return u"".join(t.text or u"" for t in node.iter(NS + "t"))


def _first_sheet_path(z):
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    first = wb.find(NS + "sheets").find(NS + "sheet")
    rid = first.get(NS_REL + "id")
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    for rel in rels.findall(NS_PKG + "Relationship"):
        if rel.get("Id") == rid:
            target = rel.get("Target")
            if target.startswith("/"):
                return target.lstrip("/")
            return "xl/" + target
    return "xl/worksheets/sheet1.xml"


def read_xlsx(path):
    z = zipfile.ZipFile(path)
    try:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            shared = [_text_of(si) for si in root.findall(NS + "si")]

        sheet = ET.fromstring(z.read(_first_sheet_path(z)))
    finally:
        z.close()

    table = []
    for row in sheet.iter(NS + "row"):
        values = {}
        for c in row.findall(NS + "c"):
            kind = c.get("t")
            v = c.find(NS + "v")
            if kind == "s" and v is not None:
                text = shared[int(v.text)]
            elif kind == "inlineStr":
                text = _text_of(c)
            elif v is not None and v.text is not None:
                text = v.text
                if kind == "b":
                    text = u"1" if text == "1" else u"0"
            else:
                text = u""
            values[_col_index(c.get("r"))] = text.strip()
        if values:
            width = max(values) + 1
            table.append([values.get(i, u"") for i in range(width)])

    if not table:
        return [], []

    headers = table[0]
    rows = []
    for raw in table[1:]:
        if not any(raw):
            continue
        raw = raw + [u""] * (len(headers) - len(raw))
        rows.append(dict((h, raw[i]) for i, h in enumerate(headers) if h))
    return headers, rows
