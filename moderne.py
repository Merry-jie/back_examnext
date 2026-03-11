import os
import sys
import json
import traceback
import re
import subprocess
import threading
import random
import time
import webbrowser
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, date
from kivy.app import App
from kivy.lang import Builder
from kivy.uix.screenmanager import ScreenManager, Screen, FadeTransition
from kivy.core.window import Window
from kivy.animation import Animation
from kivy.properties import StringProperty, ObjectProperty, NumericProperty, BooleanProperty
from kivy.metrics import dp
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.image import Image
from kivy.uix.textinput import TextInput
from kivy.uix.spinner import Spinner
from kivy.uix.scrollview import ScrollView
from kivy.uix.gridlayout import GridLayout
from kivy.uix.widget import Widget
from kivy.uix.togglebutton import ToggleButton
from kivy.uix.popup import Popup
from kivy.uix.progressbar import ProgressBar
from kivy.utils import get_color_from_hex
from kivy.graphics import Color, Ellipse, RoundedRectangle, Line, Rectangle
from kivy.config import Config
from kivy.logger import Logger

# Import pour la selection de fichiers
FILE_CHOOSER_AVAILABLE = False
try:
    from plyer import filechooser
    FILE_CHOOSER_AVAILABLE = True
    Logger.info("Utilisation de plyer pour la selection de fichiers")
except ImportError:
    try:
        from tkinter import Tk, filedialog
        import threading
        FILE_CHOOSER_AVAILABLE = True
        Logger.info("Utilisation de tkinter pour la selection de fichiers")
    except ImportError:
        Logger.warning("Ni plyer ni tkinter ne sont disponibles.")
        FILE_CHOOSER_AVAILABLE = False

# Import redoc pour la conversion (non utilise ici mais conserve)
try:
    from redoc import Redoc
    REDOC_AVAILABLE = True
except ImportError:
    REDOC_AVAILABLE = False
    Logger.warning("redoc non installe, le convertisseur utilisera un mode demo")

# Imports pour l'API IA et threading
import requests
from threading import Thread, Event

# Import pour PostgreSQL direct
try:
    import psycopg2
    from psycopg2 import pool
    from psycopg2.extras import RealDictCursor
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False
    Logger.warning("psycopg2 non disponible, utilisation du mode simulation")

# Imports pour l'analyse de documents REELS
try:
    import cv2
    import numpy as np
    import pytesseract
    from PIL import Image as PILImage
    import fitz  # PyMuPDF pour les PDF
    from pyzbar.pyzbar import decode
    REAL_ANALYSIS_AVAILABLE = True
except ImportError as e:
    REAL_ANALYSIS_AVAILABLE = False
    Logger.warning(f"Bibliotheques d'analyse non disponibles: {e}")

# Import pour la reconnaissance vocale
try:
    import speech_recognition as sr
    import pyttsx3
    import pyaudio
    import struct
    VOICE_AVAILABLE = True
except ImportError:
    VOICE_AVAILABLE = False
    Logger.warning("Bibliotheques de reconnaissance vocale non disponibles")

# Configuration de l'API StackAI (a personnaliser)
STACKAI_API_URL = "https://api.stack-ai.com/votre_endpoint"
STACKAI_API_KEY = "Bearer votre_cle_api"

# Configuration de la fenetre
Config.set('graphics', 'resizable', '0')
Config.set('graphics', 'width', '900')
Config.set('graphics', 'height', '700')

# -------------------------------------------------------------------
# Fonction utilitaire pour les chemins de ressources (images, etc.)
# -------------------------------------------------------------------
def resource_path(relative_path):
    """Retourne le chemin absolu vers la ressource (utile pour PyInstaller)"""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# -------------------------------------------------------------------
# BASE DE DONNEES POSTGRESQL AVEC VERIFICATION COMPLETE
# -------------------------------------------------------------------
class PostgresDB:
    def __init__(self, dsn, min_conn=1, max_conn=10, timeout=20):
        self.dsn = dsn
        self.pool = None
        self.connected = False
        self.table_exists = False
        self.has_data = False
        self.schema_valid = False
        self.connection_event = Event()
        self.timeout = timeout
        self.error_message = ""
        self.status_details = ""

        Thread(target=self._connect, daemon=True).start()

    def _connect(self):
        """Tente de se connecter et de verifier la table"""
        try:
            Logger.info(f"Tentative de connexion a PostgreSQL (timeout: {self.timeout}s)")
            self.pool = pool.ThreadedConnectionPool(1, 5, self.dsn)

            # Tester la connexion et verifier la table
            conn = self.pool.getconn()

            with conn.cursor() as cur:
                # 1. Verifier si la table inscriptions existe
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = 'inscriptions'
                    )
                """)
                table_exists = cur.fetchone()[0]

                if not table_exists:
                    self.error_message = "La table 'inscriptions' n'existe pas"
                    self.status_details = "Table manquante dans la base de donnees"
                    Logger.error(f"ERREUR: {self.error_message}")
                    self.table_exists = False
                    self.has_data = False
                    self.schema_valid = False
                    self.connected = False
                    self.pool.putconn(conn)
                    self.pool.closeall()
                    self.pool = None
                    return

                self.table_exists = True
                Logger.info("Table 'inscriptions' trouvee")

                # 2. Verifier si la table contient des donnees
                cur.execute("SELECT COUNT(*) FROM inscriptions")
                count = cur.fetchone()[0]

                if count == 0:
                    self.error_message = "La table 'inscriptions' est vide"
                    self.status_details = "Table existe mais aucune donnee"
                    Logger.warning(f"ATTENTION: {self.error_message}")
                    self.has_data = False
                    self.schema_valid = False
                else:
                    self.has_data = True
                    Logger.info(f"{count} enregistrements trouves dans la table")

                    # 3. Verifier les colonnes requises
                    required_columns = [
                        'id', 'nom', 'email', 'telephone', 'date_naissance',
                        'lieu_naissance', 'cisco_zap', 'examen',
                        'lieu_de_service_et_etablissement', 'document',
                        'date_creation', 'lu', 'flagged'
                    ]

                    cur.execute("""
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_name = 'inscriptions'
                    """)
                    existing_columns = [row[0] for row in cur.fetchall()]

                    missing_columns = []
                    for col in required_columns:
                        if col not in existing_columns:
                            missing_columns.append(col)

                    if missing_columns:
                        self.error_message = f"Colonnes manquantes: {missing_columns}"
                        self.status_details = f"Schema invalide - {len(missing_columns)} colonne(s) manquante(s)"
                        Logger.error(f"ERREUR: {self.error_message}")
                        self.schema_valid = False
                    else:
                        self.schema_valid = True
                        self.status_details = f"Schema valide - {count} enregistrement(s)"
                        Logger.info("Toutes les colonnes requises sont presentes")

            self.pool.putconn(conn)

            # Marquer comme connecte SEULEMENT si tout est valide
            if self.table_exists and self.has_data and self.schema_valid:
                self.connected = True
                Logger.info("Connexion PostgreSQL etablie avec succes - Utilisation des donnees reelles")
            else:
                self.connected = False
                if self.pool:
                    self.pool.closeall()
                    self.pool = None
                Logger.warning(f"Connexion etablie mais {self.error_message} - Utilisation des donnees simulees")

        except Exception as e:
            self.error_message = str(e)
            self.status_details = f"Erreur de connexion: {str(e)[:50]}"
            Logger.error(f"Erreur de connexion PostgreSQL: {e}")
            self.pool = None
            self.connected = False
            self.table_exists = False
            self.has_data = False
            self.schema_valid = False
        finally:
            self.connection_event.set()

    def is_fully_valid(self):
        """Retourne True seulement si la table existe ET contient des donnees ET le schema est valide"""
        return self.connected and self.table_exists and self.has_data and self.schema_valid

    def get_status_message(self):
        """Retourne un message d'etat pour l'affichage"""
        if self.is_fully_valid():
            return "Base de donnees reelle - Connexion etablie"
        else:
            return "Base de donnees simulation - Connexion"

    def get_status_details(self):
        """Retourne les details pour le popup"""
        return self.status_details

    def wait_for_connection(self):
        """Attend que la connexion soit etablie (ou timeout)"""
        if not self.connection_event.wait(timeout=self.timeout):
            self.error_message = f"Timeout de connexion apres {self.timeout}s"
            self.status_details = "Delai de connexion depasse"
            Logger.warning(f"ATTENTION: {self.error_message}")
            self.connected = False
            return False
        return self.is_fully_valid()

    def _get_connection(self):
        """Retourne une connexion uniquement si tout est valide"""
        if self.is_fully_valid() and self.pool:
            try:
                return self.pool.getconn()
            except Exception as e:
                Logger.error(f"Erreur d'obtention de connexion: {e}")
                return None
        return None

    def _put_connection(self, conn):
        if self.pool and conn:
            self.pool.putconn(conn)

    def _fetch_all(self, query, params=None):
        """Execute une requete uniquement si tout est valide"""
        if not self.is_fully_valid():
            return None

        conn = self._get_connection()
        if not conn:
            return None
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                return cur.fetchall()
        except Exception as e:
            Logger.error(f"Erreur SQL: {e}")
            return None
        finally:
            if conn:
                self._put_connection(conn)

    def _execute(self, query, params=None):
        """Execute une commande SQL uniquement si tout est valide"""
        if not self.is_fully_valid():
            return False

        conn = self._get_connection()
        if not conn:
            return False
        try:
            with conn.cursor() as cur:
                cur.execute(query, params)
                conn.commit()
            return True
        except Exception as e:
            Logger.error(f"Erreur SQL: {e}")
            conn.rollback()
            return False
        finally:
            if conn:
                self._put_connection(conn)

    def get_items_by_read_status(self, is_read, callback):
        def fetch():
            if not self.wait_for_connection():
                Logger.warning("PostgreSQL non disponible, utilisation des donnees de secours")
                items = self._get_fallback_data(filter_lu=is_read)
                formatted_items = []
                for row in items:
                    # Filtrer pour ne pas inclure les flagged dans les non-lu
                    if not is_read and row.get('flagged', False):
                        continue
                    formatted_items.append({
                        'id': row['id'],
                        'title': row['nom'],
                        'content': self._format_content(row),
                        'is_read': row['lu'],
                        'is_flagged': row.get('flagged', False),
                        'created_at': str(row['date_creation']) if row['date_creation'] else ''
                    })
                Clock.schedule_once(lambda dt: callback(formatted_items))
                return

            items = []
            query = "SELECT id, nom, email, telephone, date_naissance, lieu_naissance, cisco_zap, examen, lieu_de_service_et_etablissement, document, date_creation, lu, flagged FROM inscriptions WHERE lu = %s AND flagged = %s ORDER BY date_creation DESC"
            # Pour les non-lu, on exclut les flagged
            params = (is_read, False)
            rows = self._fetch_all(query, params)
            if rows is None:
                rows = self._get_fallback_data(filter_lu=is_read)
                # Filtrer les flagged des donnees de secours
                rows = [r for r in rows if not r.get('flagged', False)]
            for row in rows:
                items.append({
                    'id': row['id'],
                    'title': row['nom'],
                    'content': self._format_content(row),
                    'is_read': row['lu'],
                    'is_flagged': row.get('flagged', False),
                    'created_at': str(row['date_creation']) if row['date_creation'] else ''
                })
            Clock.schedule_once(lambda dt: callback(items))
        Thread(target=fetch).start()

    def get_flagged_items(self, callback):
        def fetch():
            if not self.wait_for_connection():
                Logger.warning("PostgreSQL non disponible, donnees de secours vides")
                items = self._get_fallback_data()
                flagged_items = []
                for row in items:
                    if row.get('flagged', False):
                        flagged_items.append({
                            'id': row['id'],
                            'title': row['nom'],
                            'content': self._format_content(row),
                            'is_read': row['lu'],
                            'is_flagged': row.get('flagged', True),
                            'created_at': str(row['date_creation']) if row['date_creation'] else ''
                        })
                Clock.schedule_once(lambda dt: callback(flagged_items))
                return

            items = []
            query = "SELECT id, nom, email, telephone, date_naissance, lieu_naissance, cisco_zap, examen, lieu_de_service_et_etablissement, document, date_creation, lu, flagged FROM inscriptions WHERE flagged = true ORDER BY date_creation DESC"
            rows = self._fetch_all(query)
            if rows:
                for row in rows:
                    items.append({
                        'id': row['id'],
                        'title': row['nom'],
                        'content': self._format_content(row),
                        'is_read': row['lu'],
                        'is_flagged': row.get('flagged', True),
                        'created_at': str(row['date_creation']) if row['date_creation'] else ''
                    })
            Clock.schedule_once(lambda dt: callback(items))
        Thread(target=fetch).start()

    def search_items(self, query, filter_type, callback):
        def fetch():
            if not self.wait_for_connection():
                Logger.warning("PostgreSQL non disponible, recherche sur donnees de secours")
                items = []
                search_term = query.lower()
                for row in self._get_fallback_data():
                    if filter_type == 'lu' and (not row['lu'] or row.get('flagged', False)):
                        continue
                    if filter_type == 'nonlu' and (row['lu'] or row.get('flagged', False)):
                        continue
                    if filter_type == 'marque' and not row.get('flagged', False):
                        continue
                    if search_term and search_term not in row['nom'].lower() and search_term not in row['email'].lower():
                        continue
                    items.append({
                        'id': row['id'],
                        'title': row['nom'],
                        'content': self._format_content(row),
                        'is_read': row['lu'],
                        'is_flagged': row.get('flagged', False),
                        'created_at': str(row['date_creation']) if row['date_creation'] else ''
                    })
                Clock.schedule_once(lambda dt: callback(items))
                return

            items = []
            search_term = f"%{query}%"
            sql = ""
            params = []
            if filter_type == 'lu':
                sql = "SELECT * FROM inscriptions WHERE (nom ILIKE %s OR email ILIKE %s OR telephone ILIKE %s) AND lu = true AND flagged = false ORDER BY date_creation DESC"
                params = [search_term, search_term, search_term]
            elif filter_type == 'nonlu':
                sql = "SELECT * FROM inscriptions WHERE (nom ILIKE %s OR email ILIKE %s OR telephone ILIKE %s) AND lu = false AND flagged = false ORDER BY date_creation DESC"
                params = [search_term, search_term, search_term]
            elif filter_type == 'marque':
                sql = "SELECT * FROM inscriptions WHERE (nom ILIKE %s OR email ILIKE %s OR telephone ILIKE %s) AND flagged = true ORDER BY date_creation DESC"
                params = [search_term, search_term, search_term]
            else:
                sql = "SELECT * FROM inscriptions WHERE nom ILIKE %s OR email ILIKE %s OR telephone ILIKE %s ORDER BY date_creation DESC"
                params = [search_term, search_term, search_term]
            if sql:
                rows = self._fetch_all(sql, params)
                if rows is None:
                    rows = self._get_fallback_data(search=query)
                for row in rows:
                    items.append({
                        'id': row['id'],
                        'title': row['nom'],
                        'content': self._format_content(row),
                        'is_read': row['lu'],
                        'is_flagged': row.get('flagged', False),
                        'created_at': str(row['date_creation']) if row['date_creation'] else ''
                    })
            Clock.schedule_once(lambda dt: callback(items))
        Thread(target=fetch).start()

    def get_item(self, item_id, callback):
        def fetch():
            if not self.wait_for_connection():
                Logger.warning("PostgreSQL non disponible, utilisation des donnees de secours")
                item = self._get_fallback_item(item_id)
                Clock.schedule_once(lambda dt: callback(item))
                return

            query = "SELECT * FROM inscriptions WHERE id = %s"
            rows = self._fetch_all(query, (item_id,))
            if rows and len(rows) > 0:
                row = rows[0]
                item = {
                    'id': row['id'],
                    'nom': row['nom'],
                    'email': row['email'],
                    'telephone': row['telephone'],
                    'date_naissance': row['date_naissance'],
                    'lieu_naissance': row['lieu_naissance'],
                    'cisco_zap': row['cisco_zap'],
                    'examen': row['examen'],
                    'lieu_de_service_et_etablissement': row['lieu_de_service_et_etablissement'],
                    'document': row['document'],
                    'date_creation': str(row['date_creation']) if row['date_creation'] else '',
                    'lu': row['lu'],
                    'flagged': row.get('flagged', False)
                }
            else:
                item = self._get_fallback_item(item_id)
            Clock.schedule_once(lambda dt: callback(item))
        Thread(target=fetch).start()

    def update_read_status(self, item_id, is_read, callback=None):
        def update():
            if not self.wait_for_connection():
                Logger.warning("PostgreSQL non disponible, mise a jour ignoree")
                if callback:
                    Clock.schedule_once(lambda dt: callback(False))
                return

            success = self._execute("UPDATE inscriptions SET lu = %s, flagged = %s WHERE id = %s", (is_read, False, item_id))
            if callback:
                Clock.schedule_once(lambda dt: callback(success))
        Thread(target=update).start()

    def update_flagged_status(self, item_id, is_flagged, callback=None):
        def update():
            if not self.wait_for_connection():
                Logger.warning("PostgreSQL non disponible, mise a jour ignoree")
                if callback:
                    Clock.schedule_once(lambda dt: callback(False))
                return

            success = self._execute("UPDATE inscriptions SET flagged = %s, lu = %s WHERE id = %s", (is_flagged, False, item_id))
            if callback:
                Clock.schedule_once(lambda dt: callback(success))
        Thread(target=update).start()

    def _get_fallback_data(self, filter_lu=None, search=None):
        """Donnees de secours anonymes"""
        fallback = [
            {
                'id': 1,
                'nom': 'OK EEE',
                'email': 'aaa@bbb.ccc',
                'telephone': '0101010101',
                'date_naissance': '1988-07-12',
                'lieu_naissance': 'XXX',
                'cisco_zap': 'XXX111',
                'examen': 'XXX',
                'lieu_de_service_et_etablissement': 'XXX',
                'document': 'doc1.pdf',
                'date_creation': '2024-02-20T14:15:00',
                'lu': False,
                'flagged': False
            },
            {
                'id': 2,
                'nom': 'NO OK',
                'email': 'bbb@ccc.ddd',
                'telephone': '0202020202',
                'date_naissance': '1990-01-01',
                'lieu_naissance': 'YYY',
                'cisco_zap': 'YYY222',
                'examen': 'YYY',
                'lieu_de_service_et_etablissement': 'YYY',
                'document': 'doc2.pdf',
                'date_creation': '2024-01-15T10:30:00',
                'lu': False,
                'flagged': False
            },
            {
                'id': 3,
                'nom': 'NOO OK',
                'email': 'ccc@ddd.eee',
                'telephone': '0303030303',
                'date_naissance': '2023-09-30',
                'lieu_naissance': 'ZZZ',
                'cisco_zap': 'ZZZ333',
                'examen': 'ZZZ',
                'lieu_de_service_et_etablissement': 'ZZZ',
                'document': 'doc3.pdf',
                'date_creation': '2024-03-01T09:45:00',
                'lu': False,
                'flagged': False
            },
            {
                'id': 4,
                'nom': 'OK EER',
                'email': 'ddd@eee.fff',
                'telephone': '0404040404',
                'date_naissance': '1985-05-15',
                'lieu_naissance': 'WWW',
                'cisco_zap': 'WWW444',
                'examen': 'WWW',
                'lieu_de_service_et_etablissement': 'WWW',
                'document': 'doc4.pdf',
                'date_creation': '2024-02-20T14:15:00',
                'lu': True,
                'flagged': False
            },
            {
                'id': 5,
                'nom': 'NO OK',
                'email': 'eee@fff.ggg',
                'telephone': '0505050505',
                'date_naissance': '1995-03-20',
                'lieu_naissance': 'VVV',
                'cisco_zap': 'VVV555',
                'examen': 'VVV',
                'lieu_de_service_et_etablissement': 'VVV',
                'document': 'doc5.pdf',
                'date_creation': '2023-01-15T10:30:00',
                'lu': False,
                'flagged': True
            },
            {
                'id': 6,
                'nom': 'OK EEE',
                'email': 'fff@ggg.hhh',
                'telephone': '0606060606',
                'date_naissance': '1992-11-25',
                'lieu_naissance': 'UUU',
                'cisco_zap': 'UUU666',
                'examen': 'UUU',
                'lieu_de_service_et_etablissement': 'UUU',
                'document': 'doc6.pdf',
                'date_creation': '2024-04-10T11:20:00',
                'lu': False,
                'flagged': False
            }
        ]
        if filter_lu is not None:
            return [f for f in fallback if f['lu'] == filter_lu and not f.get('flagged', False)]
        if search:
            return [f for f in fallback if search.lower() in f['nom'].lower()]
        return fallback

    def _get_fallback_item(self, item_id):
        return {
            'id': item_id,
            'nom': 'OK XXX',
            'email': 'xxx@yyy.zzz',
            'telephone': '0000000000',
            'date_naissance': '2000-01-01',
            'lieu_naissance': 'XXX',
            'cisco_zap': 'XXX',
            'examen': 'XXX',
            'lieu_de_service_et_etablissement': 'XXX',
            'document': 'document.pdf',
            'date_creation': datetime.now().isoformat(),
            'lu': False,
            'flagged': False
        }

    def _format_content(self, row):
        return f"{row['nom']} - {row['email']} - {row['telephone']}"

# -------------------------------------------------------------------
# BASE DE DONNEES SIMULEE
# -------------------------------------------------------------------
class MockDatabase:
    """Base de donnees simulee pour les tests"""

    def __init__(self):
        self.data_file = 'cybercore_data.json'
        self.load_data()
        self.status_details = "Mode simulation actif"

    def get_status_message(self):
        return "Base de donnees simulation - Connexion"

    def get_status_details(self):
        return self.status_details

    def load_data(self):
        """Charge les donnees depuis un fichier JSON"""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r') as f:
                    self.items = json.load(f)
                print(f"Donnees chargees: {len(self.items)} dossiers")
                self.status_details = f"{len(self.items)} dossiers charges"
            except:
                self.items = self.get_default_data()
                self.save_data()
        else:
            self.items = self.get_default_data()
            self.save_data()

    def save_data(self):
        """Sauvegarde les donnees dans un fichier JSON"""
        try:
            with open(self.data_file, 'w') as f:
                json.dump(self.items, f, indent=2)
            print("Donnees sauvegardees")
        except Exception as e:
            print(f"Erreur sauvegarde: {e}")

    def get_default_data(self):
        """Donnees par defaut avec des noms completement anonymes"""
        return [
            {
                'id': 1,
                'nom': 'OK EEE',
                'email': 'aaa@bbb.ccc',
                'telephone': '0101010101',
                'date_naissance': '1988-07-12',
                'lieu_naissance': 'XXX',
                'cisco_zap': 'XXX111',
                'examen': 'XXX',
                'lieu_de_service_et_etablissement': 'XXX',
                'document': 'doc1.pdf',
                'date_creation': '2024-02-20T14:15:00',
                'lu': False,
                'flagged': False
            },
            {
                'id': 2,
                'nom': 'NO OK',
                'email': 'bbb@ccc.ddd',
                'telephone': '0202020202',
                'date_naissance': '1990-01-01',
                'lieu_naissance': 'YYY',
                'cisco_zap': 'YYY222',
                'examen': 'YYY',
                'lieu_de_service_et_etablissement': 'YYY',
                'document': 'doc2.pdf',
                'date_creation': '2024-01-15T10:30:00',
                'lu': False,
                'flagged': False
            },
            {
                'id': 3,
                'nom': 'NOO OK',
                'email': 'ccc@ddd.eee',
                'telephone': '0303030303',
                'date_naissance': '2023-09-30',
                'lieu_naissance': 'ZZZ',
                'cisco_zap': 'ZZZ333',
                'examen': 'ZZZ',
                'lieu_de_service_et_etablissement': 'ZZZ',
                'document': 'doc3.pdf',
                'date_creation': '2024-03-01T09:45:00',
                'lu': False,
                'flagged': False
            },
            {
                'id': 4,
                'nom': 'OK EER',
                'email': 'ddd@eee.fff',
                'telephone': '0404040404',
                'date_naissance': '1985-05-15',
                'lieu_naissance': 'WWW',
                'cisco_zap': 'WWW444',
                'examen': 'WWW',
                'lieu_de_service_et_etablissement': 'WWW',
                'document': 'doc4.pdf',
                'date_creation': '2024-02-20T14:15:00',
                'lu': True,
                'flagged': False
            },
            {
                'id': 5,
                'nom': 'NO OK',
                'email': 'eee@fff.ggg',
                'telephone': '0505050505',
                'date_naissance': '1995-03-20',
                'lieu_naissance': 'VVV',
                'cisco_zap': 'VVV555',
                'examen': 'VVV',
                'lieu_de_service_et_etablissement': 'VVV',
                'document': 'doc5.pdf',
                'date_creation': '2023-01-15T10:30:00',
                'lu': False,
                'flagged': True
            },
            {
                'id': 6,
                'nom': 'OK EEE',
                'email': 'fff@ggg.hhh',
                'telephone': '0606060606',
                'date_naissance': '1992-11-25',
                'lieu_naissance': 'UUU',
                'cisco_zap': 'UUU666',
                'examen': 'UUU',
                'lieu_de_service_et_etablissement': 'UUU',
                'document': 'doc6.pdf',
                'date_creation': '2024-04-10T11:20:00',
                'lu': False,
                'flagged': False
            }
        ]

    def get_items_by_read_status(self, is_read, callback):
        """Simule la recuperation des items par statut de lecture"""
        items = []
        for row in self.items:
            # IMPORTANT: Pour les non-lu, on exclut les flagged
            if row['lu'] == is_read and not row.get('flagged', False):
                items.append({
                    'id': row['id'],
                    'title': row['nom'],
                    'content': self._format_content(row),
                    'is_read': row['lu'],
                    'is_flagged': row.get('flagged', False),
                    'created_at': str(row['date_creation']) if row['date_creation'] else ''
                })
        Clock.schedule_once(lambda dt: callback(items), 0.2)

    def get_flagged_items(self, callback):
        """Simule la recuperation des items marques"""
        items = []
        for row in self.items:
            if row.get('flagged', False):
                items.append({
                    'id': row['id'],
                    'title': row['nom'],
                    'content': self._format_content(row),
                    'is_read': row['lu'],
                    'is_flagged': row.get('flagged', True),
                    'created_at': str(row['date_creation']) if row['date_creation'] else ''
                })
        Clock.schedule_once(lambda dt: callback(items), 0.2)

    def search_items(self, query, filter_type, callback):
        """Simule la recherche d'items"""
        items = []
        search_term = query.lower()

        for row in self.items:
            if filter_type == 'lu':
                if not row['lu'] or row.get('flagged', False):
                    continue
            elif filter_type == 'nonlu':
                if row['lu'] or row.get('flagged', False):
                    continue
            elif filter_type == 'marque':
                if not row.get('flagged', False):
                    continue
            if search_term and search_term not in row['nom'].lower() and search_term not in row['email'].lower():
                continue
            items.append({
                'id': row['id'],
                'title': row['nom'],
                'content': self._format_content(row),
                'is_read': row['lu'],
                'is_flagged': row.get('flagged', False),
                'created_at': str(row['date_creation']) if row['date_creation'] else ''
            })

        Clock.schedule_once(lambda dt: callback(items), 0.2)

    def get_item(self, item_id, callback):
        """Simule la recuperation d'un item specifique"""
        for row in self.items:
            if row['id'] == item_id:
                item = {
                    'id': row['id'],
                    'nom': row['nom'],
                    'email': row['email'],
                    'telephone': row['telephone'],
                    'date_naissance': row['date_naissance'],
                    'lieu_naissance': row['lieu_naissance'],
                    'cisco_zap': row['cisco_zap'],
                    'examen': row['examen'],
                    'lieu_de_service_et_etablissement': row['lieu_de_service_et_etablissement'],
                    'document': row['document'],
                    'date_creation': str(row['date_creation']) if row['date_creation'] else '',
                    'lu': row['lu'],
                    'flagged': row.get('flagged', False)
                }
                Clock.schedule_once(lambda dt: callback(item), 0.1)
                return

        Clock.schedule_once(lambda dt: callback(self._get_fallback_item(item_id)), 0.1)

    def update_read_status(self, item_id, is_read, callback=None):
        """Met a jour le statut de lecture"""
        for row in self.items:
            if row['id'] == item_id:
                row['lu'] = is_read
                if is_read:
                    row['flagged'] = False
                self.save_data()
                break

        if callback:
            Clock.schedule_once(lambda dt: callback(True), 0.1)

    def update_flagged_status(self, item_id, is_flagged, callback=None):
        """Met a jour le statut de flag"""
        for row in self.items:
            if row['id'] == item_id:
                row['flagged'] = is_flagged
                if is_flagged:
                    row['lu'] = False
                self.save_data()
                break

        if callback:
            Clock.schedule_once(lambda dt: callback(True), 0.1)

    def _format_content(self, row):
        return f"{row['nom']} - {row['email']} - {row['telephone']}"

    def _get_fallback_item(self, item_id):
        return {
            'id': item_id,
            'nom': 'OK XXX',
            'email': 'xxx@yyy.zzz',
            'telephone': '0000000000',
            'date_naissance': '2000-01-01',
            'lieu_naissance': 'XXX',
            'cisco_zap': 'XXX',
            'examen': 'XXX',
            'lieu_de_service_et_etablissement': 'XXX',
            'document': 'document.pdf',
            'date_creation': datetime.now().isoformat(),
            'lu': False,
            'flagged': False
        }

