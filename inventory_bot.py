"""
╔══════════════════════════════════════════════════════════════╗
║           NEXOAI — INVENTORY BOT v1.0                        ║
║         Bot de Inventario con Menús Interactivos             ║
║              by Joshua Lopez Almonte                         ║
╚══════════════════════════════════════════════════════════════╝

Setup:
  pip install python-telegram-bot==20.7 python-dotenv requests

.env:
  TELEGRAM_BOT_TOKEN= 
  TELEGRAM_CHAT_ID= 
  ANTHROPIC_API_KEY= 
"""

import os
import json
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
import anthropic

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
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

# Conversation states
WAITING_CLIENT_NAME    = 1
WAITING_CLIENT_INDUSTRY = 2
WAITING_PRODUCT_NAME   = 3
WAITING_PRODUCT_QTY    = 4
WAITING_PRODUCT_UNIT   = 5
WAITING_PRODUCT_MIN    = 6
WAITING_PRODUCT_COST   = 7
WAITING_PRODUCT_EXPIRY = 8
WAITING_UPDATE_QTY     = 9
WAITING_WALLET_SEARCH  = 10

# Industry profiles
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
# DATA LAYER
# ─────────────────────────────────────────────
def load_data() -> dict:
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE) as f:
                return json.load(f)
        except:
            pass
    return {"clients": {}, "current_client": None, "current_product": {}}

def save_data(data: dict):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_alerts(client: dict) -> dict:
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

def get_health(client: dict) -> int:
    alerts = get_alerts(client)
    total  = len(client.get("inventory", {}))
    if total == 0: return 100
    penalty = len(alerts["critical"])*20 + len(alerts["expired"])*15 + len(alerts["expiring"])*5 + len(alerts["low"])*3
    return max(0, 100 - penalty)

# ─────────────────────────────────────────────
# KEYBOARDS
# ─────────────────────────────────────────────
def kb_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 Inventario",    callback_data="menu_inventory"),
         InlineKeyboardButton("🚨 Alertas",        callback_data="menu_alerts")],
        [InlineKeyboardButton("📊 Reportes",       callback_data="menu_reports"),
         InlineKeyboardButton("👥 Clientes",        callback_data="menu_clients")],
        [InlineKeyboardButton("➕ Agregar Producto",callback_data="menu_add_product")],
        [InlineKeyboardButton("🤖 Análisis IA",    callback_data="menu_ai"),
         InlineKeyboardButton("⚙️ Ajustes",        callback_data="menu_settings")],
    ])

