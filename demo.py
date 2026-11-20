import json
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from facts.ingest import put_facts
from reconcile.inputs import SourceEditionUnavailable
from reconcile.preview import preview
from registry.intake import put_registry
from release.audit import read_release
from release.publish import publish
from retention.inventory import list_editions
from retention.retire import retire
from retention.store import open_store


def report(result):
    return {
        'editions': [result.fact_version, result.registry_version],
        'rows': [asdict(row) for row in result.rows],
        'totals': [asdict(total) for total in result.totals],
    }


def main():
    day = '东线日域'
    observations = [('A', 7, '泵站簿第1行'), ('A', 7, '泵站簿第2行'), ('B', None, '巡测簿第3行')]
    assignments = [('A', '东区', '台账第1条'), ('B', '东区', '台账第2条')]
    expected = {
        'editions': [1, 1],
        'rows': [
            {'position': 0, 'point': 'A', 'liters': 7, 'partition': '东区',
             'observation_source': '泵站簿第1行', 'registry_source': '台账第1条'},
            {'position': 1, 'point': 'A', 'liters': 7, 'partition': '东区',
             'observation_source': '泵站簿第2行', 'registry_source': '台账第1条'},
            {'position': 2, 'point': 'B', 'liters': None, 'partition': '东区',
             'observation_source': '巡测簿第3行', 'registry_source': '台账第2条'},
        ],
        'totals': [{'partition': '东区', 'liters': 14, 'missing': 1}],
    }
    with TemporaryDirectory() as temporary:
        database = Path(temporary) / 'water.sqlite3'
        with open_store(database) as store:
            facts = put_facts(store, day, 'R1', observations)
            if put_facts(store, day, 'R1', observations) != facts:
                raise AssertionError('日批重传未重领原首执')
            registry = put_registry(store, day, 'C1', assignments)
            for kind, version in (('facts', facts.version), ('registry', registry.version)):
                if not any(entry.available and entry.version == version for entry in list_editions(store, day, kind)):
                    raise AssertionError(f'目录找不到{kind}可用版 {version}')
            trial = preview(store, day, facts.version, registry.version)
            actual = report(trial)
            if actual != expected:
                raise AssertionError(f'试算与手算不符 {actual!r}')
            snapshot, receipt = publish(store, day, 'P1', facts.version, registry.version)
            if report(snapshot) != expected:
                raise AssertionError('签发日账与手算不符')

        with open_store(database) as store:
            if read_release(store, day, 'P1') != (snapshot, receipt):
                raise AssertionError('重开后未取回完整日账')
            put_facts(store, day, 'R2', [*observations[:2], ('B', 0, '巡测B更正')])
            put_registry(store, day, 'C2', [('A', '西区', '台账A更正'), assignments[1]])
            retire(store, day, 'facts', facts.version)
            retire(store, day, 'registry', registry.version)

        with open_store(database) as store:
            for kind in ('facts', 'registry'):
                directory = [(entry.version, entry.available) for entry in list_editions(store, day, kind)]
                if directory != [(1, False), (2, True)]:
                    raise AssertionError(f'{kind}目录不符 {directory!r}')
            try:
                preview(store, day, facts.version, registry.version)
            except SourceEditionUnavailable as error:
                if error.status != 'retired':
                    raise
            else:
                raise AssertionError('已退役源版仍能发起试算')
            reopened, original_receipt = read_release(store, day, 'P1')
            downstream = report(reopened)
            if downstream != expected or original_receipt != receipt:
                raise AssertionError('退役后固定日账或首执发生变化')
            if publish(store, day, 'P1', facts.version, registry.version) != (reopened, original_receipt):
                raise AssertionError('按原参数重投未重领冻结结果')

    total, = reopened.totals
    print(f'{day} {original_receipt.number} 使用 F{reopened.fact_version}/D{reopened.registry_version}，'
          f'{total.partition} {total.liters} L，缺测 {total.missing}，明细 {len(reopened.rows)} 行。')
    print('旧源版退役后已重开并按原号复核。')
    evidence = {
        'case_id': 'v4',
        'input': {'day': day, 'publication': 'P1', 'observations': observations, 'registry': assignments},
        'expected': expected,
        'actual': actual,
        'downstream_expected': expected,
        'downstream_actual': downstream,
        'code_paths': ['reconcile/classify.py', 'reconcile/totals.py', 'release/publish.py',
                       'release/details.py', 'retention/retire.py', 'release/audit.py'],
        'oracle': '逐行查两条静态清册记录。A 的两次 7 L 各计一次，B 缺测计一次。按原序手列三行及双侧出处。',
    }
    print('POINTWISE_SCENARIO ' + json.dumps(evidence, ensure_ascii=False, separators=(',', ':')))


if __name__ == '__main__':
    main()
