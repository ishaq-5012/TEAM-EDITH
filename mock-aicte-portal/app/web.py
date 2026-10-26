import hashlib
import json
import os
import secrets
import threading
import logging
from datetime import datetime, timedelta, timezone
from functools import wraps
from contextlib import contextmanager
from flask import Flask, abort, flash, g, jsonify, make_response, redirect, render_template, request, send_file, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from .db import DATA, DB, FILES, get_db, close_db, initialize
from .catalog import CATEGORIES, FIELDS, field_spec, field_required, get_category, requirements
from .services import PortalError, application, audit, document_detail, login, now, notify, register, row, rows, save_form, status_change, store_document, submit, uid
from . import integration

_sync_wakeup = threading.Event()

def wake_sync():
    _sync_wakeup.set()

def run_sync_worker():
    """Deliver queued submissions and pull review updates while the local portal runs."""
    while True:
        if os.environ.get("VERIFYFLOW_INTAKE_URL") and os.environ.get("VERIFYFLOW_INTAKE_SECRET"):
            db = None
            try:
                from .db import connect
                db = connect()
                integration.deliver_pending(db, limit=20)
                integration.reconcile_status(db, limit=50)
            except Exception:
                logging.exception("VerifyFlow synchronization failed; queued work will be retried")
            finally:
                if db is not None:
                    db.close()
        _sync_wakeup.wait(timeout=30)
        _sync_wakeup.clear()

env_file=os.path.join(os.path.dirname(os.path.dirname(__file__)),".env")
if os.path.exists(env_file):
    for line in open(env_file,encoding="utf-8"):
        if "=" in line and not line.lstrip().startswith("#"):
            key,value=line.strip().split("=",1)
            os.environ.setdefault(key,value)
app=Flask(__name__)
app.config.update(SECRET_KEY=os.environ.get("SECRET_KEY",secrets.token_hex(32)),MAX_CONTENT_LENGTH=(int(os.environ.get("MAX_UPLOAD_MB","8"))+1)*1024*1024)
app.teardown_appcontext(close_db)
initialize()

@contextmanager
def atomic(db):
    db.execute("BEGIN IMMEDIATE")
    try:
        yield
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise

def payload():
    if request.is_json:
        data=request.get_json(silent=True)
        return data if isinstance(data,dict) else {}
    return request.form.to_dict()

def is_api():
    return request.path.startswith("/api/")

def result(data=None, message="Saved", location=None, status=200):
    if is_api(): return jsonify({"ok":True,"message":message,"data":data}),status
    flash(message,"success")
    return redirect(location or request.referrer or url_for("dashboard"))

@app.errorhandler(PortalError)
def portal_error(error):
    if is_api(): return jsonify({"ok":False,"error":str(error),"fields":error.errors}),error.status
    flash(str(error),"error")
    if request.method=="POST": return redirect(request.referrer or url_for("dashboard"))
    return render_template("error.html",error=error),error.status

@app.errorhandler(413)
def too_large(_):
    return portal_error(PortalError(f"Upload exceeds the {os.environ.get('MAX_UPLOAD_MB','8')} MB file limit.",413))

@app.before_request
def authenticate():
    g.user=None; g.csrf=None
    token=request.cookies.get("edu_session","")
    if token:
        session=row(get_db(),"SELECT s.*,u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.id_hash=? AND s.expires_at>? AND u.active=1",(hashlib.sha256(token.encode()).hexdigest(),now()))
        if session:
            g.user=session
            g.csrf=session["csrf"]
    if request.method in ("POST","PATCH","DELETE") and g.user and request.endpoint not in ("login_page",):
        supplied=request.headers.get("X-CSRF-Token") or request.form.get("csrf") or payload().get("csrf")
        if not secrets.compare_digest(str(supplied or ""),str(g.csrf)):
            raise PortalError("Session form token missing or invalid. Reload and retry.",403)

