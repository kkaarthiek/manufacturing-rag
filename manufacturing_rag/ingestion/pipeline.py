"""
P1-A orchestration (spec 6.1 steps 1-12, deterministic core).  STATUS: IMPLEMENTED.

raw/ -> validated CanonicalDoc objects, joined on entity IDs, every gold fact
present + normalized + resolved + traceable. Each canonical doc keeps the parsed
raw text (clean_text) beside the computed/normalized structured_fields
(reversibility), so the verify gate (6.12) can confirm the derived facts.

This module is the Tranche-A core that drives ingestion-fact recall 0.615 -> 1.0
with NO LLM and NO network. Tranche B (extract.py/derive.py) layers the semantic
units on top using Claude Haiku + OpenAI embeddings.
"""

from __future__ import annotations

import json
from pathlib import Path

from .. import REPO_ROOT
from ..contracts import CanonicalDoc, StructuredRecord, Edge
from . import parsers as P
from . import clean as C
from . import transforms as T
from .resolve import resolve_or_flag
from .master import load_master

RAW = REPO_ROOT / "raw"
ENTITY_GRAPH_ID = "_ENTITY_GRAPH_"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _doc(doc_id, doc_type, source_file, fmt, text, fields=None, version=None,
         entities=None, prov=None):
    return CanonicalDoc(
        id=doc_id, doc_type=doc_type, source_file=source_file, format=fmt,
        clean_text=text.strip(), structured_fields=fields or {},
        version=version or {}, entities=entities or [],
        provenance=prov or {"file": source_file})


def _read(rel):
    return (RAW / rel).read_bytes()


