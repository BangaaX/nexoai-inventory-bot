"""
NexoAI — Inventory Bot v1.1
Where Agents Connect
CEO: Joshua Lopez Almonte
"""

import os
import json
import logging
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

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ANTHROPIC_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
DATA_FILE      = "inventory_data.json"
MODEL          = "claude-sonnet-4-20250514"

INDUSTRIES = {
    "restaurante":   {"emoji": "🍽️",  "expiry": True,  "expiry_days": 3,   "critical": 0.20},
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
# DATA
# ─────────────────────────────────────────────
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE) as f:
                return json.load(f)
        except:
            pass
    return {"clients": {}, "current_product": {}}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_alerts(client):
    alerts = {"critical": [], "low": [], "expiring": [], "expired": []}
    profile = INDUSTRIES.get(client.get("industry", "restaurante"), INDUSTRIES["restaurante"])
    today   = datetime.now().date()
    for product, d in client.get("inventory", {}).items():
        qty, min_qty = d["qty"], d["min_qty"]
        if min_qty > 0:
            ratio = qty / min_qty
            if ratio <= profile["critical"]:
                alerts["critical"].append({"product": product, "qty": qty, "unit": d["unit"], "ratio": round(ratio*100,1)})
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
    alerts  = get_alerts(client)
    total   = len(client.get("inventory", {}))
    if total == 0: return 100
    penalty = len(alerts["critical"])*20 + len(alerts["expired"])*15 + len(alerts["expiring"])*5 + len(alerts["low"])*3
    return max(0, 100 - penalty)

# ─────────────────────────────────────────────
# KEYBOARDS
# ─────────────────────────────────────────────
def kb_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 Inventario",     callback_data="menu_inventory"),
         InlineKeyboardButton("🚨 Alertas",         callback_data="menu_alerts")],
        [InlineKeyboardButton("📊 Reportes",        callback_data="menu_reports"),
         InlineKeyboardButton("👥 Clientes",         callback_data="menu_clients")],
        [InlineKeyboardButton("➕ Agregar Producto", callback_data="menu_add_product")],
        [InlineKeyboardButton("🤖 Análisis IA",     callback_data="menu_ai"),
         InlineKeyboardButton("⚙️ Ajustes",         callback_data="menu_settings")],
    ])

def kb_back():
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Volver", callback_data="back_main")]])

def kb_clients(data, action="view"):
    clients = data.get("clients", {})
    if not clients: return None
    rows = []
    for cid, c in clients.items():
        emoji  = INDUSTRIES.get(c.get("industry", "restaurante"), {}).get("emoji", "📦")
        health = get_health(c)
        he     = "🟢" if health >= 75 else "🟡" if health >= 50 else "🔴"
        rows.append([InlineKeyboardButton(f"{he} {emoji} {c['name']}", callback_data=f"{action}_{cid}")])
    rows.append([InlineKeyboardButton("◀️ Volver", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)

def kb_industries():
    rows  = []
    items = list(INDUSTRIES.items())
    for i in range(0, len(items), 2):
        row = []
        for ind, prof in items[i:i+2]:
            row.append(InlineKeyboardButton(f"{prof['emoji']} {ind.replace('_',' ').title()}", callback_data=f"industry_{ind}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("◀️ Volver", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)

def kb_client_menu(cid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Ver Inventario",    callback_data=f"client_inv_{cid}"),
         InlineKeyboardButton("🚨 Ver Alertas",        callback_data=f"client_alerts_{cid}")],
        [InlineKeyboardButton("📉 Registrar Consumo", callback_data=f"client_consume_{cid}"),
         InlineKeyboardButton("✏️ Actualizar Stock",   callback_data=f"client_update_{cid}")],
        [InlineKeyboardButton("➕ Agregar Producto",   callback_data=f"client_addprod_{cid}"),
         InlineKeyboardButton("📄 Orden de Compra",    callback_data=f"client_order_{cid}")],
        [InlineKeyboardButton("🤖 Análisis IA",        callback_data=f"client_ai_{cid}"),
         InlineKeyboardButton("◀️ Volver",             callback_data="menu_clients")],
    ])

def kb_products(client, cid, action="update_prod"):
    rows = []
    for prod in client.get("inventory", {}).keys():
        rows.append([InlineKeyboardButton(f"📦 {prod}", callback_data=f"{action}_{cid}_{prod}")])
    rows.append([InlineKeyboardButton("◀️ Volver", callback_data=f"view_{cid}")])
    return InlineKeyboardMarkup(rows)

# ─────────────────────────────────────────────
# MAIN MENU
# ─────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 *NexoAI — Inventory Bot*\n"
        "_Where Agents Connect_\n\n"
        "Gestión inteligente de inventario\n"
        "para tu negocio en Puerto Rico.\n\n"
        "Selecciona una opción:"
    )
    if update.message:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb_main())
    else:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb_main())

