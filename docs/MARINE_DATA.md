# 海洋环境数据

## 已实现

`MarineEnvironment` 统一表示时间、位置、`Hs`、`Tp`、波向、风速/风向、表层流速/流向、水深、数据来源和质量标记。缺失变量保持 `None`，Adapter 不填充猜测值。

| 变量 | 单位 | 方向/缺失规则 |
|---|---|---|
| timestamp | ISO 8601 | 必填，建议带时区 |
| latitude / longitude | degree | 必填，WGS84 位置语义由来源元数据确认 |
| Hs | m | 可空，非负 |
| Tp | s | 可空，非负 |
| wave_direction | degree | 可空，统一为传播去向 `[0, 360)` |
| wind_speed | m/s | 可空，非负 |
| wind_direction | degree | 可空，统一为吹向 `[0, 360)` |
| surface_current_speed | m/s | 可空，非负 |
| surface_current_direction | degree | 可空，流动去向 `[0, 360)` |
| water_depth | m | 可空，使用非负深度幅值；GEBCO 高程转换尚待确认 |
| source | text | 必填，记录产品/文件来源 |
| quality_flag | enum | 必填，区分 verified/provisional/missing/simulated |

本地 CSV Adapter 骨架：

- ERA5：风速、风向；
- Copernicus WAVERYS：`Hs`、`Tp`、波向；
- Copernicus GLORYS：表层海流；
- GEBCO：水深背景。

输入方向必须转换为项目统一的“去向”方位角：真北为 `0°`、正东为 `90°`、范围 `[0, 360)`。各数据源原生方向语义可能不同，正式映射前必须核对产品元数据。

## 当前数据状态

仓库没有下载、内置或声称拥有任何庄河真实公共数据。`tests/fixtures/era5_simulated.csv` 只用于 Adapter 测试，质量标记为 `SIMULATED / DEMO ONLY`。`configs/zhuanghe.yaml` 只是 `121.5–124.5°E、38.5–40.5°N` 的项目裁剪框，不是庄河行政边界；冬季配置为 11 月至次年 3 月。

## Planned / requires real data

- 核对具体产品版本、变量名、时间分辨率、方向约定和许可；
- 增加可选 NetCDF 读取依赖及变量映射；
- 下载后保存来源 URL/产品 ID、时间、校验值和质量控制结果。
