"""باز کردن xlsx وقتی بخش اختیاری برای موتور ناخوانا است.

جدول محوری، نمودار، پیوند بیرونی و قالب‌بندی مقدار سلول نیستند.
اگر خواندن معمولی بشکند، همان بخش‌ها از یک رونوشت حافظه کنار گذاشته می‌شوند.
بایت فایل اصلی این‌جا نوشته نمی‌شود.
"""

from __future__ import annotations

import zipfile
from io import BytesIO
from xml.etree import ElementTree as ET
from xml.etree.ElementTree import ParseError

import openpyxl
from openpyxl.utils.exceptions import InvalidFileException

LOAD_ERRORS = (
    InvalidFileException,
    zipfile.BadZipFile,
    OSError,
    ValueError,
    KeyError,
    ParseError,
    TypeError,
    IndexError,
    AttributeError,
)

_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_REL_ID = f"{{{_REL}}}id"

_DROP_REL = {
    "pivottable",
    "pivotcachedefinition",
    "pivotcacherecords",
    "table",
    "drawing",
    "chart",
    "comments",
    "vmldrawing",
    "image",
    "printersettings",
    "externallink",
    "externallinkpath",
    "hyperlink",
    "control",
    "oleobject",
    "customxml",
    "slicer",
    "slicercache",
    "timeline",
    "timelinecache",
    "querytable",
    "volatiledependencies",
    "calcchain",
    "chartsheet",
    "dialogsheet",
    "xmlmaps",
    "connections",
}

_DROP_WORKBOOK = {
    "externalReferences",
    "pivotCaches",
    "definedNames",
    "extLst",
    "customWorkbookViews",
    "smartTagPr",
    "smartTagTypes",
    "oleSize",
    "fileRecoveryPr",
    "functionGroups",
    "webPublishing",
    "webPublishObjects",
}

_DROP_SHEET = {
    "tableParts",
    "drawing",
    "legacyDrawing",
    "legacyDrawingHF",
    "picture",
    "oleObjects",
    "controls",
    "hyperlinks",
    "extLst",
}

_DROP_SHEET_DEEP = _DROP_SHEET | {
    "mergeCells",
    "conditionalFormatting",
    "dataValidations",
    "autoFilter",
    "phoneticPr",
    "rowBreaks",
    "colBreaks",
    "headerFooter",
}

_SKIP_PARTS = {"docprops/custom.xml"}
_SKIP_PARTS_DEEP = _SKIP_PARTS | {"docprops/core.xml", "docprops/app.xml"}

_MINIMAL_STYLES = """<?xml version="1.0" encoding="UTF-8"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="1"><font><sz val="11"/><color theme="1"/><name val="Calibri"/><family val="2"/></font></fonts>
  <fills count="2">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
  </fills>
  <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>
""".encode()


def open_xlsx(data: bytes):
    """کتاب فرمول، کتاب مقدار ذخیره‌شده، و اینکه رونوشت تعمیر شده یا نه.

    اگر موتور هیچ‌کدام را باز نکند، None برمی‌گردد.
    """
    book = _open(data, data_only=False)
    if book is not None:
        return book, _open(data, data_only=True), False
    light = _sanitize(data, deep=False)
    if light is not data:
        book = _open(light, data_only=False)
        if book is not None:
            return book, _open(light, data_only=True), True
    deep = _sanitize(data, deep=True)
    if deep is not data and deep is not light:
        book = _open(deep, data_only=False)
        if book is not None:
            return book, _open(deep, data_only=True), True
    return None


def _open(data: bytes, data_only: bool):
    try:
        book = openpyxl.load_workbook(
            BytesIO(data),
            data_only=data_only,
            read_only=False,
            keep_links=False,
        )
    except LOAD_ERRORS:
        return None
    if not book.worksheets:
        book.close()
        return None
    return book


