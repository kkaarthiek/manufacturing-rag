#!/usr/bin/env python3
"""
build_dataset.py — Generates the RAG golden dataset for the "Helios Plant 7"
synthetic manufacturing world.

Outputs (Python 3 standard library only):
  - corpus.jsonl     : ~42 internally-consistent knowledge-base documents
  - questions.jsonl   : ~72 labelled evaluation questions
  - questions.csv     : flat, human-browsable view of the question bank

The corpus is a single coherent "factory world" so that multi-hop questions
actually resolve. All standards/compliance text is fully synthetic and
paraphrased — no real ISO/ASTM/ANSI wording is reproduced.

Entity graph (codenames / shop-floor jargon in quotes):
  Suppliers  SUP-101..105  --supply-->  Parts PRT-2001..2007
  Parts      --used on-->   Machines MCH-301 "Cyclops", MCH-302 "Hydra",
                                      MCH-303 "Goliath", MCH-304 "Atlas"
  Machines   --run on-->    Lines:  Line A "PEGASUS"  -> program "BLUEBIRD"
                                    Line B "KRAKEN"   -> program "REDFOX"
                                    Line C "TITAN-LINE" (final assembly)
  Jargon: "the squeeze" = injection molding, "the dog house" = QA hold/quarantine,
          "first-off" = first-article inspection, "the lathe cell" = MCH-301 area.
  Acronyms: OEE, MTBF, FPY, NCR, LOTO, MOQ.
"""

import csv
import json
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# PART 1 — KNOWLEDGE BASE CORPUS
# ---------------------------------------------------------------------------
# Each entry: doc_id, doc_type, title, text, metadata
CORPUS = []


def doc(doc_id, doc_type, title, text, metadata):
    CORPUS.append(
        {
            "doc_id": doc_id,
            "doc_type": doc_type,
            "title": title,
            "text": text.strip(),
            "metadata": metadata,
        }
    )


# --- 1. Supplier / firmographic records (5) --------------------------------
doc(
    "SUP-101", "supplier", "Supplier Profile — Titan Alloys Inc.",
    """
Titan Alloys Inc. (SUP-101) is a metals stockist based in Cleveland, Ohio, USA.
The company supplies 4140 alloy steel bar stock and 6061 aluminum billet to
Helios Plant 7. Standard quoted lead time is 21 days from purchase order to
dock receipt. Primary contact email is orders@titanalloys.example. Titan Alloys
holds Helios approved-supplier status for ferrous and non-ferrous raw material.
Note: "Titan Alloys" the supplier is unrelated to the "TITAN-LINE" production
line (Line C) on the shop floor; they merely share the word.
""",
    {"supplier_id": "SUP-101", "location": "Cleveland, OH, USA",
     "products": ["4140 steel bar", "6061 aluminum billet"], "lead_time_days": 21,
     "supplies_parts": ["PRT-2001", "PRT-2007"], "source": "ERP supplier master",
     "approved": True},
)
doc(
    "SUP-102", "supplier", "Supplier Profile — Pacific Polymers Ltd.",
    """
Pacific Polymers Ltd. (SUP-102) is a polymer compounder in Portland, Oregon, USA.
It supplies PA66 (nylon 6/6) injection-molding pellets and PTFE seal stock to
Helios Plant 7. Standard quoted lead time is 35 days. Contact:
sales@pacificpolymers.example. Pacific Polymers is the sole approved source for
the PA66 resin used in the "REDFOX" housing program on the KRAKEN line.
""",
    {"supplier_id": "SUP-102", "location": "Portland, OR, USA",
     "products": ["PA66 pellets", "PTFE seal stock"], "lead_time_days": 35,
     "supplies_parts": ["PRT-2002", "PRT-2006"], "source": "ERP supplier master",
     "approved": True},
)
doc(
    "SUP-103", "supplier", "Supplier Profile — Vector Bearings GmbH",
    """
Vector Bearings GmbH (SUP-103) is a precision-bearing manufacturer headquartered
in Stuttgart, Germany. It supplies the PRT-2003 precision bearing used on the
Cyclops lathe (MCH-301) and the Goliath mill (MCH-303). Standard quoted lead time
is 45 days, the longest of any approved Helios supplier. Contact:
export@vectorbearings.example.
""",
    {"supplier_id": "SUP-103", "location": "Stuttgart, Germany",
     "products": ["precision bearings"], "lead_time_days": 45,
     "supplies_parts": ["PRT-2003"], "source": "ERP supplier master",
     "approved": True},
)
doc(
    "SUP-104", "supplier", "Supplier Profile — Crescent Fasteners Co.",
    """
Crescent Fasteners Co. (SUP-104) is a fastener distributor in Monterrey, Mexico.
It supplies the PRT-2004 grade-8.8 hex bolt and assorted fasteners to Helios
Plant 7. Standard quoted lead time is 14 days, the shortest of any approved
supplier. Contact: ventas@crescentfasteners.example.
""",
    {"supplier_id": "SUP-104", "location": "Monterrey, Mexico",
     "products": ["hex bolts", "fasteners"], "lead_time_days": 14,
     "supplies_parts": ["PRT-2004"], "source": "ERP supplier master",
     "approved": True},
)
doc(
    "SUP-105", "supplier", "Supplier Profile — Lumen Sensors Corp.",
    """
Lumen Sensors Corp. (SUP-105) is a condition-monitoring vendor in San Jose,
California, USA. It supplies the PRT-2005 vibration sensor module and
thermocouples to Helios Plant 7. Standard quoted lead time is 28 days. Contact:
support@lumensensors.example.
""",
    {"supplier_id": "SUP-105", "location": "San Jose, CA, USA",
     "products": ["vibration sensors", "thermocouples"], "lead_time_days": 28,
     "supplies_parts": ["PRT-2005"], "source": "ERP supplier master",
     "approved": True},
)

