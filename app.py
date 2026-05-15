import hashlib
from datetime import datetime
from functools import wraps

import mysql.connector
from mysql.connector import Error as MySQLError
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, jsonify
)

#  CONFIG

app = Flask(__name__,template_folder="temp")  

app.secret_key = "lf_secret_key_2025"   


#  DB

def get_connection():
    return mysql.connector.connect(
        host="localhost",
        port=3306,
        user="root",
        password="",
        database="lost_and_found"
    )



def db_query(sql, params=(), one=False):
    con = get_connection()
    try:
        cur = con.cursor(dictionary=True)
        cur.execute(sql, params)
        return cur.fetchone() if one else cur.fetchall()
    finally:
        con.close()


def db_execute(sql, params=()):
    con = get_connection()
    try:
        cur = con.cursor()
        cur.execute(sql, params)
        con.commit()
        return cur.lastrowid
    finally:
        con.close()


def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")



# AUTH DECORATORS
def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapped


def admin_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Admin access required.", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return wrapped



# AUTH ROUTES
@app.route("/", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = db_query(
            "SELECT id, full_name, role FROM users WHERE username=%s AND password=%s",
            (username, hash_pw(password)), one=True
        )
        if user:
            session["user_id"]   = user["id"]
            session["user_name"] = user["full_name"]
            session["role"]      = user["role"]
            session["username"]  = username
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "danger")

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        username  = request.form.get("username",  "").strip()
        password  = request.form.get("password",  "")
        role      = "student"

        if not all([full_name, username, password]):
            flash("All fields are required.", "danger")
            return render_template("register.html")
        try:
            db_execute(
                "INSERT INTO users (username, password, full_name, role, created_at) VALUES (%s,%s,%s,%s,%s)",
                (username, hash_pw(password), full_name, role, now())
            )
            flash("Account created! You can now login.", "success")
            return redirect(url_for("login"))
        except MySQLError as e:
            if "Duplicate" in str(e):
                flash("Username already exists.", "danger")
            else:
                flash(f"Database error: {e}", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))



# DASHBOARD
@app.route("/dashboard")
@login_required
def dashboard():
    uid  = session["user_id"]
    role = session["role"]

    if role == "admin":
        lost_items  = db_query(
            "SELECT li.*, u.full_name AS reporter FROM lost_items li "
            "JOIN users u ON li.reporter_id=u.id ORDER BY li.id DESC"
        )
        found_items = db_query(
            "SELECT fi.*, u.full_name AS reporter FROM found_items fi "
            "JOIN users u ON fi.reporter_id=u.id ORDER BY fi.id DESC"
        )
        users = db_query("SELECT * FROM users ORDER BY id")
        stats = {
            "lost":      len(lost_items),
            "found":     len(found_items),
            "pending":   sum(1 for r in lost_items  if r["status"] == "pending"),
            "unclaimed": sum(1 for r in found_items if r["status"] == "unclaimed"),
            "users":     len(users),
        }
        return render_template("admin.html",
                               lost_items=lost_items, found_items=found_items,
                               users=users, stats=stats)
    else:
        my_lost     = db_query(
            "SELECT * FROM lost_items WHERE reporter_id=%s ORDER BY id DESC", (uid,)
        )
        all_found   = db_query(
            "SELECT fi.*, u.full_name AS reporter FROM found_items fi "
            "JOIN users u ON fi.reporter_id=u.id ORDER BY fi.id DESC"
        )
        all_lost    = db_query(
            "SELECT li.*, u.full_name AS reporter FROM lost_items li "
            "JOIN users u ON li.reporter_id=u.id ORDER BY li.id DESC"
        )
        stats = {
            "my_lost":   len(my_lost),
            "pending":   sum(1 for r in my_lost   if r["status"] == "pending"),
            "unclaimed": sum(1 for r in all_found if r["status"] == "unclaimed"),
        }
        return render_template("student.html",
                               my_lost=my_lost, all_found=all_found,
                               all_lost=all_lost, stats=stats)


# LOST ITEMS
@app.route("/report/lost", methods=["GET", "POST"])
@login_required
def report_lost():
    if request.method == "POST":
        item_name   = request.form.get("item_name", "").strip()
        description = request.form.get("description", "").strip()
        date_lost   = request.form.get("date_lost", "")
        location    = request.form.get("location", "").strip()

        if not all([item_name, date_lost, location]):
            flash("Item name, date, and location are required.", "danger")
            return render_template("report_lost.html")

        db_execute(
            "INSERT INTO lost_items (reporter_id, item_name, description, date_lost, location, status, created_at) "
            "VALUES (%s,%s,%s,%s,%s,'pending',%s)",
            (session["user_id"], item_name, description, date_lost, location, now())
        )
        flash("Lost item reported successfully!", "success")
        return redirect(url_for("dashboard"))

    return render_template("report_lost.html")


@app.route("/lost/update/<int:item_id>", methods=["POST"])
@login_required
@admin_required
def update_lost(item_id):
    status = request.form.get("status")
    db_execute("UPDATE lost_items SET status=%s WHERE id=%s", (status, item_id))
    flash(f"Item status updated to '{status}'.", "success")
    return redirect(url_for("dashboard"))


@app.route("/lost/delete/<int:item_id>", methods=["POST"])
@login_required
@admin_required
def delete_lost(item_id):
    db_execute("DELETE FROM lost_items WHERE id=%s", (item_id,))
    flash("Lost item record deleted.", "success")
    return redirect(url_for("dashboard"))


# FOUND ITEMS
@app.route("/report/found", methods=["GET", "POST"])
@login_required
def report_found():
    if request.method == "POST":
        item_name   = request.form.get("item_name", "").strip()
        description = request.form.get("description", "").strip()
        date_found  = request.form.get("date_found", "")
        location    = request.form.get("location", "").strip()

        if not all([item_name, date_found, location]):
            flash("Item name, date, and location are required.", "danger")
            return render_template("report_found.html")

        db_execute(
            "INSERT INTO found_items (reporter_id, item_name, description, date_found, location, status, created_at) "
            "VALUES (%s,%s,%s,%s,%s,'unclaimed',%s)",
            (session["user_id"], item_name, description, date_found, location, now())
        )
        flash("Found item reported successfully!", "success")
        return redirect(url_for("dashboard"))

    return render_template("report_found.html")


@app.route("/found/update/<int:item_id>", methods=["POST"])
@login_required
@admin_required
def update_found(item_id):
    status = request.form.get("status")
    db_execute("UPDATE found_items SET status=%s WHERE id=%s", (status, item_id))
    flash(f"Item status updated to '{status}'.", "success")
    return redirect(url_for("dashboard"))


@app.route("/found/delete/<int:item_id>", methods=["POST"])
@login_required
@admin_required
def delete_found(item_id):
    db_execute("DELETE FROM found_items WHERE id=%s", (item_id,))
    flash("Found item record deleted.", "success")
    return redirect(url_for("dashboard"))


# ADMIN
@app.route("/users/delete/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def delete_user(user_id):
    if user_id == session["user_id"]:
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for("dashboard"))
    db_execute("DELETE FROM users WHERE id=%s", (user_id,))
    flash("User deleted.", "success")
    return redirect(url_for("dashboard"))

#run

if __name__ == "__main__":
    app.run(debug=True, port=5000)
