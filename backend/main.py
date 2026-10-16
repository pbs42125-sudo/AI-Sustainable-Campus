import os
import io
import asyncio
import sqlite3
import json
import requests
import numpy as np
import cv2
from datetime import datetime
from typing import Dict, Any
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from PIL import Image, ImageDraw
from ultralytics import YOLO
from google import genai

app = FastAPI(title="EcoPulse AI - Multi-Node Campus Surveillance Grid")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

cv_executor = ThreadPoolExecutor(max_workers=2)

# ---------------------------------------------------------
# GEMINI & WHATSAPP CONFIGURATION
# ---------------------------------------------------------
GEMINI_API_KEY = "AIzaSyBAXu8b4xC7-imgnaIEwwEoa1haNxiFGbY"
try:
    genai_client = genai.Client(api_key=GEMINI_API_KEY)
    print("\n✓ Google Generative AI (Gemini) ready.")
except Exception as e:
    print(f"GenAI Init Warning: {e}")
    genai_client = None

GREEN_API_HOST = "https://7107.api.greenapi.com"
GREEN_API_ID_INSTANCE = "710722769366"
GREEN_API_TOKEN = "733d94b68a4c4d24a7de553ac7219ffe565f6a595b9b4b6d9d"
MAX_ALERT_COUNT = 2
ALERT_COOLDOWN_SECONDS = 60

# ---------------------------------------------------------
# YOLOV8 INITIALIZATION
# ---------------------------------------------------------
possible_paths = [
    os.path.join(os.path.dirname(__file__), "..", "yolov8n.pt"),
    os.path.join(os.path.dirname(__file__), "yolov8n.pt"),
    "yolov8n.pt"
]
model_path = next((p for p in possible_paths if os.path.exists(p)), "yolov8n.pt")
try:
    print(f"[SYSTEM] Loading YOLOv8 from: {os.path.abspath(model_path)}")
    model = YOLO(model_path)
    print("✓ YOLOv8 Engine initialized.\n")
except Exception as e:
    print(f"YOLO load warning: {e}")
    model = None

