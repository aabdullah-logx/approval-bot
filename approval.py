import time
import traceback
import re
import gspread
import pandas as pd
from oauth2client.client import flow_from_clientsecrets
from oauth2client.file import Storage
from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive
import server
import settings
from oauth2client import tools
import os
import datetime
import access_sc
import pytz
import slack_utils
from dotenv import load_dotenv

import get_totp

# Load environment variables
load_dotenv()

# Get the current working directory
current_directory = os.getcwd()

# Construct the full path to your client_secret.json
CLIENT_SECRETS = os.path.join(current_directory, os.getenv('CLIENT_SECRETS', 'client_secret.json'))

timezone = pytz.timezone(os.getenv('TIMEZONE', 'America/Toronto'))


# Authentication for Google Sheets
def authenticate_gspread():
    SCOPE = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    STORAGE = Storage('sheets_oauth2.dat')

    credentials = STORAGE.get()
    if credentials is None or credentials.invalid:
        flow = flow_from_clientsecrets(CLIENT_SECRETS, scope=SCOPE)
        flags = tools.argparser.parse_args(args=[])
        credentials = tools.run_flow(flow, STORAGE, flags)

    gc = gspread.authorize(credentials)
    return gc

# Authentication for Google Drive
def authenticate_pydrive():
    gauth = GoogleAuth()
    gauth.LoadClientConfigFile(CLIENT_SECRETS)
    gauth.LoadCredentialsFile("drive_oauth2.dat")

    if gauth.credentials is None:
        gauth.LocalWebserverAuth()
    elif gauth.access_token_expired:
        gauth.Refresh()
    else:
        gauth.Authorize()

    gauth.SaveCredentialsFile("drive_oauth2.dat")
    drive = GoogleDrive(gauth)
    return drive

def get_stores():
    gc = authenticate_gspread()
    drive = authenticate_pydrive()
    sh = gc.open("BOT run")
    store = sh.worksheet("stores")
    data = store.get_all_records()
    df = pd.DataFrame(data)
    return df, drive, gc, store

def sheet_exists_in_folder(sheet_name, folder_id, drive):
    query = f"'{folder_id}' in parents and title='{sheet_name}' and trashed=false"
    file_list = drive.ListFile({'q': query}).GetList()
    return len(file_list) > 0

def get_or_create_sheet_in_folder(sheet_name, folder_id, drive):
    # List all files in the folder
    query = f"'{folder_id}' in parents and trashed=false"
    file_list = drive.ListFile({'q': query}).GetList()

    # Check if sheet already exists
    for file in file_list:
        if file['title'] == sheet_name and file['mimeType'] == 'application/vnd.google-apps.spreadsheet':
            return file['id']

    # If sheet not found, create a new one
    file_metadata = {
        'title': sheet_name,
        'parents': [{'id': folder_id}],
        'mimeType': 'application/vnd.google-apps.spreadsheet'
    }
    sheet = drive.CreateFile(file_metadata)
    sheet.Upload()
    return sheet['id']


def create_sheet_in_folder(sheet_name, folder_id, drive):
    file_metadata = {
        'title': sheet_name,
        'parents': [{'id': folder_id}],
        'mimeType': 'application/vnd.google-apps.spreadsheet'
    }
    sheet = drive.CreateFile(file_metadata)
    sheet.Upload()
    return sheet['id']

def extract_file_id_from_url(url):
    try:
        match = re.search(r'/d/([a-zA-Z0-9_-]+)', url)
        if match:
            return match.group(1)
        else:
            raise ValueError(f"Could not extract file ID from URL: {url}")
    except:
        return None