# --- 2. Part / product specification sheets (7) ----------------------------
doc(
    "SPEC-2001", "part_spec", "Part Specification — PRT-2001 Drive Shaft",
    """
PRT-2001 Drive Shaft. Material: 4140 alloy steel (see MAT-4140). Overall length:
250 mm. Outside diameter: 30 mm. Diameter tolerance: +/-0.02 mm. Surface finish:
0.8 um Ra. Raw bar stock is supplied by Titan Alloys (SUP-101). The finished
drive shaft is machined on the Cyclops CNC lathe (MCH-301) on the PEGASUS line
and is a component of the BLUEBIRD gearbox program. Retaining-nut torque is
governed by the current revision of SOP-001.
""",
    {"part_id": "PRT-2001", "material": "4140 steel", "length_mm": 250,
     "diameter_mm": 30, "tolerance_mm": 0.02, "supplier_id": "SUP-101",
     "used_on": ["MCH-301"], "program": "BLUEBIRD", "source": "PLM"},
)
doc(
    "SPEC-2002", "part_spec", "Part Specification — PRT-2002 Housing Cover",
    """
PRT-2002 Housing Cover. Material: PA66 (nylon 6/6), supplied as pellets by
Pacific Polymers (SUP-102). Nominal wall thickness: 3.2 mm. Mass: 142 g. The
cover is molded on the Hydra injection-molding machine (MCH-302) on the KRAKEN
line as part of the REDFOX housing program. Operators refer to the molding step
as "the squeeze".
""",
    {"part_id": "PRT-2002", "material": "PA66", "wall_thickness_mm": 3.2,
     "mass_g": 142, "supplier_id": "SUP-102", "used_on": ["MCH-302"],
     "program": "REDFOX", "source": "PLM"},
)
doc(
    "SPEC-2003", "part_spec", "Part Specification — PRT-2003 Precision Bearing",
    """
PRT-2003 Precision Bearing. Supplied by Vector Bearings GmbH (SUP-103). Bore
diameter: 30 mm. Outside diameter: 62 mm. Width: 16 mm. Dynamic load rating:
12.5 kN. Rated speed: 12000 rpm. The bearing is fitted to the Cyclops lathe
(MCH-301) spindle and to the Goliath mill (MCH-303). It is the part replaced in
work order WO-5001.
""",
    {"part_id": "PRT-2003", "bore_mm": 30, "od_mm": 62, "width_mm": 16,
     "dynamic_load_kn": 12.5, "rated_speed_rpm": 12000, "supplier_id": "SUP-103",
     "used_on": ["MCH-301", "MCH-303"], "source": "PLM"},
)
doc(
    "SPEC-2004", "part_spec", "Part Specification — PRT-2004 Hex Bolt M10",
    """
PRT-2004 Hex Bolt, M10 x 40 mm, property class 8.8, zinc plated. Supplied by
Crescent Fasteners (SUP-104). Used as a general retaining fastener across
multiple assemblies including the BLUEBIRD gearbox. Recommended torque practice
is described in synthetic fastener standard TQ-450.
""",
    {"part_id": "PRT-2004", "thread": "M10", "length_mm": 40,
     "property_class": "8.8", "supplier_id": "SUP-104", "source": "PLM"},
)
doc(
    "SPEC-2005", "part_spec", "Part Specification — PRT-2005 Vibration Sensor Module",
    """
PRT-2005 Vibration Sensor Module. Supplied by Lumen Sensors (SUP-105).
Measurement range: 0 to 50 mm/s RMS velocity. Output: 4-20 mA. The sensor is
mounted on the Cyclops lathe (MCH-301) headstock and feeds the telemetry summary
in TEL-301. It was recalibrated under work order WO-5004.
""",
    {"part_id": "PRT-2005", "range_mm_s": 50, "output": "4-20 mA",
     "supplier_id": "SUP-105", "used_on": ["MCH-301"], "source": "PLM"},
)
doc(
    "SPEC-2006", "part_spec", "Part Specification — PRT-2006 PTFE Gasket",
    """
PRT-2006 PTFE Gasket. Material: virgin PTFE seal stock from Pacific Polymers
(SUP-102). Outside diameter: 60 mm. Inside diameter: 48 mm. Thickness: 2 mm.
Used to seal the REDFOX housing assembly. Note: PRT-2006 is PTFE, not PA66 — do
not confuse with the PA66 housing cover PRT-2002.
""",
    {"part_id": "PRT-2006", "material": "PTFE", "od_mm": 60, "id_mm": 48,
     "thickness_mm": 2, "supplier_id": "SUP-102", "source": "PLM"},
)
doc(
    "SPEC-2007", "part_spec", "Part Specification — PRT-2007 Aluminum Bracket",
    """
PRT-2007 Aluminum Mounting Bracket. Material: 6061-T6 aluminum (see MAT-AL6061),
billet supplied by Titan Alloys (SUP-101). Mass: 85 g. Used on the TITAN-LINE
(Line C) final-assembly station served by the Atlas robot (MCH-304).
""",
    {"part_id": "PRT-2007", "material": "6061 aluminum", "mass_g": 85,
     "supplier_id": "SUP-101", "used_on": ["MCH-304"], "line": "TITAN-LINE",
     "source": "PLM"},
)

# --- 3. SOPs (4) including a versioned conflict ----------------------------
doc(
    "SOP-001-v1", "sop", "SOP-001 Drive Shaft Assembly (Rev 1 — SUPERSEDED)",
    """
SOP-001 Revision 1 — Drive Shaft Retaining Nut Torque. STATUS: SUPERSEDED.
This revision specifies a retaining-nut torque of 85 Nm for the PRT-2001 drive
shaft on the Cyclops lathe (MCH-301). Effective 2022-03-01. THIS REVISION HAS
BEEN SUPERSEDED BY SOP-001 Revision 2 — do not use the 85 Nm value for current
production.
""",
    {"sop_id": "SOP-001", "version": 1, "status": "superseded",
     "torque_nm": 85, "part_id": "PRT-2001", "machine_id": "MCH-301",
     "effective_date": "2022-03-01", "superseded_by": "SOP-001-v2",
     "source": "QMS document control"},
)
doc(
    "SOP-001-v2", "sop", "SOP-001 Drive Shaft Assembly (Rev 2 — CURRENT)",
    """
SOP-001 Revision 2 — Drive Shaft Retaining Nut Torque. STATUS: CURRENT /
EFFECTIVE. This revision raises the retaining-nut torque for the PRT-2001 drive
shaft on the Cyclops lathe (MCH-301) to 95 Nm. Effective 2024-09-15. This
revision supersedes SOP-001 Revision 1 (which specified 85 Nm). Per fastener
standard TQ-450, apply the torque within +/-5% and re-check after 24 hours.
""",
    {"sop_id": "SOP-001", "version": 2, "status": "current",
     "torque_nm": 95, "part_id": "PRT-2001", "machine_id": "MCH-301",
     "effective_date": "2024-09-15", "supersedes": "SOP-001-v1",
     "source": "QMS document control"},
)
doc(
    "SOP-010", "sop", "SOP-010 Injection Molding Changeover (KRAKEN line)",
    """
SOP-010 — Mold and Material Changeover on the Hydra injection-molding machine
(MCH-302), KRAKEN line. Operators call this "changing the squeeze".
Steps:
  1. Complete the running shot count and quarantine any in-process parts.
  2. Perform LOTO on MCH-302 per SOP-020 before opening the platen.
  3. Purge the barrel of PA66 resin and verify melt temperature has dropped.
  4. Remove the existing mold using the overhead hoist.
  5. Install and clamp the incoming mold; reconnect water lines.
  6. Re-establish process parameters and run a first-off (first-article)
     inspection before releasing to production.
""",
    {"sop_id": "SOP-010", "machine_id": "MCH-302", "line": "KRAKEN",
     "related_sop": "SOP-020", "source": "QMS document control"},
)
doc(
    "SOP-020", "sop", "SOP-020 Lockout/Tagout (LOTO) Energy Control",
    """
SOP-020 — Lockout/Tagout (LOTO) for hazardous-energy control. LOTO stands for
"Lockout/Tagout". This SOP applies to all powered machines at Plant 7 including
Cyclops (MCH-301), Hydra (MCH-302), Goliath (MCH-303) and Atlas (MCH-304).
Steps:
  1. Notify affected operators and shut the machine down using normal stops.
  2. Isolate every energy source: electrical, pneumatic, and hydraulic.
  3. Apply personal locks and tags to each isolation point.
  4. Release or block stored energy (springs, accumulators, hydraulic pressure).
  5. Verify zero energy by attempting a restart before any service work begins.
This SOP implements the synthetic safety standard SF-200.
""",
    {"sop_id": "SOP-020", "applies_to": ["MCH-301", "MCH-302", "MCH-303", "MCH-304"],
     "implements_standard": "SF-200", "source": "QMS document control"},
)