# -------------------------------------------------------------------
# SERVICE DE CONNEXION AVEC INDICATEUR
# -------------------------------------------------------------------
class ConnectionManager:
    """Gere la connexion a la base de donnees avec affichage du statut"""

    def __init__(self):
        self.status_popup = None

    def show_connecting_popup(self, message="Connexion a la base de donnees..."):
        """Affiche un popup pendant la connexion"""
        content = BoxLayout(orientation='vertical', spacing=dp(15), padding=dp(20))

        with content.canvas.before:
            Color(rgba=[0.02, 0.02, 0.05, 0.98])
            RoundedRectangle(pos=content.pos, size=content.size, radius=[dp(10),])

        content.add_widget(Label(
            text="CONNEXION",
            color=App.get_running_app().theme_colors['accent'],
            font_size='18sp',
            bold=True,
            size_hint_y=None,
            height=dp(40)
        ))

        content.add_widget(Label(
            text=message,
            color=[1,1,1,1],
            size_hint_y=None,
            height=dp(60)
        ))

        progress = ProgressBar(
            max=100,
            value=30,
            size_hint_y=None,
            height=dp(20)
        )
        content.add_widget(progress)

        self.status_popup = Popup(
            title='',
            content=content,
            size_hint=(0.5, 0.3),
            background='',
            separator_color=[0,0,0,0],
            auto_dismiss=False
        )
        self.status_popup.open()

    def show_connection_result(self, success, message, db_status="", details=""):
        """Affiche le resultat de la connexion"""
        if self.status_popup:
            self.status_popup.dismiss()

        content = BoxLayout(orientation='vertical', spacing=dp(15), padding=dp(20))

        with content.canvas.before:
            Color(rgba=[0.02, 0.02, 0.05, 0.98])
            RoundedRectangle(pos=content.pos, size=content.size, radius=[dp(10),])

        if success:
            color = [0.3,0.8,0.3,1]
            title_text = "CONNEXION"
        else:
            color = [0.9,0.6,0.1,1]  # Orange
            title_text = "CONNEXION"

        content.add_widget(Label(
            text=title_text,
            color=color,
            font_size='18sp',
            bold=True,
            size_hint_y=None,
            height=dp(40)
        ))

        # Ajouter seulement le statut sans texte supplementaire
        if db_status:
            content.add_widget(Label(
                text=db_status,
                color=[0.8,0.8,0.9,1],
                size_hint_y=None,
                height=dp(30),
                font_size='12sp'
            ))

        ok_btn = Button(
            text="OK",
            size_hint=(None, None),
            size=(dp(100), dp(40)),
            pos_hint={'center_x': 0.5},
            background_color=[0,0,0,0]
        )
        with ok_btn.canvas.before:
            Color(rgba=App.get_running_app().theme_colors['accent'])
            RoundedRectangle(pos=ok_btn.pos, size=ok_btn.size, radius=[dp(8),])

        result_popup = Popup(
            title='',
            content=content,
            size_hint=(0.5, 0.3),
            background='',
            separator_color=[0,0,0,0],
            auto_dismiss=True
        )

        ok_btn.bind(on_release=result_popup.dismiss)
        content.add_widget(ok_btn)

        result_popup.open()
        Clock.schedule_once(lambda dt: result_popup.dismiss(), 5)

