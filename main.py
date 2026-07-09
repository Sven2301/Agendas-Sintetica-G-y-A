from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from datetime import date, time
import os
import sqlite3

app = FastAPI(title="SinteticaSync API con WebSockets")
DB_FILE = "sintetica.db"

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

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            booking_date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            amount_paid REAL NOT NULL
        )
    """)
    conn.commit()
    conn.close()

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

# 🛡️ ANTI-CACHÉ: Obligamos al navegador a no guardar copias viejas de la base de datos
@app.get("/api/bookings")
def get_bookings(response: Response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, customer_name, booking_date, start_time, end_time FROM bookings")
    rows = cursor.fetchall()
    conn.close()

    eventos_calendario = []
    for row in rows:
        booking_id, customer_name, booking_date, start_time, end_time = row
        eventos_calendario.append({
            "id": str(booking_id),
            "title": f"⚽ {customer_name}",
            "start": f"{booking_date}T{start_time}",
            "end": f"{booking_date}T{end_time}"
        })
    return eventos_calendario

@app.post("/api/bookings")
async def create_booking(booking: Booking):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO bookings (customer_name, booking_date, start_time, end_time, amount_paid)
        VALUES (?, ?, ?, ?, ?)
    """, (booking.customer_name, str(booking.booking_date), str(booking.start_time), str(booking.end_time), booking.amount_paid))
    conn.commit()
    conn.close()
    
    await manager.broadcast("refresh")
    return {"status": "success", "message": "Reserva guardada"}

@app.delete("/api/bookings/{booking_id}")
async def delete_booking(booking_id: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
    conn.commit()
    conn.close()
    
    await manager.broadcast("refresh")
    return {"status": "success", "message": "Reserva eliminada"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)