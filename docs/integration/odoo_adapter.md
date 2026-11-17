# Odoo 适配器

`app/adapters/odoo_adapter.py` 把 Odoo 制造模块的数据读成 ReOrch 的标准对象，并在人工确认后把工序的计划时间写回。它是第一个面向具体 ERP 产品的适配器，写法可作为接其他系统的参照。

## 状态

适配器用录制的请求和响应形状做了测试（`app/tests/test_odoo_adapter.py`，两种协议各一遍）。**还没有连过真实的 Odoo 实例。** 上线前至少要在目标版本上跑通一次只读拉取，核对下面的字段名。

## 两种协议

| 协议 | 适用版本 | 调用方式 | 鉴权 |
| --- | --- | --- | --- |
| JSON-2 | 19 及以后 | `POST /json/2/<model>/<method>`，参数全部具名 | API key 作为 bearer token |
| JSON-RPC | 18 及以前（19 起弃用） | `POST /jsonrpc`，`execute_kw` 位置参数 | 数据库、登录名、API key |

`OdooClient(protocol="json2" | "jsonrpc")` 屏蔽差异，适配器不关心走哪条。

## 对象映射

| Odoo 模型 | 标准对象 | 说明 |
| --- | --- | --- |
| `mrp.production` | 工单 | 只读 `confirmed`、`progress`、`to_close`。没有截止日期的制造单不读入，因为无法判断交付风险 |
| `mrp.workorder` | 工序 | 编号为 `<制造单号>/<工单行 id>`；前序取 `blocked_by_workorder_ids`，老版本没有该字段时按 `sequence` 串成链 |
| `mrp.workcenter` | 设备 | 编号取 `code`，没有 `code` 时为 `WC-<id>`；`alternative_workcenter_ids` 成为工序的可选设备 |
| `stock.move`（原料移动） | 工序物料需求 | 数量和消耗工序都直接取自移动行；没有指定工序的，在首道工序领料 |
| `stock.quant` | 库存 | 只取内部库位，`reserved_quantity` 记为已分配 |
| `purchase.order.line` | 在途 | 只取已确认订单，数量为未收货部分 |
| `mrp.bom.line` | BOM | 只取定义在产品变体上的 BOM |

Odoo 的时间是不带时区的 UTC 字符串，空值是 `False`，多对一字段是 `[id, 显示名]`。这三点在适配器里统一处理。

## 版本差异

计划时间字段在 17 版改过名。默认值按 17 及以后，其他版本用 `OdooFieldNames` 覆盖：

```python
from app.adapters.odoo_adapter import OdooAdapter, OdooClient, OdooFieldNames

client = OdooClient(
    "https://erp.example.com", database="prod",
    login="planner", api_key="...", protocol="jsonrpc",
)
adapter = OdooAdapter(
    client,
    fields=OdooFieldNames(
        workorder_start="date_planned_start",
        workorder_finish="date_planned_finished",
        workorder_predecessors=None,
    ),
)
```

## 写回

写回只发生在方案经人工确认之后，并且只写三样：工序的计划开始、计划结束、工作中心。

- 默认 `allow_writeback=False`。此时调用返回 `dry_run`，把将要发送的内容原样列出，什么都不发。
- 指令里只要有一个工序编号不是本适配器发出的，整个方案在写任何东西之前被拒绝。
- 中途失败返回 `partial`，并列出已写入的行，便于人工核对和补偿。Odoo 的 `write` 没有幂等键，重试前必须先核对。

## 与闭环的衔接

```python
schedule = await adapter.fetch_current_schedule(workshop_id="PLANT-1")
supply = await adapter.fetch_supply_snapshot(schedule)
```

两个快照分别交给 `POST /api/v1/schedule-snapshots` 和 `POST /api/v1/supply/snapshots`，之后的影响分析、齐套检查、求解和确认与 CSV 数据走同一条链路。Odoo 的制造模型里没有异常事件源，异常仍由 MES、IoT 或人工录入。