# -------------------------------------------------------------------
# SERVICE D'ANALYSE DE DOCUMENTS REEL (avec Tesseract et pyzbar)
# -------------------------------------------------------------------
class RealDocumentAnalyzer:
    """
    Véritable analyseur de documents avec OCR et QR code
    Compare nom, date_naissance, lieu_naissance et age du document
    """
    
    def __init__(self):
        self.available = REAL_ANALYSIS_AVAILABLE
        if not self.available:
            print("⚠️ Bibliotheques d'analyse non disponibles, utilisation du mode simulation")
    
    def analyze_document(self, file_path, item_id=None):
        """
        Analyse un document (image ou PDF) et retourne les informations extraites
        """
        if not self.available:
            return self._simulate_analysis(item_id)
        
        try:
            # Vérifier si le fichier existe
            if not os.path.exists(file_path):
                return {'success': False, 'error': f'Fichier non trouvé: {file_path}'}
            
            # Si c'est un PDF, le convertir en image
            if file_path.lower().endswith('.pdf'):
                images = self._pdf_to_images(file_path)
                if not images:
                    return {'success': False, 'error': 'Impossible de convertir le PDF'}
                # Prendre la première page
                img = images[0]
            else:
                # Charger l'image directement
                img = cv2.imread(file_path)
                if img is None:
                    return {'success': False, 'error': 'Format d\'image non supporté'}
            
            # Convertir en RGB pour PIL
            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            pil_image = PILImage.fromarray(img_rgb)
            
            # 1. Lire le QR code
            qr_data = self._read_qr_code(pil_image)
            
            # 2. Extraire le texte avec OCR
            text = self._extract_text(img)
            
            # 3. Détecter les ratures (simplifié)
            has_alterations = self._detect_alterations(img)
            
            # 4. Extraire les informations du texte (nom, date, lieu, age)
            text_info = self._extract_critical_info(text)
            
            # 5. Extraire l'age du document
            doc_age = self._extract_document_age(text)
            
            # 6. Récupérer l'age du QR code
            qr_age = qr_data.get('ans') if isinstance(qr_data, dict) else None
            if qr_age:
                try:
                    qr_age = int(qr_age)
                except:
                    qr_age = None
            
            # 7. Construire le résultat de validation
            validation_result = self._validate_document(
                text_info, qr_data, doc_age, qr_age, has_alterations, item_id
            )
            
            return validation_result
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {'success': False, 'error': str(e), 'simulation': False}
    
    def _pdf_to_images(self, pdf_path, dpi=300):
        """Convertit un PDF en images"""
        images = []
        try:
            # Ouvrir le PDF
            pdf_document = fitz.open(pdf_path)
            
            for page_num in range(len(pdf_document)):
                page = pdf_document[page_num]
                
                # Convertir la page en image
                zoom = dpi / 72
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat)
                
                # Convertir en format OpenCV
                img_data = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
                img = cv2.cvtColor(img_data, cv2.COLOR_RGB2BGR)
                images.append(img)
            
            pdf_document.close()
            return images
            
        except Exception as e:
            print(f"Erreur conversion PDF: {e}")
            return []
    
    def _read_qr_code(self, pil_image):
        """Lit et décode un QR code - retourne un dictionnaire"""
        decoded_objects = decode(pil_image)
        
        for obj in decoded_objects:
            if obj.type == 'QRCODE':
                try:
                    # Essayer de parser comme JSON
                    data = obj.data.decode('utf-8')
                    return json.loads(data)
                except json.JSONDecodeError:
                    # Si ce n'est pas du JSON, retourner le texte brut
                    return {'raw': obj.data.decode('utf-8')}
        
        return {}
    
    def _extract_text(self, img):
        """Extrait le texte de l'image avec Tesseract"""
        # Prétraitement pour améliorer l'OCR
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Amélioration du contraste
        gray = cv2.equalizeHist(gray)
        
        # Seuillage adaptatif
        thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
        
        # OCR en français
        text = pytesseract.image_to_string(thresh, lang='fra+eng')
        return text
    
    def _detect_alterations(self, img):
        """Détecte les ratures/modifications dans l'image (version simplifiée)"""
        # Convertir en niveaux de gris
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Détection de contours
        edges = cv2.Canny(gray, 50, 150)
        
        # Compter les contours (trop de contours = possible rature)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        # Si plus de 50 contours, considéré comme suspect
        return len(contours) > 50
    
    def _extract_critical_info(self, text):
        """
        Extrait UNIQUEMENT les informations critiques:
        - nom
        - date_naissance
        - lieu_naissance
        """
        info = {}
        
        # Nettoyer le texte
        text = text.replace('\n', ' ').replace('\r', '')
        
        # Patterns pour trouver les informations (format libre)
        patterns = {
            'nom': r'([A-Za-zÀ-ÿ\s-]{3,50})',  # Mot de 3 à 50 lettres
            'date_naissance': r'(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',  # Date
            'lieu_naissance': r'([A-Za-zÀ-ÿ\s-]{3,50})'  # Lieu
        }
        
        # Rechercher le nom (souvent en début de document)
        nom_match = re.search(r'(?:^|\s)([A-Z][A-Za-zÀ-ÿ\s-]{2,50})(?:\s|$)', text)
        if nom_match:
            info['nom'] = nom_match.group(1).strip()
        
        # Rechercher la date
        date_match = re.search(r'(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})', text)
        if date_match:
            info['date_naissance'] = date_match.group(1).strip()
        
        # Rechercher le lieu (souvent après "né à" ou "lieu")
        lieu_match = re.search(r'(?:né à|né le|lieu|naissance)[\s:]*([A-Za-zÀ-ÿ\s-]{3,50})', text, re.IGNORECASE)
        if lieu_match:
            info['lieu_naissance'] = lieu_match.group(1).strip()
        
        return info
    
    def _extract_document_age(self, text):
        """
        Extrait l'âge du document (nombre devant "ans")
        Exemple: "5 ans", "3ans", "ans 10"
        """
        # Pattern pour trouver un nombre suivi de "ans"
        patterns = [
            r'(\d+)\s*ans',  # 5 ans, 3ans
            r'ans\s*(\d+)',  # ans 10
            r'âge[\s:]*(\d+)',  # âge: 5
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    return int(match.group(1))
                except:
                    pass
        return None
    
    def _validate_document(self, text_info, qr_data, doc_age, qr_age, has_alterations, item_id):
        """
        Valide le document selon les critères:
        - nom, date_naissance, lieu_naissance identiques entre BD, OCR et QR
        - âge du document > 2 ans ET correspondant entre OCR et QR
        - pas de ratures
        """
        errors = []
        comparisons = {}
        
        # Récupérer les données de la BD (via callback plus tard)
        # Pour l'instant, on simule avec item_id
        
        # 1. Comparer les champs critiques avec le QR code
        critical_fields = ['nom', 'date_naissance', 'lieu_naissance']
        
        for field in critical_fields:
            text_val = self._normalize_text(text_info.get(field, ''))
            qr_val = self._normalize_text(qr_data.get(field, '')) if isinstance(qr_data, dict) else ''
            
            comparisons[field] = {
                'document': text_info.get(field, ''),
                'qr': qr_data.get(field, '') if isinstance(qr_data, dict) else '',
                'match': text_val == qr_val if text_val and qr_val else False
            }
            
            if text_val and qr_val and text_val != qr_val:
                errors.append(f"Le champ '{field}' ne correspond pas entre le document et le QR code")
        
        # 2. Vérifier l'âge du document
        age_valid = False
        age_match = False
        
        if doc_age is not None and qr_age is not None:
            age_match = doc_age == qr_age
            age_valid = doc_age > 2
            
            comparisons['age'] = {
                'document': doc_age,
                'qr': qr_age,
                'match': age_match,
                'valid': age_valid
            }
            
            if not age_match:
                errors.append(f"L'âge du document ({doc_age} ans) ne correspond pas au QR code ({qr_age} ans)")
            elif not age_valid:
                errors.append(f"L'âge du document ({doc_age} ans) doit être supérieur à 2 ans")
        else:
            if doc_age is None:
                errors.append("Impossible de déterminer l'âge du document")
            if qr_age is None:
                errors.append("Âge manquant dans le QR code")
        
        # 3. Vérifier les ratures
        if has_alterations:
            errors.append("Ratures ou modifications détectées dans le document")
        
        # 4. Déterminer le succès
        success = len(errors) == 0
        
        return {
            'success': success,
            'errors': errors,
            'comparisons': comparisons,
            'document_info': text_info,
            'qr_info': qr_data,
            'db_id': item_id,
            'has_alterations': has_alterations,
            'doc_age': doc_age,
            'qr_age': qr_age,
            'simulation': False
        }
    
    def _normalize_text(self, text):
        """Normalise le texte pour comparaison exacte"""
        if not text:
            return ''
        # Mettre en majuscules
        text = text.upper()
        # Enlever les accents
        text = text.replace('É', 'E').replace('È', 'E').replace('Ê', 'E')
        text = text.replace('À', 'A').replace('Â', 'A')
        text = text.replace('Ç', 'C')
        text = text.replace('Ô', 'O').replace('Ö', 'O')
        text = text.replace('Û', 'U').replace('Ü', 'U')
        text = text.replace('Î', 'I').replace('Ï', 'I')
        # Enlever les caractères non pertinents
        text = re.sub(r'[^A-Z0-9/.-]', '', text)
        return text
    
    def _simulate_analysis(self, item_id):
        """Simulation pour quand les bibliothèques ne sont pas disponibles"""
        if item_id == 1:
            return {
                'success': True,
                'errors': [],
                'comparisons': {
                    'nom': {'document': 'OK EEE', 'qr': 'OK EEE', 'match': True},
                    'date_naissance': {'document': '1988-07-12', 'qr': '1988-07-12', 'match': True},
                    'lieu_naissance': {'document': 'XXX', 'qr': 'XXX', 'match': True},
                    'age': {'document': 5, 'qr': 5, 'match': True, 'valid': True}
                },
                'document_info': {'nom': 'OK EEE', 'date_naissance': '1988-07-12', 'lieu_naissance': 'XXX'},
                'qr_info': {'nom': 'OK EEE', 'date_naissance': '1988-07-12', 'lieu_naissance': 'XXX', 'ans': 5},
                'db_id': item_id,
                'has_alterations': False,
                'doc_age': 5,
                'qr_age': 5,
                'simulation': True
            }
        else:
            return {
                'success': False,
                'errors': ['Simulation: document non valide'],
                'comparisons': {},
                'document_info': {},
                'qr_info': {},
                'db_id': item_id,
                'has_alterations': True,
                'doc_age': None,
                'qr_age': None,
                'simulation': True
            }

# -------------------------------------------------------------------
# Widget Switch personnalise
# -------------------------------------------------------------------
class CustomSwitch(ToggleButton):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_color = [0,0,0,0]
        self.size_hint = (None, None)
        self.size = (dp(60), dp(30))
        self.bind(state=self.update_switch)
        self.bind(pos=self.update_canvas, size=self.update_canvas)

    def update_canvas(self, *args):
        self.canvas.before.clear()
        with self.canvas.before:
            if self.state == 'down':
                Color(rgba=App.get_running_app().theme_colors['accent'])
            else:
                Color(rgba=[0.3, 0.3, 0.4, 1])
            RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(15),])

            Color(rgba=[1,1,1,1])
            if self.state == 'down':
                Ellipse(pos=(self.x + self.width - dp(28), self.y + dp(3)), size=(dp(24), dp(24)))
            else:
                Ellipse(pos=(self.x + dp(3), self.y + dp(3)), size=(dp(24), dp(24)))

    def update_switch(self, instance, value):
        self.update_canvas()

# -------------------------------------------------------------------
# Widget Scroll avec boutons integres (uniquement en bas)
# -------------------------------------------------------------------
class ScrollableWithButtons(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation='vertical', **kwargs)
        self.scroll_view = None
        self.content = None
        self.build_ui()

    def build_ui(self):
        # ScrollView
        self.scroll_view = ScrollView()
        self.add_widget(self.scroll_view)

        # Boutons de scroll en bas uniquement
        bottom_buttons = BoxLayout(size_hint_y=None, height=dp(25), spacing=dp(10), padding=[dp(10), 0])

        # Espaceur a gauche pour aligner les boutons a droite
        bottom_buttons.add_widget(Widget(size_hint_x=0.85))

        # Boutons de scroll avec texte
        btn_container = BoxLayout(size_hint_x=None, width=dp(100), spacing=dp(5))

        self.up_btn = Button(
            text="HAUT",
            size_hint=(None, None),
            size=(dp(45), dp(20)),
            background_color=[0,0,0,0],
            bold=True,
            font_size='10sp'
        )
        with self.up_btn.canvas.before:
            Color(rgba=App.get_running_app().theme_colors['accent'])
            RoundedRectangle(pos=self.up_btn.pos, size=self.up_btn.size, radius=[dp(4),])

        self.down_btn = Button(
            text="BAS",
            size_hint=(None, None),
            size=(dp(45), dp(20)),
            background_color=[0,0,0,0],
            bold=True,
            font_size='10sp'
        )
        with self.down_btn.canvas.before:
            Color(rgba=App.get_running_app().theme_colors['accent'])
            RoundedRectangle(pos=self.down_btn.pos, size=self.down_btn.size, radius=[dp(4),])

        btn_container.add_widget(self.up_btn)
        btn_container.add_widget(self.down_btn)
        bottom_buttons.add_widget(btn_container)

        self.add_widget(bottom_buttons)

        # Lier les boutons
        def scroll_up(instance):
            if self.scroll_view:
                self.scroll_view.scroll_y = min(1.0, self.scroll_view.scroll_y + 0.1)

        def scroll_down(instance):
            if self.scroll_view:
                self.scroll_view.scroll_y = max(0.0, self.scroll_view.scroll_y - 0.1)

        self.up_btn.bind(on_release=scroll_up)
        self.down_btn.bind(on_release=scroll_down)

    def set_content(self, content_widget):
        self.scroll_view.clear_widgets()
        self.scroll_view.add_widget(content_widget)

# -------------------------------------------------------------------
# En-tete avec image et barre de recherche
# -------------------------------------------------------------------
class SearchHeader(BoxLayout):
    def __init__(self, on_search_callback=None, **kwargs):
        super().__init__(orientation='horizontal', size_hint_y=None, height=dp(60), padding=[dp(15), dp(10)], spacing=dp(15), **kwargs)
        self.on_search_callback = on_search_callback
        self.build_ui()

    def build_ui(self):
        icon_container = BoxLayout(size_hint_x=0.08)
        with icon_container.canvas:
            Color(rgba=App.get_running_app().theme_colors['accent'][:3] + [0.3])
            RoundedRectangle(pos=(icon_container.x + dp(5), icon_container.y + dp(10)), size=(dp(40), dp(40)), radius=[dp(10),])

        self.icon = Image(
            source=resource_path('box.png'),
            size_hint=(None, None),
            size=(dp(30), dp(30)),
            pos_hint={'center_x': 0.5, 'center_y': 0.5}
        )
        icon_container.add_widget(self.icon)
        self.add_widget(icon_container)

        # Barre de recherche plus longue
        self.search_input = TextInput(
            hint_text="Rechercher un dossier...",
            multiline=False,
            size_hint_x=0.4,
            background_color=[0.15,0.15,0.25,1],
            foreground_color=[1,1,1,1],
            cursor_color=App.get_running_app().theme_colors['accent'],
            padding=[dp(15), dp(10)]
        )

        # Contour violet
        with self.search_input.canvas.after:
            Color(rgba=App.get_running_app().theme_colors['accent'])
            Line(rounded_rectangle=(self.search_input.x, self.search_input.y,
                                    self.search_input.width, self.search_input.height, dp(8)), width=1.5)

        self.search_input.bind(on_text_validate=self.on_search_enter)
        self.search_input.bind(pos=self._update_search_border, size=self._update_search_border)

        self.add_widget(self.search_input)

        self.add_widget(Widget(size_hint_x=0.52))

    def _update_search_border(self, instance, value):
        instance.canvas.after.clear()
        with instance.canvas.after:
            Color(rgba=App.get_running_app().theme_colors['accent'])
            Line(rounded_rectangle=(instance.x, instance.y, instance.width, instance.height, dp(8)), width=1.5)

    def on_search_click(self, instance):
        if self.on_search_callback:
            self.on_search_callback(self.search_input.text)

    def on_search_enter(self, instance):
        if self.on_search_callback:
            self.on_search_callback(self.search_input.text)

