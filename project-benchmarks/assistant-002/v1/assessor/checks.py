"""Independent simulator checks. Candidate execution is NOT an OS sandbox.

Expected observations are authored fixtures; no expectation is generated from
candidate output. Spy-sink checks separate simulator behavior from journal quality.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

API = WORKSPACE = JOURNAL_HOME = None
BASE = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
PACKET = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[4]


def stamp(ms=0):
    return (BASE + timedelta(milliseconds=ms)).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def event(identifier='a', ms=0, **changes):
    result = dict(event_id=identifier, source='observer', type='presence', entity='door',
                  timestamp=stamp(ms), confidence=0.9, ttl_seconds=30, data={'present': True})
    result.update(changes)
    return result


def entry(key='first', at=0, **changes):
    result = dict(key=key, at_ms=at, event=event(key, at))
    result.update(changes)
    return result


def scenario(events=None, cps=None, **changes):
    result = dict(schema_version=1, scenario_id='test', start_at=stamp(), duration_ms=60000,
                  events=[entry()] if events is None else events,
                  checkpoints=[dict(at_ms=0, expected_ids=['first'])] if cps is None else cps)
    result.update(changes)
    return result


def cp(at=0, ids=None):
    return dict(at_ms=at, expected_ids=[] if ids is None else ids)


def check(stage, requirement, critical=False):
    def decorate(function):
        function.stage, function.requirement = stage, requirement
        function.severity = 'critical' if critical else 'major'
        return function
    return decorate


class SpySink:
    """Records deliveries; returns explicit states without projecting world state."""
    def __init__(self, state=None):
        self.calls, self.queries, self.stored = [], [], {}
        self.state = [] if state is None else state
        self.fail_id = None
        self.fail_after_commit = False
        self.fail_query = False
        self.return_value = None
        self.mutate_input = False

    def append(self, row):
        self.calls.append(copy.deepcopy(row))
        if row['event_id'] == self.fail_id and not self.fail_after_commit:
            raise RuntimeError('synthetic delivery failure')
        inserted = row['event_id'] not in self.stored
        if inserted:
            self.stored[row['event_id']] = copy.deepcopy(row)
        elif self.stored[row['event_id']] != row:
            raise ValueError('synthetic ID conflict')
        if self.mutate_input:
            row['event_id'] = 'sink-mutated'
            row['data']['present'] = False
        if self.fail_after_commit and self.calls[-1]['event_id'] == self.fail_id:
            raise RuntimeError('synthetic lost acknowledgement')
        return inserted if self.return_value is None else self.return_value

    def current_state(self, *, as_of):
        self.queries.append(as_of)
        if self.fail_query:
            raise RuntimeError('synthetic query failure')
        return self.state


class Acceptance(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='a002-accept-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def cli(self, raw, command='validate', *, dependency=False, expected=0, extra=()):
        source = self.root / 'scenario café.json'
        source.write_text(json.dumps(raw, ensure_ascii=True), encoding='utf-8')
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONPATH'] = str(WORKSPACE) + (os.pathsep + str(JOURNAL_HOME) if dependency else '')
        result = subprocess.run([sys.executable, '-B', '-m', 'assistant_simulator', command,
                                 '--input', str(source), *extra], cwd=WORKSPACE, env=env,
                                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                encoding='utf-8', timeout=10)
        self.assertEqual(result.returncode, expected, result.stderr[-2000:])
        if expected == 2:
            self.assertEqual(result.stdout, '')
            error = json.loads(result.stderr)
            self.assertIsInstance(error.get('error'), str)
            self.assertTrue(error['error'].strip())
            self.assertNotIn('Traceback', result.stderr)
        else:
            self.assertEqual(result.stderr, '')
        return result

    def journal(self, path=None):
        import assistant_journal
        self.assertTrue(Path(assistant_journal.__file__).resolve().is_relative_to(JOURNAL_HOME.resolve()))
        journal = assistant_journal.Journal(path or self.root / 'journal.sqlite3')
        self.addCleanup(journal.close)
        return journal

    @check(1, 'S01')
    def test_normalized_defaults_and_deep_detachment(self):
        raw = scenario(); before = copy.deepcopy(raw)
        actual = API.normalize_scenario(raw)
        expected = copy.deepcopy(raw)
        expected['events'][0].update(delay_ms=0, duplicate_after_ms=[], drop=False)
        self.assertEqual(actual, expected)
        self.assertEqual(raw, before)
        actual['events'][0]['event']['data']['present'] = False
        self.assertEqual(raw, before)

    @check(1, 'S01')
    def test_digest_canonical_known_input(self):
        raw = scenario(events=[], cps=[cp()], duration_ms=0)
        expected = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(',', ':'),
                                             ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()
        self.assertEqual(API.scenario_digest(raw), expected)

    @check(1, 'S01')
    def test_equivalent_defaults_and_offsets_have_same_identity(self):
        raw = scenario()
        other = copy.deepcopy(raw)
        other['start_at'] = '2026-10-08T07:00:00-05:00'
        other['events'][0].update(delay_ms=0, duplicate_after_ms=[], drop=False)
        other['events'][0]['event']['timestamp'] = '2026-10-08T14:00:00+02:00'
        self.assertEqual(API.scenario_digest(raw), API.scenario_digest(other))

    @check(1, 'S01')
    def test_expectations_transforms_and_order_are_hashed(self):
        raw = scenario(events=[entry('a'), entry('b')])
        original = API.scenario_digest(raw)
        variants = []
        value = copy.deepcopy(raw); value['checkpoints'][0]['expected_ids'] = []; variants.append(value)
        value = copy.deepcopy(raw); value['events'][0]['drop'] = True; variants.append(value)
        value = copy.deepcopy(raw); value['events'][0]['delay_ms'] = 1; variants.append(value)
        value = copy.deepcopy(raw); value['events'].reverse(); variants.append(value)
        value = copy.deepcopy(raw); value['duration_ms'] += 1; variants.append(value)
        for value in variants:
            self.assertNotEqual(API.scenario_digest(value), original)

    @check(1, 'S01')
    def test_conflicting_event_ids_are_preserved_as_deliveries(self):
        raw = scenario(events=[entry('a', event=event('same')), entry('b', event=event('same', confidence=0))])
        actual = API.normalize_scenario(raw)
        self.assertEqual(len(actual['events']), 2)
        self.assertEqual(actual['events'][0]['event']['event_id'], 'same')
        self.assertEqual(actual['events'][1]['event']['confidence'], 0.0)

    @check(1, 'S01')
    def test_expected_id_sort_and_precise_milliseconds(self):
        raw = scenario(cps=[cp(1, ['z', 'a'])])
        raw['start_at'] = '2026-10-08T12:00:00.1Z'
        actual = API.normalize_scenario(raw)
        self.assertEqual(actual['start_at'], stamp(100))
        self.assertEqual(actual['checkpoints'][0]['expected_ids'], ['a', 'z'])

    @check(1, 'S01')
    def test_valid_bounds_and_empty_scenario(self):
        API.normalize_scenario(scenario(events=[], cps=[cp()], duration_ms=0, scenario_id='x'*64))
        API.normalize_scenario(scenario(duration_ms=86400000))
        raw = scenario(events=[entry(str(i), duplicate_after_ms=list(range(1,9))) for i in range(111)], cps=[cp(i) for i in range(64)])
        API.normalize_scenario(raw)  # 999 transmissions.
        raw['events'].append(entry('last'))
        API.normalize_scenario(raw)  # 1000 transmissions.
        raw['events'][-1]['duplicate_after_ms'] = [1]
        with self.assertRaises(ValueError): API.normalize_scenario(raw)

    @check(2, 'S02', True)
    def test_delivery_order_is_not_event_time_or_key_order(self):
        raw = scenario(events=[entry('z', 10, event=event('z', 999)), entry('a', 10, event=event('a', -999)),
                               entry('m', 0, delay_ms=20)])
        records = API.compile_schedule(raw)
        self.assertEqual([(r['delivery_id'], r['at_ms']) for r in records], [('z/0',10),('a/0',10),('m/0',20)])
        self.assertEqual(records[0]['event']['timestamp'], stamp(999))

    @check(2, 'S02', True)
    def test_duplicates_preserve_event_identity(self):
        records = API.compile_schedule(scenario(events=[entry('a', 10, delay_ms=20, duplicate_after_ms=[5,10])]))
        self.assertEqual([(r['delivery_id'],r['at_ms']) for r in records], [('a/0',30),('a/1',35),('a/2',40)])
        self.assertTrue(all(r['event'] == event('a',10) for r in records))
        self.assertTrue(all(set(r) == {'delivery_id','at_ms','event'} for r in records))

    @check(2, 'S02', True)
    def test_drop_removes_all_copies(self):
        records = API.compile_schedule(scenario(events=[entry('lost',drop=True,duplicate_after_ms=[1,2]),entry('kept')]))
        self.assertEqual([r['delivery_id'] for r in records], ['kept/0'])

    @check(2, 'S02')
    def test_duplicate_records_and_input_are_independent(self):
        raw = scenario(events=[entry(duplicate_after_ms=[1])]); before = copy.deepcopy(raw)
        records = API.compile_schedule(raw)
        records[0]['event']['data']['present'] = False
        self.assertTrue(records[1]['event']['data']['present'])
        self.assertEqual(raw, before)
        self.assertEqual(API.compile_schedule(raw)[0]['event'], event('first'))

    @check(2, 'S02')
    def test_tied_duplicate_obeys_original_entry_order(self):
        raw = scenario(events=[entry('z', duplicate_after_ms=[10]), entry('a',10)])
        self.assertEqual([r['delivery_id'] for r in API.compile_schedule(raw)], ['z/0','z/1','a/0'])

    @check(2, 'S02')
    def test_empty_schedule_and_repeatability(self):
        self.assertEqual(API.compile_schedule(scenario(events=[])), [])
        raw = scenario(events=[entry('b',300), entry('a',10,duplicate_after_ms=[500])])
        outputs = [json.dumps(API.compile_schedule(raw),sort_keys=True) for _ in range(3)]
        self.assertEqual(len(set(outputs)), 1)

    @check(3, 'S03', True)
    def test_checkpoint_boundary_delivers_before_query(self):
        sink = SpySink(state=[event('reported')])
        replay = API.Replay(scenario(events=[entry('a',1000),entry('b',1001)]), sink)
        result = replay.advance(1000)
        self.assertEqual([r['event_id'] for r in sink.calls], ['a'])
        self.assertEqual(sink.queries, [stamp(1000)])
        self.assertEqual(result, {'at_ms':1000,'as_of':stamp(1000),'deliveries':[
            {'delivery_id':'a/0','event_id':'a','at_ms':1000,'inserted':True}], 'state':[event('reported')]})

    @check(3, 'S03', True)
    def test_no_duplicate_suppression_or_repeat_advance_delivery(self):
        sink = SpySink(); replay = API.Replay(scenario(events=[entry('a',duplicate_after_ms=[1])]),sink)
        records = replay.advance(1)['deliveries']
        self.assertEqual([r['inserted'] for r in records], [True,False])
        self.assertEqual(len(sink.calls),2)
        self.assertEqual(replay.advance(1)['deliveries'],[])
        self.assertEqual(len(sink.calls),2)
        self.assertEqual(len(sink.queries),2)

    @check(3, 'S03')
    def test_advance_validates_time_without_sink_calls(self):
        for value in (-1, True, 1.5, '1', 60001):
            sink = SpySink(); replay = API.Replay(scenario(),sink)
            with self.assertRaises(ValueError): replay.advance(value)
            self.assertEqual(sink.calls,[])
        sink = SpySink(); replay = API.Replay(scenario(),sink); replay.advance(10)
        with self.assertRaises(ValueError): replay.advance(9)

    @check(3, 'S03', True)
    def test_append_error_stops_without_skipping_or_query(self):
        sink = SpySink(); sink.fail_id='b'
        replay = API.Replay(scenario(events=[entry('a'),entry('b',1),entry('c',2)]),sink)
        with self.assertRaises(RuntimeError): replay.advance(3)
        self.assertEqual([r['event_id'] for r in sink.calls], ['a','b'])
        self.assertEqual(sink.queries,[])
        sink.fail_id=None
        result = replay.advance(3)
        self.assertEqual([r['event_id'] for r in result['deliveries']], ['b','c'])
        self.assertEqual([r['event_id'] for r in sink.calls], ['a','b','b','c'])

    @check(3, 'S03', True)
    def test_query_error_does_not_redeliver_committed_events(self):
        sink=SpySink(); sink.fail_query=True; replay=API.Replay(scenario(),sink)
        with self.assertRaises(RuntimeError): replay.advance(10)
        sink.fail_query=False
        self.assertEqual(replay.advance(10)['deliveries'],[])
        self.assertEqual(len(sink.calls),1)

    @check(3, 'S03')
    def test_nonboolean_append_is_not_acknowledgement(self):
        sink=SpySink(); sink.return_value=1; replay=API.Replay(scenario(),sink)
        with self.assertRaises(ValueError): replay.advance(0)
        sink.return_value=None
        self.assertEqual(len(replay.advance(0)['deliveries']),1)
        self.assertEqual(len(sink.calls),2)

    @check(3, 'S03')
    def test_sink_mutation_cannot_poison_scheduled_duplicates(self):
        sink=SpySink(); sink.mutate_input=True
        raw=scenario(events=[entry(duplicate_after_ms=[1])]); replay=API.Replay(raw,sink)
        result=replay.advance(1)
        self.assertEqual([r['event_id'] for r in result['deliveries']],['first','first'])
        self.assertEqual(sink.calls[0],sink.calls[1])
        self.assertEqual(raw['events'][0]['event'],event('first'))

    @check(3, 'S03')
    def test_state_result_detached_and_virtual_clock_never_sleeps(self):
        sink=SpySink(state=[event()]); replay=API.Replay(scenario(events=[]),sink)
        with patch('time.sleep',side_effect=AssertionError('virtual replay must not sleep')):
            result=replay.advance(60000)
        result['state'][0]['data']['present']=False
        self.assertTrue(sink.state[0]['data']['present'])
        self.assertEqual(result['as_of'],stamp(60000))

    @check(3, 'S03')
    def test_zero_time_deliveries_and_invalid_scenario_no_sink_calls(self):
        sink=SpySink(); replay=API.Replay(scenario(duration_ms=0),sink)
        self.assertEqual(len(replay.advance(0)['deliveries']),1)
        bad=scenario(); bad['events'][-1]['at_ms']=True
        sink=SpySink()
        with self.assertRaises(ValueError): API.Replay(bad,sink)
        self.assertEqual(sink.calls,[])
        self.assertEqual(sink.queries,[])

    @check(4, 'S04')
    def test_checkpoint_exact_format_and_json_roundtrip(self):
        raw=scenario(events=[entry('a',duplicate_after_ms=[1]),entry('b',10)])
        sink=SpySink(); replay=API.Replay(raw,sink); replay.advance(1)
        saved=json.loads(json.dumps(replay.checkpoint()))
        self.assertEqual(saved,dict(schema_version=1,scenario_sha256=API.scenario_digest(raw),cursor=2,
                                    current_ms=1,inserted=1,duplicates=1))
        saved['cursor']=99
        self.assertEqual(replay.checkpoint()['cursor'],2)
        saved=replay.checkpoint(); calls=len(sink.calls); queries=len(sink.queries)
        restored=API.Replay.from_checkpoint(raw,sink,saved)
        self.assertEqual((len(sink.calls),len(sink.queries)),(calls,queries))
        self.assertEqual([r['event_id'] for r in restored.advance(10)['deliveries']],['b'])

    @check(4, 'S04', True)
    def test_lost_checkpoint_replays_committed_event_as_duplicate(self):
        raw=scenario(); sink=SpySink(); replay=API.Replay(raw,sink); saved=replay.checkpoint()
        replay.advance(0)  # Application lost its unsaved progress after durable append.
        restored=API.Replay.from_checkpoint(raw,sink,saved)
        result=restored.advance(0)
        self.assertEqual(result['deliveries'][0]['inserted'],False)
        self.assertEqual(restored.checkpoint()['duplicates'],1)
        self.assertEqual(len(sink.stored),1)
        self.assertEqual([r['event_id'] for r in sink.calls],['first','first'])

    @check(4, 'S04', True)
    def test_lost_acknowledgement_retries_identical_event(self):
        sink=SpySink(); sink.fail_id='first'; sink.fail_after_commit=True
        raw=scenario(); replay=API.Replay(raw,sink)
        with self.assertRaises(RuntimeError): replay.advance(0)
        self.assertEqual(replay.checkpoint()['cursor'],0)
        sink.fail_id=None
        restored=API.Replay.from_checkpoint(raw,sink,replay.checkpoint())
        self.assertIs(restored.advance(0)['deliveries'][0]['inserted'],False)
        self.assertEqual(sink.calls[0],sink.calls[1])

    @check(4, 'S04', True)
    def test_checkpoint_changed_scenario_or_expectations_rejected(self):
        raw=scenario(); saved=API.Replay(raw,SpySink()).checkpoint()
        for modified in (scenario(scenario_id='other'),scenario(cps=[cp()]),scenario(events=[entry(delay_ms=1)])):
            with self.assertRaises(ValueError): API.Replay.from_checkpoint(modified,SpySink(),saved)

    @check(4, 'S04', True)
    def test_checkpoint_invalid_fields_counts_bounds_and_clock(self):
        raw=scenario(events=[entry('a',10),entry('b',20)])
        good=API.Replay(raw,SpySink()).checkpoint()
        bads=[None,{},dict(good,extra=0),dict(good,schema_version=True),dict(good,cursor=True),
              dict(good,inserted=True),dict(good,duplicates=-1),dict(good,current_ms=True),
              dict(good,current_ms=60001),dict(good,scenario_sha256='0'*64),
              dict(good,cursor=3,inserted=3),dict(good,cursor=1),dict(good,cursor=1,current_ms=10),
              dict(good,cursor=1,inserted=1,current_ms=5),dict(good,current_ms=11)]
        for value in bads:
            sink=SpySink()
            with self.subTest(value=value),self.assertRaises(ValueError):
                API.Replay.from_checkpoint(raw,sink,value)
            self.assertEqual(sink.calls,[])

    @check(4, 'S04')
    def test_equal_time_partial_checkpoint_is_valid(self):
        sink=SpySink(); sink.fail_id='b'; raw=scenario(events=[entry('a',10),entry('b',10)])
        replay=API.Replay(raw,sink)
        with self.assertRaises(RuntimeError): replay.advance(10)
        saved=replay.checkpoint(); self.assertEqual(saved['cursor'],1); self.assertEqual(saved['current_ms'],10)
        sink.fail_id=None
        self.assertEqual([r['event_id'] for r in API.Replay.from_checkpoint(raw,sink,saved).advance(10)['deliveries']],['b'])

    @check(5, 'S05', True)
    def test_report_does_not_rewrite_expected_ids(self):
        raw=scenario(events=[],cps=[cp(0,['expected'])])
        report=API.evaluate_scenario(raw,SpySink(state=[event('observed')]))
        self.assertFalse(report['passed'])
        self.assertEqual(report['checks'][0],dict(at_ms=0,as_of=stamp(),expected_ids=['expected'],
            observed_ids=['observed'],missing=['expected'],unexpected=['observed'],passed=False))
        self.assertEqual(raw['checkpoints'][0]['expected_ids'],['expected'])
        self.assertEqual(set(report),{'scenario_id','scenario_sha256','passed','delivered','inserted','duplicates','checks'})

    @check(5, 'S05')
    def test_reports_all_mismatches_then_drains_later_events(self):
        raw=scenario(events=[entry('later',50000)],cps=[cp(0,['absent']),cp(1,[])])
        sink=SpySink(); report=API.evaluate_scenario(raw,sink)
        self.assertFalse(report['passed'])
        self.assertEqual([r['passed'] for r in report['checks']],[False,True])
        self.assertEqual(report['delivered'],1)
        self.assertEqual(report['inserted'],1)
        self.assertEqual(report['duplicates'],0)
        self.assertEqual(sink.queries,[stamp(),stamp(1),stamp(60000)])

    @check(5, 'S05')
    def test_observations_compared_as_sets_with_sorted_diagnostics(self):
        raw=scenario(events=[],cps=[cp(60000,['b','a'])])
        report=API.evaluate_scenario(raw,SpySink(state=[event('b'),event('a')]))
        self.assertTrue(report['passed'])
        self.assertEqual(report['checks'][0]['observed_ids'],['a','b'])
        self.assertEqual(len(report['checks']),1)

    @check(5, 'S05', True)
    def test_duplicate_observed_ids_not_silently_hidden(self):
        with self.assertRaises(ValueError):
            API.evaluate_scenario(scenario(),SpySink(state=[event('a'),event('a')]))

    @check(5, 'S05', True)
    def test_invalid_observed_id_or_append_failure_propagates(self):
        with self.assertRaises(ValueError): API.evaluate_scenario(scenario(),SpySink(state=[event('bad id')]))
        sink=SpySink(); sink.fail_id='first'
        with self.assertRaises(RuntimeError): API.evaluate_scenario(scenario(),sink)
        self.assertEqual(sink.queries,[])

    @check(5, 'S05', True)
    def test_unexpected_only_is_failure(self):
        result=API.evaluate_scenario(scenario(events=[],cps=[cp()]),SpySink(state=[event('extra')]))
        self.assertFalse(result['passed'])
        self.assertEqual(result['checks'][0]['unexpected'],['extra'])

    @check(5, 'S05')
    def test_final_checkpoint_not_queried_twice(self):
        sink=SpySink(); API.evaluate_scenario(scenario(events=[],cps=[cp(60000)]),sink)
        self.assertEqual(sink.queries,[stamp(60000)])

    @check(5, 'S04/S05 + A001', True)
    def test_real_journal_restart_with_old_checkpoint(self):
        raw=scenario(); db=self.root/'persistent.sqlite3'; journal=self.journal(db)
        first=API.Replay(raw,journal); saved=first.checkpoint(); first.advance(0); journal.close()
        reopened=self.journal(db)
        restored=API.Replay.from_checkpoint(raw,reopened,json.loads(json.dumps(saved)))
        result=restored.advance(0)
        self.assertIs(result['deliveries'][0]['inserted'],False)
        self.assertEqual(reopened.count(),1)
        self.assertEqual([r['event_id'] for r in result['state']],['first'])
        self.assertEqual(restored.advance(30000)['state'],[])

    @check(5, 'S03 + A001', True)
    def test_real_journal_conflict_leaves_prior_event_and_stops(self):
        journal=self.journal()
        raw=scenario(events=[entry('a',event=event('same')),entry('b',1,event=event('same',confidence=0)),entry('c',2)])
        replay=API.Replay(raw,journal)
        with self.assertRaises(ValueError): replay.advance(10)
        self.assertEqual(journal.count(),1)
        self.assertEqual(journal.get('same'),event('same'))
        self.assertEqual(replay.checkpoint()['cursor'],1)

    @check(6, 'S06')
    def test_cli_validate_and_schedule_without_journal(self):
        raw=scenario()
        result=json.loads(self.cli(raw).stdout)
        self.assertEqual(result,dict(scenario_id='test',scenario_sha256=API.scenario_digest(raw),deliveries=1))
        self.assertEqual(json.loads(self.cli(raw,'schedule').stdout),API.compile_schedule(raw))

    @check(6, 'S06')
    def test_cli_jsonl_is_canonical_and_retains_duplicates(self):
        raw=scenario(events=[entry(duplicate_after_ms=[1]),entry('drop',drop=True)])
        text=self.cli(raw,'jsonl').stdout
        canonical=json.dumps(event('first'),sort_keys=True,separators=(',',':'),ensure_ascii=False)+'\n'
        self.assertEqual(text,canonical*2)
        self.assertEqual(self.cli(scenario(events=[]),'jsonl').stdout,'')

    @check(6, 'S06', True)
    def test_cli_error_does_not_emit_partial_schedule_or_payload(self):
        raw=scenario(events=[entry(),entry('bad',event=event(data={'message':'PRIVATE_TEST_SENTINEL'},confidence=True))])
        result=self.cli(raw,'jsonl',expected=2)
        self.assertNotIn('PRIVATE_TEST_SENTINEL',result.stderr)
        self.cli(scenario(),'run',expected=2)  # no database supplied
        self.cli(scenario(),'validate',expected=2,extra=('--db','unused.sqlite3'))

    @check(6, 'S06 + A001')
    def test_cli_run_pass_and_mismatch_are_distinct_exit_codes(self):
        db=self.root/'journal.sqlite3'
        raw=scenario()
        report=json.loads(self.cli(raw,'run',dependency=True,extra=('--db',str(db))).stdout)
        self.assertTrue(report['passed'])
        mismatch=scenario(cps=[cp(0,[])])
        report=json.loads(self.cli(mismatch,'run',dependency=True,expected=1,extra=('--db',str(db))).stdout)
        self.assertFalse(report['passed'])
        self.assertEqual(report['duplicates'],1)
        self.assertEqual(report['checks'][0]['unexpected'],['first'])

    @check(6, 'S06 + A001', True)
    def test_cli_never_resets_preexisting_journal(self):
        db=self.root/'journal.sqlite3'; journal=self.journal(db)
        journal.append(event('external',source='contact')); journal.close()
        result=self.cli(scenario(),'run',dependency=True,expected=1,extra=('--db',str(db)))
        self.assertEqual(json.loads(result.stdout)['checks'][0]['unexpected'],['external'])
        self.assertEqual(self.journal(db).count(),2)

    @check(6, 'S06')
    def test_cli_unicode_payload_and_database_path(self):
        raw=scenario(events=[entry(event=event('first',data={'text':'café Ω 测试'}))])
        schedule=json.loads(self.cli(raw,'schedule').stdout)
        self.assertEqual(schedule[0]['event']['data']['text'],'café Ω 测试')
        self.cli(raw,'run',dependency=True,extra=('--db',str(self.root/'café-Ω.sqlite3')))

    @check(6, 'S06')
    def test_candidate_and_public_tests_run(self):
        self.assertIn('def test_', (WORKSPACE/'tests/test_candidate.py').read_text(encoding='utf-8'))
        env=os.environ.copy(); env['PYTHONPATH']=str(WORKSPACE)
        result=subprocess.run([sys.executable,'-B','-m','unittest','discover','-s','tests','-v'],
                              cwd=WORKSPACE,env=env,stdin=subprocess.DEVNULL,capture_output=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr[-3000:])
        self.assertIn(b'Ran ',result.stderr)
        self.assertNotIn(b'skipped',result.stderr.lower())


INVALID = {
    'not_object':None, 'unknown_field':scenario(extra=1),
    'missing_field':{k:v for k,v in scenario().items() if k!='events'},
    'wrong_version':scenario(schema_version=2),'bool_version':scenario(schema_version=True),
    'invalid_id':scenario(scenario_id='bad/id'),'empty_id':scenario(scenario_id=''),
    'long_id':scenario(scenario_id='a'*65),'naive_start':scenario(start_at='2026-10-08T12:00:00'),
    'bad_start_offset':scenario(start_at='2026-10-08T12:00:00+00:99'),
    'clock_overflow':scenario(start_at='9999-12-31T23:59:59Z'),
    'bool_duration':scenario(duration_ms=True),'negative_duration':scenario(duration_ms=-1),
    'large_duration':scenario(duration_ms=86400001),'float_duration':scenario(duration_ms=1.5),
    'nonlist_events':scenario(events=()),'too_many_events':scenario(events=[entry(str(i)) for i in range(257)]),
    'duplicate_keys':scenario(events=[entry(),entry()]),'unknown_entry':scenario(events=[entry(extra=1)]),
    'negative_at':scenario(events=[entry(at=-1)]),'bool_at':scenario(events=[entry(at=True)]),
    'float_delay':scenario(events=[entry(delay_ms=1.5)]),'bool_delay':scenario(events=[entry(delay_ms=True)]),
    'negative_delay':scenario(events=[entry(delay_ms=-1)]),'outside_duration':scenario(events=[entry(at=60000,delay_ms=1)]),
    'bool_drop':scenario(events=[entry(drop=1)]),'bool_duplicate_offset':scenario(events=[entry(duplicate_after_ms=[True])]),
    'duplicate_offsets':scenario(events=[entry(duplicate_after_ms=[1,1])]),
    'unsorted_offsets':scenario(events=[entry(duplicate_after_ms=[2,1])]),
    'zero_offset':scenario(events=[entry(duplicate_after_ms=[0])]),
    'too_many_offsets':scenario(events=[entry(duplicate_after_ms=list(range(1,10)))]),
    'dropped_but_invalid_time':scenario(events=[entry(at=60000,delay_ms=1,drop=True)]),
    'dropped_but_invalid_event':scenario(events=[entry(drop=True,event=event(confidence=True))]),
    'tuple_duplicates':scenario(events=[entry(duplicate_after_ms=(1,))]),
    'missing_checkpoints':scenario(cps=[]),'too_many_checkpoints':scenario(cps=[cp(i) for i in range(65)]),
    'backward_checkpoints':scenario(cps=[cp(1),cp(0)]),'duplicate_checkpoint_times':scenario(cps=[cp(0),cp(0)]),
    'bool_checkpoint_time':scenario(cps=[cp(True)]),'checkpoint_after_end':scenario(cps=[cp(60001)]),
    'duplicate_expected_ids':scenario(cps=[cp(0,['a','a'])]),'bad_expected_id':scenario(cps=[cp(0,['bad id'])]),
    'string_expected_ids':scenario(cps=[cp(0,'first')]),
    'unknown_checkpoint_field':scenario(cps=[dict(cp(),extra=1)])}
for name, value in INVALID.items():
    def invalid_test(self, value=value):
        with self.assertRaises(ValueError): API.normalize_scenario(copy.deepcopy(value))
    invalid_test.__name__='test_reject_'+name
    setattr(Acceptance,invalid_test.__name__,check(1,'S01')(invalid_test))

# Named end-to-end scenarios exercise the real supplied A001 Journal, not SpySink.
for name in sorted(p.stem for p in (PACKET/'starter/scenarios').glob('*.json')):
    def golden_test(self,name=name):
        raw=json.loads((PACKET/'starter/scenarios'/f'{name}.json').read_text(encoding='utf-8'))
        result=API.evaluate_scenario(raw,self.journal())
        self.assertTrue(result['passed'],json.dumps(result,indent=2))
        self.assertEqual([r['observed_ids'] for r in result['checks']],
                         [sorted(r['expected_ids']) for r in raw['checkpoints']])
    golden_test.__name__='test_joint_'+name.replace('-','_')
    setattr(Acceptance,golden_test.__name__,check(5,'S01–S05 + A001',True)(golden_test))


class RecordingResult(unittest.TestResult):
    def __init__(self):
        super().__init__(); self.rows=[]; self.subfailures={}

    def addSubTest(self,test,subtest,err):
        super().addSubTest(test,subtest,err)
        if err: self.subfailures.setdefault(test.id(),[]).append(self._exc_info_to_string(err,test))

    def stopTest(self,test):
        method=getattr(test,test._testMethodName)
        errors=[text for failed,text in self.failures+self.errors if failed is test]
        errors+=self.subfailures.get(test.id(),[])
        errors += [why for skipped,why in self.skipped if skipped is test]
        self.rows.append(dict(case_id=test._testMethodName,requirement=method.requirement,
            task=f'T0{method.stage}',severity=method.severity,passed=not errors,diagnostics='\n'.join(errors)[-8000:]))
        super().stopTest(test)


def install_journal(destination):
    """Calibration fixture only, outside the candidate view and output workspace."""
    source=REPO/'project-benchmarks/assistant-001/v1'
    package=Path(destination)/'assistant_journal'; package.mkdir(parents=True)
    for name in ('__init__.py',):
        shutil.copyfile(source/'starter/assistant_journal'/name,package/name)
    for name in ('validation.py','journal.py'):
        shutil.copyfile(source/'assessor/reference/assistant_journal'/name,package/name)
    return Path(destination)


def main(argv=None):
    global API,WORKSPACE,JOURNAL_HOME
    parser=argparse.ArgumentParser()
    parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--task',choices=[f'T0{i}' for i in range(1,7)],required=True)
    parser.add_argument('--result',type=Path,required=True)
    parser.add_argument('--case',action='append',help='Calibration selection only')
    parser.add_argument('--journal-workspace',type=Path,help='Optional real candidate pair; host execution is acknowledged by the caller')
    args=parser.parse_args(argv); WORKSPACE=args.workspace.resolve()
    report=dict(contract='assistant-002-v1',task=args.task,passed=False,status='candidate_error',checks=[],os_sandbox=False)
    with tempfile.TemporaryDirectory(prefix='a002-dependency-') as folder:
        try:
            JOURNAL_HOME=args.journal_workspace.resolve() if args.journal_workspace else install_journal(folder)
            sys.path.insert(0,str(JOURNAL_HOME)); sys.path.insert(0,str(WORKSPACE))
            API=importlib.import_module('assistant_simulator')
            if not Path(API.__file__).resolve().is_relative_to(WORKSPACE):
                raise ValueError('Candidate import escaped workspace')
            names=[name for name in unittest.defaultTestLoader.getTestCaseNames(Acceptance)
                   if getattr(Acceptance,name).stage<=int(args.task[-1]) and (not args.case or name in args.case)]
            if not names: raise ValueError('No acceptance checks selected')
            tests=[Acceptance(name) for name in names]; result=RecordingResult()
            unittest.TestSuite(tests).run(result)
            report.update(status='completed',checks=result.rows,planned=len(names),executed=result.testsRun,
                          passed=result.wasSuccessful() and not result.skipped and result.testsRun==len(names),
                          journal_kind='external-candidate' if args.journal_workspace else 'A001-calibration-reference')
        except Exception as exc:
            report['error']=f'{type(exc).__name__}: {exc}'
    args.result.parent.mkdir(parents=True,exist_ok=True)
    args.result.write_text(json.dumps(report,indent=2,ensure_ascii=True)+'\n',encoding='utf-8')
    return 0 if report['passed'] else 1

if __name__=='__main__':
    raise SystemExit(main())
