import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from tracker import Tracker


def export(status='In Progress', comment='', resolved='', severity='High', critical='', assignee='dev-a'):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(['Issue key', 'Summary', 'Status', 'Assignee Id', 'Story Points', 'Priority', 'Resolved', 'Comment', 'Critical At'])
    writer.writerow(['OP-1', 'Payment integration', status, assignee, 5, severity, resolved, comment, critical])
    return out.getvalue()


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Tracker(Path(self.tmp.name) / 'tracker.db')
        self.team = self.t.save('teams', {'name': 'Alpha'})
        self.ids = {}
        for name, role, slot, country in [('Dev A','Dev',None,'JO'), ('TPM A','TPM',None,'DO'), ('QA A','QA','Primary','AM'), ('QA B','QA','Secondary','JO')]:
            self.ids[role + (slot or '')] = self.t.save('members', {'name': name, 'jira_id': name.lower().replace(' ','-'), 'role': role, 'qa_slot': slot, 'country': country, 'team_id': self.team})

    def tearDown(self):
        self.t.db.close()
        self.tmp.cleanup()

    def test_daily_updates_comments_and_duplicate(self):
        one = export(comment=json.dumps({'author':'dev-a','at':'2026-10-19T10:00:00Z','body':'Started'}))
        self.t.import_csv(one, 'day1.csv', '2026-10-19T12:00:00Z')
        self.assertTrue(self.t.import_csv(one, 'again.csv', '2026-10-19T12:00:00Z')['duplicate'])
        self.t.import_csv(export('QA', json.dumps([{'author':'dev-a','at':'2026-10-19T10:00:00Z','body':'Started'},{'author':'tpm-a','at':'2026-10-20T10:00:00Z','body':'Checking'}])), 'day2.csv', '2026-10-20T12:00:00Z')
        detail = self.t.ticket('OP-1')
        self.assertEqual(detail['current']['status'], 'QA')
        self.assertEqual(len(detail['comments']), 2)
        self.assertEqual(len(detail['observations']), 2)
        self.assertTrue(any(e['kind']=='status' and e['from']=='In Progress' and e['to']=='QA' for e in detail['events']))

    def test_reopen_never_duplicates_credit(self):
        for status, day in [('In Progress',19), ('Done',20), ('In Progress',21), ('Done',22)]:
            self.t.import_csv(export(status), 'day.csv', f'2026-10-{day}T12:00:00Z')
        state = self.t.state('2026-10-23T12:00:00Z')
        self.assertEqual(len(state['credits']), 1)
        self.assertEqual(state['credits'][0]['sp'], 5)
        self.assertTrue(state['credits'][0]['at'].startswith('2026-10-20'))

    def test_undated_first_import_done_is_not_assumed_today(self):
        self.t.import_csv(export('Done'), 'historical.csv', '2026-10-20T12:00:00Z')
        state = self.t.state('2026-10-21T12:00:00Z')
        self.assertEqual(state['credits'], [])
        self.assertTrue(state['warnings'])

    def test_country_weekends_and_holidays(self):
        # Friday and Saturday are excluded in Jordan, but Friday counts in DR.
        self.assertEqual(self.t.work('2026-10-23T00:00:00+03:00','2026-10-25T00:00:00+03:00','JO'),0)
        self.assertEqual(self.t.work('2026-10-23T00:00:00-04:00','2026-10-24T00:00:00-04:00','DO'),1)
        self.t.save('holidays', {'country':'JO','day':'2026-10-25','name':'Test holiday'})
        self.assertEqual(self.t.work('2026-10-25T00:00:00+03:00','2026-10-26T00:00:00+03:00','JO'),0)

    def test_conflicting_snapshots_are_rejected_atomically(self):
        self.t.import_csv(export(), 'one.csv', '2026-10-19T12:00:00Z')
        with self.assertRaises(ValueError):
            self.t.import_csv(export('QA'), 'conflict.csv', '2026-10-19T12:00:00Z')
        self.assertEqual(len(self.t.rows('SELECT * FROM imports')),1)

    def test_out_of_order_does_not_regress_current_state(self):
        self.t.import_csv(export('QA'), 'today.csv', '2026-10-20T12:00:00Z')
        self.t.import_csv(export('In Progress'), 'yesterday.csv', '2026-10-19T12:00:00Z')
        self.assertEqual(self.t.ticket('OP-1')['current']['status'],'QA')

    def test_critical_reward_for_dev_tpm_and_both_qas(self):
        self.t.import_csv(export('Done', resolved='2026-10-20T12:00:00Z', severity='Critical', critical='2026-10-19T12:00:00Z'), 'done.csv','2026-10-20T12:00:00Z')
        state = self.t.state('2026-10-21T12:00:00Z')
        self.assertEqual(len(state['score_events']),4)
        self.assertTrue(all(e['points']==1 for e in state['score_events']))

    def test_shared_followup_only_charges_working_owner(self):
        owners = self.t.rows('SELECT * FROM members WHERE role IN (\'Dev\',\'TPM\')')
        events = []
        # Set interval to one day so the breach falls on Friday: Dev in Jordan off, TPM in DR working.
        self.t.followup_events('OP-1','2026-10-22T00:00:00+03:00','2026-10-24T00:00:00+03:00',owners,{'followup_days':1,'followup_initial':2,'followup_daily':1},events)
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]['member_id'],self.ids['TPM'])

    def test_manual_followup_persists_and_validates_author(self):
        self.t.import_csv(export('Blocked'), 'blocked.csv','2026-10-19T12:00:00Z')
        self.t.add_comment({'ticket_key':'OP-1','author_id':self.ids['TPM'],'body':'Contacted vendor','occurred_at':'2026-10-20T12:00:00Z'})
        self.assertEqual(len(self.t.ticket('OP-1')['comments']),1)
        with self.assertRaises(ValueError):
            self.t.add_comment({'ticket_key':'OP-1','author_id':self.ids['QAPrimary'],'body':'Not a qualifying author','occurred_at':'2026-10-20T12:00:00Z'})

    def test_qa_penalties_include_all_owners_and_rule_is_prospective(self):
        self.t.save('rules',{'status':'QA','severity':'High','sp':5,'days':1,'initial':2,'daily':1})
        self.t.db.execute("UPDATE rules SET created_at='2026-10-18T00:00:00+00:00'")
        self.t.db.commit()
        self.t.import_csv(export('QA'),'qa.csv','2026-10-19T12:00:00Z')
        state = self.t.state('2026-10-21T13:00:00Z')
        self.assertEqual({e['member_id'] for e in state['score_events']},set(self.ids.values()))
        again = self.t.state('2026-10-21T13:00:00Z')
        self.assertEqual(state['score_events'],again['score_events'])

    def test_preview_does_not_write_or_unmap_missing_ticket(self):
        self.t.import_csv(export(), 'preview.csv','2026-10-19T12:00:00Z',preview=True)
        self.assertEqual(self.t.rows('SELECT * FROM imports'),[])

    def test_unique_team_roles_and_backup(self):
        with self.assertRaises(Exception):
            self.t.save('members',{'name':'Another TPM','jira_id':'another','role':'TPM','qa_slot':None,'country':'JO','team_id':self.team})
        backup=self.t.backup()
        restored=Tracker(Path(self.tmp.name)/'backups'/backup)
        self.assertEqual(len(restored.rows('SELECT * FROM members')),4)
        restored.db.close()


if __name__ == '__main__':
    unittest.main()
