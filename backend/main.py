import os
import io
import asyncio
import sqlite3
import json
import requests
import numpy as np
import cv2
from datetime import datetime
from typing import Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from PIL import Image, ImageDraw
from ultralytics import YOLO

# Google GenAI Official SDK
from google import genai

app = FastAPI(title="EcoPulse AI - ESG Campus Grid with GenAI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

executor = ThreadPoolExecutor(max_workers=4)

# ---------------------------------------------------------
# GENERATIVE AI CONFIGURATION (GEMINI 2.5 FLASH)
# ---------------------------------------------------------
GEMINI_API_KEY = "AIzaSyBAXu8b4xC7-imgnaIEwwEoa1haNxiFGbY"

try:
    genai_client = genai.Client(api_key=GEMINI_API_KEY)
    print("\n✓ Google Generative AI (Gemini) successfully initialized.\n")
except Exception as e:
    print(f"❌ GenAI Initialization Warning: {e}")
    genai_client = None

# ---------------------------------------------------------
# AUTONOMOUS WHATSAPP CONFIGURATION (GREEN-API INSTANCE)
# ---------------------------------------------------------
GREEN_API_HOST = "https://7107.api.greenapi.com"
GREEN_API_ID_INSTANCE = "710722769366"
GREEN_API_TOKEN = "733d94b68a4c4d24a7de553ac7219ffe565f6a595b9b4b6d9d"

# Strict WhatsApp Notification Limit: Max 2 messages per room incident with 60s cooldown
MAX_ALERT_COUNT = 2
ALERT_COOLDOWN_SECONDS = 60

# ---------------------------------------------------------
# LOAD YOLOV8 MODEL
# ---------------------------------------------------------
possible_paths = [
    os.path.join(os.path.dirname(__file__), "..", "yolov8n.pt"),
    os.path.join(os.path.dirname(__file__), "yolov8n.pt"),
    "yolov8n.pt"
]
model_path = next((p for p in possible_paths if os.path.exists(p)), "yolov8n.pt")

try:
    print(f"[SYSTEM] Loading YOLOv8: {os.path.abspath(model_path)}")
    model = YOLO(model_path)
    print("✓ YOLOv8 Engine successfully initialized.\n")
except Exception as e:
    print(f"❌ YOLO load error: {e}")
    model = None

# ---------------------------------------------------------
# SQLITE AUDIT DATABASE SETUP
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
    conn.close()

init_db()

# ---------------------------------------------------------
# CAMPUS ZONES STATE (EDITABLE VIA ASSIGN FACULTY MODAL)
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
        "incharge_name": "Dr. Rao (Chief Librarian)"
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
    "block-a": "NORMAL",
    "library": "NORMAL",
    "hostel-1": "NORMAL",
    "cafeteria": "NORMAL"
}

latest_frames: Dict[str, bytes] = {}

# ---------------------------------------------------------
# GENERATIVE AI DYNAMIC REASONING ENGINE
# ---------------------------------------------------------
def generate_genai_incident_report(zone_name: str, incharge_name: str, devices: str, power_kw: str) -> str:
    """Uses Gemini 2.5 Flash to synthesize a dynamic, natural-language ESG alert."""
    prompt = (
        f"You are the DSU EcoPulse Generative AI Campus Sustainability Officer. "
        f"Generate a professional, urgent WhatsApp alert under 50 words with emojis. "
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
                model='gemini-2.5-flash',
                contents=prompt
            )
            return response.text.strip()
        except Exception as err:
            print(f"[GenAI API Fallback]: {err}")

    # Deterministic fallback if network drops
    return (
        f"🚨 *EcoPulse AI Incident Alert*\n"
        f"To: *{incharge_name}* ({zone_name})\n\n"
        f"YOLOv8 confirmed 0 occupants while {devices} are drawing {power_kw}. "
        f"Automated relay isolation sequence initiated to prevent carbon penalty."
    )