# -------------------------------------------------------------------
# Widget pour un element compact
# -------------------------------------------------------------------
class CompactItem(BoxLayout):
    def __init__(self, item, **kwargs):
        super().__init__(orientation='horizontal', size_hint_y=None, height=dp(45), padding=[dp(15), dp(5)], spacing=dp(10), **kwargs)
        self.item = item
        self.build_ui()

    def build_ui(self):
        with self.canvas.before:
            Color(rgba=[0.15, 0.15, 0.25, 0.6])
            self.rect_bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(10),])
            Color(rgba=App.get_running_app().theme_colors['accent'][:3] + [0.3])
            self.rect_line = Line(rounded_rectangle=(self.x, self.y, self.width, self.height, dp(10)), width=1.2)
        self.bind(pos=self.update_rect, size=self.update_rect)

        id_label = Label(
            text=f"#{self.item['id']:03d}",
            font_size='18sp',
            bold=True,
            color=App.get_running_app().theme_colors['accent'],
            size_hint_x=0.12,
            halign='center',
            valign='middle'
        )
        self.add_widget(id_label)

        title_label = Label(
            text=self.item['title'],
            font_size='14sp',
            color=[1,1,1,1],
            size_hint_x=0.6,
            halign='left',
            valign='middle',
            shorten=True
        )
        self.add_widget(title_label)

        self.switch = CustomSwitch()
        self.switch.bind(on_release=self.show_detail_popup)
        self.add_widget(self.switch)

        self.status_indicator = Widget(size_hint_x=0.05)
        with self.status_indicator.canvas:
            if self.item['is_read']:
                Color(rgba=[0.3, 0.8, 0.3, 1])
            elif self.item['is_flagged']:
                Color(rgba=[0.9, 0.6, 0.1, 1])  # Orange pour marque
            else:
                Color(rgba=[0.9, 0.3, 0.3, 1])
            Ellipse(pos=(self.status_indicator.x + dp(10), self.status_indicator.y + dp(18)), size=(dp(8), dp(8)))
        self.status_indicator.bind(pos=self.update_status_dot)
        self.add_widget(self.status_indicator)

    def update_rect(self, *args):
        self.rect_bg.pos = self.pos
        self.rect_bg.size = self.size
        self.rect_line.rounded_rectangle = (self.x, self.y, self.width, self.height, dp(10))

    def update_status_dot(self, *args):
        self.status_indicator.canvas.clear()
        with self.status_indicator.canvas:
            if self.item['is_read']:
                Color(rgba=[0.3, 0.8, 0.3, 1])
            elif self.item['is_flagged']:
                Color(rgba=[0.9, 0.6, 0.1, 1])
            else:
                Color(rgba=[0.9, 0.3, 0.3, 1])
            Ellipse(pos=(self.status_indicator.x + dp(10), self.status_indicator.y + dp(18)), size=(dp(8), dp(8)))

    def show_detail_popup(self, instance):
        app = App.get_running_app()
        app.db.get_item(self.item['id'], self._display_popup)

    def _display_popup(self, item):
        # Creer une reference au popup
        popup = None

        # Contenu principal du popup - BoxLayout vertical pour organiser
        content = BoxLayout(orientation='vertical', spacing=dp(15), padding=dp(20))

        # Fond sombre pour TOUT le contenu
        with content.canvas.before:
            Color(rgba=[0.02, 0.02, 0.05, 0.98])  # Fond tres sombre
            content.rect_bg = RoundedRectangle(pos=content.pos, size=content.size, radius=[dp(15),])
        content.bind(pos=self._update_content_bg, size=self._update_content_bg)

        # Titre
        title_label = Label(
            text=f"Dossier #{item['id']} - {item['nom']}",
            font_size='22sp',
            bold=True,
            color=App.get_running_app().theme_colors['accent'],
            size_hint_y=None,
            height=dp(60),
            halign='center'
        )
        content.add_widget(title_label)

        # Ligne de separation
        sep = Widget(size_hint_y=None, height=dp(2))
        with sep.canvas:
            Color(rgba=App.get_running_app().theme_colors['accent'][:3] + [0.7])
            Rectangle(pos=sep.pos, size=sep.size)
        sep.bind(pos=self._update_sep, size=self._update_sep)
        content.add_widget(sep)

        # Zone principale avec boutons de scroll verticaux sur le cote droit
        main_area = BoxLayout(orientation='horizontal', spacing=dp(10))

        # Zone d'information en tableau
        info_scroll = ScrollView(size_hint_x=0.9)

        # Conteneur principal pour le tableau
        table_container = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(2))
        table_container.bind(minimum_height=table_container.setter('height'))

        # En-tetes du tableau
        header = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(2))
        with header.canvas.before:
            Color(rgba=[0.15, 0.15, 0.25, 0.9])
            RoundedRectangle(pos=header.pos, size=header.size, radius=[dp(5),])

        header_label1 = Label(
            text="CHAMP",
            size_hint_x=0.35,
            color=App.get_running_app().theme_colors['accent'],
            bold=True,
            font_size='14sp',
            halign='center',
            valign='middle'
        )
        header_label2 = Label(
            text="VALEUR",
            size_hint_x=0.65,
            color=App.get_running_app().theme_colors['accent'],
            bold=True,
            font_size='14sp',
            halign='center',
            valign='middle'
        )
        header.add_widget(header_label1)
        header.add_widget(header_label2)
        table_container.add_widget(header)

        # Liste des champs
        fields = [
            ("ID", str(item['id'])),
            ("Nom complet", item['nom']),
            ("Email", item['email']),
            ("Telephone", item['telephone']),
            ("Date naissance", item['date_naissance']),
            ("Lieu naissance", item['lieu_naissance']),
            ("Cisco ZAP", item['cisco_zap']),
            ("Examen", item['examen']),
            ("Lieu service", item['lieu_de_service_et_etablissement']),
            ("Document", item['document']),
            ("Date creation", item['date_creation']),
            ("Statut", "Lu" if item['lu'] else "Non lu" if not item['flagged'] else "Marque")
        ]

        for i, (label, value) in enumerate(fields):
            # Ligne du tableau
            row = BoxLayout(size_hint_y=None, height=dp(45), spacing=dp(2))

            # Fond alterne pour les lignes
            with row.canvas.before:
                if i % 2 == 0:
                    Color(rgba=[0.1, 0.1, 0.15, 0.95])  # Lignes paires
                else:
                    Color(rgba=[0.05, 0.05, 0.1, 0.95])  # Lignes impaires
                RoundedRectangle(pos=row.pos, size=row.size, radius=[dp(3),])

            # Libelle avec largeur fixe pour alignement parfait
            label_widget = Label(
                text=label,
                size_hint_x=0.35,
                color=[0.9, 0.9, 1, 1],
                halign='right',
                valign='middle',
                text_size=(None, dp(45)),
                bold=True,
                font_size='13sp',
                padding=[dp(15), 0]
            )
            label_widget.bind(size=lambda s, w: setattr(s, 'text_size', (s.width, None)))

            # Valeur
            value_widget = Label(
                text=value,
                size_hint_x=0.65,
                color=[1, 1, 1, 1],
                halign='left',
                valign='middle',
                text_size=(None, dp(45)),
                font_size='13sp',
                padding=[dp(15), 0]
            )
            value_widget.bind(size=lambda s, w: setattr(s, 'text_size', (s.width, None)))

            row.add_widget(label_widget)
            row.add_widget(value_widget)
            table_container.add_widget(row)

        info_scroll.add_widget(table_container)
        main_area.add_widget(info_scroll)

        # Boutons de scroll verticaux sur le cote droit (petits)
        scroll_buttons = BoxLayout(orientation='vertical', size_hint_x=None, width=dp(30), spacing=dp(5))

        # Bouton Haut
        up_btn = Button(
            text="▲",
            size_hint_y=0.5,
            background_color=[0,0,0,0],
            bold=True,
            font_size='12sp'
        )
        with up_btn.canvas.before:
            Color(rgba=App.get_running_app().theme_colors['accent'])
            RoundedRectangle(pos=up_btn.pos, size=up_btn.size, radius=[dp(4),])

        # Bouton Bas
        down_btn = Button(
            text="▼",
            size_hint_y=0.5,
            background_color=[0,0,0,0],
            bold=True,
            font_size='12sp'
        )
        with down_btn.canvas.before:
            Color(rgba=App.get_running_app().theme_colors['accent'])
            RoundedRectangle(pos=down_btn.pos, size=down_btn.size, radius=[dp(4),])

        scroll_buttons.add_widget(up_btn)
        scroll_buttons.add_widget(down_btn)
        main_area.add_widget(scroll_buttons)

        content.add_widget(main_area)

        # Fonctions pour le scroll
        def scroll_up(instance):
            info_scroll.scroll_y = min(1.0, info_scroll.scroll_y + 0.2)

        def scroll_down(instance):
            info_scroll.scroll_y = max(0.0, info_scroll.scroll_y - 0.2)

        up_btn.bind(on_release=scroll_up)
        down_btn.bind(on_release=scroll_down)

        # Ligne de separation avant le bouton Traiter
        sep2 = Widget(size_hint_y=None, height=dp(2))
        with sep2.canvas:
            Color(rgba=App.get_running_app().theme_colors['accent'][:3] + [0.5])
            Rectangle(pos=sep2.pos, size=sep2.size)
        sep2.bind(pos=self._update_sep, size=self._update_sep)
        content.add_widget(sep2)

        # Bouton Traiter encadre (violet)
        traiter_container = BoxLayout(size_hint_y=None, height=dp(70), padding=[dp(20), dp(5)])

        traiter_btn = Button(
            text="TRAITER LE DOSSIER",
            size_hint_y=None,
            height=dp(55),
            background_color=[0, 0, 0, 0],
            bold=True,
            font_size='15sp'
        )

        # Encadrement du bouton en violet
        with traiter_btn.canvas.before:
            Color(rgba=App.get_running_app().theme_colors['accent'])
            Line(rounded_rectangle=(traiter_btn.x, traiter_btn.y, traiter_btn.width, traiter_btn.height, dp(10)), width=2)
            Color(rgba=App.get_running_app().theme_colors['accent'][:3] + [0.2])
            RoundedRectangle(pos=traiter_btn.pos, size=traiter_btn.size, radius=[dp(10),])

        traiter_btn.bind(on_release=lambda btn, iid=item['id']: self.verifier_document(iid, popup))
        traiter_btn.bind(pos=self._update_traiter_btn, size=self._update_traiter_btn)

        traiter_container.add_widget(traiter_btn)
        content.add_widget(traiter_container)

        # Ligne de separation avant le bouton de fermeture
        sep3 = Widget(size_hint_y=None, height=dp(2))
        with sep3.canvas:
            Color(rgba=App.get_running_app().theme_colors['accent'][:3] + [0.3])
            Rectangle(pos=sep3.pos, size=sep3.size)
        sep3.bind(pos=self._update_sep, size=self._update_sep)
        content.add_widget(sep3)

        # Bouton de fermeture sur le cote
        close_container = BoxLayout(size_hint_y=None, height=dp(50))

        # Switch de fermeture aligne a droite
        close_switch = CustomSwitch()
        close_switch.state = 'down'
        close_switch.pos_hint = {'right': 1}

        def close_popup(instance):
            if popup:
                popup.dismiss()

        close_switch.bind(on_release=close_popup)
        close_container.add_widget(Widget())  # Espaceur a gauche
        close_container.add_widget(close_switch)
        content.add_widget(close_container)

        # Creation du popup
        popup = Popup(
            title='',
            title_color=[1,1,1,1],
            content=content,
            size_hint=(0.9, 0.9),
            background='',
            separator_color=[0,0,0,0],
            auto_dismiss=False
        )

        popup.open()

    def verifier_document(self, item_id, parent_popup):
        """Lance la verification RELLE du document"""
        app = App.get_running_app()
        
        # Utiliser le vrai analyseur si disponible et si la BD est connectée
        if REAL_ANALYSIS_AVAILABLE and hasattr(app, 'db') and app.db.is_fully_valid():
            # Chemin vers le document (à adapter selon votre structure)
            document_path = f"documents/{item_id}.pdf"
            
            # Lancer l'analyse réelle dans un thread
            Thread(target=self._run_real_verification, args=(item_id, document_path, parent_popup)).start()
        else:
            # Mode simulation
            app.db.get_item(item_id, lambda item: self.afficher_verification_simulation(item, parent_popup))

    def _run_real_verification(self, item_id, document_path, parent_popup):
        """Exécute la vraie analyse"""
        app = App.get_running_app()
        
        # Récupérer les données de la BD
        app.db.get_item(item_id, lambda item: self._real_verification_with_item(item, document_path, parent_popup))
    
    def _real_verification_with_item(self, item, document_path, parent_popup):
        """Suite de la vraie analyse avec les données BD"""
        # Créer l'analyseur
        analyzer = RealDocumentAnalyzer()
        
        # Analyser le document
        result = analyzer.analyze_document(document_path, item['id'])
        
        # Afficher le résultat
        Clock.schedule_once(lambda dt: self.afficher_verification_reelle(result, parent_popup))

    def afficher_verification_reelle(self, result, parent_popup):
        """Affiche l'interface de verification avec les vrais résultats"""
        # Fermer le popup parent
        if parent_popup:
            parent_popup.dismiss()

        # Créer le popup de vérification
        verif_popup = None

        # Contenu - TOUT EN SOMBRE
        content = BoxLayout(orientation='vertical', spacing=dp(20), padding=dp(25))

        # Fond sombre pour TOUT le contenu
        with content.canvas.before:
            Color(rgba=[0.02, 0.02, 0.05, 0.98])  # Fond très sombre
            content.rect_bg = RoundedRectangle(pos=content.pos, size=content.size, radius=[dp(15),])
        content.bind(pos=self._update_content_bg, size=self._update_content_bg)

        # Titre
        title = Label(
            text="RESULTAT DE VERIFICATION",
            font_size='20sp',
            bold=True,
            color=App.get_running_app().theme_colors['accent'],
            size_hint_y=None,
            height=dp(50)
        )
        content.add_widget(title)

        # Indicateur de succès/échec
        if result['success']:
            status_label = Label(
                text="✅ DOSSIER VALIDE",
                color=[0.3, 0.8, 0.3, 1],
                size_hint_y=None,
                height=dp(40),
                font_size='18sp',
                bold=True
            )
        else:
            status_label = Label(
                text="❌ DOSSIER NON VALIDE",
                color=[0.9, 0.3, 0.3, 1],
                size_hint_y=None,
                height=dp(40),
                font_size='18sp',
                bold=True
            )
        content.add_widget(status_label)

        # Zone de résultats avec scroll
        result_area = ScrollableWithButtons(size_hint_y=0.6)
        result_container = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(10))
        result_container.bind(minimum_height=result_container.setter('height'))

        # Afficher les erreurs
        if result['errors']:
            errors_title = Label(
                text="Erreurs detectees :",
                color=[1,1,1,1],
                size_hint_y=None,
                height=dp(30),
                font_size='14sp',
                bold=True
            )
            result_container.add_widget(errors_title)

            for error in result['errors']:
                error_label = Label(
                    text=f"• {error}",
                    color=[0.9, 0.6, 0.6, 1],
                    size_hint_y=None,
                    height=dp(25),
                    font_size='12sp'
                )
                result_container.add_widget(error_label)

        # Afficher les comparaisons
        if result.get('comparisons'):
            comp_title = Label(
                text="\nComparaisons :",
                color=[1,1,1,1],
                size_hint_y=None,
                height=dp(30),
                font_size='14sp',
                bold=True
            )
            result_container.add_widget(comp_title)

            for field, comp in result['comparisons'].items():
                if field == 'age':
                    row = BoxLayout(size_hint_y=None, height=dp(30))
                    color = [0.3,0.8,0.3,1] if comp.get('match') and comp.get('valid') else [0.9,0.3,0.3,1]
                    
                    row.add_widget(Label(
                        text=f"Âge document: {comp.get('document', '?')} ans",
                        size_hint_x=0.5,
                        color=color
                    ))
                    row.add_widget(Label(
                        text=f"Âge QR: {comp.get('qr', '?')} ans",
                        size_hint_x=0.5,
                        color=color
                    ))
                    result_container.add_widget(row)
                else:
                    row = BoxLayout(size_hint_y=None, height=dp(30))
                    color = [0.3,0.8,0.3,1] if comp.get('match') else [0.9,0.3,0.3,1]
                    
                    row.add_widget(Label(
                        text=field.upper(),
                        size_hint_x=0.25,
                        color=[1,1,1,1]
                    ))
                    row.add_widget(Label(
                        text=comp.get('document', '?'),
                        size_hint_x=0.375,
                        color=color
                    ))
                    row.add_widget(Label(
                        text=comp.get('qr', '?'),
                        size_hint_x=0.375,
                        color=color
                    ))
                    result_container.add_widget(row)

        # Afficher les ratures
        if result.get('has_alterations'):
            rature_label = Label(
                text="⚠️ Ratures detectees dans le document",
                color=[0.9,0.6,0.1,1],
                size_hint_y=None,
                height=dp(30)
            )
            result_container.add_widget(rature_label)

        # Afficher le mode simulation si applicable
        if result.get('simulation'):
            sim_label = Label(
                text="(Mode simulation - bibliotheques d'analyse non disponibles)",
                color=[0.9,0.6,0.1,1],
                size_hint_y=None,
                height=dp(25),
                font_size='11sp'
            )
            result_container.add_widget(sim_label)

        result_area.set_content(result_container)
        content.add_widget(result_area)

        # Boutons d'action
        action_buttons = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(10))

        # Bouton OK pour fermer
        ok_btn = Button(
            text="FERMER",
            size_hint_x=0.5,
            background_color=[0,0,0,0]
        )
        with ok_btn.canvas.before:
            Color(rgba=App.get_running_app().theme_colors['accent'])
            RoundedRectangle(pos=ok_btn.pos, size=ok_btn.size, radius=[dp(8),])

        # Bouton Marquer comme lu (si succès)
        mark_btn = Button(
            text="MARQUER LU",
            size_hint_x=0.5,
            background_color=[0,0,0,0]
        )
        with mark_btn.canvas.before:
            Color(rgba=[0.3,0.8,0.3,1])
            RoundedRectangle(pos=mark_btn.pos, size=mark_btn.size, radius=[dp(8),])

        action_buttons.add_widget(ok_btn)
        if result['success']:
            action_buttons.add_widget(mark_btn)
            mark_btn.bind(on_release=lambda x: self._mark_as_read(result, verif_popup))

        content.add_widget(action_buttons)

        # Ligne de séparation avant le toggle switch
        sep_close = Widget(size_hint_y=None, height=dp(2))
        with sep_close.canvas:
            Color(rgba=App.get_running_app().theme_colors['accent'][:3] + [0.3])
            Rectangle(pos=sep_close.pos, size=sep_close.size)
        sep_close.bind(pos=self._update_sep, size=self._update_sep)
        content.add_widget(sep_close)

        # Toggle switch pour fermer
        close_container = BoxLayout(size_hint_y=None, height=dp(40))

        # Espaceur à gauche pour aligner à droite
        close_container.add_widget(Widget(size_hint_x=0.9))

        close_switch = CustomSwitch()
        close_switch.state = 'down'

        def close_verif_popup(instance):
            if verif_popup:
                verif_popup.dismiss()

        close_switch.bind(on_release=close_verif_popup)
        close_container.add_widget(close_switch)
        content.add_widget(close_container)

        verif_popup = Popup(
            title='',
            content=content,
            size_hint=(0.8, 0.8),
            background='',
            separator_color=[0,0,0,0],
            auto_dismiss=False
        )
        verif_popup.open()

        ok_btn.bind(on_release=close_verif_popup)

    def afficher_verification_simulation(self, item, parent_popup):
        """Affiche l'interface de vérification simulée (fallback)"""
        # Version simplifiée pour la simulation
        content = BoxLayout(orientation='vertical', spacing=dp(10), padding=dp(20))
        content.add_widget(Label(text=f"Simulation de vérification pour {item['nom']}", color=[1,1,1,1]))
        ok_btn = Button(text="OK", size_hint=(None,None), size=(dp(80), dp(40)))
        ok_btn.bind(on_release=lambda x: parent_popup.dismiss())
        content.add_widget(ok_btn)

        popup = Popup(title='Simulation', content=content, size_hint=(0.5,0.3))
        popup.open()

    def _mark_as_read(self, result, popup):
        """Marque le dossier comme lu et met à jour l'affichage"""
        item_id = result.get('db_id')
        if item_id:
            app = App.get_running_app()

            # Mettre à jour la base de données
            app.db.update_read_status(item_id, True)
            app.db.update_flagged_status(item_id, False)

            # Fermer le popup
            if popup:
                popup.dismiss()

            # FORCER LE RAFRAÎCHISSEMENT DE L'ONGLET COURANT
            main_screen = app.root.get_screen('main')
            Clock.schedule_once(lambda dt: main_screen.force_refresh_current_tab(), 0.5)

    def _update_content_bg(self, instance, value):
        if hasattr(instance, 'rect_bg'):
            instance.rect_bg.pos = instance.pos
            instance.rect_bg.size = instance.size

    def _update_sep(self, instance, value):
        instance.canvas.clear()
        with instance.canvas:
            Color(rgba=App.get_running_app().theme_colors['accent'][:3] + [0.7])
            Rectangle(pos=instance.pos, size=instance.size)

    def _update_traiter_btn(self, instance, value):
        instance.canvas.before.clear()
        with instance.canvas.before:
            Color(rgba=App.get_running_app().theme_colors['accent'])
            Line(rounded_rectangle=(instance.x, instance.y, instance.width, instance.height, dp(10)), width=2)
            Color(rgba=App.get_running_app().theme_colors['accent'][:3] + [0.2])
            RoundedRectangle(pos=instance.pos, size=instance.size, radius=[dp(10),])

# -------------------------------------------------------------------
# Écran d'authentification
# -------------------------------------------------------------------
class AuthScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.password = "APL-I-E123"  # Mot de passe précis

    def authenticate(self, password):
        if password == self.password:  # Mot de passe exact
            # Vider le champ pour la prochaine fois
            self.ids.pass_input.text = ""
            self.manager.current = 'main'
        else:
            # Animation de secousse
            anim = Animation(x=self.x+10, duration=0.05) + Animation(x=self.x-10, duration=0.05) + Animation(x=self.x, duration=0.05)
            anim.start(self)
            # Afficher un message d'erreur
            self.ids.error_label.text = "Mot de passe incorrect"
            Clock.schedule_once(lambda dt: self.clear_error(), 2)

    def clear_error(self):
        self.ids.error_label.text = ""

