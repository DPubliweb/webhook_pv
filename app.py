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
        cohort = json_tree["form_response"]["hidden"]["cohort"]
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
        clientInterests = {
            'André': [  67,68,21,58,71,89,22, 29, 35, 56,18,28,36,37,41,45,8, 10, 51,52,25,39,70,90,77,78,91,92,93,94,95,19,23,87,54, 55, 57,88,59,62,14,50,61,27, 76,44,49,53,72,85,2,60,80,16,17,79,86,11,30,34,66,33,9,32,31,65,81,82,1,7,26,38,42,13,83,84],
            'Benjamin Bohbot' : [16,17,19,21,22,23,29,35,53,56,58,71,79,86,87],
            'Samy Nackache CL': [54,55,57,67,68,88,52,70,90],
            'Yoel A': [44,49,72,53,85,17,79,86,48],
            'Yoel NG' : [3, 42, 43, 63, 31, 32, 81, 82],
            'Yoel SZ': [21,71,63,3,37,41,44,49,53,72],
            'Yoel BJ1': [25,39,52,54,55,57,67,68,70,88,90],
            'Yoel BJ': [87, 19, 23, 86, 36, 51, 8,  27, 28, 76, 57, 54, 68, 67, 88 ],            
            'Dan Amsellem': [28,45,89,10,51,61,72,27,41],
            'Ruben Nadjar' : [21,71,58,70,25,27,76,11,66,26,64,65],
            'Laurent Berdugo Z1': [49, 44, 72, 53, 28, 41, 37, 61, 35, 79, 85, 86],
            'Laurent Berdugo Z2': [44,49,53,72,21,71,63,3,37,41],            
            'Jeremy Benattar': [13,84,83,6,30,34],
            'Ruben Nadjar': [21,71,58,70,25,27,76,11,66,26,64,65]
            #'Zak Sebban': [14,61,76,27,28,60,80,2,59,62,51,10,8],
            #'Yoel N': [54,57,67,68,88],
            #Emmanuel Toubiana Z2': [24,33,40,47],
            #'Yoel TB': [46,12,81,11,34,30,48],
            #'Yoel A2': [31,32,81,82],
            #'Mickael Perez': [44,49,59,80,62,60,77,78,91,92,93,94,95],
            #'SN GR': [29,22,56,35,13,84,4,83,33,47],
            #'Samy Nackache SO': [59,62,80,2,60],
            #'Samuel Labiod': [22, 29,35,78],
            #'Dan Amsellem DB': [28,45,89,10,41,18],
            #'Maximilien Taieb': [83, 13, 84, 4, 6,5, 30, 34, 48, 15, 12, 46, 19, 23, 36, 18, 58, 71, 39, 25, 3, 63, 15, 42, 43, 69, 7, 1, 38, 26, 74, 73],
            #Yoel AU': [44,49,79,85],
        }

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
                            'text': f'Bonjour {prenom} {nom}\nMerci pour votre demande\nUn conseiller vous recontactera sous 24h à 48h\n\nPour sécuriser votre parcours, veuillez noter votre code dossier {code}. Pour annuler votre RDV, cliquez ici: https:,/aud.vc/annulationPVML'
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
    
if __name__ == "__main__":
    app.run(host='0.0.0.0',port=8080,debug=False)

    