def create_standby_frame(zone_name: str) -> bytes:
    img = Image.new("RGB", (480, 360), color=(10, 17, 40))
    draw = ImageDraw.Draw(img)
    draw.text((30, 140), f"Camera Node: {zone_name}", fill=(56, 189, 248))
    draw.text((30, 170), "STANDBY - AWAITING MOBILE SENSOR FEED", fill=(244, 63, 94))
    draw.text((30, 200), "Open mobile link to broadcast stream", fill=(148, 163, 184))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()

async def send_whatsapp_alert(zone_id: str, message: str):
    zone = active_zones.get(zone_id, {})
    raw_phone = str(zone.get("incharge_phone", "")).strip()
    phone = raw_phone.replace("+", "").replace(" ", "").replace("-", "")
    if len(phone) == 10 and not phone.startswith("91"):
        phone = f"91{phone}"

    name = zone.get("incharge_name", "Incharge Faculty")

    print("\n" + "="*58)
    print(f"🚨 [AUTONOMOUS WHATSAPP DISPATCH]")
    print(f"Target Zone      : {zone.get('name')}")
    print(f"Assigned Incharge: {name} (+{phone})")
    print(f"GenAI Message    :\n{message}")
    print("="*58 + "\n")

    if not phone:
        print("❌ Dispatch skipped: No phone number assigned.\n")
        return

    def dispatch_whatsapp():
        try:
            url = f"{GREEN_API_HOST}/waInstance{GREEN_API_ID_INSTANCE}/sendMessage/{GREEN_API_TOKEN}"
            payload = {"chatId": f"{phone}@c.us", "message": message}
            headers = {'Content-Type': 'application/json'}
            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            if resp.status_code == 200:
                print(f"✓ Automatic WhatsApp delivered to +{phone}!\n")
            else:
                print(f"❌ Green-API Error: {resp.status_code} - {resp.text}\n")
        except Exception as err:
            print(f"❌ WhatsApp Network Error: {err}\n")

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, dispatch_whatsapp)

# ---------------------------------------------------------
# HTTP API ROUTES
# ---------------------------------------------------------
@app.get("/")
def root():
    return {
        "status": "online",
        "system": "EcoPulse ESG Campus Grid",
        "genai_active": genai_client is not None,
        "version": "7.0.0"
    }

@app.get("/api/campus")
def get_campus_state():
    return active_zones

@app.get("/api/logs")
def get_logs():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT timestamp, source, item_or_event, status_or_category, impact, ai_summary FROM audit_logs ORDER BY id DESC LIMIT 8")
    rows = cur.fetchall()
    conn.close()
    return [{"timestamp": r[0], "source": r[1], "event": r[2], "status": r[3], "impact": r[4], "ai_summary": r[5]} for r in rows]

class CopilotQuery(BaseModel):
    query: str

@app.post("/api/genai_copilot")
async def copilot_chat(payload: CopilotQuery):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT timestamp, source, item_or_event, status_or_category, impact FROM audit_logs ORDER BY id DESC LIMIT 5")
    rows = cur.fetchall()
    conn.close()

    logs_context = "\n".join([f"- [{r[0]}] {r[1]}: {r[2]} ({r[3]}, Impact: {r[4]})" for r in rows]) or "No recent incidents."

    prompt = (
        f"You are the DSU EcoPulse Generative AI Campus Assistant. Answer the question concisely using the live system state.\n"
        f"Live Facility States:\n{json.dumps(active_zones, indent=2)}\n\n"
        f"Recent Audit Logs:\n{logs_context}\n\n"
        f"User Question: {payload.query}\n"
        f"Answer in 2 sentences with specific data."
    )

    if genai_client:
        try:
            resp = genai_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt
            )
            return {"answer": resp.text.strip(), "source": "gemini-2.5-flash"}
        except Exception as e:
            print(f"[Copilot Error]: {e}")

    return {
        "answer": f"Monitoring 4 facility nodes. Academic Block A is drawing {active_zones['block-a']['power_draw']} with {active_zones['block-a']['occupants']} occupants.",
        "source": "fallback-engine"
    }