# ---------------------------------------------------------
# SQLITE LEDGER SETUP & AUTOMATIC SCHEMA MIGRATION
# ---------------------------------------------------------
DB_PATH = os.path.join(os.path.dirname(__file__), "database.db")

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            source TEXT,
            item_or_event TEXT,
            status_or_category TEXT,
            impact TEXT,
            ai_summary TEXT
        )
    """)
    conn.commit()

    # Automatically check and add ai_summary column if an old database exists
    cur.execute("PRAGMA table_info(audit_logs)")
    columns = [row[1] for row in cur.fetchall()]
    if "ai_summary" not in columns:
        try:
            cur.execute("ALTER TABLE audit_logs ADD COLUMN ai_summary TEXT")
            conn.commit()
            print("✓ Database migrated: Added 'ai_summary' column successfully.")
        except Exception as err:
            pass

    conn.close()

init_db()

# ---------------------------------------------------------
# CAMPUS NODES
# ---------------------------------------------------------
active_zones: Dict[str, Dict[str, Any]] = {
    "block-a": {
        "id": "block-a",
        "name": "Academic Block A",
        "occupants": 0,
        "lights_on": True,
        "fans_on": True,
        "power_draw": "4.2 kW",
        "incharge_phone": "916361114713",
        "incharge_name": "Prof. Puneeth Kumar"
    },
    "library": {
        "id": "library",
        "name": "Central Library",
        "occupants": 0,
        "lights_on": True,
        "fans_on": True,
        "power_draw": "2.4 kW",
        "incharge_phone": "916361114713",
        "incharge_name": "Dr. Rao"
    },
    "hostel-1": {
        "id": "hostel-1",
        "name": "Hostel Block 1",
        "occupants": 0,
        "lights_on": True,
        "fans_on": True,
        "power_draw": "1.8 kW",
        "incharge_phone": "916361114713",
        "incharge_name": "Warden Office"
    },
    "cafeteria": {
        "id": "cafeteria",
        "name": "Cafeteria Complex",
        "occupants": 0,
        "lights_on": True,
        "fans_on": True,
        "power_draw": "3.1 kW",
        "incharge_phone": "916361114713",
        "incharge_name": "Estate Manager"
    }
}

violation_tracker: Dict[str, Dict[str, Any]] = {
    "block-a": {"active": False, "since": None, "sent_count": 0, "last_sent_at": None},
    "library": {"active": False, "since": None, "sent_count": 0, "last_sent_at": None},
    "hostel-1": {"active": False, "since": None, "sent_count": 0, "last_sent_at": None},
    "cafeteria": {"active": False, "since": None, "sent_count": 0, "last_sent_at": None}
}

last_logged_state: Dict[str, str] = {
    "block-a": "NORMAL", "library": "NORMAL", "hostel-1": "NORMAL", "cafeteria": "NORMAL"
}

latest_frames: Dict[str, bytes] = {}
is_processing_frame: Dict[str, bool] = {
    "block-a": False, "library": False, "hostel-1": False, "cafeteria": False
}

def create_standby_frame(zone_name: str) -> bytes:
    img = Image.new("RGB", (480, 320), color=(10, 15, 29))
    draw = ImageDraw.Draw(img)
    draw.text((25, 120), f"Camera Node: {zone_name}", fill=(56, 189, 248))
    draw.text((25, 150), "STATUS: STANDBY (Awaiting Mobile Feed)", fill=(244, 63, 94))
    draw.text((25, 180), "Open mobile link to broadcast stream", fill=(148, 163, 184))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()

def generate_genai_incident_report(zone_name: str, incharge_name: str, devices: str, power_kw: str) -> str:
    prompt = (
        f"You are the DSU EcoPulse Generative AI Sustainability Officer. "
        f"Generate a concise, urgent WhatsApp alert under 50 words with emojis. "
        f"Details:\n"
        f"- Facility Zone: {zone_name}\n"
        f"- Designated Incharge: {incharge_name}\n"
        f"- Vision Evidence: YOLOv8 confirmed 0 occupants in the room.\n"
        f"- Electrical Load: {devices} drawing {power_kw} peak power.\n"
        f"- Action: Urge cutoff or report that automated relay isolation has been tripped."
    )
    if genai_client:
        try:
            response = genai_client.models.generate_content(
                model='gemini-2.0-flash',
                contents=prompt
            )
            return response.text.strip()
        except Exception:
            pass

    # Built-in fallback response (prevents console spam and sends instantly)
    return (
        f"🚨 *EcoPulse AI Incident Alert*\n"
        f"To: *{incharge_name}* ({zone_name})\n\n"
        f"⚠️ *YOLOv8 Detection*: 0 occupants confirmed.\n"
        f"⚡ *Wastage Load*: {devices} drawing {power_kw}.\n"
        f"🛡️ *Action*: Automatic relay cutoff sequence triggered to prevent carbon penalty."
    )

async def send_whatsapp_alert(zone_id: str, message: str):
    zone = active_zones.get(zone_id, {})
    phone = str(zone.get("incharge_phone", "")).strip().replace("+", "").replace(" ", "").replace("-", "")
    if len(phone) == 10 and not phone.startswith("91"):
        phone = f"91{phone}"

    if not phone:
        return

    def dispatch():
        try:
            url = f"{GREEN_API_HOST}/waInstance{GREEN_API_ID_INSTANCE}/sendMessage/{GREEN_API_TOKEN}"
            payload = {"chatId": f"{phone}@c.us", "message": message}
            requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=8)
        except Exception as e:
            print(f"WhatsApp Dispatch Error: {e}")

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, dispatch)

def process_frame_safe(zone_id: str, frame_bytes: bytes):
    try:
        np_arr = np.frombuffer(frame_bytes, np.uint8)
        img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if img is None:
            return frame_bytes, 0

        h, w = img.shape[:2]
        if w > 480:
            scale = 480 / w
            img = cv2.resize(img, (480, int(h * scale)))

        person_count = 0
        if model:
            results = model(img, classes=[0], conf=0.25, imgsz=256, verbose=False)
            for r in results:
                for box in r.boxes:
                    person_count += 1
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    cv2.rectangle(img, (x1, y1), (x2, y2), (16, 185, 129), 2)

        badge_color = (16, 185, 129) if person_count > 0 else (68, 68, 239)
        cv2.rectangle(img, (0, 0), (250, 32), (0, 0, 0), -1)
        cv2.putText(
            img,
            f"{zone_id.upper()}: {person_count} PERSONS",
            (8, 22),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            badge_color,
            2
        )

        _, buffer = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 50])
        return buffer.tobytes(), person_count
    except Exception as e:
        print(f"[CV Error]: {e}")
        return frame_bytes, 0

# ---------------------------------------------------------
# MOBILE BROADCAST WEBCAM ROUTE (Fixes 404 / Detail Not Found)
# ---------------------------------------------------------
@app.get("/view/{zone_id}", response_class=HTMLResponse)
def mobile_cam_view(zone_id: str):
    zone_titles = {
        "block-a": "Academic Block A",
        "library": "Central Library",
        "hostel-1": "Hostel Block 1",
        "cafeteria": "Cafeteria Complex"
    }
    zone_name = zone_titles.get(zone_id, zone_id)
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
      <title>Camera Node: {zone_name}</title>
      <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-slate-950 text-white flex flex-col items-center justify-between min-h-screen p-5">
      <div class="text-center w-full max-w-sm">
        <h2 class="text-xl font-black text-cyan-400 mb-1">{zone_name}</h2>
        <p class="text-xs text-slate-400">Mobile Edge Vision Node</p>
      </div>

      <div class="w-full max-w-sm aspect-[4/3] bg-black rounded-2xl overflow-hidden border border-slate-800 relative flex items-center justify-center">
        <video id="webcamVideo" autoplay playsinline muted class="w-full h-full object-cover"></video>
        <canvas id="captureCanvas" class="hidden"></canvas>
        <div id="statusPill" class="absolute top-3 left-3 bg-black/70 px-3 py-1 rounded-full border border-slate-700 text-xs text-amber-400 font-mono">
          Ready
        </div>
      </div>

      <div class="w-full max-w-sm space-y-3">
        <button id="toggleBtn" onclick="toggleStream()" class="w-full py-4 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white font-bold text-sm tracking-wide shadow-lg shadow-cyan-900/40 transition">
          Start Broadcasting
        </button>
        <p class="text-center text-[11px] text-slate-500 font-mono">Grid Synchronized: 6 FPS Transmission</p>
      </div>

      <script>
        const zoneId = "{zone_id}";
        let isBroadcasting = false;
        let streamInterval = null;
        const video = document.getElementById('webcamVideo');
        const canvas = document.getElementById('captureCanvas');
        const statusPill = document.getElementById('statusPill');
        const toggleBtn = document.getElementById('toggleBtn');

        async function toggleStream() {{
          if (!isBroadcasting) {{
            try {{
              const stream = await navigator.mediaDevices.getUserMedia({{
                video: {{ facingMode: "environment", width: {{ ideal: 480 }}, height: {{ ideal: 360 }} }},
                audio: false
              }});
              video.srcObject = stream;
              await video.play();

              canvas.width = 400;
              canvas.height = 300;
              const ctx = canvas.getContext('2d');

              isBroadcasting = true;
              toggleBtn.innerText = "Stop Broadcasting";
              toggleBtn.className = "w-full py-4 rounded-xl bg-rose-600 hover:bg-rose-500 text-white font-bold text-sm shadow-lg transition";
              statusPill.innerText = "● Transmitting (Live)";
              statusPill.className = "absolute top-3 left-3 bg-emerald-950/80 px-3 py-1 rounded-full border border-emerald-600 text-xs text-emerald-400 font-mono animate-pulse";

              let isSending = false;
              streamInterval = setInterval(() => {{
                if (isSending) return;
                ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
                canvas.toBlob(async (blob) => {{
                  if (!blob) return;
                  isSending = true;
                  try {{
                    await fetch(`/api/upload_frame/${{zoneId}}`, {{
                      method: 'POST',
                      headers: {{ 'Content-Type': 'image/jpeg' }},
                      body: blob
                    }});
                  }} catch (err) {{}}
                  isSending = false;
                }}, 'image/jpeg', 0.5);
              }}, 160);

            }} catch (err) {{
              alert("Camera error: " + err.message);
            }}
          }} else {{
            clearInterval(streamInterval);
            if (video.srcObject) {{
              video.srcObject.getTracks().forEach(track => track.stop());
            }}
            isBroadcasting = false;
            toggleBtn.innerText = "Start Broadcasting";
            toggleBtn.className = "w-full py-4 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white font-bold text-sm shadow-lg transition";
            statusPill.innerText = "Standby";
            statusPill.className = "absolute top-3 left-3 bg-black/70 px-3 py-1 rounded-full border border-slate-700 text-xs text-amber-400 font-mono";
          }}
        }}
      </script>
    </body>
    </html>
    """

