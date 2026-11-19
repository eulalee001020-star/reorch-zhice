"""Run with `odoo-bin shell -d reorch_odoo_test --no-http < this_file`.

Synthetic fixtures only. Refuses any database without the dedicated test name.
"""

from datetime import datetime, timedelta

env = globals()["env"]  # Supplied by the Odoo shell.

assert env.cr.dbname == "reorch_odoo_test", "Use the isolated test database only"
now = datetime(2026, 11, 20, 8)
if not env["product.product"].search([("default_code", "=", "REORCH-TEST-FG")]):
    raw = env["product.product"].create(
        {"name": "ReOrch Test Component", "default_code": "REORCH-TEST-RAW", "is_storable": True}
    )
    fg = env["product.product"].create(
        {"name": "ReOrch Test Assembly", "default_code": "REORCH-TEST-FG", "is_storable": True}
    )
    center = env["mrp.workcenter"].create({"name": "ReOrch Test Bench", "code": "REORCH-TEST-WC"})
    bom = env["mrp.bom"].create(
        {
            "product_tmpl_id": fg.product_tmpl_id.id,
            "product_id": fg.id,
            "product_qty": 1,
            "bom_line_ids": [(0, 0, {"product_id": raw.id, "product_qty": 2})],
            "operation_ids": [
                (
                    0,
                    0,
                    {
                        "name": "Assemble test product",
                        "workcenter_id": center.id,
                        "time_cycle_manual": 20,
                        "time_mode": "manual",
                    },
                )
            ],
        }
    )
    location = env.ref("stock.stock_location_stock")
    env["stock.quant"]._update_available_quantity(raw, location, 100)
    mo = env["mrp.production"].create(
        {
            "product_id": fg.id,
            "product_qty": 5,
            "bom_id": bom.id,
            "date_start": now,
            "date_deadline": now + timedelta(days=1),
        }
    )
    mo.action_confirm()
    mo.workorder_ids.write({"date_start": now, "date_finished": now + timedelta(hours=2)})
    vendor = env["res.partner"].create({"name": "ReOrch Synthetic Supplier", "supplier_rank": 1})
    po = env["purchase.order"].create(
        {
            "partner_id": vendor.id,
            "order_line": [
                (
                    0,
                    0,
                    {
                        "product_id": raw.id,
                        "name": raw.name,
                        "product_qty": 20,
                        "product_uom": raw.uom_po_id.id,
                        "price_unit": 2,
                        "date_planned": now + timedelta(hours=4),
                    },
                )
            ],
        }
    )
    po.button_confirm()
env.ref("base.user_admin").write({"login": "reorch-test", "password": "odoo-sandbox-only"})
env.cr.commit()
print("Isolated synthetic Odoo fixture ready")
