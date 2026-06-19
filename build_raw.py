#!/usr/bin/env python3
"""
build_raw.py — Generates the RAW, pre-ingestion source files for the Helios
Plant 7 world, in the messy heterogeneous formats a real factory emits.

Purpose: let you build and test a full ingestion architecture FROM SCRATCH
(format detection, parsing, text extraction, cleaning/normalization, entity
extraction, doc splitting, dedup, chunking) — not just embed clean JSONL.

Pipeline contract:
    raw/  --[YOUR INGESTION]-->  ~corpus.jsonl (canonical target)
                                      |
                                 questions.jsonl (end-to-end eval)

Every raw source carries the SAME facts as the canonical corpus, but dirtied
the way real data is dirty. raw/INGESTION_GROUND_TRUTH.jsonl maps each raw file
to the canonical doc_id(s) it should yield + the key facts extraction must
recover + the specific "mess challenges" it plants — so ingestion is scorable.

Standard library only (json, csv, pathlib, random, zipfile). No network.

Real binary formats produced by hand (to exercise real parsers):
  - .xlsx  (OOXML zip, inline strings)        -> Q1_2025_FPY.xlsx
  - .docx  (OOXML zip)                         -> SOP-001_Rev2.docx
  - .pdf   (hand-built, Helvetica text)        -> HX-900_excerpt.pdf
"""

import csv
import io
import json
import random
import zipfile
from pathlib import Path

random.seed(7)  # deterministic output

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"

GROUND_TRUTH = []  # manifest entries


def gt(source, fmt, maps_to, doc_type, key_facts, mess, notes=""):
    GROUND_TRUTH.append({
        "source_file": source,
        "format": fmt,
        "maps_to_doc_ids": maps_to,
        "doc_type": doc_type,
        "key_facts": key_facts,
        "mess_challenges": mess,
        "notes": notes,
    })


def w(relpath, content, encoding="utf-8", bom=False):
    """Write a text file (optionally with a UTF-8 BOM or alternate encoding)."""
    p = RAW / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    data = content
    if bom and encoding.lower().startswith("utf-8"):
        data = "﻿" + content
    p.write_text(data, encoding=encoding)


def wb(relpath, data: bytes):
    p = RAW / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


