import os
import random
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(title="OBD Voice Assistant API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI Backend!"}


@app.get("/api/hello")
def hello():
    return {"message": "Hello from the backend API!"}


@app.get("/test")
def test_database():
    """Test endpoint to check if database is available and accessible"""
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    
    try:
        # Try to import database module
        from database import db
        
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            
            # Try to list collections to verify connectivity
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]  # Show first 10 collections
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
            
    except ImportError:
        response["database"] = "❌ Database module not found (run enable-database first)"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"
    
    # Check environment variables
    import os as _os
    response["database_url"] = "✅ Set" if _os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if _os.getenv("DATABASE_NAME") else "❌ Not Set"
    
    return response


# -------------------------
# OBD-II Simulation Endpoints
# -------------------------
class LiveData(BaseModel):
    timestamp: str
    rpm: int = Field(..., description="Engine RPM")
    speed: int = Field(..., description="Vehicle speed km/h")
    coolant_temp: int = Field(..., description="Coolant temperature °C")
    throttle: int = Field(..., description="Throttle position %")
    load: int = Field(..., description="Calculated engine load %")
    intake_temp: int = Field(..., description="Intake air temperature °C")


SUPPORTED_PIDS = {
    "010C": "Engine RPM",
    "010D": "Vehicle Speed",
    "0105": "Coolant Temperature",
    "0111": "Throttle Position",
    "0104": "Calculated Engine Load",
    "010F": "Intake Air Temp",
}


class ChatRequest(BaseModel):
    question: str


class ChatResponse(BaseModel):
    answer: str
    tips: Optional[List[str]] = None


DTC_LIBRARY = {
    "P0300": "Allumage raté aléatoire/multiple. Vérifier bougies, bobines, faisceau.",
    "P0171": "Mélange pauvre (banc 1). Chercher prise d'air, débitmètre, pression carburant.",
    "P0420": "Efficacité catalyseur faible. Contrôler fuites échappement, sonde amont/aval, catalyseur.",
    "P0113": "Capteur température d'air d'admission (IAT) – signal élevé.",
    "P0128": "Thermostat probablement ouvert. Température moteur trop basse.",
}


def _simulate_value(baseline: int, variance: int, min_v: int, max_v: int) -> int:
    value = int(random.gauss(baseline, variance))
    return max(min_v, min(max_v, value))


def generate_live_data() -> LiveData:
    # Create plausible values
    rpm = _simulate_value(850, 80, 650, 1200)  # idle
    speed = _simulate_value(0, 1, 0, 5)
    coolant = _simulate_value(88, 3, 70, 100)
    throttle = _simulate_value(4, 2, 0, 15)
    load = _simulate_value(18, 5, 5, 35)
    iat = _simulate_value(32, 3, 5, 60)
    return LiveData(
        timestamp=datetime.utcnow().isoformat() + "Z",
        rpm=rpm, speed=speed, coolant_temp=coolant, throttle=throttle, load=load, intake_temp=iat
    )


@app.get("/api/obd/pids")
def obd_pids():
    return {"supported": SUPPORTED_PIDS}


@app.get("/api/obd/live", response_model=LiveData)
def obd_live():
    return generate_live_data()


class DiagnosticItem(BaseModel):
    code: str
    description: str
    severity: str


class DiagnosticsResponse(BaseModel):
    dtcs: List[DiagnosticItem]


@app.get("/api/obd/diagnostics", response_model=DiagnosticsResponse)
def obd_diagnostics():
    # Randomly return some DTCs for demo
    codes = random.sample(list(DTC_LIBRARY.keys()), k=random.choice([0, 1, 2]))
    dtcs = [
        DiagnosticItem(
            code=c,
            description=DTC_LIBRARY.get(c, "Code inconnu"),
            severity=("élevée" if c in ["P0420", "P0300"] else "moyenne"),
        )
        for c in codes
    ]
    return DiagnosticsResponse(dtcs=dtcs)


# -------------------------
# Simple Rule-based Tech Assistant
# -------------------------

def tech_assistant_answer(q: str) -> ChatResponse:
    text = q.lower()
    tips: List[str] = []

    # Decode DTC if included
    for code, desc in DTC_LIBRARY.items():
        if code.lower() in text:
            tips.append("Vérifier le faisceau, les connecteurs et effacer le code après réparation.")
            return ChatResponse(
                answer=f"Le code {code} signifie: {desc}",
                tips=tips,
            )

    if "obd" in text or "elm327" in text:
        return ChatResponse(
            answer=(
                "Les adaptateurs ELM327 existent en Bluetooth, Wi‑Fi et USB. "
                "Pour un diagnostic fiable, utilisez un PID standard (RPM, vitesse, température) "
                "et lisez les DTC P0xxx. Je peux simuler des données et expliquer les résultats."
            ),
            tips=[
                "Toujours moteur chaud pour des valeurs stables",
                "Vérifier les tensions batterie (>12.4V à l'arrêt, >13.8V en charge)",
            ],
        )

    if any(k in text for k in ["rpm", "ralenti", "boucle", "sonde lambda", "lambda", "o2"]):
        return ChatResponse(
            answer=(
                "Au ralenti, un RPM autour de 700–900 est normal. "
                "Les sondes lambda oscillent ~0.1–0.9V en boucle fermée. "
                "Si instable: rechercher prises d'air, débitmètre encrassé, allumage."
            ),
            tips=["Contrôle fumigène pour prises d'air", "Nettoyage papillon et apprentissage ralenti"],
        )

    if any(k in text for k in ["ecu", "calculateur", "reprogram", "reprog", "carto", "map"]):
        return ChatResponse(
            answer=(
                "Le calculateur (ECU) gère injection/avance via capteurs. "
                "Une reprogrammation doit rester dans les tolérances mécaniques et légales. "
                "Pour un diagnostic, lire trims carburant (LTFT/STFT) et pression rail."
            ),
            tips=["Toujours sauvegarder la carto d'origine", "Surveiller EGT et AFR après modifs"],
        )

    if any(k in text for k in ["batterie", "alternateur", "démarrage", "démarreur", "12v"]):
        return ChatResponse(
            answer=(
                "Pour un défaut de démarrage: tester batterie (chute de tension <9.6V sous charge), "
                "alternateur (13.8–14.5V), masse châssis et excitation."
            ),
            tips=["Mesure avec multimètre en charge", "Nettoyer cosses et points de masse"],
        )

    # Default generic response
    return ChatResponse(
        answer=(
            "Je peux expliquer pannes mécaniques/électriques, décoder DTC, et interpréter tes valeurs OBD. "
            "Pose ta question (ex: 'Que signifie P0420 ?' ou 'Ralenti instable essence')."
        )
    )


@app.post("/api/chat", response_model=ChatResponse)
def chat_endpoint(req: ChatRequest):
    return tech_assistant_answer(req.question)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
