# 机器生成产物规则

V0.9.1 盘点基线：tracked 文件共约 3.22 MB、70,934 行。以下完整回放均可由现有脚本确定性重建，因此停止长期跟踪：

| 原 tracked 文件 | 大小 | 行数 | 复现脚本 | 新位置 |
|---|---:|---:|---|---|
| `data/results/v0.7_causal_mission_replay.json` | 229,319 B | 5,161 | `tools/build_v07_causal_mission_replay.py` | `data/generated/` |
| `data/results/v0.8_dynamic_mission_replay.json` | 893,722 B | 22,483 | `tools/build_v08_dynamic_mission_replay.py` | `data/generated/` |
| `data/results/v0.9_dynamic_mission_evidence.json` | 1,359,979 B | 29,661 | `tools/build_v09_dynamic_evidence.py` | `data/generated/` |

合计停止跟踪 2,483,020 B、57,305 行。按 Git blob/index 精确统计，计入新 summary、冻结/交接/产物规则文档及其他本轮文本变化后，仓库 tracked 净减少 2,466,287 B、56,965 行（由 3,159,401 B 降至 693,114 B；本轮 diff 新增 428 行、删除 57,393 行）。文件仍可在本机 ignored `data/generated/` 中保留或重建；没有删除唯一不可复现的人工文件。

## Git 长期保留规则

Git 中只长期保留：compact summary、selection rule、configuration、reproduction command、provenance/checksum 和关键代表 case。V0.9 对应文件是 `data/results/v0.9_summary.json`、`configs/v0.9_dynamic_replay.yaml`、`tools/build_v09_dynamic_evidence.py` 与冻结/交接文档。

V0.3–V0.6 JSON 各自小于 50 KB，包含阶段性代表 case 与安全/真实性标签，暂时保留。原始公共数据、处理 CSV、缓存、临时输出和完整逐场景结果分别由 `data/raw/`、`data/processed/`、Python/pytest 规则、`.test-tmp/`、`data/generated/` 忽略。

## 复现顺序

```powershell
python tools/build_v07_causal_mission_replay.py
python tools/build_v08_dynamic_mission_replay.py
python tools/build_v09_dynamic_evidence.py
```

仅从已有 ignored V0.9 全量结果刷新摘要：

```powershell
python tools/build_v09_dynamic_evidence.py --compact-only
```
