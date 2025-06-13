import json
import os
from flask import Flask, request, jsonify
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import nexmo
from dotenv import load_dotenv
import time
import threading

load_dotenv()

app = Flask(__name__)

scope = ['https://www.googleapis.com/auth/spreadsheets',
         "https://www.googleapis.com/auth/drive"]

# Charger les variables d'environnement
TYPE = os.environ.get("TYPE")
PROJECT_ID = os.environ.get("PROJECT_ID")
PRIVATE_KEY_ID = os.environ.get("PRIVATE_KEY_ID")
PRIVATE_KEY = os.environ.get("PRIVATE_KEY").replace("\\n", "\n")
CLIENT_EMAIL = os.environ.get("CLIENT_EMAIL")
CLIENT_ID = os.environ.get("CLIENT_ID")
AUTH_URI = os.environ.get("AUTH_URI")
TOKEN_URI = os.environ.get("TOKEN_URI")
AUTH_PROVIDER_X509_CERT_URL = os.environ.get("AUTH_PROVIDER_X509_CERT_URL")
CLIENT_X509_CERT_URL = os.environ.get("CLIENT_X509_CERT_URL")
KEY_VONAGE = os.environ.get("KEY_VONAGE")
KEY_VONAGE_SECRET = os.environ.get("KEY_VONAGE_SECRET")

# Initialiser les credentials pour Google Sheets à partir des variables d'environnement
creds = ServiceAccountCredentials.from_json_keyfile_dict({
    "type": TYPE,
    "project_id": PROJECT_ID,
    "private_key_id": PRIVATE_KEY_ID,
    "private_key": PRIVATE_KEY,
    "client_email": CLIENT_EMAIL,
    "client_id": CLIENT_ID,
    "auth_uri": AUTH_URI,
    "token_uri": TOKEN_URI,
    "auth_provider_x509_cert_url": AUTH_PROVIDER_X509_CERT_URL,
    "client_x509_cert_url": CLIENT_X509_CERT_URL
}, scope)

# Initialisation globale du client gspread
client = gspread.authorize(creds)
# Fichier pour stocker la file d'attente
QUEUE_FILE = "leads_queue.json"

# Initialisation de la file d'attente persistante
if not os.path.exists(QUEUE_FILE):
    with open(QUEUE_FILE, 'w') as f:
        json.dump([], f)

# Fonction pour ajouter un lead à la file d'attente
def add_to_queue(lead):
    with open(QUEUE_FILE, 'r+') as f:
        leads = json.load(f)
        leads.append(lead)
        f.seek(0)
        json.dump(leads, f)

# Fonction pour retirer un lead de la file d'attente
def pop_from_queue():
    with open(QUEUE_FILE, 'r+') as f:
        leads = json.load(f)
        if not leads:
            return None
        lead = leads.pop(0)
        f.seek(0)
        json.dump(leads, f)
        f.truncate()
        return lead

# Fonction principale pour traiter un lead
def process_lead(lead):
    global client, client_vonage

    try:
        phone = lead["form_response"]["hidden"]["telephone"]
        nom = lead["form_response"]["hidden"]["nom"]
        prenom = lead["form_response"]["hidden"]["prenom"]
        email = lead["form_response"]["hidden"]["email"]
        zipcode = lead["form_response"]["hidden"]["code_postal"]
        civilite = lead["form_response"]["hidden"]["civilite"]
        utm_source = lead["form_response"]["hidden"]["utm_source"]
        code = lead["form_response"]["hidden"]["code"]
        date = lead["form_response"]["submitted_at"]

        # Conversion et formatage de la date
        date_obj = datetime.strptime(date, "%Y-%m-%dT%H:%M:%SZ")
        date_sliced = date_obj.strftime("%d-%m-%Y %H:%M")

        form_list = lead['form_response']['answers']
        type_habitation = form_list[0]['choice']['label']
        statut_habitation = form_list[1]['choice']['label']

        print("Téléphone:", phone, date_sliced)

        # Gestion du département
        if zipcode:
            if len(zipcode) == 4:
                zipcode = '0' + zipcode
            department = zipcode[:2]
        else:
            department = ''

        # Gestion des clients intéressés
        interested_clients = []
        if department:
            for clients, departments in clientInterests.items():
                if int(department) in departments:
                    interested_clients.append(clients)

        # Interaction avec Google Sheets
        sheet = client.open("Panneaux Solaires - Publiweb").sheet1
        all_values = sheet.get_all_values()
        existing_phones = [row[5] for row in all_values]

        if phone not in existing_phones:
            next_row = len(all_values) + 1

            if next_row > sheet.row_count:
                sheet.add_rows(1)

            sheet.format(f'A{next_row}:O{next_row}', {
                "backgroundColor": {
                    "red": 1.0,
                    "green": 1.0,
                    "blue": 1.0
                }
            })

            sheet.update(f'A{next_row}:N{next_row}', [[
                type_habitation, statut_habitation, civilite, nom, prenom, phone, email,
                zipcode, code, utm_source, "", date_sliced, department, ", ".join(interested_clients)
            ]])
            print("Nouveau lead inscrit")

            # Gestion des couleurs en fonction des critères
            if type_habitation == "Appartement ❌" or statut_habitation == "Locataire ❌":
                sheet.format(f'A{next_row}:O{next_row}', {
                    "backgroundColor": {
                        "red": 1.0,
                        "green": 0.0,
                        "blue": 0.0
                    }
                })

            # Envoi de SMS
            if type_habitation != "Appartement ❌" and statut_habitation != "Locataire ❌":
                response = client_vonage.send_message({
                    'from': 'RDV TEL',
                    'to': phone,
                    'text': f'Bonjour {prenom} {nom}\nMerci pour votre demande\nUn conseiller vous recontactera sous 24h à 48h\n\nPour sécuriser votre parcours, veuillez noter votre code dossier {code}. Pour annuler votre RDV, cliquez ici: https:://vvs.bz/annulationPVML'
                })
                print("Réponse de Vonage:", response)
                if response['messages'][0]['status'] != '0':
                    print("Erreur lors de l'envoi du message:", response['messages'][0]['error-text'])
        else:
            print("Lead déjà existant avec ce numéro de téléphone")

    except Exception as e:
        print(f"Erreur lors du traitement du lead : {e}")
        # Réajouter le lead en cas d'échec
        add_to_queue(lead)

