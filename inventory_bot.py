"""
NexoAI — Inventory Bot v3.0
Where Agents Connect
CEO: Joshua Lopez Almonte

Modos:
- BOT_MODE=admin  → Orquestador, ve todos los clientes
- BOT_MODE=client → Bot individual por negocio
"""

import os
import json
import logging
import requests
from datetime import datetime
from dotenv import load_dotenv
import anthropic

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[logging.FileHandler("inventory_bot.log"), logging.StreamHandler()]
)
log = logging.getLogger("NexoAI.InventoryBot")

# ── CONFIG ─────────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ANTHROPIC_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
SUPABASE_URL   = os.getenv("SUPABASE_URL", "https://turvynjwnktsjnlsdnkb.supabase.co")
SUPABASE_KEY   = os.getenv("SUPABASE_KEY", "")
MODEL          = "claude-sonnet-4-20250514"

# BOT_MODE = "admin" → orquestador (tú)
# BOT_MODE = "client" → bot individual por negocio
BOT_MODE    = os.getenv("BOT_MODE", "admin")
CLIENT_ID   = os.getenv("CLIENT_ID", "")       # Solo en modo client
CLIENT_NAME = os.getenv("CLIENT_NAME", "")     # Nombre del negocio
ADMIN_IDS   = os.getenv("ADMIN_IDS", "").split(",")  # Telegram IDs autorizados en admin

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

INDUSTRIES = {
    "restaurante":   {"emoji": "🍽️", "expiry": True,  "expiry_days": 3,   "critical": 0.20},
    "farmacia":      {"emoji": "💊",  "expiry": True,  "expiry_days": 90,  "critical": 0.25},
    "ferreteria":    {"emoji": "🔧",  "expiry": False, "expiry_days": 0,   "critical": 0.15},
    "hotel":         {"emoji": "🏨",  "expiry": True,  "expiry_days": 30,  "critical": 0.20},
    "mecanico":      {"emoji": "🚗",  "expiry": True,  "expiry_days": 180, "critical": 0.10},
    "hospital":      {"emoji": "🏥",  "expiry": True,  "expiry_days": 60,  "critical": 0.30},
    "tienda_ropa":   {"emoji": "👗",  "expiry": False, "expiry_days": 0,   "critical": 0.15},
    "dulceria":      {"emoji": "🍬",  "expiry": True,  "expiry_days": 7,   "critical": 0.20},
    "supermercado":  {"emoji": "🛒",  "expiry": True,  "expiry_days": 5,   "critical": 0.20},
    "salon_belleza": {"emoji": "💅",  "expiry": True,  "expiry_days": 30,  "critical": 0.20},
}

# ─────────────────────────────────────────────
# SUPABASE
# ─────────────────────────────────────────────

def db_get(table, filters=None):
    url = f"{SUPABASE_URL}/rest/v1/{table}?select=*"
    if filters:
        for k, v in filters.items():
            url += f"&{k}=eq.{v}"
    r = requests.get(url, headers=HEADERS)
    return r.json() if r.status_code == 200 else []

def db_insert(table, data):
    r = requests.post(f"{SUPABASE_URL}/rest/v1/{table}", headers=HEADERS, json=data)
    if r.status_code in [200, 201]:
        res = r.json()
        return res[0] if res else data
    log.error(f"[DB] Insert error {table}: {r.text}")
    return None

def db_update(table, filters, data):
    url = f"{SUPABASE_URL}/rest/v1/{table}?" + "&".join([f"{k}=eq.{v}" for k, v in filters.items()])
    data["updated_at"] = datetime.now().isoformat()
    r = requests.patch(url, headers=HEADERS, json=data)
    return r.status_code in [200, 204]

# ─────────────────────────────────────────────
# DATA
# ─────────────────────────────────────────────

def load_data(client_id_filter=None):
    """
    Carga datos desde Supabase.
    - En modo admin: carga todos los clientes
    - En modo client: carga solo el cliente de este bot
    """
    try:
        if BOT_MODE == "client" and CLIENT_ID:
            clients_raw = db_get("clients", {"id": CLIENT_ID})
        elif client_id_filter:
            clients_raw = db_get("clients", {"id": client_id_filter})
        else:
            clients_raw = db_get("clients")

        clients = {}
        for c in clients_raw:
            cid = c["id"]
            inventory_raw = db_get("inventory", {"client_id": cid})
            inventory = {}
            for item in inventory_raw:
                inventory[item["product"]] = {
                    "qty": item["qty"],
                    "min_qty": item["min_qty"],
                    "unit": item["unit"],
                    "cost": item.get("price", 0),
                    "expiry_date": item.get("expiry_date", ""),
                    "category": "general",
                    "last_updated": item.get("updated_at", "")
                }
            clients[cid] = {
                "name": c["name"],
                "industry": c["industry"],
                "contact": c.get("phone", ""),
                "inventory": inventory,
                "created_at": c.get("created_at", "")
            }
        return {"clients": clients, "current_product": {}}
    except Exception as e:
        log.error(f"[DB] Error cargando: {e}")
        return {"clients": {}, "current_product": {}}