def role(*roles):
    def outer(fn):
        @wraps(fn)
        def inner(*args,**kwargs):
            if not g.user:
                if is_api(): raise PortalError("Sign in required.",401)
                return redirect(url_for("login_page"))
            if g.user["role"] not in roles: raise PortalError("Access denied.",403)
            return fn(*args,**kwargs)
        return inner
    return outer

@app.context_processor
def globals_for_templates():
    return dict(current_user=g.get("user"),csrf=g.get("csrf"),categories=CATEGORIES,field_spec=field_spec,field_required=field_required,requirements=requirements,max_upload_mb=os.environ.get("MAX_UPLOAD_MB","8"))

def establish_session(user):
    db=get_db(); token=secrets.token_urlsafe(48); csrf=secrets.token_urlsafe(32)
    expiry=(datetime.now(timezone.utc)+timedelta(hours=12)).isoformat(timespec="seconds")
    db.execute("INSERT INTO sessions VALUES (?,?,?,?,?)",(hashlib.sha256(token.encode()).hexdigest(),user["id"],csrf,expiry,now()))
    response=make_response(redirect(url_for("admin_dashboard" if user["role"]=="admin" else "dashboard")))
    response.set_cookie("edu_session",token,httponly=True,samesite="Lax",secure=request.is_secure,max_age=12*3600)
    return response

@app.route("/")
def index():
    if g.user: return redirect(url_for("admin_dashboard" if g.user["role"]=="admin" else "dashboard"))
    return render_template("home.html")

@app.route("/register",methods=["GET","POST"])
@app.route("/api/auth/register",methods=["POST"])
def register_page():
    if request.method=="GET":
        if g.user: return redirect(url_for("admin_dashboard" if g.user["role"]=="admin" else "dashboard"))
        return render_template("register.html",errors={},values={})
    db=get_db()
    try:
        with atomic(db): user_id=register(db,payload() or {})
    except PortalError as error:
        if is_api(): raise
        values={k:v for k,v in (payload() or {}).items() if k!="password"}
        return render_template("register.html",errors=error.errors,values=values,form_error=str(error)),error.status
    user=row(db,"SELECT * FROM users WHERE id=?",(user_id,))
    if is_api(): return jsonify({"ok":True,"data":{"user_id":user_id}}),201
    flash("Institution account created.","success")
    return establish_session(user)

@app.route("/login",methods=["GET","POST"])
@app.route("/api/auth/login",methods=["POST"])
def login_page():
    if request.method=="GET":
        if g.user: return redirect(url_for("admin_dashboard" if g.user["role"]=="admin" else "dashboard"))
        return render_template("login.html")
    data=payload() or {}
    user=login(get_db(),str(data.get("username","")),str(data.get("password","")))
    if is_api():
        token=secrets.token_urlsafe(48); csrf=secrets.token_urlsafe(32)
        expiry=(datetime.now(timezone.utc)+timedelta(hours=12)).isoformat(timespec="seconds")
        get_db().execute("INSERT INTO sessions VALUES (?,?,?,?,?)",(hashlib.sha256(token.encode()).hexdigest(),user["id"],csrf,expiry,now()))
        response=make_response(jsonify({"ok":True,"data":{"role":user["role"],"csrf":csrf}}))
        response.set_cookie("edu_session",token,httponly=True,samesite="Lax",secure=request.is_secure,max_age=12*3600)
        return response
    return establish_session(user)

@app.route("/api/evaluator-credentials")
def evaluator_credentials():
    path=DATA / "evaluator-accounts.json"
    if os.environ.get("PORTAL_EVALUATOR_AUTOFILL")!="1" or not path.is_file():
        abort(404)
    accounts=[]
    for entry in json.loads(path.read_text(encoding="utf-8")):
        user=row(get_db(),"SELECT * FROM users WHERE username=? AND role='institution' AND active=1",(entry["username"],))
        if user and check_password_hash(user["password_hash"],entry["password"]):
            accounts.append(entry)
    response=jsonify({"accounts":accounts})
    response.headers["Cache-Control"]="no-store"
    return response

