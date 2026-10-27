import sqlite3
import tempfile
import unittest
from pathlib import Path
from advanced import Tracker


class PortableRulesTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.t = Tracker(Path(self.folder.name) / 'tracker.sqlite3')

    def tearDown(self):
        self.t.db.close()
        self.folder.cleanup()

    def rule(self, **extra):
        data = dict(status='QA', severity='*', sp=-1, days=1, initial=2,
                    daily=1, calendar='mon_fri', effective_at='2026-01-01T00:00:00Z')
        data.update(extra)
        return self.t.save('rules', data)

    def test_wildcards_specificity_and_effective_history(self):
        general = self.rule()
        specific = self.rule(severity='High', sp=3, days=2)
        at = '2026-07-01T00:00:00+00:00'
        self.assertEqual(self.t.rules_at('qa', 'Future priority', None, at)[0]['id'], general)
        self.assertEqual(self.t.rules_at('QA', 'High', 3, at)[0]['id'], specific)
        self.assertEqual(self.t.rules_at('QA', 'High', 8, at)[0]['id'], general)
        self.assertEqual(self.t.rules_at('QA', 'High', 8, '2025-01-01'), [])
        self.t.discover_priorities(['*', 'High'])
        self.assertNotIn('*', [r['name'] for r in self.t.rows('SELECT name FROM priorities')])
        self.t.save('rules', dict(id=general, status='QA', severity='*', sp=-1,
                    days=4, initial=2, daily=1, calendar='country', effective_at=at))
        self.assertEqual(self.t.rules_at('QA', 'Other', 8, '2026-02-01')[0]['calendar'], 'mon_fri')
        self.assertEqual(self.t.rules_at('QA', 'Other', 8, at)[0]['calendar'], 'country')

    def test_mon_fri_strict_breach_and_country_calendar_preserved(self):
        # Friday is a country weekend in Jordan, but a business day for this rule.
        start = '2026-10-23T00:00:00+03:00'
        end = '2026-10-24T00:00:00+03:00'
        self.assertEqual(self.t.work(start, end, 'JO'), 0)
        self.assertEqual(self.t.work(start, end, 'JO', (5, 6)), 1)
        rule = dict(id=1, status='QA', days=1, initial=2, daily=1, calendar='mon_fri')
        events = []
        self.t.penalty_events('TEST-1', start, end, dict(id=1, country='JO'), rule, events)
        self.assertEqual(events, [])
        self.t.penalty_events('TEST-1', start, '2026-10-26T01:00:00+03:00', dict(id=1, country='JO'), rule, events)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['points'], -2)

    def test_export_is_complete_readable_snapshot(self):
        self.rule()
        path = Path(self.folder.name) / 'export.sqlite3'
        path.write_bytes(self.t.export_database())
        with sqlite3.connect(path) as exported:
            self.assertEqual(exported.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(exported.execute('SELECT count(*) FROM rule_versions').fetchone()[0], 1)
            self.assertEqual(exported.execute('SELECT calendar FROM rules').fetchone()[0], 'mon_fri')
            self.assertEqual(exported.execute('SELECT count(*) FROM audit').fetchone()[0], self.t.rows('SELECT count(*) n FROM audit')[0]['n'])
