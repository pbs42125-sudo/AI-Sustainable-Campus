import cv2
import datetime
import time
from ultralytics import YOLO
from app.db.database import get_connection

class VisionEngine:
    def __init__(self):
        self.model = YOLO("yolov8n.pt")
        # Global camera capture to prevent locking webcam hardware
        self.cap = cv2.VideoCapture(0)
        self.recyclables = {"bottle", "can", "cup"}
        self.biodegradables = {"banana", "apple", "sandwich", "orange"}
        self.e_waste = {"cell phone", "laptop", "mouse", "keyboard"}

    def stream_feed(self, zone_id: str = "block-a"):
        last_logged_time = time.time()

        while True:
            if not self.cap.isOpened():
                self.cap = cv2.VideoCapture(0)

            success, frame = self.cap.read()
            if not success:
                time.sleep(0.05)
                continue

            results = self.model(frame, conf=0.40, verbose=False)
            person_count = 0
            detected_items = []

            for r in results:
                for box in r.boxes:
                    cls_id = int(box.cls[0])
                    label = self.model.names[cls_id]
                    conf = float(box.conf[0])

                    if label == "person":
                        person_count += 1
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 191, 0), 2)
                        cv2.putText(frame, f"OCCUPANT {conf:.2f}", (x1, max(20, y1 - 8)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 191, 0), 2)
                        continue

                    category = (
                        "Dry / Recyclable" if label in self.recyclables else
                        "Wet / Organic" if label in self.biodegradables else
                        "E-Waste / Hazardous" if label in self.e_waste else
                        None
                    )

                    if category:
                        detected_items.append((label, category))
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        color = (16, 185, 129) if "Organic" in category else (6, 182, 212)
                        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                        cv2.putText(frame, f"{label.upper()} [{category}]", (x1, max(20, y1 - 8)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

            now = time.time()
            if now - last_logged_time > 3.0:
                conn = get_connection()
                cur = conn.cursor()
                now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                if person_count == 0 and zone_id == "block-a":
                    cur.execute(
                        "INSERT INTO audit_logs (timestamp, source, item_or_event, status_or_category, impact) VALUES (?, ?, ?, ?, ?)",
                        (now_str, f"Edge AI [{zone_id.upper()}]", "0 Occupants with HVAC/Light Active", "DISPATCH ALERT", "Push Sent to Facilities Lead")
                    )

                for w_item, w_cat in detected_items[:1]:
                    cur.execute(
                        "INSERT INTO audit_logs (timestamp, source, item_or_event, status_or_category, impact) VALUES (?, ?, ?, ?, ?)",
                        (now_str, f"Vision [{zone_id.upper()}]", w_item.upper(), w_cat, "Classified")
                    )

                conn.commit()
                conn.close()
                last_logged_time = now

            hud_color = (0, 0, 255) if (person_count == 0 and zone_id == "block-a") else (0, 255, 0)
            cv2.putText(frame, f"ZONE: {zone_id.upper()} | OCCUPANTS: {person_count}", (15, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, hud_color, 2)

            ret, buffer = cv2.imencode('.jpg', frame)
            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')