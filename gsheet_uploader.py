import gspread
import gspread.exceptions
import google.auth
import logging

# Configure logging
logger = logging.getLogger(__name__)

def upload_to_gsheet(spreadsheet_id, sheet_gid, data_row):
    try:
        logger.info("Connecting to Google Sheets...")
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds, _ = google.auth.default(scopes=scopes)
        client = gspread.authorize(creds)
        
        spreadsheet = client.open_by_key(spreadsheet_id)
        sheet = spreadsheet.get_worksheet_by_id(sheet_gid)
        
        sheet.append_row(data_row, value_input_option='RAW')
        logger.info("Successfully appended row to Google Sheets!")
        return True
    except gspread.exceptions.SpreadsheetNotFound:
        logger.error(f"Google Sheet not found (404 Error).")
        logger.error(f"Please verify SPREADSHEET_ID '{spreadsheet_id}' in your .env file.")
        logger.error("Crucial: Ensure the sheet is shared with your Google Cloud Service Account email!")
        return False
    except Exception as e:
        logger.error(f"Error occurred during Google Sheets upload: {e}")
        return False