@app.route("/logout",methods=["POST"])
@app.route("/api/auth/logout",methods=["POST"])
@role("institution","admin")
def logout():
    token=request.cookies.get("edu_session","")
    get_db().execute("DELETE FROM sessions WHERE id_hash=?",(hashlib.sha256(token.encode()).hexdigest(),))
    response=make_response((jsonify({"ok":True}) if is_api() else redirect(url_for("index"))))
    response.delete_cookie("edu_session")
    return response

@app.route("/dashboard")
@role("institution")
def dashboard():
    db=get_db()
    inst=row(db,"SELECT * FROM institutions WHERE id=?",(g.user["institution_id"],))
    apps=rows(db,"SELECT a.*,c.name category_name FROM applications a JOIN categories c ON c.id=a.category_id WHERE institution_id=? ORDER BY updated_at DESC",(inst["id"],))
    notices=rows(db,"SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 8",(g.user["id"],))
    history=rows(db,"SELECT h.*,a.reference,c.name category_name FROM status_history h JOIN applications a ON a.id=h.application_id JOIN categories c ON c.id=a.category_id WHERE a.institution_id=? ORDER BY h.at DESC LIMIT 8",(inst["id"],))
    reminders=[]
    for a in apps:
        if a["status"] in ("draft","clarification_required"):
            uploaded={d["code"] for d in rows(db,"SELECT code FROM documents WHERE application_id=? AND status='uploaded'",(a["id"],))}
            missing=[r["name"] for r in requirements(a["category_id"]) if r["flag"]=="required" and r["code"] not in uploaded]
            if missing: reminders.append({"app":a,"missing":missing})
    return render_template("dashboard.html",institution=inst,apps=apps,notices=notices,history=history,reminders=reminders)

@app.route("/profile",methods=["GET","POST"])
@app.route("/api/institutions/me",methods=["GET","PATCH"],endpoint="api_profile")
@role("institution")
def profile():
    db=get_db(); inst=row(db,"SELECT * FROM institutions WHERE id=?",(g.user["institution_id"],))
    if request.method=="GET": return jsonify({"ok":True,"data":inst}) if is_api() else render_template("profile.html",institution=inst)
    data=payload() or {}
    fields=["address","district","state","postal_code","contact_name","designation","email","phone","approval_ref"]
    clean={k:str(data.get(k,inst[k])).strip() for k in fields}
    if not all(clean[k] for k in fields if k!="approval_ref"):
        raise PortalError("Complete all contact and address fields.")
    if len(clean["postal_code"])!=6 or not clean["postal_code"].isdigit(): raise PortalError("Postal code must have 6 digits.")
    if len(clean["phone"])!=10 or not clean["phone"].isdigit(): raise PortalError("Phone must have 10 digits.")
    if "@" not in clean["email"] or len(clean["email"])>254: raise PortalError("Enter a valid institutional email.")
    if any(len(clean[k])>limit for k,limit in {"address":500,"district":80,"state":80,"contact_name":120,"designation":100,"approval_ref":100}.items()):
        raise PortalError("Profile text exceeds a field limit.")
    with atomic(db):
        db.execute("UPDATE institutions SET "+",".join(k+"=?" for k in fields)+" WHERE id=?",(*clean.values(),inst["id"]))
        audit(db,g.user["id"],"institution:updated",None,inst["id"])
    return result(message="Profile updated.",location=url_for("profile"))

@app.route("/applications/new",methods=["GET","POST"])
@app.route("/api/applications",methods=["GET","POST"],endpoint="api_applications_collection")
@role("institution")
def applications_collection():
    db=get_db()
    if request.method=="GET":
        if is_api(): return jsonify({"ok":True,"data":rows(db,"SELECT * FROM applications WHERE institution_id=? ORDER BY updated_at DESC",(g.user["institution_id"],))})
        return render_template("catalogue.html")
    category_id=str((payload() or {}).get("category_id",""))
    if not get_category(category_id): raise PortalError("Select a valid category.")
    app_id=uid()
    inst=row(db,"SELECT approval_ref FROM institutions WHERE id=?",(g.user["institution_id"],))
    initial={"approval_ref":inst["approval_ref"]} if inst["approval_ref"] and "approval_ref" in get_category(category_id)["fields"] else {}
    with atomic(db):
        db.execute("INSERT INTO applications (id,institution_id,category_id,status,form_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",(app_id,g.user["institution_id"],category_id,"draft",json.dumps(initial),now(),now()))
        db.execute("INSERT INTO status_history VALUES (?,?,?,?,?,?,?)",(uid(),app_id,None,"draft","Application created",g.user["id"],now()))
        audit(db,g.user["id"],"application:created",app_id)
    return result({"id":app_id},"Draft created.",url_for("application_page",app_id=app_id),201)