def save_data(data):
    try:
        for cid, client_data in data.get("clients", {}).items():
            record = {
                "id": cid,
                "name": client_data["name"],
                "industry": client_data["industry"],
                "phone": client_data.get("contact", "")
            }
            existing = db_get("clients", {"id": cid})
            if existing:
                db_update("clients", {"id": cid}, record)
            else:
                db_insert("clients", record)

            for product, item in client_data.get("inventory", {}).items():
                inv = {
                    "client_id": cid,
                    "product": product,
                    "qty": item.get("qty", 0),
                    "min_qty": item.get("min_qty", 0),
                    "unit": item.get("unit", "unidades"),
                    "price": item.get("cost", 0),
                    "expiry_date": item.get("expiry_date") or None
                }
                existing_inv = db_get("inventory", {"client_id": cid})
                if any(i["product"] == product for i in existing_inv):
                    db_update("inventory", {"client_id": cid, "product": product}, inv)
                else:
                    db_insert("inventory", inv)
    except Exception as e:
        log.error(f"[DB] Error guardando: {e}")

def log_consumption(cid, product, qty, notes=""):
    try:
        db_insert("consumption_log", {
            "client_id": cid,
            "product": product,
            "qty_consumed": qty,
            "notes": notes
        })
    except Exception as e:
        log.error(f"[DB] Error log consumo: {e}")

# ─────────────────────────────────────────────
# ALERTS & HEALTH
# ─────────────────────────────────────────────

def get_alerts(client):
    alerts = {"critical": [], "low": [], "expiring": [], "expired": []}
    profile = INDUSTRIES.get(client.get("industry", "restaurante"), INDUSTRIES["restaurante"])
    today = datetime.now().date()
    for product, d in client.get("inventory", {}).items():
        qty, min_qty = d["qty"], d["min_qty"]
        if min_qty > 0:
            ratio = qty / min_qty
            if ratio <= profile["critical"]:
                alerts["critical"].append({"product": product, "qty": qty, "unit": d["unit"], "ratio": round(ratio*100, 1)})
            elif ratio <= 0.35:
                alerts["low"].append({"product": product, "qty": qty, "unit": d["unit"]})
        if profile["expiry"] and d.get("expiry_date"):
            try:
                exp = datetime.strptime(d["expiry_date"], "%Y-%m-%d").date()
                days = (exp - today).days
                if days < 0:
                    alerts["expired"].append({"product": product, "days": abs(days)})
                elif days <= profile["expiry_days"]:
                    alerts["expiring"].append({"product": product, "days_left": days})
            except:
                pass
    return alerts

def get_health(client):
    alerts = get_alerts(client)
    total = len(client.get("inventory", {}))
    if total == 0:
        return 100
    penalty = len(alerts["critical"])*20 + len(alerts["expired"])*15 + len(alerts["expiring"])*5 + len(alerts["low"])*3
    return max(0, 100 - penalty)

# ─────────────────────────────────────────────
# KEYBOARDS — COMPARTIDOS
# ─────────────────────────────────────────────

