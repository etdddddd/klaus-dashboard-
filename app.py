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
    "padrao": {"name": "Padrao", "emoji": "⬜", "price": 0, "colors": {"bg": "#0a0a0a", "accent": "#3a3a3a", "border": "#8a8a8a"}},
    "madeira": {"name": "Madeira", "emoji": "🪵", "price": 500, "colors": {"bg": "#0d0805", "accent": "#6b4423", "border": "#b87333"}},
    "argila": {"name": "Argila", "emoji": "🏺", "price": 500, "colors": {"bg": "#0d0a08", "accent": "#8b5a2b", "border": "#cd853f"}},
    "musgo": {"name": "Musgo", "emoji": "🌿", "price": 500, "colors": {"bg": "#050a05", "accent": "#2d5a27", "border": "#4caf50"}},
    "pedra": {"name": "Pedra", "emoji": "🪨", "price": 750, "colors": {"bg": "#0a0a08", "accent": "#5a5a55", "border": "#8b8b80"}},
    "areia": {"name": "Areia", "emoji": "🏖️", "price": 750, "colors": {"bg": "#0d0c08", "accent": "#8b7355", "border": "#daa520"}},
    "cobre": {"name": "Cobre", "emoji": "🔶", "price": 750, "colors": {"bg": "#0d0805", "accent": "#8b4513", "border": "#cd7f32"}},
    "ferro": {"name": "Ferro", "emoji": "⚙️", "price": 1000, "colors": {"bg": "#080808", "accent": "#5a5a5a", "border": "#a0a0a0"}},
    "carvao": {"name": "Carvao", "emoji": "⬛", "price": 1000, "colors": {"bg": "#050505", "accent": "#3a3a3a", "border": "#5a5a5a"}},
    "turfa": {"name": "Turfa", "emoji": "🟤", "price": 1000, "colors": {"bg": "#0a0805", "accent": "#6b4423", "border": "#8b6914"}},
    "bambu": {"name": "Bambu", "emoji": "🎋", "price": 1500, "colors": {"bg": "#050a05", "accent": "#3a6b27", "border": "#7cfc00"}},
    "cacto": {"name": "Cacto", "emoji": "🌵", "price": 1500, "colors": {"bg": "#050a08", "accent": "#1a7b3a", "border": "#32cd32"}},
    "aloe": {"name": "Aloe", "emoji": "🌱", "price": 1500, "colors": {"bg": "#050a05", "accent": "#2e8b22", "border": "#90ee90"}},
    "mel": {"name": "Mel", "emoji": "🍯", "price": 2000, "colors": {"bg": "#0d0a05", "accent": "#8b6914", "border": "#ffd700"}},
    "cafe": {"name": "Cafe", "emoji": "☕", "price": 2000, "colors": {"bg": "#0d0805", "accent": "#6b3317", "border": "#d2691e"}},
    "cha": {"name": "Cha", "emoji": "🍵", "price": 2000, "colors": {"bg": "#080a05", "accent": "#5a7b2a", "border": "#9acd32"}},
    "bronze": {"name": "Bronze", "emoji": "🟠", "price": 2500, "colors": {"bg": "#0d0a05", "accent": "#8b6a2a", "border": "#cd9b1d"}},
    "latao": {"name": "Latao", "emoji": "🟡", "price": 2500, "colors": {"bg": "#0d0c05", "accent": "#8b7a2a", "border": "#daa520"}},
    "prata": {"name": "Prata", "emoji": "🔘", "price": 3000, "colors": {"bg": "#0a0a0d", "accent": "#7a7a8a", "border": "#c0c0c0"}},
    "platina": {"name": "Platina", "emoji": "⚪", "price": 3000, "colors": {"bg": "#0a0a0a", "accent": "#8a8a8a", "border": "#e5e5e5"}},
    "niquel": {"name": "Niquel", "emoji": "⚙️", "price": 3000, "colors": {"bg": "#0a0a0a", "accent": "#6a6a7a", "border": "#a8a8a8"}},
    "cristal": {"name": "Cristal", "emoji": "💎", "price": 3500, "colors": {"bg": "#0a0a0d", "accent": "#5a5a7a", "border": "#e0e0ff"}},
    "quartzo": {"name": "Quartzo", "emoji": "🔮", "price": 3500, "colors": {"bg": "#0d0a0d", "accent": "#7a5a7a", "border": "#dda0dd"}},
    "ametista_bg": {"name": "Ametista", "emoji": "🟣", "price": 3500, "colors": {"bg": "#0d080d", "accent": "#7a4a8a", "border": "#9932cc"}},
    "jade": {"name": "Jade", "emoji": "🟢", "price": 4000, "colors": {"bg": "#050d08", "accent": "#1a8b5a", "border": "#00fa9a"}},
    "peridot": {"name": "Peridote", "emoji": "🟩", "price": 4000, "colors": {"bg": "#080d05", "accent": "#4a8b2a", "border": "#7fff00"}},
    "aventurina": {"name": "Aventurina", "emoji": "💚", "price": 4000, "colors": {"bg": "#050d08", "accent": "#2a7a3a", "border": "#3cb371"}},
    "topazio": {"name": "Topazio", "emoji": "🟡", "price": 4500, "colors": {"bg": "#0d0c05", "accent": "#8b7a14", "border": "#ffd700"}},
    "citrino": {"name": "Citrino", "emoji": "🟨", "price": 4500, "colors": {"bg": "#0d0c05", "accent": "#8b6a14", "border": "#ffb347"}},
    "ambra": {"name": "Ambra", "emoji": "🟠", "price": 4500, "colors": {"bg": "#0d0a05", "accent": "#8b5a14", "border": "#ff8c00"}},
    "meia_noite": {"name": "Meia-Noite", "emoji": "🌙", "price": 5000, "colors": {"bg": "#050510", "accent": "#1a1a4a", "border": "#6a5acd"}},
    "rubi_bg": {"name": "Rubi", "emoji": "🔴", "price": 5000, "colors": {"bg": "#0d0505", "accent": "#8b1a1a", "border": "#dc143c"}},
    "granada": {"name": "Granada", "emoji": "🟥", "price": 5000, "colors": {"bg": "#0d0505", "accent": "#7a1a1a", "border": "#b22222"}},
    "coral": {"name": "Coral", "emoji": "🪸", "price": 5000, "colors": {"bg": "#0d0808", "accent": "#8b4a4a", "border": "#ff7f50"}},
    "safira_bg": {"name": "Safira", "emoji": "🔵", "price": 6000, "colors": {"bg": "#05050d", "accent": "#1a1a8b", "border": "#4169e1"}},
    "aquamarina": {"name": "Aquamarina", "emoji": "🩵", "price": 6000, "colors": {"bg": "#050d0d", "accent": "#1a7a8b", "border": "#7fffd4"}},
    "turquesa": {"name": "Turquesa", "emoji": "🩵", "price": 7000, "colors": {"bg": "#050d0d", "accent": "#1a8b8b", "border": "#40e0d0"}},
    "opala": {"name": "Opala", "emoji": "🤍", "price": 7000, "colors": {"bg": "#0d0a0d", "accent": "#7a7a8a", "border": "#f0f8ff"}},
    "crimson": {"name": "Crimson", "emoji": "🩸", "price": 8000, "colors": {"bg": "#100505", "accent": "#4a1a1a", "border": "#ff4444"}},
    "floresta": {"name": "Floresta", "emoji": "🌲", "price": 8000, "colors": {"bg": "#050a05", "accent": "#1a4a1a", "border": "#228b22"}},
    "vinho": {"name": "Vinho", "emoji": "🍷", "price": 10000, "colors": {"bg": "#100508", "accent": "#5a1a2a", "border": "#722f37"}},
    "oceano": {"name": "Oceano", "emoji": "🌊", "price": 10000, "colors": {"bg": "#050a10", "accent": "#1a3a5a", "border": "#1e90ff"}},
    "por_do_sol": {"name": "Por do Sol", "emoji": "🌅", "price": 12000, "colors": {"bg": "#100805", "accent": "#5a3a1a", "border": "#ff6347"}},
    "chocolate": {"name": "Chocolate", "emoji": "🍫", "price": 12000, "colors": {"bg": "#0d0805", "accent": "#6b3317", "border": "#8b4513"}},
    "caramelo": {"name": "Caramelo", "emoji": "🍮", "price": 12000, "colors": {"bg": "#0d0a05", "accent": "#7b5423", "border": "#daa520"}},
    "royal": {"name": "Royal", "emoji": "👑", "price": 15000, "colors": {"bg": "#0a050d", "accent": "#3a1a5a", "border": "#9400d3"}},
    "imperial": {"name": "Imperial", "emoji": "🥇", "price": 15000, "colors": {"bg": "#0d0a05", "accent": "#6a5a1a", "border": "#ffd700"}},
    "samurai": {"name": "Samurai", "emoji": "⚔️", "price": 15000, "colors": {"bg": "#0d0505", "accent": "#5a1a1a", "border": "#b22222"}},
    "neon": {"name": "Neon", "emoji": "💡", "price": 20000, "colors": {"bg": "#050510", "accent": "#1a1a4a", "border": "#00ff00"}},
    "ninja": {"name": "Ninja", "emoji": "🥷", "price": 20000, "colors": {"bg": "#050505", "accent": "#2a2a2a", "border": "#ff4444"}},
    "viking": {"name": "Viking", "emoji": "🪓", "price": 20000, "colors": {"bg": "#0a0a0d", "accent": "#2a2a4a", "border": "#c0c0c0"}},
    "galaxia": {"name": "Galaxia", "emoji": "🌌", "price": 25000, "colors": {"bg": "#050510", "accent": "#1a1a5a", "border": "#7b68ee"}},
    "estrela": {"name": "Estrela", "emoji": "⭐", "price": 25000, "colors": {"bg": "#0d0d0d", "accent": "#4a4a4a", "border": "#ffd700"}},
    "lua": {"name": "Lua", "emoji": "🌙", "price": 25000, "colors": {"bg": "#0a0a0d", "accent": "#3a3a4a", "border": "#f0f0f0"}},
    "sakura": {"name": "Sakura", "emoji": "🌸", "price": 30000, "colors": {"bg": "#0d0508", "accent": "#5a1a2a", "border": "#ffb7c5"}},
    "artico": {"name": "Artico", "emoji": "❄️", "price": 30000, "colors": {"bg": "#050a0d", "accent": "#1a4a5a", "border": "#b0e0e6"}},
    "esmeralda": {"name": "Esmeralda", "emoji": "💎", "price": 30000, "colors": {"bg": "#050d08", "accent": "#1a5a2a", "border": "#50c878"}},
    "tropical": {"name": "Tropical", "emoji": "🌴", "price": 30000, "colors": {"bg": "#050d05", "accent": "#1a5a1a", "border": "#00fa9a"}},
    "primavera": {"name": "Primavera", "emoji": "🌷", "price": 30000, "colors": {"bg": "#0d0508", "accent": "#5a1a3a", "border": "#ff69b4"}},
    "fantasma": {"name": "Fantasma", "emoji": "👻", "price": 35000, "colors": {"bg": "#0a0a0d", "accent": "#3a3a4a", "border": "#e0e0ff"}},
    "obsidiana": {"name": "Obsidiana", "emoji": "🖤", "price": 35000, "colors": {"bg": "#050505", "accent": "#2a2a2a", "border": "#5a5a5a"}},
    "neve_sakura": {"name": "Neve Sakura", "emoji": "🌺", "price": 35000, "colors": {"bg": "#0d080a", "accent": "#5a2a3a", "border": "#ffc0cb"}},
    "outono": {"name": "Outono", "emoji": "🍂", "price": 35000, "colors": {"bg": "#0d0a05", "accent": "#6a4a1a", "border": "#ff8c00"}},
    "cripta": {"name": "Cripta", "emoji": "⚰️", "price": 35000, "colors": {"bg": "#0a0a0a", "accent": "#3a3a3a", "border": "#696969"}},
    "oceano_profundo": {"name": "Oceano Profundo", "emoji": "🐋", "price": 40000, "colors": {"bg": "#050510", "accent": "#0a1a4a", "border": "#0000cd"}},
    "luz_estrelas": {"name": "Luz das Estrelas", "emoji": "✨", "price": 40000, "colors": {"bg": "#0a050d", "accent": "#3a1a4a", "border": "#e6e6fa"}},
    "neon_rosa": {"name": "Neon Rosa", "emoji": "💗", "price": 40000, "colors": {"bg": "#0d050a", "accent": "#4a1a2a", "border": "#ff1493"}},
    "inverno": {"name": "Inverno", "emoji": "☃️", "price": 40000, "colors": {"bg": "#050a0d", "accent": "#1a3a4a", "border": "#add8e6"}},
    "verao": {"name": "Verao", "emoji": "☀️", "price": 40000, "colors": {"bg": "#0d0d05", "accent": "#5a5a1a", "border": "#ffd700"}},
    "aurora": {"name": "Aurora", "emoji": "🌈", "price": 45000, "colors": {"bg": "#050a0d", "accent": "#1a4a4a", "border": "#00ffff"}},
    "borboleta": {"name": "Borboleta", "emoji": "🦋", "price": 45000, "colors": {"bg": "#0d050a", "accent": "#4a1a3a", "border": "#da70d6"}},
    "gravitacional": {"name": "Gravitacional", "emoji": "🌀", "price": 45000, "colors": {"bg": "#050510", "accent": "#1a1a5a", "border": "#4169e1"}},
    "relampago": {"name": "Relampago", "emoji": "⚡", "price": 45000, "colors": {"bg": "#0d0d05", "accent": "#5a5a1a", "border": "#ffff00"}},
    "cosmico": {"name": "Cosmico", "emoji": "💫", "price": 50000, "colors": {"bg": "#050510", "accent": "#1a1a5a", "border": "#9370db"}},
    "dourado": {"name": "Dourado", "emoji": "🏆", "price": 50000, "colors": {"bg": "#0d0a05", "accent": "#6a5a1a", "border": "#ffd700"}},
    "fenix": {"name": "Fenix", "emoji": "🔥", "price": 50000, "colors": {"bg": "#100505", "accent": "#5a1a1a", "border": "#ff4500"}},
    "trovao": {"name": "Trovao", "emoji": "🌩️", "price": 50000, "colors": {"bg": "#0a0a0d", "accent": "#2a2a5a", "border": "#9370db"}},
    "vulcanico": {"name": "Vulcanico", "emoji": "🌋", "price": 55000, "colors": {"bg": "#100505", "accent": "#5a1a1a", "border": "#ff6600"}},
    "roxo_real": {"name": "Roxo Real", "emoji": "🟣", "price": 55000, "colors": {"bg": "#0a050d", "accent": "#3a1a5a", "border": "#8a2be2"}},
    "terremoto": {"name": "Terremoto", "emoji": "🏚️", "price": 55000, "colors": {"bg": "#0d0a08", "accent": "#5a4a2a", "border": "#a0522d"}},
    "lava": {"name": "Lava", "emoji": "🔴", "price": 60000, "colors": {"bg": "#100505", "accent": "#6a1a1a", "border": "#ff0000"}},
    "toxico": {"name": "Toxico", "emoji": "☢️", "price": 60000, "colors": {"bg": "#050d05", "accent": "#1a5a1a", "border": "#00ff00"}},
    "tempestade_gelo": {"name": "Tempestade de Gelo", "emoji": "🧊", "price": 60000, "colors": {"bg": "#050a0d", "accent": "#1a4a5a", "border": "#b0e0e6"}},
    "metal": {"name": "Metal", "emoji": "🔩", "price": 60000, "colors": {"bg": "#0a0a0a", "accent": "#4a4a4a", "border": "#c0c0c0"}},
    "neon_v2": {"name": "Neon II", "emoji": "💜", "price": 60000, "colors": {"bg": "#050510", "accent": "#1a1a5a", "border": "#ff00ff"}},
    "lua_sangue": {"name": "Lua de Sangue", "emoji": "🌑", "price": 70000, "colors": {"bg": "#100505", "accent": "#4a1a1a", "border": "#8b0000"}},
    "abismo": {"name": "Abismo", "emoji": "🕳️", "price": 70000, "colors": {"bg": "#050505", "accent": "#0f0f1a", "border": "#3a3a5f"}},
    "eclipse": {"name": "Eclipse", "emoji": "🌑", "price": 70000, "colors": {"bg": "#0a0a0a", "accent": "#2a2a2a", "border": "#5a5a7a"}},
    "diamante": {"name": "Diamante", "emoji": "💎", "price": 75000, "colors": {"bg": "#0a0a0d", "accent": "#4a4a6a", "border": "#b9f2ff"}},
    "matrix": {"name": "Matrix", "emoji": "🔢", "price": 75000, "colors": {"bg": "#050d05", "accent": "#0a4a0a", "border": "#00ff00"}},
    "cyberpunk": {"name": "Cyberpunk", "emoji": "🤖", "price": 80000, "colors": {"bg": "#0d050d", "accent": "#4a1a3a", "border": "#ff00ff"}},
    "holograma": {"name": "Holograma", "emoji": "📱", "price": 80000, "colors": {"bg": "#0a0a0d", "accent": "#3a3a4a", "border": "#00ffff"}},
    "cyborg": {"name": "Cyborg", "emoji": "🦾", "price": 80000, "colors": {"bg": "#0a0a0a", "accent": "#4a4a5a", "border": "#4682b4"}},
    "digital": {"name": "Digital", "emoji": "💻", "price": 80000, "colors": {"bg": "#050510", "accent": "#1a1a4a", "border": "#00ff00"}},
    "nanotech": {"name": "Nanotech", "emoji": "🔬", "price": 90000, "colors": {"bg": "#0a0a0d", "accent": "#3a3a4a", "border": "#00bfff"}},
    "quantico": {"name": "Quantico", "emoji": "⚛️", "price": 90000, "colors": {"bg": "#050510", "accent": "#1a1a5a", "border": "#9370db"}},
    "sonico": {"name": "Sonico", "emoji": "🔊", "price": 90000, "colors": {"bg": "#0a050d", "accent": "#3a1a4a", "border": "#ff1493"}},
    "dragao": {"name": "Dragao", "emoji": "🐉", "price": 100000, "colors": {"bg": "#100505", "accent": "#5a1a1a", "border": "#ff4500"}},
    "hydra": {"name": "Hidra", "emoji": "🐍", "price": 100000, "colors": {"bg": "#050d05", "accent": "#1a5a1a", "border": "#228b22"}},
    "poseidon": {"name": "Poseidon", "emoji": "🔱", "price": 100000, "colors": {"bg": "#050510", "accent": "#1a1a5a", "border": "#1e90ff"}},
    "vazio": {"name": "Vazio", "emoji": "🕳️", "price": 120000, "colors": {"bg": "#050505", "accent": "#0f0f0f", "border": "#4a4a4a"}},
    "hades": {"name": "Hades", "emoji": "💀", "price": 120000, "colors": {"bg": "#0a0505", "accent": "#3a1a1a", "border": "#8b0000"}},
    "zeus": {"name": "Zeus", "emoji": "⚡", "price": 120000, "colors": {"bg": "#0d0d05", "accent": "#5a5a1a", "border": "#ffd700"}},
    "reliquia": {"name": "Reliquia", "emoji": "🏺", "price": 120000, "colors": {"bg": "#0d0a05", "accent": "#6a5a1a", "border": "#daa520"}},
    "arco_iris": {"name": "Arco-Iris", "emoji": "🌈", "price": 150000, "colors": {"bg": "#0a0a0d", "accent": "#3a3a4a", "border": "#ff00ff"}},
    "cometa": {"name": "Cometa", "emoji": "☄️", "price": 150000, "colors": {"bg": "#0a050d", "accent": "#3a1a4a", "border": "#ffa500"}},
    "athena": {"name": "Athena", "emoji": "🦉", "price": 150000, "colors": {"bg": "#0a0a0d", "accent": "#3a3a4a", "border": "#c0c0c0"}},
    "egipcio": {"name": "Egipcio", "emoji": "🏛️", "price": 150000, "colors": {"bg": "#0d0a05", "accent": "#6a5a1a", "border": "#ffd700"}},
    "supernova": {"name": "Supernova", "emoji": "💥", "price": 200000, "colors": {"bg": "#100505", "accent": "#6a1a1a", "border": "#ff6600"}},
    "buraco_negro": {"name": "Buraco Negro", "emoji": "🕳️", "price": 200000, "colors": {"bg": "#050505", "accent": "#0a0a0a", "border": "#5a0080"}},
    "big_bang": {"name": "Big Bang", "emoji": "💫", "price": 200000, "colors": {"bg": "#0d0505", "accent": "#5a1a1a", "border": "#ff0000"}},
    "pixel": {"name": "Pixel", "emoji": "🎮", "price": 200000, "colors": {"bg": "#050510", "accent": "#1a1a4a", "border": "#00ff00"}},
    "japones": {"name": "Japones", "emoji": "⛩️", "price": 200000, "colors": {"bg": "#0d0505", "accent": "#5a1a1a", "border": "#ff0000"}},
    "divino": {"name": "Divino", "emoji": "👼", "price": 250000, "colors": {"bg": "#0d0d0d", "accent": "#5a5a5a", "border": "#ffd700"}},
    "eterno": {"name": "Eterno", "emoji": "♾️", "price": 250000, "colors": {"bg": "#0a0a0d", "accent": "#3a3a4a", "border": "#e6e6fa"}},
    "infinito": {"name": "Infinito", "emoji": "🔮", "price": 250000, "colors": {"bg": "#0d050d", "accent": "#4a1a4a", "border": "#ff00ff"}},
    "tempestade": {"name": "Tempestade", "emoji": "⛈️", "price": 250000, "colors": {"bg": "#0a0a0d", "accent": "#3a3a5a", "border": "#4169e1"}},
    "mitico": {"name": "Mitico", "emoji": "⚜️", "price": 300000, "colors": {"bg": "#0d0a05", "accent": "#6a5a1a", "border": "#ffd700"}},
    "lendario": {"name": "Lendario", "emoji": "🏆", "price": 300000, "colors": {"bg": "#0d0d0d", "accent": "#5a5a5a", "border": "#ffd700"}},
    "ascensao": {"name": "Ascensao", "emoji": "🕊️", "price": 300000, "colors": {"bg": "#0d0d0d", "accent": "#5a5a5a", "border": "#f0f8ff"}},
    "tita": {"name": "Tita", "emoji": "💪", "price": 350000, "colors": {"bg": "#0a0a0a", "accent": "#4a4a4a", "border": "#c0c0c0"}},
    "colossal": {"name": "Colossal", "emoji": "🗿", "price": 350000, "colors": {"bg": "#0a0a0a", "accent": "#4a4a4a", "border": "#808080"}},
    "cosmico_v2": {"name": "Cosmico II", "emoji": "🌌", "price": 400000, "colors": {"bg": "#050510", "accent": "#1a1a5a", "border": "#9370db"}},
    "divino_v2": {"name": "Divino II", "emoji": "✨", "price": 400000, "colors": {"bg": "#0d0d0d", "accent": "#5a5a5a", "border": "#ffd700"}},
    "ascendente": {"name": "Ascendente", "emoji": "🌟", "price": 400000, "colors": {"bg": "#0d0d0d", "accent": "#5a5a5a", "border": "#fffacd"}},
    "eterno_v2": {"name": "Eterno II", "emoji": "♾️", "price": 450000, "colors": {"bg": "#0a0a0d", "accent": "#3a3a4a", "border": "#e6e6fa"}},
    "infinito_v2": {"name": "Infinito II", "emoji": "🔮", "price": 450000, "colors": {"bg": "#0d050d", "accent": "#4a1a4a", "border": "#ff00ff"}},
    "supremo": {"name": "Supremo", "emoji": "👑", "price": 500000, "colors": {"bg": "#0d0a05", "accent": "#6a5a1a", "border": "#ffd700"}},
    "absoluto": {"name": "Absoluto", "emoji": "🌟", "price": 500000, "colors": {"bg": "#0d0d0d", "accent": "#5a5a5a", "border": "#ffffff"}},
    "ultima": {"name": "Ultima", "emoji": "💫", "price": 500000, "colors": {"bg": "#050510", "accent": "#1a1a5a", "border": "#00ffff"}},
}

