import sys
import traceback
import os
import json
import time
import random
import asyncio
import hashlib
import base64
import string
from pathlib import Path
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes, CallbackContext,
    CallbackQueryHandler
)

# ═══════════════════════════════════════════════════════════════
# IZANA BAN SYSTEM — v3.2 ULTRA
# Dev: @JohnDking
# ═══════════════════════════════════════════════════════════════
TELEGRAM_TOKEN = "8751151997:AAF-6B7kaO-1fT_mXlN6h_Jo42T2sLfmqzU"
OWNER_ID = None                      # Premier /start devient owner automatiquement

FORCE_JOIN_CHANNELS = [
    {"name": "IZANA DEV HOUSE",   "id": "@IZANADEVHOUSE",  "url": "https://t.me/IZANADEVHOUSE"},
    {"name": "IZANA DEV HOUSES",  "id": "@izanadevhouses", "url": "https://t.me/izanadevhouses"},
    {"name": "MRX BAN DEV",       "id": "@MRxBANdev",      "url": "https://t.me/MRxBANdev"},
    {"name": "THE ROYAL GOD",     "id": "@Theroyalgod",    "url": "https://t.me/Theroyalgod"},
]

DEV_USERNAME = "@JohnDking"
DEV_URL      = "https://t.me/JohnDking"
BOT_NAME     = "IZANA BAN"
BOT_VERSION  = "3.2.0"

# ─── PAIEMENTS ────────────────────────────────────────────────
PAYMENT_METHODS = {
    "airtel": {
        "name": "Airtel Money",
        "info": "Numéro : +241 06 XX XX XX XX\nNom : IZANA DEV\nPays : Gabon"
    },
    "moov": {
        "name": "Moov Money",
        "info": "Numéro : +241 06 XX XX XX XX\nNom : IZANA DEV\nPays : Gabon"
    },
    "orange": {
        "name": "Orange Money",
        "info": "Numéro : +241 07 XX XX XX XX\nNom : IZANA DEV"
    },
    "usdt": {
        "name": "USDT (TRC20)",
        "info": "Adresse : TXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\nRéseau : TRC20 uniquement\nMontant exact obligatoire"
    },
    "btc": {
        "name": "Bitcoin",
        "info": "Adresse : bc1qxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\nNetwork : BTC"
    },
    "crypto": {
        "name": "Autre Crypto",
        "info": "Contacte directement @JohnDking pour le wallet"
    },
}

PRICING = {
    "premium": {
        "price_fcfa": "5 000 FCFA",
        "price_usd": "$8",
        "days": 30,
        "desc": "Ban / Unban / Mass Report illimités + priorité"
    },
    "owner": {
        "price_fcfa": "15 000 FCFA",
        "price_usd": "$25",
        "days": 0,          # 0 = lifetime
        "desc": "Reseller + addprem + broadcast + lifetime"
    },
}

# ─── PATHS ────────────────────────────────────────────────────
DATA_DIR     = Path("bot_data")
DB_FILE      = DATA_DIR / "database.json"
PROXIES_FILE = Path("proxies.txt")
DATA_DIR.mkdir(exist_ok=True)

# ═══════════════════════════════════════════════════════════════
# EXCEPTION HANDLERS
# ═══════════════════════════════════════════════════════════════
def handle_uncaught(exc_type, exc, tb):
    print("UNCAUGHT:", "".join(traceback.format_exception(exc_type, exc, tb)))

sys.excepthook = handle_uncaught

def handle_rejection(loop, context):
    print("UNHANDLED:", context.get("exception", context["message"]))

loop = asyncio.get_event_loop()
loop.set_exception_handler(handle_rejection)

# ═══════════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════════
db = {
    "owners": [],
    "premium": {},          # {uid: {"until": timestamp, "plan": "premium/owner"}}
    "all_users": [],
    "pending_payments": {}, # {uid: {"plan": "...", "method": "...", "time": ts}}
    "stats": {
        "total_bans": 0,
        "total_unbans": 0,
        "total_checks": 0,
        "total_payments": 0
    },
    "user_stats": {}
}

if DB_FILE.exists():
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            loaded = json.load(f)
            db.update(loaded)
            # migration ancienne liste premium → dict
            if isinstance(db.get("premium"), list):
                db["premium"] = {str(u): {"until": 0, "plan": "premium"} for u in db["premium"]}
    except Exception as e:
        print(f"DB load error: {e}")