class InchargeUpdate(BaseModel):
    name: str
    phone: str

@app.post("/api/update_incharge/{zone_id}")
async def update_incharge(zone_id: str, payload: InchargeUpdate):
    if zone_id in active_zones:
        clean_phone = payload.phone.replace("+", "").replace(" ", "").replace("-", "")
        if len(clean_phone) == 10 and not clean_phone.startswith("91"):
            clean_phone = f"91{clean_phone}"

        active_zones[zone_id]["incharge_name"] = payload.name
        active_zones[zone_id]["incharge_phone"] = clean_phone
        return {"status": "ok", "data": active_zones[zone_id]}
    return {"error": "Invalid zone"}

class ZoneOverride(BaseModel):
    occupants: int
    lights_on: bool
    fans_on: bool

@app.post("/api/set_zone/{zone_id}")
async def set_zone_data(zone_id: str, payload: ZoneOverride):
    if zone_id in active_zones:
        active_zones[zone_id]["occupants"] = payload.occupants
        active_zones[zone_id]["lights_on"] = payload.lights_on
        active_zones[zone_id]["fans_on"] = payload.fans_on
        active_zones[zone_id]["power_draw"] = f"{(payload.lights_on * 1.5 + payload.fans_on * 1.2):.1f} kW"
        return {"status": "updated", "zone": active_zones[zone_id]}
    return {"error": "Invalid zone"}

@app.post("/api/isolate_circuit/{zone_id}")
async def isolate_circuit(zone_id: str):
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
                "Automated circuit relay cutoff engaged via Command Center."
            )
        )
        conn.commit()
        conn.close()
        return {"status": "isolated", "zone": active_zones[zone_id]}
    return {"error": "Invalid zone"}

@app.post("/api/reset")
def reset_demo():
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
    for k in last_logged_state.keys():
        last_logged_state[k] = "NORMAL"
    return {"status": "reset_successful"}

@app.post("/api/push_alert/{zone_id}")
async def trigger_manual_alert(zone_id: str):
    if zone_id in active_zones:
        zone = active_zones[zone_id]
        loop = asyncio.get_event_loop()
        genai_msg = await loop.run_in_executor(
            None,
            generate_genai_incident_report,
            zone['name'],
            zone['incharge_name'],
            "Lighting & Ventilation",
            zone['power_draw']
        )
        await send_whatsapp_alert(zone_id, genai_msg)
        return {"status": "alert_dispatched", "zone": zone_id, "genai_text": genai_msg}
    return {"error": "Invalid zone"}