# -------------------------------------------------------------------
# MODULE TERMINAL SIGMA (version simplifiée pour la démo)
# -------------------------------------------------------------------
class ConverterApp(BoxLayout):
    """
    Module de terminal interactif avec style Matrix.
    - Animation de demarrage : pluie binaire qui tombe dans la zone de saisie
    - Logo ASCII "SIGMA" qui apparait ensuite
    - Zone de commande tres grande
    - Boutons HAUT/BAS pour le scroll
    - Execution reelle de commandes Linux via subprocess
    - Une seule commande a la fois
    """
    def __init__(self, **kwargs):
        super().__init__(orientation='vertical', spacing=dp(5), padding=dp(10), **kwargs)
        self.build_ui()
        self.animation_running = False
        self.animation_event = None
        self.command_running = False

    def build_ui(self):
        self.clear_widgets()

        # Titre du module
        title = Label(
            text="TERMINAL SIGMA",
            font_size='18sp', bold=True,
            color=App.get_running_app().theme_colors['accent'],
            size_hint_y=None, height=dp(40)
        )
        self.add_widget(title)

        # --- ZONE D'AFFICHAGE AVEC BOUTONS HAUT/BAS ---
        # Creer un ScrollableWithButtons pour la console
        self.console_scrollable = ScrollableWithButtons(size_hint_y=0.3)  # Plus petit pour laisser de la place a la saisie

        # Conteneur pour le label de la console
        console_container = BoxLayout(orientation='vertical', size_hint_y=None)
        console_container.bind(minimum_height=console_container.setter('height'))

        # Label pour l'affichage (avec markup)
        self.console_label = Label(
            text="",
            markup=True,
            size_hint_y=None,
            color=(0, 1, 0, 1),
            font_name='RobotoMono-Regular',
            font_size='13sp',
            valign='top',
            halign='left',
            text_size=(self.console_scrollable.width - dp(20), None),
            padding=[dp(10), dp(10)]
        )
        self.console_label.bind(
            texture_size=lambda instance, size: setattr(instance, 'height', size[1]),
            width=lambda *args: setattr(self.console_label, 'text_size', (self.console_label.width, None))
        )

        console_container.add_widget(self.console_label)
        self.console_scrollable.set_content(console_container)
        self.add_widget(self.console_scrollable)

        # Ligne de separation lumineuse
        sep = Widget(size_hint_y=None, height=dp(2))
        with sep.canvas:
            Color(rgba=App.get_running_app().theme_colors['accent'])
            Rectangle(pos=sep.pos, size=sep.size)
        sep.bind(pos=self._update_sep, size=self._update_sep)
        self.add_widget(sep)

        # Barre de saisie des commandes (TRES GRANDE) - ou tombera la pluie binaire
        self.input_field = TextInput(
            multiline=False,  # Une seule ligne pour les commandes
            size_hint_y=0.5,  # Tres grande zone de saisie
            background_color=(0.05, 0.05, 0.05, 1),  # Noir profond
            foreground_color=(0, 1, 0, 1),  # Vert Matrix
            cursor_color=(0, 1, 0, 1),
            hint_text="",
            font_name='RobotoMono-Regular',
            font_size='14sp',
            padding=[dp(15), dp(15)],
            readonly=True,  # Commence en lecture seule pendant l'animation
            write_tab=False  # Pas de tabulation
        )
        self.input_field.bind(on_text_validate=self.on_enter)
        self.add_widget(self.input_field)

        # Bouton Retour
        back_btn = Button(
            text="RETOUR AUX MODULES",
            size_hint_y=None,
            height=dp(50),
            background_color=[0, 0, 0, 0],
            bold=True
        )
        with back_btn.canvas.before:
            Color(rgba=App.get_running_app().theme_colors['accent'])
            RoundedRectangle(pos=back_btn.pos, size=back_btn.size, radius=[dp(10),])
        back_btn.bind(on_release=self.go_back)
        back_btn.bind(pos=self._update_btn_rect, size=self._update_btn_rect)
        self.add_widget(back_btn)

        # Lancer l'animation de demarrage
        Clock.schedule_once(self.start_animation, 0.5)

    def _update_sep(self, instance, value):
        instance.canvas.clear()
        with instance.canvas:
            Color(rgba=App.get_running_app().theme_colors['accent'])
            Rectangle(pos=instance.pos, size=instance.size)

    def _update_btn_rect(self, instance, value):
        instance.canvas.before.clear()
        with instance.canvas.before:
            Color(rgba=App.get_running_app().theme_colors['accent'])
            RoundedRectangle(pos=instance.pos, size=instance.size, radius=[dp(10),])

    def go_back(self, *args):
        main_screen = App.get_running_app().root.get_screen('main')
        main_screen.show_module_list()

    # -----------------------------------------------------------------
    # Animation de demarrage : pluie binaire qui tombe du haut vers le bas
    # -----------------------------------------------------------------
    def start_animation(self, dt):
        self.input_field.text = ""
        self.input_field.readonly = True  # Bloque la saisie pendant l'animation
        self.animation_running = True
        self.animation_lines = 0
        # On utilise un intervalle plus court pour un effet plus fluide
        self.animation_event = Clock.schedule_interval(self.add_binary_line_to_input, 0.1)

    def add_binary_line_to_input(self, dt):
        if not self.animation_running:
            return False
        
        # Generer une ligne de binaire aleatoire
        line = ''.join(str(random.randint(0, 1)) for _ in range(60))
        
        # Effet de chute du haut vers le bas : ajouter la ligne en haut et laisser descendre
        lines = self.input_field.text.split('\n')
        lines.insert(0, line)
        
        # Garder environ 20 lignes pour un effet de hauteur constante
        if len(lines) > 20:
            lines = lines[:20]
        
        self.input_field.text = '\n'.join(lines)
        
        self.animation_lines += 1
        
        # Apres environ 3 secondes (30 * 0.1 = 3s), on arrete
        if self.animation_lines >= 30:
            self.animation_running = False
            if self.animation_event:
                self.animation_event.cancel()
            # Effacer la zone de saisie
            self.input_field.text = ""
            # Afficher le logo SIGMA dans la console
            self.show_logo()
        return True

    def show_logo(self):
        """Affiche le logo ASCII de SIGMA apres l'animation"""
        logo = r"""
[color=00ff00]
   ███████╗██╗ ██████╗ ███╗   ███╗ █████╗ 
   ██╔════╝██║██╔════╝ ████╗ ████║██╔══██╗
   ███████╗██║██║  ███╗██╔████╔██║███████║
   ╚════██║██║██║   ██║██║╚██╝██║██╔══██║
   ███████║██║╚██████╔╝██║ ╚═╝ ██║██║  ██║
   ╚══════╝╚═╝ ╚═════╝ ╚═╝     ╚═╝╚═╝  ╚═╝
[/color]
"""
        self.console_label.text = logo + "\n"
        self.console_label.text += "[color=00ff00]Systeme pret. Tapez 'help' pour la liste des commandes.[/color]\n"
        
        # Reactiver la saisie
        self.input_field.readonly = False
        self.input_field.hint_text = "Entrez une commande puis ENTER..."
        self.input_field.foreground_color = (0, 1, 0, 1)
        self.input_field.text = ""
        
        self.show_prompt()

    def show_prompt(self):
        """Affiche le prompt dans la console"""
        self.console_label.text += "\n[color=00ffff]root@sigma:~#[/color] "
        # Defiler automatiquement vers le bas
        Clock.schedule_once(lambda dt: setattr(self.console_scrollable.scroll_view, 'scroll_y', 0), 0.1)

    # -----------------------------------------------------------------
    # Gestion des commandes - UNE SEULE COMMANDE A LA FOIS
    # -----------------------------------------------------------------
    def on_enter(self, instance):
        if self.input_field.readonly or self.command_running:
            return  # Ignorer les entrees pendant l'animation ou si une commande est en cours
            
        cmd = instance.text.strip()
        if not cmd:
            # Si commande vide, juste reafficher le prompt
            self.show_prompt()
            instance.text = ""
            return

        # Afficher la commande dans la console (remplacer le dernier prompt)
        # Supprimer le dernier prompt avant d'ajouter la commande
        current_text = self.console_label.text
        if current_text.endswith("[color=00ffff]root@sigma:~#[/color] "):
            current_text = current_text[:-len("[color=00ffff]root@sigma:~#[/color] ")]
            self.console_label.text = current_text
        
        self.console_label.text += f"[color=00ffff]root@sigma:~#[/color] {cmd}\n"

        # Desactiver la saisie pendant l'execution
        self.input_field.readonly = True
        self.command_running = True
        self.input_field.text = ""

        # Interpreter la commande
        self.execute_command(cmd)

    def execute_command(self, cmd):
        """Interprete la commande et lance l'action correspondante"""
        cmd_lower = cmd.lower()

        # Alias conviviaux
        if cmd_lower == "google":
            self.run_process("firefox &")
            self.console_label.text += "[color=7777ff]Ouverture de Firefox...[/color]\n"
            # Reafficher le prompt immediatement (le processus est en arrière-plan)
            self.command_finished()
        elif cmd_lower == "office":
            self.run_process("libreoffice &")
            self.console_label.text += "[color=7777ff]Lancement de LibreOffice...[/color]\n"
            self.command_finished()
        elif cmd_lower == "matrix":
            self.run_process("xterm -e cmatrix &")
            self.console_label.text += "[color=7777ff]Deploiement de la pluie binaire...[/color]\n"
            self.command_finished()
        elif cmd_lower == "sigma":
            # Reafficher le logo
            self.console_label.text = ""
            self.show_logo()
            self.command_finished()
        elif cmd_lower == "clear":
            self.console_label.text = ""
            self.command_finished()
        elif cmd_lower == "help":
            help_text = (
                "[color=00ff00]Commandes disponibles :[/color]\n"
                "  google    - Ouvre Firefox\n"
                "  office    - Ouvre LibreOffice\n"
                "  matrix    - Lance la pluie binaire (cmatrix)\n"
                "  sigma     - Reaffiche le logo\n"
                "  clear     - Efface l'ecran\n"
                "  help      - Affiche cette aide\n"
                "  [color=7777ff]Toute autre commande sera executee directement[/color]\n"
            )
            self.console_label.text += help_text
            self.command_finished()
        else:
            # Executer directement la commande (ex: ls, ping, etc.)
            self.run_process(cmd)

    def run_process(self, command):
        """Lance une commande shell en arriere-plan sans bloquer"""
        def target():
            try:
                # Utiliser shell=True pour que les commandes comme "firefox &" fonctionnent
                process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                
                # Si la commande n'a pas de '&', on attend un peu pour recuperer la sortie
                if '&' not in command:
                    try:
                        stdout, stderr = process.communicate(timeout=2)
                        if stdout:
                            Clock.schedule_once(lambda dt: self.append_output(stdout))
                        if stderr:
                            Clock.schedule_once(lambda dt: self.append_output(f"[color=ff0000]{stderr}[/color]\n"))
                    except subprocess.TimeoutExpired:
                        # La commande continue en arrière-plan
                        pass
            except Exception as e:
                error_msg = f"[color=ff0000]Erreur d'execution : {str(e)}[/color]\n"
                Clock.schedule_once(lambda dt: self.append_output(error_msg))
            
            # Toujours terminer la commande
            Clock.schedule_once(lambda dt: self.command_finished(), 0.5)
            
        thread = Thread(target=target)
        thread.daemon = True
        thread.start()

    def command_finished(self):
        """Appele quand une commande est terminee"""
        self.command_running = False
        self.input_field.readonly = False
        self.input_field.focus = True
        self.show_prompt()

    def append_output(self, text):
        self.console_label.text += text
        # Defiler vers le bas
        Clock.schedule_once(lambda dt: setattr(self.console_scrollable.scroll_view, 'scroll_y', 0), 0.1)

# -------------------------------------------------------------------
# Module Note
# -------------------------------------------------------------------
class NoteApp(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation='vertical', spacing=dp(10), padding=dp(10), **kwargs)
        self.notes_file = os.path.join(os.path.dirname(__file__), 'notes.json')
        self.notes = []
        self.current_note_index = None
        self.load_notes()
        self.build_ui()

    def build_ui(self):
        self.clear_widgets()
        
        # Titre
        title = Label(
            text="MES NOTES",
            font_size='18sp',
            bold=True,
            color=App.get_running_app().theme_colors['accent'],
            size_hint_y=None,
            height=dp(40)
        )
        self.add_widget(title)
        
        # Bouton Nouvelle note avec contour et fond violet
        new_btn_container = BoxLayout(size_hint_y=None, height=dp(60), padding=[dp(20), dp(5)])
        new_btn = Button(
            text="+ NOUVELLE NOTE", 
            size_hint_y=None,
            height=dp(50),
            background_color=[0,0,0,0],
            bold=True,
            font_size='16sp'
        )
        # Encadrement et fond violet
        with new_btn.canvas.before:
            Color(rgba=App.get_running_app().theme_colors['accent'])
            RoundedRectangle(pos=new_btn.pos, size=new_btn.size, radius=[dp(8),])
            Color(rgba=[0.2, 0.2, 0.3, 0.3])
            RoundedRectangle(pos=new_btn.pos, size=new_btn.size, radius=[dp(8),])
        
        new_btn.bind(on_release=self.new_note)
        new_btn.bind(pos=self._update_new_btn, size=self._update_new_btn)
        new_btn_container.add_widget(new_btn)
        self.add_widget(new_btn_container)
        
        # Zone de liste avec scroll
        scrollable = ScrollableWithButtons(size_hint_y=0.7)
        
        self.list_layout = GridLayout(cols=1, spacing=dp(5), size_hint_y=None, padding=dp(5))
        self.list_layout.bind(minimum_height=self.list_layout.setter('height'))
        
        scrollable.set_content(self.list_layout)
        self.add_widget(scrollable)
        
        self.refresh_list()

        back_btn = Button(
            text="RETOUR AUX MODULES",
            size_hint_y=None,
            height=dp(50),
            background_color=[0, 0, 0, 0],
            bold=True
        )
        with back_btn.canvas.before:
            Color(rgba=App.get_running_app().theme_colors['accent'])
            RoundedRectangle(pos=back_btn.pos, size=back_btn.size, radius=[dp(10),])
        back_btn.bind(on_release=self.go_back)
        back_btn.bind(pos=self._update_btn_rect, size=self._update_btn_rect)
        self.add_widget(back_btn)

    def _update_btn_rect(self, instance, value):
        instance.canvas.before.clear()
        with instance.canvas.before:
            Color(rgba=App.get_running_app().theme_colors['accent'])
            RoundedRectangle(pos=instance.pos, size=instance.size, radius=[dp(10),])

    def _update_new_btn(self, instance, value):
        instance.canvas.before.clear()
        with instance.canvas.before:
            Color(rgba=App.get_running_app().theme_colors['accent'])
            RoundedRectangle(pos=instance.pos, size=instance.size, radius=[dp(8),])
            Color(rgba=[0.2, 0.2, 0.3, 0.3])
            RoundedRectangle(pos=instance.pos, size=instance.size, radius=[dp(8),])

    def go_back(self, *args):
        main_screen = App.get_running_app().root.get_screen('main')
        main_screen.show_module_list()

    def refresh_list(self):
        self.list_layout.clear_widgets()
        if not self.notes:
            self.list_layout.add_widget(Label(
                text="Aucune note. Cliquez sur + NOUVELLE NOTE pour commencer.",
                size_hint_y=None,
                height=dp(50),
                color=[0.7,0.7,0.8,1]
            ))
            return
            
        for idx, note in enumerate(self.notes):
            note_box = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(5))
            
            # Fond pour la note
            with note_box.canvas.before:
                Color(rgba=[0.12, 0.12, 0.18, 0.8])
                note_box.rect_bg = RoundedRectangle(pos=note_box.pos, size=note_box.size, radius=[dp(5),])
            
            # Mise a jour du fond
            def update_note_bg(instance, _):
                instance.canvas.before.clear()
                with instance.canvas.before:
                    Color(rgba=[0.12, 0.12, 0.18, 0.8])
                    RoundedRectangle(pos=instance.pos, size=instance.size, radius=[dp(5),])
            
            note_box.bind(pos=update_note_bg, size=update_note_bg)
            
            title_btn = Button(
                text=f"{note['titre']} ({note['date']})", 
                background_color=[0,0,0,0],
                color=[1,1,1,1],
                halign='left',
                padding=[dp(10), 0]
            )
            title_btn.bind(on_release=lambda x, i=idx: self.open_note(i))
            
            del_btn = Button(
                text="X", 
                size_hint_x=0.12, 
                background_color=[0.8,0.2,0.2,1], 
                color=[1,1,1,1],
                bold=True
            )
            del_btn.bind(on_release=lambda x, i=idx: self.delete_note(i))
            
            note_box.add_widget(title_btn)
            note_box.add_widget(del_btn)
            self.list_layout.add_widget(note_box)

    def new_note(self, *args):
        self.current_note_index = None
        self.show_editor(titre="", contenu="")

    def open_note(self, idx):
        self.current_note_index = idx
        note = self.notes[idx]
        self.show_editor(titre=note['titre'], contenu=note['contenu'])

    def show_editor(self, titre="", contenu=""):
        self.clear_widgets()
        
        # Titre
        title = Label(
            text="EDITEUR DE NOTE",
            font_size='18sp',
            bold=True,
            color=App.get_running_app().theme_colors['accent'],
            size_hint_y=None,
            height=dp(40)
        )
        self.add_widget(title)
        
        self.title_input = TextInput(
            text=titre, 
            hint_text="Titre de la note", 
            size_hint_y=None, 
            height=dp(50), 
            background_color=[0.2,0.2,0.3,1], 
            foreground_color=[1,1,1,1],
            padding=[dp(10), dp(15)]
        )
        self.add_widget(self.title_input)
        
        # Zone de contenu avec scroll
        scrollable = ScrollableWithButtons(size_hint_y=0.6)
        
        self.content_input = TextInput(
            text=contenu, 
            hint_text="Contenu de la note...", 
            background_color=[0.15,0.15,0.25,1], 
            foreground_color=[1,1,1,1], 
            multiline=True,
            padding=[dp(10), dp(10)]
        )
        scrollable.set_content(self.content_input)
        self.add_widget(scrollable)
        
        btn_bar = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(10))
        save_btn = Button(text="SAUVEGARDER", background_color=[0,0,0,0])
        with save_btn.canvas.before:
            Color(rgba=App.get_running_app().theme_colors['accent'])
            RoundedRectangle(pos=save_btn.pos, size=save_btn.size, radius=[dp(8),])
        save_btn.bind(on_release=self.save_note)
        
        cancel_btn = Button(text="ANNULER", background_color=[0,0,0,0])
        with cancel_btn.canvas.before:
            Color(rgba=App.get_running_app().theme_colors['accent'])
            RoundedRectangle(pos=cancel_btn.pos, size=cancel_btn.size, radius=[dp(8),])
        cancel_btn.bind(on_release=lambda x: self.build_ui())
        btn_bar.add_widget(save_btn)
        btn_bar.add_widget(cancel_btn)
        self.add_widget(btn_bar)

        back_btn = Button(
            text="RETOUR AUX NOTES",
            size_hint_y=None,
            height=dp(50),
            background_color=[0, 0, 0, 0],
            bold=True
        )
        with back_btn.canvas.before:
            Color(rgba=App.get_running_app().theme_colors['accent'])
            RoundedRectangle(pos=back_btn.pos, size=back_btn.size, radius=[dp(10),])
        back_btn.bind(on_release=lambda x: self.build_ui())
        back_btn.bind(pos=self._update_btn_rect, size=self._update_btn_rect)
        self.add_widget(back_btn)

    def save_note(self, *args):
        titre = self.title_input.text.strip()
        if not titre:
            titre = "Sans titre"
        contenu = self.content_input.text
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        note = {'titre': titre, 'contenu': contenu, 'date': now}
        if self.current_note_index is None:
            self.notes.append(note)
        else:
            self.notes[self.current_note_index] = note
        self.save_notes()
        self.build_ui()

    def delete_note(self, idx):
        del self.notes[idx]
        self.save_notes()
        self.refresh_list()

    def load_notes(self):
        try:
            with open(self.notes_file, 'r', encoding='utf-8') as f:
                self.notes = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.notes = []

    def save_notes(self):
        try:
            with open(self.notes_file, 'w', encoding='utf-8') as f:
                json.dump(self.notes, f, indent=2, ensure_ascii=False)
        except Exception as e:
            Logger.error(f"Erreur sauvegarde notes: {e}")

