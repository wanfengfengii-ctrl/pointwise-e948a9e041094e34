# 复检交班事故

日样例中，0 微米的 A 可供 U、V，7 微米的 B 只可供 U，M 缺测。X 申请两格，完整归属为 U←B、V←A。Y 只申请 V←A。接口参数、结果格式和检查点见 README.md。

- 先签发再丢回包。在 `after_commit` 观察到 X 可领，然后中断回复。重开后撤办 X 并提交 Y。故障版两份正式报告都能领到 A。正确结果是撤办返回 `already_signed`，Y 返回 `not_enough`，X 的原报告和首执可按原号领取，交班账确认核销两份凭据。
- 撤办先成。X 在 `after_prepare` 暂停，撤办 X 并签出 Y，然后让原签发继续。故障版重开仍能领到 X。正确结果是 X 返回 `cancelled` 且无正式明细和首执，Y 保持 V←A，交班账只核销一份凭据。

在工程根目录运行 `python3 -B incident.py`。故障版分别报告 `EVIDENCE_DOUBLE_SPENT` 和 `STALE_REPORT_AFTER_WITHDRAWAL`，附两张实际领取报告的格位归属及首执编号。修复后命令应通过。`.pointwise-runtime.json` 中的 `verify` 和 `demo` 仍用于运行完整回归与日样例。