def app_context(app_id):
    db=get_db(); a=application(db,app_id,g.user)
    docs=rows(db,"SELECT d.*,v.id version_id,v.original_name,v.mime,v.size,v.uploaded_at FROM documents d JOIN document_versions v ON v.document_id=d.id AND v.version=d.current_version WHERE d.application_id=?",(app_id,))
    history=rows(db,"SELECT h.*,u.username actor FROM status_history h JOIN users u ON u.id=h.actor_id WHERE h.application_id=? ORDER BY h.at",(app_id,))
    clarifications=rows(db,"SELECT * FROM clarifications WHERE application_id=? ORDER BY created_at DESC",(app_id,))
    versions=rows(db,"SELECT v.*,d.code FROM document_versions v JOIN documents d ON d.id=v.document_id WHERE d.application_id=? ORDER BY v.uploaded_at DESC",(app_id,))
    institution=row(db,"SELECT * FROM institutions WHERE id=?",(a["institution_id"],))
    delivery=row(db,"SELECT submission_version,state,attempts,last_error,delivered_at FROM integration_outbox WHERE application_id=? ORDER BY submission_version DESC LIMIT 1",(app_id,))
    uploaded={d["code"] for d in docs if d["status"]=="uploaded"}
    missing_fields=[field_spec(key)["label"] for key in a["category"]["fields"] if field_required(a["category_id"],key) and not str(a["form"].get(key,"")).strip()]
    missing_documents=[req["name"] for req in requirements(a["category_id"]) if req["flag"]=="required" and req["code"] not in uploaded]
    readiness=dict(fields=missing_fields,documents=missing_documents,declaration=bool(a["declaration"]),ready=not missing_fields and not missing_documents and bool(a["declaration"]))
    return dict(appitem=a,docs=docs,history=history,clarifications=clarifications,versions=versions,institution=institution,delivery=delivery,readiness=readiness)

@app.route("/applications/<app_id>")
@app.route("/api/applications/<app_id>",endpoint="api_application_page")
@role("institution","admin")
def application_page(app_id):
    context=app_context(app_id)
    if is_api(): return jsonify({"ok":True,"data":context})
    return render_template("application.html",**context)

@app.route("/applications/<app_id>/save",methods=["POST"])
@app.route("/api/applications/<app_id>",methods=["PATCH"],endpoint="api_save_application")
@role("institution")
def save_application(app_id):
    db=get_db(); a=application(db,app_id,g.user)
    with atomic(db): save_form(db,a,payload() or {},g.user["id"])
    if (payload() or {}).get("intent")=="submit":
        updated=application(db,app_id,g.user)
        with atomic(db): submit(db,updated,g.user["id"],updated["status"]=="clarification_required")
        wake_sync()
        return result(message="Application saved and queued for VerifyFlow delivery.",location=url_for("application_page",app_id=app_id))
    return result(message="Draft saved.",location=url_for("application_page",app_id=app_id)+"#proposal")

@app.route("/applications/<app_id>/upload",methods=["POST"])
@app.route("/api/applications/<app_id>/documents",methods=["POST"],endpoint="api_upload_document")
@role("institution")
def upload_document(app_id):
    db=get_db(); a=application(db,app_id,g.user)
    upload=request.files.get("file")
    if not upload: raise PortalError("Choose a file.")
    with atomic(db): doc_id=store_document(db,a,g.user["id"],request.form.get("code",""),upload)
    return result({"id":doc_id},"Document uploaded.",url_for("application_page",app_id=app_id)+"#evidence",201)

