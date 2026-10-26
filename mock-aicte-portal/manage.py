"""Local database setup, deterministic demo seeding, and explicit reset."""
import argparse
import io
import os
import shutil
import uuid
from pathlib import Path
from werkzeug.datastructures import FileStorage
from werkzeug.security import generate_password_hash
from app.db import DB, FILES, initialize, connect
from app.catalog import get_category, requirements
from app.services import audit, now, status_change, store_document

_env_file = Path(__file__).resolve().parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.lstrip().startswith("#"):
            _key, _value = _line.split("=", 1)
            os.environ.setdefault(_key.strip(), _value.strip())

ADMIN_USER="demo_admin"
ADMIN_PASSWORD="DemoAdmin!2026"
INSTITUTION_PASSWORD="DemoInstitute!2026"
NAMESPACE=uuid.UUID("330cf112-2737-4595-a4c2-981803bad4a2")

def stable(value): return str(uuid.uuid5(NAMESPACE,value))

def pdf_document(title, institution, reference, note):
    lines=["SYNTHETIC \x97 DEMO ONLY \x97 NOT AN OFFICIAL DOCUMENT",title,institution,
           "Fictional document ID: "+reference,"Generated for EduApproval local testing.",note]
    if "Faculty" in title:
        lines += ["Faculty ID | Qualification | Department", "FAC-01 | PhD | Computing", "FAC-02 | MTech | Computing"]
    if "Infrastructure" in title:
        lines += ["Inventory ID | Asset | Quantity", "LAB-01 | Workstations | 24", "LAB-02 | Network kits | 12"]
    if "Programme" in title:
        lines += ["Programme | Level | Proposed intake", "Computer Science and Engineering | UG | 120"]
    if "financial" in title.lower():
        lines += ["Synthetic financial period: 2025-26", "Illustrative receipts: INR 12,00,000"]
    lines=[line.replace("\\","\\\\").replace("(","\\(").replace(")","\\)") for line in lines]
    stream="BT /F1 13 Tf 50 775 Td 17 TL "+" ".join(f"({line}) Tj T*" for line in lines)+" ET"
    objects=["<< /Type /Catalog /Pages 2 0 R >>","<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
             "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
             "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",f"<< /Length {len(stream.encode('latin-1'))} >>\nstream\n{stream}\nendstream"]
    out=b"%PDF-1.4\n"; offsets=[0]
    for i,obj in enumerate(objects,1):
        offsets.append(len(out));out+=f"{i} 0 obj\n{obj}\nendobj\n".encode("latin-1")
    start=len(out);out+=f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode()
    for offset in offsets[1:]: out+=f"{offset:010d} 00000 n \n".encode()
    out+=f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()
    return out

SAMPLES=[
    ("Aster Valley Institute of Technology","aster_demo","new","draft","Aster Valley", "Dharpur"),
    ("Cedar Crest Polytechnic","cedar_demo","eoa","submitted","Cedar Crest", "Nandipur"),
    ("Meridian School of Computing","meridian_demo","intake-up","under_review","Meridian", "Suryanagar"),
    ("Bluehaven Technical College","bluehaven_demo","new-course","clarification_required","Bluehaven", "Maitripur"),
    ("Northstar Design Institute","northstar_demo","site","resubmission_received","Northstar", "Prakashpur"),
    ("Silverleaf Institute of Management","silverleaf_demo","affiliation","decision_recorded","Silverleaf", "Udaygarh"),
]

def form_for(category_id, name):
    from app.catalog import field_spec
    values={"programme":"Computer Science and Engineering","level":"Undergraduate","current_intake":"60",
            "proposed_intake":"120","approval_ref":"SYN-APP-2025-1042","academic_year":"2026-27",
            "new_name":name+" College","new_location":"Fictional Sector 8, Demonstration District",
            "new_affiliation":"Fictional State Technical University","effective_date":"2026-07-01",
            "justification":"Synthetic proposal for testing a local institutional review workflow."}
    return {key:values[key] for key in get_category(category_id)["fields"]}

