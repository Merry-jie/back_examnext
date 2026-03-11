import json
import os
import psycopg2
import requests
from http.server import BaseHTTPRequestHandler, HTTPServer

# ==============================
# CONFIG
# ==============================
DATABASE_URL = os.getenv("DATABASE_URL")  # ex: postgres://username:password@host:port/dbname
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
            document JSONB NOT NULL,
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
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_POST(self):
        response = {}
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body) if body else {}

            # ===== DEBUG =====
            print("DEBUG data reçue:", data)

            # ===== Vérifier les champs obligatoires =====
            required_fields = ["nom","email","telephone","date_naissance",
                               "lieu_naissance","cisco_zap","examen",
                               "lieu_de_service_et_etablissement","document"]
            for f in required_fields:
                if f not in data or not data[f]:
                    raise ValueError(f"Le champ '{f}' est obligatoire")

            doc = data["document"]
            if "name" not in doc or "content" not in doc:
                raise ValueError("Le champ 'document' doit contenir 'name' et 'content'")

            # ===== INSERER DANS LA DB =====
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO inscriptions
                (nom,email,telephone,date_naissance,
                 lieu_naissance,cisco_zap,examen,lieu_de_service_et_etablissement,document)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id, nom, examen;
            """, (
                data.get("nom"),
                data.get("email"),
                data.get("telephone"),
                data.get("date_naissance"),
                data.get("lieu_naissance"),
                data.get("cisco_zap"),
                data.get("examen"),
                data.get("lieu_de_service_et_etablissement"),
                json.dumps(doc)
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
                        json={"message": f"Nouveau dossier reçu : {nom} pour {examen}"},
                        timeout=5
                    )
                    print("📧 Email workflow déclenché")
                except Exception as e:
                    print("Erreur StackAI:", e)

            response = {"success": True, "message": "Votre dossier est bien reçu"}

        except ValueError as ve:
            response = {"success": False, "message": str(ve)}
        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            response = {"success": False, "message": "Vous êtes déjà inscrit pour cet examen."}
        except Exception as e:
            print("Erreur serveur:", e)
            response = {"success": False, "message": "Erreur serveur"}

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
