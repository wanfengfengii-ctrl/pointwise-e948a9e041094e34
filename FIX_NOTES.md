# 原测凭据重复核销修复说明

## 根因

签发与撤办各自只在自己那一侧落终局，没有一个共享的终局判定点：

- 签发在 `archive` 的 `report_deliveries` 打开交付后才算走出去，但撤办只看 `ledger` 的
  `custody_requests.state`。`after_commit` 丢回包后账本可能仍是 `held`，撤办于是当成
  “尚未签发”，把占用删掉并记为 `cancelled`，随后 Y 再次拿到 A。
- 反过来，撤办先成并把 `held` 释放后，挂起的签发仍继续执行 `open_delivery`，因为
  `open_delivery` 只做 `INSERT OR IGNORE`，从没检查过该请求是否已被撤办。

## 修复

`archive` 新增 `report_cancellations` 表，与 `report_deliveries` 一起构成唯一终局：

- `mark_request_cancelled` 只在尚未打开交付时写入撤办标记。
- `open_delivery` 现在先查撤办标记；已撤办的请求永远打不开交付。
- `ledger.cancel.cancel` 先取 `ledger` 写锁，再在 `archive` 写事务里判定：已打开交付则
  `already_signed`（并把账本从 `held` 收敛到 `issued`），否则落撤办标记并释放占用。
  锁先取可保证账本繁忙时不会留下单边标记，直接返回 `pending`。
- 交付已提交但回执丢失（账本尚未 `issued`）时，`audit.shift`/`audit.by_report` 仍按
  `delivered` 与同一条 `held` 占用核对为已核销，使交班账与领取一致，直到重开续办收敛。

## 实测

- `python3 -B check_project.py`：21 项全过（原 18 项 + `tests/test_receipt_handoff.py`
  新增 3 项）。
- `python3 -B incident.py`：两场景通过；先签发再丢回包时撤办返回 `already_signed`、
  Y 返回 `not_enough`，X 原号领回 `U←B、V←A`；撤办先成时 X 为 `cancelled`，Y 保持
  `V←A`，交班账只核销一份。
- `python3 -B demo.py`：日样例结果与下游核对一致。