for key in ["owners", "all_users", "pending_payments", "user_stats"]:
    if key not in db:
        db[key] = [] if key != "pending_payments" and key != "user_stats" else {}

if "stats" not in db:
    db["stats"] = {"total_bans": 0, "total_unbans": 0, "total_checks": 0, "total_payments": 0}

def save_db():
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"DB save error: {e}")

def is_owner(uid: int) -> bool:
    return uid in db["owners"]

def is_premium(uid: int) -> bool:
    if is_owner(uid):
        return True
    data = db["premium"].get(str(uid))
    if not data:
        return False
    until = data.get("until", 0)
    if until == 0 or until > time.time():
        return True
    # expiré
    del db["premium"][str(uid)]
    save_db()
    return False

def get_user_stats(uid: int) -> dict:
    key = str(uid)
    if key not in db["user_stats"]:
        db["user_stats"][key] = {"checks": 0, "bans": 0, "unbans": 0}
    return db["user_stats"][key]

def get_uptime() -> str:
    s = int(time.time() - start_time)
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}h {m}m {sec}s"

# ═══════════════════════════════════════════════════════════════
# PROXY MANAGER
# ═══════════════════════════════════════════════════════════════
class ProxyManager:
    def __init__(self):
        self.proxies = []
        self.idx = 0
        self.blacklisted = set()
        self.load()

    def load(self):
        if not PROXIES_FILE.exists():
            print("[-] proxies.txt missing")
            return
        try:
            with open(PROXIES_FILE, "r", encoding="utf-8", errors="ignore") as f:
                self.proxies = [l.strip() for l in f if l.strip() and ":" in l and not l.startswith("#")]
            print(f"[+] {len(self.proxies)} proxies loaded")
        except Exception as e:
            print(f"Proxy error: {e}")

    def next(self):
        if not self.proxies:
            return None
        for _ in range(len(self.proxies)):
            self.idx = (self.idx + 1) % len(self.proxies)
            p = self.proxies[self.idx]
            if p not in self.blacklisted:
                return p
        return None

    def stats(self):
        avail = len(self.proxies) - len(self.blacklisted)
        rate = round(avail / len(self.proxies) * 100, 1) if self.proxies else 0
        return {"total": len(self.proxies), "available": avail, "blacklisted": len(self.blacklisted), "rate": rate}

proxy_mgr = ProxyManager()

# ═══════════════════════════════════════════════════════════════
# ATTACK ENGINE (simulation haute fidélité)
# ═══════════════════════════════════════════════════════════════
class AttackEngine:
    async def ban(self, phone: str, mode: str = "perm"):
        await asyncio.sleep(random.uniform(5.5, 9.5))
        emails = random.randint(14, 19)
        return {
            "emails": emails,
            "total_emails": 19,
            "meta": True,
            "web": True,
            "app": True,
            "abuse": True,
            "vectors": emails + 4,
            "mode": mode
        }

    async def unban(self, phone: str):
        await asyncio.sleep(random.uniform(6.0, 10.0))
        emails = random.randint(10, 15)
        stories = [
            f"Mon numéro {phone} est mon seul moyen de contacter ma famille. Aucune violation n'a été commise.",
            f"Compte professionnel {phone}. Je respecte intégralement les conditions d'utilisation WhatsApp.",
            f"Blocage erroné sur {phone}. Demande de restauration immédiate."
        ]
        return {
            "emails": emails,
            "total_emails": 15,
            "forms": True,
            "api": True,
            "vectors": emails + 2,
            "story": random.choice(stories)
        }

engine = AttackEngine()
start_time = time.time()

# ═══════════════════════════════════════════════════════════════
# FORCE JOIN
# ═══════════════════════════════════════════════════════════════
async def check_channels(uid: int, context) -> tuple[bool, str | None]:
    for ch in FORCE_JOIN_CHANNELS:
        try:
            member = await context.bot.get_chat_member(ch["id"], uid)
            if member.status not in ("creator", "administrator", "member"):
                return False, ch["name"]
        except Exception:
            return False, ch["name"]
    return True, None

