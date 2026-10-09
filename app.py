import os
from pathlib import Path
from uuid import uuid4

import boto3
import pymysql
from flask import Flask, jsonify, render_template, request
from werkzeug.utils import secure_filename


ALLOWED_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".png", ".webp"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024


def required_setting(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Required setting {name} is not configured")
    return value


def get_db():
    return pymysql.connect(
        host=required_setting("DB_HOST"),
        port=int(os.environ.get("DB_PORT", "3306")),
        user=required_setting("DB_USER"),
        password=required_setting("DB_PASSWORD"),
        database=os.environ.get("DB_NAME", "studentdb"),
        connect_timeout=5,
    )


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/health")
def health():
    try:
        with get_db() as db:
            with db.cursor() as cursor:
                cursor.execute("SELECT 1")
        return jsonify(status="ok"), 200
    except Exception:
        app.logger.exception("Health check failed")
        return jsonify(status="unavailable"), 503


@app.post("/register")
def register():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    course = request.form.get("course", "").strip()
    photo = request.files.get("photo")

    if not all((name, email, course, photo, photo.filename)):
        return jsonify(error="Name, email, course, and photo are required."), 400

    filename = secure_filename(photo.filename)
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        return jsonify(error="Photo must be a GIF, JPEG, PNG, or WebP image."), 400

    bucket_name = required_setting("S3_BUCKET_NAME")
    object_key = f"uploads/{uuid4().hex}{suffix}"

    try:
        boto3.client("s3").upload_fileobj(
            photo,
            bucket_name,
            object_key,
            ExtraArgs={"ContentType": photo.mimetype or "application/octet-stream"},
        )

        with get_db() as db:
            with db.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO students (name, email, course, photo_url)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (name, email, course, f"s3://{bucket_name}/{object_key}"),
                )
            db.commit()
    except Exception:
        app.logger.exception("Student registration failed")
        return jsonify(error="Unable to register the student. Please try again."), 503

    return jsonify(message="Student registered successfully."), 201


@app.errorhandler(413)
def file_too_large(_error):
    return jsonify(error="Photo must be 5 MB or smaller."), 413


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
