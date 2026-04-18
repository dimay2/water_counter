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
            
            # Service fields mapping to GSheet columns H-P (indices 7-15)
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
            
            # Start from Column H (index 7), so padding is needed if len(data_row) < 7
            while len(data_row) < 7:
                data_row.append("")
                
            for service in service_map:
                data_row.append(rumyantsevo.get(service, "0"))
            
            # Column Q: Value of previous row (index 16), Column R: Formula (=SUM(H<row>:Q<row>))
            all_values = sheet.get_all_values()
            
            # Determine the current row number for the formula (target_row will be set later, so calculate it here)
            # If cell exists (update), target_row = cell.row. If appending, target_row = len(all_values) + 1
            today_date = datetime.now().strftime("%d/%m/%Y")
            cell = sheet.find(today_date, in_column=1)
            target_row = cell.row if cell else len(all_values) + 1
            
            # Column Q: Keep previous row's value
            if len(all_values) > 0:
                last_row = all_values[-1]
                data_row.append(last_row[16] if len(last_row) > 16 else "") # Q
            else:
                data_row.append("")
                
            # Column R: Formula =SUM(H<row>:Q<row>)
            data_row.append(f"=SUM(H{target_row}:Q{target_row})")

        # Check if today's row exists
        cell = sheet.find(today_date, in_column=1)
        if cell:
            logger.info(f"Updating existing row for {today_date}...")
            range_to_update = f"A{cell.row}:R{cell.row}"
            sheet.update(range_name=range_to_update, values=[data_row], value_input_option='USER_ENTERED')
            target_row = cell.row
        else:
            logger.info(f"Appending new row for {today_date}...")
            sheet.append_row(data_row, value_input_option='USER_ENTERED')
            target_row = len(sheet.get_all_values())
            
        # Apply right alignment to the entire row (Columns A-R)
        sheet.format(f"A{target_row}:R{target_row}", {"horizontalAlignment": "RIGHT"})
        
        logger.info("Successfully updated Google Sheets!")
        return True
    except Exception as e:
        logger.error(f"Error occurred during Google Sheets upload: {e}")
        return False
