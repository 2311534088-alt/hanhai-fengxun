# 共振物理接口

## 已实现

`core/resonance/physics.py` 提供遭遇频率、横摇固有频率、共振裕度和横摇放大指标接口。遭遇频率目前采用明确标注的深水近似，为后续物理层接口，不是完成的共振预测模型。

## Unavailable / requires real data

ZLUSV-200 的横摇固有周期、GM、横摇阻尼和横摇惯量未知。固有周期为空时，`natural_roll_frequency`、`resonance_margin` 返回 `None`，状态为 `unavailable`；绝不自动猜测。

## Planned

受控试验辨识参数后验证物理模型；SAC 仍仅允许仿真，当前未实现训练且未连接真艇。

