# 寒海风巡 CODEX Handoff

新线程先读 `AGENTS.md`，再读本文；不要依赖旧聊天。

## 项目定位与当前基线

“寒海风巡”是面向东北寒海风电运维场景的无人艇抗浪决策系统。它为既有巡检无人艇提供航行风险、共振敏感性和任务连续性建议，不负责风机缺陷检测，也不直接控制真实推进器或舵机。

- branch：`codex/v0.1-init`
- V0.9 core freeze commit：`772ec55982eac96eec26b85d5d9a335f4d1127c2`
- 核心形态：`deterministic decision core`
- 冻结结果：`BUSINESS_VALUE_STATUS=NOT_ESTABLISHED`，`mission_saved_count=0`
- 冻结测试：133 项通过

## 核心架构

依赖方向保持 `apps -> core <- adapters`：

- `core/risk`：可解释、待标定的单船风险 baseline；
- `core/resonance` + `core/roll_response`：遭遇频率、共振接近度、低保真横摇响应与参数不确定性；
- `core/mission`：因果完整任务回放、返航安全决策、当前快照路线筛选、30 分钟候选 rollout、双 cohort 证据门；
- `adapters/marine_data`：ERA5/WAVERYS/GLORYS/GEBCO NetCDF pipeline、容差采样与逐字段 provenance；
- `adapters/ros_zlusv200`：只读且 disabled；
- `apps/desktop`：目前仅 CLI 骨架，不是最终 GUI。

三大核心技术模块是：可解释多源环境/船态风险评估；波浪遭遇与横摇响应感知规避；因果任务级安全与连续性决策。

## 数据、结果与复现

已验证的真实公共环境源：ERA5 风、Copernicus WAVERYS 波浪、Copernicus GLORYS 表层流、GEBCO 水深。它们不是庄河现场观测。原始文件位于 ignored `data/raw/`。

tracked 机器结果只保留 `data/results/v0.9_summary.json` 和较小的阶段/代表证据。V0.7–V0.9 完整场景明细输出到 ignored `data/generated/`：

```powershell
python tools/build_v07_causal_mission_replay.py
python tools/build_v08_dynamic_mission_replay.py
python tools/build_v09_dynamic_evidence.py
```

V0.9 summary 保留两个 cohort、三策略核心指标、选择规则、provenance/checksum、复现命令和 2026-02-05 代表 case。

## 真实性标签与禁止口径

- 环境：`REAL PUBLIC ENVIRONMENT DATA - NOT IN-SITU ZHUANGHE OBSERVATION`
- 船态/任务几何：`SIMULATED VESSEL STATE`
- 动力学：`ENGINEERING_ESTIMATE / NOT_EXPERIMENTALLY_CALIBRATED`
- 能源：`NOT VERIFIED ENERGY FEASIBILITY`
- 结果：`MODEL-BASED HISTORICAL REPLAY - NOT OPERATIONAL PERFORMANCE`

不得声称 SAC 已完成，不得把 nearest-neighbor 字段组装称为最终多源融合，不得把公共再分析/模式数据称为现场实测，不得把时长参考兼容称为能源可行，不得把 `REPLAY_INTEGRITY_GATE=PASS` 写成商业价值成立。

## 真实证据缺口

仍需水池/实艇 IMU 横摇响应、真实 speed-power 曲线、任务载荷续航测试、真实母港/风机/航道任务几何。详见 `docs/EVIDENCE_BLOCKERS.md`。这些缺口不能靠更多仿真代码消除。

## 下一阶段 V1.0 产品软件

V1.0 应以冻结核心为稳定库，重点做产品软件而非改指标：配置/数据导入、任务规划工作流、可解释决策展示、回放与审计、错误与数据质量提示、只读设备集成、发布打包。任何算法变更必须单独版本化，并与 V0.9 冻结结果回归比较；SAC、真实闭环控制和最终安全声明均不属于默认范围。
