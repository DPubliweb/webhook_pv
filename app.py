import os
import json
import time
import threading
from datetime import datetime

from flask import Flask, request, jsonify
from flask_cors import CORS

import gspread
from oauth2client.service_account import ServiceAccountCredentials

import nexmo
from dotenv import load_dotenv

import psycopg2
from psycopg2.pool import SimpleConnectionPool
import re
import unicodedata



# ============================================================
# Init
# ============================================================
load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# ============================================================
# Google Sheets creds env
# ============================================================
scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

TYPE = os.environ.get("TYPE")
PROJECT_ID = os.environ.get("PROJECT_ID")
PRIVATE_KEY_ID = os.environ.get("PRIVATE_KEY_ID")
PRIVATE_KEY = (os.environ.get("PRIVATE_KEY") or "").replace("\\n", "\n")
CLIENT_EMAIL = os.environ.get("CLIENT_EMAIL")
CLIENT_ID = os.environ.get("CLIENT_ID")
AUTH_URI = os.environ.get("AUTH_URI")
TOKEN_URI = os.environ.get("TOKEN_URI")
AUTH_PROVIDER_X509_CERT_URL = os.environ.get("AUTH_PROVIDER_X509_CERT_URL")
CLIENT_X509_CERT_URL = os.environ.get("CLIENT_X509_CERT_URL")

KEY_VONAGE = os.environ.get("KEY_VONAGE")
KEY_VONAGE_SECRET = os.environ.get("KEY_VONAGE_SECRET")

# Google creds
creds = ServiceAccountCredentials.from_json_keyfile_dict(
    {
        "type": TYPE,
        "project_id": PROJECT_ID,
        "private_key_id": PRIVATE_KEY_ID,
        "private_key": PRIVATE_KEY,
        "client_email": CLIENT_EMAIL,
        "client_id": CLIENT_ID,
        "auth_uri": AUTH_URI,
        "token_uri": TOKEN_URI,
        "auth_provider_x509_cert_url": AUTH_PROVIDER_X509_CERT_URL,
        "client_x509_cert_url": CLIENT_X509_CERT_URL,
    },
    scope,
)

client = gspread.authorize(creds)

# Vonage client
client_vonage = nexmo.Client(key=KEY_VONAGE, secret=KEY_VONAGE_SECRET)

# ============================================================
# Redshift env (NEW)
# ============================================================
REDSHIFT_HOST = os.environ.get("REDSHIFT_HOST", "")
REDSHIFT_PORT = int(os.environ.get("REDSHIFT_PORT", "5439"))
REDSHIFT_DB = os.environ.get("REDSHIFT_DB", "")
REDSHIFT_USER = os.environ.get("REDSHIFT_USER", "")
REDSHIFT_PASSWORD = os.environ.get("REDSHIFT_PASSWORD", "")
REDSHIFT_SCHEMA = os.environ.get("REDSHIFT_SCHEMA", "public")
REDSHIFT_TABLE = os.environ.get("REDSHIFT_TABLE", "")
REDSHIFT_SSLMODE = os.environ.get("REDSHIFT_SSLMODE", "require")

redshift_pool = None


def _utc_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _trunc(v, max_len=1000) -> str:
    if v is None:
        return ""
    s = str(v)
    return s[:max_len]


def _first_ip(xff: str) -> str:
    if not xff:
        return ""
    return xff.split(",")[0].strip()


def _norm_txt(s: str) -> str:
    if not s:
        return ""
    # enlève les étoiles typeform "*...*"
    s = s.replace("*", " ")
    # minuscules + suppression accents
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    # espaces clean
    s = re.sub(r"\s+", " ", s).strip()
    return s

def parse_iso(dt_str: str) -> str:
    """
    Normalise une date ISO reçue (avec ou sans ms), sinon now UTC.
    Output: YYYY-MM-DDTHH:MM:SSZ
    """
    if not dt_str:
        return _utc_iso()
    s = str(dt_str)
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            pass
    return _utc_iso()