def kb_back(to="main"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Volver", callback_data=f"back_{to}")]])

def kb_clients(data: dict, action: str = "view"):
    clients = data.get("clients", {})
    if not clients:
        return None
    rows = []
    for cid, c in clients.items():
        emoji = INDUSTRIES.get(c.get("industry","restaurante"), {}).get("emoji","📦")
        health = get_health(c)
        he = "🟢" if health >= 75 else "🟡" if health >= 50 else "🔴"
        rows.append([InlineKeyboardButton(
            f"{he} {emoji} {c['name']}",
            callback_data=f"{action}_{cid}"
        )])
    rows.append([InlineKeyboardButton("◀️ Volver", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)

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

def kb_client_menu(cid: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Ver Inventario",    callback_data=f"client_inv_{cid}"),
         InlineKeyboardButton("🚨 Ver Alertas",        callback_data=f"client_alerts_{cid}")],
        [InlineKeyboardButton("➕ Agregar Producto",   callback_data=f"client_addprod_{cid}"),
         InlineKeyboardButton("✏️ Actualizar Stock",   callback_data=f"client_update_{cid}")],
        [InlineKeyboardButton("🤖 Análisis IA",        callback_data=f"client_ai_{cid}"),
         InlineKeyboardButton("📄 Orden de Compra",    callback_data=f"client_order_{cid}")],
        [InlineKeyboardButton("◀️ Volver",             callback_data="menu_clients")],
    ])

def kb_products(client: dict, cid: str, action: str = "update"):
    rows = []
    for prod in client.get("inventory", {}).keys():
        rows.append([InlineKeyboardButton(f"📦 {prod}", callback_data=f"{action}_{cid}_{prod}")])
    rows.append([InlineKeyboardButton("◀️ Volver", callback_data=f"view_{cid}")])
    return InlineKeyboardMarkup(rows)

# ─────────────────────────────────────────────
# HANDLERS — MAIN MENU
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

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    data = q.data
    await q.answer()
    db   = load_data()

    # ── Back navigation ────────────────────────
    if data == "back_main" or data == "menu_main":
        await cmd_start(update, ctx)
        return

    # ── Main menu ──────────────────────────────
    if data == "menu_inventory":
        clients = db.get("clients", {})
        if not clients:
            await q.edit_message_text(
                "📦 *Inventario*\n\nNo tienes clientes registrados aún.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ Agregar Cliente", callback_data="menu_add_client")],
                    [InlineKeyboardButton("◀️ Volver", callback_data="back_main")],
                ])
            )
        else:
            await q.edit_message_text(
                "📦 *Inventario*\n\nSelecciona un cliente:",
                parse_mode="Markdown",
                reply_markup=kb_clients(db, "view")
            )
        return

    if data == "menu_alerts":
        clients = db.get("clients", {})
        if not clients:
            await q.edit_message_text("🚨 *Alertas*\n\nNo hay clientes registrados.",
                parse_mode="Markdown", reply_markup=kb_back())
            return
        msg = "🚨 *Alertas Activas*\n\n"
        has_alerts = False
        for cid, c in clients.items():
            alerts = get_alerts(c)
            if any(alerts.values()):
                has_alerts = True
                emoji = INDUSTRIES.get(c.get("industry","restaurante"),{}).get("emoji","📦")
                msg += f"{emoji} *{c['name']}*\n"
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

    if data == "menu_reports":
        clients = db.get("clients", {})
        if not clients:
            await q.edit_message_text("📊 *Reportes*\n\nNo hay clientes registrados.",
                parse_mode="Markdown", reply_markup=kb_back())
            return
        msg = "📊 *Reporte General*\n\n"
        for cid, c in clients.items():
            health = get_health(c)
            alerts = get_alerts(c)
            he = "🟢" if health >= 75 else "🟡" if health >= 50 else "🔴"
            emoji = INDUSTRIES.get(c.get("industry","restaurante"),{}).get("emoji","📦")
            total = len(c.get("inventory", {}))
            value = sum(d["qty"]*d.get("cost",0) for d in c.get("inventory",{}).values())
            msg += f"{emoji} *{c['name']}*\n"
            msg += f"  {he} Salud: {health}/100\n"
            msg += f"  📦 Productos: {total}\n"
            if value > 0:
                msg += f"  💰 Valor: ${value:,.2f}\n"
            msg += f"  🚨 Críticos: {len(alerts['critical'])} | 📉 Bajos: {len(alerts['low'])}\n\n"
        await q.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb_back())
        return

    if data == "menu_clients":
        clients = db.get("clients", {})
        if not clients:
            await q.edit_message_text(
                "👥 *Clientes*\n\nNo tienes clientes registrados.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ Agregar Cliente", callback_data="menu_add_client")],
                    [InlineKeyboardButton("◀️ Volver", callback_data="back_main")],
                ])
            )
        else:
            msg = "👥 *Clientes Registrados*\n\nSelecciona un cliente para ver opciones:"
            kb = kb_clients(db, "view")
            # Add new client button
            new_rows = kb.inline_keyboard + [[InlineKeyboardButton("➕ Nuevo Cliente", callback_data="menu_add_client")]]
            await q.edit_message_text(msg, parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(new_rows))
        return

    if data == "menu_add_client":
        ctx.user_data["action"] = "add_client"
        await q.edit_message_text(
            "👥 *Nuevo Cliente*\n\n¿Cuál es el nombre del negocio?",
            parse_mode="Markdown",
            reply_markup=kb_back()
        )
        return ConversationHandler.END

    if data == "menu_add_product":
        clients = db.get("clients", {})
        if not clients:
            await q.edit_message_text("📦 Primero agrega un cliente.",
                parse_mode="Markdown", reply_markup=kb_back())
            return
        await q.edit_message_text(
            "➕ *Agregar Producto*\n\nSelecciona el cliente:",
            parse_mode="Markdown",
            reply_markup=kb_clients(db, "client_addprod")
        )
        return

    if data == "menu_ai":
        clients = db.get("clients", {})
        if not clients:
            await q.edit_message_text("🤖 No hay clientes para analizar.",
                parse_mode="Markdown", reply_markup=kb_back())
            return
        await q.edit_message_text(
            "🤖 *Análisis IA*\n\nSelecciona el cliente a analizar:",
            parse_mode="Markdown",
            reply_markup=kb_clients(db, "client_ai")
        )
        return

    if data == "menu_settings":
        await q.edit_message_text(
            "⚙️ *Configuración NexoAI*\n\n"
            "• Bot: NexoAI Inventory v1.0\n"
            "• CEO: Joshua López Almonte\n"
            "• Puerto Rico, EE.UU.\n\n"
            f"• Clientes activos: {len(db.get('clients',{}))}\n"
            f"• Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M')}",
            parse_mode="Markdown",
            reply_markup=kb_back()
        )
        return

    # ── Client view ────────────────────────────
    if data.startswith("view_"):
        cid = data[5:]
        c   = db.get("clients", {}).get(cid)
        if not c:
            await q.edit_message_text("Cliente no encontrado.", reply_markup=kb_back())
            return
        health = get_health(c)
        he     = "🟢" if health >= 75 else "🟡" if health >= 50 else "🔴"
        emoji  = INDUSTRIES.get(c.get("industry","restaurante"),{}).get("emoji","📦")
        msg    = f"{emoji} *{c['name']}*\n"
        msg   += f"{he} Salud: {health}/100 | {c.get('industry','').title()}\n\n"
        msg   += f"📞 Contacto: {c.get('contact', 'N/A')}\n"
        msg   += f"📦 Productos: {len(c.get('inventory', {}))}\n"
        value  = sum(d["qty"]*d.get("cost",0) for d in c.get("inventory",{}).values())
        if value > 0:
            msg += f"💰 Valor inventario: ${value:,.2f}\n"
        msg   += f"\n_Selecciona una opción:_"
        await q.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb_client_menu(cid))
        return

    # ── Client inventory ───────────────────────
    if data.startswith("client_inv_"):
        cid = data[11:]
        c   = db.get("clients", {}).get(cid)
        if not c or not c.get("inventory"):
            await q.edit_message_text("📦 Sin productos registrados.",
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
            msg  += f"{st} *{prod}*\n"
            msg  += f"   Stock: {qty} {d['unit']} | Mínimo: {min_qty}\n"
            if d.get("expiry_date"):
                msg += f"   📅 Vence: {d['expiry_date']}\n"
            if d.get("cost", 0) > 0:
                msg += f"   💰 Costo: ${d['cost']}\n"
            msg += "\n"
        await q.edit_message_text(msg, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Volver", callback_data=f"view_{cid}")]
            ]))
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
            msg += "🔴 *CRÍTICO — Ordenar HOY:*\n"
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
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Volver", callback_data=f"view_{cid}")]
            ]))
        return

    # ── Add product to client ──────────────────
    if data.startswith("client_addprod_"):
        cid = data[15:]
        c   = db.get("clients", {}).get(cid)
        db["current_product"] = {"client_id": cid, "step": "name"}
        save_data(db)
        await q.edit_message_text(
            f"➕ *Agregar Producto — {c['name']}*\n\n¿Nombre del producto?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Cancelar", callback_data=f"view_{cid}")]])
        )
        return

    # ── Update stock ───────────────────────────
    if data.startswith("client_update_"):
        cid = data[14:]
        c   = db.get("clients", {}).get(cid)
        if not c or not c.get("inventory"):
            await q.edit_message_text("Sin productos para actualizar.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Volver", callback_data=f"view_{cid}")]]))
            return
        await q.edit_message_text(
            f"✏️ *Actualizar Stock — {c['name']}*\n\nSelecciona el producto:",
            parse_mode="Markdown",
            reply_markup=kb_products(c, cid, "update_prod")
        )
        return

    if data.startswith("update_prod_"):
        parts = data[12:].rsplit("_", 1)
        cid, prod = parts[0], parts[1]
        # Handle product names with underscores
        # Find the right split by matching client id
        db["current_product"] = {"client_id": cid, "product": prod, "step": "update_qty"}
        save_data(db)
        c = db.get("clients", {}).get(cid, {})
        current = c.get("inventory", {}).get(prod, {})
        await q.edit_message_text(
            f"✏️ *{prod}*\nStock actual: {current.get('qty', 0)} {current.get('unit', '')}\n\n¿Nueva cantidad?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Cancelar", callback_data=f"view_{cid}")]])
        )
        return

    # ── AI Analysis ────────────────────────────
    if data.startswith("client_ai_"):
        cid = data[10:]
        c   = db.get("clients", {}).get(cid)
        await q.edit_message_text("🤖 Analizando con IA... un momento...", parse_mode="Markdown")

        try:
            alerts  = get_alerts(c)
            health  = get_health(c)
            profile = INDUSTRIES.get(c.get("industry","restaurante"), {})

            claude   = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
            response = claude.messages.create(
                model=MODEL, max_tokens=600,
                system=f"""Eres el Inventory Agent de NexoAI para {c.get('industry','negocio')}s en Puerto Rico.
Analiza el inventario y da recomendaciones concretas y accionables en español.
Sé directo, usa emojis, máximo 300 palabras.""",
                messages=[{"role": "user", "content":
                    f"Cliente: {c['name']} | Industria: {c.get('industry')}\n"
                    f"Salud: {health}/100\n"
                    f"Críticos: {json.dumps(alerts['critical'])}\n"
                    f"Bajos: {json.dumps(alerts['low'])}\n"
                    f"Vencidos: {json.dumps(alerts['expired'])}\n"
                    f"Por vencer: {json.dumps(alerts['expiring'])}\n"
                    f"Inventario: {json.dumps(c.get('inventory',{}))[:500]}"}])

            analysis = response.content[0].text
            msg = f"🤖 *Análisis IA — {c['name']}*\n\n{analysis}"
        except Exception as e:
            msg = f"🤖 Error en análisis: {e}"

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
                f"✅ *{c['name']}*\n\nInventario en niveles óptimos.\nNo se necesita orden de compra.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Volver", callback_data=f"view_{cid}")]]))
            return

        await q.edit_message_text("📄 Generando orden de compra...", parse_mode="Markdown")

        try:
            claude   = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
            response = claude.messages.create(
                model=MODEL, max_tokens=500,
                system="Eres experto en compras para negocios en Puerto Rico. Genera orden de compra profesional y concisa en español.",
                messages=[{"role": "user", "content":
                    f"Genera orden para {c['name']} ({c.get('industry')}):\nProductos: {json.dumps(items)}"}])
            order = response.content[0].text
            msg   = f"📄 *Orden de Compra — {c['name']}*\n\n{order}"
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
                f"✅ *Cliente agregado*\n\n{emoji} *{name}*\nIndustria: {ind.replace('_',' ').title()}\nID: `{cid}`",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ Agregar Producto", callback_data=f"client_addprod_{cid}")],
                    [InlineKeyboardButton("👥 Ver Clientes", callback_data="menu_clients")],
                    [InlineKeyboardButton("🏠 Inicio", callback_data="back_main")],
                ])
            )
            ctx.user_data.clear()
        return


