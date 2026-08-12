# 共振物理接口

## 参数来源与优先级

算法只读取统一 `RollDynamicsParameters`，来源优先级为：

`MEASURED > ENGINEERING_ESTIMATE > UNAVAILABLE`

未来获得实测横摇周期后，可加载 `MEASURED` 配置并通过 `select_parameters()` 自动覆盖工程估计，无需修改共振算法。`configs/zlusv200.yaml` 中未知真实参数仍保持 `null`。

## V0.3 Commit 2 工程估计

`configs/zlusv200_estimated_dynamics.yaml` 单独保存“基于实艇尺度与低保真水动力模型的工程估计”，明确标记：

- `ENGINEERING_ESTIMATE`
- `NOT_EXPERIMENTALLY_CALIBRATED`

名义值包括：参考排水量 100.0 kg、GM 0.18 m、刚体/附加/有效横摇惯量 9.6/3.4/13.0 kg·m²、恢复刚度 176.6 N·m/rad、等效阻尼比 0.18、线性阻尼 17.2 N·m·s/rad、固有周期 1.70 s，以及固有频率 0.587 Hz / 3.69 rad/s。配置同时保留任务给定的上下界。

这些数值不是厂家参数、实测参数或水池试验结果。

## 共振输出与判据

物理层输出：

- `encounter_frequency_rad_s`
- `natural_roll_frequency_rad_s`
- `natural_roll_period_s`
- `resonance_margin_rad_s`
- `resonance_margin_ratio`
- `resonance_status`
- `parameter_source`
- `parameter_status`

其中：

`resonance_margin_ratio = abs(encounter_frequency - natural_roll_frequency) / natural_roll_frequency`

第一版判据集中在工程估计配置中，并标记 `PRELIMINARY / NEEDS CALIBRATION`：

- ratio `< 0.10`：`HIGH_RISK`
- `0.10 <= ratio < 0.20`：`WARNING`
- ratio `>= 0.20`：`NORMAL`

输入不足或参数不可用时返回 `UNAVAILABLE`，不猜测数值。

## Planned / requires real data

需要自由横摇试验、水池试验和实艇同步浪—姿态数据校准动力学参数与风险阈值。当前未训练 SAC，未连接真实无人艇，也没有自动控制指令。