def kb_back(target="back_main"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Volver", callback_data=target)]])

def kb_industries():
    rows = []
    items = list(INDUSTRIES.items())
    for i in range(0, len(items), 2):
        row = []
        for ind, prof in items[i:i+2]:
            row.append(InlineKeyboardButton(f"{prof['emoji']} {ind.replace('_',' ').title()}", callback_data=f"industry_{ind}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("◀️ Volver", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)

def kb_products(client, cid, action="update_prod"):
    rows = []
    for prod in client.get("inventory", {}).keys():
        rows.append([InlineKeyboardButton(f"📦 {prod}", callback_data=f"{action}_{cid}_{prod}")])
    rows.append([InlineKeyboardButton("◀️ Volver", callback_data=f"view_{cid}")])
    return InlineKeyboardMarkup(rows)

def kb_client_menu(cid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Ver Inventario",    callback_data=f"client_inv_{cid}"),
         InlineKeyboardButton("🚨 Ver Alertas",       callback_data=f"client_alerts_{cid}")],
        [InlineKeyboardButton("📉 Registrar Consumo", callback_data=f"client_consume_{cid}"),
         InlineKeyboardButton("✏️ Actualizar Stock",  callback_data=f"client_update_{cid}")],
        [InlineKeyboardButton("➕ Agregar Producto",  callback_data=f"client_addprod_{cid}"),
         InlineKeyboardButton("📄 Orden de Compra",   callback_data=f"client_order_{cid}")],
        [InlineKeyboardButton("🤖 Análisis IA",       callback_data=f"client_ai_{cid}"),
         InlineKeyboardButton("◀️ Volver",            callback_data="menu_clients")],
    ])

# ─────────────────────────────────────────────
# MODO CLIENT — Teclado simplificado
# ─────────────────────────────────────────────

def kb_client_main():
    """Menú principal para modo cliente — sin gestión de múltiples clientes"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 Mi Inventario",     callback_data="my_inventory"),
         InlineKeyboardButton("🚨 Mis Alertas",       callback_data="my_alerts")],
        [InlineKeyboardButton("📉 Registrar Consumo", callback_data="my_consume"),
         InlineKeyboardButton("✏️ Actualizar Stock",  callback_data="my_update")],
        [InlineKeyboardButton("➕ Agregar Producto",  callback_data="my_add_product"),
         InlineKeyboardButton("📄 Orden de Compra",   callback_data="my_order")],
        [InlineKeyboardButton("📊 Mi Reporte",        callback_data="my_report"),
         InlineKeyboardButton("🤖 Análisis IA",       callback_data="my_ai")],
    ])

# ─────────────────────────────────────────────
# MODO ADMIN — Teclado completo
# ─────────────────────────────────────────────

def kb_admin_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 Inventario",        callback_data="menu_inventory"),
         InlineKeyboardButton("🚨 Alertas",           callback_data="menu_alerts")],
        [InlineKeyboardButton("📊 Reportes",          callback_data="menu_reports"),
         InlineKeyboardButton("👥 Clientes",          callback_data="menu_clients")],
        [InlineKeyboardButton("➕ Agregar Producto",  callback_data="menu_add_product")],
        [InlineKeyboardButton("🤖 Análisis IA",       callback_data="menu_ai"),
         InlineKeyboardButton("⚙️ Ajustes",          callback_data="menu_settings")],
    ])

def kb_clients(data, action="view"):
    clients = data.get("clients", {})
    if not clients:
        return None
    rows = []
    for cid, c in clients.items():
        emoji = INDUSTRIES.get(c.get("industry", "restaurante"), {}).get("emoji", "📦")
        health = get_health(c)
        he = "🟢" if health >= 75 else "🟡" if health >= 50 else "🔴"
        rows.append([InlineKeyboardButton(f"{he} {emoji} {c['name']}", callback_data=f"{action}_{cid}")])
    rows.append([InlineKeyboardButton("◀️ Volver", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)

# ─────────────────────────────────────────────
# START
# ─────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if BOT_MODE == "client":
        await start_client_mode(update, ctx)
    else:
        await start_admin_mode(update, ctx)

async def start_admin_mode(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 *NexoAI — Panel Admin v3.0*\n"
        "_Where Agents Connect_\n\n"
        "Gestión completa de todos los clientes.\n\n"
        "Selecciona una opción:"
    )
    if update.message:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb_admin_main())
    else:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb_admin_main())

async def start_client_mode(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Inicio para modo cliente — muestra el negocio directamente"""
    db = load_data()
    clients = db.get("clients", {})

    # Si el cliente ya existe, mostrar su panel
    if CLIENT_ID and CLIENT_ID in clients:
        c = clients[CLIENT_ID]
        health = get_health(c)
        he = "🟢" if health >= 75 else "🟡" if health >= 50 else "🔴"
        emoji = INDUSTRIES.get(c.get("industry", "restaurante"), {}).get("emoji", "📦")
        total = len(c.get("inventory", {}))
        alerts = get_alerts(c)
        total_alerts = len(alerts["critical"]) + len(alerts["expired"])

        text = (
            f"🤖 *NexoAI — {c['name']}*\n"
            f"_Where Agents Connect_\n\n"
            f"{emoji} {c.get('industry','').replace('_',' ').title()}\n"
            f"{he} Salud: {health}/100\n"
            f"📦 Productos: {total}\n"
        )
        if total_alerts > 0:
            text += f"🚨 Alertas activas: {total_alerts}\n"

        if update.message:
            await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb_client_main())
        else:
            await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb_client_main())

    else:
        # Primera vez — onboarding del negocio
        ctx.user_data["action"] = "client_onboarding"
        ctx.user_data["step"] = "name"
        text = (
            "👋 *Bienvenido a NexoAI*\n"
            "_Where Agents Connect_\n\n"
            "Vamos a configurar tu negocio.\n\n"
            "¿Cuál es el nombre de tu negocio?"
        )
        if update.message:
            await update.message.reply_text(text, parse_mode="Markdown")
        else:
            await update.callback_query.edit_message_text(text, parse_mode="Markdown")

# ─────────────────────────────────────────────
# CALLBACK HANDLER
# ─────────────────────────────────────────────

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    await q.answer()

    if data in ("back_main", "menu_main"):
        await cmd_start(update, ctx)
        return

    # Redirigir según modo
    if BOT_MODE == "client":
        await handle_client_callback(update, ctx, data)
    else:
        await handle_admin_callback(update, ctx, data)

# ─────────────────────────────────────────────
# CALLBACKS — MODO CLIENT
# ─────────────────────────────────────────────