def _sanitize(data: bytes, deep: bool) -> bytes:
    try:
        source = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile:
        return data
    changed = False
    buffer = BytesIO()
    skip = _SKIP_PARTS_DEEP if deep else _SKIP_PARTS
    chartsheets = _chartsheet_ids(source)
    try:
        with zipfile.ZipFile(buffer, "w") as archive:
            for info in source.infolist():
                name = info.filename.replace("\\", "/")
                if name.lower() in skip:
                    changed = True
                    continue
                payload = source.read(info.filename)
                if deep and name.lower() == "xl/styles.xml":
                    archive.writestr(name, _MINIMAL_STYLES)
                    changed = True
                    continue
                rewritten = _rewrite(name, payload, deep, chartsheets)
                if rewritten is None:
                    archive.writestr(info, payload)
                else:
                    archive.writestr(name, rewritten)
                    changed = True
    finally:
        source.close()
    if not changed:
        return data
    return buffer.getvalue()


def _rewrite(name: str, payload: bytes, deep: bool, chartsheets: set[str]) -> bytes | None:
    lower = name.lower()
    if lower.endswith(".rels"):
        return _rewrite_rels(payload)
    if lower == "xl/workbook.xml":
        return _rewrite_workbook(payload, chartsheets)
    if lower.startswith("xl/worksheets/") and lower.endswith(".xml"):
        return _rewrite_sheet(payload, deep)
    return None


def _rewrite_rels(payload: bytes) -> bytes | None:
    try:
        root = ET.fromstring(payload)
    except ParseError:
        return None
    dropped = False
    for child in list(root):
        kind = _rel_kind(child.get("Type"))
        if kind in _DROP_REL:
            root.remove(child)
            dropped = True
    if not dropped:
        return None
    return ET.tostring(root, encoding="UTF-8", xml_declaration=True)


def _rewrite_workbook(payload: bytes, chartsheets: set[str]) -> bytes | None:
    try:
        root = ET.fromstring(payload)
    except ParseError:
        return None
    changed = False
    for child in list(root):
        if _local(child.tag) in _DROP_WORKBOOK:
            root.remove(child)
            changed = True
    sheets = next((child for child in root if _local(child.tag) == "sheets"), None)
    if sheets is not None and chartsheets:
        for sheet in list(sheets):
            if sheet.get(_REL_ID) in chartsheets:
                sheets.remove(sheet)
                changed = True
    if not changed:
        return None
    return ET.tostring(root, encoding="UTF-8", xml_declaration=True)


def _chartsheet_ids(archive: zipfile.ZipFile) -> set[str]:
    """شناسه برگه نموداری که رابطه‌اش حذف می‌شود، تا ارجاع یتیم نماند."""
    name = next(
        (
            info.filename
            for info in archive.infolist()
            if info.filename.replace("\\", "/").lower() == "xl/_rels/workbook.xml.rels"
        ),
        None,
    )
    if name is None:
        return set()
    try:
        root = ET.fromstring(archive.read(name))
    except ParseError:
        return set()
    found: set[str] = set()
    for child in root:
        if _rel_kind(child.get("Type")) == "chartsheet":
            rel_id = child.get("Id")
            if rel_id:
                found.add(rel_id)
    return found


def _rewrite_sheet(payload: bytes, deep: bool) -> bytes | None:
    try:
        root = ET.fromstring(payload)
    except ParseError:
        return None
    drop = _DROP_SHEET_DEEP if deep else _DROP_SHEET
    changed = False
    for child in list(root):
        if _local(child.tag) in drop:
            root.remove(child)
            changed = True
    if deep and _strip_style(root):
        changed = True
    if not changed:
        return None
    return ET.tostring(root, encoding="UTF-8", xml_declaration=True)


def _strip_style(root: ET.Element) -> bool:
    changed = False
    for node in root.iter():
        if _local(node.tag) not in {"c", "row", "col"}:
            continue
        for attr in ("s", "style"):
            if attr in node.attrib:
                del node.attrib[attr]
                changed = True
    return changed


def _rel_kind(value: str | None) -> str:
    if not value:
        return ""
    return value.rstrip("/").rsplit("/", 1)[-1].lower()


def _local(tag: str) -> str:
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag
