import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import psycopg2
from datetime import datetime

# ==========================
# DATABASE URL NEON
# ==========================
DATABASE_URL = "postgresql://neondb_owner:npg_PIjZofNhFE81@ep-gentle-wildflower-aiv4ogz4-pooler.c-4.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

# ==========================
# CONNEXION POSTGRES
# ==========================
def get_connection():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

# ==========================
# CREATION TABLE SI NON EXISTE
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
            date_naissance TEXT,
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
    print("✅ Table 'inscriptions' prête.")

# ==========================
# SERVEUR HTTP
# ==========================
class Handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.end_headers()

    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body.decode("utf-8"))

            # ==========================
            # Vérifications simples
            # ==========================
            # Date de naissance valide (pas dans le futur)
            date_naissance = datetime.strptime(data.get("date_naissance"), "%Y-%m-%d")
            if date_naissance > datetime.today():
                raise ValueError("Date de naissance invalide")

            # ==========================
            # INSERTION DANS LA TABLE
            # ==========================
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO inscriptions
                (nom,email,telephone,date_naissance,lieu_naissance,universite,examen,mention,document)
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
                bytes.fromhex(data.get("document")) if data.get("document") else None
            ))
            conn.commit()
            cur.close()
            conn.close()

            response = {"success": True, "message": "Votre dossier est bien reçu"}

        except Exception as e:
            print("❌ ERREUR:", e)
            response = {"success": False, "message": str(e) if str(e) else "Échec de l'envoi"}

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
    print("🔄 Connexion à Neon en cours...")
    init_db()
    server = HTTPServer(("0.0.0.0", 8000), Handler)
    print("🚀 Backend actif sur http://0.0.0.0:8000")
    server.serve_forever()