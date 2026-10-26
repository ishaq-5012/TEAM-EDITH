import hashlib
import json
import os
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash
from .catalog import get_category, requirements, field_spec, field_required
from .db import FILES

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def max_upload_bytes():
    return int(os.environ.get("MAX_UPLOAD_MB","8"))*1024*1024

def uid():
    return str(uuid.uuid4())

class PortalError(ValueError):
    def __init__(self, message, status=400, errors=None):
        super().__init__(message)
        self.status = status
        self.errors = errors or {}

def row(db, sql, args=()):
    r = db.execute(sql, args).fetchone()
    return dict(r) if r else None

def rows(db, sql, args=()):
    return [dict(r) for r in db.execute(sql, args).fetchall()]

def audit(db, actor, action, application_id=None, details=""):
    db.execute("INSERT INTO audit_log VALUES (?,?,?,?,?,?)", (uid(), actor, application_id, action, details, now()))

def notify(db, user_id, application_id, message):
    db.execute("INSERT INTO notifications VALUES (?,?,?,?,?,?)", (uid(), user_id, application_id, message, None, now()))

def status_change(db, app, target, actor, note=""):
    allowed = {
        "draft": {"submitted"}, "submitted": {"received", "under_review"},
        "received": {"under_review", "clarification_required"}, "under_review": {"clarification_required", "decision_recorded"},
        "clarification_required": {"resubmission_pending"},
        "resubmission_pending": {"resubmission_received"},
        "resubmission_received": {"under_review", "clarification_required", "decision_recorded"},
        "decision_recorded": {"closed"}, "closed": set(),
    }
    if target not in allowed.get(app["status"], set()):
        raise PortalError(f"Invalid transition from {app['status']} to {target}.", 409)
    db.execute("UPDATE applications SET status=?,updated_at=? WHERE id=?", (target, now(), app["id"]))
    db.execute("INSERT INTO status_history VALUES (?,?,?,?,?,?,?)", (uid(), app["id"], app["status"], target, note, actor, now()))
    audit(db, actor, "status:"+target, app["id"], note)

