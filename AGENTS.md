# 寒海风巡开发约束

- 不允许编造实验数据或缺失的船型参数。
- 不允许把仿真、回放或算法输出描述为实测结果。
- 不允许自行修改 README 或经确认的项目核心技术指标。
- 不允许默认向真实无人艇发送推进器、舵机或其他控制指令。
- SAC 模块在 V0 阶段仅允许用于仿真，不得接入真实闭环。
- 所有真实控制接口必须默认为 `read-only` 或 `disabled`。
- 代码优先保证可测试、可解释、模块化，并保持算法、UI、数据读取和 ROS 适配解耦。
- 示例数据必须显著标注 `SIMULATED / DEMO ONLY`，不得声称来自庄河实测。
- 公共数据必须记录产品、文件来源与质量标记；未实际下载或验证的文件不得写成已获得。
- 所有 baseline 经验权重必须标注 `PRELIMINARY / NEEDS CALIBRATION`，不得称为训练结果。
- 未知船体参数必须保持 `null`，任何算法不得以默认常数替代真实辨识结果。
- `PUBLIC_PRODUCT_FILE` 只表示公共产品文件通过 schema/单位校验，不得表述为现场观测或庄河实测。
- `data/raw/` 与 `data/processed/` 不进入 Git；派生产物必须配套记录产品 ID 和输入 SHA-256。
- 不得把 nearest-neighbor 字段组装描述为最终“多源融合”；超出采样容差必须返回空值并保留拒绝 provenance。
- 工程估计动力学只能标记为 `ENGINEERING_ESTIMATE / NOT_EXPERIMENTALLY_CALIBRATED`，不得称为厂家、实测或水池试验参数。
- 禁止读取、输出、记录或提交 CDS/Copernicus Marine 的账号、密码、token、API key 或 credential 文件；manifest 只允许记录非敏感产品与文件 provenance。
- 历史回放的动作选择必须因果：决策时刻 `t` 不得读取 `t` 之后的环境；未来历史值只允许用于 outcome evaluation。Oracle 后视实验必须标记为不可运行上限，不能进入商业指标。
- 任务动作不等于任务结果；只有包含出航、到站、模拟巡检服务、返航并最终进入 `MissionState.COMPLETED` 的完整时间线才可计为完成。
- 厂家 `>=4 h` 只能描述为最低公开工作时间参考，不是最大续航。超过该参考的模拟任务必须标记续航可行性未验证。
- 商业指标必须由确定性完整任务回放计算 counts 和 rates；不得用开发 smoke test、硬编码风险暴露或未完成的 HOLD 任务声称任务已保住。
- 动态回放的局部航向建议只有形成并执行 `SIMULATED MISSION MANEUVER` 轨迹后才能计入结果；否则必须保持 `ADVISORY_ONLY`。
- 原地 HOLD 必须先做未知艏向敏感性安全评估；等待位置 residual high 时禁止 HOLD，不能假设等待自动降低风险。
- 技术模拟完成与证据合格完成必须分开统计；`ENDURANCE_FEASIBILITY_UNVERIFIED` 不得进入 evidence-qualified completion 或 MISSION_SAVED。
- `REPLAY_INTEGRITY_GATE=PASS` 不等于商业价值成立；当没有安全非劣的证据合格完成增益时，`BUSINESS_VALUE_STATUS` 必须保持 `NOT_ESTABLISHED`。