def _merge_analytics(analytics_str: str, extra: dict) -> str:
    """
    analytics est stocké dans Redshift en VARCHAR(1000).
    On essaie de conserver du JSON et d'ajouter ip/headers côté serveur.
    """
    base = {}
    try:
        if analytics_str:
            base = json.loads(analytics_str)
            if not isinstance(base, dict):
                base = {"raw": analytics_str}
    except Exception:
        base = {"raw": analytics_str}

    base.update(extra)
    out = json.dumps(base, separators=(",", ":"), ensure_ascii=False)
    return _trunc(out, 1000)


def _redshift_ready() -> bool:
    return bool(REDSHIFT_HOST and REDSHIFT_DB and REDSHIFT_USER and REDSHIFT_PASSWORD and REDSHIFT_TABLE)


def _get_redshift_pool():
    global redshift_pool
    if redshift_pool is not None:
        return redshift_pool
    if not _redshift_ready():
        return None

    redshift_pool = SimpleConnectionPool(
        1,
        5,
        host=REDSHIFT_HOST,
        port=REDSHIFT_PORT,
        dbname=REDSHIFT_DB,
        user=REDSHIFT_USER,
        password=REDSHIFT_PASSWORD,
        sslmode=REDSHIFT_SSLMODE,
        connect_timeout=5,
    )
    return redshift_pool


def normalize_redshift_row(payload: dict, req) -> dict:
    """
    Attend le payload React "plat" et retourne une row conforme à la table Redshift.
    Champs attendus:
      analytics, civilite, code, code_postal, cohort, email, nom, prenom, telephone, utm_source,
      user_agent, platform, referer, network_id, browser, date_import, submitted_at,
      reponse_1, reponse_2, reponse_3
    """
    xff = req.headers.get("X-Forwarded-For", "")
    ip = _first_ip(xff) or (req.remote_addr or "")
    accept_lang = req.headers.get("Accept-Language", "")

    submitted_at = parse_iso(payload.get("submitted_at") or payload.get("timestamp"))
    date_import = parse_iso(payload.get("date_import") or submitted_at)

    analytics_in = _trunc(payload.get("analytics", ""), 1000)
    analytics = _merge_analytics(
        analytics_in,
        {
            "ip": ip,
            "xff": xff,
            "accept_language": accept_lang,
            "server_received_at": _utc_iso(),
        },
    )

    return {
        "analytics": analytics,
        "civilite": _trunc(payload.get("civilite", ""), 1000),
        "code": _trunc(payload.get("code", ""), 1000),
        "code_postal": _trunc(payload.get("code_postal", ""), 1000),
        "cohort": _trunc(payload.get("cohort", ""), 1000),
        "email": _trunc(payload.get("email", ""), 1000),
        "nom": _trunc(payload.get("nom", ""), 1000),
        "prenom": _trunc(payload.get("prenom", ""), 1000),
        "telephone": _trunc(payload.get("telephone", ""), 1000),
        "utm_source": _trunc(payload.get("utm_source", ""), 1000),
        "user_agent": _trunc(payload.get("user_agent") or req.headers.get("User-Agent", ""), 1000),
        "platform": _trunc(payload.get("platform", ""), 1000),
        "referer": _trunc(payload.get("referer") or req.headers.get("Referer", ""), 1000),
        "network_id": _trunc(payload.get("network_id", ""), 1000),
        "browser": _trunc(payload.get("browser", ""), 1000),
        "date_import": _trunc(date_import, 1000),
        "submitted_at": _trunc(submitted_at, 1000),
        "reponse_1": _trunc(payload.get("reponse_1", ""), 50),
        "reponse_2": _trunc(payload.get("reponse_2", ""), 50),
        "reponse_3": _trunc(payload.get("reponse_3", ""), 50),
    }


def insert_redshift_row(row: dict):
    """
    Insert dans la table Redshift (elle doit déjà exister).
    """
    pool = _get_redshift_pool()
    if pool is None:
        raise RuntimeError("Redshift not configured (missing REDSHIFT_* env vars)")

    sql = f"""
        INSERT INTO {REDSHIFT_SCHEMA}.{REDSHIFT_TABLE} (
            analytics,
            civilite,
            code,
            code_postal,
            cohort,
            email,
            nom,
            prenom,
            telephone,
            utm_source,
            user_agent,
            platform,
            referer,
            network_id,
            browser,
            date_import,
            submitted_at,
            reponse_1,
            reponse_2,
            reponse_3
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """

    params = (
        row["analytics"],
        row["civilite"],
        row["code"],
        row["code_postal"],
        row["cohort"],
        row["email"],
        row["nom"],
        row["prenom"],
        row["telephone"],
        row["utm_source"],
        row["user_agent"],
        row["platform"],
        row["referer"],
        row["network_id"],
        row["browser"],
        row["date_import"],
        row["submitted_at"],
        row["reponse_1"],
        row["reponse_2"],
        row["reponse_3"],
    )

    conn = pool.getconn()
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(sql, params)
    finally:
        pool.putconn(conn)