# --- 4. Maintenance work orders / logs (4) ---------------------------------
doc(
    "WO-5001", "work_order", "Work Order WO-5001 — Cyclops Bearing Replacement",
    """
Work Order WO-5001. Asset: Cyclops CNC lathe (MCH-301), PEGASUS line. Date:
2025-02-10. Task: replace failed spindle bearing PRT-2003 supplied by Vector
Bearings (SUP-103). Symptom: rising vibration flagged by the headstock sensor.
Downtime: 4.5 hours. Reported mean time between failures (MTBF) for the spindle
bearing on this asset: 1820 hours. Technician: J. Okafor.
""",
    {"wo_id": "WO-5001", "machine_id": "MCH-301", "line": "PEGASUS",
     "part_id": "PRT-2003", "supplier_id": "SUP-103", "date": "2025-02-10",
     "downtime_hours": 4.5, "mtbf_hours": 1820, "source": "CMMS"},
)
doc(
    "WO-5002", "work_order", "Work Order WO-5002 — Hydra Heater Band Failure",
    """
Work Order WO-5002. Asset: Hydra injection-molding machine (MCH-302), KRAKEN
line. Date: 2025-03-22. Task: replace failed barrel heater band. Symptom: zone-2
temperature could not reach setpoint, causing short-shot risk. Downtime: 6.0
hours. Technician: M. Adeyemi.
""",
    {"wo_id": "WO-5002", "machine_id": "MCH-302", "line": "KRAKEN",
     "date": "2025-03-22", "downtime_hours": 6.0, "source": "CMMS"},
)
doc(
    "WO-5003", "work_order", "Work Order WO-5003 — Goliath Spindle Service",
    """
Work Order WO-5003. Asset: Goliath CNC mill (MCH-303), PEGASUS line. Date:
2025-04-05. Task: scheduled spindle bearing inspection and re-grease. Downtime:
3.0 hours. No parts replaced. Technician: J. Okafor.
""",
    {"wo_id": "WO-5003", "machine_id": "MCH-303", "line": "PEGASUS",
     "date": "2025-04-05", "downtime_hours": 3.0, "source": "CMMS"},
)
doc(
    "WO-5004", "work_order", "Work Order WO-5004 — Cyclops Sensor Recalibration",
    """
Work Order WO-5004. Asset: Cyclops CNC lathe (MCH-301), PEGASUS line. Date:
2025-05-01. Task: recalibrate the PRT-2005 vibration sensor module (Lumen
Sensors, SUP-105) following the February bearing replacement. Downtime: 1.5
hours. Technician: P. Nguyen.
""",
    {"wo_id": "WO-5004", "machine_id": "MCH-301", "line": "PEGASUS",
     "part_id": "PRT-2005", "supplier_id": "SUP-105", "date": "2025-05-01",
     "downtime_hours": 1.5, "source": "CMMS"},
)

# --- 5. Quality / non-conformance reports (4, incl. near-duplicate + table) -
doc(
    "NCR-7001", "ncr", "Non-Conformance Report NCR-7001 — Drive Shaft Oversize",
    """
Non-Conformance Report NCR-7001. Part: PRT-2001 drive shaft. Line: PEGASUS
(Line A), program BLUEBIRD. Date raised: 2025-02-15. Defect type: outside
diameter oversize (above the +/-0.02 mm tolerance). Units affected: 12.
Disposition: rework. Lot quarantined in the QA hold area (the "dog house").
First-pass yield (FPY) for the affected lot: 94.2%.
""",
    {"ncr_id": "NCR-7001", "part_id": "PRT-2001", "line": "PEGASUS",
     "program": "BLUEBIRD", "date": "2025-02-15", "defect": "OD oversize",
     "units_affected": 12, "disposition": "rework", "fpy_pct": 94.2,
     "source": "QMS"},
)
doc(
    "NCR-7004", "ncr", "Non-Conformance Report NCR-7004 — Drive Shaft Oversize (re-entry)",
    """
Non-Conformance Report NCR-7004. Part: PRT-2001 drive shaft. Line: PEGASUS
(Line A), program BLUEBIRD. Date raised: 2025-02-15. Defect type: outside
diameter oversize (above the +/-0.02 mm tolerance). Units affected: 21.
Disposition: rework. Lot quarantined in the QA hold area (the "dog house").
First-pass yield (FPY) for the affected lot: 94.2%.
NOTE: This record is a suspected duplicate re-entry of NCR-7001; it is identical
except that the "units affected" field reads 21 rather than 12. The data-quality
team has flagged the discrepancy as unresolved.
""",
    {"ncr_id": "NCR-7004", "part_id": "PRT-2001", "line": "PEGASUS",
     "program": "BLUEBIRD", "date": "2025-02-15", "defect": "OD oversize",
     "units_affected": 21, "disposition": "rework", "fpy_pct": 94.2,
     "suspected_duplicate_of": "NCR-7001", "data_quality_flag": "units_affected mismatch",
     "source": "QMS"},
)
doc(
    "NCR-7002", "ncr", "Non-Conformance Report NCR-7002 — Housing Cover Short Shot",
    """
Non-Conformance Report NCR-7002. Part: PRT-2002 housing cover. Line: KRAKEN
(Line B), program REDFOX. Date raised: 2025-03-25. Defect type: short shot
(incomplete fill). Units affected: 8. Probable cause linked to the zone-2 heater
issue (see WO-5002). Disposition: scrap. FPY for the affected lot: 96.5%.
Refer to troubleshooting guide TG-001 for short-shot diagnosis.
""",
    {"ncr_id": "NCR-7002", "part_id": "PRT-2002", "line": "KRAKEN",
     "program": "REDFOX", "date": "2025-03-25", "defect": "short shot",
     "units_affected": 8, "disposition": "scrap", "fpy_pct": 96.5,
     "related_wo": "WO-5002", "source": "QMS"},
)
doc(
    "QR-7003", "quality_report", "Quality Summary QR-7003 — Q1 2025 First-Pass Yield",
    """
Quality Summary QR-7003 — First-Pass Yield (FPY) by line, Q1 2025 (Jan-Mar).
The QMS release threshold is 95.0% FPY; lots below threshold route to the QA hold
area for disposition.

| Line   | Codename    | Program  | Units Produced | FPY (%) |
|--------|-------------|----------|----------------|---------|
| Line A | PEGASUS     | BLUEBIRD | 4200           | 94.2    |
| Line B | KRAKEN      | REDFOX   | 3850           | 96.5    |
| Line C | TITAN-LINE  | (assembly)| 2100          | 98.1    |

Observation: Line A (PEGASUS) finished Q1 below the 95.0% release threshold and
is the only line requiring a corrective-action plan this quarter.
""",
    {"report_id": "QR-7003", "period": "Q1 2025", "threshold_fpy_pct": 95.0,
     "lines": ["PEGASUS", "KRAKEN", "TITAN-LINE"], "source": "QMS",
     "contains_table": True},
)

# --- 6. Standards & compliance excerpts (3) — FULLY SYNTHETIC --------------
doc(
    "STD-IS-900", "standard", "Synthetic Quality Management Framework HX-900",
    """
HX-900 Quality Management Framework (synthetic, paraphrased — not a real
standard). HX-900 asks an organization to define documented procedures, keep
records of conformance, and operate a closed-loop corrective-action process.
Clause 8.2 (paraphrased): production lots whose first-pass yield falls below the
documented release threshold shall be quarantined in a controlled hold area (at
Plant 7, the "dog house") pending disposition. Clause 7.5 (paraphrased): every
controlled document shall carry a revision identifier and an effective date, and
superseded revisions shall be withdrawn from points of use.
""",
    {"standard_id": "HX-900", "topic": "quality management", "synthetic": True,
     "source": "internal compliance library"},
)
doc(
    "STD-TQ-450", "standard", "Synthetic Fastener Torque Practice TQ-450",
    """
TQ-450 Fastener Torque Practice (synthetic, paraphrased — not a real standard).
TQ-450 recommends that threaded fasteners be tightened to the torque specified by
the controlling work instruction, held within a tolerance band of +/-5% of the
nominal value, and re-checked after 24 hours of service to detect relaxation.
Lubricated and dry threads are treated as different conditions and must not share
a torque value.
""",
    {"standard_id": "TQ-450", "topic": "fastener torque", "tolerance_pct": 5,
     "synthetic": True, "source": "internal compliance library"},
)
doc(
    "STD-SF-200", "standard", "Synthetic Hazardous-Energy Control Standard SF-200",
    """
SF-200 Hazardous-Energy Control (synthetic, paraphrased — not a real standard).
SF-200 requires that, before any servicing where unexpected start-up could cause
harm, all energy sources be isolated, locked, and tagged, that stored energy be
released or restrained, and that a zero-energy verification be performed prior to
work. SF-200 is implemented at Plant 7 through SOP-020.
""",
    {"standard_id": "SF-200", "topic": "lockout/tagout", "synthetic": True,
     "implemented_by": "SOP-020", "source": "internal compliance library"},
)

