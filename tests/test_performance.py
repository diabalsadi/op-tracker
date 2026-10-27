import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from advanced import Tracker
from server import Handler, StateCache
from test_tracker import export


class CalculationReuseTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.t=Tracker(Path(self.folder.name)/'tracker.sqlite3')
        self.team=self.t.save('teams',{'name':'Example'})
        self.member=self.t.save('members',{'name':'Example Dev','jira_id':'dev-a','role':'Dev',
            'country':'JO','team_id':self.team,'effective_at':'2026-07-01'})

    def tearDown(self):
        self.t.db.close()
        self.folder.cleanup()

    def test_configuration_does_not_calculate_ticket_histories(self):
        self.t.import_csv(export(),'example.csv','2026-10-19')
        with patch.object(self.t,'state',side_effect=AssertionError('Unexpected calculation')):
            config=self.t.configuration()
        self.assertEqual(config['members'][0]['id'],self.member)
        self.assertEqual(len(config['imports']),1)
        self.assertNotIn('score_events',config)

    def test_history_queries_do_not_repeat_for_every_ticket(self):
        self.t.save('members',{'id':self.member,'name':'Renamed Dev','jira_id':'dev-a','role':'Dev',
            'country':'JO','team_id':self.team,'effective_at':'2026-10-20'})
        for number in range(20):
            self.t.import_csv(export().replace('OP-1',f'OP-{number+1}'),'example.csv','2026-10-19')
        queries=[]
        self.t.db.set_trace_callback(queries.append)
        state=self.t.state('2026-10-21')
        self.t.db.set_trace_callback(None)
        roster_queries=[q for q in queries if q.startswith('SELECT * FROM member_versions WHERE effective_at<=')]
        self.assertLessEqual(len(roster_queries),2)
        self.assertEqual(len(state['tickets']),20)

    def test_new_calculation_sees_changes_after_previous_scope_ends(self):
        self.t.import_csv(export(),'example.csv','2026-10-19')
        self.t.state('2026-10-21')
        self.t.save('members',{'id':self.member,'name':'Updated Dev','jira_id':'dev-a','role':'Dev',
            'country':'AM','team_id':self.team,'effective_at':'2026-10-20'})
        state=self.t.state('2026-10-21')
        self.assertEqual(state['tickets'][0]['owners'][0]['country'],'AM')

    def test_report_reuses_supplied_state(self):
        self.t.import_csv(export('Done',resolved='2026-08-20T09:00:00Z'),'done.csv','2026-08-21')
        state=self.t.state()
        with patch.object(self.t,'state',side_effect=AssertionError('Repeated full calculation')):
            report=self.t.report('2026-08-01','2026-08-31',_state=state)
        self.assertEqual(report['sp'],5)

    def test_live_cache_expires_and_can_be_explicitly_invalidated(self):
        cache=StateCache(ttl=5)
        with patch.object(self.t,'state',wraps=self.t.state) as calculate:
            with patch('server.time.monotonic',return_value=10):
                cache.get(self.t);cache.get(self.t)
            self.assertEqual(calculate.call_count,1)
            with patch('server.time.monotonic',return_value=16):
                cache.get(self.t)
            self.assertEqual(calculate.call_count,2)
            cache.invalidate();cache.get(self.t)
            self.assertEqual(calculate.call_count,3)

    def test_live_cache_detects_database_changes(self):
        cache=StateCache(ttl=3600)
        cache.get(self.t)
        self.t.save('teams',{'name':'Added team'})
        self.assertEqual(len(cache.get(self.t)['teams']),2)

    def test_recalculation_preserves_finalized_records_and_flags_corrections(self):
        self.t.import_csv(export('Done',resolved='2026-08-20T09:00:00Z'),'done.csv','2026-08-21')
        self.t.finalize({'month':'2026-08','reason':'Close month'})
        original=self.t.rows("SELECT payload FROM monthly_records WHERE month='2026-08'")
        self.t.correct({'ticket_key':'OP-1','effective_at':'2026-08-01','patch':{'sp':8},'reason':'New evidence'})
        cache=StateCache();state=cache.get(self.t);cache.invalidate();state=cache.get(self.t)
        self.assertEqual(self.t.rows("SELECT payload FROM monthly_records WHERE month='2026-08'"),original)
        self.assertTrue(state['pending_revisions'])
        self.assertEqual(self.t.report('2026-08-01','2026-08-31',_state=state)['sp'],5)

    def test_static_assets_do_not_open_the_database(self):
        handler=object.__new__(Handler)
        handler.path='/styles.css'
        handler.headers={'Host':'127.0.0.1:8765'}
        handler.server=SimpleNamespace(server_port=8765)
        handler.reply=Mock()
        with patch('server.Tracker',side_effect=AssertionError('Static asset opened database')):
            handler.do_GET()
        self.assertEqual(handler.reply.call_args.args[0],200)


if __name__=='__main__':
    unittest.main()
