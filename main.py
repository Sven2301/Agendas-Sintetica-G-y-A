from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Response
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from datetime import date, time, timedelta
import os
import psycopg2
import urllib.parse

app = FastAPI(title="Sintetica GyA API con WebSockets")

DATABASE_URL = os.getenv("DATABASE_URL")

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except:
                pass

manager = ConnectionManager()

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id SERIAL PRIMARY KEY,
            customer_name TEXT NOT NULL,
            booking_date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            amount_paid REAL NOT NULL
        )
    """)
    conn.commit()
    cursor.close()
    conn.close()

if DATABASE_URL:
    init_db()

class Booking(BaseModel):
    customer_name: str
    booking_date: date
    start_time: time
    end_time: time
    amount_paid: float

@app.get("/", response_class=HTMLResponse)
def read_root():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Archivo index.html no encontrado</h1>"

# 📷 RUTA PARA SERVIR EL LOGO OFICIAL
@app.get("/logo.png")
def get_logo():
    if os.path.exists("logo.png"):
        return FileResponse("logo.png")
    return Response(status_code=404)

@app.get("/api/bookings")
def get_bookings(response: Response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, customer_name, booking_date, start_time, end_time, amount_paid FROM bookings")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    eventos_calendario = []
    for row in rows:
        booking_id, customer_name, booking_date_val, start_time_val, end_time_val, amount_paid = row
        eventos_calendario.append({
            "id": str(booking_id),
            "title": f"⚽ {customer_name}",
            "start": f"{booking_date_val}T{start_time_val}",
            "end": f"{booking_date_val}T{end_time_val}",
            "extendedProps": {
                "customer_name": customer_name,
                "amount_paid": amount_paid
            }
        })
    return eventos_calendario

@app.post("/api/bookings")
async def create_booking(booking: Booking):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT customer_name FROM bookings 
        WHERE booking_date = %s AND start_time = %s
    """, (str(booking.booking_date), str(booking.start_time)))
    
    espacio_ocupado = cursor.fetchone()
    
    if espacio_ocupado:
        cursor.close()
        conn.close()
        return {"status": "error", "message": f"Horario ya ocupado por: {espacio_ocupado[0]}"}
    
    cursor.execute("""
        INSERT INTO bookings (customer_name, booking_date, start_time, end_time, amount_paid)
        VALUES (%s, %s, %s, %s, %s)
    """, (booking.customer_name, str(booking.booking_date), str(booking.start_time), str(booking.end_time), booking.amount_paid))
    conn.commit()
    cursor.close()
    conn.close()
    
    await manager.broadcast("refresh")
    return {"status": "success", "message": "Reserva guardada con éxito"}

@app.delete("/api/bookings/{booking_id}")
async def delete_booking(booking_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM bookings WHERE id = %s", (booking_id,))
    conn.commit()
    cursor.close()
    conn.close()
    
    await manager.broadcast("refresh")
    return {"status": "success", "message": "Reserva eliminada"}

@app.get("/api/fixed-clients")
def get_fixed_clients():
    today_str = date.today().isoformat()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT customer_name, booking_date, start_time, amount_paid 
        FROM bookings 
        WHERE customer_name LIKE '%%(Fijo%%' AND booking_date >= %s
        ORDER BY booking_date ASC, start_time ASC
    """, (today_str,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    clients_dict = {}
    for row in rows:
        full_name, b_date, s_time, amount = row
        base_name = full_name.split(" (Fijo")[0].strip()
        
        if base_name not in clients_dict:
            clients_dict[base_name] = {
                "base_name": base_name,
                "bookings_count": 0,
                "next_booking_date": b_date,
                "next_booking_time": s_time[:5],
                "amount_paid": amount
            }
        clients_dict[base_name]["bookings_count"] += 1

    return list(clients_dict.values())

@app.delete("/api/fixed-clients/{base_name}")
async def delete_fixed_client(base_name: str):
    today_str = date.today().isoformat()
    decoded_name = urllib.parse.unquote(base_name)
    conn = get_db_connection()
    cursor = conn.cursor()
    
    search_pattern = f"{decoded_name} (Fijo%"
    cursor.execute("""
        DELETE FROM bookings 
        WHERE (customer_name LIKE %s OR customer_name = %s) 
          AND booking_date >= %s
    """, (search_pattern, decoded_name, today_str))
    
    deleted_count = cursor.rowcount
    conn.commit()
    cursor.close()
    conn.close()
    
    await manager.broadcast("refresh")
    return {"status": "success", "message": f"Se eliminaron {deleted_count} reservas futuras de {decoded_name}"}

# 📊 MÓDULO DE ANALÍTICAS
@app.get("/api/analytics")
def get_analytics(
    type: str, 
    year: int = None, 
    month: int = None, 
    start_date: str = None, 
    end_date: str = None
):
    conn = get_db_connection()
    cursor = conn.cursor()
    today = date.today()

    if type == "today":
        query = "SELECT id, customer_name, booking_date, start_time, amount_paid FROM bookings WHERE booking_date = %s ORDER BY start_time ASC"
        params = (today.isoformat(),)
    elif type == "week":
        start_w = today - timedelta(days=today.weekday())
        end_w = start_w + timedelta(days=6)
        query = "SELECT id, customer_name, booking_date, start_time, amount_paid FROM bookings WHERE booking_date >= %s AND booking_date <= %s ORDER BY booking_date ASC, start_time ASC"
        params = (start_w.isoformat(), end_w.isoformat())
    elif type == "month":
        y = year or today.year
        m = month or today.month
        pattern = f"{y:04d}-{m:02d}-%"
        query = "SELECT id, customer_name, booking_date, start_time, amount_paid FROM bookings WHERE booking_date LIKE %s ORDER BY booking_date ASC, start_time ASC"
        params = (pattern,)
    elif type == "year":
        y = year or today.year
        pattern = f"{y:04d}-%"
        query = "SELECT id, customer_name, booking_date, start_time, amount_paid FROM bookings WHERE booking_date LIKE %s ORDER BY booking_date ASC, start_time ASC"
        params = (pattern,)
    elif type == "range":
        s_date = start_date or today.isoformat()
        e_date = end_date or today.isoformat()
        query = "SELECT id, customer_name, booking_date, start_time, amount_paid FROM bookings WHERE booking_date >= %s AND booking_date <= %s ORDER BY booking_date ASC, start_time ASC"
        params = (s_date, e_date)
    else:
        cursor.close()
        conn.close()
        return {"status": "error", "message": "Tipo de consulta no válido"}

    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    total_earnings = sum(row[4] for row in rows)
    bookings_count = len(rows)
    
    details = []
    for r in rows:
        details.append({
            "id": r[0],
            "customer_name": r[1],
            "booking_date": r[2],
            "start_time": r[3][:5],
            "amount_paid": r[4]
        })

    return {
        "status": "success",
        "total_earnings": total_earnings,
        "bookings_count": bookings_count,
        "average_per_booking": (total_earnings / bookings_count) if bookings_count > 0 else 0,
        "details": details
    }

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)