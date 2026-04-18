import os
import gspread
import google.auth
import logging
from datetime import datetime

# Configure logging
logger = logging.getLogger(__name__)

def update_or_append_gsheet(spreadsheet_id, sheet_gid, data_row):
    try:
        logger.info("Connecting to Google Sheets...")
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds, _ = google.auth.default(scopes=scopes)
        client = gspread.authorize(creds)
        
        spreadsheet = client.open_by_key(spreadsheet_id)
        sheet = spreadsheet.get_worksheet_by_id(sheet_gid)
        
        today_date = datetime.now().strftime("%d/%m/%Y")
        data_row[0] = today_date
        
        # Check if today's row exists
        cell = sheet.find(today_date, in_column=1)
        if cell:
            logger.info(f"Updating existing row for {today_date}...")
            # Use value_input_option='USER_ENTERED' to ensure proper date parsing without prepended quotes
            sheet.update(range_name=f"A{cell.row}:E{cell.row}", values=[data_row], value_input_option='USER_ENTERED')
        else:
            logger.info(f"Appending new row for {today_date}...")
            sheet.append_row(data_row, value_input_option='USER_ENTERED')
        
        logger.info("Successfully updated Google Sheets!")
        return True
    except Exception as e:
        logger.error(f"Error occurred during Google Sheets upload: {e}")
        return False