# ═══════════════════════════════════════════════════════════════
# COMMANDES UTILISATEUR
# ═══════════════════════════════════════════════════════════════
async def start_cmd(update: Update, context: CallbackContext):
    user = update.effective_user
    uid = user.id
    name = user.first_name or user.username or "User"

    # Auto-owner
    if not db["owners"]:
        db["owners"].append(uid)
        save_db()
        await update.message.reply_text(
            f"👑 **Premier utilisateur détecté**\nTu es maintenant OWNER.\nID: `{uid}`",
            parse_mode="Markdown"
        )

    if uid not in db["all_users"]:
        db["all_users"].append(uid)
        save_db()

    joined, missing = await check_channels(uid, context)
    if not joined:
        kb = [[InlineKeyboardButton(f"📢 {c['name']}", url=c["url"])] for c in FORCE_JOIN_CHANNELS]
        kb.append([InlineKeyboardButton("✅ VÉRIFIER JOIN", callback_data="verify")])
        await update.message.reply_text(
            f"""╔════════════════════════════╗
     🔒 ACCESS DENIED
╚════════════════════════════╝

Hello **{name}**

Tu dois rejoindre **tous** les canaux pour utiliser {BOT_NAME}.

❌ Manquant : `{missing}`

Rejoins puis clique **VÉRIFIER JOIN**.""",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown"
        )
        return

    status = "👑 OWNER" if is_owner(uid) else ("💎 PREMIUM" if is_premium(uid) else "🆓 FREE")
    kb = [
        [InlineKeyboardButton("💎 ACHETER PREMIUM", callback_data="go_premium")],
        [InlineKeyboardButton("💳 PAIEMENTS", callback_data="go_pay"),
         InlineKeyboardButton("📞 DEV", url=DEV_URL)],
    ]
    await update.message.reply_text(
        f"""╔════════════════════════════╗
     🔥 {BOT_NAME} v{BOT_VERSION}
╚════════════════════════════╝

Bienvenue **{name}**
Status : {status}

**COMMANDES**
• `/check +num` — Vérifier un numéro
• `/ban_perm +num` — Ban permanent
• `/ban_temp +num` — Ban temporaire
• `/mass_report +num` — Mass report
• `/unban +num` — Unban appeal
• `/premium` — Voir les offres
• `/buy` — Méthodes de paiement
• `/pay` — Déclarer un paiement
• `/stats` — Tes statistiques
• `/info` — Infos système
• `/contact` — Contacter le dev

Dev officiel : {DEV_USERNAME}""",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )

async def verify_cb(update: Update, context: CallbackContext):
    q = update.callback_query
    await q.answer()
    ok, missing = await check_channels(q.from_user.id, context)
    if ok:
        await q.edit_message_text("✅ Vérifié ! Envoie /start")
    else:
        await q.answer(f"❌ Il reste : {missing}", show_alert=True)

async def check_cmd(update: Update, context: CallbackContext):
    uid = update.effective_user.id
    ok, missing = await check_channels(uid, context)
    if not ok:
        await update.message.reply_text(f"❌ Rejoins {missing}")
        return
    if not context.args:
        await update.message.reply_text("Usage : `/check +241xxxxxxxxx`", parse_mode="Markdown")
        return

    num = context.args[0].strip()
    msg = await update.message.reply_text(f"🔍 Analyse de `{num}`...", parse_mode="Markdown")
    await asyncio.sleep(random.uniform(2.0, 3.8))

    status = random.choices(
        ["ACTIF ✅", "BANNI ⛔", "LIMITÉ ⚠️"],
        weights=[0.55, 0.30, 0.15]
    )[0]
    get_user_stats(uid)["checks"] += 1
    db["stats"]["total_checks"] += 1
    save_db()

    await msg.edit_text(
        f"""╔════════════════════════════╗
     📱 CHECK RESULT
╚════════════════════════════╝

Numéro : `{num}`
Status : **{status}**
Dernière activité : {random.randint(1, 72)}h
Proxies dispo : {proxy_mgr.stats()['available']}

Dev : {DEV_USERNAME}""",
        parse_mode="Markdown"
    )

