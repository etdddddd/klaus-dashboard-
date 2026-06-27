import os
import secrets
from functools import wraps
from typing import Any

import certifi
import pymongo
import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "klaus-dashboard-secret-key-2026")
app.config["SESSION_COOKIE_NAME"] = "klaus_session"
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = True

CLIENT_ID = os.getenv("CLIENT_ID", "")
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
MONGODB_URL = os.getenv("MONGODB_URL", "")
API = "https://discord.com/api/v10"


def get_redirect_uri() -> str:
    env_uri = os.getenv("REDIRECT_URI", "")
    if env_uri:
        return env_uri
    url = request.url_root.rstrip("/")
    return url + "/callback"


def get_db() -> Any:
    client = pymongo.MongoClient(MONGODB_URL, tls=True, tlsCAFile=certifi.where())
    return client["economia"]


def login_required(f: Any) -> Any:
    @wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Any:
        if "user" not in session:
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated


@app.route("/")
def index() -> str:
    return render_template("index.html", user=session.get("user"))


@app.route("/login")
def login() -> redirect:
    state = secrets.token_urlsafe(32)
    session["state"] = state
    redirect_uri = get_redirect_uri()
    return redirect(
        f"https://discord.com/api/oauth2/authorize"
        f"?client_id={CLIENT_ID}&redirect_uri={redirect_uri}"
        f"&response_type=code&scope=identify+guilds&state={state}"
    )


@app.route("/callback")
def callback() -> redirect:
    code = request.args.get("code")
    state = request.args.get("state")
    if not code or state != session.get("state"):
        return redirect(url_for("index"))

    r = requests.post(
        "https://discord.com/api/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": get_redirect_uri(),
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        auth=(CLIENT_ID, CLIENT_SECRET),
    )
    if r.status_code != 200:
        return redirect(url_for("index"))

    token = r.json()["access_token"]
    user = requests.get(f"{API}/users/@me", headers={"Authorization": f"Bearer {token}"}).json()
    guilds = requests.get(f"{API}/users/@me/guilds", headers={"Authorization": f"Bearer {token}"}).json()

    user["guilds"] = guilds
    session["user"] = user
    return redirect(url_for("dashboard"))


@app.route("/logout")
def logout() -> redirect:
    session.clear()
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def dashboard() -> str:
    user = session["user"]

    bot_guilds = set()
    if BOT_TOKEN:
        r = requests.get(f"{API}/users/@me/guilds", headers={"Authorization": f"Bot {BOT_TOKEN}"})
        if r.status_code == 200:
            bot_guilds = {g["id"] for g in r.json()}

    guilds = []
    for g in user.get("guilds", []):
        perm = int(g.get("permissions", 0))
        can_manage = (perm & 0x20) != 0
        in_bot = g["id"] in bot_guilds
        if can_manage:
            guilds.append({**g, "in_bot": in_bot})

    return render_template("dashboard.html", user=user, guilds=guilds)


@app.route("/server/<guild_id>")
@login_required
def server(guild_id: str) -> str:
    user = session["user"]
    guild = next((g for g in user.get("guilds", []) if g["id"] == guild_id), None)
    if not guild:
        return redirect(url_for("dashboard"))

    config = {
        "welcome_enabled": False, "welcome_channel": "", "welcome_message": "Bem-vindo(a) ao servidor, {user}! \U0001f44b",
        "welcome_color": "#a78bfa", "welcome_title": "\U0001f31f Bem-vindo!",
        "autorole_enabled": False, "autorole_role": "",
        "farewell_enabled": False, "farewell_channel": "", "farewell_message": "Tchau, {user}! \U0001f44b",
        "farewell_color": "#f87171", "farewell_title": "\U0001f44b Até logo!",
        "logs_enabled": False, "logs_channel": "",
        "logging_messages": False, "logging_members": False, "logging_mod": False,
    }
    try:
        db = get_db()
        doc = db["guilds"].find_one({"guild_id": int(guild_id)})
        if doc:
            for k in config:
                if k in doc:
                    config[k] = doc[k]
    except Exception:
        pass

    return render_template("server.html", user=user, guild=guild, config=config)


@app.route("/api/<guild_id>", methods=["POST"])
@login_required
def save_config(guild_id: str) -> Any:
    data = request.get_json()
    if not data:
        return jsonify({"error": "no data"}), 400

    try:
        db = get_db()
        db["guilds"].update_one(
            {"guild_id": int(guild_id)},
            {"$set": data},
            upsert=True,
        )
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/<guild_id>/roles")
@login_required
def get_roles(guild_id: str) -> Any:
    if not BOT_TOKEN:
        return jsonify([])
    r = requests.get(f"{API}/guilds/{guild_id}/roles", headers={"Authorization": f"Bot {BOT_TOKEN}"})
    if r.status_code != 200:
        return jsonify([])
    roles = [x for x in r.json() if not x.get("managed") and x["name"] != "@everyone"]
    roles.sort(key=lambda x: x.get("position", 0), reverse=True)
    return jsonify([{"id": r["id"], "name": r["name"]} for r in roles])


@app.route("/api/<guild_id>/channels")
@login_required
def get_channels(guild_id: str) -> Any:
    if not BOT_TOKEN:
        return jsonify([])
    r = requests.get(f"{API}/guilds/{guild_id}/channels", headers={"Authorization": f"Bot {BOT_TOKEN}"})
    if r.status_code != 200:
        return jsonify([])
    channels = [c for c in r.json() if c.get("type") == 0]
    channels.sort(key=lambda x: x.get("position", 0))
    return jsonify([{"id": c["id"], "name": c["name"]} for c in channels])


if __name__ == "__main__":
    app.run(debug=True, port=5000)
