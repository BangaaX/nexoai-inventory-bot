# ============================================================
# NexoAI — Supabase Database Module
# Reemplaza el sistema JSON por Supabase
# ============================================================

import os
import json
import requests
from datetime import datetime

# ── CONFIGURACION ──────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://turvynjwnktsjnlsdnkb.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "sb_publishable_ROEBbAdq6FdpuFqYl2IFgg_sx-Ag-Bh")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

# ── SQL PARA CREAR LAS TABLAS ──────────────────────────────
# Ejecuta esto UNA VEZ en Supabase → SQL Editor
CREATE_TABLES_SQL = """
-- Tabla de clientes
CREATE TABLE IF NOT EXISTS clients (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    industry TEXT NOT NULL,
    phone TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Tabla de inventario
CREATE TABLE IF NOT EXISTS inventory (
    id SERIAL PRIMARY KEY,
    client_id TEXT REFERENCES clients(id) ON DELETE CASCADE,
    product TEXT NOT NULL,
    qty FLOAT DEFAULT 0,
    min_qty FLOAT DEFAULT 0,
    unit TEXT DEFAULT 'unidades',
    price FLOAT DEFAULT 0,
    expiry_date TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(client_id, product)
);

-- Tabla de historial de consumo
CREATE TABLE IF NOT EXISTS consumption_log (
    id SERIAL PRIMARY KEY,
    client_id TEXT REFERENCES clients(id) ON DELETE CASCADE,
    product TEXT NOT NULL,
    qty_consumed FLOAT NOT NULL,
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
"""

# ── FUNCIONES DE BASE DE DATOS ─────────────────────────────

def db_get(table, filters=None):
    """Lee registros de Supabase"""
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    if filters:
        url += "?" + "&".join([f"{k}=eq.{v}" for k, v in filters.items()])
    else:
        url += "?select=*"
    
    response = requests.get(url, headers=HEADERS)
    if response.status_code == 200:
        return response.json()
    return []

def db_insert(table, data):
    """Inserta un registro en Supabase"""
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    response = requests.post(url, headers=HEADERS, json=data)
    if response.status_code in [200, 201]:
        result = response.json()
        return result[0] if result else data
    return None

def db_update(table, filters, data):
    """Actualiza registros en Supabase"""
    url = f"{SUPABASE_URL}/rest/v1/{table}?"
    url += "&".join([f"{k}=eq.{v}" for k, v in filters.items()])
    data["updated_at"] = datetime.now().isoformat()
    response = requests.patch(url, headers=HEADERS, json=data)
    return response.status_code in [200, 204]

def db_delete(table, filters):
    """Elimina registros de Supabase"""
    url = f"{SUPABASE_URL}/rest/v1/{table}?"
    url += "&".join([f"{k}=eq.{v}" for k, v in filters.items()])
    response = requests.delete(url, headers=HEADERS)
    return response.status_code in [200, 204]

# ── FUNCIONES DE CLIENTES ──────────────────────────────────

def get_all_clients():
    """Retorna todos los clientes como diccionario {id: client_data}"""
    clients_raw = db_get("clients")
    clients = {}
    
    for c in clients_raw:
        cid = c["id"]
        # Cargar inventario del cliente
        inventory_raw = db_get("inventory", {"client_id": cid})
        inventory = {}
        for item in inventory_raw:
            inventory[item["product"]] = {
                "qty": item["qty"],
                "min_qty": item["min_qty"],
                "unit": item["unit"],
                "price": item["price"],
                "expiry_date": item.get("expiry_date")
            }
        
        clients[cid] = {
            "name": c["name"],
            "industry": c["industry"],
            "phone": c.get("phone", ""),
            "inventory": inventory
        }
    
    return clients

def save_client(cid, client_data):
    """Guarda o actualiza un cliente"""
    existing = db_get("clients", {"id": cid})
    
    client_record = {
        "id": cid,
        "name": client_data["name"],
        "industry": client_data["industry"],
        "phone": client_data.get("phone", "")
    }
    
    if existing:
        db_update("clients", {"id": cid}, client_record)
    else:
        db_insert("clients", client_record)
    
    # Guardar inventario
    for product, item in client_data.get("inventory", {}).items():
        save_product(cid, product, item)

def save_product(cid, product, item_data):
    """Guarda o actualiza un producto del inventario"""
    existing = db_get("inventory", {"client_id": cid})
    exists = any(i["product"] == product for i in existing)
    
    record = {
        "client_id": cid,
        "product": product,
        "qty": item_data.get("qty", 0),
        "min_qty": item_data.get("min_qty", 0),
        "unit": item_data.get("unit", "unidades"),
        "price": item_data.get("price", 0),
        "expiry_date": item_data.get("expiry_date")
    }
    
    if exists:
        db_update("inventory", {"client_id": cid, "product": product}, record)
    else:
        db_insert("inventory", record)

def log_consumption(cid, product, qty, notes=""):
    """Registra consumo en el historial"""
    db_insert("consumption_log", {
        "client_id": cid,
        "product": product,
        "qty_consumed": qty,
        "notes": notes
    })

# ── COMPATIBILIDAD CON EL BOT ACTUAL ──────────────────────
# Estas funciones reemplazan load_data() y save_data()

def load_data():
    """
    Reemplaza la funcion load_data() original.
    Carga todos los datos desde Supabase.
    """
    try:
        clients = get_all_clients()
        return {"clients": clients, "current_product": {}}
    except Exception as e:
        print(f"[Supabase] Error cargando datos: {e}")
        return {"clients": {}, "current_product": {}}

def save_data(data):
    """
    Reemplaza la funcion save_data() original.
    Guarda todos los clientes en Supabase.
    """
    try:
        for cid, client_data in data.get("clients", {}).items():
            save_client(cid, client_data)
    except Exception as e:
        print(f"[Supabase] Error guardando datos: {e}")

# ── MIGRACION DESDE JSON ───────────────────────────────────

def migrate_from_json(json_file="inventory_data.json"):
    """
    Migra datos existentes del archivo JSON a Supabase.
    Ejecuta esto UNA SOLA VEZ.
    """
    if not os.path.exists(json_file):
        print(f"[Migración] Archivo {json_file} no encontrado")
        return False
    
    try:
        with open(json_file) as f:
            data = json.load(f)
        
        clients = data.get("clients", {})
        print(f"[Migración] Migrando {len(clients)} clientes...")
        
        for cid, client_data in clients.items():
            save_client(cid, client_data)
            print(f"[Migración] ✅ {client_data['name']} migrado")
        
        print(f"[Migración] ✅ Completado — {len(clients)} clientes migrados a Supabase")
        return True
        
    except Exception as e:
        print(f"[Migración] ❌ Error: {e}")
        return False

# ── TEST DE CONEXION ───────────────────────────────────────

def test_connection():
    """Verifica que la conexion a Supabase funciona"""
    try:
        result = db_get("clients")
        print(f"[Supabase] ✅ Conexión exitosa — {len(result)} clientes en base de datos")
        return True
    except Exception as e:
        print(f"[Supabase] ❌ Error de conexión: {e}")
        return False

if __name__ == "__main__":
    print("=== NexoAI — Test Supabase ===")
    test_connection()
