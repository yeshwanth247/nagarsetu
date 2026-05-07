import os
import secrets
import sqlite3
from datetime import datetime
from functools import wraps
from math import asin, cos, radians, sin, sqrt
import re

from flask import (
    Flask,
    abort,
    jsonify,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.path.join(BASE_DIR, "civicsetu.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
IMAGE_MIMETYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
VERIFIED_THRESHOLD = 5
SUPPORT_PRIORITY_MEDIUM = 3
SUPPORT_PRIORITY_HIGH = 7
SUPPORT_PRIORITY_CRITICAL = 12
CATEGORIES = [
    "Roads",
    "Drainage",
    "Garbage",
    "Water Supply",
    "Electricity",
    "Street Lights",
    "Public Toilets",
    "Traffic Signals",
    "Parks",
    "Sewage",
    "Animal Issues",
    "Illegal Parking",
    "Government Property Damage",
    "Others",
]

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('citizen', 'admin')),
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS issues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            description TEXT NOT NULL,
            location TEXT NOT NULL,
            category TEXT NOT NULL,
            custom_category TEXT,
            latitude REAL,
            longitude REAL,
            before_image TEXT,
            after_image TEXT,
            resolution_date TEXT,
            verification_count INTEGER NOT NULL DEFAULT 0,
            repost_count INTEGER NOT NULL DEFAULT 0,
            escalation_status TEXT NOT NULL DEFAULT 'Normal',
            complaint_priority TEXT NOT NULL DEFAULT 'Low',
            nearby_duplicate_flag INTEGER NOT NULL DEFAULT 0,
            duplicate_reference INTEGER,
            status TEXT NOT NULL DEFAULT 'Pending',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (duplicate_reference) REFERENCES issues (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS supports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(issue_id, user_id),
            FOREIGN KEY (issue_id) REFERENCES issues (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS updates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (issue_id) REFERENCES issues (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS verifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(issue_id, user_id),
            FOREIGN KEY (issue_id) REFERENCES issues (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS resolution_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            uploaded_at TEXT NOT NULL,
            FOREIGN KEY (issue_id) REFERENCES issues (id)
        );

        CREATE TABLE IF NOT EXISTS complaint_supports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_id INTEGER NOT NULL,
            supporter_user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(issue_id, supporter_user_id),
            FOREIGN KEY (issue_id) REFERENCES issues (id),
            FOREIGN KEY (supporter_user_id) REFERENCES users (id)
        );
        """
    )
    migrate_db(db)
    db.commit()


def migrate_db(db):
    existing = {row["name"] for row in db.execute("PRAGMA table_info(issues)").fetchall()}
    columns = {
        "custom_category": "ALTER TABLE issues ADD COLUMN custom_category TEXT",
        "latitude": "ALTER TABLE issues ADD COLUMN latitude REAL",
        "longitude": "ALTER TABLE issues ADD COLUMN longitude REAL",
        "resolution_date": "ALTER TABLE issues ADD COLUMN resolution_date TEXT",
        "verification_count": "ALTER TABLE issues ADD COLUMN verification_count INTEGER NOT NULL DEFAULT 0",
        "repost_count": "ALTER TABLE issues ADD COLUMN repost_count INTEGER NOT NULL DEFAULT 0",
        "escalation_status": "ALTER TABLE issues ADD COLUMN escalation_status TEXT NOT NULL DEFAULT 'Normal'",
        "complaint_priority": "ALTER TABLE issues ADD COLUMN complaint_priority TEXT NOT NULL DEFAULT 'Low'",
        "nearby_duplicate_flag": "ALTER TABLE issues ADD COLUMN nearby_duplicate_flag INTEGER NOT NULL DEFAULT 0",
        "duplicate_reference": "ALTER TABLE issues ADD COLUMN duplicate_reference INTEGER",
    }
    for name, statement in columns.items():
        if name not in existing:
            db.execute(statement)
    db.execute(
        """
        INSERT OR IGNORE INTO complaint_supports (issue_id, supporter_user_id, created_at)
        SELECT issue_id, user_id, created_at FROM supports
        """
    )


@app.cli.command("init-db")
def init_db_command():
    init_db()
    print("Initialized NagarSetu database.")


@app.before_request
def ensure_database():
    init_db()


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_upload(file_storage, prefix):
    if not file_storage or not file_storage.filename:
        return None
    if not allowed_file(file_storage.filename):
        flash("Please upload an image file: png, jpg, jpeg, gif, or webp.", "error")
        return None
    if file_storage.mimetype not in IMAGE_MIMETYPES:
        flash("The uploaded file must be a valid image.", "error")
        return None
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    filename = secure_filename(file_storage.filename)
    saved_name = f"{prefix}_{stamp}_{filename}"
    file_storage.save(os.path.join(app.config["UPLOAD_FOLDER"], saved_name))
    return saved_name


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


@app.context_processor
def inject_globals():
    return {
        "current_user": current_user(),
        "app_name": "NagarSetu",
        "csrf_token": csrf_token,
        "categories": CATEGORIES,
        "verified_threshold": VERIFIED_THRESHOLD,
    }


def csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


@app.before_request
def protect_post_requests():
    if request.method == "POST":
        token = request.form.get("csrf_token") or request.headers.get("X-CSRFToken")
        if not token or token != session.get("csrf_token"):
            abort(400, description="Invalid CSRF token.")


def login_required(role=None):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if user is None:
                flash("Please log in to continue.", "error")
                return redirect(url_for("auth"))
            if role and user["role"] != role:
                flash("You do not have permission to access that page.", "error")
                return redirect(url_for("home"))
            return view(*args, **kwargs)

        return wrapped

    return decorator


def days_since(created_at):
    created = datetime.fromisoformat(created_at)
    return max((datetime.utcnow() - created).days, 0)


def escalation_for(issue):
    if issue["status"] == "Resolved":
        return "Resolved"
    days = days_since(issue["created_at"])
    if days >= 5:
        return "Escalated"
    if days >= 2:
        return "Warning"
    return "Normal"


def alert_for(issue):
    days = days_since(issue["created_at"])
    if issue["status"] == "Resolved":
        return {"label": "Resolved", "level": "resolved", "days": days, "escalated": False}
    if days >= 5:
        return {"label": "Escalated", "level": "critical", "days": days, "escalated": True}
    if days >= 2:
        return {"label": "Warning", "level": "attention", "days": days, "escalated": False}
    if issue["status"] == "In Progress":
        return {"label": "In Progress", "level": "progress", "days": days, "escalated": False}
    return {"label": "Pending", "level": "pending", "days": days, "escalated": False}


def display_category(issue):
    if issue["category"] == "Others" and issue["custom_category"]:
        return issue["custom_category"]
    return issue["category"]


def haversine_km(lat1, lon1, lat2, lon2):
    earth_radius = 6371
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    return 2 * earth_radius * asin(sqrt(a))


def tokenize(text):
    return {word for word in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(word) > 2}


def similarity_score(left, right):
    left_words = tokenize(left)
    right_words = tokenize(right)
    if not left_words or not right_words:
        return 0
    return len(left_words & right_words) / len(left_words | right_words)


def priority_for(issue, repost_count=None, verification_count=None):
    reposts = int(repost_count if repost_count is not None else issue["repost_count"] or 0)
    verifications = int(verification_count if verification_count is not None else issue["verification_count"] or 0)
    age = days_since(issue["created_at"])
    score = reposts * 2 + verifications * 2 + age
    if issue["status"] != "Resolved" and issue["escalation_status"] == "Escalated":
        score += 4
    if score >= SUPPORT_PRIORITY_CRITICAL:
        return "Critical"
    if score >= SUPPORT_PRIORITY_HIGH:
        return "High"
    if score >= SUPPORT_PRIORITY_MEDIUM:
        return "Medium"
    return "Low"


def update_escalations():
    db = get_db()
    rows = db.execute("SELECT * FROM issues").fetchall()
    for row in rows:
        status = escalation_for(row)
        repost_count = db.execute(
            "SELECT COUNT(*) FROM complaint_supports WHERE issue_id = ?", (row["id"],)
        ).fetchone()[0]
        verification_count = db.execute(
            "SELECT COUNT(*) FROM verifications WHERE issue_id = ?", (row["id"],)
        ).fetchone()[0]
        priority = priority_for(row, repost_count, verification_count)
        if row["status"] != "Resolved":
            db.execute(
                """
                UPDATE issues
                SET escalation_status = ?, repost_count = ?, verification_count = ?, complaint_priority = ?
                WHERE id = ?
                """,
                (status, repost_count, verification_count, priority, row["id"]),
            )
        else:
            db.execute(
                """
                UPDATE issues
                SET escalation_status = 'Resolved', repost_count = ?, verification_count = ?, complaint_priority = ?
                WHERE id = ?
                """,
                (repost_count, verification_count, priority, row["id"]),
            )
    db.commit()


def fetch_issues(where="", params=()):
    update_escalations()
    query = f"""
        SELECT issues.*, users.email,
               COUNT(DISTINCT complaint_supports.id) AS support_count,
               COUNT(DISTINCT verifications.id) AS live_verification_count
        FROM issues
        JOIN users ON users.id = issues.user_id
        LEFT JOIN complaint_supports ON complaint_supports.issue_id = issues.id
        LEFT JOIN verifications ON verifications.issue_id = issues.id
        {where}
        GROUP BY issues.id
        ORDER BY
            CASE issues.escalation_status WHEN 'Escalated' THEN 0 WHEN 'Warning' THEN 1 ELSE 2 END,
            live_verification_count DESC,
            issues.created_at DESC
    """
    rows = get_db().execute(query, params).fetchall()
    issues = []
    for row in rows:
        item = dict(row)
        item["verification_count"] = item["live_verification_count"]
        item["repost_count"] = item["support_count"]
        item["complaint_priority"] = priority_for(row, item["repost_count"], item["verification_count"])
        item["display_category"] = display_category(row)
        item["alert"] = alert_for(row)
        item["verified"] = item["verification_count"] >= VERIFIED_THRESHOLD
        issues.append(item)
    return issues


def issue_marker_payload(issue, origin_lat=None, origin_lng=None):
    distance = None
    if origin_lat is not None and origin_lng is not None and issue["latitude"] is not None and issue["longitude"] is not None:
        distance = round(haversine_km(origin_lat, origin_lng, float(issue["latitude"]), float(issue["longitude"])), 2)
    user = current_user()
    return {
        "id": issue["id"],
        "title": issue["display_category"],
        "category": issue["display_category"],
        "status": issue["status"],
        "priority": issue["complaint_priority"],
        "alert": issue["alert"]["label"],
        "lat": issue["latitude"],
        "lng": issue["longitude"],
        "distance": distance,
        "reported": issue["created_at"][:10],
        "verification_count": issue["verification_count"],
        "repost_count": issue["repost_count"],
        "image": url_for("static", filename="uploads/" + issue["before_image"]) if issue["before_image"] else None,
        "url": url_for("issue_detail", issue_id=issue["id"]),
        "support_url": url_for("support_issue", issue_id=issue["id"]) if user and user["role"] == "citizen" else None,
    }


def find_nearby_issues(lat, lng, category=None, description="", radius_km=1):
    rows = fetch_issues("WHERE issues.latitude IS NOT NULL AND issues.longitude IS NOT NULL")
    nearby = []
    for issue in rows:
        distance = haversine_km(lat, lng, float(issue["latitude"]), float(issue["longitude"]))
        if distance <= radius_km:
            category_match = not category or issue["category"] == category
            text_score = similarity_score(description, issue["description"])
            is_similar = category_match and (text_score >= 0.18 or distance <= 0.25)
            payload = issue_marker_payload(issue, lat, lng)
            payload["similarity"] = round(text_score, 2)
            payload["is_similar"] = is_similar
            nearby.append(payload)
    return sorted(nearby, key=lambda item: (not item["is_similar"], item["distance"] or 99))


@app.route("/")
def home():
    stats = {
        "total": get_db().execute("SELECT COUNT(*) FROM issues").fetchone()[0],
        "resolved": get_db().execute("SELECT COUNT(*) FROM issues WHERE status = 'Resolved'").fetchone()[0],
        "supported": get_db().execute("SELECT COUNT(*) FROM verifications").fetchone()[0],
    }
    return render_template("home.html", stats=stats)


@app.route("/auth", methods=("GET", "POST"))
def auth():
    if request.method == "POST":
        action = request.form.get("action")
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "citizen")

        if role not in {"citizen", "admin"} or not email or not password:
            flash("Email, password, and role are required.", "error")
            return redirect(url_for("auth"))

        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email = ? AND role = ?", (email, role)).fetchone()

        if action == "register":
            if user:
                flash("An account already exists for this email and role.", "error")
                return redirect(url_for("auth"))
            db.execute(
                "INSERT INTO users (email, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
                (email, generate_password_hash(password), role, datetime.utcnow().isoformat()),
            )
            db.commit()
            flash("Registration successful. Please log in.", "success")
            return redirect(url_for("auth"))

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            flash("Welcome back.", "success")
            return redirect(url_for("admin_dashboard" if role == "admin" else "citizen_dashboard"))

        flash("Invalid credentials for the selected role.", "error")
    return render_template("auth.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("home"))


@app.route("/citizen")
@login_required("citizen")
def citizen_dashboard():
    user = current_user()
    my_issues = fetch_issues("WHERE issues.user_id = ?", (user["id"],))
    active = fetch_issues("WHERE issues.status != 'Resolved'")
    return render_template("citizen_dashboard.html", my_issues=my_issues, active=active[:6])


@app.route("/report", methods=("GET", "POST"))
@login_required("citizen")
def report_issue():
    if request.method == "POST":
        description = request.form.get("description", "").strip()
        location = request.form.get("location", "").strip()
        category = request.form.get("category", "Roads")
        custom_category = request.form.get("custom_category", "").strip() if category == "Others" else None
        latitude = request.form.get("latitude") or None
        longitude = request.form.get("longitude") or None
        duplicate_reference = request.form.get("duplicate_reference") or None
        continue_new_report = request.form.get("continue_new_report") == "1"

        if category not in CATEGORIES:
            flash("Please select a valid category.", "error")
            return redirect(url_for("report_issue"))
        if category == "Others" and not custom_category:
            flash("Please describe the custom category.", "error")
            return redirect(url_for("report_issue"))
        if not description or not location:
            flash("Description and location are required.", "error")
            return redirect(url_for("report_issue"))
        nearby_duplicate_flag = 0
        if latitude and longitude:
            try:
                similar = [
                    issue
                    for issue in find_nearby_issues(float(latitude), float(longitude), category, description)
                    if issue["is_similar"]
                ]
            except ValueError:
                similar = []
            if similar:
                nearby_duplicate_flag = 1
                if not continue_new_report and not duplicate_reference:
                    flash("A similar issue already exists nearby. Support it or choose Continue New Report.", "error")
                    return redirect(url_for("report_issue"))

        before_image = save_upload(request.files.get("before_image"), "before")
        now = datetime.utcnow().isoformat()
        get_db().execute(
            """
            INSERT INTO issues
                (user_id, description, location, category, custom_category, latitude, longitude,
                 before_image, status, escalation_status, duplicate_reference, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Pending', 'Normal', ?, ?, ?)
            """,
            (
                current_user()["id"],
                description,
                location,
                category,
                custom_category,
                latitude,
                longitude,
                before_image,
                duplicate_reference,
                now,
                now,
            ),
        )
        issue_id = get_db().execute("SELECT last_insert_rowid()").fetchone()[0]
        get_db().execute(
            "UPDATE issues SET nearby_duplicate_flag = ? WHERE id = ?",
            (nearby_duplicate_flag, issue_id),
        )
        get_db().commit()
        flash("Issue reported successfully.", "success")
        return redirect(url_for("issues"))
    return render_template("report.html")


@app.route("/issues")
def issues():
    status_filter = request.args.get("filter", "All")
    if status_filter in {"Pending", "In Progress", "Resolved"}:
        issue_rows = fetch_issues("WHERE issues.status = ?", (status_filter,))
    else:
        issue_rows = fetch_issues()
        if status_filter == "Escalated":
            issue_rows = [issue for issue in issue_rows if issue["alert"]["escalated"]]
    top_verified = sorted(issue_rows, key=lambda item: item["verification_count"], reverse=True)[:4]
    return render_template(
        "issues.html",
        issues=issue_rows,
        selected_filter=status_filter,
        top_verified=[issue for issue in top_verified if issue["verification_count"] > 0],
    )


@app.route("/issues/<int:issue_id>")
def issue_detail(issue_id):
    issue = fetch_issues("WHERE issues.id = ?", (issue_id,))
    if not issue:
        flash("Issue not found.", "error")
        return redirect(url_for("issues"))
    updates = get_db().execute(
        """
        SELECT updates.*, users.email, users.role
        FROM updates
        JOIN users ON users.id = updates.user_id
        WHERE issue_id = ?
        ORDER BY updates.created_at ASC
        """,
        (issue_id,),
    ).fetchall()
    resolution_images = get_db().execute(
        "SELECT * FROM resolution_images WHERE issue_id = ? ORDER BY uploaded_at DESC",
        (issue_id,),
    ).fetchall()
    supported = False
    verified = False
    user = current_user()
    if user:
        supported = (
            get_db()
            .execute(
                "SELECT 1 FROM complaint_supports WHERE issue_id = ? AND supporter_user_id = ?",
                (issue_id, user["id"]),
            )
            .fetchone()
            is not None
        )
        verified = (
            get_db()
            .execute("SELECT 1 FROM verifications WHERE issue_id = ? AND user_id = ?", (issue_id, user["id"]))
            .fetchone()
            is not None
        )
    return render_template(
        "issue_detail.html",
        issue=issue[0],
        updates=updates,
        supported=supported,
        verified=verified,
        resolution_images=resolution_images,
    )


@app.route("/issues/<int:issue_id>/support", methods=("POST",))
@login_required("citizen")
def support_issue(issue_id):
    now = datetime.utcnow().isoformat()
    try:
        get_db().execute(
            "INSERT INTO complaint_supports (issue_id, supporter_user_id, created_at) VALUES (?, ?, ?)",
            (issue_id, current_user()["id"], now),
        )
        get_db().execute(
            "INSERT OR IGNORE INTO supports (issue_id, user_id, created_at) VALUES (?, ?, ?)",
            (issue_id, current_user()["id"], now),
        )
        get_db().execute("UPDATE issues SET repost_count = repost_count + 1, updated_at = ? WHERE id = ?", (now, issue_id))
        get_db().commit()
        flash("Your repost/support has been added.", "success")
    except sqlite3.IntegrityError:
        flash("You already reposted this issue.", "error")
    return redirect(request.referrer or url_for("issue_detail", issue_id=issue_id))


@app.route("/issues/<int:issue_id>/verify", methods=("POST",))
@login_required("citizen")
def verify_issue(issue_id):
    issue = get_db().execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
    if not issue:
        flash("Issue not found.", "error")
        return redirect(url_for("issues"))
    if issue["user_id"] == current_user()["id"]:
        flash("Other citizens can verify your complaint.", "error")
        return redirect(request.referrer or url_for("issue_detail", issue_id=issue_id))
    now = datetime.utcnow().isoformat()
    try:
        get_db().execute(
            "INSERT INTO verifications (issue_id, user_id, created_at) VALUES (?, ?, ?)",
            (issue_id, current_user()["id"], now),
        )
        get_db().execute(
            "UPDATE issues SET verification_count = verification_count + 1, updated_at = ? WHERE id = ?",
            (now, issue_id),
        )
        get_db().commit()
        flash("Issue verified. Thanks for strengthening this report.", "success")
    except sqlite3.IntegrityError:
        flash("You already verified this issue.", "error")
    return redirect(request.referrer or url_for("issue_detail", issue_id=issue_id))


@app.route("/api/nearby-issues")
@login_required("citizen")
def nearby_issues():
    try:
        lat = float(request.args.get("lat", ""))
        lng = float(request.args.get("lng", ""))
    except ValueError:
        return jsonify({"issues": []})

    category = request.args.get("category")
    description = request.args.get("description", "")
    nearby = find_nearby_issues(lat, lng, category, description)
    return jsonify({"issues": nearby, "similar": [issue for issue in nearby if issue["is_similar"]]})


@app.route("/api/community-issues")
def community_issues_api():
    category = request.args.get("category", "All")
    status = request.args.get("status", "All")
    priority = request.args.get("priority", "All")
    q = request.args.get("q", "").strip().lower()
    max_distance = request.args.get("distance", "")
    try:
        origin_lat = float(request.args.get("lat", "")) if request.args.get("lat") else None
        origin_lng = float(request.args.get("lng", "")) if request.args.get("lng") else None
    except ValueError:
        origin_lat = None
        origin_lng = None

    rows = fetch_issues("WHERE issues.latitude IS NOT NULL AND issues.longitude IS NOT NULL")
    filtered = []
    for issue in rows:
        if category != "All" and issue["category"] != category:
            continue
        if status != "All" and issue["status"] != status:
            continue
        if priority != "All" and issue["complaint_priority"] != priority:
            continue
        if q and q not in (issue["location"] or "").lower() and q not in issue["display_category"].lower():
            continue
        payload = issue_marker_payload(issue, origin_lat, origin_lng)
        if max_distance and payload["distance"] is not None:
            try:
                if payload["distance"] > float(max_distance):
                    continue
            except ValueError:
                pass
        filtered.append(payload)
    return jsonify({"issues": filtered})


@app.route("/community-map")
def community_map():
    all_issues = fetch_issues("WHERE issues.latitude IS NOT NULL AND issues.longitude IS NOT NULL")
    trending = sorted(all_issues, key=lambda item: (item["repost_count"], item["verification_count"]), reverse=True)[:6]
    hotspots = {}
    for issue in all_issues:
        area = issue["location"].split(",")[0].strip()[:34] or "Unknown"
        hotspots[area] = hotspots.get(area, 0) + 1
    return render_template(
        "community_map.html",
        issues=[issue_marker_payload(issue) for issue in all_issues],
        trending=trending,
        hotspots=sorted(hotspots.items(), key=lambda item: item[1], reverse=True)[:8],
    )


@app.route("/admin")
@login_required("admin")
def admin_dashboard():
    all_issues = fetch_issues()
    stats = {
        "total": len(all_issues),
        "pending": sum(1 for issue in all_issues if issue["status"] == "Pending"),
        "resolved": sum(1 for issue in all_issues if issue["status"] == "Resolved"),
        "escalated": sum(1 for issue in all_issues if issue["alert"]["escalated"]),
    }
    most_supported = sorted(all_issues, key=lambda item: item["verification_count"], reverse=True)[:5]
    most_reposted = sorted(all_issues, key=lambda item: item["repost_count"], reverse=True)[:5]
    repeated = [issue for issue in all_issues if issue["nearby_duplicate_flag"]]
    escalated = [issue for issue in all_issues if issue["alert"]["escalated"]]
    area_stats = {}
    for issue in all_issues:
        area = issue["location"].split(",")[0].strip()[:34] or "Unknown"
        area_stats[area] = area_stats.get(area, 0) + 1
    map_issues = []
    for issue in all_issues:
        if issue["latitude"] is None or issue["longitude"] is None:
            continue
        payload = issue_marker_payload(issue)
        payload["url"] = url_for("admin_issue", issue_id=issue["id"])
        payload["support_url"] = None
        map_issues.append(payload)
    return render_template(
        "admin_dashboard.html",
        issues=all_issues,
        stats=stats,
        most_supported=most_supported,
        most_reposted=most_reposted,
        repeated=repeated,
        escalated=escalated,
        area_stats=sorted(area_stats.items(), key=lambda item: item[1], reverse=True)[:8],
        map_issues=map_issues,
    )


@app.route("/admin/issues/<int:issue_id>", methods=("GET", "POST"))
@login_required("admin")
def admin_issue(issue_id):
    if request.method == "POST":
        status = request.form.get("status")
        if status not in {"Pending", "In Progress", "Resolved"}:
            flash("Invalid status.", "error")
            return redirect(url_for("admin_issue", issue_id=issue_id))
        after_files = request.files.getlist("after_images")
        now = datetime.utcnow().isoformat()
        saved_images = []
        for file_storage in after_files:
            saved = save_upload(file_storage, "after")
            if saved:
                saved_images.append(saved)
                get_db().execute(
                    "INSERT INTO resolution_images (issue_id, filename, uploaded_at) VALUES (?, ?, ?)",
                    (issue_id, saved, now),
                )
        after_image = saved_images[0] if saved_images else None
        resolution_date = now if status == "Resolved" else None
        if after_image:
            get_db().execute(
                "UPDATE issues SET status = ?, after_image = ?, resolution_date = COALESCE(?, resolution_date), updated_at = ? WHERE id = ?",
                (status, after_image, resolution_date, now, issue_id),
            )
        else:
            get_db().execute(
                "UPDATE issues SET status = ?, resolution_date = COALESCE(?, resolution_date), updated_at = ? WHERE id = ?",
                (status, resolution_date, now, issue_id),
            )
        get_db().execute(
            "INSERT INTO updates (issue_id, user_id, message, created_at) VALUES (?, ?, ?, ?)",
            (issue_id, current_user()["id"], f"Status updated to {status}.", now),
        )
        get_db().commit()
        flash("Issue updated.", "success")
        return redirect(url_for("admin_issue", issue_id=issue_id))
    return issue_detail(issue_id)


if __name__ == "__main__":
    app.run(debug=True)
