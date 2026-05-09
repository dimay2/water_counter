import os
import gspread
import google.auth
import logging
import json
from datetime import datetime
import re

# Configure logging
logger = logging.getLogger(__name__)

def col_to_idx(col_letter):
    if not col_letter: return None
    return ord(col_letter.upper()) - ord('A')

def get_last_readings(spreadsheet_id, sheet_gid, meter_idx=None):
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds, _ = google.auth.default(scopes=scopes)
        client = gspread.authorize(creds)
        
        spreadsheet = client.open_by_key(spreadsheet_id)
        sheet = spreadsheet.get_worksheet_by_id(sheet_gid)
        
        all_values = sheet.get_all_values()
        if not all_values:
            return None
        
        # Traverse rows backwards to find the latest valid row for the meter
        if meter_idx is not None:
            # We want to find a row where the meter has a non-empty, non-zero value
            for i in range(len(all_values) - 1, -1, -1):
                row = all_values[i]
                if meter_idx >= len(row):
                    continue # Column doesn't even exist in this row
                val = row[meter_idx].strip()
                if not val:
                    continue
                # Check if it's a valid number and > 0
                try:
                    num_val = float(val)
                    if num_val > 0:
                        # Return (Date, Value)
                        return (row[0], str(num_val))
                except (ValueError, TypeError):
                    continue
            return None # Not found
        else:
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
        
        # --- DEBUG LOGS START ---
        logger.info(f"DEBUG: Initial len(all_values) = {len(all_values)}")
        logger.info(f"DEBUG: Cell found for today_date: {cell.row if cell else 'None'}")
        # --- DEBUG LOGS END ---
        
        target_row = cell.row if cell else None # Initialize to None if not updating existing
        
        # If appending (cell is None), find the last non-empty row to get the actual next row number
        if target_row is None:
            last_non_empty_row_index = -1 # 0-indexed
            for i in range(len(all_values) - 1, -1, -1):
                if any(cell_value.strip() for cell_value in all_values[i]):
                    last_non_empty_row_index = i
                    break
            
            # The target row for appending is 1-indexed: last_non_empty_row_index + 1 (to convert to 1-indexed) + 1 (for the next new row)
            # If no non-empty rows found, it means sheet is completely empty, so start at row 1
            target_row = (last_non_empty_row_index + 2) if last_non_empty_row_index != -1 else 1

        # --- DEBUG LOGS START ---
        logger.info(f"DEBUG: Determined target_row = {target_row}")
        # --- DEBUG LOGS END ---
        
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

        # 5. Formula
        formula_col_letter = cols.get("formula")
        if formula_col_letter:
            formula_idx = col_to_idx(formula_col_letter)
            
            if location == "Rumyantsevo":
                # Specific Rumyantsevo logic: SUM of columns B to Q for the current row
                data_row[formula_idx] = f"=SUM(B{target_row}:Q{target_row})"
                logger.info(f"Rumyantsevo: Generated formula for column {formula_col_letter}: {data_row[formula_idx]}")
            elif location == "Tashkentskiy":
                # Specific Tashkentskiy logic: SUM of columns H to O for the current row
                data_row[formula_idx] = f"=SUM(H{target_row}:O{target_row})"
                logger.info(f"Tashkentskiy: Generated formula for column {formula_col_letter}: {data_row[formula_idx]}")
            else: # This block will now handle any other locations with generic replication
                # --- GENERIC FORMULA REPLICATION LOGIC ---
                # Check if there's a previous row to copy a formula from
                if target_row > 1 and len(all_values) >= target_row - 1: # all_values is 0-indexed, so target_row-2 is previous 0-indexed row
                    prev_row_values = all_values[target_row - 2] 
                    if formula_idx is not None and formula_idx < len(prev_row_values):
                        prev_formula = prev_row_values[formula_idx]
                        
                        if prev_formula.startswith("="): # Only replicate if previous cell contained a formula
                            # Adjust all row numbers in the formula to the current target_row
                            adjusted_formula = re.sub(r'\d+', str(target_row), prev_formula)
                            data_row[formula_idx] = adjusted_formula
                            logger.info(f"{location}: Replicated and adjusted formula for column {formula_col_letter}: {adjusted_formula}")
                        else:
                            # If previous cell was not a formula, leave current cell empty (or initial state)
                            logger.info(f"{location}: Previous cell in column {formula_col_letter} was not a formula. Leaving current cell empty.")
                    else:
                        logger.warning(f"{location}: Column {formula_col_letter} index out of bounds for previous row. Leaving current cell empty.")
                else:
                    # If it's the first data row (target_row == 1), there's no previous formula to copy.
                    logger.warning(f"{location}: No previous row to copy formula from. Leaving formula column empty.")
                # --- END GENERIC FORMULA REPLICATION LOGIC ---

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

def get_previous_meter_readings_for_rumyantsevo_meters(spreadsheet_id, sheet_gid, profile_columns):
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds, _ = google.auth.default(scopes=scopes)
        client = gspread.authorize(creds)
        
        spreadsheet = client.open_by_key(spreadsheet_id)
        sheet = spreadsheet.get_worksheet_by_id(sheet_gid)
        
        all_values = sheet.get_all_values()
        if not all_values:
            return None
        
        last_row = all_values[-1]
        
        meter_cols = profile_columns["meters"] # ["B", "C", "D", "E"]
        
        # Initialize with None or default values
        kitchen_prev_left = 0
        kitchen_prev_right = 0
        bathroom_prev_left = 0
        bathroom_prev_right = 0
        
        # Map column letters to indices and retrieve values
        # Assuming meter_cols are always in order B, C, D, E
        if len(meter_cols) > 0:
            idx = col_to_idx(meter_cols[0]) # Column B for kitchen.left
            if idx is not None and idx < len(last_row):
                kitchen_prev_left = int(float(last_row[idx])) if last_row[idx].strip() else 0
        if len(meter_cols) > 1:
            idx = col_to_idx(meter_cols[1]) # Column C for kitchen.right
            if idx is not None and idx < len(last_row):
                kitchen_prev_right = int(float(last_row[idx])) if last_row[idx].strip() else 0
        if len(meter_cols) > 2:
            idx = col_to_idx(meter_cols[2]) # Column D for bathroom.left
            if idx is not None and idx < len(last_row):
                bathroom_prev_left = int(float(last_row[idx])) if last_row[idx].strip() else 0
        if len(meter_cols) > 3:
            idx = col_to_idx(meter_cols[3]) # Column E for bathroom.right
            if idx is not None and idx < len(last_row):
                bathroom_prev_right = int(float(last_row[idx])) if last_row[idx].strip() else 0
                
        return {
            "kitchen": {
                "prev_left": kitchen_prev_left,
                "prev_right": kitchen_prev_right
            },
            "bathroom": {
                "prev_left": bathroom_prev_left,
                "prev_right": bathroom_prev_right
            }
        }
    except Exception as e:
        logger.error(f"Error fetching previous meter readings for Rumyantsevo: {e}")
        return None