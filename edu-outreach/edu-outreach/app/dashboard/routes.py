from flask import (
    Blueprint, render_template, request, redirect, url_for, session, flash, Response, send_file
)

from app.db import db
from app.config import Config
from app.models import (
    Contact, Institution, Exclusion, EmailTemplate, OutreachLog,
    TargetCriteria, SeedUrl, Setting,
)
from app.dashboard.auth import verify_login, login_required
from app.dedup import evaluate_contact_for_sending
from app.export import export_contacts_csv, export_contacts_xlsx
from app.gmail.sender import send_to_contact

bp = Blueprint("dashboard", __name__, template_folder="templates")


# ---------------------------------------------------------------- auth --
@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if verify_login(request.form.get("username", ""), request.form.get("password", "")):
            session["logged_in"] = True
            return redirect(request.args.get("next") or url_for("dashboard.home"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("dashboard.login"))


# ------------------------------------------------------------- home/stats
@bp.route("/")
@login_required
def home():
    stats = {
        "total_contacts": Contact.query.count(),
        "eligible": Contact.query.filter_by(status=Contact.STATUS_ELIGIBLE).count(),
        "needs_review": Contact.query.filter_by(status=Contact.STATUS_NEEDS_REVIEW).count(),
        "previously_contacted": Contact.query.filter_by(status=Contact.STATUS_PREVIOUSLY_CONTACTED).count(),
        "institutions": Institution.query.count(),
        "emails_sent_total": OutreachLog.query.filter_by(status=OutreachLog.STATUS_SENT).count(),
    }
    paused = Setting.get("automation_paused", "false") == "true"
    return render_template("home.html", stats=stats, paused=paused)


@bp.route("/automation/toggle", methods=["POST"])
@login_required
def toggle_automation():
    current = Setting.get("automation_paused", "false") == "true"
    Setting.set("automation_paused", "false" if current else "true")
    flash("Automation resumed." if current else "Automation paused.", "success")
    return redirect(url_for("dashboard.home"))


@bp.route("/run/discovery", methods=["POST"])
@login_required
def run_discovery_now():
    from app.scraper.discovery import run_discovery
    summary = run_discovery()
    flash(f"Discovery run complete: {summary}", "success")
    return redirect(url_for("dashboard.home"))


# -------------------------------------------------------------- contacts
@bp.route("/contacts")
@login_required
def contacts():
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()
    query = Contact.query
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(Contact.name.ilike(like), Contact.email.ilike(like), Contact.department.ilike(like))
        )
    if status:
        query = query.filter_by(status=status)
    all_contacts = query.order_by(Contact.date_discovered.desc()).limit(500).all()
    return render_template(
        "contacts.html", contacts=all_contacts, q=q, status=status, all_statuses=Contact.ALL_STATUSES
    )


@bp.route("/contacts/<int:contact_id>", methods=["GET", "POST"])
@login_required
def contact_detail(contact_id):
    contact = Contact.query.get_or_404(contact_id)
    if request.method == "POST":
        contact.name = request.form.get("name", contact.name)
        contact.title = request.form.get("title", contact.title)
        contact.department = request.form.get("department", contact.department)
        contact.email = request.form.get("email", contact.email)
        contact.status = request.form.get("status", contact.status)
        contact.notes = request.form.get("notes", contact.notes)
        db.session.commit()
        flash("Contact updated.", "success")
        return redirect(url_for("dashboard.contact_detail", contact_id=contact.id))

    eligible, reason = evaluate_contact_for_sending(contact)
    history = OutreachLog.query.filter_by(contact_id=contact.id).order_by(OutreachLog.sent_at.desc()).all()
    return render_template(
        "contact_detail.html", contact=contact, eligible=eligible, reason=reason,
        history=history, all_statuses=Contact.ALL_STATUSES,
    )


@bp.route("/contacts/<int:contact_id>/mark_duplicate/<int:original_id>", methods=["POST"])
@login_required
def mark_duplicate(contact_id, original_id):
    contact = Contact.query.get_or_404(contact_id)
    contact.duplicate_of_id = original_id
    contact.status = Contact.STATUS_DO_NOT_CONTACT
    contact.notes = (contact.notes or "") + f"\n[manual] Marked duplicate of contact #{original_id}."
    db.session.commit()
    flash("Marked as duplicate.", "success")
    return redirect(url_for("dashboard.contact_detail", contact_id=contact_id))


@bp.route("/contacts/<int:contact_id>/send_now", methods=["POST"])
@login_required
def send_now(contact_id):
    contact = Contact.query.get_or_404(contact_id)
    eligible, reason = evaluate_contact_for_sending(contact)
    if not eligible:
        flash(f"Cannot send: {reason}", "error")
        return redirect(url_for("dashboard.contact_detail", contact_id=contact_id))

    template_id = request.form.get("template_id")
    template = EmailTemplate.query.get(template_id) if template_id else EmailTemplate.query.filter_by(active=True).first()
    if not template:
        flash("No email template available.", "error")
        return redirect(url_for("dashboard.contact_detail", contact_id=contact_id))

    result = send_to_contact(contact, template)
    flash(f"Send result: {result.get('status')}", "success" if result.get("status") == "sent" else "error")
    return redirect(url_for("dashboard.contact_detail", contact_id=contact_id))


# ------------------------------------------------------------ exclusions
@bp.route("/exclusions", methods=["GET", "POST"])
@login_required
def exclusions():
    if request.method == "POST":
        excl = Exclusion(
            type=request.form["type"],
            value=request.form["value"].strip().lower(),
            reason=request.form.get("reason", ""),
        )
        db.session.add(excl)
        db.session.commit()
        flash("Exclusion added.", "success")
        return redirect(url_for("dashboard.exclusions"))

    all_exclusions = Exclusion.query.order_by(Exclusion.created_at.desc()).all()
    return render_template("exclusions.html", exclusions=all_exclusions, types=Exclusion.ALL_TYPES)