async def handle_client_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE, data: str):
    q = update.callback_query
    db = load_data()
    cid = CLIENT_ID
    c = db.get("clients", {}).get(cid)

    if not c:
        await q.edit_message_text("❌ Negocio no configurado. Escribe /start para comenzar.")
        return

    if data == "my_inventory":
        if not c.get("inventory"):
            await q.edit_message_text(
                "📦 *Mi Inventario*\n\nNo tienes productos registrados.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ Agregar Producto", callback_data="my_add_product")],
                    [InlineKeyboardButton("◀️ Volver", callback_data="back_main")],
                ]))
            return
        msg = f"📦 *Inventario — {c['name']}*\n\n"
        for prod, d in c["inventory"].items():
            ratio = (d["qty"] / d["min_qty"] * 100) if d["min_qty"] > 0 else 100
            st = "🔴" if ratio <= 20 else "🟡" if ratio <= 35 else "🟢"
            msg += f"{st} *{prod}*\n"
            msg += f"   Stock: {d['qty']} {d['unit']} | Mín: {d['min_qty']}\n"
            if d.get("expiry_date"):
                msg += f"   Vence: {d['expiry_date']}\n"
        await q.edit_message_text(msg[:4000], parse_mode="Markdown", reply_markup=kb_back())
        return

    if data == "my_alerts":
        alerts = get_alerts(c)
        msg = f"🚨 *Alertas — {c['name']}*\n\n"
        if not any(alerts.values()):
            msg += "✅ Sin alertas activas. Todo en orden."
        else:
            for item in alerts["critical"]:
                msg += f"🔴 CRÍTICO: {item['product']} ({item['ratio']}%)\n"
            for item in alerts["expired"]:
                msg += f"❌ VENCIDO: {item['product']}\n"
            for item in alerts["expiring"]:
                msg += f"⚠️ Por vencer: {item['product']} ({item['days_left']} días)\n"
            for item in alerts["low"]:
                msg += f"📉 Stock bajo: {item['product']}\n"
        await q.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb_back())
        return

    if data == "my_add_product":
        db["current_product"] = {"step": "name", "client_id": cid}
        save_data(db)
        await q.edit_message_text(
            "➕ *Agregar Producto*\n\n¿Nombre del producto?",
            parse_mode="Markdown",
            reply_markup=kb_back())
        return

    if data == "my_consume":
        if not c.get("inventory"):
            await q.edit_message_text("Sin productos registrados.", reply_markup=kb_back())
            return
        await q.edit_message_text(
            "📉 *Registrar Consumo*\n\nSelecciona el producto:",
            parse_mode="Markdown",
            reply_markup=kb_products(c, cid, "consume_prod"))
        return

    if data == "my_update":
        if not c.get("inventory"):
            await q.edit_message_text("Sin productos registrados.", reply_markup=kb_back())
            return
        await q.edit_message_text(
            "✏️ *Actualizar Stock*\n\nSelecciona el producto:",
            parse_mode="Markdown",
            reply_markup=kb_products(c, cid, "update_prod"))
        return

    if data == "my_order":
        alerts = get_alerts(c)
        needs_order = alerts["critical"] + alerts["low"]
        if not needs_order:
            await q.edit_message_text(
                "📄 *Orden de Compra*\n\n✅ No hay productos que ordenar ahora.",
                parse_mode="Markdown",
                reply_markup=kb_back())
            return
        msg = f"📄 *Orden de Compra — {c['name']}*\n\n"
        for item in needs_order:
            prod = item["product"]
            inv = c["inventory"].get(prod, {})
            needed = max(0, inv.get("min_qty", 0) * 3 - inv.get("qty", 0))
            msg += f"📦 {prod}: {needed} {inv.get('unit','unidades')}\n"
        msg += f"\n_Generado: {datetime.now().strftime('%Y-%m-%d %H:%M')}_"
        await q.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb_back())
        return

    if data == "my_report":
        health = get_health(c)
        alerts = get_alerts(c)
        he = "🟢" if health >= 75 else "🟡" if health >= 50 else "🔴"
        total = len(c.get("inventory", {}))
        value = sum(d["qty"]*d.get("cost", 0) for d in c.get("inventory", {}).values())
        msg = (
            f"📊 *Reporte — {c['name']}*\n\n"
            f"{he} Salud: {health}/100\n"
            f"📦 Productos: {total}\n"
        )
        if value > 0:
            msg += f"💰 Valor inventario: ${value:,.2f}\n"
        msg += (
            f"\n🔴 Críticos: {len(alerts['critical'])}\n"
            f"📉 Stock bajo: {len(alerts['low'])}\n"
            f"⚠️ Por vencer: {len(alerts['expiring'])}\n"
            f"❌ Vencidos: {len(alerts['expired'])}\n"
            f"\n_Generado: {datetime.now().strftime('%Y-%m-%d %H:%M')}_"
        )
        await q.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb_back())
        return

    if data == "my_ai":
        await q.edit_message_text("🤖 Analizando con IA...")
        try:
            client_ai = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
            alerts = get_alerts(c)
            health = get_health(c)
            inv_summary = json.dumps(c.get("inventory", {}), ensure_ascii=False, indent=2)
            prompt = (
                f"Eres el asistente de inventario NexoAI. Analiza este negocio:\n\n"
                f"Negocio: {c['name']}\nIndustria: {c.get('industry','')}\n"
                f"Salud: {health}/100\nAlertas críticas: {len(alerts['critical'])}\n"
                f"Inventario:\n{inv_summary}\n\n"
                f"Da un análisis breve en español:\n"
                f"1. Estado general\n2. Productos urgentes\n3. Recomendaciones (máx 3)\n"
                f"Sé conciso y directo."
            )
            response = client_ai.messages.create(
                model=MODEL, max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )
            msg = f"🤖 *Análisis IA — {c['name']}*\n\n{response.content[0].text}"
            await q.edit_message_text(msg[:4000], parse_mode="Markdown", reply_markup=kb_back())
        except Exception as e:
            await q.edit_message_text(f"❌ Error: {e}", reply_markup=kb_back())
        return

    # Callbacks compartidos con admin
    if data.startswith("consume_prod_"):
        parts = data[13:].split("_", 1)
        if len(parts) == 2:
            _, prod = parts
            db["current_product"] = {"step": "consume_qty", "client_id": cid, "product": prod}
            save_data(db)
            unit = c.get("inventory", {}).get(prod, {}).get("unit", "unidades")
            await q.edit_message_text(
                f"📉 *{prod}*\n\n¿Cuánto consumiste? (en {unit})",
                parse_mode="Markdown", reply_markup=kb_back())
        return

    if data.startswith("update_prod_"):
        parts = data[12:].split("_", 1)
        if len(parts) == 2:
            _, prod = parts
            db["current_product"] = {"step": "update_qty", "client_id": cid, "product": prod}
            save_data(db)
            await q.edit_message_text(
                f"✏️ *{prod}*\n\n¿Nuevo stock actual?",
                parse_mode="Markdown", reply_markup=kb_back())
        return

    if data.startswith("industry_"):
        ind = data[9:]
        if ctx.user_data.get("action") == "client_onboarding":
            name = ctx.user_data.get("client_name", CLIENT_NAME or "Mi Negocio")
            contact = ctx.user_data.get("client_contact", "")
            db.setdefault("clients", {})[cid] = {
                "name": name, "industry": ind,
                "contact": contact, "inventory": {},
                "created_at": datetime.now().isoformat()
            }
            save_data(db)
            emoji = INDUSTRIES[ind]["emoji"]
            await q.edit_message_text(
                f"✅ *¡Negocio configurado!*\n\n{emoji} *{name}*\n"
                f"Industria: {ind.replace('_',' ').title()}\n\n"
                f"Ya puedes comenzar a agregar tu inventario.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ Agregar Producto", callback_data="my_add_product")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="back_main")],
                ]))
            ctx.user_data.clear()
        return

