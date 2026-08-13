# 风险评估 baseline

## 已实现

V0.2 是可解释规则型 baseline，不是最终多源注意力融合算法。输入包括：

- 海况：`Hs`、`Tp`、浪向、风速、风向、表层流；
- 船态：`SOG`、`HDG`、横摇、纵摇、横摇角速度、电量；
- 船型：已知的 ZLUSV-200 全长用于波高/船长尺度化。

输出为 `risk_score`、`risk_level`、`primary_risk`、`risk_components`、`recommendation`、`data_quality` 和 `explanation`。`data_quality` 仅表示预期输入字段的可用比例，不是模型置信度。

风险分量包括 `wave_risk`、`wind_risk`、`motion_risk`、`navigation_risk`。相对浪/风角会受到对应浪高/风速强度约束，避免无风无浪时单靠方向产生风险。

## Baseline 状态

所有归一化常数、分量权重和内部项权重集中在 `configs/risk_baseline.json`，并标注 `PRELIMINARY / NEEDS CALIBRATION`。这些数值不是训练得到的、不是厂家安全限制，也未通过水池或实艇验证。

## Planned / requires real data

- 使用受控水池与实艇数据标定阈值和权重；
- 引入经验证的遭遇波频率和横摇动力学；
- 在数据充分后研发多源注意力融合模型并进行独立评估。

