import base64
import datetime
import urllib.parse
import cv2
import numpy as np
from fastapi import FastAPI, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse

from app.db.database import init_db, get_connection
from app.services.vision_engine import VisionEngine
from app.services.grid_controller import GridController

app = FastAPI(title="EcoPulse AI Core Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()
vision_service = VisionEngine()
grid_service = GridController()

# Dictionary to hold the latest processed JPEG frame per zone
remote_frames = {
    "block-a": None,
    "library": None,
    "hostel-1": None,
    "cafeteria": None
}

# Persistent in-memory incharge directory
incharges = {
    "block-a": {"name": "Prof. Sharma", "role": "Academic Dean", "phone": "919844012345"},
    "library": {"name": "Dr. Ramesh", "role": "Chief Librarian", "phone": "919844012346"},
    "hostel-1": {"name": "Mr. Venkatesh", "role": "Senior Warden", "phone": "919844012347"},
    "cafeteria": {"name": "Mr. Anand", "role": "Operations Manager", "phone": "919844012348"}
}

def init_incharge_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS campus_incharges (
            zone_id TEXT PRIMARY KEY,
            name TEXT,
            role TEXT,
            phone TEXT
        )
    """)
    for zid, data in incharges.items():
        cur.execute(
            "INSERT OR REPLACE INTO campus_incharges (zone_id, name, role, phone) VALUES (?, ?, ?, ?)",
            (zid, data["name"], data["role"], data["phone"])
        )
    conn.commit()
    conn.close()

init_incharge_db()

@app.get("/view")
@app.get("/view/{zone_id}")
def mobile_camera_broadcaster(zone_id: str = "block-a"):
    """Ultra-low latency mobile transmitter using non-blocking async capture."""
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>EcoPulse Node Camera Transmitter</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            margin: 0;
            background-color: #020617;
            color: #f8fafc;
            font-family: system-ui, -apple-system, sans-serif;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: space-between;
            min-height: 100vh;
            padding: 16px;
        }}
        .card {{
            background: #0f172a;
            border: 1px solid #1e293b;
            border-radius: 16px;
            overflow: hidden;
            width: 100%;
            max-width: 480px;
            display: flex;
            flex-direction: column;
        }}
        .header {{
            padding: 14px 18px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #1e293b;
        }}
        h2 {{
            margin: 0;
            font-size: 0.95rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: #38bdf8;
        }}
        .badge {{
            font-size: 0.75rem;
            font-family: monospace;
            background: rgba(16, 185, 129, 0.2);
            color: #34d399;
            padding: 3px 8px;
            border-radius: 9999px;
            border: 1px solid rgba(16, 185, 129, 0.3);
        }}
        #video-preview {{
            width: 100%;
            aspect-ratio: 4/3;
            object-fit: cover;
            background: #000;
        }}
        .controls {{
            padding: 16px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }}
        .btn {{
            width: 100%;
            padding: 14px;
            border: none;
            border-radius: 10px;
            font-weight: 700;
            font-size: 0.95rem;
            cursor: pointer;
            transition: 0.2s;
            text-transform: uppercase;
        }}
        .btn-start {{
            background: #10b981;
            color: #fff;
        }}
        .btn-start:active {{
            background: #059669;
        }}
        .status {{
            font-size: 0.8rem;
            color: #94a3b8;
            font-family: monospace;
            text-align: center;
        }}
    </style>
</head>
<body>
    <div class="card">
        <div class="header">
            <h2>Node: {zone_id.upper()}</h2>
            <span id="stream-badge" class="badge">STANDBY</span>
        </div>
        <video id="video-preview" autoplay playsinline muted></video>
        <canvas id="hidden-canvas" style="display: none;"></canvas>
        <div class="controls">
            <button id="start-btn" class="btn btn-start" onclick="toggleStream()">📷 Start Phone Camera Stream</button>
            <div id="status-text" class="status">Tap button above to allow camera permissions</div>
        </div>
    </div>

    <script>
        const zoneId = "{zone_id}";
        const video = document.getElementById('video-preview');
        const canvas = document.getElementById('hidden-canvas');
        const badge = document.getElementById('stream-badge');
        const statusText = document.getElementById('status-text');
        const startBtn = document.getElementById('start-btn');
        let streaming = false;
        let isSending = false;

        async function toggleStream() {{
            if (!streaming) {{
                try {{
                    const stream = await navigator.mediaDevices.getUserMedia({{
                        video: {{ 
                            facingMode: "environment", 
                            width: {{ ideal: 480 }}, 
                            height: {{ ideal: 360 }} 
                        }},
                        audio: false
                    }});
                    video.srcObject = stream;
                    streaming = true;
                    badge.innerText = "● TRANSMITTING";
                    badge.style.background = "rgba(239, 68, 68, 0.2)";
                    badge.style.color = "#f87171";
                    badge.style.borderColor = "rgba(239, 68, 68, 0.3)";
                    startBtn.innerText = "⏹ Stop Streaming";
                    startBtn.style.background = "#e11d48";
                    statusText.innerText = "Transmitting live at low latency...";

                    startPushLoop();
                }} catch (err) {{
                    alert("Camera access denied or unavailable: " + err.message);
                }}
            }} else {{
                streaming = false;
                if (video.srcObject) {{
                    video.srcObject.getTracks().forEach(track => track.stop());
                }}
                badge.innerText = "STANDBY";
                badge.style.background = "rgba(16, 185, 129, 0.2)";
                badge.style.color = "#34d399";
                badge.style.borderColor = "rgba(16, 185, 129, 0.3)";
                startBtn.innerText = "📷 Start Phone Camera Stream";
                startBtn.style.background = "#10b981";
                statusText.innerText = "Stream paused.";
            }}
        }}

        // Low-latency recursive loop: never piles up old frames in the queue
        async function startPushLoop() {{
            canvas.width = 400;
            canvas.height = 300;
            const ctx = canvas.getContext('2d');

            while (streaming) {{
                if (video.readyState >= 2 && !isSending) {{
                    isSending = true;
                    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
                    
                    // Optimized 0.45 JPEG compression prevents network bottlenecks
                    const dataUrl = canvas.toDataURL('image/jpeg', 0.45);

                    try {{
                        await fetch('/api/camera/ingest/' + zoneId, {{
                            method: 'POST',
                            headers: {{ 'Content-Type': 'application/json' }},
                            body: JSON.stringify({{ image: dataUrl }})
                        }});
                    }} catch (e) {{}}
                    
                    isSending = false;
                }}
                // Small sleep to yield execution and keep 12-15 FPS fluid
                await new Promise(r => setTimeout(r, 65));
            }}
        }}
    </script>
</body>
</html>"""
    return HTMLResponse(content=html_content, status_code=200)

@app.post("/api/camera/ingest/{zone_id}")
async def ingest_phone_frame(zone_id: str, payload: dict = Body(...)):
    """Receives remote JPEG frame, performs low-overhead YOLO inference, and buffers result."""
    try:
        data_str = payload.get("image", "")
        if "," in data_str:
            data_str = data_str.split(",")[1]
        img_bytes = base64.b64decode(data_str)
        nparr = np.frombuffer(img_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if frame is not None:
            # Fast inference with lower image size preset
            results = vision_service.model(frame, imgsz=320, verbose=False)
            annotated_frame = results[0].plot()

            # Encode at standard compression for high-speed streaming
            _, buffer = cv2.imencode('.jpg', annotated_frame, [cv2.IMWRITE_JPEG_QUALITY, 55])
            remote_frames[zone_id] = buffer.tobytes()
            return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    return {"status": "failed"}

def stream_generator(zone_id: str):
    """Streams phone frame if active; falls back to laptop webcam if no phone feed."""
    while True:
        frame_bytes = remote_frames.get(zone_id)
        if frame_bytes is not None:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        else:
            yield next(vision_service.stream_feed(zone_id))

@app.get("/video_feed")
@app.get("/video_feed/{zone_id}")
def video_feed(zone_id: str = "block-a"):
    return StreamingResponse(
        stream_generator(zone_id),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

@app.get("/api/campus")
def get_campus():
    return list(grid_service.nodes.values())

@app.get("/api/incharges")
def get_incharges():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT zone_id, name, role, phone FROM campus_incharges")
    rows = cur.fetchall()
    conn.close()
    return {r[0]: {"name": r[1], "role": r[2], "phone": r[3]} for r in rows}

@app.post("/api/incharges/{zone_id}")
def update_incharge(zone_id: str, name: str, role: str, phone: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO campus_incharges (zone_id, name, role, phone) VALUES (?, ?, ?, ?)",
        (zone_id, name, role, phone)
    )
    conn.commit()
    conn.close()
    incharges[zone_id] = {"name": name, "role": role, "phone": phone}
    return {"success": True, "data": incharges[zone_id]}

@app.post("/api/relay/trigger/{node_id}")
def trigger_relay(node_id: str):
    success = grid_service.execute_cutoff(node_id)
    return {"success": success}

@app.post("/api/notify/whatsapp/{zone_id}")
def dispatch_whatsapp(zone_id: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT name, phone FROM campus_incharges WHERE zone_id = ?", (zone_id,))
    row = cur.fetchone()
    name = row[0] if row else "Incharge"
    phone = row[1] if row else "919844012345"

    message = f"🚨 *ECOPULSE AI CRITICAL ALERT*\n\nAttention {name},\nZero occupancy detected in {zone_id.upper()} with HVAC/Power operating at 42 kW off-schedule (+128 kg CO2 penalty).\n\nPlease cut off idle switches or approve autonomous relay cutoff on your dashboard."
    
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute(
        "INSERT INTO audit_logs (timestamp, source, item_or_event, status_or_category, impact) VALUES (?, ?, ?, ?, ?)",
        (now, f"WhatsApp Gateway [{zone_id.upper()}]", f"Alert to {name} ({phone})", "DISPATCHED", "Pending Isolation")
    )
    conn.commit()
    conn.close()

    encoded_msg = urllib.parse.quote(message)
    whatsapp_url = f"https://wa.me/{phone}?text={encoded_msg}"
    return {"success": True, "whatsapp_url": whatsapp_url, "phone": phone, "name": name}

@app.post("/api/reset")
def reset_grid():
    grid_service.reset_state()
    return {"success": True, "message": "Grid state restored to baseline anomaly."}

@app.post("/api/waste/simulate-audit")
def simulate_waste(audit_type: str):
    conn = get_connection()
    cur = conn.cursor()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if audit_type == "contaminated":
        cur.execute(
            "INSERT INTO audit_logs (timestamp, source, item_or_event, status_or_category, impact) VALUES (?, ?, ?, ?, ?)",
            (now, "Preset Vision Audit", "Cafeteria Organic Bin", "CONTAMINATED", "40% Compost Purity Penalty")
        )
        res = {
            "title": "Contaminated Waste Detected",
            "result": "Unsegregated plastic packaging identified in organic bin.",
            "penalty": "40% Compost Purity Penalty Applied"
        }
    else:
        cur.execute(
            "INSERT INTO audit_logs (timestamp, source, item_or_event, status_or_category, impact) VALUES (?, ?, ?, ?, ?)",
            (now, "Preset Vision Audit", "Hostel 1 Station", "COMPLIANT", "+50 Green Credits")
        )
        res = {
            "title": "Clean Segregation Confirmed",
            "result": "Compostable organic matter verified without foreign contaminants.",
            "penalty": "+50 Green Credits Issued"
        }

    conn.commit()
    conn.close()
    return res

@app.get("/api/logs")
def get_logs():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT timestamp, source, item_or_event, status_or_category, impact FROM audit_logs ORDER BY id DESC LIMIT 8"
    )
    rows = cur.fetchall()
    conn.close()
    return [{"timestamp": r[0], "source": r[1], "event": r[2], "status": r[3], "impact": r[4]} for r in rows]