# ---------------------------------------------------------
# REST APIs & VIDEO STREAMING
# ---------------------------------------------------------
@app.get("/")
def root():
    return {"status": "online", "system": "DSU EcoPulse Grid Server"}

@app.post("/api/upload_frame/{zone_id}")
async def upload_frame(zone_id: str, request: Request):
    if zone_id not in active_zones:
        return {"status": "invalid_zone"}

    if is_processing_frame[zone_id]:
        return {"status": "busy_dropped"}

    frame_bytes = await request.body()
    if not frame_bytes:
        return {"status": "empty"}

    is_processing_frame[zone_id] = True
    try:
        loop = asyncio.get_event_loop()
        processed_bytes, person_count = await loop.run_in_executor(
            cv_executor, process_frame_safe, zone_id, frame_bytes
        )
        active_zones[zone_id]["occupants"] = person_count
        latest_frames[zone_id] = processed_bytes
    finally:
        is_processing_frame[zone_id] = False

    return {"status": "ok", "occupants": active_zones[zone_id]["occupants"]}

@app.get("/stream/{zone_id}")
async def stream_video(zone_id: str):
    zone_name = active_zones.get(zone_id, {}).get("name", zone_id)
    standby = create_standby_frame(zone_name)

    async def gen():
        while True:
            frame = latest_frames.get(zone_id, standby)
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")
            await asyncio.sleep(0.12)

    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")