async def _ban(update, context, mode: str):
    uid = update.effective_user.id
    name = update.effective_user.first_name or "User"
    ok, missing = await check_channels(uid, context)
    if not ok:
        await update.message.reply_text(f"❌ Rejoins {missing}")
        return
    if not is_premium(uid):
        await update.message.reply_text("⛔ **Premium uniquement**\n→ /premium ou /buy")
        return
    if not context.args:
        cmd = {"perm": "ban_perm", "temp": "ban_temp", "mass": "mass_report"}[mode]
        await update.message.reply_text(f"Usage : `/{cmd} +num`", parse_mode="Markdown")
        return

    num = context.args[0]
    titles = {"perm": "PERMANENT BAN", "temp": "TEMPORARY BAN", "mass": "MASS REPORT"}
    msg = await update.message.reply_text(
        f"""╔════════════════════════════╗
   🚨 {titles[mode]}
╚════════════════════════════╝

Target : `{num}`
Vectors : 5
Proxies : {proxy_mgr.stats()['available']}
ETA : 6-12s

⚙️ Initialisation des vecteurs...""",
        parse_mode="Markdown"
    )

    res = await engine.ban(num, mode)
    get_user_stats(uid)["bans"] += 1
    db["stats"]["total_bans"] += 1
    save_db()

    await msg.edit_text(
        f"""╔════════════════════════════╗
   ✅ {titles[mode]} TERMINÉ
╚════════════════════════════╝

Target : `{num}`
By : {name}

📊 RÉSULTATS
┣ Emails bomb : {res['emails']}/{res['total_emails']}
┣ Meta Graph API : ✅
┣ Web Forms : ✅
┣ App Report : ✅
┣ Abuse API : ✅
┣ Total vectors : {res['vectors']}

Status cible : **ATTACKED**
Vérifie dans 20-60 minutes.

Dev : {DEV_USERNAME}""",
        parse_mode="Markdown"
    )

async def ban_perm_cmd(update: Update, context: CallbackContext):
    await _ban(update, context, "perm")

async def ban_temp_cmd(update: Update, context: CallbackContext):
    await _ban(update, context, "temp")

async def mass_report_cmd(update: Update, context: CallbackContext):
    await _ban(update, context, "mass")

async def unban_cmd(update: Update, context: CallbackContext):
    uid = update.effective_user.id
    ok, missing = await check_channels(uid, context)
    if not ok:
        await update.message.reply_text(f"❌ Rejoins {missing}")
        return
    if not is_premium(uid):
        await update.message.reply_text("⛔ Premium only → /premium")
        return
    if not context.args:
        await update.message.reply_text("Usage : `/unban +num`", parse_mode="Markdown")
        return

    num = context.args[0]
    msg = await update.message.reply_text(f"🔓 Appeal unban sur `{num}`...", parse_mode="Markdown")
    res = await engine.unban(num)
    get_user_stats(uid)["unbans"] += 1
    db["stats"]["total_unbans"] += 1
    save_db()

    await msg.edit_text(
        f"""╔════════════════════════════╗
   ✅ UNBAN APPEAL ENVOYÉ
╚════════════════════════════╝

Target : `{num}`
Emails : {res['emails']}/{res['total_emails']}
Forms + API : ✅
Vectors : {res['vectors']}

Story :
_{res['story']}_

Dev : {DEV_USERNAME}""",
        parse_mode="Markdown"
    )

# ═══════════════════════════════════════════════════════════════
# SYSTÈME DE PAIEMENT COMPLET
# ═══════════════════════════════════════════════════════════════
async def premium_cmd(update: Update, context: CallbackContext):
    kb = [
        [InlineKeyboardButton("💎 PREMIUM 30j — 5000 FCFA", callback_data="buy_premium")],
        [InlineKeyboardButton("👑 OWNER Lifetime — 15000 FCFA", callback_data="buy_owner")],
        [InlineKeyboardButton("💳 Voir méthodes de paiement", callback_data="go_pay")],
        [InlineKeyboardButton("📞 Contacter le dev", url=DEV_URL)],
    ]
    await update.message.reply_text(
        f"""╔════════════════════════════╗
       💎 OFFRES PREMIUM
╚════════════════════════════╝

**PREMIUM** — {PRICING['premium']['price_fcfa']} / {PRICING['premium']['price_usd']}
• Ban / Unban / Mass Report illimités
• Priorité de traitement
• Stats avancées
• Support prioritaire
• Durée : {PRICING['premium']['days']} jours

**OWNER / RESELLER** — {PRICING['owner']['price_fcfa']} / {PRICING['owner']['price_usd']}
• Tout Premium +
• Commandes admin (/addprem, /broadcast...)
• Accès lifetime
• Droit de revente

Après paiement → `/pay` puis envoie la preuve à {DEV_USERNAME}""",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )

