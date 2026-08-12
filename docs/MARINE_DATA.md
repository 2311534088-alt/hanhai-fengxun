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

## V0.3 Commit 1：真实公共产品文件 pipeline

已实现本地 NetCDF 读取链：

| 数据产品 | 必需变量 | 单位检查 | 项目转换 |
|---|---|---|---|
| ERA5 | `u10`, `v10` | m/s | 东/北分量计算风速和吹向 |
| Copernicus WAVERYS | `VHM0`, `VTPK`, `VMDR` | m, s, degree | `VMDR` 来向加 180° 转为传播去向 |
| Copernicus GLORYS | `uo`, `vo` | m/s | 选择最浅深度层，计算表层流速与去向 |
| GEBCO | `elevation` | m | 只保留负海拔并转换为正水深；陆地排除 |

所有动态产品仅保留 `configs/zhuanghe.yaml` 项目裁剪框内、11 月至次年 3 月的记录。GEBCO 是静态背景，使用动态数据的最早时间戳进入统一模型。

安装可选依赖：

```powershell
python -m pip install -e ".[marine]"
```

把用户自行获取的原始文件放在 `data/raw/`（该目录已被 Git 忽略），然后运行：

```powershell
python -m adapters.marine_data.pipeline `
  --era5 data/raw/era5.nc `
  --era5-product-id reanalysis-era5-single-levels `
  --waverys data/raw/waverys.nc `
  --waverys-product-id GLOBAL_ANALYSISFORECAST_WAV_001_027 `
  --glorys data/raw/glorys.nc `
  --glorys-product-id YOUR_CONFIRMED_GLORYS_PRODUCT_ID `
  --gebco data/raw/gebco.nc `
  --gebco-product-id YOUR_CONFIRMED_GEBCO_RELEASE `
  --output data/processed/marine_environment.csv `
  --manifest data/processed/provenance.json
```

必须用下载时确认的真实产品 ID 替换占位符。pipeline 输出：

- `marine_environment.csv`：标准 `MarineEnvironment` 长表；
- `provenance.json`：输入文件名、产品 ID、SHA-256、记录数、裁剪区域和方向约定。

`PUBLIC_PRODUCT_FILE` 表示公共再分析/数值模式/地形产品的本地文件通过了项目 schema 与单位校验；它不表示现场观测、庄河实测或实验数据。pipeline 不包含下载凭据或写死的网络请求，也不会把真实数据文件提交到仓库。

## Planned / requires real files

- 用户提供实际下载且可追溯的 ERA5、WAVERYS、GLORYS、GEBCO 文件；
- 按下载产品的 PUM/QUID 再确认产品 ID、时间分辨率、坐标系、缺测值和许可；
- Commit 1 之后再考虑时空插值、四源同点合并和数据库存储。