# Worker pour traiter les leads en arrière-plan
def worker():
    while True:
        lead = pop_from_queue()
        if lead:
            process_lead(lead)
        else:
            time.sleep(5)

# Démarrage du worker en arrière-plan
thread = threading.Thread(target=worker, daemon=True)
thread.start()
# Initialisation globale du client Vonage
client_vonage = nexmo.Client(key=KEY_VONAGE, secret=KEY_VONAGE_SECRET)
clientInterests = {
            'David Madar': [60,72,62,59,80,2,28,45],
            'Gary Cohen': [6,30,34,38,69], 
            'André': [24,33,40,47,43,3,63,15,21,71,89,58,22,29,35,56,18,28,36,41,45,37,8,10,51,52,39,25,70,90,48,19,23,87,54,55,57,88,12,31,32,46,81,82,59,62,14,50,61,27,76,44,49,53,72,85,2,60,80,16,17,79,86,1,26,38,7,42,67,68,64,74,69,73,65,84],
            'Samy YE': [31,81,82,65,46,12,34, 9,11,66],
            'Yoel greenberg A': [1,38,26,19,23,87],
            'Yoel greenberg A2': [55,54,88,57,36,37,41,18,28,27,61,14,50,52,35,72],
            'Yoel greenberg SE': [12,46,15,64,65], 
            'Yoel greenberg MB': [12,46,82,81], 
            'Yoel greenberg RD': [55,52,70,21,25,88,57], 
            'Samy Nakiss' : [54,55,57,70,88,68,90],
            'Samy GLC': [24,87,19,23,16],
            'Samy THC': [22,29,56,35],
            'Axel Zarka' : [14,16,17,19,50,76,87],
        }

@app.route('/leads_pv', methods=['POST'])
def webhook_leads_pv():
    try:
        if request.headers['Content-Type'] == 'application/json':
            lead_data = json.loads(request.data)
            add_to_queue(lead_data)  # Ajouter le lead à la file d'attente
            return jsonify({"status": "success", "message": "Lead ajouté à la file d'attente."})
        else:
            return jsonify({"status": "error", "message": "Format de requête incorrect"})
    except Exception as e:
        print(f"Erreur inattendue : {e}")
        return jsonify({"status": "error", "message": str(e)})

@app.route('/leads_desinscription_pv', methods=['GET', 'POST'])
def webhook_leads_desinscription_pv():
    print('desinscription pv')

    if request.headers['Content-Type'] == 'application/json':
        json_tree = json.loads(request.data)
        form_list = json_tree['form_response']['answers']
        
        phone_without_plus = None
        for answer in form_list:
            if answer['type'] == 'phone_number':
                phone_with_plus = answer['phone_number']
                phone_without_plus = phone_with_plus.lstrip('+')
                break

        if phone_without_plus is None:
            return "Phone number not found in the form responses", 400

        sheet = client.open("Panneaux Solaires - Publiweb").sheet1
        all_values = sheet.get_all_values()
        row_number = None
        for index, row in enumerate(all_values):
            if row[5] == phone_without_plus:  # L'indexation commence à 0, donc la 5ème colonne est à l'index 4
                row_number = index + 1  # L'indexation dans les Google Sheets commence à 1
                break

        # Si le numéro est trouvé, mettre à jour la cellule correspondante dans la colonne J (10ème colonne)
        if row_number:
            sheet.update_cell(row_number, 11, "DÉSINSCRIT")  # La colonne J est la 10ème colonne
            # Changer la couleur de fond de la ligne en rouge vif
            sheet.format(f'A{row_number}:O{row_number}', {
                "backgroundColor": {
                    "red": 1.0,
                    "green": 0.0,
                    "blue": 0.0
                }
            })
            return "Done"
        else: 
            print('Numéro à désinscrire non trouvé')
            return "Numéro à désinscrire non trouvé"
    else:
        return 'Not there'
    
