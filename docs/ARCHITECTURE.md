# V0.2 架构

依赖方向为 `apps -> core <- adapters`：

- `core/` 仅包含领域模型、导航工具、任务逻辑和算法接口，不依赖 PySide6、ROS、CSV 或具体数据产品；
- `adapters/` 负责 CSV、公共数据产品和硬件边界的转换；
- `apps/` 负责交互、展示和依赖组装，当前为命令行 Demo 骨架。

## 已实现

- `core/models.py`：统一船态遥测模型及边界校验；
- `core/marine`：与数据源无关的海洋环境模型；
- `core/navigation`：方位角归一化及相对环境角；
- `core/risk`：无学习框架、可解释、待标定的规则 baseline；
- `core/mission`：显式任务状态机和允许空值的任务统计契约；
- `core/resonance`：遭遇频率及共振评估物理接口；未知固有周期时返回 unavailable；
- `core/speed_optimizer`：Pareto 候选评价契约；真实能耗模型缺失时返回 unavailable；
- `adapters/replay`：只读 CSV 时间序列；
- `adapters/marine_data`：ERA5、WAVERYS、GLORYS、GEBCO 真实本地 NetCDF/CSV Adapter、区域/冬季裁剪、标准 CSV 与来源清单 pipeline；
- `adapters/ros_zlusv200`：`read-only` 且 `disabled`，任何写控制调用都会失败。

## Baseline / planned / requires real data

风险权重和归一化常数是 `PRELIMINARY / NEEDS CALIBRATION`，不是训练值或安全阈值。NetCDF pipeline 已实现，但仓库不捆绑真实公共数据文件；共振参数辨识、正式 Pareto 非支配优化、PySide6 海事 UI、SAC 训练和 ROS 实时数据均为后续工作。真实推进器/舵机控制不在当前架构中。
