import json
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from facts.ingest import put_facts
from reconcile.inputs import SourceEditionUnavailable
from reconcile.preview import preview
from registry.intake import put_registry
from release.audit import read_release
from release.publish import publish, publish_handoff, register_handoff
from retention.eligibility import HandoffEditionProtected
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
    show_handoff()


def show_handoff():
    """Drive the handoff stream through a wait, late arrival, retirement and reopen."""
    day = '东线日域'
    f1 = (('A', 7, 'F1-A1'), ('A', 7, 'F1-A2'), ('A', None, 'F1-A3'))
    f2 = (('C', 11, 'F2-C'),)
    f3 = (('A', 13, 'F3-A'),)
    f4 = (('A', 17, 'F4-A'),)
    d1 = (('A', '东区', 'D1-A'), ('C', '东区', 'D1-C'))
    d2 = (('B', '西区', 'D2-B'), ('C', '西区', 'D2-C'))
    d3 = (('A', '北区', 'D3-A'),)
    with TemporaryDirectory() as temporary:
        database = Path(temporary) / 'handoff.sqlite3'
        with open_store(database) as store:
            put_facts(store, day, 'F1', f1)
            put_registry(store, day, 'D1', d1)
            register_handoff(store, day)
            first, first_receipt = publish_handoff(store, day, 'H1')
            print(f"交班 {first_receipt.number} 签出 F{first.fact_version}/D{first.registry_version}，"
                  f"东区 {first.totals[0].liters} L，缺测 {first.totals[0].missing}，明细 {len(first.rows)} 行。")
            # Only F2 and D2 arrive; the sole advancing compatible pair is F2/D2.
            put_facts(store, day, 'F2', f2)
            put_registry(store, day, 'D2', d2)
            second, second_receipt = publish_handoff(store, day, 'H2')
            print(f"交班 {second_receipt.number} 签出 F{second.fact_version}/D{second.registry_version}，"
                  f"{second.totals[0].partition} {second.totals[0].liters} L。")
            # Both fact sides advance, but neither D2 nor the now-below-floor D1
            # can classify them and D3 has not arrived yet: wait on the same number.
            put_facts(store, day, 'F3', f3)
            put_facts(store, day, 'F4', f4)
            if publish_handoff(store, day, 'H3') is not None:
                raise AssertionError('H3 should wait for the registry side')
            print('补件前 H3 待交班：下界与退役资格未变。')
            # F3 is no longer latest but stays at/above the fact floor, so it remains protected.
            try:
                retire(store, day, 'facts', 3)
            except HandoffEditionProtected:
                print('F3 虽非最新，仍在交班下界之上，保持保护。')
            else:
                raise AssertionError('handoff floor should protect F3')
            # The late D3_A lets the waiting number sign F4/D3.
            put_registry(store, day, 'D3', d3)
            late, late_receipt = publish_handoff(store, day, 'H3')
            if late is None:
                raise AssertionError('late D3 should let H3 sign')
            print(f"补件后 {late_receipt.number} 签出 F{late.fact_version}/D{late.registry_version}，"
                  f"{late.totals[0].partition} {late.totals[0].liters} L。")
            # Retire an edition strictly below the fact floor, then reopen.
            retired = retire(store, day, 'facts', 2)
            print(f"退役 F{retired.version}：严格低于交班下界 F{late.fact_version}。")
            expected = (late, late_receipt)
        with open_store(database) as store:
            reopened, reopened_receipt = read_release(store, day, 'H3')
            if (reopened, reopened_receipt) != expected:
                raise AssertionError('重开后交班日账或首执变化')
            directory = [(entry.version, entry.available) for entry in list_editions(store, day, 'facts')]
            if directory != [(1, True), (2, False), (3, True), (4, True)]:
                raise AssertionError(f'重开后目录不符 {directory!r}')
            print(f'重开核对 H3 = F{reopened.fact_version}/D{reopened.registry_version}，'
                  f'{len(reopened.rows)} 行原序明细与双侧出处一致；facts 目录 {directory}。')


if __name__ == '__main__':
    main()
