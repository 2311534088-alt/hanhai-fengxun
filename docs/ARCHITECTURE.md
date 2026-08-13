# V0.9 确定性决策核心架构

依赖方向为 `apps -> core <- adapters`：

- `core/` 仅包含领域模型、导航工具、任务逻辑和算法接口，不依赖 PySide6、ROS、CSV 或具体数据产品；
- `adapters/` 负责 CSV、公共数据产品和硬件边界的转换；
- `apps/` 负责交互、展示和依赖组装，当前为命令行 Demo 骨架。

## 已实现

- `core/models.py`：统一船态遥测模型及边界校验；
- `core/marine`：与数据源无关的海洋环境模型；
- `core/navigation`：方位角归一化及相对环境角；
- `core/risk`：无学习框架、可解释、待标定的规则 baseline；
- `core/mission`：显式任务状态机、因果完整任务回放、返航安全决策、当前快照路线筛选和 30 分钟短视域候选 rollout；
- `core/resonance`：配置驱动的遭遇频率、共振接近度和规避候选，参数来源优先级为实测、工程估计、不可用；
- `core/roll_response`：低保真横摇响应代理与工程参数不确定性扫描；
- `core/speed_optimizer`：Pareto 候选评价契约；真实能耗模型缺失时返回 unavailable；
- `adapters/replay`：只读 CSV 时间序列；
- `adapters/marine_data`：ERA5、WAVERYS、GLORYS、GEBCO 真实本地 NetCDF/CSV Adapter、区域/冬季裁剪、标准 CSV 与来源清单 pipeline；
- `adapters/ros_zlusv200`：`read-only` 且 `disabled`，任何写控制调用都会失败。

## 数据与证据

已实际接入并校验 ERA5 风、Copernicus WAVERYS 波浪、Copernicus GLORYS 表层流和 GEBCO 水深。本地原始数据位于 Git 忽略的 `data/raw/`；公共产品不等于庄河现场观测。完整回放明细输出到 Git 忽略的 `data/generated/`，tracked 结果只保留紧凑摘要、选择规则、配置、provenance/checksum 和关键代表 case。

## Baseline / planned / requires real evidence

风险权重、归一化常数和共振比例阈值均为 `PRELIMINARY / NEEDS CALIBRATION`，不是训练值或经认证安全阈值。横摇动力学仅为 `ENGINEERING_ESTIMATE / NOT_EXPERIMENTALLY_CALIBRATED`；任务船态和航线为模拟输入；能源可行性未验证。当前是冻结的 deterministic decision core，SAC/强化学习、最终 GUI 和真实控制均未实现。正式参数辨识、真实 speed-power/续航测试、真实航线与实艇验证属于后续证据工作。