# ─────────────────────────────────────────────
# CALLBACK HANDLER
# ─────────────────────────────────────────────
async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    data = q.data
    await q.answer()
    db   = load_data()

    # Navigation
    if data in ("back_main", "menu_main"):
        await cmd_start(update, ctx)
        return

    # ── Inventory ──────────────────────────────
    if data == "menu_inventory":
        clients = db.get("clients", {})
        if not clients:
            await q.edit_message_text(
                "📦 *Inventario*\n\nNo tienes clientes registrados.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ Agregar Cliente", callback_data="menu_add_client")],
                    [InlineKeyboardButton("◀️ Volver", callback_data="back_main")],
                ]))
        else:
            await q.edit_message_text(
                "📦 *Inventario*\n\nSelecciona un cliente:",
                parse_mode="Markdown",
                reply_markup=kb_clients(db, "view"))
        return

    # ── Alerts ─────────────────────────────────
    if data == "menu_alerts":
        clients = db.get("clients", {})
        if not clients:
            await q.edit_message_text("🚨 *Alertas*\n\nNo hay clientes registrados.", parse_mode="Markdown", reply_markup=kb_back())
            return
        msg        = "🚨 *Alertas Activas*\n\n"
        has_alerts = False
        for cid, c in clients.items():
            alerts = get_alerts(c)
            if any(alerts.values()):
                has_alerts = True
                emoji = INDUSTRIES.get(c.get("industry", "restaurante"), {}).get("emoji", "📦")
                msg  += f"{emoji} *{c['name']}*\n"
                for item in alerts["critical"]:
                    msg += f"  🔴 CRÍTICO: {item['product']} ({item['ratio']}%)\n"
                for item in alerts["expired"]:
                    msg += f"  ❌ VENCIDO: {item['product']}\n"
                for item in alerts["expiring"]:
                    msg += f"  ⚠️ Por vencer: {item['product']} ({item['days_left']} días)\n"
                for item in alerts["low"]:
                    msg += f"  📉 Stock bajo: {item['product']}\n"
                msg += "\n"
        if not has_alerts:
            msg += "✅ Todo en orden. Sin alertas activas."
        await q.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb_back())
        return

    # ── Reports ────────────────────────────────
    if data == "menu_reports":
        clients = db.get("clients", {})
        if not clients:
            await q.edit_message_text("📊 *Reportes*\n\nNo hay clientes.", parse_mode="Markdown", reply_markup=kb_back())
            return
        msg = "📊 *Reporte General*\n\n"
        for cid, c in clients.items():
            health = get_health(c)
            alerts = get_alerts(c)
            he     = "🟢" if health >= 75 else "🟡" if health >= 50 else "🔴"
            emoji  = INDUSTRIES.get(c.get("industry", "restaurante"), {}).get("emoji", "📦")
            total  = len(c.get("inventory", {}))
            value  = sum(d["qty"]*d.get("cost", 0) for d in c.get("inventory", {}).values())
            msg   += f"{emoji} *{c['name']}*\n"
            msg   += f"  {he} Salud: {health}/100 | Productos: {total}\n"
            if value > 0:
                msg += f"  💰 Valor: ${value:,.2f}\n"
            msg += f"  🚨 Críticos: {len(alerts['critical'])} | 📉 Bajos: {len(alerts['low'])}\n\n"
        await q.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb_back())
        return

    # ── Clients ────────────────────────────────
    if data == "menu_clients":
        clients = db.get("clients", {})
        if not clients:
            await q.edit_message_text(
                "👥 *Clientes*\n\nNo tienes clientes registrados.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ Agregar Cliente", callback_data="menu_add_client")],
                    [InlineKeyboardButton("◀️ Volver", callback_data="back_main")],
                ]))
        else:
            kb = kb_clients(db, "view")
            new_rows = kb.inline_keyboard + [[InlineKeyboardButton("➕ Nuevo Cliente", callback_data="menu_add_client")]]
            await q.edit_message_text(
                "👥 *Clientes*\n\nSelecciona un cliente:",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(new_rows))
        return

    if data == "menu_add_client":
        ctx.user_data["action"] = "add_client"
        ctx.user_data["step"]   = "name"
        await q.edit_message_text(
            "👥 *Nuevo Cliente*\n\n¿Cuál es el nombre del negocio?",
            parse_mode="Markdown",
            reply_markup=kb_back())
        return

    if data == "menu_add_product":
        clients = db.get("clients", {})
        if not clients:
            await q.edit_message_text("Primero agrega un cliente.", reply_markup=kb_back())
            return
        await q.edit_message_text(
            "➕ *Agregar Producto*\n\nSelecciona el cliente:",
            parse_mode="Markdown",
            reply_markup=kb_clients(db, "client_addprod"))
        return

    if data == "menu_ai":
        clients = db.get("clients", {})
        if not clients:
            await q.edit_message_text("🤖 No hay clientes para analizar.", parse_mode="Markdown", reply_markup=kb_back())
            return
        await q.edit_message_text(
            "🤖 *Análisis IA*\n\nSelecciona el cliente:",
            parse_mode="Markdown",
            reply_markup=kb_clients(db, "client_ai"))
        return

    if data == "menu_settings":
        await q.edit_message_text(
            "⚙️ *Configuración NexoAI*\n\n"
            "Bot: NexoAI Inventory v1.1\n"
            "CEO: Joshua López Almonte\n"
            "Puerto Rico, EE.UU.\n\n"
            f"Clientes activos: {len(db.get('clients', {}))}\n"
            f"Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M')}",
            parse_mode="Markdown",
            reply_markup=kb_back())
        return

    # ── View client ────────────────────────────
    if data.startswith("view_"):
        cid    = data[5:]
        c      = db.get("clients", {}).get(cid)
        if not c:
            await q.edit_message_text("Cliente no encontrado.", reply_markup=kb_back())
            return
        health = get_health(c)
        he     = "🟢" if health >= 75 else "🟡" if health >= 50 else "🔴"
        emoji  = INDUSTRIES.get(c.get("industry", "restaurante"), {}).get("emoji", "📦")
        value  = sum(d["qty"]*d.get("cost", 0) for d in c.get("inventory", {}).values())
        msg    = f"{emoji} *{c['name']}*\n"
        msg   += f"{he} Salud: {health}/100 | {c.get('industry','').title()}\n"
        msg   += f"📞 {c.get('contact', 'N/A')} | 📦 {len(c.get('inventory', {}))} productos\n"
        if value > 0:
            msg += f"💰 Valor: ${value:,.2f}\n"
        await q.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb_client_menu(cid))
        return

    # ── Client inventory ───────────────────────
    if data.startswith("client_inv_"):
        cid = data[11:]
        c   = db.get("clients", {}).get(cid)
        if not c or not c.get("inventory"):
            await q.edit_message_text(
                "📦 Sin productos registrados.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ Agregar Producto", callback_data=f"client_addprod_{cid}")],
                    [InlineKeyboardButton("◀️ Volver", callback_data=f"view_{cid}")],
                ]))
            return
        msg = f"📦 *Inventario — {c['name']}*\n\n"
        for prod, d in c.get("inventory", {}).items():
            qty, min_qty = d["qty"], d["min_qty"]
            ratio = (qty/min_qty*100) if min_qty > 0 else 100
            st    = "🔴" if ratio <= 20 else "🟡" if ratio <= 35 else "🟢"
            msg  += f"{st} *{prod}*: {qty} {d['unit']} (min: {min_qty})\n"
            if d.get("expiry_date"):
                msg += f"   📅 Vence: {d['expiry_date']}\n"
        await q.edit_message_text(msg, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Volver", callback_data=f"view_{cid}")]]))
        return

    # ── Client alerts ──────────────────────────
    if data.startswith("client_alerts_"):
        cid    = data[14:]
        c      = db.get("clients", {}).get(cid)
        alerts = get_alerts(c)
        health = get_health(c)
        he     = "🟢" if health >= 75 else "🟡" if health >= 50 else "🔴"
        msg    = f"🚨 *Alertas — {c['name']}*\n{he} Salud: {health}/100\n\n"
        if alerts["critical"]:
            msg += "🔴 *CRÍTICO:*\n"
            for i in alerts["critical"]:
                msg += f"  • {i['product']}: {i['qty']} {i['unit']} ({i['ratio']}%)\n"
            msg += "\n"
        if alerts["expired"]:
            msg += "❌ *VENCIDOS:*\n"
            for i in alerts["expired"]:
                msg += f"  • {i['product']}: venció hace {i['days']} días\n"
            msg += "\n"
        if alerts["expiring"]:
            msg += "⚠️ *Por vencer:*\n"
            for i in alerts["expiring"]:
                msg += f"  • {i['product']}: {i['days_left']} días\n"
            msg += "\n"
        if alerts["low"]:
            msg += "📉 *Stock bajo:*\n"
            for i in alerts["low"]:
                msg += f"  • {i['product']}: {i['qty']} {i['unit']}\n"
            msg += "\n"
        if not any(alerts.values()):
            msg += "✅ Sin alertas activas."
        await q.edit_message_text(msg, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Volver", callback_data=f"view_{cid}")]]))
        return

    # ── Registrar Consumo ──────────────────────
    if data.startswith("client_consume_"):
        cid = data[15:]
        c   = db.get("clients", {}).get(cid)
        if not c or not c.get("inventory"):
            await q.edit_message_text(
                "📉 Sin productos registrados.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Volver", callback_data=f"view_{cid}")]]))
            return
        nombre = c.get("name", "")
        await q.edit_message_text(
            f"📉 *Registrar Consumo — {nombre}*\n\n¿Qué producto usaste?",
            parse_mode="Markdown",
            reply_markup=kb_products(c, cid, "consume_prod"))
        return

    if data.startswith("consume_prod_"):
        rest = data[13:]
        cid  = None
        prod = None
        for client_id in db.get("clients", {}).keys():
            if rest.startswith(client_id + "_"):
                cid  = client_id
                prod = rest[len(client_id)+1:]
                break
        if not cid or not prod:
            await q.edit_message_text("❌ Error. Intenta de nuevo.", reply_markup=kb_back())
            return
        c       = db.get("clients", {}).get(cid, {})
        current = c.get("inventory", {}).get(prod, {})
        db["current_product"] = {"client_id": cid, "product": prod, "step": "consume_qty"}
        save_data(db)
        await q.edit_message_text(
            f"📉 *{prod}*\nStock actual: *{current.get('qty', 0)} {current.get('unit', '')}*\n\n¿Cuánto usaste?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Cancelar", callback_data=f"view_{cid}")]]))
        return

    # ── Add product ────────────────────────────
    if data.startswith("client_addprod_"):
        cid = data[15:]
        c   = db.get("clients", {}).get(cid)
        db["current_product"] = {"client_id": cid, "step": "name"}
        save_data(db)
        await q.edit_message_text(
            f"➕ *Agregar Producto — {c['name']}*\n\n¿Nombre del producto?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Cancelar", callback_data=f"view_{cid}")]]))
        return

    # ── Update stock ───────────────────────────
    if data.startswith("client_update_"):
        cid = data[14:]
        c   = db.get("clients", {}).get(cid)
        if not c or not c.get("inventory"):
            await q.edit_message_text("Sin productos.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Volver", callback_data=f"view_{cid}")]]))
            return
        await q.edit_message_text(
            f"✏️ *Actualizar Stock — {c['name']}*\n\nSelecciona el producto:",
            parse_mode="Markdown",
            reply_markup=kb_products(c, cid, "update_prod"))
        return

    if data.startswith("update_prod_"):
        rest = data[12:]
        cid  = None
        prod = None
        for client_id in db.get("clients", {}).keys():
            if rest.startswith(client_id + "_"):
                cid  = client_id
                prod = rest[len(client_id)+1:]
                break
        if not cid or not prod:
            await q.edit_message_text("❌ Error.", reply_markup=kb_back())
            return
        c       = db.get("clients", {}).get(cid, {})
        current = c.get("inventory", {}).get(prod, {})
        db["current_product"] = {"client_id": cid, "product": prod, "step": "update_qty"}
        save_data(db)
        await q.edit_message_text(
            f"✏️ *{prod}*\nStock actual: {current.get('qty', 0)} {current.get('unit', '')}\n\n¿Nueva cantidad total?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Cancelar", callback_data=f"view_{cid}")]]))
        return

    # ── AI Analysis ────────────────────────────
    if data.startswith("client_ai_"):
        cid = data[10:]
        c   = db.get("clients", {}).get(cid)
        await q.edit_message_text("🤖 Analizando... un momento...")
        try:
            alerts = get_alerts(c)
            health = get_health(c)
            claude = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
            resp   = claude.messages.create(
                model=MODEL, max_tokens=600,
                system=f"Eres el Inventory Agent de NexoAI para {c.get('industry','negocio')}s en Puerto Rico. Da recomendaciones concretas en español. Usa emojis. Max 300 palabras.",
                messages=[{"role": "user", "content":
                    f"Cliente: {c['name']} | Salud: {health}/100\n"
                    f"Críticos: {alerts['critical']}\nBajos: {alerts['low']}\n"
                    f"Vencidos: {alerts['expired']}\nInventario: {list(c.get('inventory',{}).keys())}"}])
            msg = f"🤖 *Análisis IA — {c['name']}*\n\n{resp.content[0].text}"
        except Exception as e:
            msg = f"🤖 Error: {e}"
        await q.edit_message_text(msg[:4000], parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Volver", callback_data=f"view_{cid}")]]))
        return

    # ── Purchase order ─────────────────────────
    if data.startswith("client_order_"):
        cid    = data[13:]
        c      = db.get("clients", {}).get(cid)
        alerts = get_alerts(c)
        items  = alerts["critical"] + alerts["low"]
        if not items:
            await q.edit_message_text(
                f"✅ *{c['name']}*\n\nInventario óptimo. Sin orden necesaria.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Volver", callback_data=f"view_{cid}")]]))
            return
        await q.edit_message_text("📄 Generando orden...")
        try:
            claude = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
            resp   = claude.messages.create(
                model=MODEL, max_tokens=500,
                system="Experto en compras para negocios en Puerto Rico. Orden de compra profesional en español.",
                messages=[{"role": "user", "content": f"Orden para {c['name']} ({c.get('industry')}): {items}"}])
            msg = f"📄 *Orden de Compra — {c['name']}*\n\n{resp.content[0].text}"
        except Exception as e:
            msg = f"Error: {e}"
        await q.edit_message_text(msg[:4000], parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Volver", callback_data=f"view_{cid}")]]))
        return

    # ── Industry selection ─────────────────────
    if data.startswith("industry_"):
        ind    = data[9:]
        action = ctx.user_data.get("action", "")
        if action == "add_client":
            name    = ctx.user_data.get("client_name", "Nuevo Cliente")
            contact = ctx.user_data.get("client_contact", "")
            cid     = f"client_{len(db.get('clients',{})) + 1:03d}"
            db.setdefault("clients", {})[cid] = {
                "name": name, "industry": ind,
                "contact": contact, "inventory": {},
                "created_at": datetime.now().isoformat()
            }
            save_data(db)
            emoji = INDUSTRIES[ind]["emoji"]
            await q.edit_message_text(
                f"✅ *Cliente agregado*\n\n{emoji} *{name}*\nIndustria: {ind.replace('_',' ').title()}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ Agregar Producto", callback_data=f"client_addprod_{cid}")],
                    [InlineKeyboardButton("👥 Ver Clientes",     callback_data="menu_clients")],
                    [InlineKeyboardButton("🏠 Inicio",           callback_data="back_main")],
                ]))
            ctx.user_data.clear()
        return