@app.get("/api/campus")
def get_campus():
    return active_zones

@app.get("/api/logs")
def get_logs():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT timestamp, source, item_or_event, status_or_category, impact, ai_summary FROM audit_logs ORDER BY id DESC LIMIT 8")
    rows = cur.fetchall()
    conn.close()
    return [{"timestamp": r[0], "source": r[1], "event": r[2], "status": r[3], "impact": r[4], "ai_summary": r[5]} for r in rows]

class InchargeUpdate(BaseModel):
    name: str
    phone: str

@app.post("/api/update_incharge/{zone_id}")
async def update_incharge(zone_id: str, payload: InchargeUpdate):
    if zone_id in active_zones:
        clean = payload.phone.replace("+", "").replace(" ", "").replace("-", "")
        if len(clean) == 10 and not clean.startswith("91"):
            clean = f"91{clean}"
        active_zones[zone_id]["incharge_name"] = payload.name
        active_zones[zone_id]["incharge_phone"] = clean
        return {"status": "ok", "zone": active_zones[zone_id]}
    return {"error": "not_found"}

class ZoneOverride(BaseModel):
    occupants: int
    lights_on: bool
    fans_on: bool

@app.post("/api/set_zone/{zone_id}")
async def set_zone(zone_id: str, payload: ZoneOverride):
    if zone_id in active_zones:
        active_zones[zone_id]["occupants"] = payload.occupants
        active_zones[zone_id]["lights_on"] = payload.lights_on
        active_zones[zone_id]["fans_on"] = payload.fans_on
        active_zones[zone_id]["power_draw"] = f"{(payload.lights_on * 1.5 + payload.fans_on * 1.2):.1f} kW"
        return {"status": "ok", "zone": active_zones[zone_id]}
    return {"error": "not_found"}

