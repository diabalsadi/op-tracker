import io
import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from advanced import Tracker
from test_tracker import export


class HistoricalTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.t=Tracker(Path(self.folder.name)/'tracker.sqlite3')
        self.a=self.t.save('teams',{'name':'Alpha'})
        self.b=self.t.save('teams',{'name':'Beta'})
        self.dev=self.t.save('members',{'name':'Dev A','jira_id':'dev-a','role':'Dev','qa_slot':None,'country':'JO','team_id':self.a,'effective_at':'2026-07-01T00:00:00Z'})

    def tearDown(self):
        self.t.db.close();self.folder.cleanup()

    def test_membership_prorates_transfer_and_quarter(self):
        q=self.t.report('2026-07-01','2026-09-30')
        self.assertAlmostEqual(q['target'],48)
        self.t.save('members',{'id':self.dev,'name':'Dev A','jira_id':'dev-a','role':'Dev','qa_slot':None,'country':'JO','team_id':self.b,'effective_at':'2026-08-01T00:00:00Z'})
        self.assertAlmostEqual(self.t.report('2026-07-01','2026-09-30',self.a)['target'],16)
        self.assertAlmostEqual(self.t.report('2026-07-01','2026-09-30',self.b)['target'],32)
        self.assertEqual(self.t.report('2026-01-01','2026-06-30')['members'],[])

    def test_rule_versions_retain_old_values(self):
        r=self.t.save('rules',{'status':'QA','severity':'High','sp':5,'days':2,'initial':2,'daily':1,'effective_at':'2026-07-01T00:00:00Z'})
        self.t.save('rules',{'id':r,'status':'QA','severity':'High','sp':5,'days':4,'initial':8,'daily':3,'effective_at':'2026-08-01T00:00:00Z'})
        self.assertEqual(self.t.rules_at('QA','High',5,'2026-07-20T00:00:00+00:00')[0]['days'],2)
        self.assertEqual(self.t.rules_at('QA','High',5,'2026-08-20T00:00:00+00:00')[0]['initial'],8)

    def test_finalized_month_is_immutable_until_revision(self):
        self.t.import_csv(export('Done',resolved='2026-08-20T09:00:00Z'),'done.csv','2026-08-21T12:00:00Z')
        self.t.finalize({'month':'2026-08','reason':'Close month'})
        old=self.t.report('2026-08-01','2026-08-31')['members'][0]
        self.t.correct({'ticket_key':'OP-1','effective_at':'2026-08-01T00:00:00Z','patch':{'sp':8},'reason':'Correct source estimate'})
        frozen=self.t.report('2026-08-01','2026-08-31')['members'][0]
        self.assertEqual(old['sp'],5);self.assertEqual(frozen['sp'],5)
        self.t.finalize({'month':'2026-08','reason':'Approved evidence correction','revise':True})
        self.assertEqual(self.t.report('2026-08-01','2026-08-31')['members'][0]['sp'],8)
        self.assertEqual(len(self.t.rows('SELECT * FROM monthly_records')),2)

    def test_finalized_targets_survive_calendar_and_policy_changes(self):
        self.t.finalize({'month':'2026-08','reason':'Close month'})
        before=self.t.report('2026-08-01','2026-08-31')['target']
        self.t.save('holidays',{'country':'JO','day':'2026-08-03','name':'Late calendar correction'})
        self.assertAlmostEqual(self.t.report('2026-08-01','2026-08-31')['target'],before)

    def test_archive_preserves_history_and_frees_slot(self):
        self.t.archive({'resource':'members','id':self.dev,'effective_at':'2026-09-01T00:00:00Z'})
        self.assertEqual(self.t.report('2026-09-01','2026-09-30')['members'],[])
        self.assertAlmostEqual(self.t.report('2026-08-01','2026-08-31')['target'],16)
        self.t.archive({'resource':'members','id':self.dev,'archived':False,'effective_at':'2026-10-01T00:00:00Z'})
        self.assertEqual(self.t.report('2026-09-01','2026-09-30')['members'],[])
        self.assertAlmostEqual(self.t.report('2026-10-01','2026-10-26')['target'],self.t.target(self.dev,'2026-10-01T00:00:00+00:00','2026-10-27T00:00:00+00:00'))

    def test_saved_profile_sprint_and_workflow(self):
        self.t.save('import_profiles',{'name':'Wide CSV','mapping':{'key':'Issue key','_timezone':'Asia/Amman'}})
        self.t.save('sprints',{'name':'Sprint 1','start_date':'2026-08-01','end_date':'2026-08-14','team_id':self.a})
        self.t.save('workflow',{'name':'Released','category':'done','roles':[]})
        self.t.import_csv(export('Released',resolved='2026-08-12T09:00:00Z'),'released.csv','2026-08-13T12:00:00Z')
        self.assertEqual(len(self.t.state('2026-08-14T00:00:00Z')['credits']),1)
        self.assertEqual(len(self.t.rows('SELECT * FROM import_profiles')),1)

    def test_jira_wide_export_dates_comments_and_aggregate_durations(self):
        stream=io.StringIO();w=csv.writer(stream)
        w.writerow(['Issue key','Status','Assignee Id','Custom field (Story Points)','Resolved','Comment','Comment','Custom field ([CHART] Time in Status)','Sprint','Sprint'])
        w.writerow(['OP-2','Closed','dev-a',3,'10/15/2026 3:49','14/Oct/26 1:18 PM;dev-a;One','15/Oct/26 1:18 PM;dev-a;Two','3_*:*_1_*:*_3600000','Sprint A','Sprint B'])
        self.t.import_csv(stream.getvalue(),'wide.csv','2026-10-16T12:00:00Z',{'_timezone':'Asia/Amman'})
        t=self.t.ticket('OP-2');self.assertEqual(len(t['comments']),2);self.assertEqual(len(t['current']['sprints']),2)
        self.assertTrue(t['current']['resolved'].startswith('2026-10-15T00:49'))
        self.t.save('status_id_mappings',{'status_id':'3','status_name':'In Progress','unit':'milliseconds'})
        self.assertAlmostEqual(self.t.ticket('OP-2')['current']['time_in_status'][0]['hours'],1)

    def test_backup_restore_validates_filename_and_database(self):
        name=self.t.backup();self.t.save('teams',{'name':'Temporary'})
        self.t.restore({'filename':name})
        self.assertFalse(self.t.rows('SELECT id FROM teams WHERE name=?',('Temporary',)))
        with self.assertRaises(ValueError):self.t.restore({'filename':'../tracker.sqlite3'})

    def test_export_and_formulas_are_safe(self):
        csvtext=self.t.export({'start_date':'2026-07-01','end_date':'2026-09-30'})['csv']
        self.assertIn('48.0',csvtext)

    def test_policy_versions_prospective(self):
        self.t.update_settings({'monthly_target':20,'effective_at':'2026-09-01T00:00:00Z'})
        self.assertAlmostEqual(self.t.report('2026-08-01','2026-08-31')['target'],16)
        self.assertAlmostEqual(self.t.report('2026-09-01','2026-09-30')['target'],20)

    def test_holiday_range_and_edit_remove(self):
        self.t.save('holidays',{'country':'JO','day':'2026-08-02','end_day':'2026-08-04','name':'Three days'})
        self.assertEqual(len(self.t.rows('SELECT * FROM holidays')),3)
        holiday=self.t.rows('SELECT * FROM holidays')[0]
        self.t.remove_holiday({'id':holiday['id']})
        self.assertEqual(len(self.t.rows('SELECT * FROM holidays')),2)

    def test_finalized_evidence_changes_are_flagged(self):
        self.t.import_csv(export('Done',resolved='2026-08-20T09:00:00Z'),'done.csv','2026-08-21T12:00:00Z')
        self.t.finalize({'month':'2026-08','reason':'Close month'})
        self.t.correct({'ticket_key':'OP-1','effective_at':'2026-08-01T00:00:00Z','patch':{'sp':8},'reason':'Source correction'})
        self.assertEqual(len(self.t.state()['pending_revisions']),1)

    def test_persisted_custom_critical_priority_names(self):
        self.t.save('critical_priorities',{'names':['Urgent']})
        reopened=Tracker(self.t.path)
        self.assertTrue(reopened.is_critical('Urgent'));self.assertFalse(reopened.is_critical('Critical'))
        reopened.db.close()

    def test_manual_comment_revisions_preserve_original(self):
        self.t.import_csv(export('Blocked'),'blocked.csv','2026-10-19T12:00:00Z')
        self.t.add_comment({'ticket_key':'OP-1','author_id':self.dev,'body':'Original','occurred_at':'2026-10-20T10:00:00Z'})
        comment=self.t.ticket('OP-1')['comments'][0]
        self.t.revise_comment({'id':comment['manual_id'],'body':'Corrected','occurred_at':'2026-10-20T11:00:00Z','reason':'Correct occurrence time'})
        self.assertEqual(self.t.ticket('OP-1')['comments'][0]['body'],'Corrected')
        self.assertEqual(self.t.rows('SELECT body FROM manual_comments')[0]['body'],'Original')

    def test_tpm_handover_keeps_followup_deadline_without_new_csv(self):
        first=self.t.save('members',{'name':'TPM First','jira_id':'tpm-first','role':'TPM','qa_slot':None,'country':'DO','team_id':self.a,'effective_at':'2026-07-01T00:00:00Z'})
        self.t.import_csv(export('Blocked'),'blocked.csv','2026-10-19T12:00:00Z')
        self.t.archive({'resource':'members','id':first,'effective_at':'2026-10-21T12:00:00Z'})
        second=self.t.save('members',{'name':'TPM Next','jira_id':'tpm-next','role':'TPM','qa_slot':None,'country':'DO','team_id':self.a,'effective_at':'2026-10-21T12:00:01Z'})
        result=self.t.state('2026-10-23T13:00:00Z')
        events=result['score_events']
        self.assertTrue(any(e['member_id']==second and e['points']<0 for e in events))
        self.assertFalse(any(e['member_id']==first for e in events))
        self.assertTrue(result['tickets'][0]['last_seen'].startswith('2026-10-19'))

    def test_legacy_database_upgrade_retains_ticket_sources(self):
        from tracker import Tracker as LegacyTracker
        path=Path(self.folder.name)/'legacy.sqlite3'
        legacy=LegacyTracker(path)
        team=legacy.save('teams',{'name':'Old team'})
        legacy.save('members',{'name':'Dev A','jira_id':'dev-a','role':'Dev','qa_slot':None,'country':'JO','team_id':team})
        legacy.import_csv(export('Done',resolved='2026-08-20T09:00:00Z'),'old.csv','2026-08-21T12:00:00Z')
        legacy.db.close()
        upgraded=Tracker(path)
        self.assertEqual(len(upgraded.ticket('OP-1')['observations']),1)
        self.assertEqual(len(upgraded.state()['credits']),1)
        self.assertEqual(len(upgraded.rows('SELECT * FROM member_versions')),1)
        upgraded.db.close()

    def test_future_and_invalid_sprints_rejected(self):
        with self.assertRaises(ValueError):self.t.save('sprints',{'name':'Bad','start_date':'2026-08-20','end_date':'2026-08-01'})
        with self.assertRaises(ValueError):self.t.finalize({'month':'2099-01','reason':'Not allowed'})


if __name__=='__main__':unittest.main()