@app.route("/files/<version_id>")
@app.route("/api/files/<version_id>",endpoint="api_file_download")
@role("institution","admin")
def file_download(version_id):
    d=document_detail(get_db(),version_id,g.user)
    response=send_file(FILES/d["stored_name"],mimetype=d["mime"],as_attachment=True,download_name=d["original_name"])
    response.headers["X-Content-Type-Options"]="nosniff"
    response.headers["Cache-Control"]="private, no-store"
    return response

@app.route("/applications/<app_id>/submit",methods=["POST"])
@app.route("/api/applications/<app_id>/submit",methods=["POST"],endpoint="api_submit_application")
@app.route("/api/applications/<app_id>/resubmit",methods=["POST"],endpoint="api_resubmit_application")
@role("institution")
def submit_application(app_id):
    db=get_db(); a=application(db,app_id,g.user)
    resubmit=request.path.endswith("resubmit") or a["status"]=="clarification_required"
    with atomic(db): submit(db,a,g.user["id"],resubmit)
    wake_sync()
    return result(message="Resubmission saved; delivery to VerifyFlow is pending." if resubmit else "Application saved; delivery to VerifyFlow is pending.",location=url_for("application_page",app_id=app_id))

@app.route("/api/application-categories")
def api_categories(): return jsonify({"ok":True,"data":CATEGORIES})

@app.route("/api/application-categories/<category_id>/requirements")
def api_requirements(category_id):
    if not get_category(category_id): raise PortalError("Unknown category.",404)
    return jsonify({"ok":True,"data":requirements(category_id)})

@app.route("/api/applications/<app_id>/history")
@app.route("/api/applications/<app_id>/status")
@role("institution","admin")
def api_history(app_id):
    a=application(get_db(),app_id,g.user)
    return jsonify({"ok":True,"data":app_context(app_id)["history"] if request.path.endswith("history") else {"status":a["status"],"reference":a["reference"]}})

@app.route("/admin")
@app.route("/api/admin/applications",endpoint="api_admin_dashboard")
@role("admin")
def admin_dashboard():
    db=get_db(); status=request.args.get("status",""); query=request.args.get("q","").strip()
    sql="SELECT a.*,i.name institution_name,c.name category_name FROM applications a JOIN institutions i ON i.id=a.institution_id JOIN categories c ON c.id=a.category_id WHERE 1=1"
    args=[]
    if status: sql+=" AND a.status=?";args.append(status)
    if query: sql+=" AND (i.name LIKE ? OR a.reference LIKE ? OR c.name LIKE ?)";args.extend(["%"+query+"%"]*3)
    apps=rows(db,sql+" ORDER BY a.updated_at DESC LIMIT 200",args)
    institutions=rows(db,"SELECT i.*,u.username,u.active,u.id user_id FROM institutions i JOIN users u ON u.institution_id=i.id ORDER BY i.created_at DESC")
    audit_items=rows(db,"SELECT l.*,u.username FROM audit_log l JOIN users u ON u.id=l.actor_id ORDER BY l.at DESC LIMIT 35")
    failed_deliveries=row(db,"SELECT count(*) n FROM integration_outbox WHERE state='failed'")["n"]
    if is_api(): return jsonify({"ok":True,"data":apps})
    return render_template("admin.html",apps=apps,institutions=institutions,audit_items=audit_items,failed_deliveries=failed_deliveries,status_filter=status,query=query)

@app.route("/admin/applications/<app_id>")
@role("admin")
def admin_application(app_id): return render_template("admin_application.html",**app_context(app_id))