# -------------------------------------------------------------------
# Module IA (amélioré avec bulles de discussion)
# -------------------------------------------------------------------
class AIApp(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation='vertical', spacing=dp(15), padding=dp(15), **kwargs)
        self.history = []  # liste de tuples (expéditeur, message)
        self.build_ui()
        self.api_url = STACKAI_API_URL
        self.api_key = STACKAI_API_KEY

    def build_ui(self):
        # Titre
        title = Label(
            text="ASSISTANT IA",
            font_size='18sp',
            bold=True,
            color=App.get_running_app().theme_colors['accent'],
            size_hint_y=None,
            height=dp(40)
        )
        self.add_widget(title)

        # Zone de discussion avec scroll
        scrollable = ScrollableWithButtons(size_hint_y=0.7)
        self.chat_container = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(10), padding=[dp(10), dp(10)])
        self.chat_container.bind(minimum_height=self.chat_container.setter('height'))
        scrollable.set_content(self.chat_container)
        self.add_widget(scrollable)

        # Zone de saisie
        self.input_field = TextInput(
            hint_text="Votre message...",
            multiline=True,
            size_hint_y=0.15,
            background_color=[0.15, 0.15, 0.25, 1],
            foreground_color=[1, 1, 1, 1],
            cursor_color=App.get_running_app().theme_colors['accent'],
            padding=[dp(15), dp(15)]
        )
        self.add_widget(self.input_field)

        # Bouton d'envoi
        send_btn = Button(
            text="ENVOYER",
            size_hint_y=None,
            height=dp(45),
            background_color=[0, 0, 0, 0],
            bold=True
        )
        with send_btn.canvas.before:
            Color(rgba=App.get_running_app().theme_colors['accent'])
            RoundedRectangle(pos=send_btn.pos, size=send_btn.size, radius=[dp(8),])
        send_btn.bind(on_release=self.send_message)
        send_btn.bind(pos=self._update_btn_rect, size=self._update_btn_rect)
        self.add_widget(send_btn)

        self.loading = Label(
            text="Envoi en cours...",
            color=App.get_running_app().theme_colors['accent'],
            size_hint_y=None,
            height=dp(30),
            opacity=0
        )
        self.add_widget(self.loading)

        # Bouton retour
        back_btn = Button(
            text="RETOUR AUX MODULES",
            size_hint_y=None,
            height=dp(50),
            background_color=[0, 0, 0, 0],
            bold=True
        )
        with back_btn.canvas.before:
            Color(rgba=App.get_running_app().theme_colors['accent'])
            RoundedRectangle(pos=back_btn.pos, size=back_btn.size, radius=[dp(10),])
        back_btn.bind(on_release=self.go_back)
        back_btn.bind(pos=self._update_btn_rect, size=self._update_btn_rect)
        self.add_widget(back_btn)

    def _update_btn_rect(self, instance, value):
        instance.canvas.before.clear()
        with instance.canvas.before:
            Color(rgba=App.get_running_app().theme_colors['accent'])
            RoundedRectangle(pos=instance.pos, size=instance.size, radius=[dp(10),])

    def go_back(self, *args):
        main_screen = App.get_running_app().root.get_screen('main')
        main_screen.show_module_list()

    def send_message(self, *args):
        message = self.input_field.text.strip()
        if not message:
            return

        # Ajouter le message de l'utilisateur
        self.add_message("user", message)
        self.input_field.text = ""

        # Ajouter un message temporaire de l'IA
        self.add_message("ia", "...")
        self.loading.opacity = 1

        # Lancer la requête API dans un thread
        Thread(target=self._call_api, args=(message,)).start()

    def add_message(self, sender, text):
        """Ajoute une bulle de message dans le chat"""
        # Créer un conteneur pour aligner la bulle
        msg_box = BoxLayout(size_hint_y=None, height=dp(60))  # Hauteur ajustée automatiquement
        msg_box.bind(minimum_height=msg_box.setter('height'))

        # Bulle de message
        bubble = Label(
            text=text,
            size_hint=(None, None),
            width=dp(300),
            text_size=(dp(280), None),
            padding=[dp(15), dp(10)],
            color=[1,1,1,1],
            halign='left',
            valign='top',
            markup=True
        )
        bubble.bind(texture_size=lambda instance, size: setattr(instance, 'height', size[1] + dp(20)))

        # Définir la couleur de fond selon l'expéditeur
        if sender == "user":
            bubble_color = [0.2, 0.4, 0.8, 1]  # Bleu pour l'utilisateur
            bubble.halign = 'right'
            msg_box.add_widget(Widget())  # Espaceur à gauche
        else:
            bubble_color = [0.3, 0.3, 0.3, 1]  # Gris pour l'IA
            bubble.halign = 'left'

        # Ajouter un fond arrondi à la bulle
        with bubble.canvas.before:
            Color(rgba=bubble_color)
            RoundedRectangle(pos=bubble.pos, size=bubble.size, radius=[dp(15),])

        bubble.bind(pos=self._update_bubble_bg, size=self._update_bubble_bg)

        if sender == "user":
            msg_box.add_widget(bubble)
            msg_box.add_widget(Widget(size_hint_x=0.1))  # Marge droite
        else:
            msg_box.add_widget(Widget(size_hint_x=0.1))  # Marge gauche
            msg_box.add_widget(bubble)

        self.chat_container.add_widget(msg_box)
        # Défiler vers le bas
        Clock.schedule_once(lambda dt: setattr(self.parent.parent.parent.scroll_view, 'scroll_y', 0) if hasattr(self.parent.parent.parent, 'scroll_view') else None, 0.1)

    def _update_bubble_bg(self, instance, value):
        instance.canvas.before.clear()
        with instance.canvas.before:
            if hasattr(instance, 'bubble_color'):
                Color(rgba=instance.bubble_color)
            else:
                Color(rgba=[0.3,0.3,0.3,1])
            RoundedRectangle(pos=instance.pos, size=instance.size, radius=[dp(15),])

    def _clean_response(self, text):
        if not isinstance(text, str):
            text = str(text)
        try:
            text = bytes(text, "utf-8").decode("unicode_escape")
        except:
            pass
        text = re.sub(r'\n\s*\n', '\n\n', text)
        text = text.strip()
        text = re.sub(r'\[.*?\]', '', text)
        text = re.sub(r'<<.*?>>', '', text)
        return text

    def _call_api(self, message):
        try:
            payload = {
                "user_id": "",
                "in-0": message
            }
            headers = {
                'Authorization': self.api_key,
                'Content-Type': 'application/json'
            }

            response = requests.post(self.api_url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()

            data = response.json()
            possible_keys = ['out-0', 'response', 'output', 'text', 'message', 'answer', 'generated_text']
            result = None
            for key in possible_keys:
                if isinstance(data, dict) and key in data:
                    result = data[key]
                    break
            if result is None:
                if isinstance(data, dict) and 'choices' in data and len(data['choices']) > 0:
                    choice = data['choices'][0]
                    if isinstance(choice, dict):
                        if 'message' in choice and 'content' in choice['message']:
                            result = choice['message']['content']
                        elif 'text' in choice:
                            result = choice['text']
                elif isinstance(data, dict) and 'generated_text' in data:
                    result = data['generated_text']
                elif isinstance(data, str):
                    result = data
                else:
                    if isinstance(data, dict) and len(data) == 1:
                        result = list(data.values())[0]
                    else:
                        result = json.dumps(data, indent=2, ensure_ascii=False)
            result = self._clean_response(result)
        except Exception as e:
            result = f"Erreur : {str(e)}"

        # Mettre à jour le dernier message de l'IA (celui avec "...")
        for child in reversed(self.chat_container.children):
            if isinstance(child, BoxLayout) and len(child.children) >= 2:
                bubble = child.children[0] if child.children[0] != child.children[-1] else child.children[1]
                if isinstance(bubble, Label) and bubble.text == "...":
                    bubble.text = result
                    # Recalculer la hauteur
                    bubble.texture_update()
                    bubble.height = bubble.texture_size[1] + dp(20)
                    break

        self.loading.opacity = 0

# -------------------------------------------------------------------
# Module Systeme (Documentation) - accents supprimés
# -------------------------------------------------------------------
class SystemApp(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation='vertical', spacing=dp(15), padding=dp(20), **kwargs)
        self.build_ui()

    def build_ui(self):
        self.clear_widgets()

        # Titre
        title = Label(
            text="DOCUMENTATION SYSTEME",
            font_size='20sp',
            bold=True,
            color=App.get_running_app().theme_colors['accent'],
            size_hint_y=None,
            height=dp(50),
            halign='center'
        )
        self.add_widget(title)

        # Zone de contenu avec scroll
        scrollable = ScrollableWithButtons(size_hint_y=0.9)

        content = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(15), padding=dp(10))
        content.bind(minimum_height=content.setter('height'))

        # Section Mot de passe
        pass_section = self._create_section(
            "MOT DE PASSE D'ACCES",
            [
                "Le mot de passe pour acceder a l'application est :",
                "",
                "   APL-I-E123",
                "",
                "Ce mot de passe est sensible a la casse (majuscules/minuscules).",
                "L'application ne s'ouvre qu'avec ce mot de passe exact."
            ]
        )
        content.add_widget(pass_section)

        # Section Navigation
        nav_section = self._create_section(
            "NAVIGATION",
            [
                "• Barre laterale gauche : Accueil, Alertes, Profil, Parametres",
                "• Bouton modules (icone boite) : ouvre le panneau des modules",
                "• Bouton theme (icone cercle) : change la couleur d'accentuation",
                "• Bouton OFF : retour a l'ecran de connexion"
            ]
        )
        content.add_widget(nav_section)

        # Section Dossiers
        docs_section = self._create_section(
            "GESTION DES DOSSIERS",
            [
                "Les dossiers sont organises en 3 onglets :",
                "   • Lu : dossiers deja traites",
                "   • Non-lu : dossiers en attente de traitement",
                "   • Marque : dossiers rejetes",
                "",
                "Chaque dossier affiche :",
                "   • Numero d'identification (#ID)",
                "   • Statut de validation : OK EEE (reussite) / NO OK (echec)",
                "   • Switch pour ouvrir les details",
                "   • Point de couleur : vert (lu), rouge (non lu), orange (marque)"
            ]
        )
        content.add_widget(docs_section)

        # Section Traitement
        process_section = self._create_section(
            "TRAITEMENT DES DOSSIERS",
            [
                "1. Cliquez sur le switch d'un dossier pour ouvrir ses details",
                "2. Cliquez sur 'TRAITER LE DOSSIER' pour lancer la verification",
                "3. Une barre de progression montre l'avancement de l'analyse",
                "4. Resultats possibles :",
                "   • VALIDATION REUSSIE : toutes les verifications sont ok",
                "   • VALIDATION NON ACCEPTEE : erreurs detectees",
                "5. Actions apres validation :",
                "   • TELECHARGER : sauvegarder le document en local",
                "   • MARQUER LU : deplacer le dossier vers l'onglet Lu",
                "   • REJETER : deplacer le dossier vers l'onglet Marque"
            ]
        )
        content.add_widget(process_section)

        # Section Verification
        verify_section = self._create_section(
            "VERIFICATION AUTOMATIQUE",
            [
                "L'application verifie automatiquement :",
                "   • Presence de ratures ou modifications suspectes",
                "   • Mots suspects dans le document",
                "   • Age du document (doit etre emis il y a plus de 2 ans)",
                "   • Correspondance nom/date/lieu avec la base de donnees",
                "   • Concordance entre le texte et le QR code"
            ]
        )
        content.add_widget(verify_section)

        # Section Modules
        modules_section = self._create_section(
            "MODULES DISPONIBLES",
            [
                "• Convertisseur : terminal SIGMA avec commandes Linux",
                "• Note : prise de notes avec sauvegarde locale",
                "• IA : assistant conversationnel (via API StackAI)",
                "• Systeme : documentation de l'application (ce module)",
                "• Commande vocale : controle du PC a la voix"
            ]
        )
        content.add_widget(modules_section)

        # Section Notes
        notes_section = self._create_section(
            "MODULE NOTES",
            [
                "• Bouton '+ NOUVELLE NOTE' pour creer une note",
                "• Les notes sont sauvegardees automatiquement",
                "• Cliquez sur une note pour la modifier",
                "• Bouton 'X' pour supprimer une note"
            ]
        )
        content.add_widget(notes_section)

        # Section IA
        ia_section = self._create_section(
            "MODULE IA",
            [
                "• Zone de saisie agrandie pour vos messages",
                "• Historique des conversations conserve",
                "• Reponses generees par l'API StackAI"
            ]
        )
        content.add_widget(ia_section)

        # Section Terminal SIGMA
        sigma_section = self._create_section(
            "TERMINAL SIGMA",
            [
                "• Lancez des commandes Linux directement",
                "• Commandes simplifiees : google, office, matrix, sigma, clear",
                "• Animation de pluie binaire au demarrage",
                "• Execute toute commande systeme (ls, ping, etc.)"
            ]
        )
        content.add_widget(sigma_section)

        # Section Commande vocale
        voice_section = self._create_section(
            "COMMANDE VOCALE",
            [
                "• Cliquez sur 'Demarrer l'ecoute' et parlez en francais",
                "• Commandes possibles :",
                "   - 'ouvre le navigateur'",
                "   - 'ouvre le gestionnaire de fichiers'",
                "   - 'envoie un email a adresse disant message'",
                "   - 'eteins l'ordinateur' (avec confirmation)",
                "• Les actions sensibles demandent confirmation",
                "• Cliquez sur 'Arreter / Quitter' pour desactiver le micro"
            ]
        )
        content.add_widget(voice_section)

        # Section Base de donnees
        db_section = self._create_section(
            "BASE DE DONNEES",
            [
                "• Connexion a PostgreSQL pour les donnees persistantes",
                "• Verification complete : table, donnees, schema",
                "• Timeout de connexion : 20 secondes",
                "• Si la table manque ou est vide, les donnees de secours sont utilisees"
            ]
        )
        content.add_widget(db_section)

        scrollable.set_content(content)
        self.add_widget(scrollable)

        # Bouton retour
        back_btn = Button(
            text="RETOUR AUX MODULES",
            size_hint_y=None,
            height=dp(50),
            background_color=[0, 0, 0, 0],
            bold=True
        )
        with back_btn.canvas.before:
            Color(rgba=App.get_running_app().theme_colors['accent'])
            RoundedRectangle(pos=back_btn.pos, size=back_btn.size, radius=[dp(10),])
        back_btn.bind(on_release=self.go_back)
        self.add_widget(back_btn)

    def _create_section(self, title, lines):
        """Cree une section de documentation"""
        section = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(5))
        section.bind(minimum_height=section.setter('height'))

        # Titre de section
        title_label = Label(
            text=title,
            font_size='16sp',
            bold=True,
            color=App.get_running_app().theme_colors['accent'],
            size_hint_y=None,
            height=dp(35),
            halign='left',
            valign='middle',
            text_size=(self.width - dp(60), None)
        )
        title_label.bind(size=lambda s, w: setattr(s, 'text_size', (s.width, None)))
        section.add_widget(title_label)

        # Lignes de contenu
        for line in lines:
            if line == "":
                # Ligne vide
                spacer = Widget(size_hint_y=None, height=dp(5))
                section.add_widget(spacer)
            else:
                label = Label(
                    text=line,
                    font_size='13sp',
                    color=[0.9, 0.9, 1, 1],
                    size_hint_y=None,
                    height=dp(25),
                    halign='left',
                    valign='middle',
                    text_size=(self.width - dp(60), None)
                )
                label.bind(size=lambda s, w: setattr(s, 'text_size', (s.width, None)))
                section.add_widget(label)

        # Ligne de separation
        sep = Widget(size_hint_y=None, height=dp(1))
        with sep.canvas:
            Color(rgba=App.get_running_app().theme_colors['accent'][:3] + [0.3])
            Rectangle(pos=sep.pos, size=sep.size)
        sep.bind(pos=self._update_sep, size=self._update_sep)
        section.add_widget(sep)

        # Espacement
        section.add_widget(Widget(size_hint_y=None, height=dp(10)))

        return section

    def _update_sep(self, instance, value):
        instance.canvas.clear()
        with instance.canvas:
            Color(rgba=App.get_running_app().theme_colors['accent'][:3] + [0.3])
            Rectangle(pos=instance.pos, size=instance.size)

    def go_back(self, *args):
        main_screen = App.get_running_app().root.get_screen('main')
        main_screen.show_module_list()

