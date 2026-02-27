import json
import os
import psycopg2
import requests

from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

# ==============================
# CONFIG
# ==============================

DATABASE_URL = os.getenv("DATABASE_URL")

STACKAI_WEBHOOK = os.getenv("STACKAI_WEBHOOK")  # url workflow email

PORT = int(os.getenv("PORT", 8000))


# ==============================
# CONNEXION DB
# ==============================

def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")


# ==============================
# CREATION TABLE (safe)
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
            universite TEXT NOT NULL,
            examen TEXT NOT NULL,
            mention TEXT NOT NULL,
            document TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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

        length = int(self.headers.get("Content-Length"))
        body = self.rfile.read(length)

        data = json.loads(body)

        try:
            conn = get_conn()
            cur = conn.cursor()

            # INSERT + récupérer dernier ID
            cur.execute("""
                INSERT INTO inscriptions
                (nom,email,telephone,date_naissance,
                 lieu_naissance,universite,examen,mention,document)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id, nom, examen;
            """, (
                data.get("nom"),
                data.get("email"),
                data.get("telephone"),
                data.get("date_naissance"),
                data.get("lieu_naissance"),
                data.get("universite"),
                data.get("examen"),
                data.get("mention"),
                data.get("document")
            ))

            new_id, nom, examen = cur.fetchone()

            conn.commit()
            cur.close()
            conn.close()

            print(f"Nouvelle inscription #{new_id}")

            # =========================
            # ENVOI STACKAI EMAIL
            # =========================
            if STACKAI_WEBHOOK:
                try:
                    requests.post(
                        STACKAI_WEBHOOK,
                        json={
                            "nom": nom,
                            "examen": examen,
                            "id": new_id
                        },
                        timeout=5
                    )
                    print("📧 Email workflow déclenché")

                except Exception as e:
                    print("Erreur StackAI:", e)

            response = {
                "success": True,
                "message": "Votre dossier est bien reçu"
            }

        # ======= ANTI DOUBLON =======
        except psycopg2.errors.UniqueViolation:

            conn.rollback()

            response = {
                "success": False,
                "message": "Vous êtes déjà inscrit pour cet examen."
            }

        except Exception as e:
            print("Erreur serveur:", e)

            response = {
                "success": False,
                "message": "Erreur serveur"
            }

        # ===== RESPONSE =====
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._cors()
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