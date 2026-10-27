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

    def test_performance_review_events_follow_dates_team_and_finalized_records(self):
        self.t.save('rules', dict(status='In Progress',severity='High',sp=5,days=1,initial=2,daily=1,effective_at='2026-07-01T00:00:00Z'))
        self.t.import_csv(export(), 'start.csv', '2026-08-03T00:00:00Z')
        self.t.import_csv(export('Done', resolved='2026-08-07T00:00:00Z'), 'done.csv', '2026-08-07T00:00:00Z')
        report=self.t.report('2026-08-01','2026-08-31',self.a)
        events=report['members'][0]['review_events']
        self.assertTrue(events)
        self.assertTrue(all(e['points']<0 and e['key']=='OP-1' for e in events))
        self.assertEqual(self.t.report('2026-08-01','2026-08-03',self.a)['members'][0]['review_events'],[])
        self.assertEqual(self.t.report('2026-08-01','2026-08-31',self.b)['members'],[])
        self.t.finalize(dict(month='2026-08',reason='Close test month'))
        frozen=self.t.report('2026-08-01','2026-08-31',self.a)['members'][0]['review_events']
        self.assertEqual(frozen,events)

    def test_unassessed_scores_do_not_become_perfect_baselines(self):
        self.assertIsNone(self.t.report('2026-08-01','2026-08-31')['members'][0]['score'])
        self.t.save('rules', dict(status='In Progress',severity='High',sp=5,days=1,initial=2,daily=1,calendar='mon_fri',effective_at='2026-07-01'))
        self.t.import_csv(export(), 'first.csv', '2026-08-03T00:00:00Z')
        short=self.t.state('2026-08-03T01:00:00Z')
        self.assertIsNone(self.t.monthly(self.dev,'2026-08',short)['score'])
        boundary=self.t.state('2026-08-04T00:00:00Z')
        self.assertEqual(self.t.monthly(self.dev,'2026-08',boundary)['score'],100)
        enough=self.t.state('2026-08-05T00:00:00Z')
        assessed=self.t.monthly(self.dev,'2026-08',enough)
        self.assertTrue(assessed['assessed'])
        self.assertLess(assessed['score'],100)
        self.assertIsNone(self.t.monthly(self.dev,'2026-07',enough)['score'])

    def test_delivery_before_membership_cannot_generate_monthly_bonus(self):
        late=self.t.save('members',dict(name='Late Dev',jira_id='late-dev',role='Dev',country='JO',team_id=self.a,effective_at='2026-10-27'))
        self.t.import_csv(export('Closed',resolved='2026-10-10T09:00:00Z',assignee='late-dev'),'closed.csv','2026-10-27T12:00:00Z')
        state=self.t.state('2026-10-27T13:00:00Z')
        monthly=self.t.monthly(late,'2026-10',state)
        report=next(m for m in self.t.report('2026-10-01','2026-10-27',_state=state)['members'] if m['id']==late)
        self.assertEqual(monthly['sp'],0)
        self.assertEqual(monthly['bonus'],0)
        self.assertIsNone(monthly['score'])
        self.assertEqual(report['sp'],monthly['sp'])

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

    def test_reopen_after_archived_role_replacement(self):
        for role, slot in [('TPM', None), ('QA', 'Primary')]:
            original = self.t.save('members', {'name':role, 'jira_id':role, 'role':role,
                'qa_slot':slot, 'country':'JO', 'team_id':self.a, 'effective_at':'2026-07-01'})
            self.t.archive({'resource':'members', 'id':original, 'effective_at':'2026-08-01'})
            self.t.save('members', {'name':role+' replacement', 'jira_id':role+'-new', 'role':role,
                'qa_slot':slot, 'country':'JO', 'team_id':self.a, 'effective_at':'2026-08-02'})
        reopened = Tracker(self.t.path)
        self.assertEqual(len(reopened.members_at('2026-09-01T00:00:00+00:00')), 3)
        reopened.db.close()

    def test_finalized_report_keeps_membership_after_backdated_archive(self):
        self.t.import_csv(export('Done', resolved='2026-08-20T09:00:00Z'), 'done.csv', '2026-08-21')
        self.t.finalize({'month':'2026-08', 'reason':'Close month'})
        before = self.t.report('2026-08-01', '2026-08-31')
        self.t.archive({'resource':'members', 'id':self.dev, 'effective_at':'2026-08-01'})
        after = self.t.report('2026-08-01', '2026-08-31')
        self.assertEqual(after['sp'], before['sp'])
        self.assertEqual(after['target'], before['target'])
        self.assertEqual(after['score'], before['score'])
        self.assertTrue(self.t.state()['pending_revisions'])
        self.t.finalize({'month':'2026-08', 'reason':'Approve inactive month', 'revise':True})
        self.assertEqual(self.t.report('2026-08-01', '2026-08-31')['members'], [])

    def test_revision_flags_changed_evidence_even_when_totals_match(self):
        self.t.import_csv(export('Done', resolved='2026-08-20T09:00:00Z'), 'done.csv', '2026-08-21')
        self.t.finalize({'month':'2026-08', 'reason':'Close month'})
        self.t.correct({'ticket_key':'OP-1', 'effective_at':'2026-08-01',
            'patch':{'resolved':'2026-08-21T09:00:00Z'}, 'reason':'Correct completion day'})
        self.assertTrue(self.t.state()['pending_revisions'])

    def test_correction_applies_without_another_import(self):
        self.t.import_csv(export('In Progress'), 'active.csv', '2026-08-01')
        self.t.correct({'ticket_key':'OP-1', 'effective_at':'2026-08-03',
            'patch':{'sp':8}, 'reason':'Repair estimate'})
        self.assertEqual(self.t.state('2026-08-02')['tickets'][0]['sp'], 5)
        current=self.t.state('2026-08-04')['tickets'][0]
        self.assertEqual(current['sp'], 8)
        self.assertEqual(current['last_seen'], '2026-08-01T00:00:00+00:00')
        self.assertEqual(len(self.t.rows('SELECT * FROM observations')), 1)

    def test_corrupt_backup_preserves_active_database(self):
        folder=self.t.path.parent/'backups'
        folder.mkdir(exist_ok=True)
        (folder/'broken.sqlite3').write_bytes(b'not a database')
        with self.assertRaises(sqlite3.DatabaseError):
            self.t.restore({'filename':'broken.sqlite3'})
        self.assertEqual(self.t.rows('PRAGMA integrity_check')[0]['integrity_check'], 'ok')
        self.assertEqual(len(self.t.rows('SELECT * FROM teams')), 2)

    def test_invalid_backup_schema_is_rejected_before_replacement(self):
        folder=self.t.path.parent/'backups'
        folder.mkdir(exist_ok=True)
        invalid=sqlite3.connect(folder/'invalid.sqlite3')
        try:
            invalid.executescript('CREATE TABLE members(id); CREATE TABLE observations(id); CREATE TABLE imports(id);')
        finally:
            invalid.close()
        with self.assertRaises(ValueError):
            self.t.restore({'filename':'invalid.sqlite3'})
        self.assertEqual(len(self.t.rows('SELECT * FROM teams')),2)
        self.assertEqual(len(self.t.rows('SELECT * FROM members')),1)

    def test_backup_retention_and_unicode_paths(self):
        folder=Path(self.folder.name)/'مسار with spaces'
        other=Tracker(folder/'tracker.sqlite3')
        try:
            other.save('teams', {'name':'فريق العمليات'})
            for _ in range(32):
                other.backup()
            self.assertEqual(len(other.backups()), 30)
            other.restore({'filename':other.backups()[-1]['filename']})
            self.assertEqual(other.rows('SELECT name FROM teams')[0]['name'], 'فريق العمليات')
        finally:
            other.db.close()

    def test_policy_change_during_followup_is_prospective(self):
        self.t.import_csv(export('Blocked'), 'blocked.csv', '2026-08-02T00:00:00Z')
        self.t.update_settings({'followup_initial':7, 'followup_daily':4,
            'effective_at':'2026-08-03T00:00:00Z'})
        events=self.t.state('2026-08-06T12:00:00Z')['score_events']
        self.assertEqual([e['points'] for e in events], [-7, -4])
        self.assertTrue(all(e['at']>'2026-08-03T00:00:00+00:00' for e in events))

    def test_archived_owner_is_not_charged_without_new_import(self):
        self.t.save('rules', {'status':'In Progress','severity':'High','sp':5,
            'days':1,'initial':2,'daily':1,'effective_at':'2026-07-01'})
        self.t.import_csv(export('In Progress'), 'active.csv', '2026-08-02')
        self.t.archive({'resource':'members','id':self.dev,'effective_at':'2026-08-03'})
        events=self.t.state('2026-08-10')['score_events']
        self.assertFalse(any(e['at']>='2026-08-03T00:00:00+00:00' for e in events))

    def test_role_change_has_no_tpm_utilization_target(self):
        self.t.save('members', {'id':self.dev,'name':'Former developer','jira_id':'dev-a',
            'role':'TPM','country':'JO','team_id':self.a,'effective_at':'2026-08-16'})
        result=self.t.report('2026-08-01','2026-08-31',role='TPM')
        self.assertEqual(result['target'],0)
        self.assertIsNone(result['members'][0]['util'])
        self.assertIsNone(result['members'][0]['score'])
        self.assertEqual(result['members'][0]['assessment_status'],'Not yet assessed')

    def test_normal_penalty_exact_boundary_and_handover_no_duplicates(self):
        self.t.save('rules', {'status':'In Progress','severity':'High','sp':5,
            'days':1,'initial':2,'daily':1,'effective_at':'2026-07-01'})
        self.t.import_csv(export('In Progress'), 'active.csv', '2026-08-02T09:00:00Z')
        self.assertEqual(self.t.state('2026-08-03T09:00:00Z')['score_events'],[])
        early=self.t.state('2026-08-03T09:00:01Z')['score_events']
        self.assertEqual([e['points'] for e in early],[-2])
        self.t.save('members', {'id':self.dev,'name':'Dev A','jira_id':'dev-a',
            'role':'Dev','country':'JO','team_id':self.b,'effective_at':'2026-08-04T09:00:00Z'})
        events=self.t.state('2026-08-05T10:00:00Z')['score_events']
        self.assertEqual([e['points'] for e in events],[-2,-1,-1])
        self.assertEqual(len({(e['member_id'],e['at']) for e in events}),len(events))

    def test_late_manual_followup_uses_historical_author(self):
        first=self.t.save('members',{'name':'Previous TPM','jira_id':'previous', 'role':'TPM',
            'country':'DO','team_id':self.a,'effective_at':'2026-07-01'})
        self.t.import_csv(export('Blocked'),'blocked.csv','2026-08-02')
        self.t.archive({'resource':'members','id':first,'effective_at':'2026-08-05'})
        self.t.add_comment({'ticket_key':'OP-1','author_id':first,'body':'Historical follow-up',
            'occurred_at':'2026-08-04T12:00:00Z'})
        self.assertEqual(self.t.ticket('OP-1')['comments'][0]['author'],'previous')
        with self.assertRaises(ValueError):
            self.t.add_comment({'ticket_key':'OP-1','author_id':first,'body':'After leaving',
                'occurred_at':'2026-08-06T12:00:00Z'})

    def test_monthly_bonus_and_inactive_months(self):
        raw=export('Done',resolved='2026-08-20T09:00:00Z').replace(',5,High,',',20,High,')
        self.t.import_csv(raw,'done.csv','2026-08-21')
        self.assertEqual(self.t.monthly(self.dev,'2026-08')['score'],110)
        self.t.archive({'resource':'members','id':self.dev,'effective_at':'2026-09-01'})
        report=self.t.report('2026-08-01','2026-09-30')
        self.assertEqual(report['members'][0]['score'],110)
        self.assertEqual(len(report['members'][0]['months']),1)

    def test_critical_reward_requires_evidence_and_stays_separate_from_sp(self):
        self.t.import_csv(export('Done', resolved='2026-08-20T09:00:00Z',severity='Critical'),
            'done.csv','2026-08-21')
        self.assertEqual(self.t.state()['score_events'],[])
        self.t.correct({'ticket_key':'OP-1','effective_at':'2026-08-01',
            'patch':{'critical_at':'2026-08-19T09:00:00Z'},'reason':'Verified history'})
        month=self.t.monthly(self.dev,'2026-08')
        self.assertEqual(month['critical'],1)
        self.assertEqual(month['sp'],5)

    def test_critical_reward_uses_calendar_when_marked_critical(self):
        self.t.update_settings({'critical_days':1,'critical_reward':2,'effective_at':'2026-07-01'})
        self.t.import_csv(export('In Progress',severity='Critical',critical='2026-10-22T12:00:00Z'),
            'critical.csv','2026-10-22T12:00:00Z')
        self.t.save('members',{'id':self.dev,'name':'Dev A','jira_id':'dev-a','role':'Dev',
            'country':'DO','team_id':self.a,'effective_at':'2026-10-23'})
        self.t.import_csv(export('Done',severity='Critical',critical='2026-10-22T12:00:00Z',resolved='2026-10-25T12:00:00Z'),
            'done.csv','2026-10-25T12:00:00Z')
        events=self.t.state('2026-10-26')['score_events']
        self.assertEqual([e['points'] for e in events],[2])
        self.assertIn('JO calendar',events[0]['reason'])

    def test_larger_csv_and_roster_keep_all_sources(self):
        for index in range(31):
            self.t.save('members',{'name':'اسم طويل للاختبار '*6+str(index),
                'jira_id':f'bulk-{index}','role':'Dev','country':'AM','team_id':self.a,'effective_at':'2026-07-01'})
        output=io.StringIO();writer=csv.writer(output)
        writer.writerow(['Issue key','Summary','Status','Assignee Id','Story Points','Priority','Resolved'])
        for index in range(1000):
            writer.writerow([f'BULK-{index+1}','اختبار استيراد','Done',f'bulk-{index%31}',1,'High','2026-08-20T09:00:00Z'])
        raw=output.getvalue()
        self.assertEqual(self.t.import_csv(raw,'bulk.csv','2026-08-21',preview=True)['count'],1000)
        self.assertEqual(self.t.rows('SELECT * FROM imports'),[])
        self.t.import_csv(raw,'bulk.csv','2026-08-21')
        report=self.t.report('2026-08-01','2026-08-31')
        self.assertEqual(report['sp'],1000)
        self.assertEqual(report['target'],512)
        self.assertEqual(self.t.rows('SELECT raw FROM imports')[0]['raw'],raw)

    def test_mid_status_rule_change_keeps_earlier_penalties(self):
        identity=self.t.save('rules',{'status':'In Progress','severity':'High','sp':5,
            'days':1,'initial':2,'daily':1,'effective_at':'2026-07-01'})
        self.t.import_csv(export('In Progress'),'active.csv','2026-08-02T09:00:00Z')
        before=self.t.state('2026-08-04T08:00:00Z')['score_events']
        self.t.save('rules',{'id':identity,'status':'In Progress','severity':'High','sp':5,
            'days':1,'initial':7,'daily':4,'effective_at':'2026-08-04T08:00:00Z'})
        events=self.t.state('2026-08-05T10:00:00Z')['score_events']
        self.assertEqual(events[:len(before)],before)
        self.assertEqual([e['points'] for e in events],[-2,-4,-4])

    def test_import_discovers_statuses_without_guessing_accountability(self):
        raw=export('Custom Review')
        self.t.import_csv(raw,'preview.csv','2026-08-02',preview=True)
        self.assertFalse(self.t.rows('SELECT name FROM workflow WHERE name=?',('Custom Review',)))
        self.t.import_csv(raw,'commit.csv','2026-08-02')
        self.assertEqual(self.t.workflow_at('Custom Review')['category'],'unconfigured')
        self.assertEqual(json.loads(self.t.workflow_at('Custom Review')['roles']),[])
        self.t.save('rules',{'status':'Custom Review','severity':'High','sp':5,'days':1,
            'initial':2,'daily':1,'effective_at':'2026-07-01'})
        self.assertEqual(self.t.state('2026-08-10')['score_events'],[])
        self.t.save('workflow',{'name':'custom review','category':'active','roles':['Dev']})
        self.assertTrue(self.t.state('2026-08-10')['score_events'])
        self.assertEqual(len(self.t.rows('SELECT name FROM workflow WHERE lower(name)=?',('custom review',))),1)

    def test_status_discovery_preserves_existing_configuration(self):
        self.t.save('workflow',{'name':'QA Review','category':'active','roles':['Dev','QA','TPM']})
        self.assertEqual(self.t.discover_workflow(['QA Review','qa review','New Status','New Status']),['New Status'])
        self.assertEqual(self.t.workflow_at('QA Review')['category'],'active')
        reopened=Tracker(self.t.path)
        try:
            self.assertEqual(reopened.workflow_at('New Status')['category'],'unconfigured')
        finally:
            reopened.db.close()

    def test_priority_discovery_and_configuration(self):
        raw=export('In Progress',severity='Urgent')
        self.t.import_csv(raw,'preview.csv','2026-08-02',preview=True)
        self.assertFalse(self.t.rows('SELECT name FROM priorities WHERE name=?',('Urgent',)))
        self.t.import_csv(raw,'commit.csv','2026-08-02')
        self.assertTrue(self.t.rows('SELECT name FROM priorities WHERE name=?',('Urgent',)))
        self.assertFalse(self.t.is_critical('Urgent'))
        self.t.save('priorities',{'name':'Urgent','critical':True})
        self.assertTrue(self.t.is_critical('Urgent'))
        self.t.discover_priorities(['urgent','Urgent'])
        self.assertEqual(len(self.t.rows('SELECT name FROM priorities WHERE lower(name)=?',('urgent',))),1)
        self.t.save('priorities',{'name':'Urgent','critical':False})
        self.assertFalse(self.t.is_critical('Urgent'))
        self.assertTrue(self.t.is_critical('Critical'))

    def test_existing_priorities_are_backfilled_on_restart(self):
        self.t.import_csv(export(severity='Medium'),'medium.csv','2026-08-02')
        with self.t.db:
            self.t.db.execute('DELETE FROM priorities')
        reopened=Tracker(self.t.path)
        try:
            self.assertTrue(reopened.rows('SELECT name FROM priorities WHERE name=?',('Medium',)))
        finally:
            reopened.db.close()

    def shared_member(self, role='TPM', effective='2026-07-01'):
        return self.t.save('members',{'name':'Shared '+role,'jira_id':'shared-'+role,'role':role,'country':'JO',
            'effective_at':effective,'team_assignments':[{'team_id':self.a,'qa_slot':'Primary' if role=='QA' else None},
                {'team_id':self.b,'qa_slot':'Secondary' if role=='QA' else None}]})

    def test_shared_tpm_and_qa_own_tickets_in_both_teams(self):
        tpm=self.shared_member();qa=self.shared_member('QA')
        self.t.save('members',{'name':'Dev B','jira_id':'dev-b','role':'Dev','country':'JO','team_id':self.b,'effective_at':'2026-07-01'})
        self.t.save('rules',{'status':'QA','severity':'High','sp':5,'days':1,'initial':2,'daily':1,'effective_at':'2026-07-01'})
        self.t.import_csv(export('QA'),'a.csv','2026-08-02T09:00:00Z')
        self.t.import_csv(export('QA',assignee='dev-b').replace('OP-1','OP-2'),'b.csv','2026-08-02T09:00:00Z')
        for key,team,slot in [('OP-1',self.a,'Primary'),('OP-2',self.b,'Secondary')]:
            owners=self.t.ticket(key)['current']['owners']
            self.assertEqual(sum(m['id']==tpm for m in owners),1)
            self.assertEqual(sum(m['id']==qa for m in owners),1)
            self.assertEqual(next(m for m in owners if m['id']==qa)['qa_slot'],slot)
            self.assertTrue(all(m['team_id']==team for m in owners))
        events=self.t.state('2026-08-03T10:00:00Z')['score_events']
        self.assertEqual(len([e for e in events if e['member_id']==tpm]),2)
        self.assertEqual(len([e for e in events if e['member_id']==qa]),2)
        self.assertEqual(len({(e['key'],e['member_id'],e['at']) for e in events}),len(events))

    def test_shared_members_filter_into_each_team_without_global_duplicates(self):
        tpm=self.shared_member();qa=self.shared_member('QA')
        all_rows=self.t.report('2026-08-01','2026-08-31')['members']
        self.assertEqual(len([m for m in all_rows if m['id']==tpm]),1)
        self.assertEqual(len([m for m in all_rows if m['id']==qa]),1)
        for team in [self.a,self.b]:
            report=self.t.report('2026-08-01','2026-08-31',team)
            for identity in [tpm,qa]:
                member=next(m for m in report['members'] if m['id']==identity)
                self.assertEqual(member['target'],0)
                self.assertIsNone(member['util'])
        self.assertAlmostEqual(self.t.report('2026-08-01','2026-08-31')['target'],16)

    def test_shared_qa_slots_allow_colleagues_and_keep_tpm_exclusive(self):
        self.shared_member();qa=self.shared_member('QA')
        with self.assertRaises(ValueError):
            self.t.save('members',{'name':'Other TPM','jira_id':'other-tpm','role':'TPM','country':'JO','team_id':self.b,'effective_at':'2026-08-01'})
        other_qa=self.t.save('members',{'name':'Other QA','jira_id':'other-qa','role':'QA','country':'JO','team_id':self.b,'qa_slot':'Secondary','effective_at':'2026-08-01'})
        self.assertTrue(other_qa)
        with self.assertRaises(ValueError):
            self.t.archive({'resource':'teams','id':self.b})
        self.t.archive({'resource':'members','id':qa,'effective_at':'2026-08-01'})
        self.t.save('members',{'name':'Replacement QA','jira_id':'replacement-qa','role':'QA','country':'JO','team_id':self.b,'qa_slot':'Secondary','effective_at':'2026-08-02'})
        self.t.archive({'resource':'members','id':qa,'archived':False,'effective_at':'2026-08-03'})
        reopened=Tracker(self.t.path)
        self.assertEqual(len([m for m in reopened.members_at('2026-08-04') if m['role']=='QA']),3)
        reopened.db.close()

    def test_shared_assignments_restart_history_and_frozen_report(self):
        identity=self.shared_member()
        self.t.finalize({'month':'2026-08','reason':'Close month'})
        self.t.save('members',{'id':identity,'name':'Shared TPM','jira_id':'shared-TPM','role':'TPM','country':'JO',
            'team_id':self.a,'effective_at':'2026-08-01'})
        self.assertTrue(any(m['id']==identity for m in self.t.report('2026-08-01','2026-08-31',self.b)['members']))
        self.assertTrue(self.t.state()['pending_revisions'])
        reopened=Tracker(self.t.path)
        try:
            from tracker import in_team
            old=next(m for m in reopened.members_at('2026-07-20T00:00:00+00:00') if m['id']==identity)
            self.assertTrue(in_team(old,self.b))
            current=next(m for m in reopened.members_at('2026-09-01T00:00:00+00:00') if m['id']==identity)
            self.assertFalse(in_team(current,self.b))
        finally:
            reopened.db.close()

    def test_shared_tpm_can_follow_up_on_secondary_team(self):
        identity=self.shared_member()
        self.t.save('members',{'name':'Dev B','jira_id':'dev-b','role':'Dev','country':'JO','team_id':self.b,'effective_at':'2026-07-01'})
        self.t.import_csv(export('Blocked',assignee='dev-b'),'blocked.csv','2026-08-02')
        self.t.add_comment({'ticket_key':'OP-1','author_id':identity,'body':'Shared TPM follow-up','occurred_at':'2026-08-04'})
        events=self.t.state('2026-08-06')['score_events']
        self.assertEqual(events,[])

    def test_developer_cannot_have_multiple_teams(self):
        with self.assertRaises(ValueError):
            self.shared_member('Dev')

    def test_secondary_team_added_without_new_csv_changes_future_owners_only(self):
        identity=self.t.save('members',{'name':'Shared QA','jira_id':'shared-QA','role':'QA','country':'JO',
            'team_id':self.a,'qa_slot':'Primary','effective_at':'2026-07-01'})
        self.t.save('members',{'name':'Dev B','jira_id':'dev-b','role':'Dev','country':'JO','team_id':self.b,'effective_at':'2026-07-01'})
        self.t.import_csv(export('QA',assignee='dev-b'),'qa.csv','2026-08-02')
        self.t.save('members',{'id':identity,'name':'Shared QA','jira_id':'shared-QA','role':'QA','country':'JO',
            'team_assignments':[{'team_id':self.a,'qa_slot':'Primary'},{'team_id':self.b,'qa_slot':'Secondary'}],
            'effective_at':'2026-08-04'})
        before=self.t.state('2026-08-03')['tickets'][0]
        after=self.t.state('2026-08-05')['tickets'][0]
        self.assertFalse(any(m['id']==identity for m in before['owners']))
        self.assertTrue(any(m['id']==identity for m in after['owners']))
        self.assertEqual(after['last_seen'],'2026-08-02T00:00:00+00:00')

    def test_shared_critical_rewards_are_once_per_person_per_ticket(self):
        tpm=self.shared_member();qa=self.shared_member('QA')
        self.t.save('members',{'name':'Dev B','jira_id':'dev-b','role':'Dev','country':'JO','team_id':self.b,'effective_at':'2026-07-01'})
        self.t.import_csv(export('Done',assignee='dev-b',severity='Critical',critical='2026-08-02T09:00:00Z',resolved='2026-08-03T09:00:00Z'),
            'done.csv','2026-08-03T12:00:00Z')
        state=self.t.state('2026-08-04')
        self.assertEqual(sum(e['points'] for e in state['score_events'] if e['member_id']==tpm),1)
        self.assertEqual(sum(e['points'] for e in state['score_events'] if e['member_id']==qa),1)
        self.assertEqual(sum(c['sp'] for c in state['credits']),5)


if __name__=='__main__':unittest.main()
