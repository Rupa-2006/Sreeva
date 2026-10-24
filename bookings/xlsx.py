"""A tiny Excel (.xlsx) writer with no extra packages.

An .xlsx file is a zip of XML files. This writes just what Excel needs:
several sheets, a bold header row that stays on screen, filters, column widths,
dates, and money in Indian format (₹1,23,456). Text is always stored as text,
never as a formula, so a customer name like "=HYPERLINK(...)" can't run in Excel.
"""
import io
import re
import zipfile
from datetime import date, datetime
from decimal import Decimal
from xml.sax.saxutils import escape

TEXT, MONEY, DATE, NUMBER = "text", "money", "date", "number"
_BAD = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_EPOCH = date(1899, 12, 30)
_STYLE = {TEXT: 0, "head": 1, DATE: 2, MONEY: 3, NUMBER: 4}


def _col(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _cell(ref, value, kind):
    if value is None or value == "":
        return ""
    if kind == DATE and isinstance(value, (date, datetime)):
        d = value.date() if isinstance(value, datetime) else value
        return f'<c r="{ref}" s="2"><v>{(d - _EPOCH).days}</v></c>'
    if kind in (MONEY, NUMBER) and isinstance(value, (int, float, Decimal)):
        return f'<c r="{ref}" s="{_STYLE[kind]}"><v>{value}</v></c>'
    text = escape(_BAD.sub("", str(value)))[:32000]
    style = ' s="1"' if kind == "head" else ""
    return f'<c r="{ref}"{style} t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'


def _sheet(columns, rows):
    """columns: [(header, kind, width)]"""
    last = _col(len(columns) - 1)
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
           '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" '
           'state="frozen"/></sheetView></sheetViews>',
           '<cols>' + "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>'
                              for i, (_, _, w) in enumerate(columns)) + '</cols>',
           '<sheetData>',
           '<row r="1">' + "".join(_cell(f"{_col(i)}1", h, "head") for i, (h, _, _) in enumerate(columns)) + '</row>']
    for r, row in enumerate(rows, start=2):
        out.append(f'<row r="{r}">' + "".join(
            _cell(f"{_col(i)}{r}", v, columns[i][1]) for i, v in enumerate(row)) + '</row>')
    out.append('</sheetData>')
    out.append(f'<autoFilter ref="A1:{last}{max(len(rows) + 1, 1)}"/>')
    out.append('</worksheet>')
    return "".join(out)


_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="2"><numFmt numFmtId="164" formatCode="dd-mmm-yyyy"/>
<numFmt numFmtId="165" formatCode="[&gt;=10000000]&quot;₹&quot;##\\,##\\,##\\,##0;[&gt;=100000]&quot;₹&quot;##\\,##\\,##0;&quot;₹&quot;##,##0"/></numFmts>
<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font></fonts>
<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFC2611C"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="5">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>
<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="1" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>"""


def workbook(sheets):
    """sheets: [(name, columns, rows)] -> .xlsx bytes"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        n = len(sheets)
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + "".join(f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                             for i in range(n)) + '</Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   '</Relationships>')
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{escape(name[:31])}" sheetId="{i + 1}" r:id="rId{i + 1}"/>'
                             for i, (name, _, _) in enumerate(sheets)) + '</sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i + 1}.xml"/>'
                             for i in range(n))
                   + f'<Relationship Id="rId{n + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                   '</Relationships>')
        z.writestr("xl/styles.xml", _STYLES)
        for i, (_, columns, rows) in enumerate(sheets):
            z.writestr(f"xl/worksheets/sheet{i + 1}.xml", _sheet(columns, rows))
    return buf.getvalue()