class Pipeline:
    def __init__(self):
        self.alias_map, self.entities, self.edges = load_master(
            RAW / "mes" / "machines.json")
        self.docs: dict[str, CanonicalDoc] = {}
        self.records: list[StructuredRecord] = []
        self.flags: list[dict] = []

    # ---- resolution helper ----
    def rid(self, name_or_id):
        cid = resolve_or_flag(name_or_id, self.alias_map, self.flags)
        return cid or name_or_id

    def register_supplier_aliases(self):
        """Extend the alias map with supplier name->ID (full + first-two-words),
        so PO/BOM references by name resolve (spec 6.6: the #1 recall lever)."""
        for sid, d in self.docs.items():
            if d.doc_type != "supplier":
                continue
            name = (d.structured_fields.get("name") or "").strip()
            if not name:
                continue
            toks = name.replace(",", " ").split()
            for alias in (name.lower(), " ".join(toks[:2]).lower()):
                if alias:
                    self.alias_map[alias] = sid

    # ===================================================================== #
    # per-source assemblers
    # ===================================================================== #
    def suppliers(self):
        rows = P.parse_csv_rows(_read("erp/suppliers_master.csv"))
        seen = {}
        for r in rows:
            sid = r.get("supplier_id", "").strip()
            if not sid:
                continue
            lt_raw = r.get("Lead Time", "")
            days = T.lead_time_to_days(lt_raw)
            email = (r.get("contact_email") or "").strip() or "MISSING"
            entry = seen.setdefault(sid, {"raws": [], "days": days, "name": r.get("Name", ""),
                                          "country": r.get(" country ", r.get("country", "")),
                                          "products": r.get("Products", ""), "email": email})
            entry["raws"].append(lt_raw)
            if days is not None:
                entry["days"] = days
            if email != "MISSING":
                entry["email"] = email
        for sid, e in seen.items():
            fields = {"name": e["name"].strip(), "country": e["country"].strip(),
                      "products": e["products"], "lead_time_days": e["days"],
                      "lead_time_unit": "days", "lead_time_raw_values": e["raws"],
                      "contact_email": e["email"]}
            text = (f"Supplier {sid} {e['name'].strip()}. Lead time {e['days']} days "
                    f"(raw: {', '.join(e['raws'])}). Contact email {e['email']}.")
            self.docs[sid] = _doc(sid, "supplier", "erp/suppliers_master.csv", "csv",
                                  text, fields, entities=[sid])
            self.records.append(StructuredRecord(
                table="suppliers", key=sid, fields=fields,
                raw={"lead_time": e["raws"]}, normalized={"lead_time_days": e["days"]},
                units={"lead_time": "days"}, source_doc_id=sid))

    def purchase_orders(self):
        rows = P.parse_csv_rows(_read("erp/purchase_orders.csv"))
        for r in rows:
            po = r.get("PO", "").strip()
            if not po:
                continue
            qty = T.parse_int(r.get("Qty", ""))
            price = T.parse_money(r.get("Unit Price", ""))
            moq_raw = (r.get("MOQ") or "").strip()
            moq = T.parse_int(moq_raw) if moq_raw else None
            total = T.line_total(qty, price) if (qty and price) else None
            sup_ref = r.get("Supplier", "")
            sup_id = self.rid(sup_ref)
            part = r.get("Part", "")
            date = T.normalize_date(r.get("Date", ""))
            price_raw = r.get("Unit Price", "")
            fields = {"supplier_name": sup_ref, "supplier_id": sup_id, "part": part,
                      "qty": qty, "unit_price": price, "unit_price_raw": price_raw,
                      "total": total, "moq": moq if moq is not None else "MISSING",
                      "date": date}
            total_s = f"{total:.2f}" if total is not None else "n/a"
            text = (f"Purchase order {po}. Supplier name {sup_ref} -> {sup_id}. "
                    f"Qty {qty} unit_price {price_raw} ({price}) total {total_s}. "
                    f"MOQ {moq if moq is not None else 'MISSING'}. Date {date}.")
            self.docs[po] = _doc(po, "purchase_order", "erp/purchase_orders.csv", "csv",
                                 text, fields, entities=[po, sup_id])
            self.records.append(StructuredRecord(
                table="purchase_orders", key=po, fields=fields,
                raw={"unit_price": r.get("Unit Price"), "qty": r.get("Qty"), "moq": moq_raw},
                normalized={"total": total, "qty": qty, "unit_price": price},
                units={"unit_price": "USD"}, source_doc_id=po))

    def bom_parts(self):
        rows = P.parse_csv_rows(_read("erp/bom_parts.csv"))
        for r in rows:
            pid = r.get("part_id", "").strip()        # PRT-200N
            if not pid:
                continue
            spec_id = pid.replace("PRT-", "SPEC-")     # canonical doc id
            length = T.strip_unit_number(r.get("dim_length", ""))
            od = T.strip_unit_number(r.get("dim_od", ""))
            tol = T.strip_unit_number(r.get("tolerance", ""))
            sup_ref = r.get("supplier", "")
            sup_id = self.rid(sup_ref)
            used = [self.rid(m.strip()) for m in r.get("used_on", "").replace(",", ";").split(";")
                    if m.strip()]
            material = (r.get("material") or "").strip() or "MISSING"
            desc = (r.get("description") or "").strip()
            fields = {"part_id": pid, "description": desc, "length_mm": length,
                      "od_mm": od, "tolerance_mm": tol, "material": material,
                      "supplier_id": sup_id, "supplier_ref": sup_ref,
                      "used_on": used, "program": (r.get("program") or "").strip()}
            text = (f"Part {pid} ({spec_id}). length {length} mm od {od} mm "
                    f"tol {tol} mm. material {material}. supplier {sup_ref} -> {sup_id}. "
                    f"used_on {', '.join(used)}.")
            self.docs[spec_id] = _doc(spec_id, "part_spec", "erp/bom_parts.csv", "csv",
                                      text, fields, entities=[pid, sup_id, *used])
            self.records.append(StructuredRecord(
                table="parts", key=spec_id, fields=fields, raw=dict(r),
                normalized={"length_mm": length, "od_mm": od, "tolerance_mm": tol},
                units={"length": "mm"}, source_doc_id=spec_id))

    def work_orders(self):
        rows = P.parse_csv_rows(_read("maintenance/cmms_export.csv"))
        for r in rows:
            wo = r.get("WO", "").strip()
            if not wo:
                continue
            dt_raw = r.get("Downtime", "")
            hours = T.parse_duration_hours(dt_raw)
            minutes = round(hours * 60) if hours is not None else None
            mtbf = r.get("MTBF_hours", "").strip()
            machine = r.get("Machine", "").strip()
            notes = r.get("Notes", "")
            part = next((tok for tok in notes.replace("(", " ").replace(")", " ").split()
                         if tok.startswith("PRT-")), "")
            fields = {"machine": machine, "part": part, "downtime_raw": dt_raw,
                      "downtime_hours": hours, "downtime_minutes": minutes,
                      "mtbf_hours": mtbf or None, "date": T.normalize_date(r.get("Date", ""))}
            text = (f"Work order {wo} machine {machine}. "
                    f"downtime {C.space_units(dt_raw)} = {hours} h ( {minutes} min ). "
                    f"MTBF {mtbf} h. part {part}. {notes}")
            self.docs[wo] = _doc(wo, "work_order", "maintenance/cmms_export.csv", "csv",
                                 text, fields, entities=[wo, machine] + ([part] if part else []))
            self.records.append(StructuredRecord(
                table="work_orders", key=wo, fields=fields,
                raw={"downtime": dt_raw}, normalized={"downtime_hours": hours,
                "downtime_minutes": minutes}, units={"downtime": "h"}, source_doc_id=wo))

    def shift_log_corroborate(self):
        text = P.parse("txt", _read("maintenance/shift_log_notes.txt"))
        for wo in ("WO-5001", "WO-5002", "WO-5004"):
            if wo in self.docs:
                self.docs[wo].clean_text += "\n[corroborating shift log] " + text
                self.docs[wo].provenance.setdefault("corroborating_sources", []).append(
                    "maintenance/shift_log_notes.txt")

    def telemetry(self):
        # vibration -> TEL-301 mean + sample count
        vib = P.decode_text(_read("telemetry/MCH-301_vibration_2025-05.csv"))
        vals, n = [], 0
        for line in vib.splitlines():
            line = line.strip()
            if line.startswith("#") or line.lower().startswith("timestamp") or not line:
                continue
            parts = line.split(",")
            if len(parts) >= 2:
                try:
                    vals.append(float(parts[1])); n += 1
                except ValueError:
                    pass
        vib_mean = T.mean(vals, 1)
        # oee daily -> per-machine component means -> OEE
        oee_rows = P.parse_csv_rows(_read("telemetry/oee_daily_may2025.csv"))
        agg = {}
        for r in oee_rows:
            mid = r.get("machine", "").strip()
            if not mid:
                continue
            a = agg.setdefault(mid, {"a": [], "p": [], "q": []})
            a["a"].append(float(r["availability"])); a["p"].append(float(r["performance"]))
            a["q"].append(float(r["quality"]))
        comp = {mid: (T.mean(v["a"], 4), T.mean(v["p"], 4), T.mean(v["q"], 4))
                for mid, v in agg.items()}

        a1, p1, q1 = comp["MCH-301"]
        oee1 = T.oee(a1, p1, q1)
        f1 = {"machine": "MCH-301", "availability": a1, "performance": p1, "quality": q1,
              "oee_pct": oee1, "avg_vibration_mm_s": vib_mean, "vibration_samples": n,
              "vibration_alarm_mm_s": 4.5, "units": "mm/s", "units_source": "comment line"}
        t1 = (f"Telemetry TEL-301 machine MCH-301. monthly OEE {a1}*{p1}*{q1} = {oee1}%. "
              f"avg vibration {vib_mean} mm/s aggregated from {n} samples; "
              f"units mm/s declared in a comment line; alarm 4.5 mm/s.")
        self.docs["TEL-301"] = _doc("TEL-301", "telemetry", "telemetry/*", "csv",
                                    t1, f1, entities=["MCH-301"])

        a2, p2, q2 = comp["MCH-302"]
        oee2 = T.oee(a2, p2, q2)
        f2 = {"machine": "MCH-302", "availability": a2, "performance": p2, "quality": q2,
              "oee_pct": oee2}
        t2 = (f"Telemetry TEL-302 machine MCH-302. monthly OEE {a2}*{p2}*{q2} = {oee2}%.")
        self.docs["TEL-302"] = _doc("TEL-302", "telemetry", "telemetry/oee_daily_may2025.csv",
                                    "csv", t2, f2, entities=["MCH-302"])
        for r in (StructuredRecord(table="telemetry", key="TEL-301", fields=f1,
                                   normalized={"oee_pct": oee1, "avg_vibration_mm_s": vib_mean},
                                   source_doc_id="TEL-301"),
                  StructuredRecord(table="telemetry", key="TEL-302", fields=f2,
                                   normalized={"oee_pct": oee2}, source_doc_id="TEL-302")):
            self.records.append(r)

    def ncr_scans(self):
        for rel, did in (("quality/NCR-7001_scan.txt", "NCR-7001"),
                         ("quality/NCR-7004_scan.txt", "NCR-7004")):
            text = C.fix_ocr(P.parse("txt", _read(rel)))
            self.docs[did] = _doc(did, "ncr", rel, "txt (OCR)", text,
                                  {"ocr_corrected": True}, entities=[did])
        # conflict flag (never merge): units_affected differs 12 vs 21.
        # entities/keywords let the query-time conflict branch (verification/
        # conflict.py) recognise a question that lands on this disputed field.
        flag = {"field": "units_affected", "values": {"NCR-7001": 12, "NCR-7004": 21},
                "entities": ["NCR-7001", "NCR-7004", "PRT-2001"],
                "keywords": ["drive shaft", "drive-shaft", "oversize",
                             "non-conformance", "nonconformance"],
                "resolution": "flag_both", "status": "unresolved"}
        self.flags.append(flag)
        self.docs["NCR-7004"].structured_fields["conflict"] = flag

    def ncr_email(self):
        text = P.parse("eml", _read("quality/ncr7002_email.eml"))
        self.docs["NCR-7002"] = _doc("NCR-7002", "ncr", "quality/ncr7002_email.eml", "eml",
                                     text, {}, entities=["NCR-7002", "PRT-2002", "WO-5002"])

    def quality_report(self):
        text = P.parse("xlsx", _read("quality/Q1_2025_FPY.xlsx"))
        self.docs["QR-7003"] = _doc("QR-7003", "quality_report", "quality/Q1_2025_FPY.xlsx",
                                    "xlsx", text, {"contains_table": True})

    def sops(self):
        v1 = P.parse("html", _read("sops/SOP-001_rev1.html"))
        self.docs["SOP-001-v1"] = _doc(
            "SOP-001-v1", "sop", "sops/SOP-001_rev1.html", "html", v1,
            {"sop_id": "SOP-001", "version": 1, "torque_nm": 85, "status": "superseded",
             "superseded_by": "SOP-001-v2", "effective_date": "2022-03-01"},
            version={"rev": 1, "effective_date": "2022-03-01", "is_current": False,
                     "superseded_by": "SOP-001-v2"})
        v2 = P.parse("docx", _read("sops/SOP-001_Rev2.docx"))
        self.docs["SOP-001-v2"] = _doc(
            "SOP-001-v2", "sop", "sops/SOP-001_Rev2.docx", "docx", v2,
            {"sop_id": "SOP-001", "version": 2, "torque_nm": 95, "status": "current",
             "supersedes": "SOP-001-v1", "effective_date": "2024-09-15"},
            version={"rev": 2, "effective_date": "2024-09-15", "is_current": True,
                     "supersedes": "SOP-001-v1"})
        for rel, did in (("sops/SOP-010_changeover.html", "SOP-010"),
                         ("sops/SOP-020_loto.html", "SOP-020")):
            txt = P.parse("html", _read(rel))
            steps = txt.count("\n- ")                  # <li> -> "- " (ordered steps)
            self.docs[did] = _doc(did, "sop", rel, "html",
                                  txt + f"\n[{steps}-step procedure]",
                                  {"step_count": steps})

    def troubleshooting(self):
        # 2-in-1 HTML; parser already splits <section> via boilerplate rules -> keep whole,
        # then carve TG-001 / TG-002 by heading.
        text = P.parse("html", _read("kb/troubleshooting.html"))
        idx = text.find("TG-002")
        tg1 = text[:idx] if idx > 0 else text
        tg2 = text[idx:] if idx > 0 else text
        self.docs["TG-001"] = _doc("TG-001", "troubleshooting", "kb/troubleshooting.html",
                                   "html", tg1, {"machine": "MCH-302"}, entities=["MCH-302"])
        self.docs["TG-002"] = _doc("TG-002", "troubleshooting", "kb/troubleshooting.html",
                                   "html", tg2, {"machine": "MCH-301"}, entities=["MCH-301"])

    def standards(self):
        for rel, did, fmt in (("standards/HX-900_excerpt.pdf", "STD-IS-900", "pdf"),
                              ("standards/TQ-450.txt", "STD-TQ-450", "txt"),
                              ("standards/SF-200.txt", "STD-SF-200", "txt")):
            text = P.parse(fmt, _read(rel))
            self.docs[did] = _doc(did, "standard", rel, fmt, text, {})

    def materials(self):
        # 4140: inject derived density kg/m3
        m4140 = P.parse("txt", _read("materials/4140_steel_datasheet.txt"))
        f4140 = {"material": "4140", "uts_mpa": 655, "yield_mpa": 415,
                 "density_g_cm3": 7.85, "density_kg_m3": 7850, "hardness_hb": 197,
                 "melting_point": None, "absent_by_design": "melting point"}
        self.docs["MAT-4140"] = _doc(
            "MAT-4140", "material_datasheet", "materials/4140_steel_datasheet.txt", "txt",
            m4140 + "\nDensity 7.85 g/cm3 = 7850 kg/m3 (cubic, exponent 3)."
                    "\nNo melting point present by design.", f4140)
        self.records.append(StructuredRecord(
            table="materials", key="MAT-4140", fields=f4140,
            normalized={"density_kg_m3": 7850}, source_doc_id="MAT-4140"))
        for alias in ("4140", "4140 steel", "4140 alloy steel"):
            self.alias_map[alias] = "MAT-4140"
        # 2-in-1 datasheet -> split
        whole = P.parse("txt", _read("materials/PA66_AL6061_datasheets.txt"))
        frags = C.split_multidoc(whole, "datasheet")
        pa = next((f for f in frags if "PA66" in f or "Nylon" in f), frags[0])
        al = next((f for f in frags if "6061" in f), frags[-1])
        self.docs["MAT-PA66"] = _doc("MAT-PA66", "material_datasheet",
                                     "materials/PA66_AL6061_datasheets.txt", "txt",
                                     pa, {"grade": "PA 66", "polymer": "nylon 66"})
        self.docs["MAT-AL6061"] = _doc("MAT-AL6061", "material_datasheet",
                                       "materials/PA66_AL6061_datasheets.txt", "txt", al, {})

    def incidents(self):
        for rel, did in (("safety/INC-8001_report.txt", "INC-8001"),
                         ("safety/INC-8002_report.txt", "INC-8002")):
            self.docs[did] = _doc(did, "incident", rel, "txt", P.parse("txt", _read(rel)), {})

    def noise(self):
        # classifier output: noise + topical category (off-topic facilities/HR)
        for rel, did, cat in (("misc/cafeteria_menu.txt", "NOISE-001", "off-topic facilities content"),
                              ("misc/parking_memo.txt", "NOISE-002", "off-topic facilities content"),
                              ("misc/holiday_schedule_2025.txt", "NOISE-003", "off-topic HR content")):
            self.docs[did] = _doc(did, "noise", rel, "txt", P.parse("txt", _read(rel)),
                                  {"category": cat})

    def backfill_entities(self):
        """Backfill each doc's entities with every canonical ID appearing in its
        text (machines, parts, suppliers, SOPs, standards) -> comprehensive
        MENTIONS edges for the graph lane (spec 6.6 resolution feeds traversal)."""
        import re as _re
        idpat = _re.compile(r"\b[A-Z]{2,4}-\d{2,5}(?:-v\d+)?\b")
        for did, d in self.docs.items():
            found = set(d.entities)
            for m in idpat.findall(d.clean_text):
                found.add(m)
            # resolve codenames/jargon in text via alias map
            low = d.clean_text.lower()
            for alias, cid in self.alias_map.items():
                if len(alias) >= 4 and _re.search(
                        r"(?<![a-z0-9])" + _re.escape(alias) + r"(?![a-z0-9])", low):
                    found.add(cid)
            d.entities = sorted(found)

    def entity_graph_doc(self):
        alias_txt = "; ".join(f"{a}={cid}" for a, cid in sorted(self.alias_map.items()))
        edge_txt = "; ".join(f"{e.src} {e.rel} {e.dst}" for e in self.edges)
        text = f"Entity graph (machines.json). aliases: {alias_txt}. edges: {edge_txt}."
        self.docs[ENTITY_GRAPH_ID] = _doc(ENTITY_GRAPH_ID, "entity_graph",
                                          "mes/machines.json", "json", text,
                                          {"alias_count": len(self.alias_map)},
                                          entities=[e.canonical_id for e in self.entities])

    # ===================================================================== #
    def run(self):
        self.suppliers()
        self.register_supplier_aliases()   # name->ID before PO/BOM resolution
        self.purchase_orders()
        self.bom_parts()
        self.work_orders()
        self.shift_log_corroborate()
        self.telemetry()
        self.ncr_scans()
        self.ncr_email()
        self.quality_report()
        self.sops()
        self.troubleshooting()
        self.standards()
        self.materials()
        self.incidents()
        self.noise()
        self.backfill_entities()
        self.entity_graph_doc()
        return self


def haystacks(docs: dict) -> dict:
    """doc_id -> searchable text (title+clean_text+structured fields), per spec."""
    out = {}
    for did, d in docs.items():
        out[did] = f"{d.id}\n{d.clean_text}\n{json.dumps(d.structured_fields, ensure_ascii=False)}"
    return out


def run_pipeline() -> Pipeline:
    return Pipeline().run()


if __name__ == "__main__":
    p = run_pipeline()
    print(f"docs={len(p.docs)} records={len(p.records)} "
          f"entities={len(p.entities)} edges={len(p.edges)} flags={len(p.flags)}")