@bp.route("/exclusions/<int:excl_id>/delete", methods=["POST"])
@login_required
def delete_exclusion(excl_id):
    excl = Exclusion.query.get_or_404(excl_id)
    db.session.delete(excl)
    db.session.commit()
    flash("Exclusion removed.", "success")
    return redirect(url_for("dashboard.exclusions"))


# --------------------------------------------------------------- targets
@bp.route("/targets", methods=["GET", "POST"])
@login_required
def targets():
    if request.method == "POST":
        crit = TargetCriteria(type=request.form["type"], keyword=request.form["keyword"].strip())
        db.session.add(crit)
        db.session.commit()
        flash("Target added.", "success")
        return redirect(url_for("dashboard.targets"))

    titles = TargetCriteria.query.filter_by(type=TargetCriteria.TYPE_TITLE).all()
    disciplines = TargetCriteria.query.filter_by(type=TargetCriteria.TYPE_DISCIPLINE).all()
    return render_template("targets.html", titles=titles, disciplines=disciplines)


@bp.route("/targets/<int:crit_id>/toggle", methods=["POST"])
@login_required
def toggle_target(crit_id):
    crit = TargetCriteria.query.get_or_404(crit_id)
    crit.active = not crit.active
    db.session.commit()
    return redirect(url_for("dashboard.targets"))


@bp.route("/targets/<int:crit_id>/delete", methods=["POST"])
@login_required
def delete_target(crit_id):
    crit = TargetCriteria.query.get_or_404(crit_id)
    db.session.delete(crit)
    db.session.commit()
    return redirect(url_for("dashboard.targets"))


# -------------------------------------------------------------- seed urls
@bp.route("/seeds", methods=["GET", "POST"])
@login_required
def seeds():
    if request.method == "POST":
        seed = SeedUrl(url=request.form["url"].strip(), institution_name=request.form.get("institution_name", "").strip())
        db.session.add(seed)
        db.session.commit()
        flash("Seed URL added.", "success")
        return redirect(url_for("dashboard.seeds"))

    all_seeds = SeedUrl.query.order_by(SeedUrl.id.desc()).all()
    return render_template("seeds.html", seeds=all_seeds)


@bp.route("/seeds/<int:seed_id>/toggle", methods=["POST"])
@login_required
def toggle_seed(seed_id):
    seed = SeedUrl.query.get_or_404(seed_id)
    seed.active = not seed.active
    db.session.commit()
    return redirect(url_for("dashboard.seeds"))


@bp.route("/seeds/<int:seed_id>/delete", methods=["POST"])
@login_required
def delete_seed(seed_id):
    seed = SeedUrl.query.get_or_404(seed_id)
    db.session.delete(seed)
    db.session.commit()
    return redirect(url_for("dashboard.seeds"))


# --------------------------------------------------------------templates
@bp.route("/templates", methods=["GET", "POST"])
@login_required
def templates():
    if request.method == "POST":
        tmpl = EmailTemplate(
            name=request.form["name"], subject=request.form["subject"], body=request.form["body"],
        )
        db.session.add(tmpl)
        db.session.commit()
        flash("Template created.", "success")
        return redirect(url_for("dashboard.templates"))

    all_templates = EmailTemplate.query.order_by(EmailTemplate.name).all()
    return render_template("templates.html", templates=all_templates)


@bp.route("/templates/<int:tmpl_id>", methods=["GET", "POST"])
@login_required
def template_detail(tmpl_id):
    tmpl = EmailTemplate.query.get_or_404(tmpl_id)
    if request.method == "POST":
        tmpl.name = request.form["name"]
        tmpl.subject = request.form["subject"]
        tmpl.body = request.form["body"]
        tmpl.active = "active" in request.form
        db.session.commit()
        flash("Template updated.", "success")
        return redirect(url_for("dashboard.templates"))
    return render_template("template_detail.html", template=tmpl)


# ---------------------------------------------------------------settings
@bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    keys = [
        ("max_emails_per_day", Config.DEFAULT_MAX_EMAILS_PER_DAY),
        ("max_emails_per_month", Config.DEFAULT_MAX_EMAILS_PER_MONTH),
        ("max_per_institution", Config.DEFAULT_MAX_PER_INSTITUTION),
        ("cooldown_days", Config.DEFAULT_COOLDOWN_DAYS),
        ("confidence_threshold", Config.DEFAULT_CONFIDENCE_THRESHOLD),
    ]
    if request.method == "POST":
        for key, _ in keys:
            if key in request.form:
                Setting.set(key, request.form[key])
        flash("Settings saved.", "success")
        return redirect(url_for("dashboard.settings"))

    current = {key: Setting.get(key, default) for key, default in keys}
    return render_template("settings.html", current=current)


# ---------------------------------------------------------------- export
@bp.route("/export/csv")
@login_required
def export_csv():
    data = export_contacts_csv()
    return Response(
        data, mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=contacts_export.csv"},
    )


@bp.route("/export/xlsx")
@login_required
def export_xlsx():
    buffer = export_contacts_xlsx()
    return send_file(
        buffer, as_attachment=True, download_name="contacts_export.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# --------------------------------------------------------------- history
@bp.route("/history")
@login_required
def history():
    logs = OutreachLog.query.order_by(OutreachLog.sent_at.desc()).limit(500).all()
    return render_template("history.html", logs=logs)