# ─────────────────────────────────────────────
# MESSAGE HANDLER
# ─────────────────────────────────────────────
async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text    = update.message.text.strip()
    db      = load_data()
    action  = ctx.user_data.get("action", "")
    product = db.get("current_product", {})

    # ── Add client flow ────────────────────────
    if action == "add_client":
        step = ctx.user_data.get("step", "name")
        if step == "name":
            ctx.user_data["client_name"] = text
            ctx.user_data["step"]        = "contact"
            await update.message.reply_text(
                f"👥 *{text}*\n\n¿Teléfono o contacto? (o escribe 'saltar')",
                parse_mode="Markdown")
        elif step == "contact":
            ctx.user_data["client_contact"] = "" if text.lower() == "saltar" else text
            ctx.user_data["step"]            = "industry"
            await update.message.reply_text(
                "🏭 *Selecciona la industria:*",
                parse_mode="Markdown",
                reply_markup=kb_industries())
        return

    # ── Add product flow ───────────────────────
    if product.get("step") == "name":
        product["name"] = text
        product["step"] = "qty"
        db["current_product"] = product
        save_data(db)
        await update.message.reply_text(f"📦 *{text}*\n\n¿Cantidad actual en stock?", parse_mode="Markdown")
        return

    if product.get("step") == "qty":
        try:
            product["qty"]  = float(text.replace(",", "."))
            product["step"] = "unit"
            db["current_product"] = product
            save_data(db)
            await update.message.reply_text(
                f"Cantidad: {product['qty']}\n\n¿Unidad de medida?\n_(libras, unidades, cajas, galones...)_",
                parse_mode="Markdown")
        except:
            await update.message.reply_text("⚠️ Solo el número. Ej: 50")
        return

    if product.get("step") == "unit":
        product["unit"] = text
        product["step"] = "min_qty"
        db["current_product"] = product
        save_data(db)
        await update.message.reply_text(
            f"Unidad: {text}\n\n¿Cantidad mínima para alertar?",
            parse_mode="Markdown")
        return

    if product.get("step") == "min_qty":
        try:
            product["min_qty"] = float(text.replace(",", "."))
            product["step"]    = "cost"
            db["current_product"] = product
            save_data(db)
            await update.message.reply_text("¿Costo por unidad? (o 'saltar')", parse_mode="Markdown")
        except:
            await update.message.reply_text("⚠️ Solo el número. Ej: 100")
        return

    if product.get("step") == "cost":
        try:
            product["cost"] = 0.0 if text.lower() == "saltar" else float(text.replace(",",".").replace("$",""))
            product["step"] = "expiry"
            db["current_product"] = product
            save_data(db)
            await update.message.reply_text("¿Fecha de vencimiento? (YYYY-MM-DD)\no 'saltar' si no aplica")
        except:
            await update.message.reply_text("⚠️ Solo el número o escribe 'saltar'")
        return

    if product.get("step") == "expiry":
        product["expiry_date"] = "" if text.lower() == "saltar" else text
        cid  = product.get("client_id")
        name = product.get("name", "Producto")
        db["clients"][cid]["inventory"][name] = {
            "qty":          product.get("qty", 0),
            "unit":         product.get("unit", "unidades"),
            "min_qty":      product.get("min_qty", 0),
            "cost":         product.get("cost", 0),
            "expiry_date":  product.get("expiry_date", ""),
            "category":     "general",
            "last_updated": datetime.now().isoformat()
        }
        db["current_product"] = {}
        save_data(db)
        await update.message.reply_text(
            f"✅ *Producto agregado*\n\n"
            f"📦 *{name}*\n"
            f"Stock: {product.get('qty')} {product.get('unit')}\n"
            f"Mínimo: {product.get('min_qty')}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Otro Producto", callback_data=f"client_addprod_{cid}")],
                [InlineKeyboardButton("📋 Ver Inventario", callback_data=f"client_inv_{cid}")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="back_main")],
            ]))
        return

    # ── Consume flow ───────────────────────────
    if product.get("step") == "consume_qty":
        try:
            consumed = float(text.replace(",", "."))
            cid      = product.get("client_id")
            prod     = product.get("product")
            if cid and prod and prod in db["clients"][cid]["inventory"]:
                old_qty = db["clients"][cid]["inventory"][prod]["qty"]
                new_qty = max(0, old_qty - consumed)
                unit    = db["clients"][cid]["inventory"][prod]["unit"]
                min_qty = db["clients"][cid]["inventory"][prod]["min_qty"]
                db["clients"][cid]["inventory"][prod]["qty"]          = new_qty
                db["clients"][cid]["inventory"][prod]["last_updated"] = datetime.now().isoformat()
                db["current_product"] = {}
                save_data(db)
                ratio  = (new_qty / min_qty * 100) if min_qty > 0 else 100
                status = "🔴 CRÍTICO — ¡Ordenar ya!" if ratio <= 20 else "🟡 BAJO — Ordenar pronto" if ratio <= 35 else "🟢 OK"
                msg = (
                    f"📉 *Consumo Registrado*\n\n"
                    f"📦 *{prod}*\n"
                    f"➖ Usaste: {consumed} {unit}\n"
                    f"Antes: {old_qty} {unit}\n"
                    f"Ahora: *{new_qty} {unit}*\n"
                    f"Estado: {status}"
                )
                await update.message.reply_text(
                    msg, parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📉 Registrar más consumo", callback_data=f"client_consume_{cid}")],
                        [InlineKeyboardButton("📋 Ver Inventario", callback_data=f"client_inv_{cid}")],
                        [InlineKeyboardButton("🏠 Inicio", callback_data="back_main")],
                    ]))
            else:
                await update.message.reply_text("❌ Error. Intenta de nuevo.")
        except:
            await update.message.reply_text("⚠️ Solo el número. Ej: 5")
        return

    # ── Update qty flow ────────────────────────
    if product.get("step") == "update_qty":
        try:
            new_qty = float(text.replace(",", "."))
            cid     = product.get("client_id")
            prod    = product.get("product")
            if cid and prod and prod in db["clients"][cid]["inventory"]:
                unit = db["clients"][cid]["inventory"][prod]["unit"]
                db["clients"][cid]["inventory"][prod]["qty"]          = new_qty
                db["clients"][cid]["inventory"][prod]["last_updated"] = datetime.now().isoformat()
                db["current_product"] = {}
                save_data(db)
                await update.message.reply_text(
                    f"✅ *Stock actualizado*\n\n📦 {prod}: {new_qty} {unit}",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📋 Ver Inventario", callback_data=f"client_inv_{cid}")],
                        [InlineKeyboardButton("🏠 Inicio", callback_data="back_main")],
                    ]))
            else:
                await update.message.reply_text("❌ Error.")
        except:
            await update.message.reply_text("⚠️ Solo el número. Ej: 75")
        return

    # ── Default ────────────────────────────────
    await update.message.reply_text(
        "🤖 *NexoAI*\n\nUsa el menú para navegar:",
        parse_mode="Markdown",
        reply_markup=kb_main())

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    print("NexoAI Inventory Bot v1.1 — Where Agents Connect")
    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN no configurado")
        return
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("menu",   cmd_start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("✅ Bot corriendo...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