PROFILE_BORDERS = {
    "default": {"name": "Padrão", "emoji": "⬜", "price": 0, "color": "#d946ef"},
    "gold": {"name": "Dourado", "emoji": "🥇", "price": 10000, "color": "#ffd700"},
    "diamond": {"name": "Diamante", "emoji": "💎", "price": 20000, "color": "#22d3ee"},
    "ruby": {"name": "Rubi", "emoji": "❤️", "price": 15000, "color": "#ef4444"},
    "emerald": {"name": "Esmeralda", "emoji": "💚", "price": 15000, "color": "#22c55e"},
    "sapphire": {"name": "Safira", "emoji": "💙", "price": 15000, "color": "#3b82f6"},
    "amethyst": {"name": "Ametista", "emoji": "💜", "price": 20000, "color": "#a855f7"},
    "rainbow": {"name": "Arco-Íris", "emoji": "🌈", "price": 50000, "color": "#f59e0b"},
    "fire": {"name": "Fogo", "emoji": "🔥", "price": 30000, "color": "#f97316"},
    "ice": {"name": "Gelo", "emoji": "❄️", "price": 30000, "color": "#7dd3fc"},
    "galaxy": {"name": "Galáxia", "emoji": "🌌", "price": 40000, "color": "#c084fc"},
    "shadow": {"name": "Shadow", "emoji": "🖤", "price": 60000, "color": "#525252"},
    "neon_pink": {"name": "Neon Rosa", "emoji": "💗", "price": 25000, "color": "#f472b6"},
    "neon_cyan": {"name": "Neon Cyan", "emoji": "🩵", "price": 25000, "color": "#22d3ee"},
    "cherry": {"name": "Cereja", "emoji": "🍒", "price": 20000, "color": "#e11d48"},
    "blood": {"name": "Sangue", "emoji": "🩸", "price": 35000, "color": "#991b1b"},
    "platinum": {"name": "Platina", "emoji": "⚪", "price": 45000, "color": "#e2e8f0"},
    "obsidian": {"name": "Obsidiana", "emoji": "🖤", "price": 30000, "color": "#18181b"},
    "neon_green": {"name": "Neon Verde", "emoji": "💚", "price": 25000, "color": "#4ade80"},
    "neon_yellow": {"name": "Neon Amarelo", "emoji": "💛", "price": 25000, "color": "#facc15"},
    "chrome": {"name": "Cromado", "emoji": "🪞", "price": 50000, "color": "#d4d4d8"},
    "sakura": {"name": "Sakura", "emoji": "🌸", "price": 20000, "color": "#ec4899"},
    "ocean": {"name": "Oceano", "emoji": "🌊", "price": 20000, "color": "#0ea5e9"},
    "toxic": {"name": "Tóxico", "emoji": "☢️", "price": 40000, "color": "#a3e635"},
    "royal": {"name": "Real", "emoji": "👑", "price": 35000, "color": "#facc15"},
    "dragon": {"name": "Dragão", "emoji": "🐉", "price": 55000, "color": "#f97316"},
    "void": {"name": "Vazio", "emoji": "🕳️", "price": 70000, "color": "#09090b"},
    "cosmic": {"name": "Cósmico", "emoji": "🪐", "price": 45000, "color": "#c084fc"},
}


