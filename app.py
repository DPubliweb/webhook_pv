import json
import os
from flask import Flask, flash, request, redirect, render_template, send_file, url_for, make_response, after_this_request, jsonify
import pandas as pd
import boto3
import csv
import io
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from google.oauth2.credentials import Credentials
import google.auth
from gspread import Cell
import nexmo
from datetime import datetime
import xml.etree.ElementTree as ET
import hashlib
import requests


from dotenv import load_dotenv

app = Flask(__name__)

scope = ['https://www.googleapis.com/auth/spreadsheets',
         "https://www.googleapis.com/auth/drive"]

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

client = gspread.authorize(creds)

client_vonage = nexmo.Client(
    key=KEY_VONAGE, secret=KEY_VONAGE_SECRET
)


@app.route('/leads_pv', methods=['GET', 'POST'])
def webhook_leads_pv():
    print('arrived lead')

    if request.headers['Content-Type'] == 'application/json':
        json_tree = json.loads(request.data)
        phone = json_tree["form_response"]["hidden"]["telephone"]
        nom = json_tree["form_response"]["hidden"]["nom"]
        prenom = json_tree["form_response"]["hidden"]["prenom"]
        email = json_tree["form_response"]["hidden"]["email"]
        cohort = json_tree ["form_response"]["hidden"]["cohort"]
        zipcode = json_tree["form_response"]["hidden"]["code_postal"]
        utm_source = json_tree["form_response"]["hidden"]["utm_source"]
        code = json_tree["form_response"]["hidden"]["code"]
        date = json_tree["form_response"]["submitted_at"]
        date_sliced = date[:10]
        form_list = json_tree['form_response']['answers']
        first_question = form_list[0]
        type_habitation = first_question['choice']['label']
        second_question = form_list[1]
        statut_habitation = second_question['choice']['label']
        #third_question = form_list[2]
        #chauffage = third_question['choice']['label']
        date_sliced = date[0:10]
        print("téléphone: ", phone , date_sliced)

        sheet = client.open("Panneaux Solaires - Publiweb").sheet1
        all_values = sheet.get_all_values()
        existing_phones = [row[5] for row in all_values]
        if phone not in existing_phones :
            sheet.append_row([type_habitation, statut_habitation, nom, prenom, phone, email,zipcode,code, utm_source, cohort, date])
            print("Nouveau lead inscrit")
        try:
            response = client_vonage.send_message({'from': 'RDV TEL', 'to': phone , 'text': 'Bonjour '+ prenom +' '+nom+'\nMerci pour votre demande\nUn conseiller vous recontactera sous 24h à 48h\n\nPour sécuriser votre parcours, veuillez noter votre code dossier '+code+' Pour annuler votre RDV, cliquez ici: https://aud.vc/annulationPVML'})
            print("Réponse de Vonage:", response)  # Log pour la réponse de Vonage
            
            if response['messages'][0]['status'] != '0':
                print("Erreur lors de l'envoi du message:", response['messages'][0]['error-text'])
            return "Enregistrement réussi!"
        except Exception as e:
            print("Erreur lors de l'envoi du message via Vonage:", e)
            return str(e)
    else:
        return "Erreur de format de requête"
    


@app.route('/leads_desinscription_pv', methods=['GET', 'POST'])
def webhook_leads_desinscription_pv():
    print('desinscription pv')
    

    if request.headers['Content-Type'] == 'application/json':
        json_tree = json.loads(request.data)
        form_list = json_tree['form_response']['answers']
        first_question = form_list[0]
        if form_list and form_list[0]['type'] == 'phone_number':
            phone_with_plus = form_list[0]['phone_number']
            phone_without_plus = phone_with_plus.lstrip('+')

        sheet = client.open("Panneaux Solaires - Publiweb").sheet1
        all_values = sheet.get_all_values()
        row_number = None
        for index, row in enumerate(all_values):
                if row[5] == phone_without_plus:  # L'indexation commence à 0, donc la 5ème colonne est à l'index 4
                    row_number = index + 1  # L'indexation dans les Google Sheets commence à 1
                    break
            
        # Si le numéro est trouvé, mettre à jour la cellule correspondante dans la colonne J (10ème colonne)
        if row_number:
            sheet.update_cell(row_number, 10, "DÉSINSCRIT")  # La colonne J est la 10ème colonneeets commence à 1, tandis que l'indexation des listes en Python commence à 0.
        else: 
            print('Numéro à désinscrire non trouvé')
        return "Done"
    else:
        return 'Not there'

    
if __name__ == "__main__":
    app.run(host='0.0.0.0',port=8080,debug=False)

    