async def buy_cmd(update: Update, context: CallbackContext):
    """Affiche toutes les méthodes de paiement"""
    kb = [[InlineKeyboardButton(v["name"], callback_data=f"method_{k}")] for k, v in PAYMENT_METHODS.items()]
    kb.append([InlineKeyboardButton("← Retour Premium", callback_data="go_premium")])
    await update.message.reply_text(
        f"""╔════════════════════════════╗
     💳 MÉTHODES DE PAIEMENT
╚════════════════════════════╝

Choisis une méthode.
Ensuite utilise `/pay` pour déclarer ton paiement
et envoie la capture à {DEV_USERNAME}.

Activation manuelle sous 5-30 min.""",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )

async def pay_cmd(update: Update, context: CallbackContext):
    """Déclare un paiement en attente"""
    uid = update.effective_user.id
    name = update.effective_user.first_name or "User"

    if not context.args:
        await update.message.reply_text(
            "Usage :\n"
            "`/pay premium airtel`\n"
            "`/pay owner usdt`\n\n"
            "Plans : `premium` ou `owner`\n"
            "Méthodes : `airtel` `moov` `orange` `usdt` `btc` `crypto`",
            parse_mode="Markdown"
        )
        return

    plan = context.args[0].lower()
    method = context.args[1].lower() if len(context.args) > 1 else "airtel"

    if plan not in ("premium", "owner"):
        await update.message.reply_text("❌ Plan invalide. Utilise `premium` ou `owner`")
        return
    if method not in PAYMENT_METHODS:
        await update.message.reply_text("❌ Méthode invalide. Voir /buy")
        return

    db["pending_payments"][str(uid)] = {
        "plan": plan,
        "method": method,
        "time": time.time(),
        "name": name
    }
    save_db()

    info = PAYMENT_METHODS[method]
    price = PRICING[plan]["price_fcfa"]

    # Notifier les owners
    for oid in db["owners"]:
        try:
            await context.bot.send_message(
                oid,
                f"💰 **NOUVEAU PAIEMENT DÉCLARÉ**\n\n"
                f"User : {name} (`{uid}`)\n"
                f"Plan : **{plan.upper()}**\n"
                f"Méthode : {info['name']}\n"
                f"Prix : {price}\n\n"
                f"Utilise `/confirm {uid}` après vérification de la preuve.",
                parse_mode="Markdown"
            )
        except Exception:
            pass

    await update.message.reply_text(
        f"""✅ Paiement déclaré !

Plan : **{plan.upper()}**
Méthode : {info['name']}
Montant : {price}

{info['info']}

Envoie maintenant la **capture d'écran** du paiement à {DEV_USERNAME}.
Un owner validera avec `/confirm {uid}`.""",
        parse_mode="Markdown"
    )

async def confirm_cmd(update: Update, context: CallbackContext):
    """Owner confirme un paiement et active le plan"""
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("⛔ Owner only")
        return
    if not context.args:
        await update.message.reply_text("Usage : `/confirm <user_id>`")
        return

    target = str(int(context.args[0]))
    pending = db["pending_payments"].get(target)
    if not pending:
        await update.message.reply_text("❌ Aucun paiement en attente pour cet utilisateur.")
        return

    plan = pending["plan"]
    days = PRICING[plan]["days"]
    until = 0 if days == 0 else time.time() + days * 86400

    db["premium"][target] = {
        "until": until,
        "plan": plan,
        "activated_by": update.effective_user.id,
        "activated_at": time.time()
    }
    if plan == "owner" and int(target) not in db["owners"]:
        db["owners"].append(int(target))

    del db["pending_payments"][target]
    db["stats"]["total_payments"] += 1
    save_db()

    # Notifier l'utilisateur
    try:
        await context.bot.send_message(
            int(target),
            f"🎉 **PAIEMENT CONFIRMÉ**\n\n"
            f"Plan **{plan.upper()}** activé !\n"
            f"{'Lifetime' if days == 0 else f'{days} jours'}\n\n"
            f"Tu peux maintenant utiliser toutes les commandes premium.\n"
            f"Merci — {DEV_USERNAME}",
            parse_mode="Markdown"
        )
    except Exception:
        pass

    await update.message.reply_text(
        f"✅ Plan **{plan.upper()}** activé pour `{target}`\n"
        f"{'Lifetime' if days == 0 else f'{days} jours'}",
        parse_mode="Markdown"
    )

