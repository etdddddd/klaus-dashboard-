import os
import secrets
from functools import wraps
from typing import Any

import certifi
import pymongo
import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, url_for

load_dotenv()

app = Flask(__name__)

CLIENT_ID = os.getenv("CLIENT_ID", "")
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
MONGODB_URL = os.getenv("MONGODB_URL", "")
API = "https://discord.com/api/v10"


def get_redirect_uri() -> str:
    env = os.getenv("REDIRECT_URI", "")
    if env:
        return env
    return request.url_root.rstrip("/") + "/callback"


def get_db() -> Any:
    c = pymongo.MongoClient(MONGODB_URL, tls=True, tlsCAFile=certifi.where())
    return c["economia"]


def fetch_user(token: str) -> dict | None:
    try:
        r = requests.get(f"{API}/users/@me", headers={"Authorization": f"Bearer {token}"}, timeout=10)
        if r.status_code != 200:
            return None
        user = r.json()
        g = requests.get(f"{API}/users/@me/guilds", headers={"Authorization": f"Bearer {token}"}, timeout=10)
        user["guilds"] = g.json() if g.status_code == 200 else []
        return user
    except Exception:
        return None


def login_required(f: Any) -> Any:
    @wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Any:
        token = request.cookies.get("token")
        if not token:
            return redirect(url_for("index"))
        user = fetch_user(token)
        if not user:
            resp = redirect(url_for("index"))
            resp.delete_cookie("token")
            return resp
        return f(user, *args, **kwargs)
    return decorated


@app.route("/")
def index() -> str:
    token = request.cookies.get("token")
    user = fetch_user(token) if token else None
    return render_template("index.html", user=user)


@app.route("/login")
def login() -> redirect:
    return redirect(
        f"https://discord.com/api/oauth2/authorize"
        f"?client_id={CLIENT_ID}"
        f"&redirect_uri={get_redirect_uri()}"
        f"&response_type=code"
        f"&scope=identify+guilds"
    )


@app.route("/callback")
def callback() -> redirect:
    code = request.args.get("code")
    if not code:
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
    resp = redirect(url_for("dashboard"))
    resp.set_cookie("token", token, max_age=60 * 60 * 24 * 7, httponly=True, samesite="Lax")
    return resp


@app.route("/logout")
def logout() -> redirect:
    resp = redirect(url_for("index"))
    resp.delete_cookie("token")
    return resp


@app.route("/dashboard")
@login_required
def dashboard(user: dict) -> str:
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
        if perm & 0x20:
            guilds.append({**g, "in_bot": g["id"] in bot_guilds})

    return render_template("dashboard.html", user=user, guilds=guilds)


@app.route("/server/<guild_id>")
@login_required
def server(user: dict, guild_id: str) -> str:
    guild = next((g for g in user.get("guilds", []) if g["id"] == guild_id), None)
    if not guild or not (int(guild.get("permissions", 0)) & 0x20):
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
def api_save(guild_id: str) -> Any:
    token = request.cookies.get("token")
    user = fetch_user(token) if token else None
    if not user:
        return jsonify({"error": "not logged in"}), 401

    guild = next((g for g in user.get("guilds", []) if g["id"] == guild_id), None)
    if not guild or not (int(guild.get("permissions", 0)) & 0x20):
        return jsonify({"error": "no permission"}), 403

    data = request.get_json()
    if not data:
        return jsonify({"error": "no data"}), 400

    try:
        db = get_db()
        db["guilds"].update_one({"guild_id": int(guild_id)}, {"$set": data}, upsert=True)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/<guild_id>/roles")
def api_roles(guild_id: str) -> Any:
    user_token = request.cookies.get("token")
    auth = f"Bot {BOT_TOKEN}" if BOT_TOKEN else f"Bearer {user_token}" if user_token else ""
    if not auth:
        return jsonify([])
    try:
        r = requests.get(f"{API}/guilds/{guild_id}/roles", headers={"Authorization": auth}, timeout=10)
        print(f"[API] Roles {guild_id}: status={r.status_code} auth={'Bot' if BOT_TOKEN else 'User'}")
        if r.status_code != 200:
            print(f"[API] Roles error: {r.text[:200]}")
            return jsonify([])
        roles = [x for x in r.json() if not x.get("managed") and x["name"] != "@everyone"]
        roles.sort(key=lambda x: x.get("position", 0), reverse=True)
        return jsonify([{"id": r["id"], "name": r["name"]} for r in roles])
    except Exception as e:
        print(f"[API] Roles exception: {e}")
        return jsonify([])


@app.route("/api/<guild_id>/channels")
def api_channels(guild_id: str) -> Any:
    user_token = request.cookies.get("token")
    auth = f"Bot {BOT_TOKEN}" if BOT_TOKEN else f"Bearer {user_token}" if user_token else ""
    if not auth:
        return jsonify([])
    try:
        r = requests.get(f"{API}/guilds/{guild_id}/channels", headers={"Authorization": auth}, timeout=10)
        print(f"[API] Channels {guild_id}: status={r.status_code} auth={'Bot' if BOT_TOKEN else 'User'}")
        if r.status_code != 200:
            print(f"[API] Channels error: {r.text[:200]}")
            return jsonify([])
        channels = [c for c in r.json() if c.get("type") == 0]
        channels.sort(key=lambda x: x.get("position", 0))
        return jsonify([{"id": c["id"], "name": c["name"]} for c in channels])
    except Exception as e:
        print(f"[API] Channels exception: {e}")
        return jsonify([])


if __name__ == "__main__":
    app.run(debug=True, port=5000)
