from __future__ import annotations

import json
import os
import secrets
import sqlite3
import uuid
from decimal import Decimal, InvalidOperation
from contextlib import contextmanager
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT=Path(__file__).parent
STORE=Path(os.environ.get("DECISION_NOTEBOOK_HOME",Path.home()/".local/share/decision-notebook"))
STORE.mkdir(parents=True,exist_ok=True,mode=0o700)
STORE.chmod(0o700)
DB=STORE/"notebook.sqlite3"
TOKEN=secrets.token_urlsafe(24)

def connect():
    db=sqlite3.connect(DB); db.row_factory=sqlite3.Row
    db.executescript("""
    CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY, title TEXT NOT NULL, question TEXT NOT NULL, prediction TEXT NOT NULL, confidence INTEGER NOT NULL, metric TEXT NOT NULL, metric_mode TEXT NOT NULL, comparator TEXT NOT NULL, threshold TEXT NOT NULL, original_criteria TEXT NOT NULL, review_date TEXT NOT NULL, created_at TEXT NOT NULL, sample INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, decision_id TEXT NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL, FOREIGN KEY(decision_id) REFERENCES decisions(id));
    CREATE TRIGGER IF NOT EXISTS decisions_no_update BEFORE UPDATE ON decisions BEGIN SELECT RAISE(ABORT,'decisions are immutable'); END;
    CREATE TRIGGER IF NOT EXISTS decisions_no_delete BEFORE DELETE ON decisions BEGIN SELECT RAISE(ABORT,'decisions are immutable'); END;
    CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'events are append-only'); END;
    CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'events are append-only'); END;
    """)
    db.commit(); DB.chmod(0o600); return db

@contextmanager
def database():
    db=connect()
    try:
        yield db; db.commit()
    finally: db.close()

