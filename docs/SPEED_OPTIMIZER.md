# 航速优化接口

## 已实现

`core/speed_optimizer/pareto.py` 定义候选航速、`safety_cost`、`time_cost`、`energy_cost` 和能耗模型状态，只是 Pareto 数据契约和候选评价接口，不是最终多目标优化技术。

## Unavailable / requires real data

当前没有 ZLUSV-200 真实“航速—功率—海况”曲线。未提供能耗函数时 `energy_cost=None`、状态为 `unavailable`；调用方显式提供的临时函数统一标记 `DEMO ONLY`，不得描述为真实能耗模型。

## Planned

获得实测推进功率与任务数据后再建立经验证的能耗模型、非支配排序和操作约束。

