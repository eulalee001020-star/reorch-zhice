# Odoo 实例联调、规划快照持久化与参数校准

## 已验证范围

真实 Odoo 18 Community JSON-RPC：制造工单、工序/工作中心、BOM、库存、在途采购和工序物料需求；改期写回后读回日期，并在测试结束时恢复；默认 writeback 禁用时确认远端未变。

本地验证使用 Odoo 源码 `4adf9ebea1f39dc2d42461e1a92f55cb5b64f3e8`、Python 3.12、PostgreSQL 16.14。制造/采购/库存数据由 `tools/odoo_sandbox_seed.py` 创建，全部是合成测试数据。未连接客户数据库。Odoo 19 JSON-2 仍仅有协议 fixture 测试，不能据此声称通过 Odoo 19 实例验收。

## 容器复现（GitHub Actions 同样执行）

```sh
docker compose -f compose.odoo-test.yml up -d --wait --wait-timeout 240
docker compose -f compose.odoo-test.yml exec -T odoo odoo shell \
  --db_host=db --db_port=5432 --db_user=odoo --db_password=odoo-test \
  -d reorch_odoo_test --no-http < tools/odoo_sandbox_seed.py
docker compose -f compose.odoo-test.yml exec -T db createdb -U odoo reorch_runtime_test
ODOO_TEST_URL=http://127.0.0.1:18069 \
ODOO_TEST_DATABASE=reorch_odoo_test ODOO_TEST_LOGIN=reorch-test \
ODOO_TEST_PASSWORD=odoo-sandbox-only \
PLANNING_TEST_DATABASE_URL=postgresql+psycopg2://odoo:odoo-test@127.0.0.1:55432/reorch_runtime_test \
pytest -q app/tests/integration
docker compose -f compose.odoo-test.yml down -v
```

这些口令只用于此隔离测试栈，端口绑定到本机。种子脚本和 PostgreSQL 测试均检查专用数据库名，避免误写其他数据库。没有实例环境变量时，真实联调测试会明确跳过。

## 持久化

供应链和配送快照在 API 确认导入前提交到现有 operational store；SQLite 开发环境和 PostgreSQL 部署均可使用。读取以数据库为准，进程重启后无需重新导入，也不会被另一 worker 的旧缓存覆盖。数据库失败不会返回导入成功。

同一类型/快照 ID 内容相同的重复导入幂等；不同内容返回 409；重复提交旧快照不会改变最新快照。保留历史导入，序列决定当前快照。数据库事务和唯一约束处理并发导入。新增 Alembic 005，并把快照纳入现有备份恢复；PostgreSQL 恢复后重置自增序列，保证可继续导入。

配置沿用 `RUNTIME_DATABASE_URL` / `RUNTIME_LOCAL_DATABASE_PATH`，生产环境默认使用既有 PostgreSQL 配置。生产数据库按部署流程运行 `alembic upgrade head`。

## 参数校准

```sh
python -m app.services.validation.parameter_calibration \
  data/calibration/test_observations.json --output output/calibration.json
```

输入明确给出来源、行驶时间训练/留出样本、同币种成本单价和供应商延迟训练/留出样本。行驶速度用过原点最小二乘拟合，迟到/加班/车辆/未送达罚值由成本单价除以每公里成本得到，不能从路线表现反推经营偏好。输出含输入 SHA256、留出误差、供应商 P80 缓冲覆盖率及 0.5/1/2 倍罚值对照。

`dispatch_parameters` 中的 `speed_kmh` 和 `cost_weights` 可合入新的配送快照，随快照持久化并实际进入求解器。未指定罚值时保留原默认值。

测试数据结果：30 km/h，留出 MAE 1 分钟；罚值分别为 10、3、60、6000 公里等价单位。供应商训练 P80 为 90 分钟，留出覆盖仅 60%，没有达到 80% 的目标，不能当作已通过的供应商保障参数。小样本仅验证流程，不自动提升为业务配置。供应商评分权重/SLA 需真实业务标签和成本依据，保持原默认策略。
