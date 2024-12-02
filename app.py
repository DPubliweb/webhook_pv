import json
import os
from flask import Flask, request, jsonify
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import nexmo
from dotenv import load_dotenv

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

# Initialisation globale du client Vonage
client_vonage = nexmo.Client(key=KEY_VONAGE, secret=KEY_VONAGE_SECRET)
clientInterests = {
            'André': [56,22,35,14,61,53,72,49,44,85,79,86,16,17,87,23,18,36,41,45,28,37,27,76,80,2,60,55,54,57,88,68,67,70,90,25,39,71,21,89,58,42,84,82,81,31,32,65,9,66,11,48,63,43,12,47,30,8,51,10,52,19,3],
            #'Yoel A': [44,49,72,53,85,17,79,43,48,12],
            'Yoel N' : [67,68,88,54,57,55,52,70,25,21],
            #'Yoel NG': [3,42,43,63],
            'Dan Amsellem': [45,28,89,51,10,27],
            #'Daniel Zerdoun' : [54,55,57,67,68,88],
            #'Laurent Berdugo ': [54,55,57,51,10,52,],
            'Benjamin Bohbot': [3,16,19,22,23,25,35,36,37,53,56,70,71,72,86,87],
            #'Dorian Lancry': [1,21,20,70,71,39,90,58,89,],
            #'Samy OC': [36,37,18,41],            
            #'Dan Amsellem DB': [28,45,89,10,41,18],
            #'Maximilien Taieb': [83, 13, 84, 4, 6,5, 30, 34, 48, 15, 12, 46, 19, 23, 36, 18, 58, 71, 39, 25, 3, 63, 15, 42, 43, 69, 7, 1, 38, 26, 74, 73],
            #Yoel AU': [44,49,79,85],
            #'Laurent Berdugo Z2': [44,49,72,53,85,17,79,86,12,43,48],            
            #'Menahem Aouizerat': [33,44,49,53,72,79,85,86],
            'Axel Zarka': [14,50,61,27,76,59]
            #'Zak Sebban': [14,61,76,27,28,60,80,2,59,62,51,10,8],
            #'Yoel N': [54,57,67,68,88],
            'Gary Cohen': [30,34,38,69,6,31],
            #'Yoel TB': [46,12,81,11,34,30,48],
            #'Yoel A2': [55,88,36,37,41,45,18,59,62,14,50,61],
            #'Mickael Perez': [44,49,59,80,62,60,77,78,91,92,93,94,95],
            #'Samy Naccache GB': [44,49,85],
            #'Samy Nackache YP': [36,37,41,81,87,19,23,15,46],
            #'Samy Nackache SO': [59,62,80,2,60],
            #'Samy Naccache PS' : [34,11,30,66,13,84],
            'Samy Nackache CL': [54,55,57,67,68,88,52,70,90],
        }

@app.route('/leads_pv', methods=['GET', 'POST'])
def webhook_leads_pv():
    global client
    print('arrived lead')

    if request.headers['Content-Type'] == 'application/json':
        json_tree = json.loads(request.data)
        phone = json_tree["form_response"]["hidden"]["telephone"]
        nom = json_tree["form_response"]["hidden"]["nom"]
        prenom = json_tree["form_response"]["hidden"]["prenom"]
        email = json_tree["form_response"]["hidden"]["email"]
        cohort = ""
        zipcode = json_tree["form_response"]["hidden"]["code_postal"]
        civilite = json_tree["form_response"]["hidden"]["civilite"]
        utm_source = json_tree["form_response"]["hidden"]["utm_source"]
        code = json_tree["form_response"]["hidden"]["code"]
        date = json_tree["form_response"]["submitted_at"]
        
        # Conversion et formatage de la date
        date_obj = datetime.strptime(date, "%Y-%m-%dT%H:%M:%SZ")
        date_sliced = date_obj.strftime("%d-%m-%Y %H:%M")

        form_list = json_tree['form_response']['answers']
        type_habitation = form_list[0]['choice']['label']
        statut_habitation = form_list[1]['choice']['label']
        print("téléphone: ", phone , date_sliced)

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
                sheet.update(f'A{next_row}:N{next_row}', [[type_habitation, statut_habitation, civilite, nom, prenom, phone, email, zipcode, code, utm_source, cohort, date_sliced, department, ", ".join(interested_clients)]])
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
                            'text': f'Bonjour {prenom} {nom}\nMerci pour votre demande\nUn conseiller vous recontactera sous 24h à 48h\n\nPour sécuriser votre parcours, veuillez noter votre code dossier {code}. Pour annuler votre RDV, cliquez ici: https:://vvs.bz/annulationPVML'
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
                sheet.update(f'A{next_row}:N{next_row}', [[type_habitation, statut_habitation, civilite, nom, prenom, phone, email, zipcode, code, utm_source, cohort, date_time, department, ", ".join(interested_clients)]])
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

    
