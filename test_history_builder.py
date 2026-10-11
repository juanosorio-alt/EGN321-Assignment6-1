"""Run with: python -m unittest -v"""
import copy
import sqlite3
import tempfile
import unittest
from pathlib import Path
from history_builder import (ROOT,read_primary,read_instructor,write_database,
    query_history,detect_gaps,summarize,plot_segments)


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.rows=read_primary(ROOT/'data/readings_failure_scenario.csv')
        self.temp=tempfile.TemporaryDirectory()
        self.db=Path(self.temp.name)/'test.db'
    def tearDown(self):
        self.temp.cleanup()
    def test_logging_preserves_raw_rejected_missing_and_identity(self):
        write_database(self.db,self.rows,{'interval':1})
        actual=query_history(self.db)
        self.assertEqual(actual,self.rows)
        self.assertEqual(actual[61]['raw_value'],54.1)
        self.assertIsNone(actual[61]['accepted_value'])
        self.assertEqual(actual[109]['status'],'MISSING')
        self.assertEqual(actual[109]['raw_text'],'')
        self.assertIsNone(actual[109]['raw_value'])
        self.assertEqual(actual[100]['run_id'],2)
        self.assertEqual(actual[100]['sample_number'],1)
    def test_repeat_import_does_not_duplicate(self):
        write_database(self.db,self.rows,{})
        write_database(self.db,self.rows,{})
        self.assertEqual(len(query_history(self.db)),125)
    def test_duplicate_import_rolls_back(self):
        write_database(self.db,self.rows,{})
        with self.assertRaises(sqlite3.IntegrityError):
            write_database(self.db,self.rows+[self.rows[0]],{})
        self.assertEqual(len(query_history(self.db)),125)
    def test_gap_counts_missing_positions_not_elapsed_seconds(self):
        sample=[self.rows[i] for i in [0,1,4]]
        gaps=detect_gaps(sample,1)
        self.assertEqual(len(gaps),1)
        self.assertEqual(gaps[0]['elapsed_seconds'],3)
        self.assertEqual(gaps[0]['missing_slots'],2)
        self.assertEqual(summarize(sample,1)['record_completeness_percent'],60)
    def test_no_gap_at_expected_interval(self):
        self.assertEqual(detect_gaps(self.rows,1),[])
    def test_missing_value_is_not_absent_record(self):
        summary=summarize(self.rows,1)
        self.assertEqual(summary['missing_records'],0)
        self.assertEqual(summary['records_with_missing_values'],1)
        self.assertEqual(summary['numeric_readings'],124)
        self.assertEqual(summary['accepted_readings'],105)
    def test_sampling_grid_and_duplicates_checked(self):
        rows=copy.deepcopy(self.rows[:2])
        rows[1]['timestamp']='2026-10-01T12:00:01.500000'
        with self.assertRaises(ValueError):detect_gaps(rows,1)
        rows[1]['timestamp']=rows[0]['timestamp']
        with self.assertRaises(ValueError):detect_gaps(rows,1)
    def test_unknown_inter_run_delay_is_not_counted(self):
        rows=[self.rows[99],self.rows[100]]
        self.assertEqual(detect_gaps(rows,1),[])
        self.assertEqual(len(plot_segments(rows,1)),2)
    def test_plot_breaks_at_null_and_absent_records(self):
        rows=[self.rows[i] for i in [107,108,109,110,111]]
        self.assertEqual([len(s) for s in plot_segments(rows,1)],[2,2])
        absent=[self.rows[i] for i in [0,1,4,5]]
        self.assertEqual([len(s) for s in plot_segments(absent,1)],[2,2])
    def test_windows_use_latest_timestamp_and_inclusive_cutoff(self):
        rows=copy.deepcopy(self.rows[:4])
        times=['2026-01-01T09:59:59','2026-01-01T10:00:00',
               '2026-01-01T10:30:00','2026-01-01T11:00:00']
        for r,t in zip(rows,times):r['timestamp']=t
        write_database(self.db,rows,{})
        self.assertEqual([r['record_id'] for r in query_history(self.db,1)],[2,3,4])
        self.assertEqual(len(query_history(self.db,24)),4)
    def test_primary_counts_and_reset_reconstruction(self):
        summary=summarize(self.rows,1)
        self.assertEqual(summary['status_counts'],{'MISSING':1,'OK':103,'OUT_OF_RANGE':19,'SUSPICIOUS':2})
        self.assertEqual(self.rows[100]['timestamp'],'2026-10-01T12:01:40')
        self.assertEqual(self.rows[-1]['timestamp'],'2026-10-01T12:02:04')
    def test_instructor_evidence_has_45_missing_positions(self):
        rows=read_instructor(ROOT/'data/instructor_sample_history.csv')
        summary=summarize(rows,60)
        self.assertEqual(summary['received_records'],1756)
        self.assertEqual(summary['expected_records_within_observed_runs'],1801)
        self.assertEqual(summary['missing_records'],45)


if __name__=='__main__':
    unittest.main(verbosity=2)