def seed():
    import json
    initialize();db=connect()
    try:
        if not db.execute("SELECT 1 FROM users WHERE username=?",(ADMIN_USER,)).fetchone():
            admin_id=stable("admin")
            db.execute("INSERT INTO users VALUES (?,?,?,?,?,?,?)",(admin_id,None,ADMIN_USER,generate_password_hash(ADMIN_PASSWORD),"admin",1,now()))
        else: admin_id=db.execute("SELECT id FROM users WHERE username=?",(ADMIN_USER,)).fetchone()[0]
        for name,username,category,status,short,district in SAMPLES:
            inst_id,user_id,app_id=(stable(username+suffix) for suffix in (":institution",":user",":application"))
            if db.execute("SELECT 1 FROM institutions WHERE id=?",(inst_id,)).fetchone(): continue
            db.execute("INSERT INTO institutions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (inst_id,name,"Engineering & Technology","Private unaided","Demo Pradesh",district,
                        "12 Fictional Campus Road","000000","Dr. Sample Contact","Registrar",
                        username+"@example.invalid","0000000000",2012,"SYN-APP-2025-1042",1,now()))
            db.execute("INSERT INTO users VALUES (?,?,?,?,?,?,?)",(user_id,inst_id,username,generate_password_hash(INSTITUTION_PASSWORD),"institution",1,now()))
            db.execute("INSERT INTO applications (id,institution_id,category_id,status,form_json,declaration,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                       (app_id,inst_id,category,"draft",json.dumps(form_for(category,name)),1,now(),now()))
            db.execute("INSERT INTO status_history VALUES (?,?,?,?,?,?,?)",(stable(app_id+":draft"),app_id,None,"draft","Synthetic draft created",user_id,now()))
            audit(db,user_id,"application:created",app_id,"Synthetic demo seed")
            for req in requirements(category):
                if req["flag"]=="required" or (status!="draft" and req["code"] in ("approval","faculty")):
                    reference="SYN-DOC-"+short.upper()+"-"+req["code"].upper()
                    note="Programme: Computer Science and Engineering; intake: 120."
                    if username=="bluehaven_demo" and req["code"]=="programme":
                        note="Deliberate test discrepancy: intake shown as 90 instead of 120."
                    pdf=pdf_document(req["name"],name,reference,note)
                    upload=FileStorage(stream=io.BytesIO(pdf),filename=req["code"]+".pdf",content_type="application/pdf")
                    store_document(db,{"id":app_id,"status":"draft","category_id":category},user_id,req["code"],upload)
            if status=="draft": continue
            a={"id":app_id,"status":"draft"}
            status_change(db,a,"submitted",user_id,"Synthetic institution submission")
            db.execute("UPDATE applications SET reference=?,submitted_at=? WHERE id=?",("EDU-2026-"+app_id[:8].upper(),now(),app_id))
            a["status"]="submitted"
            if status=="submitted": continue
            status_change(db,a,"under_review",admin_id,"Synthetic review started")
            a["status"]="under_review"
            db.execute("UPDATE applications SET reviewer=? WHERE id=?",("Demo Reviewer A",app_id))
            if status=="under_review": continue
            if status in ("clarification_required","resubmission_received"):
                message="Please clarify the supporting programme details and upload a corrected statement."
                db.execute("INSERT INTO clarifications VALUES (?,?,?,?,?,?)",(stable(app_id+":clarification"),app_id,message,admin_id,now(),None))
                status_change(db,a,"clarification_required",admin_id,message)
                a["status"]="clarification_required"
                if status=="resubmission_received":
                    status_change(db,a,"resubmission_received",user_id,"Synthetic correction submitted")
                    db.execute("UPDATE applications SET resubmitted_at=?,decision=NULL WHERE id=?",(now(),app_id))
                continue
            if status=="decision_recorded":
                db.execute("UPDATE applications SET decision=? WHERE id=?",("Demo review completed for this fictional application. No official approval is implied.",app_id))
                status_change(db,a,"decision_recorded",admin_id,"Synthetic demo decision")
        print("Seed complete. Existing demo records were left unchanged.")
        print(f"Admin: {ADMIN_USER} / {ADMIN_PASSWORD}")
        print(f"Institution: aster_demo (and five others) / {INSTITUTION_PASSWORD}")
    finally: db.close()

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("command",choices=["init","seed","reset","sync"])
    args=parser.parse_args()
    if args.command=="init": initialize();print("Database initialized.")
    elif args.command=="seed": seed()
    elif args.command=="sync":
        from app.integration import deliver_pending, reconcile_status
        db=connect()
        try:
            sent,failed=deliver_pending(db)
            print(f"Delivery complete: {sent} received, {failed} pending retry.")
            updated,sync_failed=reconcile_status(db)
            print(f"Status reconciliation: {updated} updates, {sync_failed} failures.")
        finally: db.close()
    else:
        if DB.exists(): DB.unlink()
        if FILES.exists(): shutil.rmtree(FILES)
        seed()
        print("Local demo database and uploads reset.")
