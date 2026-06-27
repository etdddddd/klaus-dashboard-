import json
import os
import secrets
import time
import hmac
import hashlib
import base64
from functools import wraps
from typing import Any

import certifi
import pymongo
import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, url_for

load_dotenv()

app = Flask(__name__)
SECRET = os.getenv("SECRET_KEY", "klaus-dashboard-secret-2026")

CLIENT_ID = os.getenv("CLIENT_ID", "")
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
MONGODB_URL = os.getenv("MONGODB_URL", "")
API = "https://discord.com/api/v10"


def sign_data(data: str) -> str:
    sig = hmac.new(SECRET.encode(), data.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(data.encode()).decode() + "." + sig


def unsign_data(signed: str) -> str | None:
    try:
        parts = signed.split(".", 1)
        data_b64 = parts[0]
        sig = parts[1]
        data = base64.urlsafe_b64decode(data_b64.encode()).decode()
        expected = hmac.new(SECRET.encode(), data.encode(), hashlib.sha256).hexdigest()
        if hmac.compare_digest(sig, expected):
            return data
    except Exception:
        pass
    return None


def set_user_cookie(resp: Any, user: dict) -> Any:
    payload = json.dumps(user)
    signed = sign_data(payload)
    max_age = 60 * 60 * 24 * 7
    resp.set_cookie("user", signed, max_age=max_age, httponly=True, samesite="Lax", secure=False)
    return resp


def get_user() -> dict | None:
    signed = request.cookies.get("user")
    if not signed:
        return None
    data = unsign_data(signed)
    if not data:
        return None
    try:
        user = json.loads(data)
        if time.time() - user.get("_ts", 0) > 60 * 60 * 24 * 7:
            return None
        return user
    except Exception:
        return None


def login_required(f: Any) -> Any:
    @wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Any:
        if not get_user():
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated


def get_redirect_uri() -> str:
    env_uri = os.getenv("REDIRECT_URI", "")
    if env_uri:
        return env_uri
    url = request.url_root.rstrip("/")
    return url + "/callback"


def get_db() -> Any:
    client = pymongo.MongoClient(MONGODB_URL, tls=True, tlsCAFile=certifi.where())
    return client["economia"]


@app.route("/")
def index() -> str:
    user = get_user()
    return render_template("index.html", user=user)


@app.route("/login")
def login() -> redirect:
    state = secrets.token_urlsafe(32)
    redirect_uri = get_redirect_uri()
    resp = redirect(
        f"https://discord.com/api/oauth2/authorize"
        f"?client_id={CLIENT_ID}&redirect_uri={redirect_uri}"
        f"&response_type=code&scope=identify+guilds&state={state}"
    )
    resp.set_cookie("oauth_state", state, max_age=300)
    return resp


@app.route("/callback")
def callback() -> redirect:
    code = request.args.get("code")
    state = request.args.get("state")
    saved_state = request.cookies.get("oauth_state")

    if not code:
        return redirect(url_for("index"))

    if state != saved_state:
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
        timeout=10,
    )
    if r.status_code != 200:
        return redirect(url_for("index"))

    token = r.json()["access_token"]
    user_resp = requests.get(f"{API}/users/@me", headers={"Authorization": f"Bearer {token}"}, timeout=10)
    guilds_resp = requests.get(f"{API}/users/@me/guilds", headers={"Authorization": f"Bearer {token}"}, timeout=10)

    if user_resp.status_code != 200:
        return redirect(url_for("index"))

    user = user_resp.json()
    user["guilds"] = guilds_resp.json() if guilds_resp.status_code == 200 else []
    user["_ts"] = int(time.time())

    resp = redirect(url_for("dashboard"))
    set_user_cookie(resp, user)
    resp.delete_cookie("oauth_state")
    return resp


@app.route("/logout")
def logout() -> redirect:
    resp = redirect(url_for("index"))
    resp.delete_cookie("user")
    return resp


@app.route("/dashboard")
@login_required
def dashboard() -> str:
    user = get_user()
    assert user is not None

    bot_guilds = set()
    if BOT_TOKEN:
        try:
            r = requests.get(f"{API}/users/@me/guilds", headers={"Authorization": f"Bot {BOT_TOKEN}"}, timeout=10)
            if r.status_code == 200:
                bot_guilds = {g["id"] for g in r.json()}
        except Exception:
            pass

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
    user = get_user()
    assert user is not None
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
    try:
        r = requests.get(f"{API}/guilds/{guild_id}/roles", headers={"Authorization": f"Bot {BOT_TOKEN}"}, timeout=10)
        if r.status_code != 200:
            return jsonify([])
        roles = [x for x in r.json() if not x.get("managed") and x["name"] != "@everyone"]
        roles.sort(key=lambda x: x.get("position", 0), reverse=True)
        return jsonify([{"id": r["id"], "name": r["name"]} for r in roles])
    except Exception:
        return jsonify([])


@app.route("/api/<guild_id>/channels")
@login_required
def get_channels(guild_id: str) -> Any:
    if not BOT_TOKEN:
        return jsonify([])
    try:
        r = requests.get(f"{API}/guilds/{guild_id}/channels", headers={"Authorization": f"Bot {BOT_TOKEN}"}, timeout=10)
        if r.status_code != 200:
            return jsonify([])
        channels = [c for c in r.json() if c.get("type") == 0]
        channels.sort(key=lambda x: x.get("position", 0))
        return jsonify([{"id": c["id"], "name": c["name"]} for c in channels])
    except Exception:
        return jsonify([])


if __name__ == "__main__":
    app.run(debug=True, port=5000)