# --- 7. Procurement / purchase-order records (3) ---------------------------
doc(
    "PO-9001", "purchase_order", "Purchase Order PO-9001 — Vector Bearings",
    """
Purchase Order PO-9001. Supplier: Vector Bearings GmbH (SUP-103). Date:
2025-01-10. Line item: PRT-2003 precision bearing, quantity 200 units, unit price
USD 42.50. Minimum order quantity (MOQ): 100 units. Quoted lead time: 45 days.
Ship-to: Helios Plant 7 receiving dock.
""",
    {"po_id": "PO-9001", "supplier_id": "SUP-103", "part_id": "PRT-2003",
     "quantity": 200, "unit_price_usd": 42.50, "moq": 100, "lead_time_days": 45,
     "date": "2025-01-10", "source": "ERP procurement"},
)
doc(
    "PO-9002", "purchase_order", "Purchase Order PO-9002 — Titan Alloys",
    """
Purchase Order PO-9002. Supplier: Titan Alloys (SUP-101). Date: 2025-01-18.
Line item: 4140 steel bar stock, quantity 50 bars, unit price USD 115.00.
Quoted lead time: 21 days. This stock feeds PRT-2001 drive-shaft machining on the
PEGASUS line.
""",
    {"po_id": "PO-9002", "supplier_id": "SUP-101", "material": "4140 steel",
     "quantity": 50, "unit_price_usd": 115.00, "lead_time_days": 21,
     "date": "2025-01-18", "source": "ERP procurement"},
)
doc(
    "PO-9003", "purchase_order", "Purchase Order PO-9003 — Crescent Fasteners",
    """
Purchase Order PO-9003. Supplier: Crescent Fasteners (SUP-104). Date: 2025-02-02.
Line item: PRT-2004 M10 hex bolt, quantity 5000 units, unit price USD 0.35.
Minimum order quantity (MOQ): 1000 units. Quoted lead time: 14 days.
""",
    {"po_id": "PO-9003", "supplier_id": "SUP-104", "part_id": "PRT-2004",
     "quantity": 5000, "unit_price_usd": 0.35, "moq": 1000, "lead_time_days": 14,
     "date": "2025-02-02", "source": "ERP procurement"},
)

# --- 8. Materials property datasheets (3) ----------------------------------
doc(
    "MAT-4140", "material_datasheet", "Material Datasheet — 4140 Alloy Steel",
    """
4140 Alloy Steel (chromium-molybdenum). Properties (typical, quenched & tempered):
ultimate tensile strength 655 MPa, yield strength 415 MPa, density 7.85 g/cm^3,
elongation 25.7%, Brinell hardness 197 HB. Used for the PRT-2001 drive shaft.
(Note: this datasheet lists mechanical properties only; thermal properties such
as melting point are not included.)
""",
    {"material": "4140 steel", "uts_mpa": 655, "yield_mpa": 415,
     "density_g_cm3": 7.85, "hardness_hb": 197, "used_for": ["PRT-2001"],
     "source": "materials library"},
)
doc(
    "MAT-PA66", "material_datasheet", "Material Datasheet — PA66 Nylon",
    """
PA66 (Nylon 6/6), unfilled injection grade. Properties (typical): density
1.14 g/cm^3, tensile strength 80 MPa, melt processing temperature 255 C, mold
shrinkage 1.5%. Used for the PRT-2002 housing cover on the REDFOX program.
""",
    {"material": "PA66", "density_g_cm3": 1.14, "tensile_mpa": 80,
     "melt_temp_c": 255, "shrinkage_pct": 1.5, "used_for": ["PRT-2002"],
     "source": "materials library"},
)
doc(
    "MAT-AL6061", "material_datasheet", "Material Datasheet — 6061-T6 Aluminum",
    """
6061-T6 Aluminum alloy. Properties (typical): ultimate tensile strength 310 MPa,
yield strength 276 MPa, density 2.70 g/cm^3, elongation 12%, Brinell hardness
95 HB. Used for the PRT-2007 mounting bracket.
""",
    {"material": "6061 aluminum", "uts_mpa": 310, "yield_mpa": 276,
     "density_g_cm3": 2.70, "hardness_hb": 95, "used_for": ["PRT-2007"],
     "source": "materials library"},
)

# --- 9. Sensor / telemetry summaries (2, one with table) -------------------
doc(
    "TEL-301", "telemetry", "Telemetry Summary TEL-301 — Cyclops (MCH-301)",
    """
Telemetry Summary TEL-301 — Cyclops CNC lathe (MCH-301), PEGASUS line, May 2025.
Overall Equipment Effectiveness (OEE) is reported with its three components.

| Metric        | Value  |
|---------------|--------|
| Availability  | 91.0%  |
| Performance   | 95.0%  |
| Quality       | 95.2%  |
| OEE           | 82.3%  |
| Avg vibration | 3.2 mm/s |

OEE is the product of Availability x Performance x Quality. Average headstock
vibration of 3.2 mm/s is within the PRT-2005 sensor's 0-50 mm/s range and below
the 4.5 mm/s alarm limit.
""",
    {"telemetry_id": "TEL-301", "machine_id": "MCH-301", "line": "PEGASUS",
     "period": "May 2025", "availability_pct": 91.0, "performance_pct": 95.0,
     "quality_pct": 95.2, "oee_pct": 82.3, "avg_vibration_mm_s": 3.2,
     "vibration_alarm_mm_s": 4.5, "contains_table": True, "source": "historian"},
)
doc(
    "TEL-302", "telemetry", "Telemetry Summary TEL-302 — Hydra (MCH-302)",
    """
Telemetry Summary TEL-302 — Hydra injection-molding machine (MCH-302), KRAKEN
line, May 2025. Overall Equipment Effectiveness (OEE): 76.5%. Availability was
depressed by the March heater-band failure (WO-5002). Cycle time averaged 38
seconds per shot.
""",
    {"telemetry_id": "TEL-302", "machine_id": "MCH-302", "line": "KRAKEN",
     "period": "May 2025", "oee_pct": 76.5, "cycle_time_s": 38,
     "related_wo": "WO-5002", "source": "historian"},
)

# --- 10. Troubleshooting guides / FAQs (2) ---------------------------------
doc(
    "TG-001", "troubleshooting", "Troubleshooting Guide TG-001 — Short Shot (the squeeze)",
    """
Troubleshooting Guide TG-001 — Short Shot on the Hydra injection-molding machine
(MCH-302). A short shot ("the squeeze didn't fill") is an incompletely filled
part. Common causes and checks:
  - Melt temperature too low: verify barrel zone setpoints and heater bands
    (a failed heater band caused NCR-7002 via WO-5002).
  - Injection pressure or hold pressure too low: increase in small steps.
  - Blocked gate or vent: inspect and clean the tool.
  - Insufficient shot size: increase shot volume and check the check-ring.
""",
    {"guide_id": "TG-001", "machine_id": "MCH-302", "defect": "short shot",
     "related": ["NCR-7002", "WO-5002"], "source": "engineering FAQ"},
)
doc(
    "TG-002", "troubleshooting", "Troubleshooting Guide TG-002 — Lathe Chatter / Vibration",
    """
Troubleshooting Guide TG-002 — Chatter and vibration on the Cyclops lathe
(MCH-301). Elevated vibration (watch the PRT-2005 sensor reading) can indicate:
  - Worn or failing spindle bearing (PRT-2003): the root cause behind WO-5001.
  - Excessive spindle speed for the setup: reduce rpm.
  - Long tool overhang or a dull insert: shorten overhang, index the tool.
  - Loose workholding: re-seat and re-clamp the part.
If average vibration exceeds the 4.5 mm/s alarm limit, stop and investigate.
""",
    {"guide_id": "TG-002", "machine_id": "MCH-301", "symptom": "vibration",
     "related": ["WO-5001", "PRT-2003", "PRT-2005"], "source": "engineering FAQ"},
)

