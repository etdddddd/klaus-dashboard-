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
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
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


def fetch_discord_user(user_id: str) -> dict | None:
    if not BOT_TOKEN:
        return None
    try:
        r = requests.get(
            f"{API}/users/{user_id}",
            headers={"Authorization": f"Bot {BOT_TOKEN}"},
            timeout=5,
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def avatar_url(user_id: str, avatar_hash: str | None) -> str:
    if avatar_hash:
        return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png?size=128"
    idx = (int(user_id) >> 22) % 6 if user_id else 0
    return f"https://cdn.discordapp.com/embed/avatars/{idx}.png"


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
        "welcome_image": "",
        "autorole_enabled": False, "autorole_role": "",
        "farewell_enabled": False, "farewell_channel": "", "farewell_message": "Tchau, {user}! \U0001f44b",
        "farewell_color": "#f87171", "farewell_title": "\U0001f44b Até logo!",
        "farewell_image": "",
        "logs_enabled": False, "logs_channel": "",
        "logging_messages": False, "logging_members": False, "logging_mod": False,
        "logging_voice": False,
        "xp_enabled": True, "xp_min": 15, "xp_max": 25, "xp_cooldown": 60,
        "xp_announce_channel": "",
        "automod_enabled": False,
        "automod_max_links": 3, "automod_max_mentions": 5,
        "automod_bad_words": "", "automod_anti_spam": False,
        "automod_anti_links": False, "automod_bad_words_toggle": False,
        "economy_starting_koins": 1000,
        "economy_daily_min": 100, "economy_daily_max": 500,
        "economy_work_cooldown": 3600, "economy_rob_cooldown": 7200,
        "economy_daily_streak_bonus": 50,
        "embed_color_primary": "#8b5cf6", "embed_color_success": "#22c55e",
        "embed_color_error": "#ef4444", "embed_color_warning": "#f59e0b",
        "welcome_footer": "Klaus Bot", "farewell_footer": "Klaus Bot",
        "reaction_role_channel": "",
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
        return jsonify({"error": "no token", "roles": []})
    try:
        r = requests.get(f"{API}/guilds/{guild_id}/roles", headers={"Authorization": auth}, timeout=10)
        if r.status_code != 200:
            return jsonify({"error": r.json().get("message", str(r.status_code)), "roles": []})
        roles = [x for x in r.json() if not x.get("managed") and x["name"] != "@everyone"]
        roles.sort(key=lambda x: x.get("position", 0), reverse=True)
        return jsonify({"roles": [{"id": r["id"], "name": r["name"]} for r in roles]})
    except Exception as e:
        return jsonify({"error": str(e), "roles": []})


@app.route("/api/<guild_id>/channels")
def api_channels(guild_id: str) -> Any:
    user_token = request.cookies.get("token")
    auth = f"Bot {BOT_TOKEN}" if BOT_TOKEN else f"Bearer {user_token}" if user_token else ""
    if not auth:
        return jsonify({"error": "no token", "channels": []})
    try:
        r = requests.get(f"{API}/guilds/{guild_id}/channels", headers={"Authorization": auth}, timeout=10)
        if r.status_code != 200:
            return jsonify({"error": r.json().get("message", str(r.status_code)), "channels": []})
        channels = [c for c in r.json() if c.get("type") == 0]
        channels.sort(key=lambda x: x.get("position", 0))
        return jsonify({"channels": [{"id": c["id"], "name": c["name"]} for c in channels]})
    except Exception as e:
        return jsonify({"error": str(e), "channels": []})


@app.route("/api/leaderboard")
def api_leaderboard() -> Any:
    try:
        db = get_db()
        cursor = db["usuarios"].find().sort("koins", -1).limit(10)
        entries = []
        for i, doc in enumerate(cursor):
            entries.append({
                "rank": i + 1,
                "discord_id": str(doc.get("discord_id", "")),
                "username": doc.get("username", ""),
                "koins": doc.get("koins", 0),
                "wins": doc.get("wins", 0),
                "losses": doc.get("losses", 0),
            })
        return jsonify({"entries": entries})
    except Exception as e:
        return jsonify({"error": str(e), "entries": []})


@app.route("/api/stats")
def api_stats() -> Any:
    try:
        db = get_db()
        total_users = db["usuarios"].count_documents({})
        pipeline = [{"$group": {"_id": None, "total_koins": {"$sum": "$koins"}}}]
        result = list(db["usuarios"].aggregate(pipeline))
        total_koins = result[0]["total_koins"] if result else 0
        return jsonify({
            "total_users": total_users,
            "total_koins": total_koins,
        })
    except Exception as e:
        return jsonify({"error": str(e), "total_users": 0, "total_koins": 0})


@app.route("/api/profile/<user_id>")
def api_profile(user_id: str) -> Any:
    try:
        db = get_db()
        doc = db["usuarios"].find_one({"discord_id": int(user_id)})
        if not doc:
            return jsonify({"error": "user not found"}), 404
        av = doc.get("avatar", "")
        return jsonify({
            "discord_id": str(doc.get("discord_id", "")),
            "username": doc.get("username", f"User#{user_id[-4:]}"),
            "avatar_url": avatar_url(user_id, av),
            "koins": doc.get("koins", 0),
            "wins": doc.get("wins", 0),
            "losses": doc.get("losses", 0),
            "profit": doc.get("profit", 0),
            "commands_used": doc.get("commands_used", 0),
            "mines": doc.get("mines", 0),
            "daily_streak": doc.get("daily_streak", 0),
            "achievements": doc.get("achievements", []),
            "total_earned": doc.get("total_earned", 0),
            "total_lost": doc.get("total_lost", 0),
            "daily_claims": doc.get("daily_claims", 0),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/leaderboard_full")
def api_leaderboard_full() -> Any:
    try:
        db = get_db()
        page = int(request.args.get("page", 1))
        per_page = 20
        skip = (page - 1) * per_page
        total = db["usuarios"].count_documents({})
        cursor = db["usuarios"].find().sort("koins", -1).skip(skip).limit(per_page)
        entries = []
        for i, doc in enumerate(cursor):
            uid = str(doc.get("discord_id", ""))
            username = doc.get("username", "")
            av_hash = doc.get("avatar", "")

            if not username or not av_hash:
                remote = fetch_discord_user(uid)
                if remote:
                    username = username or remote.get("username", "")
                    av_hash = av_hash or remote.get("avatar", "")
                    gn = remote.get("global_name", "")
                    db["usuarios"].update_one(
                        {"discord_id": int(uid)},
                        {"$set": {"username": username, "avatar": av_hash, "global_name": gn}},
                    )

            entries.append({
                "rank": skip + i + 1,
                "discord_id": uid,
                "username": username or f"User#{uid[-4:]}",
                "avatar_url": avatar_url(uid, av_hash),
                "koins": doc.get("koins", 0),
                "wins": doc.get("wins", 0),
                "losses": doc.get("losses", 0),
                "daily_streak": doc.get("daily_streak", 0),
                "commands_used": doc.get("commands_used", 0),
                "achievements": len(doc.get("achievements", [])),
            })
        return jsonify({
            "entries": entries,
            "total": total,
            "page": page,
            "pages": (total + per_page - 1) // per_page,
        })
    except Exception as e:
        return jsonify({"error": str(e), "entries": []})


@app.route("/api/bot_status")
def api_bot_status() -> Any:
    try:
        db = get_db()
        total_users = db["usuarios"].count_documents({})
        total_guilds = 0
        if BOT_TOKEN:
            try:
                r = requests.get(f"{API}/users/@me", headers={"Authorization": f"Bot {BOT_TOKEN}"}, timeout=10)
                if r.status_code == 200:
                    pass
                r2 = requests.get(f"{API}/users/@me/guilds", headers={"Authorization": f"Bot {BOT_TOKEN}"}, timeout=10)
                if r2.status_code == 200:
                    total_guilds = len(r2.json())
            except Exception:
                pass

        pipeline = [{"$group": {"_id": None, "total": {"$sum": "$koins"}}}]
        result = list(db["usuarios"].aggregate(pipeline))
        total_koins = result[0]["total"] if result else 0

        pipeline2 = [{"$group": {"_id": None, "total": {"$sum": "$commands_used"}}}]
        result2 = list(db["usuarios"].aggregate(pipeline2))
        total_commands = result2[0]["total"] if result2 else 0

        pipeline3 = [{"$group": {"_id": None, "total": {"$sum": {"$size": {"$ifNull": ["$achievements", []]}}}}}]
        result3 = list(db["usuarios"].aggregate(pipeline3))
        total_achievements = result3[0]["total"] if result3 else 0

        top_user = db["usuarios"].find_one(sort=[("koins", -1)])
        top_name = "N/A"
        top_uid = "N/A"
        top_koins = 0
        top_avatar = ""
        if top_user:
            top_uid = str(top_user.get("discord_id", ""))
            top_name = top_user.get("username", "")
            top_avatar = top_user.get("avatar", "")
            top_koins = top_user.get("koins", 0)
            if not top_name or not top_avatar:
                remote = fetch_discord_user(top_uid)
                if remote:
                    top_name = top_name or remote.get("username", "")
                    top_avatar = top_avatar or remote.get("avatar", "")
                    db["usuarios"].update_one(
                        {"discord_id": int(top_uid)},
                        {"$set": {"username": top_name, "avatar": top_avatar}},
                    )
            top_name = top_name or f"User#{top_uid[-4:]}"

        return jsonify({
            "status": "online",
            "total_users": total_users,
            "total_guilds": total_guilds,
            "total_koins": total_koins,
            "total_commands": total_commands,
            "total_achievements": total_achievements,
            "top_user_id": top_uid,
            "top_user_name": top_name,
            "top_user_avatar": avatar_url(top_uid, top_avatar),
            "top_user_koins": top_koins,
            "bot_name": "Klaus",
            "bot_version": "2.0",
            "uptime": "24/7",
        })
    except Exception as e:
        return jsonify({"error": str(e), "status": "offline"})


@app.route("/status")
def status_page() -> str:
    return render_template("status.html")


@app.route("/leaderboard")
def leaderboard_page() -> str:
    return render_template("leaderboard.html")


PROFILE_BACKGROUNDS = {
        "padrao": {"name": "Padrao", "emoji": "⬜", "price": 0, "colors": {"bg": "#0a0a0a", "accent": "#3a3a3a", "border": "#8a8a8a"}, "effects": {"particles": 20, "sparkles": 0, "stripes": False, "grid": False, "glow": 0}},
        "madeira": {"name": "Madeira", "emoji": "🪵", "price": 500, "colors": {"bg": "#0d0805", "accent": "#6b4423", "border": "#b87333"}, "effects": {"particles": 30, "sparkles": 5, "stripes": False, "grid": False, "glow": 1}},
        "argila": {"name": "Argila", "emoji": "🏺", "price": 500, "colors": {"bg": "#0d0a08", "accent": "#8b5a2b", "border": "#cd853f"}, "effects": {"particles": 30, "sparkles": 5, "stripes": False, "grid": False, "glow": 1}},
        "musgo": {"name": "Musgo", "emoji": "🌿", "price": 500, "colors": {"bg": "#050a05", "accent": "#2d5a27", "border": "#4caf50"}, "effects": {"particles": 30, "sparkles": 5, "stripes": False, "grid": False, "glow": 1}},
        "pedra": {"name": "Pedra", "emoji": "🪨", "price": 750, "colors": {"bg": "#0a0a08", "accent": "#5a5a55", "border": "#8b8b80"}, "effects": {"particles": 15, "sparkles": 0, "stripes": False, "grid": False, "glow": 0}},
        "areia": {"name": "Areia", "emoji": "🏖️", "price": 750, "colors": {"bg": "#0d0c08", "accent": "#8b7355", "border": "#daa520"}, "effects": {"particles": 30, "sparkles": 5, "stripes": False, "grid": False, "glow": 1}},
        "cinza_prata": {"name": "Cinza Prata", "emoji": "🔘", "price": 800, "colors": {"bg": "#0a0a0a", "accent": "#4a4a4a", "border": "#b0b0b0"}, "effects": {"particles": 20, "sparkles": 3, "stripes": False, "grid": False, "glow": 1}},
        "tartaruga": {"name": "Tartaruga", "emoji": "🐢", "price": 800, "colors": {"bg": "#050a05", "accent": "#2a5a2a", "border": "#3cb371"}, "effects": {"particles": 20, "sparkles": 3, "stripes": False, "grid": False, "glow": 1}},
        "ferro": {"name": "Ferro", "emoji": "⚙️", "price": 1000, "colors": {"bg": "#080808", "accent": "#5a5a5a", "border": "#a0a0a0"}, "effects": {"particles": 25, "sparkles": 8, "stripes": True, "grid": False, "glow": 1}},
        "carvao": {"name": "Carvao", "emoji": "⬛", "price": 1000, "colors": {"bg": "#050505", "accent": "#3a3a3a", "border": "#5a5a5a"}, "effects": {"particles": 15, "sparkles": 0, "stripes": False, "grid": False, "glow": 0}},
        "turfa": {"name": "Turfa", "emoji": "🟤", "price": 1000, "colors": {"bg": "#0a0805", "accent": "#6b4423", "border": "#8b6914"}, "effects": {"particles": 15, "sparkles": 0, "stripes": False, "grid": False, "glow": 0}},
        "bambu": {"name": "Bambu", "emoji": "🎋", "price": 1500, "colors": {"bg": "#050a05", "accent": "#3a6b27", "border": "#7cfc00"}, "effects": {"particles": 30, "sparkles": 8, "stripes": False, "grid": False, "glow": 1}},
        "cacto": {"name": "Cacto", "emoji": "🌵", "price": 1500, "colors": {"bg": "#050a08", "accent": "#1a7b3a", "border": "#32cd32"}, "effects": {"particles": 30, "sparkles": 8, "stripes": False, "grid": False, "glow": 1}},
        "aloe": {"name": "Aloe", "emoji": "🌱", "price": 1500, "colors": {"bg": "#050a05", "accent": "#2e8b22", "border": "#90ee90"}, "effects": {"particles": 30, "sparkles": 8, "stripes": False, "grid": False, "glow": 1}},
        "chimarra": {"name": "Chimarra", "emoji": "🧉", "price": 2000, "colors": {"bg": "#0d0a05", "accent": "#5a4a1a", "border": "#8b7355"}, "effects": {"particles": 25, "sparkles": 5, "stripes": False, "grid": False, "glow": 1}},
        "melancia": {"name": "Melancia", "emoji": "🍉", "price": 3000, "colors": {"bg": "#0d0505", "accent": "#4a2a1a", "border": "#ff6b6b"}, "effects": {"particles": 40, "sparkles": 10, "stripes": False, "grid": False, "glow": 1}},
        "cerveja": {"name": "Cerveja", "emoji": "🍺", "price": 5000, "colors": {"bg": "#0d0a05", "accent": "#6a5a1a", "border": "#daa520"}, "effects": {"particles": 40, "sparkles": 10, "stripes": False, "grid": False, "glow": 1}},
        "cafe": {"name": "Cafe", "emoji": "☕", "price": 6000, "colors": {"bg": "#0d0805", "accent": "#6b3317", "border": "#d2691e"}, "effects": {"particles": 50, "sparkles": 12, "stripes": False, "grid": False, "glow": 1}},
        "cha": {"name": "Cha", "emoji": "🍵", "price": 6000, "colors": {"bg": "#080a05", "accent": "#5a7b2a", "border": "#9acd32"}, "effects": {"particles": 50, "sparkles": 12, "stripes": False, "grid": False, "glow": 1}},
        "frutas_tropicais": {"name": "Frutas Tropicais", "emoji": "🍊", "price": 8000, "colors": {"bg": "#0d0a05", "accent": "#5a4a1a", "border": "#ff8c00"}, "effects": {"particles": 60, "sparkles": 15, "stripes": True, "grid": False, "glow": 1}},
        "mandacaru": {"name": "Mandacaru", "emoji": "🌵", "price": 10000, "colors": {"bg": "#050a05", "accent": "#1a4a1a", "border": "#32cd32"}, "effects": {"particles": 40, "sparkles": 10, "stripes": False, "grid": False, "glow": 1}},
        "amarelo_solar": {"name": "Amarelo Solar", "emoji": "☀️", "price": 10000, "colors": {"bg": "#0d0d05", "accent": "#5a5a1a", "border": "#ffd700"}, "effects": {"particles": 60, "sparkles": 15, "stripes": True, "grid": False, "glow": 2}},
        "tucano": {"name": "Tucano", "emoji": "🦜", "price": 12000, "colors": {"bg": "#050d05", "accent": "#1a5a1a", "border": "#ff8c00"}, "effects": {"particles": 60, "sparkles": 15, "stripes": False, "grid": False, "glow": 1}},
        "planicie": {"name": "Planicie", "emoji": "🌾", "price": 12000, "colors": {"bg": "#0a0d05", "accent": "#4a6a2a", "border": "#9acd32"}, "effects": {"particles": 50, "sparkles": 12, "stripes": False, "grid": False, "glow": 1}},
        "chocolate": {"name": "Chocolate", "emoji": "🍫", "price": 12000, "colors": {"bg": "#0d0805", "accent": "#6b3317", "border": "#8b4513"}, "effects": {"particles": 40, "sparkles": 8, "stripes": False, "grid": False, "glow": 1}},
        "caramelo": {"name": "Caramelo", "emoji": "🍮", "price": 12000, "colors": {"bg": "#0d0a05", "accent": "#7b5423", "border": "#daa520"}, "effects": {"particles": 40, "sparkles": 8, "stripes": False, "grid": False, "glow": 1}},
        "sake": {"name": "Sake", "emoji": "🍶", "price": 12000, "colors": {"bg": "#0d0d0d", "accent": "#4a4a4a", "border": "#f5f5f5"}, "effects": {"particles": 40, "sparkles": 10, "stripes": False, "grid": False, "glow": 1}},
        "neblina": {"name": "Neblina", "emoji": "🌫️", "price": 15000, "colors": {"bg": "#0a0a0a", "accent": "#3a3a3a", "border": "#c0c0c0"}, "effects": {"particles": 40, "sparkles": 10, "stripes": False, "grid": False, "glow": 2, "type": "shadow_waves", "intensity": 1}},
        "vinho_tinto": {"name": "Vinho Tinto", "emoji": "🍷", "price": 15000, "colors": {"bg": "#100508", "accent": "#4a1a2a", "border": "#800020"}, "effects": {"particles": 50, "sparkles": 10, "stripes": False, "grid": False, "glow": 1}},
        "bronze": {"name": "Bronze", "emoji": "🟠", "price": 15000, "colors": {"bg": "#0d0a05", "accent": "#8b6a2a", "border": "#cd9b1d"}, "effects": {"particles": 60, "sparkles": 15, "stripes": True, "grid": False, "glow": 1}},
        "latao": {"name": "Latao", "emoji": "🟡", "price": 15000, "colors": {"bg": "#0d0c05", "accent": "#8b7a2a", "border": "#daa520"}, "effects": {"particles": 60, "sparkles": 15, "stripes": True, "grid": False, "glow": 1}},
        "royal": {"name": "Royal", "emoji": "👑", "price": 15000, "colors": {"bg": "#0a050d", "accent": "#3a1a5a", "border": "#9400d3"}, "effects": {"particles": 80, "sparkles": 25, "stripes": True, "grid": False, "glow": 2}},
        "imperial": {"name": "Imperial", "emoji": "🥇", "price": 15000, "colors": {"bg": "#0d0a05", "accent": "#6a5a1a", "border": "#ffd700"}, "effects": {"particles": 80, "sparkles": 25, "stripes": True, "grid": False, "glow": 2, "type": "nebula", "intensity": 1}},
        "coral_vibrante": {"name": "Coral Vibrante", "emoji": "🪸", "price": 15000, "colors": {"bg": "#0d0808", "accent": "#5a3a3a", "border": "#ff7f50"}, "effects": {"particles": 70, "sparkles": 20, "stripes": True, "grid": False, "glow": 2}},
        "samurai": {"name": "Samurai", "emoji": "⚔️", "price": 15000, "colors": {"bg": "#0d0505", "accent": "#5a1a1a", "border": "#b22222"}, "effects": {"particles": 90, "sparkles": 30, "stripes": True, "grid": False, "glow": 2}},
        "vinho": {"name": "Vinho", "emoji": "🍷", "price": 18000, "colors": {"bg": "#100508", "accent": "#5a1a2a", "border": "#722f37"}, "effects": {"particles": 50, "sparkles": 10, "stripes": False, "grid": False, "glow": 1}},
        "oasis": {"name": "Oasis", "emoji": "🏝️", "price": 18000, "colors": {"bg": "#0d0c08", "accent": "#4a6a2a", "border": "#40e0d0"}, "effects": {"particles": 50, "sparkles": 12, "stripes": False, "grid": False, "glow": 1}},
        "geada": {"name": "Geada", "emoji": "🥶", "price": 20000, "colors": {"bg": "#050a0d", "accent": "#1a4a5a", "border": "#87ceeb"}, "effects": {"particles": 80, "sparkles": 30, "stripes": False, "grid": True, "glow": 2, "type": "crystal", "intensity": 1}},
        "lobo_guara": {"name": "Lobo Guara", "emoji": "🐺", "price": 20000, "colors": {"bg": "#0a0a08", "accent": "#4a3a2a", "border": "#b87333"}, "effects": {"particles": 60, "sparkles": 15, "stripes": False, "grid": False, "glow": 1}},
        "retro": {"name": "Retro", "emoji": "📺", "price": 20000, "colors": {"bg": "#0d0a08", "accent": "#5a4a2a", "border": "#daa520"}, "effects": {"particles": 70, "sparkles": 18, "stripes": True, "grid": False, "glow": 2}},
        "neon": {"name": "Neon", "emoji": "💡", "price": 20000, "colors": {"bg": "#050510", "accent": "#1a1a4a", "border": "#00ff00"}, "effects": {"particles": 100, "sparkles": 40, "stripes": True, "grid": True, "glow": 3, "type": "neon_pulse", "intensity": 2}},
        "ninja": {"name": "Ninja", "emoji": "🥷", "price": 20000, "colors": {"bg": "#050505", "accent": "#2a2a2a", "border": "#ff4444"}, "effects": {"particles": 90, "sparkles": 30, "stripes": True, "grid": False, "glow": 2, "type": "shadow_waves", "intensity": 2}},
        "viking": {"name": "Viking", "emoji": "🪓", "price": 20000, "colors": {"bg": "#0a0a0d", "accent": "#2a2a4a", "border": "#c0c0c0"}, "effects": {"particles": 90, "sparkles": 30, "stripes": True, "grid": False, "glow": 2}},
        "azul_profundo": {"name": "Azul Profundo", "emoji": "💙", "price": 20000, "colors": {"bg": "#050510", "accent": "#1a1a4a", "border": "#00008b"}, "effects": {"particles": 80, "sparkles": 25, "stripes": True, "grid": False, "glow": 2}},
        "sol_nascente": {"name": "Sol Nascente", "emoji": "🌅", "price": 22000, "colors": {"bg": "#100805", "accent": "#6a4a1a", "border": "#ff8c00"}, "effects": {"particles": 70, "sparkles": 20, "stripes": False, "grid": False, "glow": 2}},
        "arara": {"name": "Arara", "emoji": "🦜", "price": 22000, "colors": {"bg": "#050510", "accent": "#1a1a4a", "border": "#4169e1"}, "effects": {"particles": 70, "sparkles": 20, "stripes": False, "grid": False, "glow": 2}},
        "canela_dourada": {"name": "Canela Dourada", "emoji": "✨", "price": 22000, "colors": {"bg": "#0d0a05", "accent": "#6a4a1a", "border": "#daa520"}, "effects": {"particles": 80, "sparkles": 25, "stripes": True, "grid": False, "glow": 2}},
        "polaridade": {"name": "Polaridade", "emoji": "🧲", "price": 25000, "colors": {"bg": "#0d0d0d", "accent": "#5a5a5a", "border": "#e0e0e0"}, "effects": {"particles": 80, "sparkles": 25, "stripes": True, "grid": True, "glow": 2}},
        "agate": {"name": "Agata", "emoji": "🟤", "price": 25000, "colors": {"bg": "#0d0a08", "accent": "#5a4a2a", "border": "#cd853f"}, "effects": {"particles": 50, "sparkles": 12, "stripes": False, "grid": False, "glow": 1}},
        "verde_esmeralda": {"name": "Verde Esmeralda", "emoji": "💚", "price": 25000, "colors": {"bg": "#050d05", "accent": "#1a5a2a", "border": "#2e8b57"}, "effects": {"particles": 80, "sparkles": 25, "stripes": True, "grid": False, "glow": 2}},
        "tufao": {"name": "Tufao", "emoji": "🌪️", "price": 25000, "colors": {"bg": "#0a0a0d", "accent": "#2a2a4a", "border": "#708090"}, "effects": {"particles": 80, "sparkles": 20, "stripes": False, "grid": False, "glow": 2, "type": "shadow_waves", "intensity": 2}},
        "cafe_eterno": {"name": "Cafe Eterno", "emoji": "☕", "price": 25000, "colors": {"bg": "#0d0805", "accent": "#5a3317", "border": "#a0522d"}, "effects": {"particles": 40, "sparkles": 8, "stripes": False, "grid": False, "glow": 1}},
        "zirconio": {"name": "Zirconio", "emoji": "💙", "price": 25000, "colors": {"bg": "#050510", "accent": "#1a1a4a", "border": "#4169e1"}, "effects": {"particles": 60, "sparkles": 18, "stripes": False, "grid": False, "glow": 2}},
        "prata": {"name": "Prata", "emoji": "🔘", "price": 30000, "colors": {"bg": "#0a0a0d", "accent": "#7a7a8a", "border": "#c0c0c0"}, "effects": {"particles": 40, "sparkles": 15, "stripes": True, "grid": False, "glow": 1}},
        "platina": {"name": "Platina", "emoji": "⚪", "price": 30000, "colors": {"bg": "#0a0a0a", "accent": "#8a8a8a", "border": "#e5e5e5"}, "effects": {"particles": 40, "sparkles": 15, "stripes": True, "grid": False, "glow": 1}},
        "niquel": {"name": "Niquel", "emoji": "⚙️", "price": 30000, "colors": {"bg": "#0a0a0a", "accent": "#6a6a7a", "border": "#a8a8a8"}, "effects": {"particles": 40, "sparkles": 15, "stripes": True, "grid": False, "glow": 1}},
        "lofi": {"name": "Lo-Fi", "emoji": "🎧", "price": 30000, "colors": {"bg": "#0d0a08", "accent": "#5a4a2a", "border": "#cd853f"}, "effects": {"particles": 70, "sparkles": 18, "stripes": True, "grid": False, "glow": 2, "type": "shadow_waves", "intensity": 1}},
        "sakura": {"name": "Sakura", "emoji": "🌸", "price": 30000, "colors": {"bg": "#0d0508", "accent": "#5a1a2a", "border": "#ffb7c5"}, "effects": {"particles": 70, "sparkles": 20, "stripes": True, "grid": False, "glow": 2, "type": "petals", "intensity": 2}},
        "esmeralda": {"name": "Esmeralda", "emoji": "💎", "price": 30000, "colors": {"bg": "#050d08", "accent": "#1a5a2a", "border": "#50c878"}, "effects": {"particles": 80, "sparkles": 25, "stripes": True, "grid": False, "glow": 2}},
        "tropical": {"name": "Tropical", "emoji": "🌴", "price": 30000, "colors": {"bg": "#050d05", "accent": "#1a5a1a", "border": "#00fa9a"}, "effects": {"particles": 60, "sparkles": 15, "stripes": False, "grid": False, "glow": 1, "type": "petals", "intensity": 2}},
        "primavera": {"name": "Primavera", "emoji": "🌷", "price": 30000, "colors": {"bg": "#0d0508", "accent": "#5a1a3a", "border": "#ff69b4"}, "effects": {"particles": 60, "sparkles": 18, "stripes": False, "grid": False, "glow": 2, "type": "petals", "intensity": 3}},
        "rosa_champagne": {"name": "Rosa Champagne", "emoji": "🥂", "price": 30000, "colors": {"bg": "#0d0508", "accent": "#4a2a3a", "border": "#f7cac9"}, "effects": {"particles": 70, "sparkles": 22, "stripes": True, "grid": False, "glow": 2}},
        "prisma": {"name": "Prisma", "emoji": "🔺", "price": 30000, "colors": {"bg": "#0a0a0d", "accent": "#3a3a4a", "border": "#ff69b4"}, "effects": {"particles": 90, "sparkles": 30, "stripes": True, "grid": True, "glow": 2, "type": "sacred_geometry", "intensity": 1}},
        "mercurio": {"name": "Mercurio", "emoji": "☿️", "price": 30000, "colors": {"bg": "#0a0a0a", "accent": "#6a6a6a", "border": "#c0c0c0"}, "effects": {"particles": 40, "sparkles": 15, "stripes": True, "grid": False, "glow": 1}},
        "geleira": {"name": "Geleira", "emoji": "🧊", "price": 35000, "colors": {"bg": "#050510", "accent": "#1a3a5a", "border": "#00bfff"}, "effects": {"particles": 100, "sparkles": 40, "stripes": False, "grid": True, "glow": 2, "type": "crystal", "intensity": 2}},
        "cristal": {"name": "Cristal", "emoji": "💎", "price": 35000, "colors": {"bg": "#0a0a0d", "accent": "#5a5a7a", "border": "#e0e0ff"}, "effects": {"particles": 100, "sparkles": 35, "stripes": False, "grid": True, "glow": 2, "type": "crystal", "intensity": 2}},
        "quartzo": {"name": "Quartzo", "emoji": "🔮", "price": 35000, "colors": {"bg": "#0d0a0d", "accent": "#7a5a7a", "border": "#dda0dd"}, "effects": {"particles": 100, "sparkles": 35, "stripes": False, "grid": True, "glow": 2, "type": "crystal", "intensity": 2}},
        "vanadio": {"name": "Vanadio", "emoji": "🟣", "price": 35000, "colors": {"bg": "#0d050d", "accent": "#4a1a4a", "border": "#9932cc"}, "effects": {"particles": 80, "sparkles": 22, "stripes": True, "grid": False, "glow": 2}},
        "fantasma": {"name": "Fantasma", "emoji": "👻", "price": 35000, "colors": {"bg": "#0a0a0d", "accent": "#3a3a4a", "border": "#e0e0ff"}, "effects": {"particles": 80, "sparkles": 20, "stripes": True, "grid": False, "glow": 2, "type": "shadow_waves", "intensity": 2}},
        "neve_sakura": {"name": "Neve Sakura", "emoji": "🌺", "price": 35000, "colors": {"bg": "#0d080a", "accent": "#5a2a3a", "border": "#ffc0cb"}, "effects": {"particles": 90, "sparkles": 35, "stripes": False, "grid": True, "glow": 2, "type": "petals", "intensity": 2}},
        "outono": {"name": "Outono", "emoji": "🍂", "price": 35000, "colors": {"bg": "#0d0a05", "accent": "#6a4a1a", "border": "#ff8c00"}, "effects": {"particles": 60, "sparkles": 15, "stripes": False, "grid": False, "glow": 1, "type": "petals", "intensity": 2}},
        "cripta": {"name": "Cripta", "emoji": "⚰️", "price": 35000, "colors": {"bg": "#0a0a0a", "accent": "#3a3a3a", "border": "#696969"}, "effects": {"particles": 60, "sparkles": 10, "stripes": False, "grid": False, "glow": 1, "type": "shadow_waves", "intensity": 1}},
        "obsidiana": {"name": "Obsidiana", "emoji": "🖤", "price": 35000, "colors": {"bg": "#050505", "accent": "#2a2a2a", "border": "#5a5a5a"}, "effects": {"particles": 50, "sparkles": 10, "stripes": False, "grid": False, "glow": 1, "type": "shadow_waves", "intensity": 1}},
        "lila_mistico": {"name": "Lila Mistico", "emoji": "🔮", "price": 35000, "colors": {"bg": "#0d050d", "accent": "#4a1a4a", "border": "#c8a2c8"}, "effects": {"particles": 80, "sparkles": 25, "stripes": True, "grid": False, "glow": 2}},
        "obsidiana_v2": {"name": "Obsidiana II", "emoji": "🖤", "price": 35000, "colors": {"bg": "#050505", "accent": "#1a1a1a", "border": "#3a3a3a"}, "effects": {"particles": 40, "sparkles": 8, "stripes": False, "grid": False, "glow": 1, "type": "shadow_waves", "intensity": 1}},
        "safira_bg": {"name": "Safira", "emoji": "🔵", "price": 40000, "colors": {"bg": "#05050d", "accent": "#1a1a8b", "border": "#4169e1"}, "effects": {"particles": 80, "sparkles": 25, "stripes": False, "grid": False, "glow": 2}},
        "aquamarina": {"name": "Aquamarina", "emoji": "🩵", "price": 40000, "colors": {"bg": "#050d0d", "accent": "#1a7a8b", "border": "#7fffd4"}, "effects": {"particles": 90, "sparkles": 30, "stripes": False, "grid": False, "glow": 2, "type": "aurora", "intensity": 1}},
        "turquesa": {"name": "Turquesa", "emoji": "🩵", "price": 40000, "colors": {"bg": "#050d0d", "accent": "#1a8b8b", "border": "#40e0d0"}, "effects": {"particles": 90, "sparkles": 30, "stripes": False, "grid": False, "glow": 2, "type": "aurora", "intensity": 1}},
        "opala": {"name": "Opala", "emoji": "🤍", "price": 40000, "colors": {"bg": "#0d0a0d", "accent": "#7a7a8a", "border": "#f0f8ff"}, "effects": {"particles": 100, "sparkles": 40, "stripes": False, "grid": True, "glow": 2, "type": "crystal", "intensity": 2}},
        "jade": {"name": "Jade", "emoji": "🟢", "price": 40000, "colors": {"bg": "#050d08", "accent": "#1a8b5a", "border": "#00fa9a"}, "effects": {"particles": 80, "sparkles": 22, "stripes": False, "grid": False, "glow": 2}},
        "peridot": {"name": "Peridote", "emoji": "🟩", "price": 40000, "colors": {"bg": "#080d05", "accent": "#4a8b2a", "border": "#7fff00"}, "effects": {"particles": 80, "sparkles": 22, "stripes": False, "grid": False, "glow": 2}},
        "aventurina": {"name": "Aventurina", "emoji": "💚", "price": 40000, "colors": {"bg": "#050d08", "accent": "#2a7a3a", "border": "#3cb371"}, "effects": {"particles": 80, "sparkles": 22, "stripes": False, "grid": False, "glow": 2}},
        "topazio": {"name": "Topazio", "emoji": "🟡", "price": 40000, "colors": {"bg": "#0d0c05", "accent": "#8b7a14", "border": "#ffd700"}, "effects": {"particles": 80, "sparkles": 22, "stripes": False, "grid": False, "glow": 2}},
        "citrino": {"name": "Citrino", "emoji": "🟨", "price": 40000, "colors": {"bg": "#0d0c05", "accent": "#8b6a14", "border": "#ffb347"}, "effects": {"particles": 80, "sparkles": 22, "stripes": False, "grid": False, "glow": 2}},
        "ambra": {"name": "Ambra", "emoji": "🟠", "price": 40000, "colors": {"bg": "#0d0a05", "accent": "#8b5a14", "border": "#ff8c00"}, "effects": {"particles": 80, "sparkles": 22, "stripes": False, "grid": False, "glow": 2}},
        "rubi_bg": {"name": "Rubi", "emoji": "🔴", "price": 40000, "colors": {"bg": "#0d0505", "accent": "#8b1a1a", "border": "#dc143c"}, "effects": {"particles": 80, "sparkles": 22, "stripes": False, "grid": False, "glow": 2}},
        "granada": {"name": "Granada", "emoji": "🟥", "price": 40000, "colors": {"bg": "#0d0505", "accent": "#7a1a1a", "border": "#b22222"}, "effects": {"particles": 80, "sparkles": 22, "stripes": False, "grid": False, "glow": 2}},
        "coral": {"name": "Coral", "emoji": "🪸", "price": 40000, "colors": {"bg": "#0d0808", "accent": "#8b4a4a", "border": "#ff7f50"}, "effects": {"particles": 80, "sparkles": 22, "stripes": False, "grid": False, "glow": 2}},
        "inverno": {"name": "Inverno", "emoji": "☃️", "price": 40000, "colors": {"bg": "#050a0d", "accent": "#1a3a4a", "border": "#add8e6"}, "effects": {"particles": 80, "sparkles": 25, "stripes": True, "grid": False, "glow": 2, "type": "rain", "intensity": 1}},
        "verao": {"name": "Verao", "emoji": "☀️", "price": 40000, "colors": {"bg": "#0d0d05", "accent": "#5a5a1a", "border": "#ffd700"}, "effects": {"particles": 80, "sparkles": 25, "stripes": True, "grid": False, "glow": 2}},
        "luz_estrelas": {"name": "Luz das Estrelas", "emoji": "✨", "price": 40000, "colors": {"bg": "#0a050d", "accent": "#3a1a4a", "border": "#e6e6fa"}, "effects": {"particles": 130, "sparkles": 50, "stripes": True, "grid": True, "glow": 3}},
        "neon_rosa": {"name": "Neon Rosa", "emoji": "💗", "price": 40000, "colors": {"bg": "#0d050a", "accent": "#4a1a2a", "border": "#ff1493"}, "effects": {"particles": 110, "sparkles": 45, "stripes": True, "grid": True, "glow": 3, "type": "neon_pulse", "intensity": 2}},
        "cromo": {"name": "Cromo", "emoji": "🪞", "price": 40000, "colors": {"bg": "#0a0a0a", "accent": "#4a4a4a", "border": "#d4d4d4"}, "effects": {"particles": 40, "sparkles": 15, "stripes": True, "grid": False, "glow": 1}},
        "berilo": {"name": "Berilo", "emoji": "💎", "price": 40000, "colors": {"bg": "#050d0d", "accent": "#1a5a5a", "border": "#7fffd4"}, "effects": {"particles": 90, "sparkles": 30, "stripes": False, "grid": True, "glow": 2}},
        "fractal": {"name": "Fractal", "emoji": "🔮", "price": 40000, "colors": {"bg": "#050510", "accent": "#1a1a4a", "border": "#7b68ee"}, "effects": {"particles": 100, "sparkles": 35, "stripes": True, "grid": True, "glow": 2, "type": "sacred_geometry", "intensity": 2}},
        "vermelho_sangue": {"name": "Vermelho Sangue", "emoji": "🩸", "price": 40000, "colors": {"bg": "#100505", "accent": "#5a1a1a", "border": "#8b0000"}, "effects": {"particles": 80, "sparkles": 20, "stripes": True, "grid": False, "glow": 2}},
        "lapis_lazuli": {"name": "Lapis Lazuli", "emoji": "🔵", "price": 42000, "colors": {"bg": "#050510", "accent": "#1a1a5a", "border": "#1f3fb5"}, "effects": {"particles": 90, "sparkles": 30, "stripes": False, "grid": True, "glow": 2}},
        "difracao": {"name": "Difracao", "emoji": "🌈", "price": 42000, "colors": {"bg": "#0a0a0d", "accent": "#3a3a5a", "border": "#ff69b4"}, "effects": {"particles": 100, "sparkles": 35, "stripes": True, "grid": True, "glow": 2}},
        "aurora": {"name": "Aurora", "emoji": "🌈", "price": 45000, "colors": {"bg": "#050a0d", "accent": "#1a4a4a", "border": "#00ffff"}, "effects": {"particles": 140, "sparkles": 50, "stripes": True, "grid": True, "glow": 3, "type": "aurora", "intensity": 3}},
        "borboleta": {"name": "Borboleta", "emoji": "🦋", "price": 45000, "colors": {"bg": "#0d050a", "accent": "#4a1a3a", "border": "#da70d6"}, "effects": {"particles": 80, "sparkles": 22, "stripes": True, "grid": False, "glow": 2, "type": "petals", "intensity": 2}},
        "gravitacional": {"name": "Gravitacional", "emoji": "🌀", "price": 45000, "colors": {"bg": "#050510", "accent": "#1a1a5a", "border": "#4169e1"}, "effects": {"particles": 100, "sparkles": 30, "stripes": True, "grid": False, "glow": 2, "type": "vortex", "intensity": 2}},
        "relampago": {"name": "Relampago", "emoji": "⚡", "price": 45000, "colors": {"bg": "#0d0d05", "accent": "#5a5a1a", "border": "#ffff00"}, "effects": {"particles": 100, "sparkles": 30, "stripes": False, "grid": False, "glow": 3, "type": "neon_pulse", "intensity": 3}},
        "niobio": {"name": "Niobio", "emoji": "⚡", "price": 45000, "colors": {"bg": "#050510", "accent": "#1a1a4a", "border": "#4682b4"}, "effects": {"particles": 80, "sparkles": 22, "stripes": True, "grid": False, "glow": 2, "type": "neon_pulse", "intensity": 1}},
        "resonancia": {"name": "Resonancia", "emoji": "🔊", "price": 45000, "colors": {"bg": "#0a0510", "accent": "#3a1a4a", "border": "#ff1493"}, "effects": {"particles": 100, "sparkles": 30, "stripes": True, "grid": True, "glow": 2}},
        "aurora_boreal": {"name": "Aurora Boreal", "emoji": "🌌", "price": 45000, "colors": {"bg": "#050510", "accent": "#0a3a4a", "border": "#00ff88"}, "effects": {"particles": 140, "sparkles": 50, "stripes": True, "grid": True, "glow": 3, "type": "aurora", "intensity": 3}},
        "branco_perola": {"name": "Branco Perola", "emoji": "🤍", "price": 50000, "colors": {"bg": "#0d0d0d", "accent": "#5a5a5a", "border": "#fdeef4"}, "effects": {"particles": 80, "sparkles": 25, "stripes": True, "grid": False, "glow": 2}},
        "meia_noite": {"name": "Meia-Noite", "emoji": "🌙", "price": 50000, "colors": {"bg": "#050510", "accent": "#1a1a4a", "border": "#6a5acd"}, "effects": {"particles": 80, "sparkles": 22, "stripes": False, "grid": False, "glow": 2, "type": "aurora", "intensity": 1}},
        "perola": {"name": "Perola", "emoji": "🤍", "price": 50000, "colors": {"bg": "#0d0d0d", "accent": "#5a5a5a", "border": "#fdeef4"}, "effects": {"particles": 80, "sparkles": 28, "stripes": False, "grid": False, "glow": 2}},
        "crimson": {"name": "Crimson", "emoji": "🩸", "price": 50000, "colors": {"bg": "#100505", "accent": "#4a1a1a", "border": "#ff4444"}, "effects": {"particles": 70, "sparkles": 18, "stripes": False, "grid": False, "glow": 2, "type": "embers", "intensity": 1}},
        "floresta": {"name": "Floresta", "emoji": "🌲", "price": 50000, "colors": {"bg": "#050a05", "accent": "#1a4a1a", "border": "#228b22"}, "effects": {"particles": 60, "sparkles": 15, "stripes": False, "grid": False, "glow": 1, "type": "petals", "intensity": 1}},
        "floresta_sombria": {"name": "Floresta Sombria", "emoji": "🌑", "price": 50000, "colors": {"bg": "#050a05", "accent": "#1a3a1a", "border": "#006400"}, "effects": {"particles": 60, "sparkles": 12, "stripes": False, "grid": False, "glow": 1, "type": "shadow_waves", "intensity": 2}},
        "dourado": {"name": "Dourado", "emoji": "🏆", "price": 50000, "colors": {"bg": "#0d0a05", "accent": "#6a5a1a", "border": "#ffd700"}, "effects": {"particles": 100, "sparkles": 35, "stripes": True, "grid": False, "glow": 2, "type": "nebula", "intensity": 1}},
        "fenix": {"name": "Fenix", "emoji": "🔥", "price": 50000, "colors": {"bg": "#100505", "accent": "#5a1a1a", "border": "#ff4500"}, "effects": {"particles": 120, "sparkles": 35, "stripes": True, "grid": False, "glow": 3, "type": "embers", "intensity": 2}},
        "trovao": {"name": "Trovao", "emoji": "🌩️", "price": 50000, "colors": {"bg": "#0a0a0d", "accent": "#2a2a5a", "border": "#9370db"}, "effects": {"particles": 100, "sparkles": 25, "stripes": False, "grid": False, "glow": 2, "type": "neon_pulse", "intensity": 2}},
        "glitch": {"name": "Glitch", "emoji": "📟", "price": 50000, "colors": {"bg": "#050510", "accent": "#1a1a4a", "border": "#00ff00"}, "effects": {"particles": 120, "sparkles": 45, "stripes": True, "grid": True, "glow": 3, "type": "neon_pulse", "intensity": 3}},
        "cobre": {"name": "Cobre", "emoji": "🔶", "price": 55000, "colors": {"bg": "#0d0805", "accent": "#8b4513", "border": "#cd7f32"}, "effects": {"particles": 60, "sparkles": 18, "stripes": True, "grid": False, "glow": 1}},
        "turmalina": {"name": "Turmalina", "emoji": "🩷", "price": 55000, "colors": {"bg": "#0d050a", "accent": "#4a1a3a", "border": "#ff69b4"}, "effects": {"particles": 100, "sparkles": 35, "stripes": True, "grid": True, "glow": 2}},
        "vulcanico": {"name": "Vulcanico", "emoji": "🌋", "price": 55000, "colors": {"bg": "#100505", "accent": "#5a1a1a", "border": "#ff6600"}, "effects": {"particles": 120, "sparkles": 35, "stripes": True, "grid": False, "glow": 3, "type": "embers", "intensity": 3}},
        "roxo_real": {"name": "Roxo Real", "emoji": "🟣", "price": 55000, "colors": {"bg": "#0a050d", "accent": "#3a1a5a", "border": "#8a2be2"}, "effects": {"particles": 100, "sparkles": 30, "stripes": True, "grid": True, "glow": 2}},
        "terremoto": {"name": "Terremoto", "emoji": "🏚️", "price": 55000, "colors": {"bg": "#0d0a08", "accent": "#5a4a2a", "border": "#a0522d"}, "effects": {"particles": 100, "sparkles": 30, "stripes": True, "grid": True, "glow": 2, "type": "shadow_waves", "intensity": 3}},
        "monsoon": {"name": "Monsoon", "emoji": "🌧️", "price": 55000, "colors": {"bg": "#050510", "accent": "#1a2a4a", "border": "#4682b4"}, "effects": {"particles": 80, "sparkles": 20, "stripes": False, "grid": False, "glow": 2, "type": "rain", "intensity": 2}},
        "sakura_noite": {"name": "Sakura Noite", "emoji": "🌸", "price": 55000, "colors": {"bg": "#0d050a", "accent": "#5a2a3a", "border": "#ff69b4"}, "effects": {"particles": 120, "sparkles": 40, "stripes": True, "grid": True, "glow": 3, "type": "petals", "intensity": 3}},
        "onda_sonora": {"name": "Onda Sonora", "emoji": "🎵", "price": 55000, "colors": {"bg": "#0a0510", "accent": "#3a1a4a", "border": "#ff69b4"}, "effects": {"particles": 100, "sparkles": 30, "stripes": True, "grid": True, "glow": 2}},
        "cobalto": {"name": "Cobalto", "emoji": "🔵", "price": 60000, "colors": {"bg": "#05050d", "accent": "#1a1a6a", "border": "#0047ab"}, "effects": {"particles": 50, "sparkles": 15, "stripes": True, "grid": False, "glow": 1}},
        "neon_v2": {"name": "Neon II", "emoji": "💜", "price": 60000, "colors": {"bg": "#050510", "accent": "#1a1a5a", "border": "#ff00ff"}, "effects": {"particles": 110, "sparkles": 45, "stripes": True, "grid": True, "glow": 3, "type": "neon_pulse", "intensity": 3}},
        "lava": {"name": "Lava", "emoji": "🔴", "price": 60000, "colors": {"bg": "#100505", "accent": "#6a1a1a", "border": "#ff0000"}, "effects": {"particles": 120, "sparkles": 35, "stripes": True, "grid": False, "glow": 3, "type": "embers", "intensity": 3}},
        "toxico": {"name": "Toxico", "emoji": "☢️", "price": 60000, "colors": {"bg": "#050d05", "accent": "#1a5a1a", "border": "#00ff00"}, "effects": {"particles": 100, "sparkles": 30, "stripes": True, "grid": True, "glow": 3, "type": "neon_pulse", "intensity": 2}},
        "tempestade_gelo": {"name": "Tempestade de Gelo", "emoji": "🧊", "price": 60000, "colors": {"bg": "#050a0d", "accent": "#1a4a5a", "border": "#b0e0e6"}, "effects": {"particles": 100, "sparkles": 40, "stripes": False, "grid": True, "glow": 2, "type": "rain", "intensity": 2}},
        "metal": {"name": "Metal", "emoji": "🔩", "price": 60000, "colors": {"bg": "#0a0a0a", "accent": "#4a4a4a", "border": "#c0c0c0"}, "effects": {"particles": 40, "sparkles": 15, "stripes": True, "grid": False, "glow": 1}},
        "cromado": {"name": "Cromado", "emoji": "🪞", "price": 60000, "colors": {"bg": "#0a0a0a", "accent": "#4a4a4a", "border": "#d4d4d4"}, "effects": {"particles": 50, "sparkles": 18, "stripes": True, "grid": False, "glow": 1}},
        "vaporwave": {"name": "Vaporwave", "emoji": "🌴", "price": 60000, "colors": {"bg": "#0d050d", "accent": "#4a1a4a", "border": "#ff71ce"}, "effects": {"particles": 100, "sparkles": 30, "stripes": True, "grid": True, "glow": 2, "type": "neon_pulse", "intensity": 2}},
        "oceano_lunar": {"name": "Oceano Lunar", "emoji": "🌙", "price": 65000, "colors": {"bg": "#050510", "accent": "#1a2a4a", "border": "#87ceeb"}, "effects": {"particles": 100, "sparkles": 35, "stripes": False, "grid": False, "glow": 2, "type": "aurora", "intensity": 2}},
        "rubelita": {"name": "Rubelita", "emoji": "❤️", "price": 65000, "colors": {"bg": "#0d0508", "accent": "#5a1a2a", "border": "#e0115f"}, "effects": {"particles": 100, "sparkles": 35, "stripes": True, "grid": False, "glow": 2}},
        "interferencia": {"name": "Interferencia", "emoji": "📡", "price": 65000, "colors": {"bg": "#050510", "accent": "#1a1a4a", "border": "#00ffff"}, "effects": {"particles": 100, "sparkles": 30, "stripes": True, "grid": True, "glow": 2, "type": "neon_pulse", "intensity": 2}},
        "sinestesia": {"name": "Sinestesia", "emoji": "🎨", "price": 70000, "colors": {"bg": "#0d050d", "accent": "#4a1a3a", "border": "#da70d6"}, "effects": {"particles": 100, "sparkles": 35, "stripes": True, "grid": True, "glow": 2, "type": "nebula", "intensity": 2}},
        "lua_sangue": {"name": "Lua de Sangue", "emoji": "🌑", "price": 70000, "colors": {"bg": "#100505", "accent": "#4a1a1a", "border": "#8b0000"}, "effects": {"particles": 60, "sparkles": 12, "stripes": False, "grid": False, "glow": 1, "type": "embers", "intensity": 1}},
        "abismo": {"name": "Abismo", "emoji": "🕳️", "price": 70000, "colors": {"bg": "#050505", "accent": "#0f0f1a", "border": "#3a3a5f"}, "effects": {"particles": 60, "sparkles": 10, "stripes": False, "grid": False, "glow": 1, "type": "shadow_waves", "intensity": 2}},
        "eclipse": {"name": "Eclipse", "emoji": "🌑", "price": 70000, "colors": {"bg": "#0a0a0a", "accent": "#2a2a2a", "border": "#5a5a7a"}, "effects": {"particles": 60, "sparkles": 12, "stripes": False, "grid": False, "glow": 2, "type": "aurora", "intensity": 1}},
        "espiral": {"name": "Espiral", "emoji": "🔮", "price": 75000, "colors": {"bg": "#0d050d", "accent": "#4a1a4a", "border": "#da70d6"}, "effects": {"particles": 100, "sparkles": 35, "stripes": True, "grid": True, "glow": 2, "type": "vortex", "intensity": 2}},
        "seda": {"name": "Seda", "emoji": "🎀", "price": 75000, "colors": {"bg": "#0d0508", "accent": "#4a1a2a", "border": "#ffb6c1"}, "effects": {"particles": 100, "sparkles": 35, "stripes": True, "grid": True, "glow": 2}},
        "diamante": {"name": "Diamante", "emoji": "💎", "price": 75000, "colors": {"bg": "#0a0a0d", "accent": "#4a4a6a", "border": "#b9f2ff"}, "effects": {"particles": 110, "sparkles": 45, "stripes": False, "grid": True, "glow": 2, "type": "crystal", "intensity": 3}},
        "matrix": {"name": "Matrix", "emoji": "🔢", "price": 75000, "colors": {"bg": "#050d05", "accent": "#0a4a0a", "border": "#00ff00"}, "effects": {"particles": 110, "sparkles": 45, "stripes": True, "grid": True, "glow": 3, "type": "rain", "intensity": 3}},
        "labirinto": {"name": "Labirinto", "emoji": "🏛️", "price": 75000, "colors": {"bg": "#0a0a0d", "accent": "#3a3a5a", "border": "#c0c0c0"}, "effects": {"particles": 70, "sparkles": 18, "stripes": True, "grid": True, "glow": 2, "type": "sacred_geometry", "intensity": 1}},
        "steampunk": {"name": "Steampunk", "emoji": "⚙️", "price": 75000, "colors": {"bg": "#0d0a05", "accent": "#6a4a1a", "border": "#b87333"}, "effects": {"particles": 100, "sparkles": 30, "stripes": True, "grid": True, "glow": 2}},
        "cyberpunk": {"name": "Cyberpunk", "emoji": "🤖", "price": 80000, "colors": {"bg": "#0d050d", "accent": "#4a1a3a", "border": "#ff00ff"}, "effects": {"particles": 120, "sparkles": 45, "stripes": True, "grid": True, "glow": 3, "type": "neon_pulse", "intensity": 3}},
        "holograma": {"name": "Holograma", "emoji": "📱", "price": 80000, "colors": {"bg": "#0a0a0d", "accent": "#3a3a4a", "border": "#00ffff"}, "effects": {"particles": 120, "sparkles": 45, "stripes": True, "grid": True, "glow": 3, "type": "neon_pulse", "intensity": 3}},
        "synthwave": {"name": "Synthwave", "emoji": "🌆", "price": 80000, "colors": {"bg": "#0a0510", "accent": "#3a1a4a", "border": "#ff00ff"}, "effects": {"particles": 100, "sparkles": 35, "stripes": True, "grid": True, "glow": 2, "type": "neon_pulse", "intensity": 2}},
        "veludo": {"name": "Veludo", "emoji": "🎭", "price": 80000, "colors": {"bg": "#0a050d", "accent": "#3a1a4a", "border": "#800080"}, "effects": {"particles": 100, "sparkles": 35, "stripes": True, "grid": True, "glow": 2, "type": "shadow_waves", "intensity": 2}},
        "tornada": {"name": "Tornada", "emoji": "🌪️", "price": 80000, "colors": {"bg": "#0a0a0a", "accent": "#3a3a3a", "border": "#a0a0a0"}, "effects": {"particles": 80, "sparkles": 20, "stripes": False, "grid": False, "glow": 2, "type": "vortex", "intensity": 2}},
        "cyborg": {"name": "Cyborg", "emoji": "🦾", "price": 80000, "colors": {"bg": "#0a0a0a", "accent": "#4a4a5a", "border": "#4682b4"}, "effects": {"particles": 100, "sparkles": 30, "stripes": True, "grid": True, "glow": 2, "type": "neon_pulse", "intensity": 1}},
        "digital": {"name": "Digital", "emoji": "💻", "price": 80000, "colors": {"bg": "#050510", "accent": "#1a1a4a", "border": "#00ff00"}, "effects": {"particles": 110, "sparkles": 45, "stripes": True, "grid": True, "glow": 3, "type": "rain", "intensity": 2}},
        "druida": {"name": "Druida", "emoji": "🌿", "price": 85000, "colors": {"bg": "#050a05", "accent": "#2a5a2a", "border": "#32cd32"}, "effects": {"particles": 130, "sparkles": 45, "stripes": True, "grid": True, "glow": 3, "type": "petals", "intensity": 3}},
        "carmesim": {"name": "Carmesim", "emoji": "❤️", "price": 85000, "colors": {"bg": "#100505", "accent": "#5a1a1a", "border": "#dc143c"}, "effects": {"particles": 90, "sparkles": 28, "stripes": True, "grid": False, "glow": 2}},
        "vortex": {"name": "Vortex", "emoji": "🌀", "price": 85000, "colors": {"bg": "#050510", "accent": "#1a1a5a", "border": "#4169e1"}, "effects": {"particles": 100, "sparkles": 35, "stripes": True, "grid": True, "glow": 2, "type": "vortex", "intensity": 2}},
        "granito": {"name": "Granito", "emoji": "🪨", "price": 90000, "colors": {"bg": "#0a0a0a", "accent": "#4a4a4a", "border": "#808080"}, "effects": {"particles": 50, "sparkles": 15, "stripes": True, "grid": False, "glow": 1}},
        "nanotech": {"name": "Nanotech", "emoji": "🔬", "price": 90000, "colors": {"bg": "#0a0a0d", "accent": "#3a3a4a", "border": "#00bfff"}, "effects": {"particles": 100, "sparkles": 30, "stripes": True, "grid": True, "glow": 2, "type": "crystal", "intensity": 2}},
        "quantico": {"name": "Quantico", "emoji": "⚛️", "price": 90000, "colors": {"bg": "#050510", "accent": "#1a1a5a", "border": "#9370db"}, "effects": {"particles": 100, "sparkles": 30, "stripes": True, "grid": True, "glow": 2, "type": "vortex", "intensity": 2}},
        "sonico": {"name": "Sonico", "emoji": "🔊", "price": 90000, "colors": {"bg": "#0a050d", "accent": "#3a1a4a", "border": "#ff1493"}, "effects": {"particles": 100, "sparkles": 30, "stripes": True, "grid": True, "glow": 2}},
        "tsunami": {"name": "Tsunami", "emoji": "🌊", "price": 90000, "colors": {"bg": "#050510", "accent": "#0a2a4a", "border": "#0080ff"}, "effects": {"particles": 90, "sparkles": 25, "stripes": False, "grid": False, "glow": 2, "type": "aurora", "intensity": 2}},
        "alexandrita": {"name": "Alexandrita", "emoji": "🟣", "price": 90000, "colors": {"bg": "#0d050d", "accent": "#4a1a4a", "border": "#9b59b6"}, "effects": {"particles": 110, "sparkles": 40, "stripes": True, "grid": True, "glow": 2}},
        "elfico": {"name": "El fico", "emoji": "🧝", "price": 100000, "colors": {"bg": "#050d08", "accent": "#1a5a2a", "border": "#98fb98"}, "effects": {"particles": 130, "sparkles": 45, "stripes": True, "grid": True, "glow": 3, "type": "petals", "intensity": 3}},
        "dragao": {"name": "Dragao", "emoji": "🐉", "price": 100000, "colors": {"bg": "#100505", "accent": "#5a1a1a", "border": "#ff4500"}, "effects": {"particles": 120, "sparkles": 35, "stripes": True, "grid": False, "glow": 3, "type": "embers", "intensity": 2}},
        "hydra": {"name": "Hidra", "emoji": "🐍", "price": 100000, "colors": {"bg": "#050d05", "accent": "#1a5a1a", "border": "#228b22"}, "effects": {"particles": 120, "sparkles": 35, "stripes": True, "grid": False, "glow": 2, "type": "shadow_waves", "intensity": 2}},
        "poseidon": {"name": "Poseidon", "emoji": "🔱", "price": 100000, "colors": {"bg": "#050510", "accent": "#1a1a5a", "border": "#1e90ff"}, "effects": {"particles": 100, "sparkles": 30, "stripes": False, "grid": False, "glow": 2, "type": "aurora", "intensity": 2}},
        "titanio": {"name": "Titanio", "emoji": "🔩", "price": 100000, "colors": {"bg": "#0a0a0d", "accent": "#4a4a5a", "border": "#b0c4de"}, "effects": {"particles": 50, "sparkles": 18, "stripes": True, "grid": False, "glow": 1}},
        "marmore": {"name": "Marmore", "emoji": "🏛️", "price": 100000, "colors": {"bg": "#0d0d0d", "accent": "#5a5a5a", "border": "#f0f0f0"}, "effects": {"particles": 80, "sparkles": 25, "stripes": True, "grid": True, "glow": 2}},
        "anoes_brancos": {"name": "Anoes Brancos", "emoji": "⚪", "price": 100000, "colors": {"bg": "#0d0d0d", "accent": "#5a5a5a", "border": "#ffffff"}, "effects": {"particles": 110, "sparkles": 35, "stripes": True, "grid": True, "glow": 3, "type": "crystal", "intensity": 2}},
        "cyber_goth": {"name": "Cyber Goth", "emoji": "🤖", "price": 100000, "colors": {"bg": "#050510", "accent": "#1a1a4a", "border": "#ff00ff"}, "effects": {"particles": 100, "sparkles": 35, "stripes": True, "grid": True, "glow": 2, "type": "neon_pulse", "intensity": 2}},
        "topazio_imperial": {"name": "Topazio Imperial", "emoji": "🟡", "price": 110000, "colors": {"bg": "#0d0c05", "accent": "#7a6a1a", "border": "#ffd700"}, "effects": {"particles": 100, "sparkles": 35, "stripes": True, "grid": False, "glow": 2, "type": "nebula", "intensity": 1}},
        "cristal_arcoiris": {"name": "Cristal Arco-iris", "emoji": "💎", "price": 120000, "colors": {"bg": "#0a0a0d", "accent": "#4a4a6a", "border": "#ff69b4"}, "effects": {"particles": 130, "sparkles": 45, "stripes": True, "grid": True, "glow": 3, "type": "crystal", "intensity": 3}},
        "vazio": {"name": "Vazio", "emoji": "🕳️", "price": 120000, "colors": {"bg": "#050505", "accent": "#0f0f0f", "border": "#4a4a4a"}, "effects": {"particles": 40, "sparkles": 8, "stripes": False, "grid": False, "glow": 1, "type": "shadow_waves", "intensity": 1}},
        "hades": {"name": "Hades", "emoji": "💀", "price": 120000, "colors": {"bg": "#0a0505", "accent": "#3a1a1a", "border": "#8b0000"}, "effects": {"particles": 70, "sparkles": 15, "stripes": False, "grid": False, "glow": 2, "type": "embers", "intensity": 2}},
        "zeus": {"name": "Zeus", "emoji": "⚡", "price": 120000, "colors": {"bg": "#0d0d05", "accent": "#5a5a1a", "border": "#ffd700"}, "effects": {"particles": 110, "sparkles": 35, "stripes": True, "grid": False, "glow": 3, "type": "neon_pulse", "intensity": 3}},
        "reliquia": {"name": "Reliquia", "emoji": "🏺", "price": 120000, "colors": {"bg": "#0d0a05", "accent": "#6a5a1a", "border": "#daa520"}, "effects": {"particles": 100, "sparkles": 35, "stripes": True, "grid": False, "glow": 2, "type": "nebula", "intensity": 1}},
        "nebulosa": {"name": "Nebulosa", "emoji": "🔭", "price": 120000, "colors": {"bg": "#050510", "accent": "#2a1a4a", "border": "#8a2be2"}, "effects": {"particles": 150, "sparkles": 50, "stripes": True, "grid": True, "glow": 3, "type": "nebula", "intensity": 3}},
        "noir": {"name": "Noir", "emoji": "🎩", "price": 120000, "colors": {"bg": "#050505", "accent": "#1a1a1a", "border": "#4a4a4a"}, "effects": {"particles": 50, "sparkles": 10, "stripes": False, "grid": False, "glow": 1, "type": "rain", "intensity": 1}},
        "vulcao": {"name": "Vulcao", "emoji": "🌋", "price": 120000, "colors": {"bg": "#100505", "accent": "#5a1a1a", "border": "#ff3300"}, "effects": {"particles": 110, "sparkles": 35, "stripes": True, "grid": True, "glow": 3, "type": "embers", "intensity": 3}},
        "feiteiceiro": {"name": "Feiticeiro", "emoji": "🧙", "price": 125000, "colors": {"bg": "#0a0510", "accent": "#3a1a4a", "border": "#9370db"}, "effects": {"particles": 130, "sparkles": 45, "stripes": True, "grid": True, "glow": 3, "type": "nebula", "intensity": 3}},
        "feiticeiro": {"name": "Feiticeiro", "emoji": "🧙", "price": 125000, "colors": {"bg": "#0a0510", "accent": "#3a1a4a", "border": "#9370db"}, "effects": {"particles": 130, "sparkles": 45, "stripes": True, "grid": True, "glow": 3, "type": "nebula", "intensity": 3}},
        "medusa": {"name": "Medusa", "emoji": "🐍", "price": 130000, "colors": {"bg": "#050d05", "accent": "#1a5a2a", "border": "#00fa9a"}, "effects": {"particles": 110, "sparkles": 35, "stripes": False, "grid": True, "glow": 2, "type": "vortex", "intensity": 2}},
        "tungstenio": {"name": "Tungstenio", "emoji": "⚙️", "price": 150000, "colors": {"bg": "#0a0a0a", "accent": "#3a3a3a", "border": "#696969"}, "effects": {"particles": 50, "sparkles": 18, "stripes": True, "grid": False, "glow": 1}},
        "piramide": {"name": "Piramide", "emoji": "🔺", "price": 150000, "colors": {"bg": "#0d0a05", "accent": "#6a5a1a", "border": "#ffd700"}, "effects": {"particles": 100, "sparkles": 35, "stripes": True, "grid": True, "glow": 3, "type": "sacred_geometry", "intensity": 2}},
        "arco_iris": {"name": "Arco-Iris", "emoji": "🌈", "price": 150000, "colors": {"bg": "#0a0a0d", "accent": "#3a3a4a", "border": "#ff00ff"}, "effects": {"particles": 110, "sparkles": 40, "stripes": True, "grid": True, "glow": 3, "type": "aurora", "intensity": 3}},
        "cometa": {"name": "Cometa", "emoji": "☄️", "price": 150000, "colors": {"bg": "#0a050d", "accent": "#3a1a4a", "border": "#ffa500"}, "effects": {"particles": 110, "sparkles": 40, "stripes": True, "grid": True, "glow": 3, "type": "vortex", "intensity": 3}},
        "athena": {"name": "Athena", "emoji": "🦉", "price": 150000, "colors": {"bg": "#0a0a0d", "accent": "#3a3a4a", "border": "#c0c0c0"}, "effects": {"particles": 110, "sparkles": 35, "stripes": True, "grid": False, "glow": 2}},
        "egipcio": {"name": "Egipcio", "emoji": "🏛️", "price": 150000, "colors": {"bg": "#0d0a05", "accent": "#6a5a1a", "border": "#ffd700"}, "effects": {"particles": 100, "sparkles": 35, "stripes": True, "grid": False, "glow": 2, "type": "sacred_geometry", "intensity": 2}},
        "deserto_glacial": {"name": "Deserto Glacial", "emoji": "🏜️", "price": 150000, "colors": {"bg": "#0d0c08", "accent": "#5a5a3a", "border": "#daa520"}, "effects": {"particles": 100, "sparkles": 30, "stripes": True, "grid": True, "glow": 2, "type": "rain", "intensity": 1}},
        "osmio": {"name": "Osmio", "emoji": "💎", "price": 150000, "colors": {"bg": "#0a0a0d", "accent": "#3a3a5a", "border": "#4169e1"}, "effects": {"particles": 50, "sparkles": 18, "stripes": True, "grid": False, "glow": 1}},
        "iridio": {"name": "Iridio", "emoji": "🪞", "price": 150000, "colors": {"bg": "#0d0d0d", "accent": "#5a5a5a", "border": "#e0e0e0"}, "effects": {"particles": 50, "sparkles": 18, "stripes": True, "grid": False, "glow": 1}},
        "art_deco": {"name": "Art Deco", "emoji": "🏛️", "price": 150000, "colors": {"bg": "#0d0a05", "accent": "#6a5a1a", "border": "#c5a258"}, "effects": {"particles": 100, "sparkles": 35, "stripes": True, "grid": True, "glow": 2, "type": "sacred_geometry", "intensity": 2}},
        "paradoxo": {"name": "Paradoxo", "emoji": "♾️", "price": 150000, "colors": {"bg": "#050510", "accent": "#1a1a4a", "border": "#9370db"}, "effects": {"particles": 100, "sparkles": 35, "stripes": True, "grid": True, "glow": 2, "type": "vortex", "intensity": 3}},
        "paladino": {"name": "Paladino", "emoji": "⚔️", "price": 160000, "colors": {"bg": "#0d0d0d", "accent": "#5a5a3a", "border": "#ffd700"}, "effects": {"particles": 130, "sparkles": 45, "stripes": True, "grid": True, "glow": 3, "type": "crystal", "intensity": 3}},
        "arcana": {"name": "Arcana", "emoji": "🔮", "price": 175000, "colors": {"bg": "#0d050d", "accent": "#4a1a4a", "border": "#ba55d3"}, "effects": {"particles": 130, "sparkles": 45, "stripes": True, "grid": True, "glow": 3, "type": "nebula", "intensity": 3}},
        "pulsar": {"name": "Pulsar", "emoji": "⚡", "price": 180000, "colors": {"bg": "#050510", "accent": "#1a1a5a", "border": "#00bfff"}, "effects": {"particles": 150, "sparkles": 50, "stripes": True, "grid": True, "glow": 3, "type": "neon_pulse", "intensity": 3}},
        "troia": {"name": "Troia", "emoji": "🏛️", "price": 180000, "colors": {"bg": "#0d0a05", "accent": "#5a4a2a", "border": "#daa520"}, "effects": {"particles": 90, "sparkles": 30, "stripes": True, "grid": False, "glow": 2}},
        "tempestade_neon": {"name": "Tempestade Neon", "emoji": "⚡", "price": 180000, "colors": {"bg": "#050510", "accent": "#1a1a4a", "border": "#00ffff"}, "effects": {"particles": 130, "sparkles": 45, "stripes": True, "grid": True, "glow": 3, "type": "neon_pulse", "intensity": 3}},
        "sombras_eternas": {"name": "Sombras Eternas", "emoji": "🌑", "price": 190000, "colors": {"bg": "#050505", "accent": "#1a1a2a", "border": "#483d8b"}, "effects": {"particles": 60, "sparkles": 10, "stripes": False, "grid": False, "glow": 1, "type": "shadow_waves", "intensity": 2}},
        "neon_dreams": {"name": "Neon Dreams", "emoji": "💡", "price": 200000, "colors": {"bg": "#050510", "accent": "#1a1a4a", "border": "#00ffff"}, "effects": {"particles": 120, "sparkles": 40, "stripes": True, "grid": True, "glow": 3, "type": "neon_pulse", "intensity": 3}},
        "obsidiana_arcoiris": {"name": "Obsidiana Arco-iris", "emoji": "🌈", "price": 200000, "colors": {"bg": "#050505", "accent": "#2a2a2a", "border": "#ff69b4"}, "effects": {"particles": 140, "sparkles": 50, "stripes": True, "grid": True, "glow": 3, "type": "aurora", "intensity": 3}},
        "supernova": {"name": "Supernova", "emoji": "💥", "price": 200000, "colors": {"bg": "#100505", "accent": "#6a1a1a", "border": "#ff6600"}, "effects": {"particles": 150, "sparkles": 50, "stripes": True, "grid": True, "glow": 3, "type": "embers", "intensity": 3}},
        "buraco_negro": {"name": "Buraco Negro", "emoji": "🕳️", "price": 200000, "colors": {"bg": "#050505", "accent": "#0a0a0a", "border": "#5a0080"}, "effects": {"particles": 150, "sparkles": 50, "stripes": True, "grid": True, "glow": 3, "type": "vortex", "intensity": 3}},
        "big_bang": {"name": "Big Bang", "emoji": "💫", "price": 200000, "colors": {"bg": "#0d0505", "accent": "#5a1a1a", "border": "#ff0000"}, "effects": {"particles": 150, "sparkles": 50, "stripes": True, "grid": False, "glow": 3, "type": "embers", "intensity": 3}},
        "pixel": {"name": "Pixel", "emoji": "🎮", "price": 200000, "colors": {"bg": "#050510", "accent": "#1a1a4a", "border": "#00ff00"}, "effects": {"particles": 120, "sparkles": 45, "stripes": True, "grid": True, "glow": 3, "type": "rain", "intensity": 3}},
        "japones": {"name": "Japones", "emoji": "⛩️", "price": 200000, "colors": {"bg": "#0d0505", "accent": "#5a1a1a", "border": "#ff0000"}, "effects": {"particles": 120, "sparkles": 40, "stripes": True, "grid": True, "glow": 3, "type": "petals", "intensity": 3}},
        "anjo": {"name": "Anjo", "emoji": "😇", "price": 200000, "colors": {"bg": "#0d0d0d", "accent": "#5a5a5a", "border": "#fffacd"}, "effects": {"particles": 130, "sparkles": 45, "stripes": True, "grid": True, "glow": 3, "type": "crystal", "intensity": 3}},
        "portal": {"name": "Portal", "emoji": "🌀", "price": 200000, "colors": {"bg": "#050510", "accent": "#1a1a5a", "border": "#9370db"}, "effects": {"particles": 140, "sparkles": 50, "stripes": True, "grid": True, "glow": 3, "type": "vortex", "intensity": 3}},
        "ouro_liquido": {"name": "Ouro Liquido", "emoji": "🫗", "price": 200000, "colors": {"bg": "#0d0a05", "accent": "#7a6a1a", "border": "#ffc107"}, "effects": {"particles": 120, "sparkles": 40, "stripes": True, "grid": True, "glow": 3, "type": "nebula", "intensity": 3}},
        "quasar": {"name": "Quasar", "emoji": "💫", "price": 200000, "colors": {"bg": "#0d0505", "accent": "#5a1a1a", "border": "#ff6347"}, "effects": {"particles": 150, "sparkles": 50, "stripes": True, "grid": True, "glow": 3, "type": "embers", "intensity": 3}},
        "entropia": {"name": "Entropia", "emoji": "🔥", "price": 200000, "colors": {"bg": "#100505", "accent": "#5a1a1a", "border": "#ff4500"}, "effects": {"particles": 120, "sparkles": 35, "stripes": True, "grid": False, "glow": 3, "type": "embers", "intensity": 3}},
        "magnetar": {"name": "Magnetar", "emoji": "🧲", "price": 220000, "colors": {"bg": "#05050d", "accent": "#1a1a4a", "border": "#0000cd"}, "effects": {"particles": 120, "sparkles": 40, "stripes": True, "grid": True, "glow": 3, "type": "vortex", "intensity": 3}},
        "necromante": {"name": "Necromante", "emoji": "💀", "price": 225000, "colors": {"bg": "#050505", "accent": "#2a1a2a", "border": "#8b008b"}, "effects": {"particles": 130, "sparkles": 45, "stripes": True, "grid": True, "glow": 3, "type": "shadow_waves", "intensity": 3}},
        "infernal": {"name": "Infernal", "emoji": "🔥", "price": 250000, "colors": {"bg": "#100505", "accent": "#6a1a1a", "border": "#ff4500"}, "effects": {"particles": 130, "sparkles": 45, "stripes": True, "grid": False, "glow": 3, "type": "embers", "intensity": 3}},
        "divino": {"name": "Divino", "emoji": "👼", "price": 250000, "colors": {"bg": "#0d0d0d", "accent": "#5a5a5a", "border": "#ffd700"}, "effects": {"particles": 110, "sparkles": 40, "stripes": True, "grid": False, "glow": 3, "type": "crystal", "intensity": 3}},
        "eterno": {"name": "Eterno", "emoji": "♾️", "price": 250000, "colors": {"bg": "#0a0a0d", "accent": "#3a3a4a", "border": "#e6e6fa"}, "effects": {"particles": 130, "sparkles": 45, "stripes": True, "grid": True, "glow": 3, "type": "aurora", "intensity": 3}},
        "infinito": {"name": "Infinito", "emoji": "🔮", "price": 250000, "colors": {"bg": "#0d050d", "accent": "#4a1a4a", "border": "#ff00ff"}, "effects": {"particles": 130, "sparkles": 45, "stripes": True, "grid": True, "glow": 3, "type": "vortex", "intensity": 3}},
        "tempestade": {"name": "Tempestade", "emoji": "⛈️", "price": 250000, "colors": {"bg": "#0a0a0d", "accent": "#3a3a5a", "border": "#4169e1"}, "effects": {"particles": 100, "sparkles": 25, "stripes": False, "grid": False, "glow": 3, "type": "rain", "intensity": 3}},
        "platina_negra": {"name": "Platina Negra", "emoji": "⚫", "price": 250000, "colors": {"bg": "#050505", "accent": "#3a3a3a", "border": "#8a8a8a"}, "effects": {"particles": 120, "sparkles": 40, "stripes": True, "grid": True, "glow": 3, "type": "crystal", "intensity": 2}},
        "wormhole": {"name": "Wormhole", "emoji": "🕳️", "price": 250000, "colors": {"bg": "#050505", "accent": "#0a0a2a", "border": "#4b0082"}, "effects": {"particles": 150, "sparkles": 50, "stripes": True, "grid": True, "glow": 3, "type": "vortex", "intensity": 3}},
        "esfinge": {"name": "Esfinge", "emoji": "🗿", "price": 250000, "colors": {"bg": "#0d0a05", "accent": "#5a4a2a", "border": "#daa520"}, "effects": {"particles": 110, "sparkles": 38, "stripes": True, "grid": True, "glow": 3, "type": "sacred_geometry", "intensity": 2}},
        "sangue_sagrado": {"name": "Sangue Sagrado", "emoji": "🩸", "price": 275000, "colors": {"bg": "#0d0505", "accent": "#5a1a1a", "border": "#b22222"}, "effects": {"particles": 130, "sparkles": 45, "stripes": True, "grid": True, "glow": 3, "type": "embers", "intensity": 2}},
        "jade_imperial": {"name": "Jade Imperial", "emoji": "💚", "price": 275000, "colors": {"bg": "#050d08", "accent": "#1a6a3a", "border": "#00a86b"}, "effects": {"particles": 120, "sparkles": 40, "stripes": True, "grid": True, "glow": 3, "type": "petals", "intensity": 3}},
        "perola_imperial": {"name": "Perola Imperial", "emoji": "🤍", "price": 300000, "colors": {"bg": "#0d0d0d", "accent": "#5a5a5a", "border": "#fdeef4"}, "effects": {"particles": 120, "sparkles": 40, "stripes": True, "grid": True, "glow": 3, "type": "crystal", "intensity": 3}},
        "demonio": {"name": "Demonio", "emoji": "😈", "price": 300000, "colors": {"bg": "#100505", "accent": "#5a1a1a", "border": "#ff0000"}, "effects": {"particles": 130, "sparkles": 45, "stripes": True, "grid": True, "glow": 3, "type": "embers", "intensity": 3}},
        "mitico": {"name": "Mitico", "emoji": "⚜️", "price": 300000, "colors": {"bg": "#0d0a05", "accent": "#6a5a1a", "border": "#ffd700"}, "effects": {"particles": 120, "sparkles": 40, "stripes": True, "grid": False, "glow": 3, "type": "nebula", "intensity": 2}},
        "lendario": {"name": "Lendario", "emoji": "🏆", "price": 300000, "colors": {"bg": "#0d0d0d", "accent": "#5a5a5a", "border": "#ffd700"}, "effects": {"particles": 120, "sparkles": 40, "stripes": True, "grid": False, "glow": 3, "type": "crystal", "intensity": 3}},
        "ascensao": {"name": "Ascensao", "emoji": "🕊️", "price": 300000, "colors": {"bg": "#0d0d0d", "accent": "#5a5a5a", "border": "#f0f8ff"}, "effects": {"particles": 130, "sparkles": 45, "stripes": True, "grid": True, "glow": 3, "type": "aurora", "intensity": 3}},
        "via_lactea": {"name": "Via Lactea", "emoji": "🌌", "price": 300000, "colors": {"bg": "#050510", "accent": "#1a1a3a", "border": "#e6e6fa"}, "effects": {"particles": 150, "sparkles": 50, "stripes": True, "grid": True, "glow": 3, "type": "nebula", "intensity": 3}},
        "dimensional": {"name": "Dimensional", "emoji": "🕳️", "price": 300000, "colors": {"bg": "#050510", "accent": "#0a0a3a", "border": "#4b0082"}, "effects": {"particles": 120, "sparkles": 40, "stripes": True, "grid": True, "glow": 3, "type": "vortex", "intensity": 3}},
        "buraco_branco": {"name": "Buraco Branco", "emoji": "🕳️", "price": 325000, "colors": {"bg": "#0d0d0d", "accent": "#4a4a4a", "border": "#f5f5f5"}, "effects": {"particles": 150, "sparkles": 50, "stripes": True, "grid": True, "glow": 3, "type": "crystal", "intensity": 3}},
        "celestial": {"name": "Celestial", "emoji": "☁️", "price": 350000, "colors": {"bg": "#0a0510", "accent": "#3a1a5a", "border": "#dda0dd"}, "effects": {"particles": 130, "sparkles": 45, "stripes": True, "grid": True, "glow": 3, "type": "aurora", "intensity": 3}},
        "tita": {"name": "Tita", "emoji": "💪", "price": 350000, "colors": {"bg": "#0a0a0a", "accent": "#4a4a4a", "border": "#c0c0c0"}, "effects": {"particles": 150, "sparkles": 50, "stripes": True, "grid": True, "glow": 3}},
        "colossal": {"name": "Colossal", "emoji": "🗿", "price": 350000, "colors": {"bg": "#0a0a0a", "accent": "#4a4a4a", "border": "#808080"}, "effects": {"particles": 150, "sparkles": 50, "stripes": True, "grid": True, "glow": 3}},
        "supernova_v2": {"name": "Supernova II", "emoji": "💥", "price": 350000, "colors": {"bg": "#100505", "accent": "#6a2a1a", "border": "#ff8c00"}, "effects": {"particles": 150, "sparkles": 50, "stripes": True, "grid": True, "glow": 3, "type": "embers", "intensity": 3}},
        "ouro_rosa": {"name": "Ouro Rosa", "emoji": "🌹", "price": 350000, "colors": {"bg": "#0d0508", "accent": "#5a2a3a", "border": "#e8b4b8"}, "effects": {"particles": 150, "sparkles": 50, "stripes": True, "grid": True, "glow": 3, "type": "petals", "intensity": 3}},
        "cosmico_v2": {"name": "Cosmico II", "emoji": "🌌", "price": 400000, "colors": {"bg": "#050510", "accent": "#1a1a5a", "border": "#9370db"}, "effects": {"particles": 150, "sparkles": 50, "stripes": True, "grid": True, "glow": 3, "type": "nebula", "intensity": 3}},
        "divino_v2": {"name": "Divino II", "emoji": "✨", "price": 400000, "colors": {"bg": "#0d0d0d", "accent": "#5a5a5a", "border": "#ffd700"}, "effects": {"particles": 150, "sparkles": 50, "stripes": True, "grid": True, "glow": 3, "type": "crystal", "intensity": 3}},
        "ascendente": {"name": "Ascendente", "emoji": "🌟", "price": 400000, "colors": {"bg": "#0d0d0d", "accent": "#5a5a5a", "border": "#fffacd"}, "effects": {"particles": 150, "sparkles": 50, "stripes": True, "grid": True, "glow": 3, "type": "aurora", "intensity": 3}},
        "estrela_negra": {"name": "Estrela Negra", "emoji": "⭐", "price": 400000, "colors": {"bg": "#050505", "accent": "#1a1a1a", "border": "#4a4a6a"}, "effects": {"particles": 150, "sparkles": 50, "stripes": True, "grid": True, "glow": 3, "type": "vortex", "intensity": 3}},
        "safira_imperial": {"name": "Safira Imperial", "emoji": "👑", "price": 400000, "colors": {"bg": "#050510", "accent": "#0a1a5a", "border": "#0f52ba"}, "effects": {"particles": 150, "sparkles": 50, "stripes": True, "grid": True, "glow": 3, "type": "aurora", "intensity": 3}},
        "esmeralda_colombiana": {"name": "Esmeralda Colombiana", "emoji": "💚", "price": 425000, "colors": {"bg": "#050d05", "accent": "#1a5a2a", "border": "#046307"}, "effects": {"particles": 150, "sparkles": 50, "stripes": True, "grid": True, "glow": 3, "type": "petals", "intensity": 3}},
        "dragao_fogo": {"name": "Dragao de Fogo", "emoji": "🐉", "price": 450000, "colors": {"bg": "#100505", "accent": "#6a1a1a", "border": "#ff4500"}, "effects": {"particles": 150, "sparkles": 50, "stripes": True, "grid": True, "glow": 3, "type": "embers", "intensity": 3}},
        "eterno_v2": {"name": "Eterno II", "emoji": "♾️", "price": 450000, "colors": {"bg": "#0a0a0d", "accent": "#3a3a4a", "border": "#e6e6fa"}, "effects": {"particles": 150, "sparkles": 50, "stripes": True, "grid": True, "glow": 3, "type": "aurora", "intensity": 3}},
        "infinito_v2": {"name": "Infinito II", "emoji": "🔮", "price": 450000, "colors": {"bg": "#0d050d", "accent": "#4a1a4a", "border": "#ff00ff"}, "effects": {"particles": 150, "sparkles": 50, "stripes": True, "grid": True, "glow": 3, "type": "vortex", "intensity": 3}},
        "rubi_birman": {"name": "Rubis Birman", "emoji": "❤️", "price": 450000, "colors": {"bg": "#100505", "accent": "#5a1a1a", "border": "#9b111e"}, "effects": {"particles": 150, "sparkles": 50, "stripes": True, "grid": True, "glow": 3, "type": "embers", "intensity": 3}},
        "supremo": {"name": "Supremo", "emoji": "👑", "price": 500000, "colors": {"bg": "#0d0a05", "accent": "#6a5a1a", "border": "#ffd700"}, "effects": {"particles": 130, "sparkles": 45, "stripes": True, "grid": False, "glow": 3, "type": "nebula", "intensity": 3}},
        "absoluto": {"name": "Absoluto", "emoji": "🌟", "price": 500000, "colors": {"bg": "#0d0d0d", "accent": "#5a5a5a", "border": "#ffffff"}, "effects": {"particles": 150, "sparkles": 50, "stripes": True, "grid": True, "glow": 3, "type": "crystal", "intensity": 3}},
        "ultima": {"name": "Ultima", "emoji": "💫", "price": 500000, "colors": {"bg": "#050510", "accent": "#1a1a5a", "border": "#00ffff"}, "effects": {"particles": 150, "sparkles": 50, "stripes": True, "grid": True, "glow": 3, "type": "neon_pulse", "intensity": 3}},
        "cosmica_infinita": {"name": "Cosmica Infinita", "emoji": "✨", "price": 500000, "colors": {"bg": "#050510", "accent": "#1a1a4a", "border": "#ff00ff"}, "effects": {"particles": 150, "sparkles": 50, "stripes": True, "grid": True, "glow": 3, "type": "nebula", "intensity": 3}},
        "diamante_negro": {"name": "Diamante Negro", "emoji": "💎", "price": 500000, "colors": {"bg": "#050505", "accent": "#1a1a1a", "border": "#4a4a4a"}, "effects": {"particles": 150, "sparkles": 50, "stripes": True, "grid": True, "glow": 3, "type": "crystal", "intensity": 3}},
        "big_crunch": {"name": "Big Crunch", "emoji": "💥", "price": 550000, "colors": {"bg": "#0a0505", "accent": "#3a1a1a", "border": "#ff4444"}, "effects": {"particles": 150, "sparkles": 50, "stripes": True, "grid": True, "glow": 3, "type": "embers", "intensity": 3}},
        "licor_estelar": {"name": "Licor Estelar", "emoji": "🍸", "price": 600000, "colors": {"bg": "#0a0510", "accent": "#3a1a5a", "border": "#ff1493"}, "effects": {"particles": 150, "sparkles": 50, "stripes": True, "grid": True, "glow": 3, "type": "nebula", "intensity": 3}},
    }