@app.route('/webhook_unbounce_pv', methods=['POST'])
def webhook_unbounce_pv():
    # Assurer que la requête contient des données JSON
    if request.is_json:
        data = request.get_json()
        print

        # Extraire chaque champ dans une variable
        civilite = data.get('civilite')
        #cohort = data.get('cohort')
        time_submitted = data.get('time_submitted')
        prenom = data.get('prenom')
        code = data.get('code')
        date_submitted = data.get('date_submitted')
        phone = data.get('telephone')
        utm_source = data.get('utm_source')
        nom = data.get('nom')
        email = data.get('email')
        statut_habitation = data.get('êtesvous_propriétaire_ou_locataire_')
        type_habitation = data.get('vivezvous_en_maison_ou_en_appartement_')
        zipcode = data.get('code_postal')
        date_time = date_submitted + " " + time_submitted
        cohort = ""

               # Conversion et formatage de la date
        

    
        print("téléphone: ", phone , date_time)

        # Extract department
        if zipcode:
            if len(zipcode) == 4:
                zipcode = '0' + zipcode
            department = zipcode[:2]
        else:
            department = ''

        # Define client interests

        # Determine interested clients
        interested_clients = []
        if department:
            for clients, departments in clientInterests.items():
                if int(department) in departments:
                    interested_clients.append(clients)

        try:
            sheet = client.open("Panneaux Solaires - Publiweb").sheet1
            all_values = sheet.get_all_values()
            existing_phones = [row[5] for row in all_values]

            print("Numéro de téléphone reçu :", phone)

            if phone not in existing_phones:
                # Find the next available row
                next_row = len(all_values) + 1

                # Vérifier si la ligne suivante dépasse le nombre actuel de lignes
                if next_row > sheet.row_count:
                    # Ajouter une nouvelle ligne si nécessaire
                    sheet.add_rows(1)

                # Réinitialiser la couleur de fond à blanc
                sheet.format(f'A{next_row}:O{next_row}', {
                    "backgroundColor": {
                        "red": 1.0,
                        "green": 1.0,
                        "blue": 1.0
                    }
                })

                # Update the sheet with new lead information
                sheet.update(f'A{next_row}:N{next_row}', [[type_habitation, statut_habitation, civilite, nom, prenom, phone, email, zipcode, code, utm_source, ' ', date_time, department, ", ".join(interested_clients)]])
                print("Nouveau lead inscrit")


                # Change the background color if conditions are met
                if type_habitation == "Appartement ❌" or statut_habitation == "Locataire ❌":
                    sheet.format(f'A{next_row}:O{next_row}', {
                        "backgroundColor": {
                            "red": 1.0,
                            "green": 0.0,
                            "blue": 0.0
                        }
                    })

                # Envoi de SMS si les conditions sont remplies
                if type_habitation != "Appartement ❌" and statut_habitation != "Locataire ❌":
                    try:
                        response = client_vonage.send_message({
                            'from': 'RDV TEL',
                            'to': phone,
                            'text': f'Bonjour {prenom} {nom}\nMerci pour votre demande\nUn conseiller vous recontactera sous 24h à 48h\n\nPour sécuriser votre parcours, veuillez noter votre code dossier {code}. Pour annuler votre RDV, cliquez ici: https://vvs.bz/annulationPVML'
                        })
                        print("Réponse de Vonage:", response)  # Log pour la réponse de Vonage

                        if response['messages'][0]['status'] != '0':
                            print("Erreur lors de l'envoi du message:", response['messages'][0]['error-text'])
                            return jsonify({"status": "error", "message": response['messages'][0]['error-text']})
                        return jsonify({"status": "success", "message": "Enregistrement réussi!"})
                    except Exception as e:
                        print("Erreur lors de l'envoi du message via Vonage:", e)
                        return jsonify({"status": "error", "message": str(e)})
                else:
                    return jsonify({"status": "success", "message": "Enregistrement réussi sans envoi de SMS."})
            else:
                print("Lead déjà existant avec ce numéro de téléphone")
                return jsonify({"status": "duplicate", "message": "Lead déjà existant avec ce numéro de téléphone"})
        except Exception as e:
            print(f"Erreur lors de l'interaction avec Google Sheets: {e}")
            return jsonify({"status": "error", "message": f"Erreur lors de l'interaction avec Google Sheets: {e}"})
    else:
        return jsonify({"status": "error", "message": "Erreur de format de requête"})


if __name__ == "__main__":
    app.run(host='0.0.0.0',port=8080,debug=False)

    