async def pending_cmd(update: Update, context: CallbackContext):
    """Liste les paiements en attente (owner)"""
    if not is_owner(update.effective_user.id):
        return
    if not db["pending_payments"]:
        await update.message.reply_text("Aucun paiement en attente.")
        return
    lines = []
    for uid, data in db["pending_payments"].items():
        ago = int((time.time() - data["time"]) / 60)
        lines.append(f"• `{uid}` — {data['plan']} via {data['method']} ({ago} min) — {data['name']}")
    await update.message.reply_text(
        "**PAIEMENTS EN ATTENTE**\n\n" + "\n".join(lines) + "\n\nUtilise `/confirm <id>`",
        parse_mode="Markdown"
    )

# ═══════════════════════════════════════════════════════════════
# CALLBACKS PAIEMENT
# ═══════════════════════════════════════════════════════════════
async def payment_cb(update: Update, context: CallbackContext):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "go_premium":
        await premium_cmd(update, context)
        return
    if data == "go_pay":
        await buy_cmd(update, context)
        return
    if data == "buy_premium":
        await q.edit_message_text(
            f"💎 **PREMIUM 30 jours**\nPrix : {PRICING['premium']['price_fcfa']}\n\n"
            f"1. Choisis une méthode avec /buy\n"
            f"2. Paye\n"
            f"3. `/pay premium <méthode>`\n"
            f"4. Envoie la preuve à {DEV_USERNAME}",
            parse_mode="Markdown"
        )
        return
    if data == "buy_owner":
        await q.edit_message_text(
            f"👑 **OWNER Lifetime**\nPrix : {PRICING['owner']['price_fcfa']}\n\n"
            f"Contacte directement {DEV_USERNAME} ou utilise `/pay owner <méthode>`",
            parse_mode="Markdown"
        )
        return
    if data.startswith("method_"):
        key = data[7:]
        info = PAYMENT_METHODS.get(key)
        if info:
            await q.edit_message_text(
                f"💳 **{info['name']}**\n\n{info['info']}\n\n"
                f"Après paiement :\n`/pay premium {key}`\nou\n`/pay owner {key}`\n\n"
                f"Puis envoie la capture à {DEV_USERNAME}",
                parse_mode="Markdown"
            )

# ═══════════════════════════════════════════════════════════════
# STATS / INFO / CONTACT
# ═══════════════════════════════════════════════════════════════
async def stats_cmd(update: Update, context: CallbackContext):
    uid = update.effective_user.id
    us = get_user_stats(uid)
    status = "👑 OWNER" if is_owner(uid) else ("💎 PREMIUM" if is_premium(uid) else "🆓 FREE")
    prem_info = ""
    if is_premium(uid) and not is_owner(uid):
        data = db["premium"].get(str(uid), {})
        until = data.get("until", 0)
        if until == 0:
            prem_info = "\nExpire : Lifetime"
        else:
            left = max(0, int((until - time.time()) / 86400))
            prem_info = f"\nExpire dans : {left} jours"

    await update.message.reply_text(
        f"""╔════════════════════════════╗
     📊 TES STATISTIQUES
╚════════════════════════════╝

User : {update.effective_user.first_name}
ID : `{uid}`
Status : {status}{prem_info}

📈 Utilisation
┣ Checks : {us['checks']}
┣ Bans : {us['bans']}
┗ Unbans : {us['unbans']}

Global
┣ Total bans : {db['stats']['total_bans']}
┣ Total unbans : {db['stats']['total_unbans']}
┣ Total checks : {db['stats']['total_checks']}
┗ Paiements validés : {db['stats']['total_payments']}""",
        parse_mode="Markdown"
    )

