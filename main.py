import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import psycopg2
import os

# ==========================
# DATABASE URL NEON (pooler)
# ==========================
DATABASE_URL = os.environ.get("DATABASE_URL")  # On prendra l'URL depuis Render environment variable

# ==========================
# CONNEXION POSTGRES
# ==========================
def get_connection():
    try:
        print("Connexion à Neon en cours...")
        conn = psycopg2.connect(DATABASE_URL, sslmode="require")  # SSL obligatoire pour Neon
        print("Connecté à Neon !")
        return conn
    except Exception as e:
        print("❌ Erreur de connexion :", e)
        raise

# ==========================
# CREATION TABLE AUTO
# ==========================
def init_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS inscriptions (
            id SERIAL PRIMARY KEY,
            nom TEXT,
            email TEXT,
            telephone TEXT,
            date_naissance DATE,
            lieu_naissance TEXT,
            universite TEXT,
            examen TEXT,
            mention TEXT,
            document BYTEA,
            date_creation TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

# ==========================
# SERVEUR HTTP
# ==========================
class Handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        # autoriser CORS
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.end_headers()

    def do_POST(self):
        try:
            content_length = int(self.headers['Content-Length'])
            body = self.rfile.read(content_length)
            data = json.loads(body.decode("utf-8"))

            conn = get_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO inscriptions
                (nom,email,telephone,date_naissance,lieu_naissance,
                 universite,examen,mention,document)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                data.get("nom"),
                data.get("email"),
                data.get("telephone"),
                data.get("date_naissance"),
                data.get("lieu_naissance"),
                data.get("universite"),
                data.get("examen"),
                data.get("mention"),
                bytes(data.get("document"), "utf-8") if data.get("document") else None
            ))
            conn.commit()
            cur.close()
            conn.close()

            response = {"success": True, "message": "Votre dossier est bien reçu"}

        except Exception as e:
            print("❌ ERREUR :", e)
            response = {"success": False, "message": "Échec de l'envoi, réessayer plus tard"}

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())

# ==========================
# START SERVER
# ==========================
if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 8000))  # Render donne la variable PORT automatiquement
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"Backend actif sur http://0.0.0.0:{port}")
    server.serve_forever()