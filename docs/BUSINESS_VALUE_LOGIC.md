# 寒海风巡任务连续性与商业价值逻辑

> V0.7 修正说明：V0.6 的四任务比较仅为使用 oracle 历史后视信息的 development smoke test，不能形成商业百分比。V0.7 完整证据现由 `tools/build_v07_causal_mission_replay.py` 确定性生成到 Git 忽略的 `data/generated/`；当前冻结结论以 `data/results/v0.9_summary.json` 为准。

> V0.8 进一步将完整模拟任务与证据合格完成分开，并把 gate 拆为 `REPLAY_INTEGRITY_GATE` 与 `BUSINESS_VALUE_STATUS`。当前动态多源回放的完整证据见 `V0.8_DYNAMIC_MISSION_REPLAY.md`；`REPLAY_INTEGRITY_GATE=PASS` 不得解释为商业价值已成立。

## 目标

寒海风巡不以“绝对最低横摇”为最终目标。项目目标是在安全约束下提高有效巡检任务完成能力，降低非计划中断和不必要返航，并减少危险海况暴露。

安全优先于完成率。系统不得为了降低返航率而建议在明显不可接受的风险下继续航行，也不得把模型回放指标写成真实风场经营绩效。

## 横摇模型表达边界

当前计算链为：

`response proxy = wave slope * beam excitation factor * DAF`

真实横摇响应理论结构为：

`actual roll response = K_phi * wave slope * beam excitation factor * DAF`

`K_phi` 即 roll-transfer gain，目前为 null，状态为 `REQUIRES REAL ROLL DATA OR HYDRODYNAMIC CALIBRATION`。因此 `actual_roll_response_deg` 必须 unavailable。

V0.6 新结果使用 `roll_response_proxy` 和 `roll_response_degree_equivalent`，并标记：

- `LOW_FIDELITY_RESPONSE_PROXY`
- `NOT A CALIBRATED ROLL ANGLE PREDICTION`

历史 `estimated_roll_response_deg` 仅为 deprecated 兼容字段。29.296、19.284、13.149 等不能称为真实或预测实艇横摇角，只能用于 `MODEL-PROXY REDUCTION` 等相对比较。

## 任务动作优先级

安全约束下的动作顺序为：

1. CONTINUE
2. ADJUST_SPEED_HEADING
3. REROUTE
4. HOLD_AND_REASSESS
5. DELAY_MISSION（仅出航前）
6. RETURN（已出航、且其他方案均不可接受时）

PRE_DEPARTURE 高风险只能输出 DELAY_MISSION/等待窗口，不输出 RETURN。已出航 residual high risk 必须先检查受限局部调整、模拟绕行和历史 3–6 小时窗口。

所有结果都是 `DECISION ADVICE ONLY`，不发送推进器或舵机命令。

## 厂家上下文

ZLUSV-200 的 4 级风、3 级海况能力作为 `manufacturer_operating_context` 保留。这不是“该类别内每一种海况绝对安全”的承诺；未校准 proxy 的异常绝对值也不能单独否定厂家能力。

当总体环境不极端但 proxy 异常偏大时，输出 `MODEL_CALIBRATION_WARNING: LOW-FIDELITY RESPONSE MODEL MAY BE CONSERVATIVE / REQUIRES REAL ROLL VALIDATION`，而不是仅凭绝对 proxy 触发 RETURN。

## 历史窗口与路线

等待窗口使用 2025-11-01 至 2026-03-31 的公共历史环境序列，标记 `HISTORICAL_ENVIRONMENT_REPLAY - NOT A FORECAST`。6 小时 horizon 和 3 小时间隔属于 `PRELIMINARY MISSION POLICY PARAMETER`，不代表 forecast accuracy 或未来预测能力。

路线使用 `SIMULATED MISSION ROUTE`。第一版只比较直接路线和少量中间航点方案，计算 integrated proxy、high-risk exposure steps、距离和时间，不是 A* 自动驾驶，也不是真艇航线命令。

## Business Value Check

每个任务决策均输出 technical_outcome 和 business_outcome。任务级字段包括：

- mission_completed
- mission_interrupted
- unplanned_return
- mission_delayed
- reroute_used
- hold_used
- estimated_extra_travel_time
- high_risk_exposure_duration_or_steps

不估算人民币收益，不声称已经真实提高风场巡检完成率。

## 策略对照

`BASELINE_CONSERVATIVE_POLICY` 是项目内部仿真 baseline：持续 residual high risk 时 RETURN/ABORT；它不代表行业现有无人艇策略。

`HANHAI_MISSION_CONTINUITY_POLICY` 为 adjust → reroute → hold → return last，且安全始终优先。

V0.6 的 4 个代表性模拟任务回放结果：

| 策略 | 模拟完成率 | 模拟中断率 | 模拟非计划返航率 | 模拟延迟率 | 平均时间代价 | 风险暴露 steps |
|---|---:|---:|---:|---:|---:|---:|
| Baseline | 25% | 75% | 75% | 0% | 0 s | 3 |
| Hanhai | 75% | 25% | 25% | 25% | 3950 s | 1 |

以上全部标记 `MODEL-BASED / HISTORICAL-ENVIRONMENT REPLAY / NOT REAL WIND-FARM OPERATIONAL PERFORMANCE`，不能用于对外声称真实运营效果。

## 2026-02-05 场景

- 00:00：当前 GRID_Q90 proxy 为 33.410，受限局部动作后仍为 28.810，residual high risk。
- 历史序列 +3 h：Hs 0.69 m、Tp 3.35 s、波向 176.81°，GRID_Q90 proxy 5.516，ROBUST_NORMAL。
- 历史序列 +6 h：Hs 0.80 m、Tp 3.82 s、波向 180.22°，GRID_Q90 proxy 4.330，ROBUST_NORMAL。
- 模拟南绕行降低了 high-risk exposure，但时间代价约 122.8%，超过 35% 暂定阈值，因此不接受。

最终 preferred action 为 HOLD_AND_REASSESS：3 小时历史环境窗口显示可接受工况，优先等待而不是直接返航。该判断不是实时预报。