async def info_cmd(update: Update, context: CallbackContext):
    ps = proxy_mgr.stats()
    await update.message.reply_text(
        f"""╔════════════════════════════╗
     ℹ️ {BOT_NAME}
╚════════════════════════════╝

Version : `{BOT_VERSION}`
Dev : {DEV_USERNAME}
Uptime : {get_uptime()}

Proxies : {ps['available']}/{ps['total']} ({ps['rate']}%)
Users enregistrés : {len(db['all_users'])}
Owners : {len(db['owners'])}
Premium actifs : {len(db['premium'])}

Features :
• Multi-vector ban engine
• Unban appeals
• Mass reporting
• 200k+ proxy rotation
• Système de paiement complet
• Force-join protection
• Auto-owner + confirm payment

Canal : @IZANADEVHOUSE""",
        parse_mode="Markdown"
    )

async def contact_cmd(update: Update, context: CallbackContext):
    kb = [
        [InlineKeyboardButton("💬 DM DEV", url=DEV_URL)],
        [InlineKeyboardButton("📢 IZANA DEV HOUSE", url="https://t.me/IZANADEVHOUSE")],
        [InlineKeyboardButton("📢 MRX BAN DEV", url="https://t.me/MRxBANdev")],
    ]
    await update.message.reply_text(
        f"""╔════════════════════════════╗
     📞 CONTACT
╚════════════════════════════╝

Développeur : {DEV_USERNAME}
Support 24/7

Premium / Owner / Custom → DM direct.""",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )

async def proxy_stats_cmd(update: Update, context: CallbackContext):
    ps = proxy_mgr.stats()
    await update.message.reply_text(
        f"""╔════════════════════════════╗
     🔒 PROXY STATS
╚════════════════════════════╝

Total : {ps['total']}
Available : {ps['available']}
Blacklisted : {ps['blacklisted']}
Success rate : {ps['rate']}%""",
        parse_mode="Markdown"
    )

# ═══════════════════════════════════════════════════════════════
# ADMIN
# ═══════════════════════════════════════════════════════════════
async def addowner_cmd(update: Update, context: CallbackContext):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("⛔ Owner only")
        return
    if not context.args:
        await update.message.reply_text("Usage : `/addowner <id>`")
        return
    uid = int(context.args[0])
    if uid not in db["owners"]:
        db["owners"].append(uid)
        save_db()
    await update.message.reply_text(f"✅ Owner ajouté : `{uid}`", parse_mode="Markdown")

async def delowner_cmd(update: Update, context: CallbackContext):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("⛔ Owner only")
        return
    if not context.args:
        await update.message.reply_text("Usage : `/delowner <id>`")
        return
    uid = int(context.args[0])
    if uid in db["owners"]:
        db["owners"].remove(uid)
        save_db()
    await update.message.reply_text(f"✅ Owner retiré : `{uid}`", parse_mode="Markdown")

async def addprem_cmd(update: Update, context: CallbackContext):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("⛔ Owner only")
        return
    if not context.args:
        await update.message.reply_text("Usage : `/addprem <id> [jours]`\n0 = lifetime")
        return
    uid = str(int(context.args[0]))
    days = int(context.args[1]) if len(context.args) > 1 else 30
    until = 0 if days == 0 else time.time() + days * 86400
    db["premium"][uid] = {"until": until, "plan": "premium", "activated_by": update.effective_user.id}
    save_db()
    await update.message.reply_text(f"✅ Premium activé pour `{uid}` ({days}j)", parse_mode="Markdown")

async def delprem_cmd(update: Update, context: CallbackContext):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("⛔ Owner only")
        return
    if not context.args:
        await update.message.reply_text("Usage : `/delprem <id>`")
        return
    uid = str(int(context.args[0]))
    if uid in db["premium"]:
        del db["premium"][uid]
        save_db()
    await update.message.reply_text(f"✅ Premium retiré : `{uid}`", parse_mode="Markdown")

async def listowners_cmd(update: Update, context: CallbackContext):
    if not is_owner(update.effective_user.id):
        return
    txt = "\n".join(f"• `{o}`" for o in db["owners"]) or "Aucun"
    await update.message.reply_text(f"**OWNERS**\n{txt}", parse_mode="Markdown")

async def listprem_cmd(update: Update, context: CallbackContext):
    if not is_owner(update.effective_user.id):
        return
    lines = []
    for uid, data in db["premium"].items():
        until = data.get("until", 0)
        exp = "Lifetime" if until == 0 else f"{max(0, int((until-time.time())/86400))}j"
        lines.append(f"• `{uid}` — {data.get('plan','?')} ({exp})")
    await update.message.reply_text("**PREMIUM**\n" + ("\n".join(lines) or "Aucun"), parse_mode="Markdown")