@app.post("/api/push_alert/{zone_id}")
async def manual_alert(zone_id: str):
    if zone_id in active_zones:
        z = active_zones[zone_id]
        loop = asyncio.get_event_loop()
        msg = await loop.run_in_executor(
            None,
            generate_genai_incident_report,
            z["name"],
            z["incharge_name"],
            "Lights & Fans",
            z["power_draw"]
        )
        await send_whatsapp_alert(zone_id, msg)
        return {"status": "alert_dispatched"}
    return {"error": "not_found"}

@app.post("/api/isolate_circuit/{zone_id}")
async def isolate(zone_id: str):
    if zone_id in active_zones:
        active_zones[zone_id]["lights_on"] = False
        active_zones[zone_id]["fans_on"] = False
        active_zones[zone_id]["power_draw"] = "0.0 kW"

        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO audit_logs (timestamp, source, item_or_event, status_or_category, impact, ai_summary) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                datetime.now().strftime("%H:%M:%S"),
                active_zones[zone_id]["name"],
                "Circuit Relay Isolation",
                "Relay Cutoff Tripped",
                "-4.2 kW Cut Off",
                "Automated cutoff engaged."
            )
        )
        conn.commit()
        conn.close()
        return {"status": "ok"}
    return {"error": "not_found"}

@app.post("/api/reset")
def reset_all():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM audit_logs")
    conn.commit()
    conn.close()
    for tracker in violation_tracker.values():
        tracker["active"] = False
        tracker["since"] = None
        tracker["sent_count"] = 0
        tracker["last_sent_at"] = None
    return {"status": "reset"}

# ---------------------------------------------------------
# BACKGROUND SUSTAINABILITY MONITOR
# ---------------------------------------------------------
async def auto_monitor():
    await asyncio.sleep(2)
    while True:
        try:
            now = datetime.now()
            for zone_id, zone_data in active_zones.items():
                occ = zone_data.get("occupants", 0)
                lights = zone_data.get("lights_on", False)
                fans = zone_data.get("fans_on", False)
                is_wasting = (occ == 0) and (lights or fans)
                tracker = violation_tracker[zone_id]

                if is_wasting:
                    if not tracker["active"]:
                        tracker["active"] = True
                        tracker["since"] = now
                        tracker["sent_count"] = 0
                        tracker["last_sent_at"] = None
                    else:
                        elapsed = (now - tracker["since"]).total_seconds()
                        last_sent_elapsed = (now - tracker["last_sent_at"]).total_seconds() if tracker["last_sent_at"] else 9999
                        if elapsed >= 8 and tracker["sent_count"] < MAX_ALERT_COUNT and last_sent_elapsed >= ALERT_COOLDOWN_SECONDS:
                            loads = []
                            if lights: loads.append("Lights")
                            if fans: loads.append("Fans")
                            device_str = " & ".join(loads)

                            loop = asyncio.get_event_loop()
                            msg = await loop.run_in_executor(
                                None,
                                generate_genai_incident_report,
                                zone_data["name"],
                                zone_data.get("incharge_name"),
                                device_str,
                                zone_data["power_draw"]
                            )
                            await send_whatsapp_alert(zone_id, msg)
                            tracker["sent_count"] += 1
                            tracker["last_sent_at"] = now
                            last_logged_state[zone_id] = "ALERT"

                            conn = get_connection()
                            cur = conn.cursor()
                            cur.execute(
                                "INSERT INTO audit_logs (timestamp, source, item_or_event, status_or_category, impact, ai_summary) "
                                "VALUES (?, ?, ?, ?, ?, ?)",
                                (
                                    now.strftime("%H:%M:%S"),
                                    zone_data["name"],
                                    f"Idle {device_str} Leakage",
                                    f"GenAI Alert ({tracker['sent_count']}/{MAX_ALERT_COUNT})",
                                    "-1.6 kWh Saved",
                                    msg
                                )
                            )
                            conn.commit()
                            conn.close()

                elif occ > 0:
                    tracker["active"] = False
                    tracker["since"] = None
                    tracker["sent_count"] = 0
                    tracker["last_sent_at"] = None

        except Exception as e:
            pass
        await asyncio.sleep(3)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(auto_monitor())
    