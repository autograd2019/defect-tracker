from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(200), nullable=False, unique=True)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    address = db.Column(db.String(400), nullable=False, default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    defects = db.relationship("Defect", backref="project", lazy=True, cascade="all, delete-orphan")


class Defect(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False)
    unit_number = db.Column(db.String(50), nullable=False, default="")
    trade = db.Column(db.String(100), nullable=False, default="")
    description = db.Column(db.Text, nullable=False, default="")
    status = db.Column(db.String(20), nullable=False, default="Open")
    date_added = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    date_completed = db.Column(db.DateTime, nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    completed_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    created_by = db.relationship("User", foreign_keys=[created_by_id], backref="defects_created")
    completed_by = db.relationship("User", foreign_keys=[completed_by_id], backref="defects_completed")
    photos = db.relationship("DefectPhoto", backref="defect", lazy=True, cascade="all, delete-orphan")


class DefectPhoto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    defect_id = db.Column(db.Integer, db.ForeignKey("defect.id"), nullable=False)
    filename = db.Column(db.String(300), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
