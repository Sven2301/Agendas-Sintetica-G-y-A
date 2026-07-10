from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from datetime import date, time
import os
import psycopg2

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

@app.get("/api/bookings")
def get_bookings(response: Response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    
    conn = get_db_connection()
    cursor = conn.cursor()
    # ⚙️ ACTUALIZADO: Ahora traemos el amount_paid de la base de datos
    cursor.execute("SELECT id, customer_name, booking_date, start_time, end_time, amount_paid FROM bookings")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    eventos_calendario = []
    for row in rows:
        booking_id, customer_name, booking_date, start_time, end_time, amount_paid = row
        eventos_calendario.append({
            "id": str(booking_id),
            "title": f"⚽ {customer_name}",
            "start": f"{booking_date}T{start_time}",
            "end": f"{booking_date}T{end_time}",
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

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)