# ============================================================
# Redshift persistent queue (retry) (NEW)
# ============================================================
REDSHIFT_QUEUE_FILE = "redshift_queue.json"
_redshift_lock = threading.Lock()

if not os.path.exists(REDSHIFT_QUEUE_FILE):
    with open(REDSHIFT_QUEUE_FILE, "w") as f:
        json.dump([], f)


def add_to_redshift_queue(row: dict):
    with _redshift_lock:
        with open(REDSHIFT_QUEUE_FILE, "r+") as f:
            rows = json.load(f)
            rows.append(row)
            f.seek(0)
            json.dump(rows, f)
            f.truncate()


def pop_from_redshift_queue():
    with _redshift_lock:
        with open(REDSHIFT_QUEUE_FILE, "r+") as f:
            rows = json.load(f)
            if not rows:
                return None
            row = rows.pop(0)
            f.seek(0)
            json.dump(rows, f)
            f.truncate()
            return row


def redshift_worker():
    while True:
        row = pop_from_redshift_queue()
        if not row:
            time.sleep(5)
            continue
        try:
            insert_redshift_row(row)
            print("✅ Redshift insert OK (from queue)")
        except Exception as e:
            print("❌ Redshift insert failed (requeue):", str(e))
            add_to_redshift_queue(row)
            time.sleep(5)


threading.Thread(target=redshift_worker, daemon=True).start()


# ============================================================
# Old pipeline: persistent queue -> worker -> process_lead
# ============================================================
QUEUE_FILE = "leads_queue.json"
_queue_lock = threading.Lock()

if not os.path.exists(QUEUE_FILE):
    with open(QUEUE_FILE, "w") as f:
        json.dump([], f)


def add_to_queue(lead):
    with _queue_lock:
        with open(QUEUE_FILE, "r+") as f:
            leads = json.load(f)
            leads.append(lead)
            f.seek(0)
            json.dump(leads, f)
            f.truncate()


def pop_from_queue():
    with _queue_lock:
        with open(QUEUE_FILE, "r+") as f:
            leads = json.load(f)
            if not leads:
                return None
            lead = leads.pop(0)
            f.seek(0)
            json.dump(leads, f)
            f.truncate()
            return lead


# ============================================================
# Client interests (unchanged)
# ============================================================
clientInterests = {
    "André": [27,76,29,56,22,35,24,33,40,47,21,58,71,89,18,28,36,37,41,45,19,23,87,48,25,39,70,90,8,10,51,52,54,55,57,88,12,32,46,81,82,59,62,14,50,61,44,49,53,72,85,2,60,80,16,17,79,86,7,26,38,1,69,42,4,84,30,34,83,11,66],
    'Alex Benamou': [27,28,45,60,76],
    'Jayson Partouche': [79,49,85],
    'Axel Zarka':[27,76,14,50,61,62,31,81,27,28,45,60,76],
    'Gary Cohen':[6,30,34,38,69,83],
    'Reb 1': [63,3,43],
    'Reb 2': [8,51,10,52,55,89],
    'Reb 3': [57,54,70,88]

}

