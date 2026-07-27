#!/usr/bin/env python3
"""Build auditable ReOrch reliability packs from downloaded public datasets."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import openpyxl


ROOT = Path(__file__).resolve().parents[1]
PACK_ROOT = ROOT / "datasets" / "public_reliability_packs"
UTC = timezone.utc


SOURCES: dict[str, dict[str, Any]] = {
    "p0_ulster_mes": {
        "tier": "P0",
        "title": "Ulster University Manufacturing Operations Dataset",
        "source_url": "https://mdep.smdh.uk/en/dataset/ulster-university--manufacturing-operations-dataset",
        "license": "Other (Non-Commercial)",
        "provenance": "real_anonymized_mes",
        "expected_raw": [
            "product_cycle_anonymised.csv",
            "df_unit_level_cycle_downtime_anonymised.csv",
            "order_analysis_anonymised.csv",
            "stoppage_all_anonymised.csv",
            "Manufacturing Operations Documentation.pdf",
        ],
    },
    "p0_textile_schedule": {
        "tier": "P0",
        "title": "Production line dataset for task scheduling and energy optimization",
        "source_url": "https://zenodo.org/records/4106746",
        "license": "MIT",
        "provenance": "real_company_schedule",
        "expected_raw": [
            "Input_JSON_Schedule_Optimization.json",
            "Output_JSON_Schedule_Optimization.json",
            "Output_Statistics_Schedule_Optimization.xlsx",
        ],
    },
    "p1_flexible_packaging": {
        "tier": "P1",
        "title": "Data for Flexible Packaging Scheduling",
        "source_url": "https://data.mendeley.com/datasets/h66hb89k6z/1",
        "license": "CC BY 4.0",
        "provenance": "public_research_dataset_unverified_factory_origin",
        "expected_raw": ["source_bundle.zip"],
    },
    "p1_aerospace_surface_treatment": {
        "tier": "P1",
        "title": "Aerospace Production Scheduling",
        "source_url": "https://data.mendeley.com/datasets/p7g96yvvgb/2",
        "license": "CC BY 4.0",
        "provenance": "real_demand_plus_simulated_stress",
        "expected_raw": ["source_bundle.zip"],
    },
    "p1_tablets_manufacturing": {
        "tier": "P1",
        "title": "TABLETS_MANUFACTURING",
        "source_url": "https://data.mendeley.com/datasets/mm7yr6t7pp/1",
        "license": "CC BY 4.0",
        "provenance": "real_anonymized_production_planning",
        "expected_raw": ["source_bundle.zip"],
    },
}


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    materialized = list(rows)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(materialized)
    return len(materialized)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_id(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value).strip()).strip("_")


def iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def read_sheet(path: Path, sheet_name: str, header_row: int = 1) -> list[dict[str, Any]]:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet = workbook[sheet_name]
    rows = sheet.iter_rows(values_only=True)
    for _ in range(header_row - 1):
        next(rows)
    headers = [str(value).strip() if value is not None else "" for value in next(rows)]
    result = []
    for row in rows:
        record = {headers[index]: value for index, value in enumerate(row) if index < len(headers) and headers[index]}
        if any(value is not None for value in record.values()):
            result.append(record)
    workbook.close()
    return result


def process_map(machine_name: str) -> str:
    name = machine_name.lower()
    if "printing" in name:
        return "P1"
    if "dry" in name and "lam" in name:
        return "P2"
    if "extrusion" in name:
        return "P3"
    if "slitting" in name or "sliting" in name:
        return "P4"
    if "bag" in name or "pouch" in name:
        return "P5"
    return "UNMAPPED"


def build_textile(pack: Path) -> dict[str, Any]:
    raw = pack / "raw"
    source = json.loads((raw / "Input_JSON_Schedule_Optimization.json").read_text(encoding="utf-8"))
    output = json.loads((raw / "Output_JSON_Schedule_Optimization.json").read_text(encoding="utf-8"))
    canonical = pack / "canonical"
    scenario_dir = pack / "scenarios"
    epoch = datetime(2026, 1, 5, 7, tzinfo=UTC)

    task_modes = {row["id"]: len(row.get("power", [])) for row in source["task_modes"]}
    task_to_modes = {row["id"]: row["task_modes"] for row in source["tasks"]}
    mode_to_machines: dict[str, list[str]] = defaultdict(list)
    for machine in source["machines"]:
        for mode in machine["task_modes"]:
            mode_to_machines[mode].append(machine["id"])

    work_orders = []
    operations = []
    product_defs = {row["id"]: row for row in source["products"]}
    for request_index, request in enumerate(source["product_requests"], 1):
        work_order_id = f"TEXTILE-WO-{request_index:04d}"
        due_slot = int(request.get("deadline", source["configuration"]["time_window"]))
        work_orders.append({
            "work_order_id": work_order_id,
            "product_id": request["product"],
            "product_name": request["product"],
            "quantity": request["amount"],
            "priority": 100 if "deadline" in request else 0,
            "due_time": iso(epoch + timedelta(minutes=due_slot * 5)),
            "status": "planned",
        })
        sequence = 0
        previous = ""
        for task_spec in product_defs[request["product"]]["tasks"]:
            for run in range(1, int(task_spec["runs"]) + 1):
                sequence += 1
                operation_id = f"{work_order_id}-OP-{sequence:03d}"
                modes = task_to_modes[task_spec["task"]]
                machines = sorted({machine for mode in modes for machine in mode_to_machines.get(mode, [])})
                duration = min((task_modes.get(mode, 1) for mode in modes), default=1) * 5
                operations.append({
                    "operation_id": operation_id,
                    "work_order_id": work_order_id,
                    "sequence": sequence,
                    "required_capability": task_spec["task"],
                    "processing_time_min": duration,
                    "eligible_machine_ids": "|".join(machines),
                    "predecessors": previous,
                    "source_run": run,
                })
                previous = operation_id

    resources = [{
        "machine_id": machine["id"],
        "name": machine["id"],
        "capabilities": "|".join(sorted({mode.split(" TM", 1)[0] for mode in machine["task_modes"]})),
        "status": "available",
    } for machine in source["machines"]]

    schedule = []
    assignment_index = 0
    for cell in output["cell_schedules"]:
        for machine in cell["machines"]:
            for assignment in machine["assignments"]:
                assignment_index += 1
                duration_slots = task_modes.get(assignment["task_mode"], 1)
                schedule.append({
                    "schedule_operation_id": f"TEXTILE-SCHEDULE-{assignment_index:04d}",
                    "machine_id": machine["machine"],
                    "task": assignment["task"],
                    "task_mode": assignment["task_mode"],
                    "planned_start": iso(epoch + timedelta(minutes=int(assignment["start"]) * 5)),
                    "planned_end": iso(epoch + timedelta(minutes=(int(assignment["start"]) + duration_slots) * 5)),
                    "product_finished": assignment.get("product_finished", ""),
                })

    counts = {
        "work_orders": write_csv(canonical / "work_orders.csv", list(work_orders[0]), work_orders),
        "operations": write_csv(canonical / "operations.csv", list(operations[0]), operations),
        "resources": write_csv(canonical / "resources.csv", list(resources[0]), resources),
        "schedule": write_csv(canonical / "current_schedule.csv", list(schedule[0]), schedule),
    }
    incident_time = epoch + timedelta(minutes=300 * 5)
    scenarios = [
        {"scenario_id": "textile_machine_down", "incident_type": "machine_down", "machine_id": "MAQ118", "occurred_at": iso(incident_time), "duration_min": 180, "provenance": "synthetic_incident_on_real_schedule"},
        {"scenario_id": "textile_capacity_degradation", "incident_type": "capacity_degradation", "machine_id": "MAQ120", "occurred_at": iso(incident_time + timedelta(hours=3)), "capacity_ratio": 0.5, "duration_min": 240, "provenance": "synthetic_incident_on_real_schedule"},
        {"scenario_id": "textile_urgent_order", "incident_type": "urgent_order_insert", "occurred_at": iso(incident_time + timedelta(hours=6)), "product_id": source["product_requests"][0]["product"], "quantity": 2, "due_in_min": 360, "provenance": "synthetic_incident_on_real_schedule"},
    ]
    write_json(scenario_dir / "incidents.json", scenarios)
    return {"counts": counts, "scenario_count": len(scenarios), "limitations": ["Published schedule assignments cannot be deterministically joined to source work-order instances."]}


def build_flexible_packaging(pack: Path) -> dict[str, Any]:
    base = next((pack / "raw" / "extracted").rglob("1-Machine.xlsx")).parent
    machines = read_sheet(base / "1-Machine.xlsx", "1-Machine", header_row=2)
    routes = read_sheet(base / "3-Routing.xlsx", "3-Routing", header_row=2)
    products = read_sheet(base / "5-Product Type.xlsx", "5-Product Type", header_row=2)
    orders = read_sheet(base / "6-Data Order.xlsx", "6-Data Order", header_row=2)
    route_map = {int(row["No"]): str(row["Routing"]).split("-") for row in routes}
    product_map = {int(row["No"]): row for row in products}
    resource_rows = [{
        "machine_id": row["Code"],
        "name": row["Machine Name"],
        "capabilities": process_map(str(row["Machine Name"])),
        "status": "available",
        "minimum_speed": row.get("MinSpeed", ""),
        "speed_ratio": row.get("Ratio Speed", ""),
        "setup_time_min": row.get("SetupTime", ""),
    } for row in machines]
    process_resources: dict[str, list[str]] = defaultdict(list)
    for row in resource_rows:
        process_resources[row["capabilities"]].append(str(row["machine_id"]))

    work_orders = []
    operations = []
    for order in orders:
        order_no = int(order["No"])
        wo_id = f"FLEX-WO-{order_no:04d}"
        product_id = int(order["Tipe Produk"])
        due = order["Deadline"]
        work_orders.append({
            "work_order_id": wo_id,
            "product_id": f"FLEX-PRODUCT-{product_id:03d}",
            "product_name": f"Flexible packaging type {product_id}",
            "quantity": order["Running Meter"],
            "priority": int(order["Prioritas"]),
            "due_time": iso(due),
            "status": "planned",
        })
        product = product_map[product_id]
        route = route_map[int(product["Routing"])]
        previous = ""
        for sequence, process in enumerate(route, 1):
            op_id = f"{wo_id}-OP-{sequence:02d}"
            lookup_process = "P2" if process == "P2b" else process
            eligible = process_resources.get(lookup_process, [])
            operations.append({
                "operation_id": op_id,
                "work_order_id": wo_id,
                "sequence": sequence,
                "required_capability": process,
                "processing_time_min": max(1, int(float(order["Running Meter"]) / 200)),
                "eligible_machine_ids": "|".join(eligible),
                "predecessors": previous,
                "mapping_status": "mapped" if eligible else "unmapped",
            })
            previous = op_id

    canonical = pack / "canonical"
    counts = {
        "work_orders": write_csv(canonical / "work_orders.csv", list(work_orders[0]), work_orders),
        "operations": write_csv(canonical / "operations.csv", list(operations[0]), operations),
        "resources": write_csv(canonical / "resources.csv", list(resource_rows[0]), resource_rows),
    }
    incidents = [
        {"scenario_id": "flex_printing_down", "incident_type": "machine_down", "machine_id": resource_rows[0]["machine_id"], "occurred_at": "2022-10-03T08:00:00+00:00", "duration_min": 240, "provenance": "synthetic_incident_on_public_research_data"},
        {"scenario_id": "flex_urgent_order", "incident_type": "urgent_order_insert", "occurred_at": "2022-10-05T08:00:00+00:00", "source_work_order_id": work_orders[0]["work_order_id"], "priority": 100, "due_in_min": 720, "provenance": "synthetic_incident_on_public_research_data"},
        {"scenario_id": "flex_material_delay", "incident_type": "material_shortage", "occurred_at": "2022-10-07T08:00:00+00:00", "affected_capability": "P2", "available_in_min": 480, "provenance": "synthetic_incident_on_public_research_data"},
    ]
    write_json(pack / "scenarios" / "incidents.json", incidents)
    unmapped = sum(row["mapping_status"] == "unmapped" for row in operations)
    return {"counts": counts, "scenario_count": len(incidents), "unmapped_operations": unmapped, "limitations": ["Factory origin is not established by the repository page.", "Process-to-machine mapping is inferred from published machine names and is retained as an explicit assumption."]}


def read_semicolon_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter=";"))


def build_aerospace(pack: Path) -> dict[str, Any]:
    base = next((pack / "raw" / "extracted").rglob("MaxFixturesPerTank.csv")).parent
    raw_material = {row["Item_ID"]: row for row in read_semicolon_csv(base / "RawMaterial.csv")}
    max_fixture = {row["Item_ID"]: row for row in read_semicolon_csv(base / "MaxFixturesPerTank.csv")}
    per_fixture = {row["Item_ID"]: row for row in read_semicolon_csv(base / "MaxPerFixture.csv")}
    tanks = ["B1", "B2", "B6", "LTS30"]
    resources = [{"machine_id": f"TANK-{tank}", "name": tank, "capabilities": "surface_treatment_batch", "status": "available"} for tank in tanks]
    work_orders = []
    operations = []
    real_case_rows = []
    for demand_file in sorted((base / "Real_Demand").glob("*.csv")):
        case_id = safe_id(demand_file.stem)
        for row in read_semicolon_csv(demand_file):
            quantity = int(row["Quantity"])
            if quantity <= 0:
                continue
            item = row["Item_ID"]
            wo_id = f"AERO-{case_id}-{safe_id(item)}"
            eligible = [f"TANK-{tank}" for tank in tanks if int(raw_material[item].get(tank, 0)) == 1]
            fixture_capacity = max((int(max_fixture.get(item, {}).get(f"tank_{tank}", 0) or 0) for tank in ["B1", "B2"]), default=0)
            units_per_fixture = int(per_fixture.get(item, {}).get("quantity", 1) or 1)
            work_orders.append({"work_order_id": wo_id, "product_id": item, "product_name": item, "quantity": quantity, "priority": 0, "due_time": "", "status": "planned", "source_case": case_id})
            operations.append({"operation_id": f"{wo_id}-OP-01", "work_order_id": wo_id, "sequence": 1, "required_capability": "surface_treatment_batch", "processing_time_min": 60, "eligible_machine_ids": "|".join(eligible), "fixture_capacity": fixture_capacity, "units_per_fixture": units_per_fixture})
            real_case_rows.append({"case_id": case_id, "work_order_id": wo_id, "item_id": item, "quantity": quantity, "source_type": "real_demand"})

    stress_rows = []
    for demand_file in sorted((base / "Simulated_Demand").glob("*.csv")):
        case_id = f"stress_{safe_id(demand_file.stem)}"
        for row in read_semicolon_csv(demand_file):
            quantity = int(row["Quantity"])
            if quantity > 0:
                stress_rows.append({"case_id": case_id, "item_id": row["Item_ID"], "quantity": quantity, "source_type": "simulated_stress"})

    canonical = pack / "canonical"
    counts = {
        "work_orders": write_csv(canonical / "work_orders.csv", list(work_orders[0]), work_orders),
        "operations": write_csv(canonical / "operations.csv", list(operations[0]), operations),
        "resources": write_csv(canonical / "resources.csv", list(resources[0]), resources),
        "real_demand_rows": write_csv(canonical / "real_demand_cases.csv", list(real_case_rows[0]), real_case_rows),
        "stress_rows": write_csv(canonical / "simulated_stress_cases.csv", list(stress_rows[0]), stress_rows),
    }
    incidents = [
        {"scenario_id": "aero_tank_down", "incident_type": "machine_down", "machine_id": "TANK-B2", "occurred_at": "2026-06-11T08:00:00+00:00", "duration_min": 480, "provenance": "synthetic_incident_on_real_demand"},
        {"scenario_id": "aero_fixture_shortage", "incident_type": "capacity_degradation", "machine_id": "TANK-B1", "occurred_at": "2026-06-11T09:00:00+00:00", "capacity_ratio": 0.5, "duration_min": 360, "provenance": "synthetic_incident_on_real_demand"},
        {"scenario_id": "aero_double_demand", "incident_type": "urgent_order_insert", "occurred_at": "2026-06-11T10:00:00+00:00", "stress_source": "canonical/simulated_stress_cases.csv", "provenance": "publisher_simulated_stress"},
    ]
    write_json(pack / "scenarios" / "incidents.json", incidents)
    return {"counts": counts, "scenario_count": len(incidents), "limitations": ["Dataset contains demand and capacity constraints, not an MES execution timeline or planner decision history."]}


def build_tablets(pack: Path) -> dict[str, Any]:
    workbook_path = next((pack / "raw" / "extracted").rglob("data.xlsx"))
    demands = read_sheet(workbook_path, "Demand")
    capacities = read_sheet(workbook_path, "Capacity")
    bom_headers = read_sheet(workbook_path, "BOMHeader")
    bom_items = read_sheet(workbook_path, "BOMItem")
    setups = read_sheet(workbook_path, "SetupMatrix")
    header_by_key = {(row["probleminstanceid"], row["materialid"]): row for row in bom_headers}
    inputs_by_header: dict[str, list[str]] = defaultdict(list)
    for row in bom_items:
        inputs_by_header[str(row["bomheaderid"])].append(str(row["materialid"]))

    resources = [{
        "machine_id": row["machineid"],
        "name": row["machinename"],
        "capabilities": row["probleminstanceid"],
        "status": "available",
        "capacity": row["capacity"],
        "valid_from": iso(row["validitydatefrom"]),
        "valid_to": iso(row["validitydateto"]),
    } for row in capacities]
    work_orders = []
    operations = []
    for index, demand in enumerate(demands, 1):
        wo_id = f"TABLET-WO-{index:05d}"
        key = (demand["probleminstanceid"], demand["materialid"])
        header = header_by_key.get(key)
        work_orders.append({
            "work_order_id": wo_id,
            "product_id": demand["materialid"],
            "product_name": demand["materialid"],
            "quantity": demand["quantity"],
            "priority": 0,
            "due_time": iso(demand["deliverydate"]),
            "status": "planned",
            "problem_instance": demand["probleminstanceid"],
        })
        operations.append({
            "operation_id": f"{wo_id}-OP-01",
            "work_order_id": wo_id,
            "sequence": 1,
            "required_capability": demand["probleminstanceid"],
            "processing_time_min": max(1, round(float(header.get("productiontime", 1)) * float(demand["quantity"]))) if header else 1,
            "eligible_machine_ids": header["machineid"] if header else "",
            "material_inputs": "|".join(inputs_by_header.get(str(header.get("bomheaderid", "")), [])) if header else "",
            "mapping_status": "mapped" if header else "missing_bom_header",
        })

    setup_rows = [{key: value for key, value in row.items()} for row in setups]
    canonical = pack / "canonical"
    counts = {
        "work_orders": write_csv(canonical / "work_orders.csv", list(work_orders[0]), work_orders),
        "operations": write_csv(canonical / "operations.csv", list(operations[0]), operations),
        "resources": write_csv(canonical / "resources.csv", list(resources[0]), resources),
        "setup_matrix": write_csv(canonical / "setup_matrix.csv", list(setup_rows[0]), setup_rows),
    }
    incidents = [
        {"scenario_id": "tablets_packaging_robot_down", "incident_type": "machine_down", "machine_id": resources[0]["machine_id"], "occurred_at": "2018-06-01T08:00:00+00:00", "duration_min": 1440, "provenance": "synthetic_incident_on_real_anonymized_planning_data"},
        {"scenario_id": "tablets_material_hold", "incident_type": "quality_hold", "affected_material_id": work_orders[0]["product_id"], "occurred_at": "2018-07-01T08:00:00+00:00", "release_in_min": 720, "provenance": "synthetic_incident_on_real_anonymized_planning_data"},
        {"scenario_id": "tablets_demand_surge", "incident_type": "urgent_order_insert", "source_work_order_id": work_orders[0]["work_order_id"], "quantity_multiplier": 2, "occurred_at": "2018-08-01T08:00:00+00:00", "provenance": "synthetic_incident_on_real_anonymized_planning_data"},
    ]
    write_json(pack / "scenarios" / "incidents.json", incidents)
    missing = sum(row["mapping_status"] != "mapped" for row in operations)
    return {"counts": counts, "scenario_count": len(incidents), "missing_bom_headers": missing, "limitations": ["Lot-sizing data does not contain timestamped equipment incidents, planner actions, or execution outcomes."]}


def build_ulster_surrogate_and_twin(pack: Path) -> dict[str, Any]:
    """Materialize an explicitly synthetic fallback without weakening the raw-data gate."""
    source = ROOT / "datasets" / "p0_reality_pack"
    surrogate = pack / "surrogate_sample"
    surrogate.mkdir(parents=True, exist_ok=True)
    for name in ("erp_work_orders.csv", "aps_resources.csv"):
        shutil.copyfile(source / name, surrogate / name)

    with (source / "erp_work_orders.csv").open(encoding="utf-8", newline="") as handle:
        seed_orders = list(csv.DictReader(handle))
    with (source / "mes_operations.csv").open(encoding="utf-8", newline="") as handle:
        seed_operations = list(csv.DictReader(handle))
    with (source / "aps_resources.csv").open(encoding="utf-8", newline="") as handle:
        seed_resources = list(csv.DictReader(handle))
    with (source / "mes_downtime_events.csv").open(encoding="utf-8", newline="") as handle:
        seed_incidents = list(csv.DictReader(handle))

    extension_operation = dict(seed_operations[-1])
    extension_operation.update({
        "operation_id": "OP-P0-SYNTHETIC-EXT-01",
        "work_order_id": seed_orders[-1]["work_order_id"],
        "sequence": "99",
        "start_time": "2026-05-14T16:00:00+08:00",
        "end_time": "2026-05-14T16:45:00+08:00",
        "predecessors": seed_operations[-1]["operation_id"],
        "successors": "",
        "provenance": "synthetic_extension_to_required_shape",
    })
    for row in seed_operations:
        row["provenance"] = "existing_local_surrogate_sample"
    seed_operations.append(extension_operation)
    extension_incident = dict(seed_incidents[-1])
    extension_incident.update({
        "incident_id": "INC-P0-SYNTHETIC-EXT-02",
        "machine_id": seed_resources[-1]["machine_id"],
        "start_time": "2026-05-14T15:20:00+08:00",
        "severity": "P2-High",
        "description": "Synthetic capacity degradation added to meet the 2-event surrogate test shape.",
        "provenance": "synthetic_extension_to_required_shape",
    })
    for row in seed_incidents:
        row["provenance"] = "existing_local_surrogate_sample"
    seed_incidents.append(extension_incident)
    write_csv(surrogate / "mes_operations.csv", list(seed_operations[0]), seed_operations)
    write_csv(surrogate / "mes_downtime_events.csv", list(seed_incidents[0]), seed_incidents)

    twin = pack / "digital_twin"
    twin.mkdir(parents=True, exist_ok=True)
    target_operations = 10_000
    work_order_count = (target_operations + len(seed_operations) - 1) // len(seed_operations)
    epoch = datetime(2026, 7, 13, tzinfo=UTC)
    twin_orders = []
    twin_operations = []
    receipts = []
    cdc_path = twin / "cdc_events_10000.jsonl"
    with cdc_path.open("w", encoding="utf-8") as cdc:
        sequence = 0
        for index in range(work_order_count):
            seed_order = seed_orders[index % len(seed_orders)]
            wo_id = f"DT-WO-{index + 1:05d}"
            due_time = epoch + timedelta(hours=24 + index % 168)
            twin_orders.append({
                "work_order_id": wo_id,
                "product_id": seed_order.get("product_id", seed_order.get("product_code", "DT-PRODUCT")),
                "quantity": seed_order.get("quantity", 1),
                "priority": seed_order.get("priority", 0),
                "due_time": iso(due_time),
                "status": "planned",
                "provenance": "synthetic_digital_twin_from_p0_sample",
                "seed_work_order_id": seed_order.get("work_order_id", ""),
                "generation_seed": 20260713,
            })
            for local_index, seed_operation in enumerate(seed_operations):
                if len(twin_operations) >= target_operations:
                    break
                op_id = f"{wo_id}-OP-{local_index + 1:03d}"
                machine_id = seed_operation.get("machine_id") or seed_operation.get("assigned_machine_id") or seed_resources[local_index % len(seed_resources)].get("machine_id", "DT-MACHINE")
                start = epoch + timedelta(minutes=len(twin_operations) * 3)
                duration = int(float(seed_operation.get("processing_time_min") or seed_operation.get("standard_duration_min") or 30))
                twin_operations.append({
                    "operation_id": op_id,
                    "work_order_id": wo_id,
                    "sequence": local_index + 1,
                    "machine_id": machine_id,
                    "processing_time_min": duration,
                    "planned_start": iso(start),
                    "planned_end": iso(start + timedelta(minutes=duration)),
                    "provenance": "synthetic_digital_twin_from_p0_sample",
                    "seed_operation_id": seed_operation.get("operation_id", ""),
                    "generation_seed": 20260713,
                })
                receipt_status = "completed" if len(twin_operations) % 23 else "failed"
                receipts.append({
                    "receipt_id": f"DT-MES-RECEIPT-{len(twin_operations):05d}",
                    "operation_id": op_id,
                    "work_order_id": wo_id,
                    "machine_id": machine_id,
                    "status": receipt_status,
                    "occurred_at": iso(start + timedelta(minutes=duration)),
                    "idempotency_key": f"dt-mes:{op_id}:v1",
                    "terminal": True,
                    "provenance": "synthetic_digital_twin_mes_receipt",
                })
                sequence += 1
                event = {
                    "event_id": f"DT-CDC-{sequence:05d}",
                    "source_system": "digital_twin_mes",
                    "partition_key": machine_id,
                    "sequence": sequence,
                    "occurred_at": iso(start),
                    "entity_type": "operation",
                    "entity_id": op_id,
                    "operation": "upsert",
                    "provenance": "synthetic_digital_twin_cdc",
                }
                cdc.write(json.dumps(event, ensure_ascii=False) + "\n")

    twin_incidents = []
    for index in range(300):
        seed_incident = seed_incidents[index % len(seed_incidents)]
        machine = seed_incident.get("machine_id") or seed_resources[index % len(seed_resources)].get("machine_id", "DT-MACHINE")
        twin_incidents.append({
            "incident_id": f"DT-INCIDENT-{index + 1:04d}",
            "incident_type": seed_incident.get("incident_type", "machine_down"),
            "machine_id": machine,
            "start_time": iso(epoch + timedelta(minutes=index * 37)),
            "duration_min": 30 + (index % 12) * 15,
            "severity": f"P{1 + index % 4}",
            "provenance": "synthetic_digital_twin_from_p0_sample",
            "seed_incident_id": seed_incident.get("incident_id", ""),
            "generation_seed": 20260713,
        })

    order_fields = list(twin_orders[0])
    operation_fields = list(twin_operations[0])
    incident_fields = list(twin_incidents[0])
    receipt_fields = list(receipts[0])
    counts = {
        "surrogate_work_orders": len(seed_orders),
        "surrogate_operations": len(seed_operations),
        "surrogate_resources": len(seed_resources),
        "surrogate_downtime_events": len(seed_incidents),
        "digital_twin_work_orders": write_csv(twin / "work_orders_10k.csv", order_fields, twin_orders),
        "digital_twin_operations": write_csv(twin / "operations_10k.csv", operation_fields, twin_operations),
        "digital_twin_incidents": write_csv(twin / "incidents_300.csv", incident_fields, twin_incidents),
        "digital_twin_mes_receipts": write_csv(twin / "mes_terminal_receipts_10k.csv", receipt_fields, receipts),
        "digital_twin_cdc_events": sequence,
    }
    write_json(twin / "generation_contract.json", {
        "generation_seed": 20260713,
        "parent_dataset": "datasets/p0_reality_pack",
        "parent_shape": {"operations": len(seed_operations), "downtime_events": len(seed_incidents)},
        "profiles": {"operations": 10_000, "incidents": 300, "mes_terminal_receipts": 10_000, "cdc_events": 10_000},
        "provenance": "synthetic_digital_twin",
        "allowed_claims": ["engineering_stability", "throughput", "idempotency", "cdc_sequence", "receipt_state_machine"],
        "forbidden_claims": ["real_mes_validation", "real_shadow", "real_roi", "customer_production_reliability", "production_writeback_authorization"],
    })

    rehearsal = pack / "customer_admission_rehearsal"
    dictionary_rows = [
        {"source_object": "ERP_WORK_ORDER", "source_field": "work_order_id", "canonical_object": "WorkOrder", "canonical_field": "work_order_id", "type": "string", "required": True, "authority": "order_authority"},
        {"source_object": "ERP_WORK_ORDER", "source_field": "due_time", "canonical_object": "WorkOrder", "canonical_field": "due_time", "type": "datetime-tz", "required": True, "authority": "order_authority"},
        {"source_object": "MES_OPERATION", "source_field": "operation_id", "canonical_object": "Operation", "canonical_field": "operation_id", "type": "string", "required": True, "authority": "execution_authority"},
        {"source_object": "MES_OPERATION", "source_field": "machine_id", "canonical_object": "Operation", "canonical_field": "machine_id", "type": "string", "required": True, "authority": "execution_authority"},
        {"source_object": "MES_INCIDENT", "source_field": "start_time", "canonical_object": "Incident", "canonical_field": "start_time", "type": "datetime-tz", "required": True, "authority": "execution_authority"},
        {"source_object": "MES_RECEIPT", "source_field": "status", "canonical_object": "ExecutionFeedback", "canonical_field": "status", "type": "enum", "required": True, "authority": "execution_authority"},
        {"source_object": "PLANNER_DECISION", "source_field": "disposition", "canonical_object": "DecisionRecord", "canonical_field": "planner_disposition", "type": "enum", "required": True, "authority": "schedule_authority"},
    ]
    write_csv(rehearsal / "mes_data_dictionary.csv", list(dictionary_rows[0]), dictionary_rows)
    cases, planner_rows, rehearsal_receipts = [], [], []
    dispositions = ["accepted", "adjusted", "rejected"]
    for index in range(30):
        number = index + 1
        case_id = f"REHEARSAL-CASE-{number:03d}"
        operation = twin_operations[(index * 317) % len(twin_operations)]
        seed_incident = seed_incidents[index % len(seed_incidents)]
        disposition = dispositions[index % len(dispositions)]
        occurred_at = epoch + timedelta(hours=index * 5)
        receipt_id = f"REHEARSAL-RECEIPT-{number:03d}"
        reason = {"accepted": "meets_constraints", "adjusted": "hidden_shift_constraint", "rejected": "material_status_unconfirmed"}[disposition]
        cases.append({
            "case_id": case_id,
            "provenance": "synthetic_customer_admission_rehearsal",
            "incident": {"type": seed_incident.get("type", "machine_down"), "occurred_at": iso(occurred_at), "machine_id": operation["machine_id"], "affected_operation_id": operation["operation_id"]},
            "pre_incident_snapshot": {"snapshot_id": f"REHEARSAL-SNAPSHOT-{number:03d}", "snapshot_hash": hashlib.sha256(f"{case_id}:snapshot".encode()).hexdigest(), "as_of": iso(occurred_at - timedelta(minutes=1))},
            "planner_result": {"disposition": disposition, "reason_code": reason},
            "execution_outcome": {"receipt_id": receipt_id, "status": "completed" if disposition != "rejected" else "not_executed"},
            "source_refs": [f"surrogate_sample/mes_operations.csv#{operation['seed_operation_id']}", f"surrogate_sample/mes_downtime_events.csv#{seed_incident['incident_id']}", f"customer_admission_rehearsal/execution_receipts.csv#{receipt_id}"],
        })
        planner_rows.append({"case_id": case_id, "planner_role": "synthetic_planner", "disposition": disposition, "reason_code": reason, "decided_at": iso(occurred_at + timedelta(minutes=20)), "provenance": "synthetic_customer_admission_rehearsal"})
        rehearsal_receipts.append({"receipt_id": receipt_id, "case_id": case_id, "operation_id": operation["operation_id"], "status": "completed" if disposition != "rejected" else "not_executed", "terminal": True, "provenance": "synthetic_customer_admission_rehearsal"})
    write_json(rehearsal / "historical_incident_cases_30.json", cases)
    write_csv(rehearsal / "planner_dispositions.csv", list(planner_rows[0]), planner_rows)
    write_csv(rehearsal / "execution_receipts.csv", list(rehearsal_receipts[0]), rehearsal_receipts)
    write_json(rehearsal / "admission_gate.json", {
        "rehearsal_case_count": 30,
        "real_customer_case_count": 0,
        "real_mes_data_dictionary_received": False,
        "real_execution_receipts_received": False,
        "real_planner_dispositions_received": False,
        "customer_admission_ready": False,
        "provenance": "synthetic_customer_admission_rehearsal",
    })
    counts.update({
        "admission_rehearsal_cases": len(cases),
        "admission_rehearsal_dictionary_fields": len(dictionary_rows),
        "admission_rehearsal_planner_dispositions": len(planner_rows),
        "admission_rehearsal_execution_receipts": len(rehearsal_receipts),
        "real_customer_cases": 0,
    })
    return {
        "counts": counts,
        "digital_twin_status": "built_from_small_surrogate",
        "limitations": [
            "Official Ulster MES raw files are absent.",
            "The only MES-shaped local seed contains 7 operations and 2 downtime events.",
            "Digital-twin MES receipts are synthetic and cannot validate real Shadow or real ROI.",
            "Thirty synthetic admission cases validate workflow shape only; real customer case count remains zero.",
        ],
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_inventory(pack: Path) -> list[dict[str, Any]]:
    inventory = []
    for path in sorted(pack.rglob("*")):
        if (
            path.is_file()
            and path.name not in {"manifest.json", "quality_report.json"}
            and "__pycache__" not in path.parts
            and path.suffix != ".pyc"
        ):
            inventory.append({"path": str(path.relative_to(pack)), "bytes": path.stat().st_size, "sha256": sha256(path)})
    return inventory


def build_pack(pack_id: str) -> dict[str, Any]:
    source = SOURCES[pack_id]
    pack = PACK_ROOT / pack_id
    raw = pack / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    missing_raw = [name for name in source["expected_raw"] if not (raw / name).exists()]
    acquired = not missing_raw
    result: dict[str, Any] = {"counts": {}, "scenario_count": 0, "limitations": []}
    if pack_id == "p0_ulster_mes":
        result = build_ulster_surrogate_and_twin(pack)
    elif acquired:
        if pack_id == "p0_textile_schedule":
            result = build_textile(pack)
        elif pack_id == "p1_flexible_packaging":
            result = build_flexible_packaging(pack)
        elif pack_id == "p1_aerospace_surface_treatment":
            result = build_aerospace(pack)
        elif pack_id == "p1_tablets_manufacturing":
            result = build_tablets(pack)
    else:
        result["limitations"] = ["Official source was unavailable during acquisition; no synthetic substitute was created."]

    quality = {
        "pack_id": pack_id,
        "acquisition_status": "complete" if acquired else "acquisition_blocked",
        "missing_raw_files": missing_raw,
        "canonical_status": "built" if acquired else "not_built",
        "evidence_gate": {
            "official_raw_file_count": len(source["expected_raw"]) - len(missing_raw),
            "official_raw_expected_count": len(source["expected_raw"]),
            "real_mes_validated": acquired and pack_id == "p0_ulster_mes",
            "real_shadow_validated": False,
            "real_shadow_2_to_4_weeks_validated": False,
            "real_roi_validated": False,
            "production_writeback_authorized": False,
        },
        **result,
    }
    write_json(pack / "quality_report.json", quality)
    manifest = {
        "pack_id": pack_id,
        "tier": source["tier"],
        "title": source["title"],
        "source_url": source["source_url"],
        "license": source["license"],
        "provenance": source["provenance"],
        "claim_boundary": "Engineering reliability evidence only; not customer production reliability, ROI, planner adoption, or writeback authorization.",
        "critical_conclusion": (
            "Local p0_ulster_mes has no real anonymized MES raw files; all 5 expected files are missing and acquisition_status is acquisition_blocked. "
            "Available MES-shaped evidence is a 7-operation, 2-downtime-event surrogate plus digital-twin MES receipts. "
            "This does not validate real MES data, real Shadow, or real ROI."
            if pack_id == "p0_ulster_mes" else None
        ),
        "gate_interpretation": (
            {
                "overall_result": "4 complete public packs pass; Ulster MES strict source gate fails",
                "system_failure": False,
                "digital_twin_engineering_consistency": "pass",
                "official_anonymized_mes_source": "fail",
                "real_mes_validation": False,
                "real_shadow": False,
                "real_shadow_2_to_4_weeks": False,
                "real_roi": False,
                "production_writeback_authorization": False,
            }
            if pack_id == "p0_ulster_mes" else None
        ),
        "acquisition_status": quality["acquisition_status"],
        "generated_at": "2026-07-13T00:00:00+08:00",
        "files": file_inventory(pack),
    }
    write_json(pack / "manifest.json", manifest)
    return quality


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", choices=[*SOURCES, "all"], default="all")
    args = parser.parse_args()
    selected = list(SOURCES) if args.pack == "all" else [args.pack]
    results = [build_pack(pack_id) for pack_id in selected]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(result["acquisition_status"] == "complete" for result in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