# --- 11. Safety / incident reports (2) -------------------------------------
doc(
    "INC-8001", "incident", "Incident Report INC-8001 — LOTO Near-Miss on Hydra",
    """
Incident Report INC-8001. Date: 2025-03-20. Location: KRAKEN line, Hydra
injection-molding machine (MCH-302). Type: near-miss, no injury. During a mold
changeover a technician began opening the platen before stored hydraulic energy
had been released. Root cause: LOTO step 4 (release of stored energy) per SOP-020
was skipped. Corrective action: re-train crew on SOP-020; add a hydraulic
bleed-down check to the changeover checklist in SOP-010.
""",
    {"incident_id": "INC-8001", "date": "2025-03-20", "machine_id": "MCH-302",
     "line": "KRAKEN", "severity": "near-miss", "injury": False,
     "related": ["SOP-020", "SOP-010"], "source": "EHS"},
)
doc(
    "INC-8002", "incident", "Incident Report INC-8002 — Forklift Contact in Warehouse",
    """
Incident Report INC-8002. Date: 2025-04-12. Location: raw-material warehouse.
Type: minor property damage, no injury. A forklift contacted a pallet rack while
reversing, dislodging packaging (no parts damaged). Root cause: blind corner with
no convex mirror. Corrective action: install mirror and repaint floor lanes.
""",
    {"incident_id": "INC-8002", "date": "2025-04-12", "location": "warehouse",
     "severity": "minor", "injury": False, "source": "EHS"},
)

# --- 12. Off-topic "noise" docs (3) ----------------------------------------
doc(
    "NOISE-001", "noise", "Plant 7 Cafeteria — Weekly Lunch Menu",
    """
Plant 7 Cafeteria weekly lunch menu. Monday: chili and cornbread. Tuesday: taco
bar. Wednesday: grilled chicken and rice. Thursday: pasta primavera. Friday:
fish and chips. The salad bar and vegetarian option are available daily. Coffee
is complimentary in the break room.
""",
    {"category": "facilities", "topic": "cafeteria menu", "source": "HR bulletin"},
)
doc(
    "NOISE-002", "noise", "Memo — North Parking Lot Repaving",
    """
Facilities memo: the north employee parking lot will be repaved over the weekend.
Please park in the south or visitor lots during this period. Normal parking
resumes Monday. Contact facilities with questions.
""",
    {"category": "facilities", "topic": "parking", "source": "Facilities memo"},
)
doc(
    "NOISE-003", "noise", "2025 Company Holiday Schedule",
    """
2025 observed company holidays at Plant 7: New Year's Day, Memorial Day,
Independence Day, Labor Day, Thanksgiving (two days), and Christmas Day. The
plant runs a skeleton maintenance crew on observed holidays. Paid-time-off
requests should be filed through the HR portal.
""",
    {"category": "hr", "topic": "holiday schedule", "source": "HR bulletin"},
)


# ---------------------------------------------------------------------------
# PART 2 — QUESTION BANK
# ---------------------------------------------------------------------------
ALLOWED_CATEGORIES = {
    "single_fact", "multi_hop", "aggregation_count", "comparison",
    "numeric_calculation", "unit_conversion", "temporal_versioned",
    "conflict_resolution", "unanswerable", "jargon_codename_acronym",
    "tabular_reasoning", "procedural_stepwise", "constraint_filtering",
    "ambiguous_needs_clarification", "out_of_scope_rejection",
    "high_level_synthesis", "entity_disambiguation",
}
ALLOWED_PERSONAS = {
    "design_engineer", "procurement", "quality", "maintenance", "plant_manager",
}

QUESTIONS = []


def q(qid, question, category, difficulty, persona, answerable, gold, answer, notes):
    QUESTIONS.append(
        {
            "qid": qid,
            "question": question,
            "category": category,
            "difficulty": difficulty,
            "persona": persona,
            "answerable": answerable,
            "gold_doc_ids": gold,
            "reference_answer": answer,
            "eval_notes": notes,
        }
    )


# --- single_fact (6) -------------------------------------------------------
q("Q001", "What is the standard lead time for Vector Bearings GmbH?",
  "single_fact", "easy", "procurement", True, ["SUP-103"],
  "45 days.",
  "Basic single-document fact lookup.")
q("Q002", "What material is the PRT-2002 housing cover made from?",
  "single_fact", "easy", "design_engineer", True, ["SPEC-2002"],
  "PA66 (nylon 6/6).",
  "Single-fact retrieval; must not confuse with the PTFE gasket PRT-2006.")
q("Q003", "What is the diameter tolerance of the PRT-2001 drive shaft?",
  "single_fact", "easy", "design_engineer", True, ["SPEC-2001"],
  "+/-0.02 mm.",
  "Single-fact numeric retrieval.")
q("Q004", "How long was the downtime recorded in work order WO-5002?",
  "single_fact", "easy", "maintenance", True, ["WO-5002"],
  "6.0 hours.",
  "Single-fact retrieval keyed on an explicit record ID.")
q("Q005", "What is the dynamic load rating of the PRT-2003 precision bearing?",
  "single_fact", "easy", "design_engineer", True, ["SPEC-2003"],
  "12.5 kN.",
  "Single-fact spec retrieval.")
q("Q006", "Where is Crescent Fasteners Co. located?",
  "single_fact", "easy", "procurement", True, ["SUP-104"],
  "Monterrey, Mexico.",
  "Single-fact firmographic retrieval.")

# --- multi_hop (5) ---------------------------------------------------------
q("Q007",
  "What is the lead time of the supplier that provides the bearing used on the Cyclops lathe?",
  "multi_hop", "hard", "procurement", True, ["SPEC-2003", "SUP-103"],
  "45 days. Cyclops is MCH-301, which uses bearing PRT-2003, supplied by Vector Bearings (SUP-103), whose lead time is 45 days.",
  "3-hop: machine codename -> part -> supplier -> lead time.")
q("Q008",
  "What raw material is the drive shaft on the PEGASUS line made from, and who supplies that material?",
  "multi_hop", "hard", "design_engineer", True, ["SPEC-2001", "SUP-101"],
  "4140 alloy steel, supplied by Titan Alloys (SUP-101). PEGASUS = Line A, whose drive shaft is PRT-2001, made of 4140 steel sourced from SUP-101.",
  "Multi-hop: line codename -> part -> material -> supplier.")
q("Q009",
  "The part replaced in work order WO-5001 — who supplies it and what is its rated speed?",
  "multi_hop", "medium", "maintenance", True, ["WO-5001", "SPEC-2003"],
  "The replaced part is the PRT-2003 bearing, supplied by Vector Bearings (SUP-103), with a rated speed of 12000 rpm.",
  "Multi-hop: work order -> part -> spec/supplier.")
q("Q010",
  "Which troubleshooting guide applies to the failure mode behind WO-5002, and what part did that failure scrap?",
  "multi_hop", "hard", "quality", True, ["WO-5002", "NCR-7002", "TG-001"],
  "WO-5002 was a heater-band failure that caused short shots; troubleshooting guide TG-001 covers short shots, and NCR-7002 records the scrapped part PRT-2002 (housing cover).",
  "Multi-hop across work order, NCR, and troubleshooting guide.")