# ============================================================
# normalize_lead: accepte payload Typeform OU payload React (NEW)
# ============================================================
def normalize_lead(data: dict) -> dict:
    """
    Convertit un payload React "plat" vers le format attendu par process_lead
    (typeform-like: form_response.hidden + form_response.answers).
    Si déjà au format typeform, renvoie tel quel.
    """

    # Déjà au format typeform-like
    if isinstance(data, dict) and "form_response" in data:
        fr = data.get("form_response", {})
        fr["submitted_at"] = parse_iso(fr.get("submitted_at"))

        # --- ✅ ADAPTATION NOUVELLE QUESTION "tout en une" ---
        answers = fr.get("answers", []) or []
        if len(answers) == 1:
            raw_label = (answers[0].get("choice", {}) or {}).get("label", "") or ""
            label = _norm_txt(raw_label)

            type_label = ""
            own_label = ""

            # habitation
            if "maison" in label:
                type_label = "Maison ✅"
            elif "appartement" in label:
                type_label = "Appartement ❌"

            # statut
            # (on cherche propriétaire / locataire)
            if "propriet" in label:      # couvre proprietaire / propriete...
                own_label = "Propriétaire ✅"
            elif "locat" in label:       # couvre locataire / location...
                own_label = "Locataire ❌"

            # Si on a pu déduire au moins un des 2, on réécrit le format attendu
            if type_label or own_label:
                fr["answers"] = [
                    {"type": "choice", "choice": {"label": type_label}},
                    {"type": "choice", "choice": {"label": own_label}},
                ]

        data["form_response"] = fr
        return data

    # Payload React "plat" (inchangé)
    prop = data.get("property_type") or data.get("reponse_1") or data.get("propertyType") or ""
    own = data.get("ownership_status") or data.get("reponse_2") or data.get("ownershipStatus") or ""

    type_label = "Maison ✅" if prop == "house" else "Appartement ❌" if prop == "apartment" else ""
    own_label = "Propriétaire ✅" if own == "owner" else "Locataire ❌" if own == "tenant" else ""

    return {
        "form_response": {
            "hidden": {
                "telephone": data.get("telephone", ""),
                "nom": data.get("nom", ""),
                "prenom": data.get("prenom", ""),
                "email": data.get("email", ""),
                "code_postal": data.get("code_postal", ""),
                "civilite": data.get("civilite", ""),
                "utm_source": data.get("utm_source", ""),
                "code": data.get("code", ""),
            },
            "submitted_at": parse_iso(data.get("submitted_at") or data.get("date_import") or data.get("timestamp")),
            "answers": [
                {"type": "choice", "choice": {"label": type_label}},
                {"type": "choice", "choice": {"label": own_label}},
            ],
        },
        "page": data.get("page", ""),
    }
# ============================================================
# process_lead (UNCHANGED, juste sécurisation parse date)
# ============================================================
def process_lead(lead):
    global client, client_vonage

    try:
        phone = lead["form_response"]["hidden"].get("telephone", "")
        nom = lead["form_response"]["hidden"].get("nom", "")
        prenom = lead["form_response"]["hidden"].get("prenom", "")
        email = lead["form_response"]["hidden"].get("email", "")
        zipcode = lead["form_response"]["hidden"].get("code_postal", "")
        civilite = lead["form_response"]["hidden"].get("civilite", "")
        utm_source = lead["form_response"]["hidden"].get("utm_source", "")
        code = lead["form_response"]["hidden"].get("code", "")
        date = lead["form_response"].get("submitted_at", "")

        # Conversion date -> affichage FR
        date_iso = parse_iso(date)
        date_obj = datetime.strptime(date_iso, "%Y-%m-%dT%H:%M:%SZ")
        date_sliced = date_obj.strftime("%d-%m-%Y %H:%M")

        form_list = lead["form_response"].get("answers", [])
        type_habitation = ""
        statut_habitation = ""
        if len(form_list) > 0:
            type_habitation = form_list[0].get("choice", {}).get("label", "") or ""
        if len(form_list) > 1:
            statut_habitation = form_list[1].get("choice", {}).get("label", "") or ""

        print("Téléphone:", phone, date_sliced)

        # Département
        if zipcode:
            if len(zipcode) == 4:
                zipcode = "0" + zipcode
            department = zipcode[:2]
        else:
            department = ""

        interested_clients = []
        if department:
            try:
                dep_int = int(department)
                for clients, departments in clientInterests.items():
                    if dep_int in departments:
                        interested_clients.append(clients)
            except Exception:
                pass

        # Google Sheet
        sheet = client.open("Panneaux Solaires - Publiweb").sheet1
        all_values = sheet.get_all_values()
        existing_phones = [row[5] for row in all_values]  # tel en colonne 6

        if phone not in existing_phones:
            next_row = len(all_values) + 1

            if next_row > sheet.row_count:
                sheet.add_rows(1)

            # reset white
            sheet.format(f"A{next_row}:O{next_row}", {
                "backgroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0}
            })

            sheet.update(f"A{next_row}:N{next_row}", [[
                type_habitation,
                statut_habitation,
                civilite,
                nom,
                prenom,
                phone,
                email,
                zipcode,
                code,
                utm_source,
                "",
                date_sliced,
                department,
                ", ".join(interested_clients),
            ]])

            print("Nouveau lead inscrit")

            # Rouge si KO
            if type_habitation == "Appartement ❌" or statut_habitation == "Locataire ❌":
                sheet.format(f"A{next_row}:O{next_row}", {
                    "backgroundColor": {"red": 1.0, "green": 0.0, "blue": 0.0}
                })

            # SMS si OK
            if type_habitation != "Appartement ❌" and statut_habitation != "Locataire ❌":
                response = client_vonage.send_message({
                    "from": "RDV TEL",
                    "to": phone,
                    "text": (
                        f"Bonjour {prenom} {nom}\n"
                        f"Merci pour votre demande\n"
                        f"Un conseiller vous recontactera sous 24h à 48h\n\n"
                        f"Pour sécuriser votre parcours, veuillez noter votre code dossier {code}. "
                        f"Pour annuler votre RDV, cliquez ici: https:://vvs.bz/annulationPVML"
                    )
                })
                print("Réponse Vonage:", response)
                if response.get("messages", [{}])[0].get("status") != "0":
                    print("Erreur SMS:", response.get("messages", [{}])[0].get("error-text", "unknown"))
        else:
            print("Lead déjà existant avec ce numéro")

    except Exception as e:
        print("Erreur process_lead:", str(e))
        # Réajouter le lead en cas d'échec
        add_to_queue(lead)