def now(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def add_event(db,decision_id,kind,data):
    db.execute("INSERT INTO events(decision_id,kind,data,created_at) VALUES(?,?,?,?)",(decision_id,kind,json.dumps(data,ensure_ascii=False),now()))
def valid_date(value):
    try: date.fromisoformat(value); return True
    except (ValueError,TypeError): return False
def history(db,decision_id):
    return [dict(r) | {"data":json.loads(r["data"])} for r in db.execute("SELECT seq,kind,data,created_at FROM events WHERE decision_id=? ORDER BY seq",(decision_id,))]
def state(db):
    out=[]
    for r in db.execute("SELECT * FROM decisions ORDER BY created_at DESC"):
        d=dict(r); ev=history(db,d["id"]); criteria=[e for e in ev if e["kind"]=="criteria_changed"]
        outcomes=[e for e in ev if e["kind"]=="outcome"]
        d["criteria_versions"]=[{"version":1,"text":d["original_criteria"],"created_at":d["created_at"]}]+[{"version":e["data"]["version"],"text":e["data"]["text"],"created_at":e["created_at"]} for e in criteria]
        d["current_criteria_version"]=d["criteria_versions"][-1]["version"]
        d["current_criteria"]=d["criteria_versions"][-1]["text"]
        d["current_outcome"]=outcomes[-1]["data"] if outcomes else None
        d["events"]=ev; out.append(d)
    for d in out:
        original=[e["data"] for e in d["events"] if e["kind"]=="outcome" and e["data"]["criteria_version"]==1]
        d["original_criteria_outcome"]=original[-1] if original else None
    eligible=[d for d in out if d["original_criteria_outcome"] and d["original_criteria_outcome"]["result"] in {"success","failure"}]
    successes=sum(d["original_criteria_outcome"]["result"]=="success" for d in eligible)
    brier=(round(sum((d["confidence"]/100-(1 if d["original_criteria_outcome"]["result"]=="success" else 0))**2 for d in eligible)/len(eligible),6) if eligible else None)
    return {"decisions":out,"calibration":{"sample_size":len(eligible),"successes":successes,"rate":successes/len(eligible) if eligible else None,"brier":brier}}

class Handler(BaseHTTPRequestHandler):
    server_version="DecisionNotebook/1.0"
    def log_message(self,*_): pass
    def reply(self,data,status=200,ctype="application/json; charset=utf-8"):
        raw=data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status); self.send_header("Content-Type",ctype); self.send_header("Content-Length",str(len(raw))); self.send_header("Cache-Control","no-store"); self.end_headers(); self.wfile.write(raw)
    def safe_origin(self):
        if self.headers.get("Host") not in {"127.0.0.1:8352","localhost:8352"}: return False
        origin=self.headers.get("Origin")
        return not origin or origin in {"http://127.0.0.1:8352","http://localhost:8352"}
    def do_GET(self):
        if not self.safe_origin(): return self.reply({"error":"invalid host"},403)
        if self.path=="/":
            return self.reply((ROOT/"index.html").read_text().replace("__TOKEN__",TOKEN).encode(),ctype="text/html; charset=utf-8")
        if self.path in {"/style.css","/app.js"}:
            name=self.path[1:];return self.reply((ROOT/name).read_bytes(),ctype="text/css; charset=utf-8" if name.endswith("css") else "text/javascript; charset=utf-8")
        if self.path!="/api/state": return self.reply({"error":"not found"},404)
        with database() as db: return self.reply(state(db))
    def do_POST(self):
        if not self.safe_origin() or self.headers.get("X-Request-Token")!=TOKEN: return self.reply({"error":"request rejected"},403)
        try: length=int(self.headers.get("Content-Length","0"))
        except ValueError: return self.reply({"error":"invalid length"},400)
        if length<=0: return self.reply({"error":"request body required"},400)
        if length>20000: return self.reply({"error":"request too large"},413)
        try: data=json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError,UnicodeDecodeError): return self.reply({"error":"invalid JSON"},400)
        if not isinstance(data,dict): return self.reply({"error":"JSON object required"},400)
        with database() as db:
            if self.path=="/api/decision":
                fields={k:str(data.get(k,"" )).strip() for k in ("title","question","prediction","metric","metric_mode","comparator","threshold","criteria","review_date")}
                required=("title","question","prediction","metric","metric_mode","criteria","review_date")
                if any(not fields[k] for k in required) or any(len(v)>1800 for v in fields.values()) or len(fields["title"])>100: return self.reply({"error":"complete each field within its limit"},400)
                raw_confidence=data.get("confidence")
                if isinstance(raw_confidence,bool) or not (isinstance(raw_confidence,int) or isinstance(raw_confidence,str) and raw_confidence.isdigit()):return self.reply({"error":"confidence must be a whole number from 0 to 100"},400)
                confidence=int(raw_confidence)
                if confidence<0 or confidence>100 or not valid_date(fields["review_date"]): return self.reply({"error":"check confidence and review date"},400)
                if fields["metric_mode"] not in {"manual","numeric"}: return self.reply({"error":"choose a metric type"},400)
                if fields["metric_mode"]=="numeric":
                    if not fields["comparator"] or not fields["threshold"] or fields["comparator"] not in {">=","<=",">","<","="}: return self.reply({"error":"enter a threshold and choose a valid comparison"},400)
                    try:
                        threshold=Decimal(fields["threshold"])
                        if not threshold.is_finite(): raise InvalidOperation
                    except InvalidOperation: return self.reply({"error":"enter a valid numeric threshold"},400)
                    fields["threshold"]=str(threshold)
                else: fields["comparator"]="";fields["threshold"]=""
                ident=str(uuid.uuid4()); created=now()
                db.execute("INSERT INTO decisions(id,title,question,prediction,confidence,metric,metric_mode,comparator,threshold,original_criteria,review_date,created_at,sample) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0)",(ident,fields["title"],fields["question"],fields["prediction"],confidence,fields["metric"],fields["metric_mode"],fields["comparator"],fields["threshold"],fields["criteria"],fields["review_date"],created))
                add_event(db,ident,"prediction_recorded",{"title":fields["title"],"question":fields["question"],"prediction":fields["prediction"],"confidence":confidence,"metric":fields["metric"],"metric_mode":fields["metric_mode"],"comparator":fields["comparator"],"threshold":fields["threshold"],"criteria":fields["criteria"],"review_date":fields["review_date"]})
                return self.reply({"ok":True,"id":ident},201)
            if self.path=="/api/sample":
                if db.execute("SELECT 1 FROM decisions LIMIT 1").fetchone(): return self.reply({"error":"sample data loads only into an empty notebook"},409)
                samples=[
                    ("Hiring capacity","Can the team handle 12 new accounts next month?","The team can onboard 12 accounts without missed service targets.",65,"Accounts onboarded","numeric",">=","12","At least 12 accounts with no missed service targets.","2026-10-01","failure","9","Hiring capacity was lower than planned."),
                    ("Landing page test","Will the new page lift qualified signups?","Qualified signups will rise by at least 10% over four weeks.",70,"Qualified signup rate vs prior four weeks","manual","","","At least 10% higher with similar traffic sources.","2026-10-10","inconclusive","","Traffic sources changed during the test."),
                    ("Support coverage","Will the new schedule cover peak hours?","The schedule will cover all peak hours for a month.",75,"Peak-hour coverage","manual","","","All peak hours have a named owner for one month.","2026-10-15","success","","Synthetic schedule review supports this result."),
                    ("Onboarding change","Will the revised plan shorten setup time?","The revised plan will cut setup time by two days.",60,"Average setup time in days","numeric","<=","5","Average setup time is 5 days or less.","2026-10-20","success","4","Manual review used the revised criteria.")]
                for title,question,prediction,confidence,metric,mode,comparator,threshold,criteria,review,result,observed,note in samples:
                    ident=str(uuid.uuid4());created=now();db.execute("INSERT INTO decisions(id,title,question,prediction,confidence,metric,metric_mode,comparator,threshold,original_criteria,review_date,created_at,sample) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1)",(ident,title,question,prediction,confidence,metric,mode,comparator,threshold,criteria,review,created));add_event(db,ident,"prediction_recorded",{"title":title,"question":question,"prediction":prediction,"confidence":confidence,"metric":metric,"metric_mode":mode,"comparator":comparator,"threshold":threshold,"criteria":criteria,"review_date":review,"sample":True});add_event(db,ident,"evidence",{"text":"Synthetic example. No real company or result."})
                    version=1
                    if title=="Onboarding change":
                        add_event(db,ident,"criteria_changed",{"version":2,"text":"Manual review finds the revised plan quicker than the prior setup process."});version=2
                    outcome={"result":result,"criteria_version":version,"mode":"manual" if version>1 or mode=="manual" else "numeric","note":note}
                    if mode=="numeric" and version==1:outcome.update({"observed_value":observed,"comparator":comparator,"threshold":threshold})
                    add_event(db,ident,"outcome",outcome)
                return self.reply({"ok":True},201)
            parts=self.path.split("/")
            if len(parts)!=5 or parts[1:3]!=["api","decisions"] or parts[4] not in {"evidence","criteria","outcome"}:return self.reply({"error":"not found"},404)
            ident,action=parts[3],parts[4]
            decision=db.execute("SELECT * FROM decisions WHERE id=?",(ident,)).fetchone()
            if not decision:return self.reply({"error":"decision not found"},404)
            ev=history(db,ident); version=1+sum(e["kind"]=="criteria_changed" for e in ev)
            if action=="evidence":
                text=data.get("text","")
                if not isinstance(text,str) or not text.strip() or len(text)>4000:return self.reply({"error":"evidence must be 1 to 4000 characters"},400)
                add_event(db,ident,"evidence",{"text":text.strip()});return self.reply({"ok":True},201)
            if action=="criteria":
                text=data.get("text","")
                if not isinstance(text,str) or not text.strip() or len(text)>1800:return self.reply({"error":"criteria must be 1 to 1800 characters"},400)
                add_event(db,ident,"criteria_changed",{"version":version+1,"text":text.strip()});return self.reply({"ok":True,"version":version+1},201)
            if action=="outcome":
                note=data.get("note","")
                if not isinstance(note,str) or not note.strip() or len(note)>1800:return self.reply({"error":"add a short review note"},400)
                if not any(e["kind"]=="evidence" for e in ev):return self.reply({"error":"add supporting evidence before reviewing this decision"},400)
                if version==1 and decision["metric_mode"]=="numeric" and data.get("result")=="inconclusive":
                    outcome={"result":"inconclusive","criteria_version":1,"mode":"numeric","note":note.strip()}
                    add_event(db,ident,"outcome",outcome);return self.reply({"ok":True,"criteria_version":1,"result":"inconclusive"},201)
                if version==1 and decision["metric_mode"]=="numeric":
                    try:
                        observed=Decimal(str(data.get("observed_value","")))
                        threshold=Decimal(decision["threshold"])
                        if not observed.is_finite():raise InvalidOperation
                    except InvalidOperation:return self.reply({"error":"enter a valid observed number"},400)
                    op=decision["comparator"];passed={">=":observed>=threshold,"<=":observed<=threshold,">":observed>threshold,"<":observed<threshold,"=":observed==threshold}[op]
                    result="success" if passed else "failure"
                    outcome={"result":result,"criteria_version":1,"mode":"numeric","observed_value":str(observed),"comparator":op,"threshold":str(threshold),"note":note.strip()}
                else:
                    result=data.get("result")
                    if result not in {"success","failure","inconclusive"}:return self.reply({"error":"choose success, failure, or inconclusive"},400)
                    outcome={"result":result,"criteria_version":version,"mode":"manual","note":note.strip()}
                add_event(db,ident,"outcome",outcome);return self.reply({"ok":True,"criteria_version":version,"result":result},201)
        return self.reply({"error":"not found"},404)

if __name__=="__main__":
    http=ThreadingHTTPServer(("127.0.0.1",8352),Handler);print("Decision Notebook ready at http://127.0.0.1:8352");http.serve_forever()