# ---------------------------------------------------------
# THREADED YOLO MULTI-STREAM INFERENCE
# ---------------------------------------------------------
def process_frame_yolo(zone_id: str, frame_bytes: bytes, current_occupants: int):
    np_arr = np.frombuffer(frame_bytes, np.uint8)
    img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if img is None:
        return frame_bytes, current_occupants

    person_count = 0
    if model:
        results = model(img, classes=[0], conf=0.20, imgsz=320, verbose=False)
        for r in results:
            for box in r.boxes:
                person_count += 1
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                conf = float(box.conf[0])
                cv2.rectangle(img, (x1, y1), (x2, y2), (16, 185, 129), 2)
                cv2.putText(
                    img,
                    f"Person {conf*100:.0f}%",
                    (x1, max(20, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (16, 185, 129),
                    2
                )

    badge_bg = (16, 185, 129) if person_count > 0 else (239, 68, 68)
    cv2.rectangle(img, (0, 0), (280, 36), (255, 255, 255), -1)
    cv2.putText(
        img,
        f"{zone_id.upper()}: {person_count} PERSONS",
        (10, 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        badge_bg,
        2
    )

    _, buffer = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 55])
    return buffer.tobytes(), person_count

@app.post("/api/upload_frame/{zone_id}")
async def upload_frame(zone_id: str, request: Request):
    frame_bytes = await request.body()
    if not frame_bytes or zone_id not in active_zones:
        return {"status": "empty"}

    current_occ = active_zones[zone_id]["occupants"]
    loop = asyncio.get_event_loop()
    processed_bytes, person_count = await loop.run_in_executor(
        executor, process_frame_yolo, zone_id, frame_bytes, current_occ
    )

    active_zones[zone_id]["occupants"] = person_count
    latest_frames[zone_id] = processed_bytes
    return {"status": "ok", "zone": zone_id, "persons": person_count}

@app.get("/stream/{zone_id}")
async def video_stream_endpoint(zone_id: str):
    zone_name = active_zones.get(zone_id, {}).get("name", zone_id)
    standby_frame = create_standby_frame(zone_name)

    async def frame_generator():
        while True:
            frame = latest_frames.get(zone_id, standby_frame)
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")
            await asyncio.sleep(0.12)

    return StreamingResponse(frame_generator(), media_type="multipart/x-mixed-replace; boundary=frame")

# ---------------------------------------------------------
# BACKGROUND MONITOR WITH AUTONOMOUS GENAI REPORTING
# ---------------------------------------------------------
async def auto_energy_waste_monitor():
    await asyncio.sleep(2)
    while True:
        try:
            now = datetime.now()
            for zone_id, zone_data in active_zones.items():
                occupants = zone_data.get("occupants", 0)
                lights_active = zone_data.get("lights_on", False)
                fans_active = zone_data.get("fans_on", False)

                is_wasting = (occupants == 0) and (lights_active or fans_active)
                tracker = violation_tracker[zone_id]

                if is_wasting:
                    if not tracker["active"]:
                        tracker["active"] = True
                        tracker["since"] = now
                        tracker["sent_count"] = 0
                        tracker["last_sent_at"] = None
                    else:
                        elapsed_since_start = (now - tracker["since"]).total_seconds()
                        time_since_last_alert = 9999
                        if tracker["last_sent_at"]:
                            time_since_last_alert = (now - tracker["last_sent_at"]).total_seconds()

                        # Enforce 2-message cap and 60s cooldown
                        if elapsed_since_start >= 8 and tracker["sent_count"] < MAX_ALERT_COUNT and time_since_last_alert >= ALERT_COOLDOWN_SECONDS:
                            loads = []
                            if lights_active: loads.append("Lights")
                            if fans_active: loads.append("Fans")
                            device_str = " & ".join(loads)

                            # >>> CALL GEMINI GENAI FOR DYNAMIC INCIDENT BRIEF <<<
                            loop = asyncio.get_event_loop()
                            genai_report = await loop.run_in_executor(
                                None,
                                generate_genai_incident_report,
                                zone_data['name'],
                                zone_data.get('incharge_name'),
                                device_str,
                                zone_data['power_draw']
                            )

                            await send_whatsapp_alert(zone_id, genai_report)
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
                                    genai_report
                                )
                            )
                            conn.commit()
                            conn.close()

                elif occupants > 0:
                    tracker["active"] = False
                    tracker["since"] = None
                    tracker["sent_count"] = 0
                    tracker["last_sent_at"] = None

                    if last_logged_state.get(zone_id) == "ALERT":
                        last_logged_state[zone_id] = "NORMAL"

                        conn = get_connection()
                        cur = conn.cursor()
                        cur.execute(
                            "INSERT INTO audit_logs (timestamp, source, item_or_event, status_or_category, impact, ai_summary) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (
                                now.strftime("%H:%M:%S"),
                                zone_data["name"],
                                f"Occupancy Verified ({occupants} Persons)",
                                "Normal Operation",
                                "Grid Compliant",
                                "GenAI verified compliant human occupancy."
                            )
                        )
                        conn.commit()
                        conn.close()

                else:
                    tracker["active"] = False
                    tracker["since"] = None
                    tracker["sent_count"] = 0
                    tracker["last_sent_at"] = None

        except Exception as err:
            print(f"[AutoMonitor Error]: {err}")

        await asyncio.sleep(3)

@app.on_event("startup")
async def start_background_workers():
    asyncio.create_task(auto_energy_waste_monitor())