import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from datetime import date, timedelta
from unittest.mock import patch
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

TEMP = tempfile.TemporaryDirectory()
os.environ["DECISION_NOTEBOOK_HOME"] = TEMP.name
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import server


class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = server.make_server(port=0)
        cls.base = f"http://127.0.0.1:{cls.http.server_port}"
        cls.origin = cls.base
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown(); cls.http.server_close(); cls.thread.join(timeout=2); TEMP.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        server.DB = Path(self.temp.name) / "notebook.sqlite3"
        self.addCleanup(self.temp.cleanup)

    def request(self, path, body=None, token=None, origin=None):
        origin=origin or self.origin
        headers={"Origin":origin};raw=None
        if body is not None:
            raw=json.dumps(body).encode();headers["Content-Type"]="application/json"
            if token is not None:headers["X-Request-Token"]=token
        req=Request(self.base+path,data=raw,headers=headers)
        with urlopen(req) as response:return response.status,json.loads(response.read()) if response.headers.get("Content-Type","").startswith("application/json") else response.read().decode()

    def token(self):
        _,page=self.request("/");return page.split('window.REQUEST_TOKEN="',1)[1].split('"',1)[0]

    def create(self,token,mode="numeric",threshold="10",confidence=80):
        data={"title":"Capacity check","question":"Can we add 10 accounts?","prediction":"We can add 10 accounts.","confidence":confidence,"review_date":"2026-12-01","metric":"Accounts added","metric_mode":mode,"comparator":">=","threshold":threshold if mode=="numeric" else "","criteria":"At least 10 accounts by review date."}
        return self.request("/api/decision",data,token)

    def test_original_prediction_is_immutable_and_amended_result_does_not_change_calibration(self):
        token=self.token();_,created=self.create(token);ident=created["id"]
        self.assertIsInstance(ident,str)
        self.request(f"/api/decisions/{ident}/evidence",{"text":"Only 8 accounts were ready."},token)
        self.request(f"/api/decisions/{ident}/outcome",{"observed_value":"8","note":"Counted completed accounts."},token)
        self.request(f"/api/decisions/{ident}/criteria",{"text":"Accept 8 accounts if all have support coverage."},token)
        self.request(f"/api/decisions/{ident}/evidence",{"text":"The eight accounts now have full coverage."},token)
        self.request(f"/api/decisions/{ident}/outcome",{"result":"success","note":"Manual review under the new rule."},token)
        _,state=self.request("/api/state");d=state["decisions"][0]
        self.assertEqual(d["prediction"],"We can add 10 accounts.");self.assertEqual(d["confidence"],80)
        self.assertEqual(d["original_criteria"],"At least 10 accounts by review date.")
        self.assertEqual(d["current_outcome"]["result"],"success");self.assertEqual(d["current_outcome"]["criteria_version"],2)
        self.assertEqual(d["original_criteria_outcome"]["result"],"failure")
        self.assertEqual(state["calibration"]["sample_size"],1);self.assertEqual(state["calibration"]["successes"],0)
        self.assertEqual(state["calibration"]["brier"],0.64)
        with sqlite3.connect(server.DB) as db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute("UPDATE decisions SET prediction='changed' WHERE id=?",(ident,))
            with self.assertRaises(sqlite3.IntegrityError):db.execute("DELETE FROM events WHERE decision_id=?",(ident,))

    def test_numeric_threshold_and_inconclusive_result(self):
        token=self.token();_,created=self.create(token,confidence=60);ident=created["id"]
        self.request(f"/api/decisions/{ident}/evidence",{"text":"The measure cannot be confirmed yet."},token)
        _,result=self.request(f"/api/decisions/{ident}/outcome",{"result":"inconclusive","note":"Source data is incomplete."},token)
        self.assertEqual(result["result"],"inconclusive")
        _,created=self.create(token,threshold="10",confidence=60);ident=created["id"]
        self.request(f"/api/decisions/{ident}/evidence",{"text":"Eleven accounts finished onboarding."},token)
        _,result=self.request(f"/api/decisions/{ident}/outcome",{"observed_value":"11","note":"Counted completed accounts."},token)
        self.assertEqual(result["result"],"success")
        _,state=self.request("/api/state");self.assertEqual(state["calibration"]["sample_size"],1);self.assertEqual(state["calibration"]["rate"],1.0)

    def test_manual_result_needs_evidence_and_counts_original_binary_verdict(self):
        token=self.token();_,created=self.create(token,mode="manual");ident=created["id"]
        with self.assertRaises(HTTPError) as err:self.request(f"/api/decisions/{ident}/outcome",{"result":"success","note":"Seems good."},token)
        self.assertEqual(err.exception.code,400);err.exception.close()
        self.request(f"/api/decisions/{ident}/evidence",{"text":"Observed signups rose in the period."},token)
        self.request(f"/api/decisions/{ident}/outcome",{"result":"success","note":"The recorded rule was met."},token)
        _,state=self.request("/api/state");self.assertEqual(state["calibration"]["sample_size"],1);self.assertEqual(state["calibration"]["successes"],1)

    def test_synthetic_examples_show_failed_inconclusive_and_amended_outcomes(self):
        token=self.token();status,_=self.request("/api/sample",{},token);self.assertEqual(status,201)
        _,state=self.request("/api/state");self.assertEqual(len(state["decisions"]),4)
        results=[d["current_outcome"]["result"] for d in state["decisions"]]
        self.assertIn("failure",results);self.assertIn("inconclusive",results)
        self.assertEqual(state["calibration"]["sample_size"],2);self.assertEqual(state["calibration"]["successes"],1)
        with self.assertRaises(HTTPError) as err:self.request("/api/sample",{},token)
        self.assertEqual(err.exception.code,409);err.exception.close()

    def test_invalid_fields_and_numeric_threshold_are_rejected(self):
        token=self.token()
        with self.assertRaises(HTTPError) as threshold:self.create(token,threshold="NaN")
        self.assertEqual(threshold.exception.code,400);threshold.exception.close()
        bad_data={"title":"","question":"q","prediction":"p","confidence":101,"review_date":"not-a-date","metric":"m","metric_mode":"manual","criteria":"c"}
        with self.assertRaises(HTTPError) as err:self.request("/api/decision",bad_data,token)
        self.assertEqual(err.exception.code,400);err.exception.close()
        bad_data.update({"title":"Fractional confidence","confidence":80.5,"review_date":"2026-12-01","metric":"m"})
        with self.assertRaises(HTTPError) as err:self.request("/api/decision",bad_data,token)
        self.assertEqual(err.exception.code,400);err.exception.close()
        bad_data["confidence"]=True
        with self.assertRaises(HTTPError) as err:self.request("/api/decision",bad_data,token)
        self.assertEqual(err.exception.code,400);err.exception.close()

    def test_bad_origin_missing_token_large_body_and_wrong_route_are_rejected(self):
        token=self.token()
        with self.assertRaises(HTTPError) as missing:self.request("/api/sample",{})
        self.assertEqual(missing.exception.code,403);missing.exception.close()
        with self.assertRaises(HTTPError) as origin:self.request("/api/sample",{},token,"http://evil.test")
        self.assertEqual(origin.exception.code,403);origin.exception.close()
        req=Request(self.base+"/api/sample",data=b"x"*20001,headers={"Origin":self.origin,"X-Request-Token":token})
        with self.assertRaises(HTTPError) as large:urlopen(req)
        self.assertEqual(large.exception.code,413);large.exception.close()
        with self.assertRaises(HTTPError) as route:self.request("/api/decisions/not-an-id/unexpected/outcome",{},token)
        self.assertEqual(route.exception.code,404);route.exception.close()

    def test_negative_content_length_is_rejected(self):
        req=Request(self.base+"/api/sample",data=b"{}",headers={"Origin":self.origin,"X-Request-Token":self.token(),"Content-Length":"-1"})
        with self.assertRaises(HTTPError) as err:urlopen(req)
        self.assertEqual(err.exception.code,400);err.exception.close()

    def weekly_payload(self, start=None):
        start=start or (date.today()+timedelta(days=14))
        monday=start-timedelta(days=start.weekday())
        if monday<=date.today():monday+=timedelta(days=7)
        return {"week_start":monday.isoformat(),"week_end":(monday+timedelta(days=6)).isoformat(),"prediction":"I will finish the planned reading.","how_to_check":"Check the dated reading log.","criteria":"The log shows all planned chapters.","confidence":70,"no_ai_attested":True}

    def test_week_bounds_and_self_attestation_validation(self):
        self.assertEqual(server.week_bounds("2026-11-04"),("2026-11-02","2026-11-08"))
        token=self.token();data=self.weekly_payload();data["no_ai_attested"]=False
        with self.assertRaises(HTTPError) as err:self.request("/api/weekly-prediction",data,token)
        self.assertEqual(err.exception.code,400);err.exception.close()
        data=self.weekly_payload();data["week_end"]="2026-11-09"
        with self.assertRaises(HTTPError) as err:self.request("/api/weekly-prediction",data,token)
        self.assertEqual(err.exception.code,400);err.exception.close()

    def test_weekly_prediction_locks_rule_and_review_waits_until_week_end(self):
        token=self.token();_,created=self.request("/api/weekly-prediction",self.weekly_payload(),token);ident=created["id"]
        with self.assertRaises(HTTPError) as err:self.request(f"/api/decisions/{ident}/criteria",{"text":"Changed rule"},token)
        self.assertEqual(err.exception.code,409);err.exception.close()
        data={"evidence":"The dated reading log shows completion.","result":"right","lesson":"Keep the same schedule.","no_ai_attested":True}
        with self.assertRaises(HTTPError) as err:self.request(f"/api/decisions/{ident}/weekly-review",data,token)
        self.assertEqual(err.exception.code,409);err.exception.close()
        end=date.fromisoformat(self.weekly_payload()["week_end"])
        class AfterWeek(date):
            @classmethod
            def today(cls):return end+timedelta(days=1)
        with patch.object(server,"date",AfterWeek):
            self.request(f"/api/decisions/{ident}/weekly-review",data,token)
            _,state=self.request("/api/state")
        self.assertEqual(state["weekly_summary"]["resolved"],1)
        self.assertEqual(state["weekly_summary"]["right_rate"],1.0)
        self.assertEqual(state["weekly_summary"]["average_confidence"],70)
        self.assertEqual(state["weekly_summary"]["confidence_gap_points"],-30.0)
        with sqlite3.connect(server.DB) as db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute("UPDATE weekly_predictions SET week_end='2030-01-01' WHERE decision_id=?",(ident,))
            with self.assertRaises(sqlite3.IntegrityError):db.execute("DELETE FROM weekly_predictions WHERE decision_id=?",(ident,))
        with self.assertRaises(HTTPError) as err:self.request(f"/api/decisions/{ident}/outcome",{"result":"success","note":"No shortcut."},token)
        self.assertEqual(err.exception.code,409);err.exception.close()

    def test_weekly_scores_exclude_samples_and_unresolved_and_legacy_remains_readable(self):
        token=self.token();self.request("/api/sample",{},token)
        _,legacy=self.request("/api/state");self.assertEqual(len(legacy["decisions"]),4)
        weekly=self.weekly_payload();_,created=self.request("/api/weekly-prediction",weekly,token)
        _,state=self.request("/api/state")
        self.assertEqual(state["weekly_summary"]["resolved"],0)
        self.assertIsNone(state["weekly_summary"]["right_rate"])
        self.assertEqual(state["calibration"]["sample_size"],2)
        sample=next(d for d in state["decisions"] if d["sample"])
        with sqlite3.connect(server.DB) as db:
            db.execute("INSERT INTO weekly_predictions(decision_id,week_start,week_end,self_attested_no_ai) VALUES(?,?,?,1)",(sample["id"],weekly["week_start"],weekly["week_end"]))
            server.add_event(db,sample["id"],"weekly_review",{"result":"right","evidence":"Synthetic test fixture only.","lesson":"Fixture lesson."})
        _,state=self.request("/api/state")
        self.assertEqual(len([d for d in state["decisions"] if d["weekly"]]),2)
        self.assertEqual(state["weekly_summary"]["resolved"],0)
        self.assertEqual(len([d for d in state["decisions"] if not d["weekly"]]),3)
        self.assertEqual(len([d for d in state["decisions"] if d["weekly"] and d["sample"]]),1)
        self.assertTrue(next(d for d in state["decisions"] if d["id"]==created["id"])["weekly"]["self_attested_no_ai"])

    def test_weekly_review_saturday_sunday_gate_and_latest_review_counts_once(self):
        token=self.token();payload=self.weekly_payload();_,created=self.request("/api/weekly-prediction",payload,token);ident=created["id"]
        end=date.fromisoformat(payload["week_end"])
        evidence={"evidence":"The log confirms completion.","result":"right","lesson":"Keep the plan.","no_ai_attested":True}
        for blocked_day in (end-timedelta(days=1),end):
            class BeforeMonday(date):
                @classmethod
                def today(cls):return blocked_day
            with patch.object(server,"date",BeforeMonday):
                with self.assertRaises(HTTPError) as err:self.request(f"/api/decisions/{ident}/weekly-review",evidence,token)
                self.assertEqual(err.exception.code,409);err.exception.close()
        class Monday(date):
            @classmethod
            def today(cls):return end+timedelta(days=1)
        with patch.object(server,"date",Monday):
            self.request(f"/api/decisions/{ident}/weekly-review",evidence,token)
            evidence.update({"result":"missed","lesson":"Set a smaller plan."})
            self.request(f"/api/decisions/{ident}/weekly-review",evidence,token)
            _,state=self.request("/api/state")
        self.assertEqual(state["weekly_summary"]["resolved"],1)
        self.assertEqual(state["weekly_summary"]["right_rate"],0.0)
        self.assertEqual(state["weekly_summary"]["confidence_gap_points"],70.0)
        self.assertEqual(len(next(d for d in state["decisions"] if d["id"]==ident)["weekly_reviews"]),2)

    def test_not_clear_stays_unresolved_and_right_and_missed_mix_scores_latest_result(self):
        token=self.token();payload=self.weekly_payload();_,unclear=self.request("/api/weekly-prediction",payload,token)
        next_payload=self.weekly_payload(date.fromisoformat(payload["week_start"])+timedelta(days=7));_,right=self.request("/api/weekly-prediction",next_payload,token)
        last_payload=self.weekly_payload(date.fromisoformat(payload["week_start"])+timedelta(days=14));_,missed=self.request("/api/weekly-prediction",last_payload,token)
        last_end=date.fromisoformat(last_payload["week_end"])
        class AfterAllWeeks(date):
            @classmethod
            def today(cls):return last_end+timedelta(days=1)
        with patch.object(server,"date",AfterAllWeeks):
            for record,result in ((unclear,"not_clear"),(right,"right"),(missed,"missed")):
                self.request(f"/api/decisions/{record['id']}/weekly-review",{"evidence":"Checked the dated record.","result":result,"lesson":"Carry forward one adjustment."},token)
            _,state=self.request("/api/state")
        self.assertEqual(state["weekly_summary"]["resolved"],2)
        self.assertEqual(state["weekly_summary"]["right_rate"],0.5)
        self.assertAlmostEqual(state["weekly_summary"]["confidence_gap_points"],20.0)


if __name__=="__main__":unittest.main()
