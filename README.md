# 临浦供水监测日仓 V1

巡测班提交现场观测全版，测点资料员独立提交分区清册全版。日结员指定版次试算和签发，分区运行班据汇总日结，核账员按发布号复核原行与出处。保管员可在各自有新版后撤下旧原件。

使用 Python 3.11 和标准库。从项目根目录运行完整回归及样例。

```sh
python3 -B check_project.py
python3 -B -m demo
```

`check_project.py` 由运行平台在物化时提供。单独复制源码时也可运行 `python3 -B -m unittest discover -s tests`。样例使用自行清理的临时库，输出实测日账及退役后复核结果。

## Python API

```python
from facts.ingest import put_facts
from registry.intake import put_registry
from reconcile.preview import preview
from release.audit import read_release
from release.publish import publish
from retention.inventory import list_editions
from retention.retire import retire
from retention.store import open_store

with open_store('water.sqlite3') as store:
    facts = put_facts(store, '东线日域', 'R1', [
        ('A', 7, '泵站簿第1行'),
        ('A', 7, '泵站簿第2行'),
        ('B', None, '巡测簿第3行'),
    ])
    registry = put_registry(store, '东线日域', 'C1', [
        ('A', '东区', '台账第1条'),
        ('B', '东区', '台账第2条'),
    ])
    directory = list_editions(store, '东线日域', 'facts')
    trial = preview(store, '东线日域', facts.version, registry.version)
    snapshot, receipt = publish(store, '东线日域', 'P1', facts.version, registry.version)

with open_store('water.sqlite3') as store:
    snapshot, receipt = read_release(store, '东线日域', 'P1')
```

- 日域、请求号、发布号、测点、分区和出处为非空白字符串，原内容保留。版号为正整数，源类为 `facts` 或 `registry`。观测和清册均接收完整的三字段序列，允许空版。首个成功接纳建立日域，各侧版号从 1 独立递增。已知日域未到件的一侧有空目录。
- 观测行按 `(测点, 整数升或 None, 观测出处)` 提交，原序从 0 起。整数可为零或负值，布尔值和小数无效。清册条目按 `(测点, 分区, 清册出处)` 提交，同版测点须唯一。格式错误报 `ValueError`，重复测点报 `DuplicatePoint`，整版拒绝。
- `put_facts` 和 `put_registry` 返回带 `day`、`request_id`、`version` 的原首执。同日域同源类同请求号重投同内容可重领，异内容分别报 `FactRequestConflict` 或 `RegistryRequestConflict`。观测原序参与比较，清册条目顺序可以变化。出处参与比较，原件退役后仍可比较。
- `preview` 返回所选版次、原序 `rows` 和按分区标识排列的 `totals`。每条已归类的实测行累计一次有符号整升，每条缺测行累计一次 `missing`。仅缺测分区合计 0 L，空观测的明细和汇总均为空。指定版不存在或已退役报 `SourceEditionUnavailable`。首个无法关联的观测抛出 `UnmappedObservation`，`as_report()` 给出日域、双版号、零基位置、测点和出处。
- `publish` 使用显式版次，返回 `(ReleaseSnapshot, ReleaseReceipt)`。新号在同一写事务内重新试算并固定两版号、所有明细、双侧出处、汇总及首执。重复原参数返回原成果，异参报 `PublishNumberConflict`，提交错误以 SQLite 异常返回且完整回滚。`read_release` 同样返回成果和首执，按日域及发布号查找，缺少该号时抛出 `ReleaseNotFound`。
- `list_editions` 按版号列出 `EditionAvailability`，含可用及已退役条目。`retire(store, day, kind, version)` 撤下指定旧版原件，返回 `RetirementRecord`，重投返回原记录。目录和退役入口对未知日域及非法源类分别报 `UnknownDay`、`InvalidSourceKind`。退役入口对未知版及本侧最新版分别报 `UnknownEdition`、`LatestEdition`。已发布明细、汇总、首执及源请求证据跨退役和重开保留。

`open_store` 幂等初始化库结构，保留已登记业务数据。读操作使用一次 SQLite 事务视图，写操作使用 `BEGIN IMMEDIATE` 把核对和变更串行化。接纳、定稿与退役都通过公开入口完整提交。提交失败场景使用同一连接上的延迟约束，在发布回执写入后由 SQLite 的 COMMIT 触发。