# ─────────────────────────────────────────────
# CALLBACKS — MODO ADMIN
# ─────────────────────────────────────────────

async def handle_admin_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE, data: str):
    q = update.callback_query
    db = load_data()

    if data == "menu_inventory":
        clients = db.get("clients", {})
        if not clients:
            await q.edit_message_text("📦 No tienes clientes registrados.", parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ Agregar Cliente", callback_data="menu_add_client")],
                    [InlineKeyboardButton("◀️ Volver", callback_data="back_main")],
                ]))
        else:
            await q.edit_message_text("📦 *Inventario*\n\nSelecciona un cliente:",
                parse_mode="Markdown", reply_markup=kb_clients(db, "view"))
        return

    if data == "menu_alerts":
        clients = db.get("clients", {})
        if not clients:
            await q.edit_message_text("🚨 No hay clientes.", parse_mode="Markdown", reply_markup=kb_back())
            return
        msg = "🚨 *Alertas Activas*\n\n"
        has_alerts = False
        for cid, c in clients.items():
            alerts = get_alerts(c)
            if any(alerts.values()):
                has_alerts = True
                emoji = INDUSTRIES.get(c.get("industry", "restaurante"), {}).get("emoji", "📦")
                msg += f"{emoji} *{c['name']}*\n"
                for item in alerts["critical"]:
                    msg += f" 🔴 CRÍTICO: {item['product']} ({item['ratio']}%)\n"
                for item in alerts["expired"]:
                    msg += f" ❌ VENCIDO: {item['product']}\n"
                for item in alerts["expiring"]:
                    msg += f" ⚠️ Por vencer: {item['product']} ({item['days_left']} días)\n"
                for item in alerts["low"]:
                    msg += f" 📉 Stock bajo: {item['product']}\n"
                msg += "\n"
        if not has_alerts:
            msg += "✅ Todo en orden."
        await q.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb_back())
        return

    if data == "menu_reports":
        clients = db.get("clients", {})
        if not clients:
            await q.edit_message_text("📊 No hay clientes.", parse_mode="Markdown", reply_markup=kb_back())
            return
        msg = "📊 *Reporte General*\n\n"
        for cid, c in clients.items():
            health = get_health(c)
            alerts = get_alerts(c)
            he = "🟢" if health >= 75 else "🟡" if health >= 50 else "🔴"
            emoji = INDUSTRIES.get(c.get("industry", "restaurante"), {}).get("emoji", "📦")
            total = len(c.get("inventory", {}))
            value = sum(d["qty"]*d.get("cost", 0) for d in c.get("inventory", {}).values())
            msg += f"{emoji} *{c['name']}*\n"
            msg += f" {he} Salud: {health}/100 | Productos: {total}\n"
            if value > 0:
                msg += f" 💰 Valor: ${value:,.2f}\n"
            msg += f" 🚨 Críticos: {len(alerts['critical'])} | 📉 Bajos: {len(alerts['low'])}\n\n"
        await q.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb_back())
        return

    if data == "menu_clients":
        clients = db.get("clients", {})
        if not clients:
            await q.edit_message_text("👥 No tienes clientes.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ Agregar Cliente", callback_data="menu_add_client")],
                    [InlineKeyboardButton("◀️ Volver", callback_data="back_main")],
                ]))
        else:
            kb = kb_clients(db, "view")
            new_rows = kb.inline_keyboard + [[InlineKeyboardButton("➕ Nuevo Cliente", callback_data="menu_add_client")]]
            await q.edit_message_text("👥 *Clientes*\n\nSelecciona un cliente:",
                parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(new_rows))
        return

    if data == "menu_add_client":
        ctx.user_data["action"] = "add_client"
        ctx.user_data["step"] = "name"
        await q.edit_message_text("👥 *Nuevo Cliente*\n\n¿Nombre del negocio?",
            parse_mode="Markdown", reply_markup=kb_back())
        return

    if data == "menu_add_product":
        clients = db.get("clients", {})
        if not clients:
            await q.edit_message_text("Primero agrega un cliente.", reply_markup=kb_back())
            return
        await q.edit_message_text("➕ Selecciona el cliente:",
            parse_mode="Markdown", reply_markup=kb_clients(db, "client_addprod"))
        return

    if data == "menu_ai":
        clients = db.get("clients", {})
        if not clients:
            await q.edit_message_text("🤖 No hay clientes.", parse_mode="Markdown", reply_markup=kb_back())
            return
        await q.edit_message_text("🤖 *Análisis IA*\n\nSelecciona el cliente:",
            parse_mode="Markdown", reply_markup=kb_clients(db, "client_ai"))
        return

    if data == "menu_settings":
        total_clients = len(db.get("clients", {}))
        await q.edit_message_text(
            f"⚙️ *NexoAI Admin v3.0*\n\n"
            f"Modo: Admin 👑\n"
            f"Clientes activos: {total_clients}\n"
            f"DB: Supabase ✅\n"
            f"CEO: Joshua López Almonte",
            parse_mode="Markdown", reply_markup=kb_back())
        return

    if data.startswith("view_"):
        cid = data[5:]
        c = db.get("clients", {}).get(cid)
        if not c:
            await q.edit_message_text("❌ Cliente no encontrado.", reply_markup=kb_back())
            return
        health = get_health(c)
        he = "🟢" if health >= 75 else "🟡" if health >= 50 else "🔴"
        emoji = INDUSTRIES.get(c.get("industry", "restaurante"), {}).get("emoji", "📦")
        total = len(c.get("inventory", {}))
        value = sum(d["qty"]*d.get("cost", 0) for d in c.get("inventory", {}).values())
        msg = (
            f"{emoji} *{c['name']}*\n"
            f"Industria: {c.get('industry','').replace('_',' ').title()}\n"
            f"Contacto: {c.get('contact','N/A')}\n\n"
            f"{he} Salud: {health}/100\n"
            f"📦 Productos: {total}\n"
        )
        if value > 0:
            msg += f"💰 Valor: ${value:,.2f}\n"
        await q.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb_client_menu(cid))
        return

    if data.startswith("client_inv_"):
        cid = data[11:]
        c = db.get("clients", {}).get(cid)
        if not c or not c.get("inventory"):
            await q.edit_message_text("📦 Sin productos.", reply_markup=kb_client_menu(cid))
            return
        msg = f"📦 *Inventario — {c['name']}*\n\n"
        for prod, d in c["inventory"].items():
            ratio = (d["qty"] / d["min_qty"] * 100) if d["min_qty"] > 0 else 100
            st = "🔴" if ratio <= 20 else "🟡" if ratio <= 35 else "🟢"
            msg += f"{st} *{prod}*: {d['qty']} {d['unit']} | Mín: {d['min_qty']}\n"
        await q.edit_message_text(msg[:4000], parse_mode="Markdown", reply_markup=kb_client_menu(cid))
        return

    if data.startswith("client_alerts_"):
        cid = data[14:]
        c = db.get("clients", {}).get(cid)
        if not c:
            await q.edit_message_text("❌ No encontrado.", reply_markup=kb_back())
            return
        alerts = get_alerts(c)
        msg = f"🚨 *Alertas — {c['name']}*\n\n"
        if not any(alerts.values()):
            msg += "✅ Sin alertas."
        else:
            for item in alerts["critical"]:
                msg += f"🔴 CRÍTICO: {item['product']} ({item['ratio']}%)\n"
            for item in alerts["expired"]:
                msg += f"❌ VENCIDO: {item['product']}\n"
            for item in alerts["expiring"]:
                msg += f"⚠️ Por vencer: {item['product']} ({item['days_left']} días)\n"
            for item in alerts["low"]:
                msg += f"📉 Stock bajo: {item['product']}\n"
        await q.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb_client_menu(cid))
        return

    if data.startswith("client_addprod_"):
        cid = data[15:]
        db["current_product"] = {"step": "name", "client_id": cid}
        save_data(db)
        await q.edit_message_text("➕ *Agregar Producto*\n\n¿Nombre del producto?",
            parse_mode="Markdown", reply_markup=kb_back())
        return

    if data.startswith("client_consume_"):
        cid = data[15:]
        c = db.get("clients", {}).get(cid)
        if not c or not c.get("inventory"):
            await q.edit_message_text("Sin productos.", reply_markup=kb_client_menu(cid))
            return
        await q.edit_message_text("📉 *Registrar Consumo*\n\nSelecciona el producto:",
            parse_mode="Markdown", reply_markup=kb_products(c, cid, "consume_prod"))
        return

    if data.startswith("consume_prod_"):
        parts = data[13:].split("_", 1)
        if len(parts) == 2:
            cid, prod = parts
            db["current_product"] = {"step": "consume_qty", "client_id": cid, "product": prod}
            save_data(db)
            c = db.get("clients", {}).get(cid, {})
            unit = c.get("inventory", {}).get(prod, {}).get("unit", "unidades")
            await q.edit_message_text(f"📉 *{prod}*\n\n¿Cuánto consumiste? (en {unit})",
                parse_mode="Markdown", reply_markup=kb_back())
        return

    if data.startswith("client_update_"):
        cid = data[14:]
        c = db.get("clients", {}).get(cid)
        if not c or not c.get("inventory"):
            await q.edit_message_text("Sin productos.", reply_markup=kb_client_menu(cid))
            return
        await q.edit_message_text("✏️ *Actualizar Stock*\n\nSelecciona el producto:",
            parse_mode="Markdown", reply_markup=kb_products(c, cid, "update_prod"))
        return

    if data.startswith("update_prod_"):
        parts = data[12:].split("_", 1)
        if len(parts) == 2:
            cid, prod = parts
            db["current_product"] = {"step": "update_qty", "client_id": cid, "product": prod}
            save_data(db)
            await q.edit_message_text(f"✏️ *{prod}*\n\n¿Nuevo stock actual?",
                parse_mode="Markdown", reply_markup=kb_back())
        return

    if data.startswith("client_order_"):
        cid = data[13:]
        c = db.get("clients", {}).get(cid)
        if not c:
            await q.edit_message_text("❌ No encontrado.", reply_markup=kb_back())
            return
        alerts = get_alerts(c)
        needs_order = alerts["critical"] + alerts["low"]
        if not needs_order:
            await q.edit_message_text("📄 ✅ No hay productos que ordenar.",
                parse_mode="Markdown", reply_markup=kb_client_menu(cid))
            return
        msg = f"📄 *Orden de Compra — {c['name']}*\n\n"
        for item in needs_order:
            prod = item["product"]
            inv = c["inventory"].get(prod, {})
            needed = max(0, inv.get("min_qty", 0) * 3 - inv.get("qty", 0))
            msg += f"📦 {prod}: {needed} {inv.get('unit','unidades')}\n"
        msg += f"\n_Generado: {datetime.now().strftime('%Y-%m-%d %H:%M')}_"
        await q.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb_client_menu(cid))
        return

    if data.startswith("client_ai_"):
        cid = data[10:]
        c = db.get("clients", {}).get(cid)
        if not c:
            await q.edit_message_text("❌ No encontrado.", reply_markup=kb_back())
            return
        await q.edit_message_text("🤖 Analizando...")
        try:
            client_ai = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
            alerts = get_alerts(c)
            health = get_health(c)
            prompt = (
                f"Eres NexoAI. Analiza:\nNegocio: {c['name']}\nIndustria: {c.get('industry','')}\n"
                f"Salud: {health}/100\nAlertas críticas: {len(alerts['critical'])}\n"
                f"Inventario: {json.dumps(c.get('inventory',{}), ensure_ascii=False)}\n\n"
                f"Análisis breve en español: estado, urgentes, 3 recomendaciones."
            )
            response = client_ai.messages.create(
                model=MODEL, max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )
            msg = f"🤖 *Análisis — {c['name']}*\n\n{response.content[0].text}"
            await q.edit_message_text(msg[:4000], parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Volver", callback_data=f"view_{cid}")]]))
        except Exception as e:
            await q.edit_message_text(f"❌ Error: {e}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Volver", callback_data=f"view_{cid}")]]))
        return

    if data.startswith("industry_"):
        ind = data[9:]
        if ctx.user_data.get("action") == "add_client":
            name = ctx.user_data.get("client_name", "Nuevo Cliente")
            contact = ctx.user_data.get("client_contact", "")
            cid = f"client_{len(db.get('clients', {})) + 1:03d}"
            db.setdefault("clients", {})[cid] = {
                "name": name, "industry": ind,
                "contact": contact, "inventory": {},
                "created_at": datetime.now().isoformat()
            }
            save_data(db)
            emoji = INDUSTRIES[ind]["emoji"]
            await q.edit_message_text(
                f"✅ *Cliente agregado*\n\n{emoji} {name}\nIndustria: {ind.replace('_',' ').title()}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ Agregar Producto", callback_data=f"client_addprod_{cid}")],
                    [InlineKeyboardButton("👥 Ver Clientes", callback_data="menu_clients")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="back_main")],
                ]))
            ctx.user_data.clear()
        return