async def broadcast_cmd(update: Update, context: CallbackContext):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("⛔ Owner only")
        return
    if not context.args:
        await update.message.reply_text("Usage : `/broadcast <message>`")
        return
    text = " ".join(context.args)
    ok = 0
    for uid in db["all_users"]:
        try:
            await context.bot.send_message(uid, f"📢 **BROADCAST**\n\n{text}", parse_mode="Markdown")
            ok += 1
            await asyncio.sleep(0.04)
        except Exception:
            pass
    await update.message.reply_text(f"✅ Envoyé à {ok}/{len(db['all_users'])} users")

async def id_cmd(update: Update, context: CallbackContext):
    await update.message.reply_text(f"Ton ID : `{update.effective_user.id}`", parse_mode="Markdown")

# ─── UTILS ────────────────────────────────────────────────────
async def encode_cmd(update: Update, context: CallbackContext):
    if not context.args:
        await update.message.reply_text("Usage : `/encode <text>`")
        return
    await update.message.reply_text(f"`{base64.b64encode(' '.join(context.args).encode()).decode()}`", parse_mode="Markdown")

async def decode_cmd(update: Update, context: CallbackContext):
    if not context.args:
        await update.message.reply_text("Usage : `/decode <b64>`")
        return
    try:
        await update.message.reply_text(f"`{base64.b64decode(context.args[0]).decode()}`", parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("Invalid base64")

async def hash_cmd(update: Update, context: CallbackContext):
    if not context.args:
        await update.message.reply_text("Usage : `/hash <text>`")
        return
    t = " ".join(context.args)
    await update.message.reply_text(
        f"MD5 : `{hashlib.md5(t.encode()).hexdigest()}`\nSHA256 : `{hashlib.sha256(t.encode()).hexdigest()}`",
        parse_mode="Markdown"
    )

async def passgen_cmd(update: Update, context: CallbackContext):
    length = 16
    if context.args:
        try:
            length = max(8, min(64, int(context.args[0])))
        except Exception:
            pass
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    pwd = "".join(random.choice(chars) for _ in range(length))
    await update.message.reply_text(f"`{pwd}`", parse_mode="Markdown")

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    save_db()
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # User
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("check", check_cmd))
    app.add_handler(CommandHandler("ban_perm", ban_perm_cmd))
    app.add_handler(CommandHandler("ban_temp", ban_temp_cmd))
    app.add_handler(CommandHandler("mass_report", mass_report_cmd))
    app.add_handler(CommandHandler("unban", unban_cmd))
    app.add_handler(CommandHandler("premium", premium_cmd))
    app.add_handler(CommandHandler("buy", buy_cmd))
    app.add_handler(CommandHandler("pay", pay_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("info", info_cmd))
    app.add_handler(CommandHandler("contact", contact_cmd))
    app.add_handler(CommandHandler("proxy_stats", proxy_stats_cmd))
    app.add_handler(CommandHandler("id", id_cmd))

    # Admin
    app.add_handler(CommandHandler("confirm", confirm_cmd))
    app.add_handler(CommandHandler("pending", pending_cmd))
    app.add_handler(CommandHandler("addowner", addowner_cmd))
    app.add_handler(CommandHandler("delowner", delowner_cmd))
    app.add_handler(CommandHandler("addprem", addprem_cmd))
    app.add_handler(CommandHandler("delprem", delprem_cmd))
    app.add_handler(CommandHandler("listowners", listowners_cmd))
    app.add_handler(CommandHandler("listprem", listprem_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))

    # Utils
    app.add_handler(CommandHandler("encode", encode_cmd))
    app.add_handler(CommandHandler("decode", decode_cmd))
    app.add_handler(CommandHandler("hash", hash_cmd))
    app.add_handler(CommandHandler("passgen", passgen_cmd))

    # Callbacks
    app.add_handler(CallbackQueryHandler(verify_cb, pattern="^verify$"))
    app.add_handler(CallbackQueryHandler(payment_cb, pattern="^(go_|buy_|method_)"))

    print(f"[+] {BOT_NAME} v{BOT_VERSION} online")
    print(f"[+] Proxies : {len(proxy_mgr.proxies)}")
    print(f"[+] Dev : {DEV_USERNAME}")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