@app.route("/api/profile_config/<user_id>")
def api_profile_config(user_id: str) -> Any:
    try:
        db_conn = get_db()
        doc = db_conn["usuarios"].find_one({"discord_id": int(user_id)})
        if not doc:
            return jsonify({"error": "user not found"}), 404
        av = doc.get("avatar", "")
        avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{av}.png?size=256" if av else f"https://cdn.discordapp.com/embed/avatars/{int(user_id) % 6}.png"
        return jsonify({
            "discord_id": str(doc.get("discord_id", "")),
            "username": doc.get("username", f"User#{user_id[-4:]}"),
            "global_name": doc.get("global_name", ""),
            "avatar_url": avatar_url,
            "koins": doc.get("koins", 0),
            "wins": doc.get("wins", 0),
            "losses": doc.get("losses", 0),
            "commands_used": doc.get("commands_used", 0),
            "daily_streak": doc.get("daily_streak", 0),
            "achievements": len(doc.get("achievements", [])),
            "background": doc.get("profile_background", "padrao"),
            "border": doc.get("profile_border", "default"),
            "purchased_backgrounds": doc.get("purchased_backgrounds", ["padrao"]),
            "purchased_borders": doc.get("purchased_borders", ["default"]),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/profile_config/<user_id>/set", methods=["POST"])
def api_profile_config_set(user_id: str) -> Any:
    try:
        data = request.get_json()
        db_conn = get_db()
        update = {}
        if "background" in data:
            update["profile_background"] = data["background"]
        if "border" in data:
            update["profile_border"] = data["border"]
        if update:
            db_conn["usuarios"].update_one(
                {"discord_id": int(user_id)},
                {"$set": update},
                upsert=True,
            )
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/profile_buy", methods=["POST"])
def api_profile_buy() -> Any:
    try:
        data = request.get_json()
        user_id = data.get("user_id")
        item_type = data.get("type")
        item_key = data.get("key")
        if not user_id or not item_type or not item_key:
            return jsonify({"error": "missing params"}), 400

        items = PROFILE_BACKGROUNDS if item_type == "backgrounds" else PROFILE_BORDERS
        item = items.get(item_key)
        if not item:
            return jsonify({"error": "item not found"}), 404

        db_conn = get_db()
        doc = db_conn["usuarios"].find_one({"discord_id": int(user_id)})
        if not doc:
            return jsonify({"error": "user not found"}), 404

        koins = doc.get("koins", 0)
        purchased_field = f"purchased_{item_type}"
        purchased = doc.get(purchased_field, [])

        if item_key in purchased:
            return jsonify({"error": "already owned"}), 400

        if koins < item["price"]:
            return jsonify({"error": "insufficient koins", "needed": item["price"], "have": koins}), 400

        db_conn["usuarios"].update_one(
            {"discord_id": int(user_id)},
            {
                "$inc": {"koins": -item["price"]},
                "$push": {purchased_field: item_key},
            },
            upsert=True,
        )
        return jsonify({"ok": True, "new_koins": koins - item["price"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/profile_image/<user_id>")
def api_profile_image(user_id: str) -> Any:
    try:
        db_conn = get_db()
        doc = db_conn["usuarios"].find_one({"discord_id": int(user_id)})
        if not doc:
            return jsonify({"error": "user not found"}), 404
        img_b64 = doc.get("profile_image_b64")
        if not img_b64:
            return jsonify({"error": "no image cached"}), 404
        import base64
        img_bytes = base64.b64decode(img_b64)
        from flask import Response
        return Response(img_bytes, mimetype="image/png", headers={"Cache-Control": "public, max-age=300"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/profile")
@login_required
def profile_page(user: dict) -> str:
    return render_template("profile.html", user=user, backgrounds=PROFILE_BACKGROUNDS, borders=PROFILE_BORDERS)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