# ─────────────────────────────────────────────
# MESSAGE HANDLER — COMPARTIDO
# ─────────────────────────────────────────────

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    db = load_data()
    action = ctx.user_data.get("action", "")
    product = db.get("current_product", {})

    # ── Onboarding cliente (modo client) ───────
    if action == "client_onboarding":
        step = ctx.user_data.get("step", "name")
        if step == "name":
            ctx.user_data["client_name"] = text
            ctx.user_data["step"] = "industry"
            await update.message.reply_text(
                f"👥 *{text}*\n\n¿Qué tipo de negocio es?",
                parse_mode="Markdown",
                reply_markup=kb_industries())
        return

    # ── Add client (modo admin) ─────────────────
    if action == "add_client":
        step = ctx.user_data.get("step", "name")
        if step == "name":
            ctx.user_data["client_name"] = text
            ctx.user_data["step"] = "contact"
            await update.message.reply_text(f"👥 *{text}*\n\n¿Teléfono? (o 'saltar')", parse_mode="Markdown")
        elif step == "contact":
            ctx.user_data["client_contact"] = "" if text.lower() == "saltar" else text
            ctx.user_data["step"] = "industry"
            await update.message.reply_text("🏭 Selecciona la industria:", parse_mode="Markdown", reply_markup=kb_industries())
        return

    # ── Add product ─────────────────────────────
    if product.get("step") == "name":
        product["name"] = text
        product["step"] = "qty"
        db["current_product"] = product
        save_data(db)
        await update.message.reply_text(f"📦 *{text}*\n\n¿Cantidad actual en stock?", parse_mode="Markdown")
        return

    if product.get("step") == "qty":
        try:
            product["qty"] = float(text.replace(",", "."))
            product["step"] = "unit"
            db["current_product"] = product
            save_data(db)
            await update.message.reply_text("¿Unidad de medida?\n_(libras, unidades, cajas...)_", parse_mode="Markdown")
        except:
            await update.message.reply_text("⚠️ Solo el número. Ej: 50")
        return

    if product.get("step") == "unit":
        product["unit"] = text
        product["step"] = "min_qty"
        db["current_product"] = product
        save_data(db)
        await update.message.reply_text("¿Cantidad mínima para alertar?", parse_mode="Markdown")
        return

    if product.get("step") == "min_qty":
        try:
            product["min_qty"] = float(text.replace(",", "."))
            product["step"] = "cost"
            db["current_product"] = product
            save_data(db)
            await update.message.reply_text("¿Costo por unidad? (o 'saltar')", parse_mode="Markdown")
        except:
            await update.message.reply_text("⚠️ Solo el número.")
        return

    if product.get("step") == "cost":
        try:
            product["cost"] = 0.0 if text.lower() == "saltar" else float(text.replace(",", ".").replace("$", ""))
            product["step"] = "expiry"
            db["current_product"] = product
            save_data(db)
            await update.message.reply_text("¿Fecha de vencimiento? (YYYY-MM-DD)\no 'saltar'")
        except:
            await update.message.reply_text("⚠️ Solo el número o 'saltar'")
        return

    if product.get("step") == "expiry":
        product["expiry_date"] = "" if text.lower() == "saltar" else text
        cid = product.get("client_id")
        name = product.get("name", "Producto")
        if cid and cid in db.get("clients", {}):
            db["clients"][cid]["inventory"][name] = {
                "qty": product.get("qty", 0),
                "unit": product.get("unit", "unidades"),
                "min_qty": product.get("min_qty", 0),
                "cost": product.get("cost", 0),
                "expiry_date": product.get("expiry_date", ""),
                "category": "general",
                "last_updated": datetime.now().isoformat()
            }
            db["current_product"] = {}
            save_data(db)
            back_btn = "my_add_product" if BOT_MODE == "client" else f"client_addprod_{cid}"
            inv_btn  = "my_inventory"   if BOT_MODE == "client" else f"client_inv_{cid}"
            await update.message.reply_text(
                f"✅ *Producto agregado*\n\n📦 {name}\nStock: {product.get('qty')} {product.get('unit')}\nMínimo: {product.get('min_qty')}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ Otro Producto", callback_data=back_btn)],
                    [InlineKeyboardButton("📋 Ver Inventario", callback_data=inv_btn)],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="back_main")],
                ]))
        return

    # ── Consume ─────────────────────────────────
    if product.get("step") == "consume_qty":
        try:
            consumed = float(text.replace(",", "."))
            cid = product.get("client_id")
            prod = product.get("product")
            if cid and prod and cid in db.get("clients", {}) and prod in db["clients"][cid]["inventory"]:
                old_qty = db["clients"][cid]["inventory"][prod]["qty"]
                new_qty = max(0, old_qty - consumed)
                unit = db["clients"][cid]["inventory"][prod]["unit"]
                min_qty = db["clients"][cid]["inventory"][prod]["min_qty"]
                db["clients"][cid]["inventory"][prod]["qty"] = new_qty
                db["clients"][cid]["inventory"][prod]["last_updated"] = datetime.now().isoformat()
                db["current_product"] = {}
                save_data(db)
                log_consumption(cid, prod, consumed)
                ratio = (new_qty / min_qty * 100) if min_qty > 0 else 100
                status = "🔴 CRÍTICO" if ratio <= 20 else "🟡 BAJO" if ratio <= 35 else "🟢 OK"
                await update.message.reply_text(
                    f"📉 *Consumo Registrado*\n\n📦 {prod}\n➖ {consumed} {unit}\nAhora: {new_qty} {unit}\n{status}",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🏠 Inicio", callback_data="back_main")],
                    ]))
            else:
                await update.message.reply_text("❌ Error.")
        except:
            await update.message.reply_text("⚠️ Solo el número.")
        return

    # ── Update qty ───────────────────────────────
    if product.get("step") == "update_qty":
        try:
            new_qty = float(text.replace(",", "."))
            cid = product.get("client_id")
            prod = product.get("product")
            if cid and prod and cid in db.get("clients", {}) and prod in db["clients"][cid]["inventory"]:
                unit = db["clients"][cid]["inventory"][prod]["unit"]
                db["clients"][cid]["inventory"][prod]["qty"] = new_qty
                db["clients"][cid]["inventory"][prod]["last_updated"] = datetime.now().isoformat()
                db["current_product"] = {}
                save_data(db)
                await update.message.reply_text(
                    f"✅ *Stock actualizado*\n\n📦 {prod}: {new_qty} {unit}",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🏠 Inicio", callback_data="back_main")],
                    ]))
            else:
                await update.message.reply_text("❌ Error.")
        except:
            await update.message.reply_text("⚠️ Solo el número.")
        return

    # ── Default ──────────────────────────────────
    await update.message.reply_text("🤖 NexoAI\n\nUsa el menú:", parse_mode="Markdown",
        reply_markup=kb_client_main() if BOT_MODE == "client" else kb_admin_main())

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    mode_label = "👑 Admin" if BOT_MODE == "admin" else f"🏪 Cliente: {CLIENT_NAME or CLIENT_ID}"
    print(f"🤖 NexoAI Inventory Bot v3.0 — {mode_label}")
    print(f"📡 Supabase: {SUPABASE_URL}")
    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN no configurado")
        return
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("✅ Bot corriendo...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
