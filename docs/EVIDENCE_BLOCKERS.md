# 关键真实证据缺口

以下缺口不能通过增加仿真代码消除。V0.9 的所有结果仍是历史公共环境驱动的模型回放，不是运营性能或商业价值实证。

| 缺口 | 当前状态 | 必需证据 | 不允许的替代口径 |
|---|---|---|---|
| 横摇传递增益 / 真实横摇响应 | `ENGINEERING_ESTIMATE / NOT_EXPERIMENTALLY_CALIBRATED` | 水池试验或实艇 IMU 同步波浪/姿态数据 | 不得把低保真横摇代理称为实测横摇角 |
| 航速—功率曲线 | `UNAVAILABLE` | 实艇分级航速、推进功率、电流/电压测试 | 不得由任务时间或绕航距离反推真实能耗 |
| 任务载荷下真实续航 | 仅有厂家 `>=4 h` 最低公开工作时间参考 | 电池、电流、载荷、海况和完整任务联合测试 | 不得把“参考时间内完成”称为能源可行 |
| 实际巡检航线几何 | `UNAVAILABLE` | 真实风机、母港、禁航区、航道与任务点数据 | 不得把三类模拟几何称为庄河实际航线 |

在以上证据取得前，统一使用：

- `duration_reference_compatible_completion`：仅表示任务时长处于已发布最低工作时间参考内；
- `NOT VERIFIED ENERGY FEASIBILITY`：明确能源可行性未验证；
- `REAL PUBLIC ENVIRONMENT DATA` + `SIMULATED VESSEL STATE`；
- `MODEL-BASED HISTORICAL REPLAY - NOT OPERATIONAL PERFORMANCE`。