q("Q011",
  "What is the OEE of the machine that molds the REDFOX housing cover?",
  "multi_hop", "medium", "plant_manager", True, ["SPEC-2002", "TEL-302"],
  "76.5%. The REDFOX housing cover (PRT-2002) is molded on Hydra (MCH-302), whose OEE in TEL-302 is 76.5%.",
  "Multi-hop: program/part -> machine -> telemetry OEE.")

# --- aggregation_count (5) -------------------------------------------------
q("Q012", "How many work orders were logged against the Cyclops lathe (MCH-301)?",
  "aggregation_count", "medium", "maintenance", True, ["WO-5001", "WO-5004"],
  "2 (WO-5001 and WO-5004).",
  "Counting/aggregation across the work-order set for one asset.")
q("Q013", "How many of the approved suppliers are based in the United States?",
  "aggregation_count", "medium", "procurement", True,
  ["SUP-101", "SUP-102", "SUP-103", "SUP-104", "SUP-105"],
  "3 — Titan Alloys (OH), Pacific Polymers (OR), and Lumen Sensors (CA). Vector Bearings (Germany) and Crescent Fasteners (Mexico) are not.",
  "Count requires filtering by location across all supplier docs.")
q("Q014", "How many distinct parts does Pacific Polymers (SUP-102) supply?",
  "aggregation_count", "medium", "procurement", True, ["SPEC-2002", "SPEC-2006"],
  "2 — the PRT-2002 housing cover (PA66) and the PRT-2006 gasket (PTFE).",
  "Aggregation across part specs by supplier.")
q("Q015", "How many non-conformance reports (NCRs) are in the knowledge base?",
  "aggregation_count", "medium", "quality", True,
  ["NCR-7001", "NCR-7002", "NCR-7004"],
  "3 NCR records (NCR-7001, NCR-7002, NCR-7004). Note NCR-7004 is a suspected duplicate of NCR-7001.",
  "Counting documents of a type; duplicate record complicates the count.")
q("Q016", "How many machines does the LOTO procedure SOP-020 explicitly apply to?",
  "aggregation_count", "easy", "maintenance", True, ["SOP-020"],
  "4 — Cyclops (MCH-301), Hydra (MCH-302), Goliath (MCH-303), and Atlas (MCH-304).",
  "Count of entities listed within a single document.")

# --- comparison (4) --------------------------------------------------------
q("Q017", "Which has the longer lead time, Vector Bearings or Pacific Polymers?",
  "comparison", "easy", "procurement", True, ["SUP-103", "SUP-102"],
  "Vector Bearings (45 days) is longer than Pacific Polymers (35 days).",
  "Two-document numeric comparison.")
q("Q018", "Which material has higher ultimate tensile strength, 4140 steel or 6061 aluminum?",
  "comparison", "medium", "design_engineer", True, ["MAT-4140", "MAT-AL6061"],
  "4140 steel (655 MPa) is much higher than 6061 aluminum (310 MPa).",
  "Cross-datasheet property comparison.")
q("Q019", "Between Line A and Line B, which had the higher Q1 first-pass yield?",
  "comparison", "easy", "quality", True, ["QR-7003"],
  "Line B (KRAKEN) at 96.5% was higher than Line A (PEGASUS) at 94.2%.",
  "Comparison read from a single summary table.")
q("Q020", "Which machine had the lower OEE, Cyclops or Hydra?",
  "comparison", "medium", "plant_manager", True, ["TEL-301", "TEL-302"],
  "Hydra (MCH-302) at 76.5% had a lower OEE than Cyclops (MCH-301) at 82.3%.",
  "Comparison across two telemetry docs using codenames.")

# --- numeric_calculation (4) -----------------------------------------------
q("Q021", "What is the total line-item cost of purchase order PO-9001?",
  "numeric_calculation", "medium", "procurement", True, ["PO-9001"],
  "USD 8,500.00 (200 units x USD 42.50).",
  "Arithmetic over quantity and unit price in one PO.")
q("Q022", "What was the total maintenance downtime across all work orders on the Cyclops lathe?",
  "numeric_calculation", "medium", "maintenance", True, ["WO-5001", "WO-5004"],
  "6.0 hours (4.5 h from WO-5001 + 1.5 h from WO-5004).",
  "Sum across multiple records for one asset.")
q("Q023",
  "Using the components in TEL-301, calculate the OEE of the Cyclops lathe and confirm it matches the reported value.",
  "numeric_calculation", "hard", "plant_manager", True, ["TEL-301"],
  "0.910 x 0.950 x 0.952 = 0.823 = 82.3%, which matches the reported OEE.",
  "Multi-factor calculation that must reproduce the stated figure.")
q("Q024", "What is the total cost of the bolt line item on PO-9003?",
  "numeric_calculation", "easy", "procurement", True, ["PO-9003"],
  "USD 1,750.00 (5000 units x USD 0.35).",
  "Single-line arithmetic.")

# --- unit_conversion (4) ---------------------------------------------------
q("Q025", "Express the current drive-shaft retaining-nut torque in foot-pounds.",
  "unit_conversion", "medium", "maintenance", True, ["SOP-001-v2"],
  "About 70.1 ft-lb (95 Nm x 0.7376). Use the CURRENT 95 Nm value, not the superseded 85 Nm.",
  "Unit conversion that also depends on resolving the current SOP version.")
q("Q026", "What is the PRT-2001 drive-shaft length in inches?",
  "unit_conversion", "easy", "design_engineer", True, ["SPEC-2001"],
  "About 9.84 inches (250 mm / 25.4).",
  "Straight metric-to-imperial length conversion.")
q("Q027", "Express the density of 4140 steel in kg/m^3.",
  "unit_conversion", "easy", "design_engineer", True, ["MAT-4140"],
  "7850 kg/m^3 (7.85 g/cm^3 x 1000).",
  "Density unit conversion.")
q("Q028", "Convert the PRT-2003 bearing bore diameter to inches.",
  "unit_conversion", "easy", "design_engineer", True, ["SPEC-2003"],
  "About 1.181 inches (30 mm / 25.4).",
  "Simple length conversion from a spec.")

# --- temporal_versioned (4) ------------------------------------------------
q("Q029", "What is the effective date of the current drive-shaft torque SOP?",
  "temporal_versioned", "medium", "quality", True, ["SOP-001-v2"],
  "2024-09-15 (SOP-001 Revision 2).",
  "Must select the current revision's effective date, not the superseded one.")
q("Q030", "Which revision of SOP-001 is currently in effect?",
  "temporal_versioned", "easy", "quality", True, ["SOP-001-v2"],
  "Revision 2 (the current/effective version); Revision 1 is superseded.",
  "Version-status retrieval.")
q("Q031", "When was the superseded revision of the drive-shaft torque SOP first effective?",
  "temporal_versioned", "medium", "quality", True, ["SOP-001-v1"],
  "2022-03-01 (SOP-001 Revision 1, now superseded).",
  "Temporal lookup specifically of the older, superseded revision.")
q("Q032", "What period does the QR-7003 quality summary cover?",
  "temporal_versioned", "easy", "plant_manager", True, ["QR-7003"],
  "Q1 2025 (January-March 2025).",
  "Temporal scoping of a report.")

# --- conflict_resolution (4) -----------------------------------------------
q("Q033", "What torque should I apply to the PRT-2001 drive-shaft retaining nut?",
  "conflict_resolution", "hard", "maintenance", True, ["SOP-001-v2", "SOP-001-v1"],
  "95 Nm — the value in the CURRENT SOP-001 Revision 2 (effective 2024-09-15), which supersedes the 85 Nm in Revision 1.",
  "Conflicting versioned values; correct only if the current value (95 Nm) is returned.")
