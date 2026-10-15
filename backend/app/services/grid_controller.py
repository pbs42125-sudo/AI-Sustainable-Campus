import datetime
from app.db.database import get_connection

class GridController:
    def __init__(self):
        self.reset_state()

    def reset_state(self):
        self.nodes = {
            "block-a": {
                "id": "block-a",
                "name": "Academic Block A",
                "power_kw": 142.8,
                "water_lpm": 8.2,
                "hvac_status": "RUNNING 100%",
                "waste_level": "42%",
                "status": "CRITICAL",
                "anomaly": {
                    "title": "HVAC running at 100% capacity at 2:00 AM - 42 kW leakage",
                    "root_cause": "Unoccupied lecture halls drawing peak HVAC load.",
                    "carbon_impact": "+128 kg CO2/day",
                    "cost_waste": "₹3,840 / 6 hrs",
                    "recommendation": "Execute AI Sub-Panel Cutoff on Floor 4."
                }
            },
            "library": {
                "id": "library",
                "name": "Central Library",
                "power_kw": 38.2,
                "water_lpm": 14.1,
                "hvac_status": "ECO MODE",
                "waste_level": "18%",
                "status": "OPTIMAL",
                "anomaly": None
            },
            "hostel-1": {
                "id": "hostel-1",
                "name": "Hostel Block 1",
                "power_kw": 62.0,
                "water_lpm": 48.5,
                "hvac_status": "OFF",
                "waste_level": "64%",
                "status": "WARNING",
                "anomaly": {
                    "title": "Water Line Micro-Leak Detected",
                    "root_cause": "Continuous 38 L/min water draw in restrooms during off-hours.",
                    "carbon_impact": "+15 kg CO2/day",
                    "cost_waste": "2,400 Litres wasted",
                    "recommendation": "Isolate Overhead Tank Line 3."
                }
            },
            "cafeteria": {
                "id": "cafeteria",
                "name": "Cafeteria Complex",
                "power_kw": 51.0,
                "water_lpm": 22.0,
                "hvac_status": "OFF",
                "waste_level": "88%",
                "status": "OPTIMAL",
                "anomaly": None
            }
        }

    def execute_cutoff(self, node_id: str):
        if node_id in self.nodes:
            node = self.nodes[node_id]
            # Fixed target baseline so it never goes negative
            node["status"] = "OPTIMAL"
            node["power_kw"] = 100.8
            node["hvac_status"] = "ISOLATED / ECO"
            node["anomaly"] = None

            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO audit_logs (timestamp, source, item_or_event, status_or_category, impact) VALUES (?, ?, ?, ?, ?)",
                (
                    datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "Relay Controller",
                    f"Sub-Panel Trip {node['name']}",
                    "RESOLVED",
                    "Saved 42 kW (-128 kg CO₂)"
                )
            )
            conn.commit()
            conn.close()
            return True
        return False