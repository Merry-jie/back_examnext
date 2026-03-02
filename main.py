import json
import os
import psycopg2
import requests
from http.server import BaseHTTPRequestHandler, HTTPServer

# ==============================
# CONFIG
# ==============================

DATABASE_URL = os.getenv("DATABASE_URL")
STACKAI_WEBHOOK = os.getenv("STACKAI_WEBHOOK")  # URL workflow email
PORT = int(os.getenv("PORT", 8000))

# ==============================
# CONNEXION DB
# ==============================

def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

# ==============================
# CREATION TABLE
# ==============================

def init_db():
    print("Connexion DB en cours...")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS inscriptions (
            id SERIAL PRIMARY KEY,
            nom TEXT NOT NULL,
            email TEXT NOT NULL,
            telephone TEXT NOT NULL,
            date_naissance DATE NOT NULL,
            lieu_naissance TEXT NOT NULL,
            cisco_zap TEXT NOT NULL,
            examen TEXT NOT NULL,
            lieu_de_service_et_etablissement TEXT NOT NULL,
            documents JSONB NOT NULL,
            date_creation TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            lu BOOLEAN DEFAULT FALSE,
            UNIQUE(email, examen)
        );
    """)
    conn.commit()
    cur.close()
    conn.close()
    print("✅ Table inscriptions prête")

# ==============================
# HTTP SERVER
# ==============================

class Handler(BaseHTTPRequestHandler):

    # -------- CORS ----------
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    # -------- POST ----------
    def do_POST(self):
        response = {}
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body) if body else {}

            # Vérification des champs obligatoires
            required_fields = ["nom","email","telephone","date_naissance","lieu_naissance",
                               "cisco_zap","examen","lieu_de_service_et_etablissement","documents"]
            for field in required_fields:
                if field not in data or not data[field]:
                    raise ValueError(f"Le champ '{field}' est obligatoire")

            # Vérification du nombre de fichiers
            if not isinstance(data["documents"], list) or len(data["documents"]) < 3:
                raise ValueError("Au moins 3 fichiers doivent être uploadés")

            # ===== INSERER DANS LA DB =====
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO inscriptions
                (nom,email,telephone,date_naissance,
                 lieu_naissance,cisco_zap,examen,lieu_de_service_et_etablissement,documents)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id, nom, examen;
            """, (
                data["nom"],
                data["email"],
                data["telephone"],
                data["date_naissance"],
                data["lieu_naissance"],
                data["cisco_zap"],
                data["examen"],
                data["lieu_de_service_et_etablissement"],
                json.dumps(data["documents"])
            ))
            new_id, nom, examen = cur.fetchone()
            conn.commit()
            cur.close()
            conn.close()

            print(f"Nouvelle inscription #{new_id}")

            # ===== ENVOI STACKAI =====
            if STACKAI_WEBHOOK:
                try:
                    requests.post(
                        STACKAI_WEBHOOK,
                        json={"message": f"Nouveau dossier reçu: {nom} ({examen})"},
                        timeout=5
                    )
                    print("📧 Email workflow déclenché")
                except Exception as e:
                    print("Erreur StackAI:", e)

            response = {"success": True, "message": "Votre dossier est bien reçu"}

        except psycopg2.errors.UniqueViolation:
            if 'conn' in locals(): conn.rollback()
            response = {"success": False, "message": "Vous êtes déjà inscrit pour cet examen."}

        except ValueError as ve:
            response = {"success": False, "message": str(ve)}

        except Exception as e:
            print("Erreur serveur:", e)
            response = {"success": False, "message": "Erreur serveur"}

        # ===== REPONSE =====
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())

# ==============================
# START SERVER
# ==============================

if __name__ == "__main__":
    init_db()
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"🚀 Backend actif sur port {PORT}")
    server.serve_forever()