def register(db, data):
    required = ["name","category","ownership","state","district","address","postal_code","contact_name","designation","email","phone","established_year","username","password"]
    errors = {k:"Required" for k in required if not str(data.get(k,"")).strip()}
    limits={"name":160,"category":80,"ownership":80,"state":80,"district":80,"address":500,"contact_name":120,"designation":100,"approval_ref":100}
    for key,limit in limits.items():
        if len(str(data.get(key,"")))>limit: errors[key]=f"Use at most {limit} characters"
    if data.get("category") not in ("Engineering & Technology","Management","Computer Applications","Applied Arts & Design","Other technical education"):
        errors["category"]="Choose a listed category"
    if data.get("ownership") not in ("Private unaided","Government","Government aided","Trust / Society","Other"):
        errors["ownership"]="Choose a listed ownership type"
    if data.get("email") and ("@" not in data["email"] or len(data["email"])>254): errors["email"]="Enter a valid email"
    if data.get("postal_code") and (not str(data["postal_code"]).isdigit() or len(str(data["postal_code"]))!=6): errors["postal_code"]="Enter a 6-digit code"
    if data.get("phone") and (not str(data["phone"]).isdigit() or len(str(data["phone"]))!=10): errors["phone"]="Enter a 10-digit number"
    if data.get("password") and len(data["password"])<10: errors["password"]="Use at least 10 characters"
    if data.get("username") and not (3<=len(data["username"])<=40 and data["username"].replace("_","").isalnum()): errors["username"]="Use 3–40 letters, digits or underscores"
    try:
        yr=int(data.get("established_year",0))
        if yr<1850 or yr>datetime.now().year: errors["established_year"]="Enter a valid year"
    except ValueError: errors["established_year"]="Enter a valid year"
    if row(db,"SELECT id FROM users WHERE lower(username)=lower(?)",(data.get("username",""),)): errors["username"]="Username already exists"
    if errors: raise PortalError("Please correct the highlighted fields.",400,errors)
    inst_id,user_id=uid(),uid()
    db.execute("INSERT INTO institutions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(inst_id,*[str(data[k]).strip() for k in ["name","category","ownership","state","district","address","postal_code","contact_name","designation","email","phone"]],yr,str(data.get("approval_ref","")).strip(),1,now()))
    db.execute("INSERT INTO users VALUES (?,?,?,?,?,?,?)",(user_id,inst_id,data["username"].strip().lower(),generate_password_hash(data["password"]),"institution",1,now()))
    audit(db,user_id,"institution:registered",None,inst_id)
    return user_id

def login(db, username, password):
    user=row(db,"SELECT * FROM users WHERE lower(username)=lower(?)",(username.strip(),))
    if not user or not user["active"] or not check_password_hash(user["password_hash"],password):
        raise PortalError("Invalid credentials or inactive account.",401)
    return user

def application(db, app_id, user):
    app=row(db,"SELECT a.*,i.name AS institution_name FROM applications a JOIN institutions i ON i.id=a.institution_id WHERE a.id=?",(app_id,))
    if not app or (user["role"]!="admin" and app["institution_id"]!=user["institution_id"]):
        raise PortalError("Application not found.",404)
    app["form"]=json.loads(app.pop("form_json"))
    app["category"]=get_category(app["category_id"])
    return app

def validate_form(category_id, data, complete=False):
    cat=get_category(category_id)
    if not cat: raise PortalError("Unknown application category.",404)
    clean={}; errors={}
    for key in cat["fields"]:
        spec=field_spec(key)
        value=str(data.get(key,"")).strip()
        if len(value)>3000: errors[key]="Too long"
        if complete and field_required(category_id,key) and not value: errors[key]="Required for submission"
        if spec["type"]=="number" and value and (not value.isdigit() or int(value)>100000): errors[key]="Enter a valid non-negative number"
        if spec["type"]=="select" and value and value not in spec["options"]: errors[key]="Choose a listed option"
        clean[key]=value
    if category_id in ("intake-up","intake-down") and complete:
        try:
            a,b=int(clean["current_intake"]),int(clean["proposed_intake"])
            if category_id=="intake-up" and b<=a: errors["proposed_intake"]="Must exceed current intake"
            if category_id=="intake-down" and b>=a: errors["proposed_intake"]="Must be lower than current intake"
        except (ValueError,KeyError): errors["proposed_intake"]="Enter both intake values"
    if errors: raise PortalError("Please correct the application fields.",400,errors)
    return clean

def save_form(db, app, data, actor):
    if app["status"] not in ("draft","clarification_required"):
        raise PortalError("This application cannot be edited now.",409)
    form=validate_form(app["category_id"],data)
    db.execute("UPDATE applications SET form_json=?,declaration=?,updated_at=? WHERE id=?",
               (json.dumps(form),int(str(data.get("declaration","0")).lower() in ("1","on","true")),now(),app["id"]))
    audit(db,actor,"application:saved",app["id"])

def submit(db, app, actor, resubmit=False):
    expected="clarification_required" if resubmit else "draft"
    if app["status"]!=expected: raise PortalError("Application is not in a submittable state.",409)
    validate_form(app["category_id"],app["form"],True)
    if not app["declaration"]: raise PortalError("Confirm the declaration before submitting.")
    uploaded={r["code"] for r in rows(db,"SELECT code FROM documents WHERE application_id=? AND status='uploaded'",(app["id"],))}
    missing=[r["name"] for r in requirements(app["category_id"]) if r["flag"]=="required" and r["code"] not in uploaded]
    if missing: raise PortalError("Upload required documents: "+", ".join(missing))
    target="resubmission_pending" if resubmit else "submitted"
    status_change(db,app,target,actor,"Institution confirmed "+("resubmission" if resubmit else "submission"))
    stamp=now()
    if resubmit:
        db.execute("UPDATE applications SET resubmitted_at=? WHERE id=?",(stamp,app["id"]))
        db.execute("UPDATE clarifications SET resolved_at=? WHERE application_id=? AND resolved_at IS NULL",(stamp,app["id"]))
    else:
        reference=f"EDU-{datetime.now().year}-{app['id'][:8].upper()}"
        db.execute("UPDATE applications SET reference=?,submitted_at=? WHERE id=?",(reference,stamp,app["id"]))
    for admin in rows(db,"SELECT id FROM users WHERE role='admin' AND active=1"):
        notify(db,admin["id"],app["id"],"Application "+("resubmitted" if resubmit else "submitted")+" for review")
    from .integration import queue_submission
    queue_submission(db, app["id"], actor)

def detect_file(data, filename, claimed_type):
    ext=Path(filename).suffix.lower()
    signatures={".pdf":(b"%PDF-","application/pdf"),".png":(b"\x89PNG\r\n\x1a\n","image/png"),".jpg":(b"\xff\xd8\xff","image/jpeg"),".jpeg":(b"\xff\xd8\xff","image/jpeg")}
    if ext not in signatures: raise PortalError("Upload a PDF, PNG, or JPEG file.")
    signature,mime=signatures[ext]
    if not data.startswith(signature) or claimed_type not in (mime,"application/octet-stream"):
        raise PortalError("File content does not match its type.")
    if ext==".pdf" and b"%%EOF" not in data[-2048:]: raise PortalError("PDF appears incomplete.")
    if len(data)>max_upload_bytes(): raise PortalError("File exceeds the configured size limit.")
    if not data: raise PortalError("Empty file.")
    return mime,ext

def store_document(db, app, actor, code, upload):
    if app["status"] not in ("draft","clarification_required"):
        raise PortalError("Documents cannot be changed in this status.",409)
    if code not in {r["code"] for r in requirements(app["category_id"])}:
        raise PortalError("Document type is not on this checklist.")
    original=Path(upload.filename or "").name[:180]
    data=upload.read(max_upload_bytes()+1)
    mime,ext=detect_file(data,original,upload.mimetype)
    doc=row(db,"SELECT * FROM documents WHERE application_id=? AND code=?",(app["id"],code))
    version=(doc["current_version"]+1) if doc else 1
    if version>int(os.environ.get("MAX_VERSIONS_PER_DOCUMENT","10")):
        raise PortalError("Document version limit reached; contact the administrator.")
    doc_id=doc["id"] if doc else uid()
    stored=secrets.token_hex(24)+ext
    path=FILES/stored
    try:
        path.write_bytes(data)
        if doc:
            db.execute("UPDATE documents SET current_version=?,status='uploaded' WHERE id=?",(version,doc_id))
        else:
            db.execute("INSERT INTO documents VALUES (?,?,?,?,?)",(doc_id,app["id"],code,version,"uploaded"))
        db.execute("INSERT INTO document_versions VALUES (?,?,?,?,?,?,?,?,?)",(uid(),doc_id,version,original,stored,mime,len(data),now(),actor))
        audit(db,actor,"document:uploaded",app["id"],f"{code} v{version}")
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return doc_id

def document_detail(db, version_id, user):
    d=row(db,"SELECT v.*,d.application_id,d.code FROM document_versions v JOIN documents d ON d.id=v.document_id WHERE v.id=?",(version_id,))
    if not d: raise PortalError("File not found.",404)
    application(db,d["application_id"],user)
    return d