# -------------------------------------------------------------------
# MODULE COMMANDE VOCALE (avec indicateur sonore sous forme de ligne)
# -------------------------------------------------------------------
class VoiceCommandApp(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation='vertical', spacing=dp(15), padding=dp(20), **kwargs)
        self.listening = False
        self.recognizer = None
        self.microphone = None
        self.tts_engine = None
        self.stream = None
        self.audio_interface = None
        if VOICE_AVAILABLE:
            try:
                self.recognizer = sr.Recognizer()
                self.microphone = sr.Microphone()
                self.tts_engine = pyttsx3.init()
                self.tts_engine.setProperty('rate', 150)
                self.tts_engine.setProperty('volume', 0.9)
                self.audio_interface = pyaudio.PyAudio()
            except Exception as e:
                Logger.error(f"Erreur initialisation voix: {e}")
        self.build_ui()

    def build_ui(self):
        # Titre
        title = Label(
            text="COMMANDE VOCALE",
            font_size='18sp', bold=True,
            color=App.get_running_app().theme_colors['accent'],
            size_hint_y=None, height=dp(40)
        )
        self.add_widget(title)

        # Bouton démarrer écoute
        self.start_btn = Button(
            text="DEMARRER L'ECOUTE",
            size_hint_y=None, height=dp(60),
            background_color=[0,0,0,0], bold=True
        )
        with self.start_btn.canvas.before:
            Color(rgba=App.get_running_app().theme_colors['accent'])
            RoundedRectangle(pos=self.start_btn.pos, size=self.start_btn.size, radius=[dp(10),])
        self.start_btn.bind(on_release=self.start_listening)
        self.start_btn.bind(pos=self._update_btn_rect, size=self._update_btn_rect)
        self.add_widget(self.start_btn)

        # Bouton arrêter/quitter
        self.stop_btn = Button(
            text="ARRETER / QUITTER",
            size_hint_y=None, height=dp(60),
            background_color=[0,0,0,0], bold=True
        )
        with self.stop_btn.canvas.before:
            Color(rgba=[0.9, 0.3, 0.3, 1])  # Rouge
            RoundedRectangle(pos=self.stop_btn.pos, size=self.stop_btn.size, radius=[dp(10),])
        self.stop_btn.bind(on_release=self.stop_listening)
        self.stop_btn.bind(pos=self._update_stop_btn, size=self._update_stop_btn)
        self.add_widget(self.stop_btn)

        # Indicateur sonore sous forme de ligne horizontale
        self.sound_indicator = ProgressBar(
            max=100,
            value=0,
            size_hint_y=None,
            height=dp(10)
        )
        self.add_widget(self.sound_indicator)

        # Zone de logs / notifications
        scrollable = ScrollableWithButtons(size_hint_y=0.4)
        self.log_label = Label(
            text="Pret. Cliquez sur 'Demarrer' et parlez.",
            size_hint_y=None,
            color=[0.9,0.9,1,1],
            valign='top', halign='left',
            text_size=(scrollable.width - dp(20), None),
            padding=[dp(10), dp(10)]
        )
        self.log_label.bind(
            texture_size=lambda instance, size: setattr(instance, 'height', size[1]),
            width=lambda *args: setattr(self.log_label, 'text_size', (self.log_label.width, None))
        )
        log_container = BoxLayout(orientation='vertical', size_hint_y=None)
        log_container.bind(minimum_height=log_container.setter('height'))
        log_container.add_widget(self.log_label)
        scrollable.set_content(log_container)
        self.add_widget(scrollable)

        # Bouton retour aux modules
        back_btn = Button(
            text="RETOUR AUX MODULES",
            size_hint_y=None, height=dp(50),
            background_color=[0,0,0,0], bold=True
        )
        with back_btn.canvas.before:
            Color(rgba=App.get_running_app().theme_colors['accent'])
            RoundedRectangle(pos=back_btn.pos, size=back_btn.size, radius=[dp(10),])
        back_btn.bind(on_release=self.go_back)
        back_btn.bind(pos=self._update_btn_rect, size=self._update_btn_rect)
        self.add_widget(back_btn)

    def _update_btn_rect(self, instance, value):
        instance.canvas.before.clear()
        with instance.canvas.before:
            Color(rgba=App.get_running_app().theme_colors['accent'])
            RoundedRectangle(pos=instance.pos, size=instance.size, radius=[dp(10),])

    def _update_stop_btn(self, instance, value):
        instance.canvas.before.clear()
        with instance.canvas.before:
            Color(rgba=[0.9, 0.3, 0.3, 1])
            RoundedRectangle(pos=instance.pos, size=instance.size, radius=[dp(10),])

    def go_back(self, *args):
        self.stop_listening()
        main_screen = App.get_running_app().root.get_screen('main')
        main_screen.show_module_list()

    def log(self, message, color=None):
        """Ajoute un message dans la zone de logs"""
        if color is None:
            color = [0.9,0.9,1,1]
        # On garde un historique simple
        current = self.log_label.text
        # Limiter la taille pour éviter le dépassement
        lines = current.split('\n')
        if len(lines) > 100:
            lines = lines[-100:]
            current = '\n'.join(lines)
        self.log_label.text = current + '\n' + message
        # Auto-scroll vers le bas
        def scroll():
            if hasattr(self.parent, 'parent') and hasattr(self.parent.parent, 'scroll_view'):
                self.parent.parent.scroll_view.scroll_y = 0
        Clock.schedule_once(lambda dt: scroll(), 0.1)

    def speak(self, text):
        """Synthèse vocale si disponible"""
        if self.tts_engine:
            try:
                self.tts_engine.say(text)
                self.tts_engine.runAndWait()
            except:
                pass
        self.log(f"[Notification] {text}", color=[0.3,0.8,0.3,1])

    def start_listening(self, *args):
        if not VOICE_AVAILABLE or not self.recognizer:
            self.log("Module vocal non disponible (bibliotheques manquantes).", color=[0.9,0.3,0.3,1])
            return
        if self.listening:
            return
        self.listening = True
        self.start_btn.disabled = True
        self.log("Ecoute en cours... Parlez maintenant.")
        # Lancer le monitoring sonore
        Thread(target=self.monitor_sound, daemon=True).start()
        # Lancer l'écoute de la commande
        Thread(target=self.listen_once).start()

    def stop_listening(self, *args):
        self.listening = False
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None
        if self.audio_interface:
            self.audio_interface.terminate()
            self.audio_interface = None
        self.start_btn.disabled = False
        self.log("Micro desactive.")
        # Remettre l'indicateur à zéro
        Clock.schedule_once(lambda dt: setattr(self.sound_indicator, 'value', 0))

    def monitor_sound(self):
        """Mesure l'amplitude sonore en continu et met à jour la barre"""
        if not self.audio_interface:
            return
        CHUNK = 1024
        FORMAT = pyaudio.paInt16
        CHANNELS = 1
        RATE = 44100

        self.stream = self.audio_interface.open(format=FORMAT,
                                                channels=CHANNELS,
                                                rate=RATE,
                                                input=True,
                                                frames_per_buffer=CHUNK)

        while self.listening and self.stream:
            try:
                data = self.stream.read(CHUNK, exception_on_overflow=False)
                # Convertir les données en entiers
                count = len(data) // 2
                format = "<{}h".format(count)
                shorts = struct.unpack(format, data)
                # Calculer l'amplitude moyenne
                amplitude = np.sqrt(np.mean(np.square(shorts)))
                # Normaliser pour l'affichage (valeur entre 0 et 100)
                intensity = min(100, amplitude / 50)  # Ajuster le seuil
                # Mettre à jour la barre sur le thread principal
                Clock.schedule_once(lambda dt, i=intensity: setattr(self.sound_indicator, 'value', i))
            except Exception as e:
                break

    def listen_once(self):
        """Écoute une seule commande et la traite"""
        try:
            with self.microphone as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=5)
        except sr.WaitTimeoutError:
            Clock.schedule_once(lambda dt: self.log("Aucune commande detectee (delai expire)."))
            self.stop_listening()
            return
        except Exception as e:
            Clock.schedule_once(lambda dt: self.log(f"Erreur micro : {str(e)}"))
            self.stop_listening()
            return

        try:
            # Reconnaissance en français
            command = self.recognizer.recognize_google(audio, language="fr-FR")
            Clock.schedule_once(lambda dt: self.log(f"Commande reconnue : {command}"))
            Clock.schedule_once(lambda dt: self.process_command(command))
        except sr.UnknownValueError:
            Clock.schedule_once(lambda dt: self.log("Desole, je n'ai pas compris."))
            self.stop_listening()
        except sr.RequestError as e:
            Clock.schedule_once(lambda dt: self.log(f"Erreur de service de reconnaissance : {e}"))
            self.stop_listening()

    def process_command(self, command):
        """Analyse la commande et exécute l'action correspondante"""
        cmd_lower = command.lower()

        # Dictionnaire de mots-clés et actions
        if "ouvre le navigateur" in cmd_lower or "lance le navigateur" in cmd_lower or "ouvre firefox" in cmd_lower:
            self.execute_action("open_browser")
        elif "ouvre le gestionnaire de fichiers" in cmd_lower or "ouvre l'explorateur" in cmd_lower or "ouvre les fichiers" in cmd_lower:
            self.execute_action("open_file_manager")
        elif "envoie un email" in cmd_lower or "envoie un mail" in cmd_lower:
            self.handle_email_command(cmd_lower)
        elif "eteins l'ordinateur" in cmd_lower or "arrete le pc" in cmd_lower:
            self.require_confirmation("shutdown", "Voulez-vous vraiment eteindre l'ordinateur ?")
        elif "redemarre" in cmd_lower or "restart" in cmd_lower:
            self.require_confirmation("restart", "Voulez-vous vraiment redemarrer ?")
        elif "efface" in cmd_lower or "supprime" in cmd_lower:
            self.log("Action non autorisee sans confirmation explicite.", color=[0.9,0.3,0.3,1])
            self.speak("Desole, je ne peux pas effacer de fichiers sans confirmation.")
        else:
            self.log("Commande non reconnue. Essayez : 'ouvre le navigateur', 'envoie un email', etc.")
            self.speak("Commande non reconnue.")

        self.stop_listening()  # Après traitement, on arrête l'écoute

    def execute_action(self, action):
        """Exécute une action simple"""
        if action == "open_browser":
            try:
                webbrowser.open("https://www.google.com")
                self.speak("Navigateur ouvert.")
            except Exception as e:
                self.log(f"Erreur ouverture navigateur : {e}")
        elif action == "open_file_manager":
            try:
                # Selon l'OS
                import platform
                system = platform.system()
                if system == "Windows":
                    subprocess.Popen("explorer")
                elif system == "Linux":
                    subprocess.Popen(["nautilus"])  # ou thunar, dolphin...
                elif system == "Darwin":
                    subprocess.Popen(["open", "."])
                self.speak("Gestionnaire de fichiers ouvert.")
            except Exception as e:
                self.log(f"Erreur ouverture gestionnaire : {e}")
        else:
            self.log("Action inconnue.")

    def handle_email_command(self, cmd):
        """Gère l'envoi d'email : extrait destinataire et message"""
        import re
        match = re.search(r"à (.+?) disant (.+)", cmd)
        if match:
            to_addr = match.group(1).strip()
            message = match.group(2).strip()
            self.send_email(to_addr, message)
        else:
            self.log("Format attendu : 'envoie un email a adresse disant message'")
            self.speak("Veuillez preciser le destinataire et le message.")

    def send_email(self, to_addr, message):
        """Envoie un email via SMTP (à configurer avec vos identifiants)"""
        # À remplacer par vos informations SMTP
        smtp_server = "smtp.gmail.com"
        port = 587
        sender_email = "votre.email@gmail.com"
        password = "votre_mot_de_passe"  # Utilisez un mot de passe d'application

        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = to_addr
        msg['Subject'] = "Commande vocale"
        msg.attach(MIMEText(message, 'plain'))

        try:
            server = smtplib.SMTP(smtp_server, port)
            server.starttls()
            server.login(sender_email, password)
            server.send_message(msg)
            server.quit()
            self.speak("Email envoye.")
            self.log(f"Email envoye a {to_addr}")
        except Exception as e:
            self.log(f"Erreur envoi email : {e}")
            self.speak("Echec de l'envoi de l'email.")

    def require_confirmation(self, action, question):
        """Affiche une popup de confirmation pour les actions sensibles"""
        content = BoxLayout(orientation='vertical', spacing=dp(10), padding=dp(20))
        content.add_widget(Label(text=question, color=[1,1,1,1]))
        btn_box = BoxLayout(spacing=dp(10), size_hint_y=None, height=dp(50))
        confirm_btn = Button(text="OUI", background_color=[0,0,0,0])
        with confirm_btn.canvas.before:
            Color(rgba=[0.3,0.8,0.3,1])
            RoundedRectangle(pos=confirm_btn.pos, size=confirm_btn.size, radius=[dp(8),])
        cancel_btn = Button(text="NON", background_color=[0,0,0,0])
        with cancel_btn.canvas.before:
            Color(rgba=[0.9,0.3,0.3,1])
            RoundedRectangle(pos=cancel_btn.pos, size=cancel_btn.size, radius=[dp(8),])
        btn_box.add_widget(confirm_btn)
        btn_box.add_widget(cancel_btn)
        content.add_widget(btn_box)

        popup = Popup(title='Confirmation', content=content, size_hint=(0.5,0.3), background='', separator_color=[0,0,0,0])
        with popup.canvas.before:
            Color(rgba=[0.02,0.02,0.05,0.98])
            RoundedRectangle(pos=popup.pos, size=popup.size, radius=[dp(10),])

        def on_confirm(inst):
            popup.dismiss()
            if action == "shutdown":
                import platform
                system = platform.system()
                if system == "Windows":
                    subprocess.Popen(["shutdown", "/s", "/t", "0"])
                elif system == "Linux":
                    subprocess.Popen(["shutdown", "-h", "now"])
                elif system == "Darwin":
                    subprocess.Popen(["shutdown", "-h", "now"])
            elif action == "restart":
                import platform
                system = platform.system()
                if system == "Windows":
                    subprocess.Popen(["shutdown", "/r", "/t", "0"])
                elif system == "Linux":
                    subprocess.Popen(["shutdown", "-r", "now"])
                elif system == "Darwin":
                    subprocess.Popen(["shutdown", "-r", "now"])
            self.speak("Action confirmee.")

        def on_cancel(inst):
            popup.dismiss()
            self.log("Action annulee.")

        confirm_btn.bind(on_release=on_confirm)
        cancel_btn.bind(on_release=on_cancel)
        popup.open()

# -------------------------------------------------------------------
# MainScreen (ecran principal)
# -------------------------------------------------------------------
class MainScreen(Screen):
    current_time = StringProperty("00:00:00")
    current_tab = StringProperty("home_lu")
    modules_visible = False
    themes_open = False
    current_filter = StringProperty("lu")
    db_ready = BooleanProperty(False)

    def __init__(self, **kwargs):
        super(MainScreen, self).__init__(**kwargs)
        Clock.schedule_interval(self.update_time, 1)
        Clock.schedule_once(self.init_ui)

    def init_ui(self, dt):
        try:
            self.add_nav_button("bboite.png", self.toggle_modules)
            self.add_nav_button("off.png", self.go_to_auth)
            self.setup_themes()
            self.setup_sidebar()
            self.ids.main_pages.current = 'home'

            # Verifier la connexion a la base de donnees
            self.check_database_connection()

        except Exception as e:
            Logger.error(f"Erreur dans init_ui: {e}")
            traceback.print_exc()

    def check_database_connection(self):
        """Verifie la connexion a la base de donnees et affiche le resultat"""
        app = App.get_running_app()
        conn_manager = ConnectionManager()

        # Afficher un popup de connexion
        conn_manager.show_connecting_popup("Connexion a la base de donnees...")

        def check():
            # Attendre la connexion
            if hasattr(app.db, 'wait_for_connection'):
                connected = app.db.wait_for_connection()
                status_message = app.db.get_status_message() if hasattr(app.db, 'get_status_message') else ""
                details = app.db.get_status_details() if hasattr(app.db, 'get_status_details') else ""

                if connected:
                    Clock.schedule_once(lambda dt: conn_manager.show_connection_result(
                        True, "", status_message, details
                    ))
                    self.db_ready = True
                else:
                    Clock.schedule_once(lambda dt: conn_manager.show_connection_result(
                        False, "", status_message, details
                    ))
                    self.db_ready = False
            else:
                # Mode simulation (MockDatabase)
                status_message = app.db.get_status_message() if hasattr(app.db, 'get_status_message') else "Base de donnees simulation - Connexion"
                details = app.db.get_status_details() if hasattr(app.db, 'get_status_details') else "Donnees simulees locales"
                Clock.schedule_once(lambda dt: conn_manager.show_connection_result(
                    True, "", status_message, details
                ))
                self.db_ready = True

            # Charger les donnees apres la connexion
            Clock.schedule_once(lambda dt: self.switch_tab('home', 'lu'), 0.5)

        Thread(target=check).start()

    def refresh_current_tab(self):
        """Rafraichit l'onglet courant"""
        print(f"Rafraichissement de l'onglet: {self.current_filter}")
        self.switch_tab('home', self.current_filter)

    def force_refresh_current_tab(self):
        """Force le rafraichissement complet de l'onglet courant"""
        print(f"RAFRAICHISSEMENT FORCE de l'onglet: {self.current_filter}")

        # Forcer le rechargement en vidant d'abord le contenu
        content_box = self.ids.home_content
        content_box.clear_widgets()

        # Reconstruire l'onglet
        self.switch_tab('home', self.current_filter)

        # Afficher une notification
        self.show_refresh_message()

    def show_refresh_message(self):
        """Affiche un message temporaire de rafraichissement"""
        # Creer un petit popup de notification
        content = BoxLayout(orientation='vertical', padding=dp(10))
        content.add_widget(Label(
            text="Onglet actualise",
            color=[0.3,0.8,0.3,1],
            font_size='14sp'
        ))

        popup = Popup(
            title='',
            content=content,
            size_hint=(0.3, 0.15),
            background='',
            separator_color=[0,0,0,0],
            auto_dismiss=True
        )

        # Fond sombre
        with popup.canvas.before:
            Color(rgba=[0.02, 0.02, 0.05, 0.95])
            RoundedRectangle(pos=popup.pos, size=popup.size, radius=[dp(10),])

        popup.open()
        Clock.schedule_once(lambda dt: popup.dismiss(), 1)

    def add_nav_button(self, icon_path, callback):
        btn = Button(size_hint=(None, None), size=(dp(45), dp(45)), background_color=[0,0,0,0])
        with btn.canvas.before:
            Color(rgba=[1, 1, 1, 0.1])
            RoundedRectangle(pos=btn.pos, size=btn.size, radius=[dp(10),])
        icon = Image(source=resource_path(icon_path), size_hint=(None, None), size=(dp(25), dp(25)))
        btn.add_widget(icon)
        btn.bind(pos=self._update_btn_assets, size=self._update_btn_assets)
        btn.bind(on_release=lambda x: callback())
        self.ids.nav_container.add_widget(btn)

    def _update_btn_assets(self, instance, value):
        for instr in instance.canvas.before.children:
            if isinstance(instr, RoundedRectangle):
                instr.pos = instance.pos
                instr.size = instance.size
        for child in instance.children:
            if isinstance(child, Image):
                child.center = instance.center

    def setup_sidebar(self):
        letter_font = "/usr/share/fonts/truetype/fonts-ukij-uyghur/UKIJEsC.ttf"
        if not os.path.exists(letter_font):
            letter_font = "Roboto"
        items = [
            {"title": "Accueil", "page": "home"},
            {"title": "Alertes", "page": "alerts"},
            {"title": "Profil", "page": "profile"},
            {"title": "Parametres", "page": "settings"}
        ]
        for item in items:
            container = BoxLayout(orientation='vertical', size_hint_y=None, height=dp(60), spacing=dp(2))
            letter_label = Label(text=item["title"][0].upper(), font_size='24sp', font_name=letter_font, color=[1,1,1,1], size_hint_y=0.7, halign='center', valign='middle', text_size=(self.ids.sidebar.width, dp(40)))
            title_label = Label(text=item["title"], font_size='10sp', size_hint_y=0.3, color=[0.8,0.8,0.9,1], halign='center', valign='middle', text_size=(self.ids.sidebar.width, dp(15)))
            title_label.bind(size=lambda s, w: setattr(s, 'text_size', (s.width, None)))
            container.add_widget(letter_label)
            container.add_widget(title_label)
            container.bind(on_touch_down=lambda inst, touch, p=item["page"]: self.on_sidebar_click(inst, touch, p))
            self.ids.sidebar.add_widget(container)

    def on_sidebar_click(self, instance, touch, page):
        if instance.collide_point(*touch.pos):
            self.ids.main_pages.current = page
            if page == 'home':
                self.switch_tab('home', self.current_filter)
            else:
                self.update_page_content(page)

    def update_page_content(self, page):
        if page == 'alerts':
            content = self.ids.alerts_content
            text = "Liste des alertes systemes..."
        elif page == 'profile':
            content = self.ids.profile_content
            text = "Informations du profil..."
        elif page == 'settings':
            content = self.ids.settings_content
            text = "Parametres de l'application..."
        else:
            return
        content.clear_widgets()
        content.add_widget(Label(text=text, color=[1,1,1,1]))

    def setup_themes(self):
        colors = ['#0044cc', '#7b2cbf', '#ff00c8', '#00ffaa']
        for c in colors:
            btn = Button(size_hint=(None, None), size=(dp(30), dp(30)), background_color=[0,0,0,0])
            with btn.canvas.before:
                Color(rgba=get_color_from_hex(c))
                Ellipse(pos=btn.pos, size=btn.size)
            btn.bind(pos=self._update_ellipse, size=self._update_ellipse)
            btn.bind(on_release=lambda x, col=c: App.get_running_app().change_theme(col))
            self.ids.theme_menu.add_widget(btn)

    def _update_ellipse(self, instance, value):
        for instr in instance.canvas.before.children:
            if isinstance(instr, Ellipse):
                instr.pos = instance.pos
                instr.size = instance.size

    def update_time(self, dt):
        self.current_time = datetime.now().strftime("%H:%M:%S")

    def toggle_theme_menu(self):
        self.themes_open = not self.themes_open
        w = dp(160) if self.themes_open else 0
        o = 1 if self.themes_open else 0
        Animation(width=w, opacity=o, duration=0.3).start(self.ids.theme_menu)

    def toggle_modules(self):
        try:
            self.modules_visible = not self.modules_visible
            w = dp(380) if self.modules_visible else 0
            o = 1 if self.modules_visible else 0
            Animation(width=w, opacity=o, duration=0.4, t='out_quad').start(self.ids.section_b)
            if self.modules_visible:
                self.show_module_list()
        except Exception as e:
            Logger.error(f"Erreur dans toggle_modules: {e}")
            traceback.print_exc()

    def show_module_list(self):
        try:
            self.ids.module_content_area.clear_widgets()
            self.ids.module_panel_title.text = "MODULES"
            grid = self.ids.modules_grid
            grid.clear_widgets()
            # Couleurs violet sombre pour les modules (harmonie avec le fond #0a0a12)
            modules = [
                {"name": "Convertisseur", "letter": "C", "glass_color": [0.3, 0.0, 0.4, 0.4]},   # Violet sombre
                {"name": "Note", "letter": "N", "glass_color": [0.35, 0.05, 0.45, 0.4]},
                {"name": "IA", "letter": "A", "glass_color": [0.25, 0.0, 0.35, 0.4]},
                {"name": "Systeme", "letter": "S", "glass_color": [0.4, 0.1, 0.5, 0.4]},
                {"name": "Commande vocale", "letter": "V", "glass_color": [0.2, 0.0, 0.3, 0.4]}
            ]
            btn_size = dp(150)
            accent = App.get_running_app().theme_colors['accent']
            font_3d = "/usr/share/fonts/truetype/fonts-ukij-uyghur/UKIJKa3D-b.ttf"
            if not os.path.exists(font_3d):
                font_3d = "Roboto"
            for m in modules:
                btn = Button(size_hint=(None, None), size=(btn_size, btn_size), background_color=[0,0,0,0])
                with btn.canvas.before:
                    Color(rgba=m['glass_color'])
                    RoundedRectangle(pos=btn.pos, size=btn.size, radius=[dp(15),])
                    Color(rgba=[accent[0], accent[1], accent[2], 0.3])
                    Line(rounded_rectangle=(btn.x, btn.y, btn.width, btn.height, dp(15)), width=2)
                    Color(rgba=[accent[0], accent[1], accent[2], 0.8])
                    Line(rounded_rectangle=(btn.x+1, btn.y+1, btn.width-2, btn.height-2, dp(15)), width=1)
                box = BoxLayout(orientation='vertical', spacing=dp(5), padding=[0, dp(20), 0, dp(10)])
                letter_label = Label(text=m['letter'], font_size='48sp', bold=True, font_name=font_3d, color=[1,1,1,1], size_hint_y=0.7)
                name_label = Label(text=m['name'], font_size='14sp', bold=True, color=[1,1,1,1], size_hint_y=0.3)
                box.add_widget(letter_label)
                box.add_widget(name_label)
                btn.add_widget(box)
                btn.box = box
                def update_btn(instance, _):
                    instance.box.pos = instance.pos
                    instance.box.size = instance.size
                    instance.canvas.before.clear()
                    with instance.canvas.before:
                        Color(rgba=m['glass_color'])
                        RoundedRectangle(pos=instance.pos, size=instance.size, radius=[dp(15),])
                        Color(rgba=[accent[0], accent[1], accent[2], 0.3])
                        Line(rounded_rectangle=(instance.x, instance.y, instance.width, instance.height, dp(15)), width=2)
                        Color(rgba=[accent[0], accent[1], accent[2], 0.8])
                        Line(rounded_rectangle=(instance.x+1, instance.y+1, instance.width-2, instance.height-2, dp(15)), width=1)
                btn.bind(pos=update_btn, size=update_btn)
                btn.bind(on_release=lambda x, name=m['name']: self.open_module_view(name))
                grid.add_widget(btn)
            self.ids.module_content_area.add_widget(self.ids.scroll_modules)
        except Exception as e:
            Logger.error(f"Erreur dans show_module_list: {e}")
            traceback.print_exc()

    def open_module_view(self, module_name):
        try:
            self.ids.module_content_area.clear_widgets()
            self.ids.module_panel_title.text = module_name.upper()
            if module_name == "Note":
                note_app = NoteApp()
                self.ids.module_content_area.add_widget(note_app)
            elif module_name == "Convertisseur":
                converter_app = ConverterApp()
                self.ids.module_content_area.add_widget(converter_app)
            elif module_name == "IA":
                ai_app = AIApp()
                self.ids.module_content_area.add_widget(ai_app)
            elif module_name == "Systeme":
                system_app = SystemApp()
                self.ids.module_content_area.add_widget(system_app)
            elif module_name == "Commande vocale":
                voice_app = VoiceCommandApp()
                self.ids.module_content_area.add_widget(voice_app)
            else:
                view = BoxLayout(orientation='vertical', padding=dp(15), spacing=dp(20))
                info = Label(text=f"Interface {module_name}", halign='center', color=[0.8,0.8,0.9,1])
                back_btn = Button(text="RETOUR", size_hint_y=None, height=dp(45), background_color=[0,0,0,0], bold=True)
                with back_btn.canvas.before:
                    Color(rgba=App.get_running_app().theme_colors['accent'])
                    RoundedRectangle(pos=back_btn.pos, size=back_btn.size, radius=[dp(10),])
                back_btn.bind(on_release=lambda x: self.show_module_list())
                view.add_widget(info)
                view.add_widget(back_btn)
                self.ids.module_content_area.add_widget(view)
        except Exception as e:
            Logger.error(f"Erreur dans open_module_view: {e}")
            traceback.print_exc()

    def switch_tab(self, page, tab):
        if page != 'home':
            return
        self.current_tab = f"{page}_{tab}"
        self.current_filter = tab

        content_box = self.ids.home_content
        content_box.clear_widgets()

        main_layout = BoxLayout(orientation='vertical')

        header = SearchHeader(on_search_callback=self.on_search)
        main_layout.add_widget(header)

        # Ligne de separation lumineuse
        sep_line = Widget(size_hint_y=None, height=dp(3))
        with sep_line.canvas:
            Color(rgba=[0.8, 0.6, 1, 0.8])  # Ligne lumineuse violette
            Line(points=[sep_line.x + dp(20), sep_line.y + dp(1), sep_line.right - dp(20), sep_line.y + dp(1)], width=2)
        main_layout.add_widget(sep_line)

        # Zone de liste avec scroll et boutons en bas
        scrollable = ScrollableWithButtons()

        self.items_grid = GridLayout(
            cols=1,
            spacing=dp(8),
            size_hint_y=None,
            padding=[dp(10), dp(10)]
        )
        self.items_grid.bind(minimum_height=self.items_grid.setter('height'))

        scrollable.set_content(self.items_grid)
        main_layout.add_widget(scrollable)

        content_box.add_widget(main_layout)

        self.load_items(tab)

    def load_items(self, filter_type=None, search_query=None):
        if filter_type is None:
            filter_type = self.current_filter

        app = App.get_running_app()
        db = app.db

        self.items_grid.clear_widgets()
        self.items_grid.add_widget(Label(
            text="Chargement...",
            color=[0.7,0.7,0.8,1],
            size_hint_y=None,
            height=dp(40)
        ))

        if search_query and search_query.strip():
            db.search_items(search_query, filter_type, self.display_items)
        else:
            if filter_type == 'lu':
                db.get_items_by_read_status(True, self.display_items)
            elif filter_type == 'nonlu':
                db.get_items_by_read_status(False, self.display_items)
            elif filter_type == 'marque':
                db.get_flagged_items(self.display_items)
            else:
                self.display_items([])

    def display_items(self, items):
        self.items_grid.clear_widgets()
        if not items:
            self.items_grid.add_widget(Label(
                text="Aucun element",
                color=[0.7,0.7,0.8,1],
                size_hint_y=None,
                height=dp(40)
            ))
            return
        for item in items:
            card = CompactItem(item)
            self.items_grid.add_widget(card)

    def on_search(self, query):
        self.load_items(self.current_filter, query)

    def go_to_auth(self):
        self.manager.current = 'auth'

