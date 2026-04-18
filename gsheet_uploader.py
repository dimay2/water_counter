import gspread
import gspread.exceptions
import google.auth
import logging
from datetime import datetime

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
        
        # Prepare data with properly formatted date
        data_row[0] = datetime.now().strftime("%d/%m/%Y")
        
        # Append row using USER_ENTERED to allow Google Sheets to parse the date string
        sheet.append_row(data_row, value_input_option='USER_ENTERED')
        
        # Apply formatting from the row above
        values = sheet.get_all_values()
        num_rows = len(values)
        if num_rows > 2:
            # Copy format from row (num_rows - 1) to new row (num_rows)
            # copy_format(source_range, destination_range)
            source_range = f"A{num_rows - 1}:E{num_rows - 1}"
            dest_range = f"A{num_rows}:E{num_rows}"
            sheet.copy_format(source_range, dest_range)
        
        logger.info("Successfully appended row and copied format from preceding row.")
        return True
    except gspread.exceptions.SpreadsheetNotFound:
        logger.error(f"Google Sheet not found (404 Error).")
        logger.error(f"Please verify SPREADSHEET_ID '{spreadsheet_id}' in your .env file.")
        logger.error("Crucial: Ensure the sheet is shared with your Google Cloud Service Account email!")
        return False
    except Exception as e:
        logger.error(f"Error occurred during Google Sheets upload: {e}")
        return False