q("Q034", "There are two torque values for the drive shaft in the SOPs — which one is correct now and why?",
  "conflict_resolution", "hard", "quality", True, ["SOP-001-v2", "SOP-001-v1"],
  "95 Nm is correct now. SOP-001 Rev 2 (effective 2024-09-15) explicitly supersedes Rev 1's 85 Nm.",
  "Tests whether the model reasons about supersession metadata, not just keyword match.")
q("Q035", "How many units were affected by the drive-shaft oversize non-conformance?",
  "conflict_resolution", "hard", "quality", True, ["NCR-7001", "NCR-7004"],
  "The records conflict: NCR-7001 says 12 units while its suspected duplicate NCR-7004 says 21. The data-quality team has flagged this as an unresolved discrepancy; the model should surface the conflict rather than assert one number.",
  "Near-duplicate records disagree on one field; correct behavior is to flag the conflict.")
q("Q036", "Is the 85 Nm drive-shaft torque value still valid for production?",
  "conflict_resolution", "medium", "maintenance", True, ["SOP-001-v1", "SOP-001-v2"],
  "No. 85 Nm (SOP-001 Rev 1) is superseded; the current value is 95 Nm (Rev 2).",
  "Conflict resolution framed as a yes/no validity check on the stale value.")

# --- unanswerable (6) ------------------------------------------------------
q("Q037", "What is the warranty period offered on the PRT-2003 bearings?",
  "unanswerable", "medium", "procurement", False, [],
  "Not in the knowledge base. No warranty terms for PRT-2003 (or any part) are documented.",
  "Hallucination resistance: plausible but genuinely absent fact.")
q("Q038", "What is the melting point of 4140 steel?",
  "unanswerable", "medium", "design_engineer", False, [],
  "Not in the knowledge base. The MAT-4140 datasheet lists mechanical properties only; no melting/thermal data is given.",
  "Absent thermal property; the steel datasheet deliberately omits melting point.")
q("Q039", "What is the OEE of the Atlas robot (MCH-304) on the TITAN-LINE?",
  "unanswerable", "medium", "plant_manager", False, [],
  "Not in the knowledge base. Telemetry exists only for MCH-301 and MCH-302; there is no OEE record for MCH-304.",
  "Absent telemetry for a real entity; tests refusal vs. fabrication.")
q("Q040", "What is the unit price of the PRT-2002 housing cover?",
  "unanswerable", "medium", "procurement", False, [],
  "Not in the knowledge base. No purchase order or price record exists for PRT-2002 (POs cover bearings, steel, and bolts only).",
  "Pricing absent for a part that otherwise exists; tests scoped refusal.")
q("Q041", "What is the MTBF of the Hydra injection-molding machine (MCH-302)?",
  "unanswerable", "hard", "maintenance", False, [],
  "Not in the knowledge base. MTBF is reported only for the MCH-301 spindle bearing (WO-5001); no MTBF figure exists for MCH-302.",
  "Acronym is known and a similar fact exists for another machine — strong lure to hallucinate.")
q("Q042", "Who is the CEO of Vector Bearings GmbH?",
  "unanswerable", "easy", "procurement", False, [],
  "Not in the knowledge base. Supplier records list only location, products, lead time, and a contact email — no executive names.",
  "Firmographic detail deliberately absent.")

# --- jargon_codename_acronym (5) -------------------------------------------
q("Q043", "What product program runs on the PEGASUS line?",
  "jargon_codename_acronym", "medium", "plant_manager", True, ["QR-7003"],
  "The BLUEBIRD program (PEGASUS = Line A).",
  "Codename resolution: PEGASUS -> Line A -> BLUEBIRD.")
q("Q044", "What does LOTO stand for and which SOP covers it?",
  "jargon_codename_acronym", "easy", "maintenance", True, ["SOP-020"],
  "LOTO = Lockout/Tagout, covered by SOP-020.",
  "Acronym expansion plus document mapping.")
q("Q045", "On the shop floor, what is meant by 'the dog house'?",
  "jargon_codename_acronym", "medium", "quality", True, ["STD-IS-900"],
  "The 'dog house' is the QA hold / quarantine area where below-threshold lots are held for disposition.",
  "Shop-floor jargon resolution.")
q("Q046", "What is the first-pass yield (FPY) of the KRAKEN line?",
  "jargon_codename_acronym", "medium", "quality", True, ["QR-7003"],
  "96.5% (KRAKEN = Line B, REDFOX program).",
  "Combines acronym (FPY) and codename (KRAKEN) resolution against a table.")
q("Q047", "What does operators' phrase 'the squeeze' refer to?",
  "jargon_codename_acronym", "easy", "maintenance", True, ["SPEC-2002", "TG-001"],
  "'The squeeze' is the injection-molding step (on the Hydra machine, MCH-302).",
  "Jargon resolution for a process step.")

# --- tabular_reasoning (4) -------------------------------------------------
q("Q048", "From the Q1 quality summary, which program had the highest FPY?",
  "tabular_reasoning", "medium", "quality", True, ["QR-7003"],
  "The TITAN-LINE (Line C) assembly at 98.1% FPY.",
  "Row selection by max over a table column.")
q("Q049", "How many units did Line B produce in Q1 according to the quality summary?",
  "tabular_reasoning", "easy", "plant_manager", True, ["QR-7003"],
  "3850 units.",
  "Cell lookup at a row/column intersection in a table.")
q("Q050", "From the TEL-301 table, what is the Cyclops lathe's availability?",
  "tabular_reasoning", "easy", "maintenance", True, ["TEL-301"],
  "91.0%.",
  "Table cell lookup within telemetry doc.")
q("Q051", "Across both lines with reported units in QR-7003 above the 95% threshold, what is their combined Q1 unit output?",
  "tabular_reasoning", "hard", "plant_manager", True, ["QR-7003"],
  "5950 units — Line B (3850) + Line C (2100); Line A is excluded because its 94.2% FPY is below the 95% threshold.",
  "Tabular reasoning with a filter condition plus a sum.")

# --- procedural_stepwise (3) -----------------------------------------------
q("Q052", "What are the steps to lock out the Hydra machine before servicing it?",
  "procedural_stepwise", "medium", "maintenance", True, ["SOP-020"],
  "Per SOP-020: (1) notify operators and shut down normally; (2) isolate electrical, pneumatic, and hydraulic energy; (3) apply locks and tags; (4) release/restrain stored energy; (5) verify zero energy by attempting a restart before working.",
  "Ordered procedure extraction; order matters.")
q("Q053", "Outline the mold changeover procedure on the KRAKEN line.",
  "procedural_stepwise", "medium", "maintenance", True, ["SOP-010"],
  "Per SOP-010: finish the shot count and quarantine in-process parts; perform LOTO (SOP-020); purge the barrel and confirm melt-temp drop; remove the old mold with the hoist; install/clamp the new mold and reconnect water; re-establish parameters and run a first-off inspection.",
  "Multi-step procedure extraction with an embedded cross-reference to SOP-020.")
q("Q054", "What should a technician check first when diagnosing a short shot?",
  "procedural_stepwise", "medium", "maintenance", True, ["TG-001"],
  "Per TG-001, start with melt temperature (verify barrel zone setpoints and heater bands), then injection/hold pressure, blocked gate/vent, and shot size.",
  "Procedural/diagnostic ordering from a troubleshooting guide.")

# --- constraint_filtering (4) ----------------------------------------------
q("Q055", "Which approved suppliers have a quoted lead time of 30 days or less?",
  "constraint_filtering", "medium", "procurement", True,
  ["SUP-101", "SUP-104", "SUP-105"],
  "Three: Titan Alloys (21), Crescent Fasteners (14), and Lumen Sensors (28). Pacific Polymers (35) and Vector Bearings (45) exceed 30 days.",
  "Numeric threshold filter across all supplier docs.")
q("Q056", "Which production lines finished Q1 below the 95% FPY release threshold?",
  "constraint_filtering", "medium", "quality", True, ["QR-7003"],
  "Only Line A (PEGASUS) at 94.2%.",
  "Filter rows of a table against a stated threshold.")
