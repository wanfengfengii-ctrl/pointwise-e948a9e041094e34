# 精密计量复检归档

白班从测头批次接纳原读和勘误。质检员冻结原测，逐格选证，签发复检表。交班员按号领取固定报告和首执，并将出处、正式核销和本批余额核对到同一份原测修订。

## 运行

需要 Python 3.11，仅使用标准库。在工程根目录运行。

```sh
python3 -B check_project.py
python3 -B demo.py
```

第一条是控制台提供的完整回归入口。直接使用 Python 时也可以运行 `python3 -B -m unittest discover -s tests -t .`。演示和测试使用独立临时目录。日常样例输入在 `samples/day.json`。

## 公开接口

- `archive.initialize.initialize(directory)` 返回 `Stores`。工作目录下有独立的 `archive.sqlite3` 和 `ledger.sqlite3`。重复初始化只补建结构，保留源修订、冻结批、占用、终局、成品和首执。
- `source.ingest.ingest(stores, device, measurement, *, unit, reading, category, origin, previous=None)` 返回 `RevisionRef`。`unit` 为 `um`，读数为整数或显式 `None`，布尔值非法。`Origin(probe_batch, document, line)` 指向测头批次、原件及正整数行号。前修订须为同一设备和测次的当前链尾。错误输入抛出 `ValueError`，不接纳新修订。可在源库读事务中使用 `source.store.load_revision` 和 `load_revision_chain` 复核旧件。
- `review.freeze.freeze(stores, batch_id, revisions, gauge, slots)` 返回 `FrozenBatch`。`Gauge(minimum_um, maximum_um)` 为包含端点的闭区间。`SlotRequirement(name, categories, candidates)` 声明格位类别和按序提名的修订。返回值保存全部所选原测，以及每格提名、资格和排除原因。未知或重复的修订、重复格、批号异参抛出 `ValueError`；同批号同参取回原快照。
- `archive.publish.sign(stores, batch_id, request_id, slots, *, checkpoint=None)` 中 `slots` 是有序 `RequestSlot(name, candidates)` 序列。每格可明确排列或缩小候选，合法但未获冻结资格的候选被滤除，返回归属保持提交格序。完整解优先按首格候选次序选择，再按后续格依序选择。无完整解返回 `not_enough`。未知批返回 `unknown_batch`，未知格、非本批修订或畸形结构抛出 `ValueError`。同号异参返回 `request_conflict`；持续占用、提交结果无法确认或存储临时不可用可返回 `pending`，用原参数续办。缺证可在凭据资格变化后同参重试。
- `ledger.cancel.cancel(stores, batch_id, request_id, slots)` 使用原参数。返回 `cancelled`、`already_signed`、`unknown_request`、`request_conflict` 或 `pending`。签发与撤办只有一个终局；已签报告的凭据保持永久核销。
- `archive.readback.read(stores, report_id)` 按 `R-` 加请求号定位报告。`signed` 含 `lines`、`receipt`、`report_id`、`request_id` 和 `batch_id`，也是签发成功的结果格式。每条明细包含格号、凭据身份、准确修订、读数和原件出处。`unknown_report`、`not_signed`、`cancelled` 和 `pending` 均无正式明细及首执。`sign`、`cancel` 和 `read` 均用结果字典的 `status` 字段表示业务状态。
- `audit.shift.audit(stores, batch_id, report_id=None)` 返回逐凭据状态、余额、待确认请求和可选的逐格报告核对。每份修订至多计一次，非正式报告不产生逐格账。报告属于另一批时返回 `batch_mismatch`。余额类别为 `used`、`available`、`held`、`missing`、`ineligible` 和 `unconfirmed`。台账暂不可读时返回 `pending`，仅报告可由冻结快照确认的分类，余下凭据单列待确认。

签发的可选同步 `checkpoint(stage)` 供测试与调用方观察工作进度。阶段为 `before_claim`、`after_prepare`、`before_commit` 和 `after_commit`。回调可用 `ConfirmationInterrupted` 模拟该处中断，调用方得到 `pending`。`before_commit` 处事务仍打开，回调用于观测或中断。重开时用同一目录和原请求参数。

## 手算样例

量规为 0 至 10 微米。A 为 0，可供 U、V。B 为 7，只可供 U。M 缺测。U 依序申请 A、B，V 只申请 A。选 U←A 会使 V 无证，所以完整归属为 U←B、V←A。签发后只申请 A 的 Y 缺证。本批核账为已用 2、可用 0、缺测 1。更正 B 后，原号领取仍返回 B 的原修订、原出处和原首执。