def worker():
    while True:
        lead = pop_from_queue()
        if lead:
            process_lead(lead)
        else:
            time.sleep(5)


threading.Thread(target=worker, daemon=True).start()


# ============================================================
# Routes
# ============================================================
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "time": _utc_iso()}), 200


@app.route("/leads_pv", methods=["POST", "OPTIONS"])
def webhook_leads_pv():
    # preflight CORS
    if request.method == "OPTIONS":
        return ("", 204)

    try:
        data = request.get_json(silent=True)
        if not data or not isinstance(data, dict):
            print("❌ /leads_pv: JSON invalide")
            return jsonify({"status": "error", "message": "Invalid JSON"}), 400

        # ---- 1) Redshift (NEW) ----
        # On essaye d'insérer; si ça échoue, on requeue pour retry.
        try:
            row = normalize_redshift_row(data, request)
            insert_redshift_row(row)
            print("✅ Redshift insert OK")
        except Exception as e:
            print("❌ Redshift insert failed (queued):", str(e))
            try:
                row = normalize_redshift_row(data, request)
                add_to_redshift_queue(row)
            except Exception as e2:
                print("❌ Redshift queue failed:", str(e2))
            # Important: on ne bloque pas le pipeline Google Sheet

        # ---- 2) Google Sheets pipeline (OLD) ----
        lead = normalize_lead(data)
        print("✅ /leads_pv reçu (hidden):", lead.get("form_response", {}).get("hidden", {}))
        add_to_queue(lead)

        return jsonify({"status": "success", "message": "Lead reçu."}), 200

    except Exception as e:
        print("Erreur inattendue /leads_pv :", str(e))
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/leads_desinscription_pv", methods=["GET", "POST"])
def webhook_leads_desinscription_pv():
    print("desinscription pv")

    ct = request.headers.get("Content-Type", "")
    if "application/json" in ct:
        json_tree = request.get_json(silent=True) or {}
        form_list = json_tree.get("form_response", {}).get("answers", [])

        phone_without_plus = None
        for answer in form_list:
            if answer.get("type") == "phone_number":
                phone_with_plus = answer.get("phone_number", "")
                phone_without_plus = phone_with_plus.lstrip("+")
                break

        if phone_without_plus is None:
            return "Phone number not found in the form responses", 400

        sheet = client.open("Panneaux Solaires - Publiweb").sheet1
        all_values = sheet.get_all_values()

        row_number = None
        for index, row in enumerate(all_values):
            if len(row) > 5 and row[5] == phone_without_plus:
                row_number = index + 1
                break

        if row_number:
            sheet.update_cell(row_number, 11, "DÉSINSCRIT")
            sheet.format(f"A{row_number}:O{row_number}", {
                "backgroundColor": {"red": 1.0, "green": 0.0, "blue": 0.0}
            })
            return "Done"
        else:
            print("Numéro à désinscrire non trouvé")
            return "Numéro à désinscrire non trouvé"
    else:
        return "Not there"