# ---------------------------------------------------------------------------
# Binary-format builders (stdlib only)
# ---------------------------------------------------------------------------
def _xml_escape(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _zip_bytes(files: dict) -> bytes:
    """Deterministic OOXML zip from {arcname: str|bytes}."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, payload in files.items():
            zi = zipfile.ZipInfo(name, date_time=(2025, 1, 1, 0, 0, 0))
            if isinstance(payload, str):
                payload = payload.encode("utf-8")
            z.writestr(zi, payload)
    return buf.getvalue()


def build_xlsx(rows, sheet_name="Sheet1") -> bytes:
    """Minimal valid .xlsx (inline strings). rows: list[list[cell]]."""
    def colname(n):  # 1-indexed -> A, B, ...
        s = ""
        while n > 0:
            n, r = divmod(n - 1, 26)
            s = chr(65 + r) + s
        return s

    sd = []
    for ri, row in enumerate(rows, 1):
        cells = []
        for ci, val in enumerate(row, 1):
            ref = f"{colname(ci)}{ri}"
            if isinstance(val, bool):
                val = str(val)
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                cells.append(f'<c r="{ref}"><v>{val}</v></c>')
            elif val is None or val == "":
                continue
            else:
                cells.append(f'<c r="{ref}" t="inlineStr">'
                             f'<is><t xml:space="preserve">{_xml_escape(val)}</t></is></c>')
        sd.append(f'<row r="{ri}">' + "".join(cells) + "</row>")
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             "<sheetData>" + "".join(sd) + "</sheetData></worksheet>")
    files = {
        "[Content_Types].xml":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            "</Types>",
        "_rels/.rels":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>",
        "xl/workbook.xml":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets><sheet name="{_xml_escape(sheet_name)}" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>",
        "xl/worksheets/sheet1.xml": sheet,
    }
    return _zip_bytes(files)


def build_docx(paragraphs) -> bytes:
    """Minimal valid .docx. paragraphs: list[str]."""
    body = ""
    for para in paragraphs:
        body += ('<w:p><w:r><w:t xml:space="preserve">'
                 + _xml_escape(para) + "</w:t></w:r></w:p>")
    body += "<w:sectPr/>"
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                f"<w:body>{body}</w:body></w:document>")
    files = {
        "[Content_Types].xml":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>",
        "_rels/.rels":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>",
        "word/document.xml": document,
    }
    return _zip_bytes(files)


def build_pdf(pages) -> bytes:
    """Minimal hand-built PDF. pages: list[list[str]] (each page = lines)."""
    n_pages = len(pages)
    num_objs = 3 + 2 * n_pages
    objs = {}
    objs[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    kids = " ".join(f"{5 + 2 * k} 0 R" for k in range(n_pages))
    objs[2] = (f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>").encode()
    objs[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    def esc(s):
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    for k, lines in enumerate(pages):
        content_num = 4 + 2 * k
        page_num = 5 + 2 * k
        body = "BT /F1 11 Tf 14 TL 1 0 0 1 50 740 Tm\n"
        for i, ln in enumerate(lines):
            body += (f"({esc(ln)}) Tj\n" if i == 0 else f"T* ({esc(ln)}) Tj\n")
        body += "ET"
        bb = body.encode("latin-1", "replace")
        objs[content_num] = (b"<< /Length %d >>\nstream\n" % len(bb)) + bb + b"\nendstream"
        objs[page_num] = (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            "/Resources << /Font << /F1 3 0 R >> >> "
            f"/Contents {content_num} 0 R >>").encode()

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = {}
    for n in range(1, num_objs + 1):
        offsets[n] = len(out)
        out += f"{n} 0 obj\n".encode() + objs[n] + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {num_objs + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for n in range(1, num_objs + 1):
        out += f"{offsets[n]:010d} 00000 n \n".encode()
    out += b"trailer\n" + f"<< /Size {num_objs + 1} /Root 1 0 R >>\n".encode()
    out += b"startxref\n" + f"{xref_pos}\n".encode() + b"%%EOF\n"
    return bytes(out)


# ===========================================================================
# 1) ERP exports (CSV) — dirty structured data
# ===========================================================================
# Supplier master: UTF-8 BOM, inconsistent headers/casing/whitespace,
# lead-time as days/weeks, country-name variants, embedded comma, a DUPLICATE
# supplier row differing in one field, a missing email.
w("erp/suppliers_master.csv", bom=True, content=
"""supplier_id,Name, country ,Products,Lead Time,contact_email
SUP-101, Titan Alloys Inc. , U.S.A. ,"4140 steel bar; 6061 aluminum billet",21 days,orders@titanalloys.example
SUP-102,Pacific Polymers Ltd.,USA,"PA66 pellets; PTFE seal stock",5 weeks,sales@pacificpolymers.example
SUP-103,Vector Bearings GmbH,Germany,precision bearings,45 days,export@vectorbearings.example
SUP-104,"Crescent Fasteners, Co.",Mexico,"hex bolts; fasteners",14 days,ventas@crescentfasteners.example
SUP-105,Lumen Sensors Corp.,United States,"vibration sensors; thermocouples",28 days,
SUP-104,"Crescent Fasteners, Co.",MX,"hex bolts; fasteners",2 weeks,ventas@crescentfasteners.example
""")
gt("erp/suppliers_master.csv", "csv", ["SUP-101", "SUP-102", "SUP-103", "SUP-104", "SUP-105"],
   "supplier",
   ["SUP-103 lead_time=45 days", "SUP-104 lead_time=14 days (=2 weeks)",
    "SUP-102 lead_time=35 days (=5 weeks)", "SUP-105 contact_email MISSING"],
   ["utf-8 BOM", "header whitespace/casing", "lead-time units days vs weeks",
    "country-name variants (U.S.A./USA/United States/MX/Mexico)",
    "embedded comma in quoted field", "DUPLICATE supplier row (SUP-104) differing in one field",
    "missing field (email)"],
   "Lead time must be normalized to days; weeks->days; dedup SUP-104.")

# Purchase orders: currency symbols/suffixes, thousands separators, mixed date
# formats, supplier by NAME (not id), missing MOQ.
w("erp/purchase_orders.csv", content=
"""PO,Supplier,Part,Qty,Unit Price,MOQ,Lead Time,Date
PO-9001,Vector Bearings GmbH,PRT-2003,200,$42.50,100,45 days,2025-01-10
PO-9002,Titan Alloys,4140 steel bar,50,"USD 115.00",,21 days,01/18/2025
PO-9003,Crescent Fasteners,PRT-2004,"5,000",0.35 USD,"1,000",14 days,2025-02-02
""")
gt("erp/purchase_orders.csv", "csv", ["PO-9001", "PO-9002", "PO-9003"],
   "purchase_order",
   ["PO-9001 qty=200 unit_price=42.50 total=8500", "PO-9003 qty=5000 unit_price=0.35 total=1750",
    "PO-9002 MOQ MISSING; supplier by name='Titan Alloys'->SUP-101"],
   ["currency symbol $ vs 'USD 115.00' vs '0.35 USD'", "thousands separators (5,000 / 1,000)",
    "date formats ISO vs mm/dd/yyyy", "supplier referenced by name not ID", "missing MOQ"],
   "Resolve supplier name->ID; strip currency; parse thousands; normalize dates.")

# BOM / parts: units embedded in values, +/- symbol, supplier by name/id mix,
# multi-machine list, missing material/program.
w("erp/bom_parts.csv", content=
"""part_id,description,material,dim_length,dim_od,tolerance,supplier,used_on,program
PRT-2001,Drive Shaft,4140 steel,250 mm,30 mm,+/-0.02 mm,SUP-101,MCH-301,BLUEBIRD
PRT-2002,Housing Cover,PA66,,,,Pacific Polymers,MCH-302,REDFOX
PRT-2003,Precision Bearing,,bore 30 mm,OD 62 mm,,Vector Bearings GmbH,MCH-301; MCH-303,
PRT-2004,Hex Bolt M10x40,Steel 8.8,40 mm,,,SUP-104,multiple,BLUEBIRD
PRT-2005,Vibration Sensor,,,,,SUP-105,MCH-301,
PRT-2006,PTFE Gasket,PTFE,,OD 60 mm,,SUP-102,REDFOX assy,
PRT-2007,Aluminum Bracket,6061-T6 aluminum,,,,Titan Alloys,MCH-304,TITAN-LINE
""")
gt("erp/bom_parts.csv", "csv",
   ["SPEC-2001", "SPEC-2002", "SPEC-2003", "SPEC-2004", "SPEC-2005", "SPEC-2006", "SPEC-2007"],
   "part_spec",
   ["PRT-2001 length=250mm od=30mm tol=0.02mm supplier=SUP-101 used_on=MCH-301",
    "PRT-2003 used_on=[MCH-301,MCH-303] supplier=SUP-103 (material MISSING here)",
    "PRT-2007 supplier 'Titan Alloys'->SUP-101 used_on=MCH-304"],
   ["units embedded in values (250 mm)", "tolerance as +/- text",
    "supplier name vs ID mix", "multi-value field 'MCH-301; MCH-303'",
    "missing material/program fields"],
   "Strip units to numerics; split multi-machine; backfill material from datasheets.")

# ===========================================================================
# 2) CMMS maintenance export (CSV) — downtime in INCONSISTENT units
# ===========================================================================
w("maintenance/cmms_export.csv", content=
"""WO,Asset,Machine,Date,Downtime,MTBF_hours,Technician,Notes
WO-5001,Cyclops,MCH-301,2025-02-10,4.5h,1820,J. Okafor,"Replaced spindle bearing PRT-2003 (Vector); rising vibration flagged by sensor"
WO-5002,Hydra,MCH-302,2025-03-22,360 min,,M. Adeyemi,"Barrel heater band failed; zone 2 under temp, short-shot risk"
WO-5003,Goliath,MCH-303,2025-04-05,3:00,,J. Okafor,"Scheduled spindle inspect + regrease; no parts"
WO-5004,Cyclops,MCH-301,2025-05-01,1h30m,,P. Nguyen,"Recalibrated PRT-2005 vibration sensor (Lumen) after Feb bearing job"
""")
gt("maintenance/cmms_export.csv", "csv", ["WO-5001", "WO-5002", "WO-5003", "WO-5004"],
   "work_order",
   ["WO-5001 downtime=4.5h(270min) MTBF=1820h part=PRT-2003 machine=MCH-301",
    "WO-5002 downtime=360min(6.0h)", "WO-5003 downtime=3:00(3.0h)", "WO-5004 downtime=1h30m(1.5h)"],
   ["downtime in 4 different unit formats (4.5h / 360 min / 3:00 / 1h30m)",
    "MTBF present on only one row", "asset by codename + machine ID both",
    "free-text notes column with embedded commas"],
   "Normalize all downtime to hours: 4.5 / 6.0 / 3.0 / 1.5.")

# Free-text shift log mixing several WOs in narrative (entity extraction test).
w("maintenance/shift_log_notes.txt", content=
"""=== NIGHT SHIFT MAINTENANCE LOG ===
Feb 10: Cyclops (the lathe cell) down ~4.5 hrs. Swapped the spindle bearing,
the Vector one (PRT-2003). Vibration had been creeping up for days.
Mar 22: Hydra on the KRAKEN line - heater band cooked on zone 2, ~6 hours to
sort it. Watch for short shots until temps stabilize.
May 1: came back to Cyclops to recal the Lumen vibration sensor (about an hour
and a half). Reading sits around 3.2 mm/s now, well under the 4.5 alarm.
""")
gt("maintenance/shift_log_notes.txt", "txt", ["WO-5001", "WO-5002", "WO-5004"],
   "work_order",
   ["corroborates WO-5001/5002/5004 with jargon", "vibration ~3.2 mm/s < 4.5 alarm"],
   ["free-text narrative", "codenames + jargon ('the lathe cell')",
    "approximate/rounded numbers", "multiple records in one blob"],
   "Cross-source corroboration; must link narrative back to WO IDs.")

# ===========================================================================
# 3) Historian / telemetry exports (CSV with preamble) — aggregate-on-ingest
# ===========================================================================
# Raw vibration signal (preamble + units row); mean must aggregate to ~3.2.
vib_lines = ["# Helios Historian Export",
             "# Tag: MCH-301.HEADSTOCK.VIB_RMS",
             "# Units: mm/s",
             "# Sample interval: 15 min",
             "# Period: 2025-05-01..2025-05-02",
             "",
             "timestamp,value"]
_pat = [0.10, -0.10, 0.05, -0.05, 0.15, -0.15, 0.0, 0.0]  # zero-sum -> exact mean 3.2
for i in range(96):
    mins = i * 15
    day = 1 + mins // (60 * 24)
    hh = (mins // 60) % 24
    mm = mins % 60
    val = round(3.2 + _pat[i % len(_pat)], 3)
    vib_lines.append(f"2025-05-{day:02d} {hh:02d}:{mm:02d}:00,{val}")
w("telemetry/MCH-301_vibration_2025-05.csv", content="\n".join(vib_lines) + "\n")
gt("telemetry/MCH-301_vibration_2025-05.csv", "csv", ["TEL-301"], "telemetry",
   ["avg vibration ~= 3.2 mm/s (aggregated from 96 samples)", "units from comment = mm/s"],
   ["comment/preamble lines before header", "units declared in a comment, not a column",
    "raw time-series requiring aggregation to a summary value"],
   "Skip '#' preamble; compute mean -> matches TEL-301 avg_vibration 3.2.")

# Daily OEE components; monthly OEE must aggregate to 82.3% / 76.5%.
oee_rows = ["date,machine,availability,performance,quality"]
_off = [0.02, -0.02, 0.01, -0.01, 0.015, -0.015, 0.005, -0.005]  # sum 0
targets = {"MCH-301": (0.91, 0.95, 0.952), "MCH-302": (0.84, 0.93, 0.98)}
for mid, (a, p, qy) in targets.items():
    for d in range(8):
        oee_rows.append(f"2025-05-{d + 1:02d},{mid},"
                        f"{round(a + _off[d], 4)},{round(p + _off[d], 4)},{round(qy + _off[d], 4)}")
w("telemetry/oee_daily_may2025.csv", content="\n".join(oee_rows) + "\n")
gt("telemetry/oee_daily_may2025.csv", "csv", ["TEL-301", "TEL-302"], "telemetry",
   ["MCH-301 monthly OEE = 0.91*0.95*0.952 = 82.3%",
    "MCH-302 monthly OEE = 0.84*0.93*0.98 = 76.5%"],
   ["per-day component rows requiring monthly aggregation",
    "OEE not stored directly (must compute A*P*Q)", "two machines interleaved"],
   "Aggregate components by machine, then OEE=A*P*Q -> 82.3 / 76.5.")

# ===========================================================================
# 4) Quality — OCR'd scans (.txt) + email (.eml) + spreadsheet (.xlsx)
# ===========================================================================
# Near-duplicate NCR scans with OCR noise; differ in ONE field (12 vs 21 units).
w("quality/NCR-7001_scan.txt", content=
"""HEL1OS PLANT 7  --  QUAL1TY ASSURANCE  --  NON-CONFORMANCE REPORT
========================================================================
NCR No.: NCR-7OO1                     Date Ra1sed: 2O25-02-15
Part No.: PRT-2OO1   (Dr1ve Shaft)
L1ne: PEGASUS  (L1ne A)               Program: BLUEB1RD
------------------------------------------------------------------------
Defect Type: 0uts1de d1ameter 0vers1ze  (above the +/- O.O2 mm tol-
erance band)
Un1ts affected: 12
D1sposit1on: rework    Quarant1ned 1n QA hold area ("dog house")
F1rst-pass y1eld (FPY) for the lot: 94.2 %
Ra1sed by: QA 1nspector (badge redacted)
""")
gt("quality/NCR-7001_scan.txt", "txt (OCR)", ["NCR-7001"], "ncr",
   ["NCR-7001 part=PRT-2001 units_affected=12 disposition=rework FPY=94.2 date=2025-02-15"],
   ["OCR noise (1<->l, O<->0)", "hyphenation line-break ('tol-\\nerance')",
    "form-field layout", "shares all fields with NCR-7004 except units"],
   "Decode OCR; units_affected=12 (conflicts with NCR-7004's 21).")

w("quality/NCR-7004_scan.txt", content=
"""HEL1OS PLANT 7  --  QUAL1TY ASSURANCE  --  NON-CONFORMANCE REPORT
========================================================================
NCR No.: NCR-7OO4                     Date Ra1sed: 2O25-02-15
Part No.: PRT-2OO1   (Dr1ve Shaft)
L1ne: PEGASUS  (L1ne A)               Program: BLUEB1RD
------------------------------------------------------------------------
Defect Type: 0uts1de d1ameter 0vers1ze  (above the +/- O.O2 mm tol-
erance band)
Un1ts affected: 21
D1sposit1on: rework    Quarant1ned 1n QA hold area ("dog house")
F1rst-pass y1eld (FPY) for the lot: 94.2 %
*** STAMP: SUSPECTED DUPL1CATE OF NCR-7OO1 -- DATA QUAL1TY REV1EW ***
""")
gt("quality/NCR-7004_scan.txt", "txt (OCR)", ["NCR-7004"], "ncr",
   ["NCR-7004 units_affected=21; suspected duplicate of NCR-7001"],
   ["OCR noise", "NEAR-DUPLICATE of NCR-7001 differing only in units_affected (21 vs 12)",
    "duplicate stamp in free text"],
   "Dedup logic must flag NCR-7001 vs NCR-7004 conflict, not silently merge.")

# Short-shot NCR as an email thread (headers, quoting, signature, typo).
w("quality/ncr7002_email.eml", content=
"""From: m.adeyemi@helios.example
To: quality@helios.example
Cc: p.nguyen@helios.example
Date: Tue, 25 Mar 2025 14:08:11 -0500
Subject: RE: Short shots on REDFOX housing covers (NCR-7002)
Message-ID: <ncr7002-2025@helios.example>

Confirming the NCR. Raising NCR-7002 against PRT-2002 (housing cover) on the
KRAKEN line. 8 units short-shot, dispositioned SCRAP. FPY on the lot was 96.5%.
Pretty sure its the zone-2 heater band from WO-5002 - temps never reached
setpoint. See troubleshooting guide TG-001 for the short-shot checklist.

-- Marcus

> On Mar 25, 2025, M. Quality wrote:
> Are the short shots from the squeeze on Hydra? How many parts?
> Do we scrap or rework?
""")
gt("quality/ncr7002_email.eml", "eml", ["NCR-7002"], "ncr",
   ["NCR-7002 part=PRT-2002 units=8 disposition=scrap FPY=96.5 line=KRAKEN related=WO-5002"],
   ["email headers + Message-ID", "quoted reply (>) to strip", "signature block",
    "typo ('its')", "jargon ('the squeeze')"],
   "Extract the new content; ignore quoted history; link to WO-5002 / TG-001.")

# Q1 FPY summary as a REAL .xlsx (table + threshold note in cells).
fpy_rows = [
    ["Helios Plant 7 - Q1 2025 First-Pass Yield"],
    [],
    ["Line", "Codename", "Program", "Units Produced", "FPY %"],
    ["Line A", "PEGASUS", "BLUEBIRD", 4200, 94.2],
    ["Line B", "KRAKEN", "REDFOX", 3850, 96.5],
    ["Line C", "TITAN-LINE", "Assembly", 2100, 98.1],
    [],
    ["Release threshold (FPY %)", 95.0],
    ["Note", "Line A below threshold - CAPA required"],
]
wb("quality/Q1_2025_FPY.xlsx", build_xlsx(fpy_rows, sheet_name="Q1 FPY"))
gt("quality/Q1_2025_FPY.xlsx", "xlsx (binary)", ["QR-7003"], "quality_report",
   ["Line A FPY=94.2 units=4200", "Line B FPY=96.5 units=3850", "Line C FPY=98.1 units=2100",
    "threshold=95.0", "Line A below threshold"],
   ["binary OOXML spreadsheet (needs xlsx parser)", "title + blank rows before the table",
    "mixed text/number cells", "threshold + note rows after the table"],
   "Parse xlsx; locate the table; recover the 3x5 FPY grid and 95.0 threshold.")

# ===========================================================================
# 5) Engineering docs — HTML wiki + DOCX (version sprawl across systems)
# ===========================================================================
# SOP-001 Rev 1 (SUPERSEDED) on the old intranet wiki (HTML).
w("sops/SOP-001_rev1.html", content=
"""<!DOCTYPE html>
<html><head><title>SOP-001 Drive Shaft Assembly (Rev 1)</title></head>
<body>
<nav>Home &gt; QMS &gt; SOPs &gt; SOP-001</nav>
<div class="banner status-superseded">STATUS: SUPERSEDED</div>
<h1>SOP-001 Drive Shaft Retaining Nut Torque (Revision 1)</h1>
<table class="meta">
 <tr><th>Document</th><td>SOP-001</td></tr>
 <tr><th>Revision</th><td>1</td></tr>
 <tr><th>Effective</th><td>2022-03-01</td></tr>
 <tr><th>Status</th><td>Superseded by SOP-001 Rev 2</td></tr>
</table>
<p>Apply a retaining-nut torque of <b>85 Nm</b> to the PRT-2001 drive shaft on
the Cyclops lathe (MCH-301). <em>DO NOT use this value for current production -
this revision has been superseded.</em></p>
<footer>(c) Helios Plant 7 - intranet wiki - last edited 2022-03-01</footer>
</body></html>
""")
gt("sops/SOP-001_rev1.html", "html", ["SOP-001-v1"], "sop",
   ["SOP-001 rev=1 torque=85 Nm status=SUPERSEDED effective=2022-03-01 superseded_by=SOP-001-v2"],
   ["HTML tags + nav/footer boilerplate", "metadata in an HTML table",
    "OLD/superseded value (85 Nm) that must NOT win conflict resolution"],
   "Strip HTML; capture status=superseded so 85 Nm loses to Rev 2's 95 Nm.")

# SOP-001 Rev 2 (CURRENT) as a REAL .docx (different system than Rev 1).
wb("sops/SOP-001_Rev2.docx", build_docx([
    "SOP-001 Drive Shaft Retaining Nut Torque (Revision 2)",
    "STATUS: CURRENT / EFFECTIVE",
    "Document: SOP-001    Revision: 2    Effective date: 2024-09-15",
    "This revision supersedes SOP-001 Revision 1 (which specified 85 Nm).",
    "Apply a retaining-nut torque of 95 Nm to the PRT-2001 drive shaft on the "
    "Cyclops lathe (MCH-301).",
    "Per fastener standard TQ-450, hold the torque within +/-5% and re-check after "
    "24 hours of service.",
]))
gt("sops/SOP-001_Rev2.docx", "docx (binary)", ["SOP-001-v2"], "sop",
   ["SOP-001 rev=2 torque=95 Nm status=CURRENT effective=2024-09-15 supersedes=SOP-001-v1"],
   ["binary OOXML word doc (needs docx parser)",
    "CURRENT value (95 Nm) lives in a different format than Rev 1",
    "supersession stated in prose"],
   "Parse docx; this 95 Nm is the conflict-resolution WINNER.")

w("sops/SOP-010_changeover.html", content=
"""<!DOCTYPE html><html><head><title>SOP-010 Mold Changeover</title></head><body>
<nav>Home &gt; QMS &gt; SOPs &gt; SOP-010</nav>
<h1>SOP-010 Injection Molding Mold/Material Changeover (KRAKEN line)</h1>
<p>Hydra injection-molding machine (MCH-302). Operators call this "changing the
squeeze". Steps:</p>
<ol>
 <li>Finish the shot count; quarantine in-process parts.</li>
 <li>Perform LOTO per SOP-020 before opening the platen.</li>
 <li>Purge the barrel of PA66 resin; verify melt temperature has dropped.</li>
 <li>Remove the existing mold with the overhead hoist.</li>
 <li>Install and clamp the incoming mold; reconnect water lines.</li>
 <li>Re-establish parameters; run a first-off (first-article) inspection.</li>
</ol>
<footer>(c) Helios Plant 7 wiki</footer></body></html>
""")
gt("sops/SOP-010_changeover.html", "html", ["SOP-010"], "sop",
   ["SOP-010 6-step changeover; machine=MCH-302; references SOP-020"],
   ["HTML <ol> list -> ordered steps", "nav/footer boilerplate", "jargon ('the squeeze')"],
   "Preserve step ORDER when converting <ol> to text.")

w("sops/SOP-020_loto.html", content=
"""<!DOCTYPE html><html><head><title>SOP-020 LOTO</title></head><body>
<nav>Home &gt; EHS &gt; SOPs &gt; SOP-020</nav>
<h1>SOP-020 Lockout/Tagout (LOTO) Energy Control</h1>
<p>LOTO = "Lockout/Tagout". Applies to Cyclops (MCH-301), Hydra (MCH-302),
Goliath (MCH-303) and Atlas (MCH-304). Implements synthetic standard SF-200.</p>
<ol>
 <li>Notify operators; shut down using normal stops.</li>
 <li>Isolate every energy source: electrical, pneumatic, hydraulic.</li>
 <li>Apply personal locks and tags at each isolation point.</li>
 <li>Release or block stored energy (springs, accumulators, hydraulic pressure).</li>
 <li>Verify zero energy by attempting a restart before any service work.</li>
</ol>
<footer>(c) Helios Plant 7 wiki</footer></body></html>
""")
gt("sops/SOP-020_loto.html", "html", ["SOP-020"], "sop",
   ["SOP-020 5-step LOTO; applies to MCH-301..304; implements SF-200; LOTO=Lockout/Tagout"],
   ["HTML ordered list", "acronym expansion in prose", "entity list (4 machines)"],
   "Acronym + 5 ordered steps; map applies_to machines.")

# Troubleshooting wiki: TWO guides in ONE file (doc-splitting test).
w("kb/troubleshooting.html", content=
"""<!DOCTYPE html><html><head><title>Troubleshooting KB</title></head><body>
<h1>Troubleshooting Knowledge Base</h1>

<section id="TG-001">
<h2>TG-001 - Short Shot ("the squeeze didn't fill")</h2>
<p>Hydra injection molder (MCH-302). A short shot is an incompletely filled part.</p>
<ul>
 <li>Melt temperature too low: check barrel zone setpoints / heater bands
     (a failed band caused NCR-7002 via WO-5002).</li>
 <li>Injection or hold pressure too low: raise in small steps.</li>
 <li>Blocked gate or vent: inspect and clean the tool.</li>
 <li>Insufficient shot size: increase shot volume; check the check-ring.</li>
</ul>
</section>

<section id="TG-002">
<h2>TG-002 - Lathe Chatter / Vibration</h2>
<p>Cyclops lathe (MCH-301). Watch the PRT-2005 sensor reading.</p>
<ul>
 <li>Worn spindle bearing (PRT-2003): root cause behind WO-5001.</li>
 <li>Excessive spindle speed: reduce rpm.</li>
 <li>Long tool overhang / dull insert: shorten overhang, index tool.</li>
 <li>Loose workholding: re-seat and re-clamp.</li>
</ul>
<p>If average vibration exceeds the 4.5 mm/s alarm limit, stop and investigate.</p>
</section>
</body></html>
""")
gt("kb/troubleshooting.html", "html", ["TG-001", "TG-002"], "troubleshooting",
   ["TG-001 short-shot causes (machine MCH-302)", "TG-002 chatter causes (machine MCH-301); alarm 4.5 mm/s"],
   ["TWO documents in ONE file (must split on <section>/<h2>)",
    "HTML unordered lists", "cross-refs to NCR/WO/parts"],
   "Split into TG-001 and TG-002 as separate canonical docs.")

# ===========================================================================
# 6) Standards — REAL PDF + extracted-text (.txt) with page artifacts
# ===========================================================================
wb("standards/HX-900_excerpt.pdf", build_pdf([
    [
        "HELIOS COMPLIANCE LIBRARY                                  Page 1 of 1",
        "HX-900 Quality Management Framework (SYNTHETIC - paraphrased)",
        "",
        "This document is fully synthetic and paraphrased; it does not reproduce",
        "any real standard's wording.",
        "",
        "Clause 7.5 - Document control. Every controlled document shall carry a",
        "revision identifier and an effective date. Superseded revisions shall be",
        "withdrawn from points of use.",
        "",
        "Clause 8.2 - Nonconforming output. Production lots whose first-pass yield",
        "falls below the documented release threshold shall be quarantined in a",
        "controlled hold area (at Plant 7, the 'dog house') pending disposition.",
        "",
        "CONFIDENTIAL - INTERNAL USE ONLY                          HX-900 / r3",
    ]
]))
gt("standards/HX-900_excerpt.pdf", "pdf (binary)", ["STD-IS-900"], "standard",
   ["HX-900 clause 8.2: below-threshold lots quarantined in 'dog house'",
    "clause 7.5: revision id + effective date; withdraw superseded"],
   ["binary PDF (needs PDF text extraction)", "running header + footer",
    "page-number line ('Page 1 of 1')", "synthetic standard"],
   "Extract PDF text; strip header/footer/page-number boilerplate.")

w("standards/TQ-450.txt", content=
"""TQ-450 Fastener Torque Practice (SYNTHETIC - paraphrased)
                                                                    [p. 1]
TQ-450 recommends that threaded fasteners be tightened to the torque specified
by the controlling work instruction, held within a tolerance band of +/-5% of
the nominal value, and re-checked after 24 hours of service to detect
relaxation.
- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - page 1 - -
Lubricated and dry threads are treated as different conditions and must not
share a torque value.
                                                                    [p. 2]
""")
gt("standards/TQ-450.txt", "txt (extracted)", ["STD-TQ-450"], "standard",
   ["TQ-450 tolerance=+/-5%", "re-check after 24h", "lubricated vs dry are different"],
   ["interleaved page-number artifacts ('[p. 1]', 'page 1')",
    "dashed page-break separators", "synthetic standard"],
   "Strip page artifacts left over from PDF text extraction.")

w("standards/SF-200.txt", content=
"""SF-200 Hazardous-Energy Control (SYNTHETIC - paraphrased)
SF-200 requires that, before any servicing where unexpected start-up could cause
harm, all energy sources be isolated, locked, and tagged; that stored energy be
released or restrained; and that a zero-energy verification be performed before
work. SF-200 is implemented at Plant 7 through SOP-020.
""")
gt("standards/SF-200.txt", "txt", ["STD-SF-200"], "standard",
   ["SF-200 implemented by SOP-020", "isolate/lock/tag, release stored energy, verify zero"],
   ["synthetic standard", "cross-ref to SOP-020"],
   "Link SF-200 -> SOP-020.")

# ===========================================================================
# 7) Materials — datasheets; one file holds TWO datasheets (split test)
# ===========================================================================
# 4140: ASCII table; intentionally NO melting point (enables unanswerable Q038).
w("materials/4140_steel_datasheet.txt", content=
"""MATERIAL DATASHEET
4140 Alloy Steel (Chromium-Molybdenum), quenched & tempered
-----------------------------------------------------------
| Property                 | Value      |
|--------------------------|------------|
| Ultimate tensile (UTS)   | 655 MPa    |
| Yield strength           | 415 MPa    |
| Density                  | 7.85 g/cm3 |
| Elongation               | 25.7 %     |
| Hardness (Brinell)       | 197 HB     |
-----------------------------------------------------------
Used for: PRT-2001 drive shaft.
Footnote: Mechanical properties only. Thermal properties (incl. melting point)
are NOT listed on this sheet.
""")
gt("materials/4140_steel_datasheet.txt", "txt", ["MAT-4140"], "material_datasheet",
   ["4140 UTS=655 MPa yield=415 MPa density=7.85 g/cm3 (=7850 kg/m3) hardness=197HB",
    "NO melting point present (by design)"],
   ["ASCII pipe table", "units inside cells", "deliberate ABSENCE (no melting point)"],
   "Parse ASCII table; absence of melting point supports an unanswerable question.")

# PA66 + 6061 in ONE file (must split into MAT-PA66 and MAT-AL6061).
w("materials/PA66_AL6061_datasheets.txt", content=
"""=== DATASHEET 1 ===========================================
PA66 (Nylon 6/6), unfilled injection grade
Density: 1.14 g/cm3   Tensile strength: 80 MPa
Melt processing temperature: 255 °C   Mold shrinkage: 1.5 %
Used for: PRT-2002 housing cover (REDFOX program).

=== DATASHEET 2 ===========================================
6061-T6 Aluminum alloy
Ultimate tensile: 310 MPa   Yield: 276 MPa
Density: 2.70 g/cm3   Elongation: 12 %   Hardness: 95 HB
Used for: PRT-2007 mounting bracket.
""")
gt("materials/PA66_AL6061_datasheets.txt", "txt", ["MAT-PA66", "MAT-AL6061"],
   "material_datasheet",
   ["PA66 density=1.14 tensile=80 melt=255C", "6061 UTS=310 yield=276 density=2.70 hardness=95HB"],
   ["TWO datasheets in ONE file (split on '=== DATASHEET ===')",
    "degree sign (UTF-8 multibyte) in '255 C'"],
   "Split into MAT-PA66 + MAT-AL6061; handle the degree-sign byte.")

# ===========================================================================
# 8) Supplier email (.eml) in cp1252 — encoding-detection challenge
# ===========================================================================
w("email/vector_bearings_quote.eml", encoding="cp1252", content=
"""From: export@vectorbearings.example
To: procurement@helios.example
Date: Fri, 10 Jan 2025 09:30:00 +0100
Subject: Quotation – PRT-2003 precision bearing

Dear Procurement Team,

Please find our quotation for the PRT-2003 precision bearing:
 • Unit price: €– quoted in USD at $42.50/unit
 • Minimum order quantity (MOQ): 100 units
 • Lead time: 45 days ex-works Stuttgart
 • Operating temperature rating: up to 120°C

We look forward to your order “as discussed”.

Mit freundlichen Grüßen,
Vector Bearings GmbH
""")
gt("email/vector_bearings_quote.eml", "eml (cp1252)", ["SUP-103", "PO-9001"],
   "supplier",
   ["corroborates SUP-103 lead=45 days; PO-9001 unit_price=$42.50 MOQ=100"],
   ["NON-UTF-8 encoding (cp1252)", "smart quotes / en-dash / bullet (•) / euro / degree",
    "German umlaut/eszett in signature"],
   "Detect cp1252 (decoding as utf-8 will corrupt); corroborates SUP-103 & PO-9001.")

# ===========================================================================
# 9) Safety incidents (.txt forms)
# ===========================================================================
w("safety/INC-8001_report.txt", content=
"""HELIOS PLANT 7 - EHS INCIDENT REPORT
Incident ID: INC-8001          Date: 2025-03-20
Location: KRAKEN line, Hydra injection molder (MCH-302)
Type: NEAR-MISS (no injury)
Description: During a mold changeover a technician began opening the platen
before stored hydraulic energy had been released.
Root cause: LOTO step 4 (release of stored energy) per SOP-020 was skipped.
Corrective action: re-train crew on SOP-020; add a hydraulic bleed-down check
to the SOP-010 changeover checklist.
""")
gt("safety/INC-8001_report.txt", "txt", ["INC-8001"], "incident",
   ["INC-8001 2025-03-20 MCH-302 near-miss; cause=skipped LOTO step 4; refs SOP-020/SOP-010"],
   ["form layout", "cross-refs to SOP-020 / SOP-010"], "")

w("safety/INC-8002_report.txt", content=
"""HELIOS PLANT 7 - EHS INCIDENT REPORT
Incident ID: INC-8002          Date: 2025-04-12
Location: Raw-material warehouse
Type: Minor property damage (no injury)
Description: A forklift contacted a pallet rack while reversing, dislodging
packaging. No parts damaged.
Root cause: blind corner with no convex mirror.
Corrective action: install mirror; repaint floor lanes.
""")
gt("safety/INC-8002_report.txt", "txt", ["INC-8002"], "incident",
   ["INC-8002 2025-04-12 warehouse forklift; minor; no injury"],
   ["form layout"], "")

# ===========================================================================
# 10) MES API dump (.json) — the machine/codename/line/program graph
# ===========================================================================
mes = {
    "plant": "Helios Plant 7",
    "machines": [
        {"id": "MCH-301", "codename": "Cyclops", "type": "CNC lathe", "line": "Line A",
         "line_codename": "PEGASUS", "program": "BLUEBIRD"},
        {"id": "MCH-302", "codename": "Hydra", "type": "injection molder", "line": "Line B",
         "line_codename": "KRAKEN", "program": "REDFOX"},
        {"id": "MCH-303", "codename": "Goliath", "type": "CNC mill", "line": "Line A",
         "line_codename": "PEGASUS", "program": "BLUEBIRD"},
        {"id": "MCH-304", "codename": "Atlas", "type": "assembly robot", "line": "Line C",
         "line_codename": "TITAN-LINE", "program": None},
    ],
}
wb("mes/machines.json", json.dumps(mes, indent=2).encode("utf-8"))
gt("mes/machines.json", "json", [], "entity_graph",
   ["machine<->codename<->line<->program mappings (e.g., Cyclops=MCH-301=PEGASUS=BLUEBIRD)"],
   ["JSON API payload", "null fields", "this is the GRAPH GLUE for codename resolution"],
   "Not a corpus doc itself; provides the entity graph that resolves codenames/jargon.")

# ===========================================================================
# 11) Off-topic noise (.txt) — precision distractors
# ===========================================================================
w("misc/cafeteria_menu.txt", content=
"""PLANT 7 CAFETERIA - WEEKLY LUNCH MENU
Mon: chili & cornbread   Tue: taco bar   Wed: grilled chicken & rice
Thu: pasta primavera     Fri: fish & chips
Salad bar and a vegetarian option daily. Coffee is free in the break room.
""")
gt("misc/cafeteria_menu.txt", "txt", ["NOISE-001"], "noise",
   ["off-topic facilities content"], ["distractor / noise doc"],
   "Should be ingested but rank as off-topic for precision testing.")

w("misc/parking_memo.txt", content=
"""FACILITIES MEMO - NORTH PARKING LOT REPAVING
The north employee lot will be repaved this weekend. Please use the south or
visitor lots. Normal parking resumes Monday.
""")
gt("misc/parking_memo.txt", "txt", ["NOISE-002"], "noise",
   ["off-topic facilities content"], ["distractor / noise doc"], "")

w("misc/holiday_schedule_2025.txt", content=
"""2025 COMPANY HOLIDAY SCHEDULE - PLANT 7
Observed: New Year's Day, Memorial Day, Independence Day, Labor Day,
Thanksgiving (2 days), Christmas Day. Skeleton maintenance crew on holidays.
File PTO via the HR portal.
""")
gt("misc/holiday_schedule_2025.txt", "txt", ["NOISE-003"], "noise",
   ["off-topic HR content"], ["distractor / noise doc"], "")


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------
def main():
    with open(RAW / "INGESTION_GROUND_TRUTH.jsonl", "w", encoding="utf-8") as f:
        for row in GROUND_TRUTH:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    n_files = sum(1 for _ in RAW.rglob("*") if _.is_file())
    print(f"Wrote raw/ source tree: {n_files} files across "
          f"{len(set(p.parent for p in RAW.rglob('*') if p.is_file()))} folders")
    print(f"Wrote raw/INGESTION_GROUND_TRUTH.jsonl: {len(GROUND_TRUTH)} mapping entries")
    fmts = {}
    for g in GROUND_TRUTH:
        fmts[g["format"]] = fmts.get(g["format"], 0) + 1
    print("Source formats:")
    for k, v in sorted(fmts.items()):
        print(f"  {k:18s} {v}")


if __name__ == "__main__":
    main()
