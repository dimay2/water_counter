import os
import gspread
import google.auth
import logging
import json
from datetime import datetime

# Configure logging
logger = logging.getLogger(__name__)

def col_to_idx(col_letter):
    if not col_letter: return None
    return ord(col_letter.upper()) - ord('A')

def get_last_readings(spreadsheet_id, sheet_gid):
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds, _ = google.auth.default(scopes=scopes)
        client = gspread.authorize(creds)
        
        spreadsheet = client.open_by_key(spreadsheet_id)
        sheet = spreadsheet.get_worksheet_by_id(sheet_gid)
        
        all_values = sheet.get_all_values()
        if not all_values:
            return None
        
        # Traverse rows backwards to find the last populated reading
        # We assume the last row with non-empty meter values is the last valid one.
        for row in reversed(all_values):
            # Check if any meter column (col 1-6) is populated
            if any(val and val != "0" and val != "" for val in row[1:7]):
                return row
        return all_values[-1]
    except Exception as e:
        logger.error(f"Error fetching last readings: {e}")
        return None

def update_or_append_gsheet(spreadsheet_id, sheet_gid, location, profile, results_list, ingestion_data=None):
    try:
        logger.info(f"Connecting to Google Sheets for {location}...")
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds, _ = google.auth.default(scopes=scopes)
        client = gspread.authorize(creds)
        
        spreadsheet = client.open_by_key(spreadsheet_id)
        sheet = spreadsheet.get_worksheet_by_id(sheet_gid)
        
        all_values = sheet.get_all_values()
        today_date = datetime.now().strftime("%d/%m/%Y")
        
        # Check if today's row exists
        cell = sheet.find(today_date, in_column=1)
        target_row = cell.row if cell else len(all_values) + 1
        
        # Determine max index needed
        cols = profile["columns"]
        max_idx = 0
        for key, val in cols.items():
            if isinstance(val, list):
                for c in val:
                    max_idx = max(max_idx, col_to_idx(c))
            elif val:
                max_idx = max(max_idx, col_to_idx(val))
        
        data_row = [""] * (max_idx + 1)
        
        # 1. Date
        data_row[col_to_idx(cols["date"])] = today_date
        
        # 2. Meters
        meter_cols = cols["meters"]
        for i, val in enumerate(results_list):
            if i < len(meter_cols):
                data_row[col_to_idx(meter_cols[i])] = str(val)
                
        # 3. Services (from ingestion_data)
        if ingestion_data and location in ingestion_data:
            loc_data = ingestion_data[location]
            service_cols = cols.get("services", [])
            service_keys = profile.get("service_keys", [])
            
            # Map services in order to service_cols
            for i, service_name in enumerate(service_keys):
                if i < len(service_cols):
                    data_row[col_to_idx(service_cols[i])] = str(loc_data.get(service_name, "0"))
                    
        # 4. Previous value (Q)
        prev_col = cols.get("previous_val")
        if prev_col:
            prev_idx = col_to_idx(prev_col)
            if len(all_values) > 0:
                last_row = all_values[-1]
                data_row[prev_idx] = last_row[prev_idx] if len(last_row) > prev_idx else ""

        # 5. Formula (R)
        formula_col = cols.get("formula")
        if formula_col:
            # For Rumyantsevo: =SUM(H<row>:Q<row>)
            # Let's generalize: SUM from first service to previous_val
            first_service_col = cols["services"][0]
            last_sum_col = cols["previous_val"]
            data_row[col_to_idx(formula_col)] = f"=SUM({first_service_col}{target_row}:{last_sum_col}{target_row})"

        if cell:
            logger.info(f"Updating existing row for {today_date} at row {target_row}...")
            range_to_update = f"A{target_row}:{chr(ord('A') + max_idx)}{target_row}"
            sheet.update(range_name=range_to_update, values=[data_row], value_input_option='USER_ENTERED')
        else:
            logger.info(f"Appending new row for {today_date}...")
            sheet.append_row(data_row, value_input_option='USER_ENTERED')
            
        # Apply right alignment
        sheet.format(f"A{target_row}:{chr(ord('A') + max_idx)}{target_row}", {"horizontalAlignment": "RIGHT"})
        
        logger.info("Successfully updated Google Sheets!")
        return True
    except Exception as e:
        logger.error(f"Error occurred during Google Sheets upload: {e}")
        return False