# ─────────────────────────────────────────────
# MESSAGE HANDLER (text inputs)
# ─────────────────────────────────────────────
async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    db   = load_data()

    action  = ctx.user_data.get("action", "")
    product = db.get("current_product", {})

    # ── Add client flow ────────────────────────
    if action == "add_client":
        step = ctx.user_data.get("step", "name")
        if step == "name":
            ctx.user_data["client_name"] = text
            ctx.user_data["step"]        = "contact"
            await update.message.reply_text(
                f"👥 *{text}*\n\n¿Número de teléfono o contacto? (o escribe 'saltar')",
                parse_mode="Markdown"
            )
        elif step == "contact":
            ctx.user_data["client_contact"] = "" if text.lower() == "saltar" else text
            ctx.user_data["step"]            = "industry"
            await update.message.reply_text(
                "🏭 *Selecciona la industria:*",
                parse_mode="Markdown",
                reply_markup=kb_industries()
            )
        return

    # ── Add product flow ───────────────────────
    if product.get("step") == "name":
        product["name"] = text
        product["step"] = "qty"
        db["current_product"] = product
        save_data(db)
        await update.message.reply_text(
            f"📦 *{text}*\n\n¿Cantidad actual en stock?",
            parse_mode="Markdown"
        )
        return

    if product.get("step") == "qty":
        try:
            product["qty"]  = float(text.replace(",", "."))
            product["step"] = "unit"
            db["current_product"] = product
            save_data(db)
            await update.message.reply_text(
                f"📦 Cantidad: {product['qty']}\n\n¿Unidad de medida?\n_(libras, unidades, cajas, galones, etc.)_",
                parse_mode="Markdown"
            )
        except:
            await update.message.reply_text("⚠️ Escribe solo el número. Ej: 50")
        return

    if product.get("step") == "unit":
        product["unit"] = text
        product["step"] = "min_qty"
        db["current_product"] = product
        save_data(db)
        await update.message.reply_text(
            f"📦 Unidad: {text}\n\n¿Cantidad mínima antes de alertar?\n_(cuando baje de este número te aviso)_",
            parse_mode="Markdown"
        )
        return

    if product.get("step") == "min_qty":
        try:
            product["min_qty"] = float(text.replace(",", "."))
            product["step"]    = "cost"
            db["current_product"] = product
            save_data(db)
            await update.message.reply_text(
                f"📦 Mínimo: {product['min_qty']}\n\n¿Costo por unidad? (o escribe 'saltar')",
                parse_mode="Markdown"
            )
        except:
            await update.message.reply_text("⚠️ Escribe solo el número. Ej: 100")
        return

    if product.get("step") == "cost":
        product["cost"] = 0.0 if text.lower() == "saltar" else float(text.replace(",",".").replace("$",""))
        product["step"] = "expiry"
        db["current_product"] = product
        save_data(db)
        await update.message.reply_text(
            f"📅 ¿Fecha de vencimiento? (formato: YYYY-MM-DD)\no escribe 'saltar' si no aplica",
            parse_mode="Markdown"
        )
        return

    if product.get("step") == "expiry":
        product["expiry_date"] = "" if text.lower() == "saltar" else text
        cid  = product.get("client_id")
        c    = db.get("clients", {}).get(cid)
        name = product.get("name", "Producto")

        db["clients"][cid]["inventory"][name] = {
            "qty":         product.get("qty", 0),
            "unit":        product.get("unit", "unidades"),
            "min_qty":     product.get("min_qty", 0),
            "cost":        product.get("cost", 0),
            "expiry_date": product.get("expiry_date", ""),
            "category":    "general",
            "last_updated": datetime.now().isoformat()
        }
        db["current_product"] = {}
        save_data(db)

        await update.message.reply_text(
            f"✅ *Producto agregado*\n\n"
            f"📦 *{name}*\n"
            f"Stock: {product.get('qty')} {product.get('unit')}\n"
            f"Mínimo: {product.get('min_qty')}\n"
            f"Cliente: {c['name']}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Otro Producto", callback_data=f"client_addprod_{cid}")],
                [InlineKeyboardButton("📋 Ver Inventario", callback_data=f"client_inv_{cid}")],
                [InlineKeyboardButton("🏠 Inicio", callback_data="back_main")],
            ])
        )
        return

    # ── Update qty flow ────────────────────────
    if product.get("step") == "update_qty":
        try:
            new_qty = float(text.replace(",","."))
            cid     = product.get("client_id")
            prod    = product.get("product")
            if cid and prod and prod in db["clients"][cid]["inventory"]:
                db["clients"][cid]["inventory"][prod]["qty"]          = new_qty
                db["clients"][cid]["inventory"][prod]["last_updated"] = datetime.now().isoformat()
                db["current_product"] = {}
                save_data(db)
                await update.message.reply_text(
                    f"✅ *Stock actualizado*\n\n📦 {prod}: {new_qty} {db['clients'][cid]['inventory'][prod]['unit']}",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📋 Ver Inventario", callback_data=f"client_inv_{cid}")],
                        [InlineKeyboardButton("🏠 Inicio", callback_data="back_main")],
                    ])
                )
            else:
                await update.message.reply_text("❌ Error actualizando. Intenta de nuevo.")
        except:
            await update.message.reply_text("⚠️ Escribe solo el número. Ej: 75")
        return

    # ── Add client name trigger ────────────────
    if text.lower() in ["nuevo cliente", "/addclient", "agregar cliente"]:
        ctx.user_data["action"] = "add_client"
        ctx.user_data["step"]   = "name"
        await update.message.reply_text(
            "👥 *Nuevo Cliente*\n\n¿Cuál es el nombre del negocio?",
            parse_mode="Markdown"
        )
        return

    # ── Default ────────────────────────────────
    await update.message.reply_text(
        "🤖 *NexoAI*\n\nUsa el menú para navegar:",
        parse_mode="Markdown",
        reply_markup=kb_main()
    )


# ─────────────────────────────────────────────
# ADD CLIENT via callback (text input trigger)
# ─────────────────────────────────────────────
async def handle_add_client_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data["action"] = "add_client"
    ctx.user_data["step"]   = "name"
    await q.edit_message_text(
        "👥 *Nuevo Cliente*\n\n¿Cuál es el nombre del negocio?",
        parse_mode="Markdown"
    )


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    print("""
╔══════════════════════════════════════════════════════╗
║       NexoAI — Inventory Bot v1.0                    ║
║       Where Agents Connect                           ║
║       CEO: Joshua Lopez Almonte                      ║
╚══════════════════════════════════════════════════════╝
    """)

    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN no configurado")
        return

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("menu",    cmd_start))
    app.add_handler(CommandHandler("inicio",  cmd_start))
    app.add_handler(CallbackQueryHandler(handle_add_client_callback, pattern="^menu_add_client$"))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ NexoAI Inventory Bot corriendo...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