q("Q057", "List the parts that are supplied by Titan Alloys (SUP-101).",
  "constraint_filtering", "medium", "procurement", True, ["SPEC-2001", "SPEC-2007"],
  "PRT-2001 drive shaft (4140 steel) and PRT-2007 aluminum bracket (6061).",
  "Filter parts by supplier across multiple specs.")
q("Q058", "Which work orders involved replacing or servicing a supplier-provided part?",
  "constraint_filtering", "hard", "maintenance", True, ["WO-5001", "WO-5004"],
  "WO-5001 (replaced PRT-2003 bearing) and WO-5004 (recalibrated PRT-2005 sensor). WO-5002 and WO-5003 did not replace a catalog part.",
  "Filter work orders by whether a part/supplier is referenced.")

# --- ambiguous_needs_clarification (3) -------------------------------------
q("Q059", "What is the torque value?",
  "ambiguous_needs_clarification", "medium", "maintenance", False, [],
  "Ambiguous — clarification needed. Torque depends on the fastener: the drive-shaft retaining nut (currently 95 Nm per SOP-001 Rev 2) and the M10 hex bolt (governed by TQ-450) are different. Ask which fastener is meant before answering.",
  "Under-specified query; correct behavior is to request clarification, not guess.")
q("Q060", "How long is the lead time?",
  "ambiguous_needs_clarification", "easy", "procurement", False, [],
  "Ambiguous — clarification needed. Lead time varies by supplier (14-45 days). Ask which supplier or part is meant.",
  "Missing entity; multiple valid answers exist, so clarify first.")
q("Q061", "What's the OEE?",
  "ambiguous_needs_clarification", "easy", "plant_manager", False, [],
  "Ambiguous — clarification needed. OEE is reported per machine (Cyclops 82.3%, Hydra 76.5%). Ask which machine or line is meant.",
  "Ambiguous metric request spanning multiple entities.")

# --- out_of_scope_rejection (4) --------------------------------------------
q("Q062", "What's the weather forecast for tomorrow?",
  "out_of_scope_rejection", "easy", "plant_manager", False, [],
  "Out of scope. This is a manufacturing knowledge base and does not contain weather information; the RAG system should decline and redirect.",
  "Off-topic; should be refused/redirected, not answered.")
q("Q063", "Can you recommend a good stock to invest in?",
  "out_of_scope_rejection", "easy", "procurement", False, [],
  "Out of scope. Financial/investment advice is outside the purpose of this knowledge base.",
  "Off-topic and advice-seeking; refuse and redirect.")
q("Q064", "Write me a poem about the ocean.",
  "out_of_scope_rejection", "easy", "design_engineer", False, [],
  "Out of scope. Creative writing is unrelated to the manufacturing knowledge base.",
  "Tests that the system stays on-task rather than free-forming.")
q("Q065", "What is Helios Plant 7's total annual revenue and profit margin?",
  "out_of_scope_rejection", "medium", "plant_manager", False, [],
  "Out of scope / not in the knowledge base. Financial performance is not part of this operational/technical corpus.",
  "Plausible business question outside the corpus scope; refuse rather than fabricate.")

# --- high_level_synthesis (4) — gold_doc_ids intentionally empty -----------
q("Q066", "Give an overall assessment of the reliability risks on the PEGASUS line.",
  "high_level_synthesis", "hard", "plant_manager", True, [],
  "Synthesis (no single source): PEGASUS (Line A) shows the spindle-bearing failure on Cyclops (WO-5001, MTBF 1820 h) and a follow-on sensor recalibration (WO-5004); a drive-shaft oversize non-conformance (NCR-7001/7004) dragging Line A's Q1 FPY to 94.2% (below the 95% threshold, QR-7003); and vibration trends (TEL-301, TG-002). Net: bearing reliability and dimensional control are the leading risks.",
  "High-level synthesis spanning WO/NCR/QR/TEL/TG; answer is in no single doc.")
q("Q067", "Summarize the plant's quality posture for Q1 2025.",
  "high_level_synthesis", "hard", "quality", True, [],
  "Synthesis: Q1 FPY was 94.2% (Line A), 96.5% (Line B), 98.1% (Line C); only Line A fell below the 95% threshold and needs a corrective-action plan. Drivers include the drive-shaft oversize NCR on Line A and a short-shot scrap NCR on Line B tied to a heater-band failure.",
  "Cross-document synthesis of overall quality state.")
q("Q068", "Assess the supply-chain risk for the bearing used on the Cyclops lathe.",
  "high_level_synthesis", "hard", "procurement", True, [],
  "Synthesis: the PRT-2003 bearing is single-sourced from Vector Bearings (SUP-103) in Germany with the longest lead time of any supplier (45 days), it is a known failure item (WO-5001), and it sits on two critical machines (MCH-301 and MCH-303). Long lead time plus single-source plus failure history make it a notable risk.",
  "Risk synthesis combining supplier, PO, spec, and maintenance evidence.")
q("Q069", "What are the main themes across the plant's 2025 safety incidents?",
  "high_level_synthesis", "medium", "plant_manager", True, [],
  "Synthesis: incidents in 2025 include a LOTO near-miss on Hydra from skipped stored-energy release (INC-8001) and a forklift rack contact in the warehouse (INC-8002). Themes: energy-control procedure adherence and warehouse traffic/visibility.",
  "Thematic synthesis across incident reports.")

# --- entity_disambiguation (3) ---------------------------------------------
q("Q070", "Tell me about 'Titan' at the plant.",
  "entity_disambiguation", "hard", "plant_manager", True, ["SUP-101", "SPEC-2007"],
  "'Titan' is ambiguous: Titan Alloys (SUP-101) is the Cleveland metals supplier, while TITAN-LINE is Line C (final assembly). They are unrelated despite the shared word; clarify which is meant. (PRT-2007 is used on the TITAN-LINE.)",
  "Deliberate name collision between a supplier and a production line.")
q("Q071", "Which 'Atlas' are you referring to — is it a supplier?",
  "entity_disambiguation", "medium", "maintenance", True, ["SOP-020", "SPEC-2007"],
  "Atlas is the MCH-304 assembly robot on the TITAN-LINE, not a supplier. No supplier named Atlas exists in the corpus.",
  "Disambiguates a machine codename from an assumed supplier category.")
q("Q072", "The PEGASUS line uses a bearing supplied by Vector Bearings — is that the same Vector that does our sensors?",
  "entity_disambiguation", "medium", "procurement", True, ["SUP-103", "SUP-105"],
  "No. Vector Bearings GmbH (SUP-103) supplies bearings; sensors come from Lumen Sensors (SUP-105). There is no sensor supplier named 'Vector'.",
  "Disambiguates two suppliers and corrects a false-premise conflation.")


# ---------------------------------------------------------------------------
# Emit files
# ---------------------------------------------------------------------------
def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_questions_csv(path, rows):
    fields = ["qid", "question", "category", "difficulty", "persona",
              "answerable", "gold_doc_ids", "reference_answer", "eval_notes"]
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            flat = dict(r)
            flat["gold_doc_ids"] = ";".join(r["gold_doc_ids"])
            flat["answerable"] = "true" if r["answerable"] else "false"
            writer.writerow(flat)


def main():
    write_jsonl(OUT_DIR / "corpus.jsonl", CORPUS)
    write_jsonl(OUT_DIR / "questions.jsonl", QUESTIONS)
    write_questions_csv(OUT_DIR / "questions.csv", QUESTIONS)
    print(f"Wrote {len(CORPUS)} docs -> corpus.jsonl")
    print(f"Wrote {len(QUESTIONS)} questions -> questions.jsonl / questions.csv")


if __name__ == "__main__":
    main()
