import csv
import io
import os
import uuid
from datetime import datetime, timezone
from functools import wraps

from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.utils import secure_filename

import config
from models import Defect, DefectPhoto, Project, db

app = Flask(__name__)
app.config.from_object(config)

db.init_app(app)

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

with app.app_context():
    db.create_all()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


@app.route("/")
def index():
    if session.get("authenticated"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == config.APP_PASSWORD:
            session["authenticated"] = True
            return redirect(url_for("dashboard"))
        flash("Incorrect password.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Dashboard / Projects
# ---------------------------------------------------------------------------

@app.route("/dashboard")
@login_required
def dashboard():
    projects = Project.query.order_by(Project.created_at.desc()).all()
    return render_template("dashboard.html", projects=projects)


@app.route("/projects", methods=["POST"])
@login_required
def create_project():
    name = request.form.get("name", "").strip()
    address = request.form.get("address", "").strip()
    if not name:
        flash("Project name is required.", "danger")
        return redirect(url_for("dashboard"))
    project = Project(name=name, address=address)
    db.session.add(project)
    db.session.commit()
    flash(f"Project '{name}' created.", "success")
    return redirect(url_for("dashboard"))


# ---------------------------------------------------------------------------
# Defect register (project view)
# ---------------------------------------------------------------------------

@app.route("/project/<int:project_id>")
@login_required
def project_view(project_id):
    project = db.get_or_404(Project, project_id)

    query = Defect.query.filter_by(project_id=project_id)

    # Filters
    trade = request.args.get("trade", "")
    unit = request.args.get("unit", "")
    status = request.args.get("status", "")
    search = request.args.get("search", "")
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")

    if trade:
        query = query.filter(Defect.trade == trade)
    if unit:
        query = query.filter(Defect.unit_number == unit)
    if status:
        query = query.filter(Defect.status == status)
    if search:
        query = query.filter(Defect.description.ilike(f"%{search}%"))
    if date_from:
        try:
            dt = datetime.strptime(date_from, "%Y-%m-%d")
            query = query.filter(Defect.date_added >= dt)
        except ValueError:
            pass
    if date_to:
        try:
            dt = datetime.strptime(date_to, "%Y-%m-%d")
            dt = dt.replace(hour=23, minute=59, second=59)
            query = query.filter(Defect.date_added <= dt)
        except ValueError:
            pass

    defects = query.order_by(Defect.date_added.desc()).all()

    # Gather distinct unit numbers and trades for filter dropdowns
    all_defects = Defect.query.filter_by(project_id=project_id).all()
    units = sorted({d.unit_number for d in all_defects if d.unit_number})
    trades_used = sorted({d.trade for d in all_defects if d.trade})

    return render_template(
        "project.html",
        project=project,
        defects=defects,
        units=units,
        trades_used=trades_used,
        trades=config.TRADES,
        filters=dict(trade=trade, unit=unit, status=status, search=search, date_from=date_from, date_to=date_to),
    )


# ---------------------------------------------------------------------------
# Add defect
# ---------------------------------------------------------------------------

@app.route("/project/<int:project_id>/add", methods=["GET", "POST"])
@login_required
def add_defect(project_id):
    project = db.get_or_404(Project, project_id)

    if request.method == "POST":
        defect = Defect(
            project_id=project_id,
            unit_number=request.form.get("unit_number", "").strip(),
            trade=request.form.get("trade", "").strip(),
            description=request.form.get("description", "").strip(),
            status="Open",
        )
        db.session.add(defect)
        db.session.flush()  # get defect.id

        # Handle uploaded photos
        files = request.files.getlist("photos")
        for f in files:
            if f and f.filename:
                ext = os.path.splitext(f.filename)[1].lower()
                filename = f"{uuid.uuid4().hex}{ext}"
                f.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
                photo = DefectPhoto(defect_id=defect.id, filename=filename)
                db.session.add(photo)

        db.session.commit()
        flash("Defect added.", "success")
        return redirect(url_for("project_view", project_id=project_id))

    return render_template("add_defect.html", project=project, trades=config.TRADES)


# ---------------------------------------------------------------------------
# Defect detail
# ---------------------------------------------------------------------------

@app.route("/defect/<int:defect_id>")
@login_required
def defect_detail(defect_id):
    defect = db.get_or_404(Defect, defect_id)
    return render_template("defect_detail.html", defect=defect, trades=config.TRADES)


@app.route("/defect/<int:defect_id>/update", methods=["POST"])
@login_required
def update_defect(defect_id):
    defect = db.get_or_404(Defect, defect_id)

    defect.unit_number = request.form.get("unit_number", defect.unit_number).strip()
    defect.trade = request.form.get("trade", defect.trade).strip()
    defect.description = request.form.get("description", defect.description).strip()

    new_status = request.form.get("status", defect.status).strip()
    if new_status == "Completed" and defect.status != "Completed":
        defect.date_completed = datetime.now(timezone.utc)
    elif new_status != "Completed":
        defect.date_completed = None
    defect.status = new_status

    db.session.commit()
    flash("Defect updated.", "success")
    return redirect(url_for("defect_detail", defect_id=defect_id))


@app.route("/defect/<int:defect_id>/photos", methods=["POST"])
@login_required
def add_photos(defect_id):
    defect = db.get_or_404(Defect, defect_id)
    files = request.files.getlist("photos")
    count = 0
    for f in files:
        if f and f.filename:
            ext = os.path.splitext(f.filename)[1].lower()
            filename = f"{uuid.uuid4().hex}{ext}"
            f.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
            photo = DefectPhoto(defect_id=defect.id, filename=filename)
            db.session.add(photo)
            count += 1
    db.session.commit()
    if count:
        flash(f"{count} photo(s) added.", "success")
    return redirect(url_for("defect_detail", defect_id=defect_id))


@app.route("/defect/<int:defect_id>/status", methods=["POST"])
@login_required
def quick_status(defect_id):
    """Inline status toggle from the register table."""
    defect = db.get_or_404(Defect, defect_id)
    new_status = request.form.get("status", defect.status)
    if new_status in ("Open", "In Progress", "Completed"):
        if new_status == "Completed" and defect.status != "Completed":
            defect.date_completed = datetime.now(timezone.utc)
        elif new_status != "Completed":
            defect.date_completed = None
        defect.status = new_status
        db.session.commit()
    return redirect(request.referrer or url_for("project_view", project_id=defect.project_id))


# ---------------------------------------------------------------------------
# Serve uploaded photos
# ---------------------------------------------------------------------------

@app.route("/uploads/<filename>")
@login_required
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


# ---------------------------------------------------------------------------
# CSV import
# ---------------------------------------------------------------------------

@app.route("/project/<int:project_id>/import", methods=["GET", "POST"])
@login_required
def import_csv(project_id):
    project = db.get_or_404(Project, project_id)

    if request.method == "POST":
        file = request.files.get("csv_file")
        if not file or not file.filename:
            flash("Please select a CSV file.", "danger")
            return redirect(url_for("import_csv", project_id=project_id))

        try:
            stream = io.StringIO(file.stream.read().decode("utf-8-sig"))
            reader = csv.DictReader(stream)

            count = 0
            for row in reader:
                # Support flexible column names
                unit = (
                    row.get("Unit Number", "")
                    or row.get("Unit", "")
                    or row.get("unit_number", "")
                    or row.get("unit", "")
                ).strip()

                trade = (
                    row.get("Responsible Trade", "")
                    or row.get("Trade", "")
                    or row.get("trade", "")
                ).strip()

                description = (
                    row.get("Defect", "")
                    or row.get("Description", "")
                    or row.get("description", "")
                    or row.get("defect", "")
                ).strip()

                status = (
                    row.get("Status", "")
                    or row.get("status", "")
                ).strip()
                if status not in ("Open", "In Progress", "Completed"):
                    status = "Open"

                if not description:
                    continue

                defect = Defect(
                    project_id=project_id,
                    unit_number=unit,
                    trade=trade,
                    description=description,
                    status=status,
                )
                db.session.add(defect)
                count += 1

            db.session.commit()
            flash(f"Imported {count} defects.", "success")
            return redirect(url_for("project_view", project_id=project_id))

        except Exception as e:
            db.session.rollback()
            flash(f"Import error: {e}", "danger")
            return redirect(url_for("import_csv", project_id=project_id))

    return render_template("import_csv.html", project=project)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