@app.route("/webhook_unbounce_pv", methods=["POST"])
def webhook_unbounce_pv():
    if not request.is_json:
        return jsonify({"status": "error", "message": "Erreur de format de requête"}), 400

    data = request.get_json(silent=True) or {}

    civilite = data.get("civilite", "")
    time_submitted = data.get("time_submitted", "")
    prenom = data.get("prenom", "")
    code = data.get("code", "")
    date_submitted = data.get("date_submitted", "")
    phone = data.get("telephone", "")
    utm_source = data.get("utm_source", "")
    nom = data.get("nom", "")
    email = data.get("email", "")
    statut_habitation = data.get("êtesvous_propriétaire_ou_locataire_", "")
    type_habitation = data.get("vivezvous_en_maison_ou_en_appartement_", "")
    zipcode = data.get("code_postal", "")
    date_time = (date_submitted + " " + time_submitted).strip()
    cohort = ""

    print("téléphone:", phone, date_time)

    if zipcode:
        if len(zipcode) == 4:
            zipcode = "0" + zipcode
        department = zipcode[:2]
    else:
        department = ""

    interested_clients = []
    if department:
        try:
            dep_int = int(department)
            for clients, departments in clientInterests.items():
                if dep_int in departments:
                    interested_clients.append(clients)
        except Exception:
            pass

    try:
        sheet = client.open("Panneaux Solaires - Publiweb").sheet1
        all_values = sheet.get_all_values()
        existing_phones = [row[5] for row in all_values]

        if phone not in existing_phones:
            next_row = len(all_values) + 1
            if next_row > sheet.row_count:
                sheet.add_rows(1)

            sheet.format(f"A{next_row}:O{next_row}", {
                "backgroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0}
            })

            sheet.update(f"A{next_row}:N{next_row}", [[
                type_habitation, statut_habitation, civilite, nom, prenom, phone, email,
                zipcode, code, utm_source, " ", date_time, department, ", ".join(interested_clients)
            ]])

            if type_habitation == "Appartement ❌" or statut_habitation == "Locataire ❌":
                sheet.format(f"A{next_row}:O{next_row}", {
                    "backgroundColor": {"red": 1.0, "green": 0.0, "blue": 0.0}
                })

            if type_habitation != "Appartement ❌" and statut_habitation != "Locataire ❌":
                try:
                    response = client_vonage.send_message({
                        "from": "RDV TEL",
                        "to": phone,
                        "text": (
                            f"Bonjour {prenom} {nom}\n"
                            f"Merci pour votre demande\n"
                            f"Un conseiller vous recontactera sous 24h à 48h\n\n"
                            f"Pour sécuriser votre parcours, veuillez noter votre code dossier {code}. "
                            f"Pour annuler votre RDV, cliquez ici: https://vvs.bz/annulationPVML"
                        )
                    })
                    if response.get("messages", [{}])[0].get("status") != "0":
                        return jsonify({"status": "error", "message": response.get("messages", [{}])[0].get("error-text", "SMS error")})
                    return jsonify({"status": "success", "message": "Enregistrement réussi!"})
                except Exception as e:
                    return jsonify({"status": "error", "message": str(e)}), 500
            else:
                return jsonify({"status": "success", "message": "Enregistrement réussi sans envoi de SMS."})
        else:
            return jsonify({"status": "duplicate", "message": "Lead déjà existant"}), 200

    except Exception as e:
        print("Erreur Sheets:", str(e))
        return jsonify({"status": "error", "message": str(e)}), 500


# ============================================================
# Main
# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False)