@app.route("/admin/applications/<app_id>/action",methods=["POST"])
@app.route("/api/admin/applications/<app_id>/action",methods=["POST"])
@role("admin")
def admin_action(app_id):
    db=get_db(); a=application(db,app_id,g.user); data=payload() or {}; action=data.get("action","")
    with atomic(db):
        if action=="assign":
            reviewer=str(data.get("reviewer","")).strip()[:80]
            if not reviewer: raise PortalError("Enter a reviewer name.")
            db.execute("UPDATE applications SET reviewer=?,updated_at=? WHERE id=?",(reviewer,now(),app_id))
            audit(db,g.user["id"],"reviewer:assigned",app_id,reviewer)
        elif action=="start_review":
            if a["status"] not in ("submitted","received","resubmission_received"): raise PortalError("Cannot start review from this status.",409)
            status_change(db,a,"under_review",g.user["id"],"Review started")
        elif action=="clarification":
            message=str(data.get("message","")).strip()
            if len(message)<10 or len(message)>2000: raise PortalError("Clarification must contain 10–2000 characters.")
            if a["status"] not in ("under_review","resubmission_received"): raise PortalError("Cannot request clarification from this status.",409)
            document_code=str(data.get("document_code","")).strip()
            if document_code:
                document_status=str(data.get("document_status","replacement_required"))
                if document_status not in ("rejected","replacement_required"):
                    raise PortalError("Choose a valid document review outcome.")
                doc=row(db,"SELECT * FROM documents WHERE application_id=? AND code=?",(app_id,document_code))
                if not doc: raise PortalError("Select an uploaded document for replacement.")
                db.execute("UPDATE documents SET status=? WHERE id=?",(document_status,doc["id"]))
                audit(db,g.user["id"],"document:"+document_status,app_id,document_code)
            db.execute("INSERT INTO clarifications VALUES (?,?,?,?,?,?)",(uid(),app_id,message,g.user["id"],now(),None))
            status_change(db,a,"clarification_required",g.user["id"],"Clarification requested")
            for u in rows(db,"SELECT id FROM users WHERE institution_id=? AND active=1",(a["institution_id"],)):
                notify(db,u["id"],app_id,"Clarification requested: "+message[:120])
        elif action=="decision":
            delivered=row(db,"SELECT id FROM integration_outbox WHERE application_id=? AND state='delivered' LIMIT 1",(app_id,))
            if delivered and a["verifyflow_stage"]!="approved":
                raise PortalError("Await VerifyFlow auditor approval before recording a decision.",409)
            decision=str(data.get("decision","")).strip()
            if len(decision)<10 or len(decision)>2000: raise PortalError("Enter a 10–2000 character decision note.")
            if a["status"] not in ("under_review","resubmission_received"): raise PortalError("Cannot record a decision from this status.",409)
            db.execute("UPDATE applications SET decision=? WHERE id=?",(decision,app_id))
            status_change(db,a,"decision_recorded",g.user["id"],"Decision recorded")
            for u in rows(db,"SELECT id FROM users WHERE institution_id=? AND active=1",(a["institution_id"],)):
                notify(db,u["id"],app_id,"A decision was recorded.")
        elif action=="close": status_change(db,a,"closed",g.user["id"],"File closed")
        else: raise PortalError("Unknown action.")
    return result(message="Administrative action recorded.",location=url_for("admin_application",app_id=app_id))

@app.route("/admin/users/<user_id>/toggle",methods=["POST"])
@role("admin")
def toggle_user(user_id):
    db=get_db(); user=row(db,"SELECT * FROM users WHERE id=? AND role='institution'",(user_id,))
    if not user: raise PortalError("Institution user not found.",404)
    with atomic(db):
        db.execute("UPDATE users SET active=? WHERE id=?",(0 if user["active"] else 1,user_id))
        db.execute("DELETE FROM sessions WHERE user_id=?",(user_id,))
        audit(db,g.user["id"],"account:"+("disabled" if user["active"] else "enabled"),None,user_id)
    return result(message="Account access updated.",location=url_for("admin_dashboard"))

@app.route("/health")
def health(): return jsonify({"ok":True,"database":DB.exists()})

if __name__=="__main__":
    threading.Thread(target=run_sync_worker,name="verifyflow-sync",daemon=True).start()
    app.run(debug=False,port=int(os.environ.get("PORT","5000")))