def get_or_create_folder(folder_name, drive, parent_folder_id=None):
    """Get folder ID by name, create if doesn't exist"""
    try:
        # Search for folder
        if parent_folder_id:
            query = f"title='{folder_name}' and mimeType='application/vnd.google-apps.folder' and '{parent_folder_id}' in parents and trashed=false"
        else:
            query = f"title='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        
        file_list = drive.ListFile({'q': query}).GetList()
        
        if file_list:
            return file_list[0]['id']
        
        # Create folder if not found
        folder_metadata = {
            'title': folder_name,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        if parent_folder_id:
            folder_metadata['parents'] = [{'id': parent_folder_id}]
        
        folder = drive.CreateFile(folder_metadata)
        folder.Upload()
        print(f"Created folder: {folder_name}")
        return folder['id']
    except Exception as e:
        print(f"Error getting/creating folder: {e}")
        return None


def upload_file_to_drive(file_path, folder_id, drive):
    """Upload a file to Google Drive folder"""
    try:
        if not os.path.exists(file_path):
            print(f"File not found: {file_path}")
            return None
        
        file_name = os.path.basename(file_path)
        
        # Check if file already exists in folder
        query = f"title='{file_name}' and '{folder_id}' in parents and trashed=false"
        file_list = drive.ListFile({'q': query}).GetList()
        
        if file_list:
            # Update existing file
            file = file_list[0]
            file.SetContentFile(file_path)
            file.Upload()
            print(f"Updated existing file: {file_name}")
        else:
            # Create new file
            file_metadata = {
                'title': file_name,
                'parents': [{'id': folder_id}]
            }
            file = drive.CreateFile(file_metadata)
            file.SetContentFile(file_path)
            file.Upload()
            print(f"Uploaded new file: {file_name}")
        
        return file['id']
    except Exception as e:
        print(f"Error uploading file: {e}")
        return None
    

def set_profile_qr_key(store, drive):
    # print(store)

    url = store['QRCODE']

    if url:
        file_id = extract_file_id_from_url(url)
    else:
        print('URL for TOTP not found')
        return None
    
    if file_id:
        try:
            image = get_totp.download_image_from_gdrive_and_load(file_id, drive)
            # print(image)
            store['qr_key'] = get_totp.generate_qr_key(image)
            print(store['qr_key'])
        except Exception as e:
            print(f'Error: {e}')
            return None

            
    else:
        print('File id in TOTP Link not found')
        return None
    
    return store

def run():
    while True:
        try:
            df, drive, gc, store = get_stores()

            filtered_df = df[(df['run'] == 1) & (df['server'] == server.server) & (df['server'] == server.server)]
            folder_id = settings.folder_id
            
            # Get or create "Bot Approval files" folder in Google Drive
            bot_files_folder_id = get_or_create_folder("Bot Approval files", drive)
            
            if len(filtered_df.index) > 0:

                for index, profile in filtered_df.iterrows():

                    profile = set_profile_qr_key(profile, drive)

                    if profile is not None:

                        worksheet = None
                        df_worksheet = None
                        for x in range(3):  # Let's retry 3 times maximum
                            try:
                                store.update_cell(index + 2, df.columns.get_loc('update') + 1, 'running')
                                current_datetime = datetime.datetime.now(timezone)
                                current_date = current_datetime.strftime('%Y-%m-%d')
                                sheet_name = f"{profile['profile_name']}_{current_date}"
                                
                                # Create or get sheet directly in "Bot Approval files" folder
                                if bot_files_folder_id:
                                    sheet_id = get_or_create_sheet_in_folder(sheet_name, bot_files_folder_id, drive)
                                    sh = gc.open_by_key(sheet_id)
                                    
                                    # Get or create the first worksheet
                                    try:
                                        worksheet = sh.get_worksheet(0)
                                    except:
                                        worksheet = sh.add_worksheet(title="Sheet1", rows="1000000", cols="4")
                                    
                                    # Check if header exists, if not write it
                                    header = worksheet.row_values(1)
                                    if not header or 'ASIN' not in header:
                                        worksheet.insert_row(['ASIN', 'SKU', 'Title', 'Status'], 1)
                                    
                                    records = worksheet.get_all_records()
                                    df_worksheet = pd.DataFrame(records) if records else pd.DataFrame(columns=['ASIN', 'SKU', 'Title', 'Status'])
                                else:
                                    print("Error: Bot Approval files folder not found")
                                    worksheet = None
                                    df_worksheet = None
                                
                                break  # Success, break the retry loop
                            except Exception as e:
                                print(f"Error connecting to Google Sheet/Drive (Attempt {x+1}/3): {e}")
                                time.sleep(5)
                        
                        if worksheet is None:
                            connection_error_msg = f"*Access Alert: {store_name}*\nThe automation bot was unable to establish a connection with Google Sheets. Please verify the spreadsheet permissions and configuration."
                            slack_utils.send_slack_message(connection_error_msg)
                            print(f"Warning: Connection to Google Sheets failed for {store_name}.")

                        # Now process the profile and pass the worksheet handle (which might be None)
                        store_name = profile.get('profile_name', 'Unknown')
                        
                        start_msg = f"*Processing Started: {store_name}*\nThe automation bot has initiated the approval routine for this store."
                        # slack_utils.send_slack_message(start_msg)

                        result_dict = access_sc.process_row(profile, worksheet, df_worksheet)
                        if result_dict.get('success'):
                            success_msg = (
                                f"*Store Completed: {store_name}*\n"
                                f"Processed ASINs: `{result_dict.get('processed', 0)}`\n"
                                f"Skipped (Duplicates): `{result_dict.get('skipped', 0)}`\n"
                                f"Pages Scanned: `{result_dict.get('pages', 1)}`"
                            )
                            slack_utils.send_slack_message(success_msg)
                            
                            for x in range(5):
                                try:
                                    store.update_cell(index + 2, df.columns.get_loc('update') + 1, 'completed')
                                    store.update_cell(index + 2, df.columns.get_loc('run') + 1, 0)
                                    current_datetime = datetime.datetime.now(timezone)
                                    current_datetime_str = current_datetime.strftime('%Y-%m-%d %H:%M:%S')
                                    store.update_cell(index + 2, df.columns.get_loc('complete_on') + 1,
                                                    current_datetime_str)
                                except Exception as e:
                                    print(f"Error marking as completed: {e}")
                                    time.sleep(5)
                                else:
                                    break
                        else:
                            error_details = result_dict.get('error', 'Unknown Error')
                            error_msg = f"*Error in Store: {store_name}*\nBot encountered an error during scraping:\n```{error_details}```"
                            slack_utils.send_slack_message(error_msg)

                print('All tasks completed!')

            else:
                print('Nothing to Process')
                time.sleep(600)
        except Exception as e:
            # time.sleep(30)
            print("An exception occurred:", e)
            traceback.print_exc()
            try:
                slack_utils.send_slack_message(f"*Critical System Failure: `approval.py`*\nThe bot experienced a critical crash during execution:\n```{str(e)}```")
            except:
                pass


def main():
    while True:
        run()

if __name__ == '__main__':
    main()
