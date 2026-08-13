# V0.2 数据规范

所有回放记录使用 UTF-8 CSV，按 `timestamp` 严格升序。统一字段如下：

| 字段 | 类型/单位 | 约束 |
|---|---|---|
| timestamp | ISO 8601 | 必填，建议带时区 |
| latitude / longitude | degree | 必填，有效经纬度 |
| Hs | m | 可空，非负 |
| Tp | s | 可空，非负 |
| wave_direction | degree | 可空，[0, 360) |
| wind_speed | m/s | 可空，非负 |
| wind_direction | degree | 可空，[0, 360) |
| surface_current_speed | m/s | 可空，非负 |
| surface_current_direction | degree | 可空，[0, 360) |
| SOG | m/s | 可空，非负 |
| COG / HDG | degree | 可空，[0, 360) |
| roll | degree | 可空，-180–180 |
| pitch | degree | 可空，-90–90 |
| roll_rate | degree/s | 可空，有限数值 |
| battery | percent | 可空，0–100 |
| mission_state | enum | 任务状态枚举 |
| data_label | text | 必填；示例必须为 `SIMULATED / DEMO ONLY` |

空传感器值读取为 `None`；格式错误、越界数值、缺少必填字段和乱序时间戳均拒绝。样例数据完全为演示构造，不是庄河实验数据，也不得用于证明实艇性能。

## 方向约定

所有方位角采用真北顺时针方位：`0° = North`，`90° = East`，有效范围 `[0, 360)`。环境方向按其传播/流动“去向”定义。相对环境角是环境去向与船首向 `HDG` 的最小夹角，范围 `[0, 180]`：`0°` 表示顺浪/顺风，`90°` 表示横浪/横风，`180°` 表示迎浪/迎风。