# -------------------------------------------------------------------
# KV string (definition de l'interface graphique) - accents supprimés
# -------------------------------------------------------------------
KV = """
#:import utils kivy.utils

<Label>:
    font_name: app.get_best_font()

<AuthScreen>:
    canvas.before:
        Color:
            rgba: utils.get_color_from_hex('#0a0a12')
        Rectangle:
            pos: self.pos
            size: self.size

    BoxLayout:
        orientation: 'vertical'
        padding: dp(50)
        spacing: dp(15)

        Widget:
            size_hint_y: 0.1

        Image:
            source: app.resource_path('tour.png')
            size_hint: (None, None)
            size: dp(120), dp(120)
            pos_hint: {'center_x': 0.5}
            allow_stretch: True

        Label:
            text: "CYBERCORE"
            font_size: '38sp'
            bold: True
            color: [1, 1, 1, 1]
            size_hint_y: None
            height: dp(60)

        TextInput:
            id: pass_input
            hint_text: "Code d'acces"
            password: True
            multiline: False
            size_hint: (None, None)
            width: dp(320)
            height: dp(55)
            pos_hint: {'center_x': 0.5}
            background_color: [1, 1, 1, 0.05]
            foreground_color: [1, 1, 1, 1]
            cursor_color: app.theme_colors['accent']
            padding: [dp(15), (self.height - self.line_height)/2]

        Label:
            id: error_label
            text: ""
            color: [0.9, 0.3, 0.3, 1]
            size_hint_y: None
            height: dp(30)
            font_size: '14sp'

        Button:
            text: "IDENTIFICATION"
            size_hint: (None, None)
            width: dp(320)
            height: dp(60)
            pos_hint: {'center_x': 0.5}
            bold: True
            background_color: [0,0,0,0]
            on_release: root.authenticate(pass_input.text)
            canvas.before:
                Color:
                    rgba: app.theme_colors['accent']
                RoundedRectangle:
                    pos: self.pos
                    size: self.size
                    radius: [dp(12),]

        Widget:

<MainScreen>:
    canvas.before:
        Color:
            rgba: utils.get_color_from_hex(app.theme_colors['bg'])
        Rectangle:
            pos: self.pos
            size: self.size

    BoxLayout:
        orientation: 'horizontal'
        padding: dp(25)
        spacing: dp(20)

        BoxLayout:
            id: section_a
            orientation: 'horizontal'
            padding: dp(0)
            spacing: dp(10)
            canvas.before:
                Color:
                    rgba: [0.1, 0.1, 0.2, 0.4]
                RoundedRectangle:
                    pos: self.pos
                    size: self.size
                    radius: [dp(35),]
                Color:
                    rgba: app.theme_colors['accent'][0], app.theme_colors['accent'][1], app.theme_colors['accent'][2], 0.3
                Line:
                    width: 1.1
                    rounded_rectangle: (self.x, self.y, self.width, self.height, dp(35))

            BoxLayout:
                id: sidebar
                orientation: 'vertical'
                size_hint_x: None
                width: dp(90)
                padding: [dp(5), dp(15)]
                spacing: dp(10)
                canvas.before:
                    Color:
                        rgba: [0.05, 0.05, 0.1, 0.6]
                    RoundedRectangle:
                        pos: self.pos
                        size: self.size
                        radius: [dp(20),]

            BoxLayout:
                id: main_content
                orientation: 'vertical'
                padding: dp(20)
                spacing: dp(15)

                BoxLayout:
                    size_hint_y: None
                    height: dp(60)
                    padding: [dp(10), 0]

                    Label:
                        text: root.current_time
                        font_size: '22sp'
                        color: app.theme_colors['accent']
                        bold: True
                        size_hint_x: None
                        width: dp(120)

                    Widget:

                    BoxLayout:
                        id: nav_container
                        size_hint: None, 1
                        width: dp(120)
                        spacing: dp(15)

                Widget:
                    size_hint_y: None
                    height: dp(3)
                    canvas:
                        Color:
                            rgba: [0.8, 0.6, 1, 0.8]
                        Line:
                            points: [self.x + dp(20), self.y + dp(1), self.right - dp(20), self.y + dp(1)]
                            width: 2

                ScreenManager:
                    id: main_pages
                    size_hint: 1, 1

                    Screen:
                        name: 'home'
                        BoxLayout:
                            orientation: 'vertical'
                            spacing: dp(10)

                            BoxLayout:
                                size_hint_y: None
                                height: dp(40)
                                BoxLayout:
                                    size_hint_x: None
                                    width: dp(320)
                                    pos_hint: {'center_x': 0.5}
                                    spacing: dp(5)

                                    Button:
                                        text: "Lu"
                                        size_hint_x: None
                                        width: dp(100)
                                        font_size: '16sp'
                                        bold: True
                                        background_color: [0,0,0,0] if root.current_tab != 'home_lu' else app.theme_colors['accent']
                                        color: [1,1,1,1]
                                        on_release: root.switch_tab('home', 'lu')
                                        canvas.before:
                                            Color:
                                                rgba: app.theme_colors['accent'][0], app.theme_colors['accent'][1], app.theme_colors['accent'][2], 0.3
                                            RoundedRectangle:
                                                pos: self.pos
                                                size: self.size
                                                radius: [dp(10), dp(10), 0, 0]

                                    Button:
                                        text: "Non-lu"
                                        size_hint_x: None
                                        width: dp(100)
                                        font_size: '16sp'
                                        bold: True
                                        background_color: [0,0,0,0] if root.current_tab != 'home_nonlu' else app.theme_colors['accent']
                                        color: [1,1,1,1]
                                        on_release: root.switch_tab('home', 'nonlu')
                                        canvas.before:
                                            Color:
                                                rgba: app.theme_colors['accent'][0], app.theme_colors['accent'][1], app.theme_colors['accent'][2], 0.3
                                            RoundedRectangle:
                                                pos: self.pos
                                                size: self.size
                                                radius: [dp(10), dp(10), 0, 0]

                                    Button:
                                        text: "Marque"
                                        size_hint_x: None
                                        width: dp(100)
                                        font_size: '16sp'
                                        bold: True
                                        background_color: [0,0,0,0] if root.current_tab != 'home_marque' else app.theme_colors['accent']
                                        color: [1,1,1,1]
                                        on_release: root.switch_tab('home', 'marque')
                                        canvas.before:
                                            Color:
                                                rgba: app.theme_colors['accent'][0], app.theme_colors['accent'][1], app.theme_colors['accent'][2], 0.3
                                            RoundedRectangle:
                                                pos: self.pos
                                                size: self.size
                                                radius: [dp(10), dp(10), 0, 0]

                            BoxLayout:
                                id: home_content
                                orientation: 'vertical'
                                padding: dp(15)
                                canvas.before:
                                    Color:
                                        rgba: [0.1, 0.1, 0.15, 0.3]
                                    RoundedRectangle:
                                        pos: self.pos
                                        size: self.size
                                        radius: [0, 0, dp(15), dp(15)]

                    Screen:
                        name: 'alerts'
                        BoxLayout:
                            orientation: 'vertical'
                            spacing: dp(10)
                            Label:
                                text: "Page Alertes"
                                font_size: '24sp'
                                color: [1,1,1,1]
                                size_hint_y: None
                                height: dp(40)
                            BoxLayout:
                                id: alerts_content
                                orientation: 'vertical'
                                padding: dp(15)

                    Screen:
                        name: 'profile'
                        BoxLayout:
                            orientation: 'vertical'
                            spacing: dp(10)
                            Label:
                                text: "Page Profil"
                                font_size: '24sp'
                                color: [1,1,1,1]
                                size_hint_y: None
                                height: dp(40)
                            BoxLayout:
                                id: profile_content
                                orientation: 'vertical'
                                padding: dp(15)

                    Screen:
                        name: 'settings'
                        BoxLayout:
                            orientation: 'vertical'
                            spacing: dp(10)
                            Label:
                                text: "Page Parametres"
                                font_size: '24sp'
                                color: [1,1,1,1]
                                size_hint_y: None
                                height: dp(40)
                            BoxLayout:
                                id: settings_content
                                orientation: 'vertical'
                                padding: dp(15)

                BoxLayout:
                    size_hint_y: None
                    height: dp(50)
                    spacing: dp(12)

                    Image:
                        id: theme_icon
                        source: app.resource_path('box.png')
                        size_hint: None, None
                        size: dp(40), dp(40)
                        allow_stretch: True
                        on_touch_down: if self.collide_point(*args[1].pos): root.toggle_theme_menu()

                    BoxLayout:
                        id: theme_menu
                        orientation: 'horizontal'
                        size_hint_x: None
                        width: 0
                        opacity: 0
                        spacing: dp(10)

        BoxLayout:
            id: section_b
            orientation: 'vertical'
            size_hint_x: None
            width: 0
            opacity: 0
            padding: dp(20)
            spacing: dp(15)
            canvas.before:
                Color:
                    rgba: [0.08, 0.08, 0.15, 0.5]
                RoundedRectangle:
                    pos: self.pos
                    size: self.size
                    radius: [dp(35),]
                Color:
                    rgba: app.theme_colors['accent'][0], app.theme_colors['accent'][1], app.theme_colors['accent'][2], 0.4
                Line:
                    width: 1.2
                    rounded_rectangle: (self.x, self.y, self.width, self.height, dp(35))

            BoxLayout:
                size_hint_y: None
                height: dp(40)
                Label:
                    id: module_panel_title
                    text: "MODULES"
                    bold: True
                    font_size: '14sp'
                    color: app.theme_colors['accent']

                Button:
                    size_hint: None, None
                    width: dp(30)
                    height: dp(30)
                    background_color: [0,0,0,0]
                    on_release: root.toggle_modules()
                    Image:
                        source: app.resource_path('x.png')
                        center_x: self.parent.center_x
                        center_y: self.parent.center_y
                        size: dp(20), dp(20)

            BoxLayout:
                id: module_content_area
                orientation: 'vertical'

                ScrollView:
                    id: scroll_modules
                    GridLayout:
                        id: modules_grid
                        cols: 2
                        spacing: dp(12)
                        size_hint_y: None
                        height: self.minimum_height
                        width: self.minimum_width
                        padding: [dp(5), dp(5)]
"""

# -------------------------------------------------------------------
# Application principale
# -------------------------------------------------------------------
class CyberCoreApp(App):
    theme_colors = ObjectProperty({
        'bg': '#0a0a12',
        'accent': get_color_from_hex('#7b2cbf')
    })

    def get_best_font(self):
        general_font = "/usr/share/fonts/truetype/fonts-bpg-georgian/BPG_Elite_GPL&GNU.ttf"
        if os.path.exists(general_font):
            return general_font
        fallbacks = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "DejaVuSans",
            "Arial",
            "Roboto"
        ]
        for f in fallbacks:
            if os.path.exists(f):
                return f
        return "Roboto"

    def resource_path(self, relative_path):
        """Wrapper pour la fonction resource_path"""
        return resource_path(relative_path)

    def change_theme(self, hex_color):
        self.theme_colors['accent'] = get_color_from_hex(hex_color)

    def build(self):
        # Utiliser la base de donnees simulee si PostgreSQL n'est pas disponible
        if POSTGRES_AVAILABLE:
            try:
                POSTGRES_DSN = "postgresql://postgres:mlrLJbMKLmCozyCtUBNKtCzVGWnXQHnG@shuttle.proxy.rlwy.net:49373/railway"
                self.db = PostgresDB(POSTGRES_DSN, timeout=20)
                Logger.info("Tentative de connexion a PostgreSQL...")
            except Exception as e:
                Logger.error(f"Erreur lors de la creation de la connexion: {e}")
                self.db = MockDatabase()
                Logger.info("Utilisation du mode simulation")
        else:
            self.db = MockDatabase()
            Logger.info("Utilisation du mode simulation (base de donnees locale)")

        Builder.load_string(KV)
        sm = ScreenManager(transition=FadeTransition(duration=0.3))
        sm.add_widget(AuthScreen(name='auth'))
        sm.add_widget(MainScreen(name='main'))
        return sm

if __name__ == '__main__':
    CyberCoreApp().run()