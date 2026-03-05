import csv
import io
import os
import uuid
from datetime import datetime, timezone
from functools import wraps

from flask import (
    Flask,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
    g,
)
from werkzeug.utils import secure_filename

import config
from models import Defect, DefectPhoto, Project, User, db

app = Flask(__name__)
app.config.from_object(config)

db.init_app(app)

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

with app.app_context():
    db.create_all()


@app.after_request
def add_no_cache(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    return response


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

ALLOWED_DOMAIN = "pembc.com.au"


@app.before_request
def load_user():
    g.user = None
    user_id = session.get("user_id")
    if user_id:
        g.user = db.session.get(User, user_id)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not g.user:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


@app.context_processor
def inject_user():
    return dict(current_user=g.user)


@app.route("/")
def index():
    if g.user:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            session["user_id"] = user.id
            return redirect(url_for("dashboard"))
        flash("Invalid email or password.", "danger")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        errors = []
        if not name:
            errors.append("Name is required.")
        if not email or not email.endswith(f"@{ALLOWED_DOMAIN}"):
            errors.append(f"Email must be a @{ALLOWED_DOMAIN} address.")
        if len(password) < 6:
            errors.append("Password must be at least 6 characters.")
        if password != confirm:
            errors.append("Passwords do not match.")
        if User.query.filter_by(email=email).first():
            errors.append("An account with this email already exists.")

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("register.html", name=name, email=email)

        user = User(name=name, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        session["user_id"] = user.id
        flash(f"Welcome, {name}!", "success")
        return redirect(url_for("dashboard"))

    return render_template("register.html", name="", email="")


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
# Helpers: build filtered query
# ---------------------------------------------------------------------------

def _filtered_defects(project_id):
    """Return (query, filters_dict) applying request.args filters."""
    query = Defect.query.filter_by(project_id=project_id)

    trade = request.args.get("trade", "")
    location = request.args.get("location", "")
    status = request.args.get("status", "")
    search = request.args.get("search", "")
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")

    if trade:
        query = query.filter(Defect.trade == trade)
    if location:
        query = query.filter(Defect.unit_number == location)
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

    filters = dict(trade=trade, location=location, status=status, search=search, date_from=date_from, date_to=date_to)
    return query, filters


def _filter_description(filters):
    """Human-readable description of active filters."""
    parts = []
    if filters["trade"]:
        parts.append(f"Trade: {filters['trade']}")
    if filters["location"]:
        parts.append(f"Location: {filters['location']}")
    if filters["status"]:
        parts.append(f"Status: {filters['status']}")
    if filters["search"]:
        parts.append(f"Search: {filters['search']}")
    if filters["date_from"]:
        parts.append(f"From: {filters['date_from']}")
    if filters["date_to"]:
        parts.append(f"To: {filters['date_to']}")
    return ", ".join(parts) if parts else "All Defects"


# ---------------------------------------------------------------------------
# Defect register (project view)
# ---------------------------------------------------------------------------

@app.route("/project/<int:project_id>")
@login_required
def project_view(project_id):
    project = db.get_or_404(Project, project_id)

    query, filters = _filtered_defects(project_id)
    defects = query.order_by(Defect.date_added.desc()).all()

    all_defects = Defect.query.filter_by(project_id=project_id).all()
    locations = sorted({d.unit_number for d in all_defects if d.unit_number})
    trades_used = sorted({d.trade for d in all_defects if d.trade})

    return render_template(
        "project.html",
        project=project,
        defects=defects,
        locations=locations,
        trades_used=trades_used,
        trades=config.TRADES,
        filters=filters,
    )


# ---------------------------------------------------------------------------
# Export filtered defects as CSV
# ---------------------------------------------------------------------------

@app.route("/project/<int:project_id>/export")
@login_required
def export_csv(project_id):
    project = db.get_or_404(Project, project_id)

    query, filters = _filtered_defects(project_id)
    defects = query.order_by(Defect.date_added.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Location", "Trade", "Description", "Status", "Date Added", "Date Completed", "Created By", "Completed By"])
    for d in defects:
        writer.writerow([
            d.id,
            d.unit_number,
            d.trade,
            d.description,
            d.status,
            d.date_added.strftime("%d/%m/%Y") if d.date_added else "",
            d.date_completed.strftime("%d/%m/%Y") if d.date_completed else "",
            d.created_by.name if d.created_by else "",
            d.completed_by.name if d.completed_by else "",
        ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={project.name} Defects.csv"},
    )


# ---------------------------------------------------------------------------
# Export filtered defects as PDF with photos
# ---------------------------------------------------------------------------

@app.route("/project/<int:project_id>/export-pdf")
@login_required
def export_pdf(project_id):
    from fpdf import FPDF

    project = db.get_or_404(Project, project_id)

    query, filters = _filtered_defects(project_id)
    defects = query.order_by(Defect.unit_number, Defect.date_added.desc()).all()

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)

    # Title page
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 15, project.name, new_x="LMARGIN", new_y="NEXT", align="C")
    if project.address:
        pdf.set_font("Helvetica", "", 12)
        pdf.cell(0, 8, project.address, new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(5)
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 8, f"Defect Report - {_filter_description(filters)}", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.cell(0, 8, f"Generated: {datetime.now().strftime('%d/%m/%Y %H:%M')}", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.cell(0, 8, f"Total: {len(defects)} defect(s)", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(10)

    # Summary table
    pdf.set_font("Helvetica", "B", 10)
    col_widths = [12, 30, 30, 80, 25]
    headers = ["#", "Location", "Trade", "Description", "Status"]
    for i, h in enumerate(headers):
        pdf.cell(col_widths[i], 8, h, border=1, align="C")
    pdf.ln()

    pdf.set_font("Helvetica", "", 9)
    for d in defects:
        desc = d.description[:60] + "..." if len(d.description) > 60 else d.description
        row = [str(d.id), d.unit_number[:20], d.trade[:20], desc, d.status]
        max_h = 8
        for i, val in enumerate(row):
            pdf.cell(col_widths[i], max_h, val, border=1)
        pdf.ln()
        if pdf.get_y() > 270:
            pdf.add_page()

    # Detail pages with photos
    for d in defects:
        pdf.add_page()

        # Header
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, f"Defect #{d.id}", new_x="LMARGIN", new_y="NEXT")

        pdf.set_font("Helvetica", "", 11)
        pdf.cell(0, 7, f"Location: {d.unit_number}", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 7, f"Trade: {d.trade}", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 7, f"Status: {d.status}", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 7, f"Date Added: {d.date_added.strftime('%d/%m/%Y') if d.date_added else 'N/A'}", new_x="LMARGIN", new_y="NEXT")
        if d.created_by:
            pdf.cell(0, 7, f"Created By: {d.created_by.name}", new_x="LMARGIN", new_y="NEXT")
        if d.date_completed:
            completed_info = d.date_completed.strftime('%d/%m/%Y')
            if d.completed_by:
                completed_info += f" by {d.completed_by.name}"
            pdf.cell(0, 7, f"Completed: {completed_info}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, "Description:", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(0, 6, d.description)
        pdf.ln(5)

        # Photos
        if d.photos:
            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(0, 7, f"Photos ({len(d.photos)}):", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(3)

            for photo in d.photos:
                photo_path = os.path.join(app.config["UPLOAD_FOLDER"], photo.filename)
                if os.path.exists(photo_path):
                    try:
                        if pdf.get_y() > 180:
                            pdf.add_page()
                        pdf.image(photo_path, w=90)
                        pdf.ln(5)
                    except Exception:
                        pdf.set_font("Helvetica", "I", 9)
                        pdf.cell(0, 7, f"[Could not load image: {photo.filename}]", new_x="LMARGIN", new_y="NEXT")

    pdf_bytes = bytes(pdf.output())
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={project.name} Defects.pdf"},
    )


# ---------------------------------------------------------------------------
# Add defect
# ---------------------------------------------------------------------------

@app.route("/project/<int:project_id>/add", methods=["GET", "POST"])
@login_required
def add_defect(project_id):
    project = db.get_or_404(Project, project_id)

    if request.method == "POST":
        location = request.form.get("unit_number", "").strip()
        custom_location = request.form.get("custom_location", "").strip()
        if location == "__custom__" and custom_location:
            location = custom_location

        defect = Defect(
            project_id=project_id,
            unit_number=location,
            trade=request.form.get("trade", "").strip(),
            description=request.form.get("description", "").strip(),
            status="Open",
            created_by_id=g.user.id,
        )
        db.session.add(defect)
        db.session.flush()

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

    return render_template("add_defect.html", project=project, trades=config.TRADES, locations=config.LOCATIONS)


# ---------------------------------------------------------------------------
# Defect detail
# ---------------------------------------------------------------------------

@app.route("/defect/<int:defect_id>")
@login_required
def defect_detail(defect_id):
    defect = db.get_or_404(Defect, defect_id)
    return render_template("defect_detail.html", defect=defect, trades=config.TRADES, locations=config.LOCATIONS)


@app.route("/defect/<int:defect_id>/update", methods=["POST"])
@login_required
def update_defect(defect_id):
    defect = db.get_or_404(Defect, defect_id)

    location = request.form.get("unit_number", defect.unit_number).strip()
    custom_location = request.form.get("custom_location", "").strip()
    if location == "__custom__" and custom_location:
        location = custom_location
    defect.unit_number = location

    defect.trade = request.form.get("trade", defect.trade).strip()
    defect.description = request.form.get("description", defect.description).strip()

    new_status = request.form.get("status", defect.status).strip()
    if new_status == "Completed" and defect.status != "Completed":
        defect.date_completed = datetime.now(timezone.utc)
        defect.completed_by_id = g.user.id
    elif new_status != "Completed":
        defect.date_completed = None
        defect.completed_by_id = None
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
    """Inline status change from the register table."""
    defect = db.get_or_404(Defect, defect_id)
    new_status = request.form.get("status", defect.status)
    if new_status in ("Open", "In Progress", "Completed"):
        if new_status == "Completed" and defect.status != "Completed":
            defect.date_completed = datetime.now(timezone.utc)
            defect.completed_by_id = g.user.id
        elif new_status != "Completed":
            defect.date_completed = None
            defect.completed_by_id = None
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
                unit = (
                    row.get("Unit Number", "")
                    or row.get("Location", "")
                    or row.get("Unit", "")
                    or row.get("Unit #", "")
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
                    created_by_id=g.user.id,
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
# Admin: delete all defects for a project
# ---------------------------------------------------------------------------

@app.route("/project/<int:project_id>/delete-all", methods=["POST"])
@login_required
def delete_all_defects(project_id):
    project = db.get_or_404(Project, project_id)

    # Delete all photos from disk
    photos = DefectPhoto.query.join(Defect).filter(Defect.project_id == project_id).all()
    for photo in photos:
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], photo.filename)
        if os.path.exists(filepath):
            os.remove(filepath)

    # Delete photo records
    DefectPhoto.query.filter(
        DefectPhoto.defect_id.in_(
            db.session.query(Defect.id).filter(Defect.project_id == project_id)
        )
    ).delete(synchronize_session=False)

    # Delete defects
    Defect.query.filter_by(project_id=project_id).delete()
    db.session.commit()

    flash("All defects deleted.", "success")
    return redirect(url_for("project_view", project_id=project_id))


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
