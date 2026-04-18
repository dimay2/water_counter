import os
import gspread
import google.auth
import logging
import json
from datetime import datetime

# Configure logging
logger = logging.getLogger(__name__)

def update_or_append_gsheet(spreadsheet_id, sheet_gid, data_row, ingestion_data=None):
    try:
        logger.info("Connecting to Google Sheets...")
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds, _ = google.auth.default(scopes=scopes)
        client = gspread.authorize(creds)
        
        spreadsheet = client.open_by_key(spreadsheet_id)
        sheet = spreadsheet.get_worksheet_by_id(sheet_gid)
        
        today_date = datetime.now().strftime("%d/%m/%Y")
        data_row[0] = today_date
        
        # If ingestion_data is provided, append additional service fields
        if ingestion_data and "Rumyantsevo" in ingestion_data:
            rumyantsevo = ingestion_data["Rumyantsevo"]
            # Ordering: H-P (indices 7-15)
            # - H: "Содержание и техническое обслуживание помещений"
            # - I: "Обращение с ТКО"
            # - J: "Холодное водоснабжение"
            # - K: "Холодная вода для ГВС"
            # - L: "Теплоэнергия для ГВС"
            # - M: "Водоотведение"
            # - N: "Отопление"
            # - O: "Охрана и мониторинг ЖК"
            # - P: "Электроснабжение для СОИ:"
            service_map = [
                "Содержание и техническое обслуживание помещений",
                "Обращение с ТКО",
                "Холодное водоснабжение",
                "Холодная вода для ГВС",
                "Теплоэнергия для ГВС",
                "Водоотведение",
                "Отопление",
                "Охрана и мониторинг ЖК",
                "Электроснабжение для СОИ:"
            ]
            for service in service_map:
                data_row.append(rumyantsevo.get(service, "0"))
            
            # Column Q: Value of previous row
            # Column R: Formula from previous row
            
            # Simple logic to get last row data if it exists
            all_values = sheet.get_all_values()
            if len(all_values) > 1:
                last_row = all_values[-1]
                data_row.append(last_row[16]) # Q (index 16)
                data_row.append(last_row[17]) # R (index 17)
            else:
                data_row.extend(["", ""])

        # Check if today's row exists
        cell = sheet.find(today_date, in_column=1)
        if cell:
            logger.info(f"Updating existing row for {today_date}...")
            sheet.update(range_name=f"A{cell.row}", values=[data_row], value_input_option='USER_ENTERED')
        else:
            logger.info(f"Appending new row for {today_date}...")
            sheet.append_row(data_row, value_input_option='USER_ENTERED')
        
        logger.info("Successfully updated Google Sheets!")
        return True
    except Exception as e:
        logger.error(f"Error occurred during Google Sheets upload: {e}")
        return False
