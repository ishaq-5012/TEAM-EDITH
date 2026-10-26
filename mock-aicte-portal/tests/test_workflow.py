import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import db as database
from app import services
from app import web
from app import integration
from app.catalog import CATEGORIES, field_required, requirements

PDF=b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF"

class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.root=Path(cls.tmp.name)
        cls.patches=[patch.object(database,"DATA",cls.root),patch.object(database,"DB",cls.root/"test.sqlite3"),
                     patch.object(database,"FILES",cls.root/"uploads"),patch.object(services,"FILES",cls.root/"uploads"),
                     patch.object(web,"FILES",cls.root/"uploads")]
        for p in cls.patches: p.start()
        database.initialize()
        from werkzeug.security import generate_password_hash
        db=database.connect()
        db.execute("INSERT INTO users VALUES (?,?,?,?,?,?,?)",("admin",None,"admin",generate_password_hash("password123"),"admin",1,services.now()))
        db.close()

    @classmethod
    def tearDownClass(cls):
        for p in reversed(cls.patches): p.stop()
        cls.tmp.cleanup()

    def setUp(self): self.client=web.app.test_client()

    def register(self,name):
        username=name.lower()
        data=dict(name=name+" College",category="Engineering & Technology",ownership="Private unaided",state="Demo State",district="Demo District",address="Fictional Road",postal_code="123456",contact_name="Sample Person",designation="Registrar",email=username+"@example.invalid",phone="1234567890",established_year="2015",username=username,password="password12345")
        response=self.client.post("/api/auth/register",json=data)
        self.assertEqual(response.status_code,201,response.json)
        return username

    def login(self,username,password="password12345"):
        r=self.client.post("/api/auth/login",json={"username":username,"password":password})
        self.assertEqual(r.status_code,200,r.json)
        return r.json["data"]["csrf"]

    def create(self,csrf,category="other"):
        r=self.client.post("/api/applications",json={"category_id":category,"csrf":csrf})
        self.assertEqual(r.status_code,201,r.json)
        return r.json["data"]["id"]

    def test_evaluator_autofill_uses_separate_institution_account(self):
        from werkzeug.security import generate_password_hash
        self.register("Evaluator")
        db=database.connect()
        institution=services.row(db,"SELECT institution_id FROM users WHERE username=?",("evaluator",))
        db.execute("INSERT INTO users VALUES (?,?,?,?,?,?,?)",(
            services.uid(),institution["institution_id"],"evaluator_walkthrough",
            generate_password_hash("Walkthrough-Pass-42"),"institution",1,services.now(),
        ))
        db.close()
        (self.root/"evaluator-accounts.json").write_text(json.dumps([{
            "label":"Evaluator College","username":"evaluator_walkthrough","password":"Walkthrough-Pass-42",
        }]),encoding="utf-8")
        with patch.object(web,"DATA",self.root), patch.dict("os.environ",{"PORTAL_EVALUATOR_AUTOFILL":"1"}):
            response=self.client.get("/api/evaluator-credentials")
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.headers["Cache-Control"],"no-store")
            self.assertEqual(response.json["accounts"][0]["username"],"evaluator_walkthrough")
            self.login("evaluator_walkthrough","Walkthrough-Pass-42")

    def test_z_auditor_approval_is_visible_in_portal(self):
        self.register("Zeta")
        csrf = self.login("zeta")
        app_id = self.create(csrf)
        saved = self.client.patch(f"/api/applications/{app_id}", json={
            "csrf": csrf, "programme": "Robotics", "academic_year": "2026-27",
            "justification": "Institution programme proposal", "declaration": 1,
        })
        self.assertEqual(saved.status_code, 200, saved.json)
        for code in ("explanation", "declaration"):
            uploaded = self.client.post(f"/api/applications/{app_id}/documents", data={
                "csrf": csrf, "code": code, "file": (io.BytesIO(PDF), code + ".pdf"),
            }, content_type="multipart/form-data")
            self.assertEqual(uploaded.status_code, 201, uploaded.json)
        self.assertEqual(self.client.post(f"/api/applications/{app_id}/submit", json={"csrf": csrf}).status_code, 200)
        db = database.connect()
        outbox = services.row(db, "SELECT id FROM integration_outbox WHERE application_id=?", (app_id,))
        config = {"VERIFYFLOW_INTAKE_URL": "http://127.0.0.1:8000", "VERIFYFLOW_INTAKE_SECRET": "test-secret"}
        with patch.dict("os.environ", config), patch.object(integration, "_call", return_value={"application_id": "verifyflow-zeta", "state": "received"}):
            self.assertTrue(integration.deliver_one(db, outbox["id"]))
        def approved(_base, _secret, method, _path, *_args):
            if method == "POST": return {"state": "complete", "validation_run_id": "run-zeta"}
            return {"application_status": "completed", "review_stage": "approved",
                    "assigned_reviewer": "Review Officer", "document_requests": []}
        with patch.dict("os.environ", config), patch.object(integration, "_call", side_effect=approved):
            integration.reconcile_status(db)
        app = services.row(db, "SELECT status,verifyflow_stage,decision FROM applications WHERE id=?", (app_id,))
        self.assertEqual(app["status"], "decision_recorded")
        self.assertEqual(app["verifyflow_stage"], "approved")
        self.assertIn("approved", app["decision"])
        db.close()

    def test_status_reconciliation_replays_clarification_once(self):
        self.register("Epsilon")
        csrf=self.login("epsilon")
        app_id=self.create(csrf)
        self.assertEqual(self.client.patch(f"/api/applications/{app_id}",json={"csrf":csrf,"programme":"Robotics","academic_year":"2026-27","justification":"Synthetic proposal","declaration":1}).status_code,200)
        for code in ("explanation","declaration"):
            self.assertEqual(self.client.post(f"/api/applications/{app_id}/documents",data={"csrf":csrf,"code":code,"file":(io.BytesIO(PDF),code+".pdf")},content_type="multipart/form-data").status_code,201)
        self.assertEqual(self.client.post(f"/api/applications/{app_id}/submit",json={"csrf":csrf}).status_code,200)
        db=database.connect()
        outbox=services.row(db,"SELECT id FROM integration_outbox WHERE application_id=?",(app_id,))
        config={"VERIFYFLOW_INTAKE_URL":"http://127.0.0.1:8000","VERIFYFLOW_INTAKE_SECRET":"test-secret"}
        with patch.dict("os.environ",config), patch.object(integration,"_call",return_value={"application_id":"verifyflow-gamma","state":"received"}):
            self.assertTrue(integration.deliver_one(db,outbox["id"]))
        def remote(_base,_secret,method,_path,*_args):
            if method=="POST": return {"state":"complete","validation_run_id":"run-1"}
            if app_id not in _path:
                return {"application_status":"completed","assigned_reviewer":None,"document_requests":[]}
            return {"application_status":"needs_review","assigned_reviewer":"Reviewer Gamma",
                    "document_requests":[{"id":"review-item-gamma","description":"Please provide a corrected supporting document."}]}
        with patch.dict("os.environ",config), patch.object(integration,"_call",side_effect=remote):
            self.assertEqual(integration.reconcile_status(db)[0],3)
            self.assertEqual(integration.reconcile_status(db)[0],0)
        app=services.row(db,"SELECT status,reviewer FROM applications WHERE id=?",(app_id,))
        self.assertEqual(app["status"],"clarification_required")
        self.assertEqual(app["reviewer"],"Reviewer Gamma")
        self.assertEqual(services.row(db,"SELECT count(*) n FROM clarifications WHERE application_id=?",(app_id,))["n"],1)
        db.close()

    def test_complete_review_correction_and_boundaries(self):
        self.register("Alpha")
        csrf=self.login("alpha")
        app_id=self.create(csrf)
        r=self.client.patch(f"/api/applications/{app_id}",json={"csrf":csrf,"programme":"Robotics","academic_year":"2026-27","justification":"Demo proposal explanation","declaration":1})
        self.assertEqual(r.status_code,200,r.json)
        self.client.post("/api/auth/logout",json={"csrf":csrf})
        csrf=self.login("alpha")
        detail=self.client.get(f"/api/applications/{app_id}").json["data"]
        self.assertEqual(detail["appitem"]["form"]["programme"],"Robotics")
        fail=self.client.post(f"/api/applications/{app_id}/submit",json={"csrf":csrf})
        self.assertEqual(fail.status_code,400)
        self.assertIn("Upload",fail.json["error"])
        for code in ("explanation","declaration"):
            r=self.client.post(f"/api/applications/{app_id}/documents",data={"csrf":csrf,"code":code,"file":(io.BytesIO(PDF),code+".pdf")},content_type="multipart/form-data")
            self.assertEqual(r.status_code,201,r.json)
        sent=self.client.post(f"/api/applications/{app_id}/submit",json={"csrf":csrf})
        self.assertEqual(sent.status_code,200,sent.json)
        db=database.connect()
        outbox=services.row(db,"SELECT * FROM integration_outbox WHERE application_id=?",(app_id,))
        self.assertEqual(outbox["state"],"pending")
        self.assertEqual(len(json.loads(outbox["payload_json"])["documents"]),2)
        with patch.dict("os.environ",{"VERIFYFLOW_INTAKE_URL":"http://127.0.0.1:8000","VERIFYFLOW_INTAKE_SECRET":"test-secret"}), patch.object(integration,"_call",side_effect=ConnectionError("unavailable")):
            self.assertFalse(integration.deliver_one(db,outbox["id"]))
        self.assertEqual(services.row(db,"SELECT state FROM integration_outbox WHERE id=?",(outbox["id"],))["state"],"failed")
        self.assertEqual(services.row(db,"SELECT status FROM applications WHERE id=?",(app_id,))["status"],"submitted")
        with patch.dict("os.environ",{"VERIFYFLOW_INTAKE_URL":"http://127.0.0.1:8000","VERIFYFLOW_INTAKE_SECRET":"test-secret"}), patch.object(integration,"_call",return_value={"application_id":"verifyflow-app-1","state":"received"}):
            self.assertTrue(integration.deliver_one(db,outbox["id"]))
        self.assertEqual(services.row(db,"SELECT status FROM applications WHERE id=?",(app_id,))["status"],"received")
        db.close()
        detail=self.client.get(f"/api/applications/{app_id}").json["data"]
        self.assertTrue(detail["appitem"]["reference"].startswith("EDU-"))
        version_id=detail["versions"][0]["id"]
        download=self.client.get(f"/files/{version_id}")
        self.assertEqual(download.status_code,200)
        download.close()
        invalid=self.client.post(f"/api/applications/{app_id}/submit",json={"csrf":csrf})
        self.assertEqual(invalid.status_code,409)
        self.client.post("/api/auth/logout",json={"csrf":csrf})

        self.register("Beta")
        beta_csrf=self.login("beta")
        self.assertEqual(self.client.get(f"/api/applications/{app_id}").status_code,404)
        self.assertEqual(self.client.get(f"/files/{version_id}").status_code,404)
        self.assertEqual(self.client.patch(f"/api/applications/{app_id}",json={"csrf":beta_csrf}).status_code,404)
        self.client.post("/api/auth/logout",json={"csrf":beta_csrf})

        admin_csrf=self.login("admin","password123")
        queue=self.client.get("/api/admin/applications").json["data"]
        self.assertTrue(any(a["id"]==app_id for a in queue))
        bad=self.client.post(f"/api/admin/applications/{app_id}/action",json={"csrf":admin_csrf,"action":"decision","decision":"A demo note longer than ten characters"})
        self.assertEqual(bad.status_code,409)
        review=self.client.post(f"/api/admin/applications/{app_id}/action",json={"csrf":admin_csrf,"action":"start_review"})
        self.assertEqual(review.status_code,200,review.json)
        clarify=self.client.post(f"/api/admin/applications/{app_id}/action",json={"csrf":admin_csrf,"action":"clarification","document_code":"explanation","message":"Please provide a corrected supporting explanation."})
        self.assertEqual(clarify.status_code,200,clarify.json)
        self.client.post("/api/auth/logout",json={"csrf":admin_csrf})

        csrf=self.login("alpha")
        detail=self.client.get(f"/api/applications/{app_id}").json["data"]
        self.assertEqual(detail["appitem"]["status"],"clarification_required")
        self.assertEqual(len(detail["clarifications"]),1)
        self.assertEqual(next(d for d in detail["docs"] if d["code"]=="explanation")["status"],"replacement_required")
        blocked=self.client.post(f"/api/applications/{app_id}/resubmit",json={"csrf":csrf})
        self.assertEqual(blocked.status_code,400)
        replace=self.client.post(f"/api/applications/{app_id}/documents",data={"csrf":csrf,"code":"explanation","file":(io.BytesIO(PDF),"corrected.pdf")},content_type="multipart/form-data")
        self.assertEqual(replace.status_code,201,replace.json)
        resubmit=self.client.post(f"/api/applications/{app_id}/resubmit",json={"csrf":csrf})
        self.assertEqual(resubmit.status_code,200,resubmit.json)
        detail=self.client.get(f"/api/applications/{app_id}").json["data"]
        self.assertEqual(detail["appitem"]["status"],"resubmission_pending")
        self.assertEqual(len(detail["history"]),6)
        self.assertEqual(len([v for v in detail["versions"] if v["code"]=="explanation"]),2)
        db=database.connect()
        self.assertGreater(db.execute("SELECT count(*) FROM audit_log WHERE application_id=?",(app_id,)).fetchone()[0],5)
        db.close()

    def test_upload_rejects_spoofed_content_and_csrf(self):
        self.register("Gamma")
        csrf=self.login("gamma")
        app_id=self.create(csrf)
        self.assertEqual(self.client.post("/api/applications",json={"category_id":"other"}).status_code,403)
        r=self.client.post(f"/api/applications/{app_id}/documents",data={"csrf":csrf,"code":"explanation","file":(io.BytesIO(b"not a pdf"),"fake.pdf")},content_type="multipart/form-data")
        self.assertEqual(r.status_code,400)

    def test_page_navigation_stays_on_html_routes(self):
        self.register("Delta")
        csrf=self.login("delta")
        app_id=self.create(csrf)
        dashboard=self.client.get("/dashboard")
        self.assertEqual(dashboard.status_code,200)
        self.assertIn(b'href="/applications/new"',dashboard.data)
        self.assertIn(b'href="/profile"',dashboard.data)
        self.assertEqual(self.client.get("/applications/new").mimetype,"text/html")
        self.assertEqual(self.client.get(f"/applications/{app_id}").mimetype,"text/html")
        self.client.post("/api/auth/logout",json={"csrf":csrf})
        self.login("admin","password123")
        admin=self.client.get("/admin")
        self.assertEqual(admin.mimetype,"text/html")
        self.assertIn(b'href="/admin#institutions"',admin.data)

    def test_every_category_can_upload_and_submit_from_page(self):
        self.register("Allcategories")
        csrf=self.login("allcategories")
        for category in CATEGORIES:
            with self.subTest(category=category["id"]):
                app_id=self.create(csrf,category["id"])
                page=self.client.get(f"/applications/{app_id}")
                self.assertEqual(page.status_code,200)
                self.assertIn(b'Save and submit application',page.data)
                self.assertIn(b'Upload selected document',page.data)
                self.assertIn(f'action="/applications/{app_id}/save"'.encode(),page.data)
                self.assertIn(f'action="/applications/{app_id}/upload"'.encode(),page.data)
                self.assertNotIn(f'action="/api/applications/{app_id}"'.encode(),page.data)
                required=[req for req in requirements(category["id"]) if req["flag"]=="required"]
                for req in required:
                    self.assertIn(f'value="{req["code"]}"'.encode(),page.data)
                    upload=self.client.post(f"/applications/{app_id}/upload",data={"csrf":csrf,"code":req["code"],"file":(io.BytesIO(PDF),req["code"]+".pdf")},content_type="multipart/form-data")
                    self.assertEqual(upload.status_code,302)
                    self.assertIn(f"/applications/{app_id}#evidence",upload.headers["Location"])
                fields={key:("20" if key=="current_intake" else "30" if key=="proposed_intake" else "2026-27" if key=="academic_year" else "Undergraduate" if key=="level" else "2026-10-25" if key=="effective_date" else "Demo value") for key in category["fields"] if field_required(category["id"],key)}
                if category["id"]=="intake-down": fields["proposed_intake"]="10"
                sent=self.client.post(f"/applications/{app_id}/save",data={"csrf":csrf,"intent":"submit","declaration":"1",**fields})
                self.assertEqual(sent.status_code,302)
                db=database.connect()
                saved=services.row(db,"SELECT status FROM applications WHERE id=?",(app_id,))
                queued=services.row(db,"SELECT payload_json FROM integration_outbox WHERE application_id=?",(app_id,))
                db.close()
                self.assertEqual(saved["status"],"submitted")
                self.assertEqual(len(json.loads(queued["payload_json"])["documents"]),len(required))

if __name__=="__main__": unittest.main()
