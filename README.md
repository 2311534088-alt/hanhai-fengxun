# 寒海风巡

**面向东北寒海风电运维场景的无人艇智能抗浪决策系统**

本仓库用于开发“寒海风巡”真实可运行软件原型。

项目面向现有风电巡检无人艇，通过智能决策软件增强寒海环境下的航行能力，重点解决：

1. 单船风险判断不准；
2. 横摇共振难以及时规避；
3. 航速决策难以兼顾安全、效率与能耗。

## 当前版本：V0.9 deterministic decision core（冻结基线）

当前已实现：

- 因果、确定性的完整任务历史回放；
- 统一船态与海洋环境数据模型；
- 本地 CSV 历史/模拟任务回放；
- 使用浪、风、流、船态及已知船型尺度的可解释规则型风险 baseline；
- ERA5、Copernicus WAVERYS/GLORYS、GEBCO 真实本地 NetCDF pipeline；
- 波浪遭遇频率、共振接近度、低保真横摇响应与参数不确定性扫描；
- 容差受控的多数据源时空采样与逐字段 provenance；
- 与真实参数隔离的 ZLUSV-200 横摇动力学 `ENGINEERING_ESTIMATE`；
- 返航安全决策、当前快照路线筛选与 30 分钟短视域候选 rollout；
- 双 cohort 冬季证据与紧凑 V0.9 结果；
- 命令行 Demo 和 133 项测试。

仍属 planned / requires real evidence：

- SAC / 强化学习（尚未实现，不属于当前核心）；
- 真实 speed-power / endurance 模型；
- 实测横摇传递增益和真实巡检航线；
- ZLUSV-200 ROS实时数据接口。

当前核心是 `deterministic decision core`，不是最终“多源海况注意力融合算法”，也不是 SAC。所有经验权重均为 `PRELIMINARY / NEEDS CALIBRATION`。已接入并验证 ERA5、Copernicus WAVERYS、Copernicus GLORYS 和 GEBCO 公共产品；真实文件仅保存在 Git 忽略的 `data/raw/`，仓库不内置原始数据。公共再分析/模式/地形文件标记为 `PUBLIC_PRODUCT_FILE`，不等于庄河现场实测；船态和任务几何仍为 `SIMULATED VESSEL STATE`。V0.9 当前 `BUSINESS_VALUE_STATUS=NOT_ESTABLISHED`、`mission_saved_count=0`，不得为展示而修改。

## 软件架构

```text
hanhai-fengxun/
├── apps/desktop/              # 桌面交互入口（当前为 CLI 骨架）
├── core/
│   ├── risk/                  # 多源单船风险评估
│   ├── marine/                # 统一环境数据模型
│   ├── resonance/             # 确定性共振接近度与规避候选
│   ├── roll_response/         # 低保真横摇响应与不确定性扫描
│   ├── speed_optimizer/       # Pareto 候选接口，非最终优化器
│   └── mission/               # 因果完整任务、返航和路线决策
├── adapters/
│   ├── replay/                # 历史数据回放
│   ├── marine_data/           # ERA5/Copernicus数据
│   └── ros_zlusv200/          # 只读/禁用的无人艇边界
├── configs/
├── data/samples/
├── data/results/              # tracked 紧凑摘要/代表证据
├── data/generated/            # ignored、可确定性重建的完整明细
├── tests/
└── docs/
```

## 产品边界

寒海风巡不负责风机缺陷检测，而是为现有巡检无人艇提供航行决策增强能力，提升复杂海况下任务可达性、连续性和返航可靠性。

## 安全原则

在完成仿真、回放、实验验证和实艇测试前，算法默认只输出决策建议，不直接控制真实无人艇推进器和舵机。

新开发线程应先阅读 `AGENTS.md` 和 `docs/CODEX_HANDOFF.md`。V0.9 冻结说明见 `docs/V0.9_CORE_FREEZE.md`，紧凑结果见 `data/results/v0.9_summary.json`。

运行：

```powershell
python -m unittest discover -v
python -m apps.desktop.main
```
