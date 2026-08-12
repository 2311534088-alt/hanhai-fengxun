# 寒海风巡

**面向东北寒海风电运维场景的无人艇智能抗浪决策系统**

本仓库用于开发“寒海风巡”真实可运行软件原型。

项目面向现有风电巡检无人艇，通过智能决策软件增强寒海环境下的航行能力，重点解决：

1. 单船风险判断不准；
2. 横摇共振难以及时规避；
3. 航速决策难以兼顾安全、效率与能耗。

## 当前版本：V0.2 baseline

当前已实现：

- 历史/模拟任务回放；
- 统一船态与海洋环境数据模型；
- 本地 CSV 历史/模拟任务回放；
- 使用浪、风、流、船态及已知船型尺度的可解释规则型风险 baseline；
- ERA5、Copernicus WAVERYS/GLORYS、GEBCO 真实本地 NetCDF pipeline；
- 共振物理接口与 Pareto 候选接口；
- 容差受控的多数据源时空采样与逐字段 provenance；
- 与真实参数隔离的 ZLUSV-200 横摇动力学 `ENGINEERING_ESTIMATE`；
- 命令行 Demo 和基础测试。

仍属 planned / requires real data：

- 物理嵌入SAC横摇共振规避；
- Pareto多目标航速优化；
- ZLUSV-200 ROS实时数据接口。

当前 baseline 不是最终“多源海况注意力融合算法”，所有经验权重均为 `PRELIMINARY / NEEDS CALIBRATION`。仓库没有内置任何庄河真实公共数据文件；用户提供的公共再分析/模式/地形文件会被标记为 `PUBLIC_PRODUCT_FILE`，不等于庄河现场实测。示例任务全部为 `SIMULATED / DEMO ONLY`。

## 软件架构

```text
hanhai-fengxun/
├── apps/desktop/              # 桌面交互入口（当前为 CLI 骨架）
├── core/
│   ├── risk/                  # 多源单船风险评估
│   ├── marine/                # 统一环境数据模型
│   ├── resonance/             # 共振物理接口，尚未训练 SAC
│   ├── speed_optimizer/       # Pareto 候选接口，非最终优化器
│   └── mission/               # 巡检任务逻辑
├── adapters/
│   ├── replay/                # 历史数据回放
│   ├── marine_data/           # ERA5/Copernicus数据
│   └── ros_zlusv200/          # 只读/禁用的无人艇边界
├── configs/
├── data/samples/
├── tests/
└── docs/
```

## 产品边界

寒海风巡不负责风机缺陷检测，而是为现有巡检无人艇提供航行决策增强能力，提升复杂海况下任务可达性、连续性和返航可靠性。

## 安全原则

在完成仿真、回放、实验验证和实艇测试前，算法默认只输出决策建议，不直接控制真实无人艇推进器和舵机。

运行：

```powershell
python -m unittest discover -v
python -m apps.desktop.main
```
