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

本机 `data/raw/` 已获取 2026-02-20 四源 Smoke Test，以及 2025-11-01 至 2026-03-31 的 ERA5、WAVERYS、GLORYS 和一份静态 GEBCO_2026 区域文件。它们是 `REAL PUBLIC ENVIRONMENT DATA / PUBLIC REANALYSIS OR MODEL DATA`，不是庄河现场实测；原始文件受 `.gitignore` 保护，不进入仓库。可提交的 `data/manifests/` 只记录产品标识、变量、单位、统计、文件大小与 SHA-256，不记录凭据。

`tests/fixtures/era5_simulated.csv` 仍只用于 Adapter 测试，质量标记为 `SIMULATED / DEMO ONLY`。`configs/zhuanghe.yaml` 只是 `121.5–124.5°E、38.5–40.5°N` 的项目裁剪框，不是庄河行政边界；冬季配置为 11 月至次年 3 月。

当前已核验产品：

| 来源 | product/dataset ID | 原生变量与单位 | 方向处理 |
|---|---|---|---|
| ERA5 | `reanalysis-era5-single-levels` | `u10`, `v10`; `m s**-1` | 东/北分量计算风吹向 |
| WAVERYS | `GLOBAL_MULTIYEAR_WAV_001_032` / `cmems_mod_glo_wav_my_0.2deg_PT3H-i` | `VHM0` m, `VTPK` s, `VMDR` degree | `VMDR` 为来向，项目加 180° 转传播去向 |
| GLORYS | `GLOBAL_MULTIYEAR_PHY_001_030` / `cmems_mod_glo_phy_my_0.083deg_P1D-m` | `uo`, `vo`; `m s-1` | 0.494 m 表层东/北分量计算流去向 |
| GEBCO | `GEBCO_2026 Grid ice surface elevation` | `elevation`; m | 负 elevation 转正水深，陆地排除 |

运行 `python tools/build_real_public_data_reports.py` 可重复生成 `data/manifests/smoke_test_20260220.json` 与 `data/manifests/winter_environment_20251101_20260331.json`。该工具只读取本地已下载文件，不读取认证文件。

## V0.3 Commit 1：真实公共产品文件 pipeline

已实现本地 NetCDF 读取链：

| 数据产品 | 必需变量 | 单位检查 | 项目转换 |
|---|---|---|---|
| ERA5 | `u10`, `v10` | m/s | 东/北分量计算风速和吹向 |
| Copernicus WAVERYS | `VHM0`, `VTPK`, `VMDR` | m, s, degree | `VMDR` 来向加 180° 转为传播去向 |
| Copernicus GLORYS | `uo`, `vo` | m/s | 选择最浅深度层，计算表层流速与去向 |
| GEBCO | `elevation` | m | 只保留负海拔并转换为正水深；陆地排除 |

所有动态产品仅保留 `configs/zhuanghe.yaml` 项目裁剪框内、11 月至次年 3 月的记录。GEBCO 是静态背景，使用动态数据的最早时间戳进入统一模型。

Adapter 在调用 `to_dataframe()` 前先在 xarray Dataset 层执行空间裁剪和冬季月份筛选；GLORYS 还会先选择绝对深度最小的表层。裁剪兼容纬度升序/降序，以及 `0–360`、`-180–180` 两种经度坐标。

## MarineEnvironmentSampler

各产品网格与时间分辨率不同，因此原始记录的简单拼接不是“多源融合”。`MarineEnvironmentSampler` 接收目标 `timestamp/latitude/longitude`，按环境字段分别执行可解释的 nearest-neighbor 采样：

- 默认最大时间偏差 3 小时、最大空间距离 30 km，可显式配置；
- 水深为静态字段，不应用时间容差；
- 超过任一容差时对应值为 `null`，不静默使用远距离格点；
- `provenance_by_field` 为每个字段记录数据源、采样方法、绝对时间偏差、球面空间距离和是否通过容差；
- `Hs/Tp/wave_direction`、wind、current、depth 可分别来自 WAVERYS、ERA5、GLORYS、GEBCO。

该操作是容差受控的时空采样与字段组装，不是统计学习或项目最终“多源注意力融合”。

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
- 后续再考虑经验证的线性插值、数据库存储和批量任务轨迹采样。
