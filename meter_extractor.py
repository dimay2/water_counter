import os
import json
import logging
from datetime import datetime
from PIL import Image
from pydantic import BaseModel
from pdf_extractor import parse_rumyantsevo_pdf, parse_tashkentskiy_pdf
from gemini_utils import call_gemini_with_retry
from prompt_utils import load_prompts

# Configure logging
logger = logging.getLogger(__name__)

MODELS_CACHE_FILE = 'working_models.json'
DATA_INGESTION_FILE = 'data_for_ingestion.json'

class MeterReadings(BaseModel):
    meter_1: str
    meter_2: str

_CACHED_MODELS_TO_TRY = None

def load_cached_models():
    if os.path.exists(MODELS_CACHE_FILE):
        try:
            with open(MODELS_CACHE_FILE, 'r') as f:
                models = json.load(f)
                if isinstance(models, list) and len(models) > 0:
                    return models
        except Exception as e:
            logger.warning(f"Could not read {MODELS_CACHE_FILE}: {e}")
    return []

def save_ingestion_data(data):
    try:
        with open(DATA_INGESTION_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.warning(f"Could not write {DATA_INGESTION_FILE}: {e}")

def load_ingestion_data():
    if os.path.exists(DATA_INGESTION_FILE):
        try:
            with open(DATA_INGESTION_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not read {DATA_INGESTION_FILE}: {e}")
    return {}

def process_location(location: str, client, profiles):
    ingestion_data = load_ingestion_data()
    pdf_dir = os.path.join('Input_data', location)
    
    global _CACHED_MODELS_TO_TRY
    if _CACHED_MODELS_TO_TRY is None:
        _CACHED_MODELS_TO_TRY = load_cached_models()
    model_name = _CACHED_MODELS_TO_TRY[0]

    if os.path.exists(pdf_dir):
        loc_data = ingestion_data.setdefault(location, {})
        
        # Force re-processing if no utility charges found in data
        required_keys = []
        if location == "Tashkentskiy":
             required_keys = ["ХВС КПУ", "ГВС КПУ", "Водоотв. КПУ", "Отоп.эн.пл.", "Содержание ТКО", "Запирающее устройство", "Газ"]
        elif location == "Rumyantsevo":
             required_keys = ["Холодное водоснабжение", "Холодная вода для ГВС", "Водоотведение"]
        
        logger.debug(f"[{location}] Before initial refresh_pdf check: loc_data keys={list(loc_data.keys())}, required_keys={required_keys}")
        logger.debug(f"[{location}] Initial all(key in loc_data for key in required_keys) is {all(key in loc_data for key in required_keys)}")
        if not all(key in loc_data for key in required_keys):
            loc_data["refresh_pdf"] = True

        if loc_data.get("refresh_pdf") is not True:
            logger.info(f"PDF data for {location} is already up to date. Skipping parsing.")
        else:
            parser_type = profiles[location]["pdf_parser"]
            for filename in os.listdir(pdf_dir):
                if filename.lower().endswith('.pdf'):
                    pdf_path = os.path.join(pdf_dir, filename)
                    logger.info(f"Processing PDF: {pdf_path}")
                    if parser_type == "rumyantsevo":
                        pdf_data = parse_rumyantsevo_pdf(pdf_path, client, model_name)
                    elif parser_type == "tashkentskiy":
                        pdf_data = parse_tashkentskiy_pdf(pdf_path, client, model_name)
                    
                    if pdf_data:
                        # Fix: Handle if pdf_data is a list of dicts
                        if isinstance(pdf_data, list):
                            for d in pdf_data:
                                if isinstance(d, dict):
                                    loc_data.update(d)
                        else:
                            loc_data.update(pdf_data)
                        
                        # Only set refresh_pdf to False if all keys are present and no zero values
                        has_zero_values = False
                        zero_keys = []
                        
                        # Gather keys to check
                        keys_to_check = {}
                        if isinstance(pdf_data, list):
                            for d in pdf_data:
                                if isinstance(d, dict):
                                    keys_to_check.update(d)
                        else:
                            keys_to_check = pdf_data

                        for k, v in keys_to_check.items():
                            val_str = str(v).strip()
                            if val_str == "0" or val_str == "0.0" or val_str == "":
                                has_zero_values = True
                                zero_keys.append(k)

                        logger.debug(f"[{location}] After PDF parsing and before final refresh_pdf check: loc_data keys={list(loc_data.keys())}, has_zero_values={has_zero_values}")
                        logger.debug(f"[{location}] Final all(key in loc_data for key in required_keys) is {all(key in loc_data for key in required_keys)}")

                        if has_zero_values:
                            logger.error(f"PDF extraction error: detected '0' or empty values for fields {zero_keys} in {location}")
                            loc_data["refresh_pdf"] = True
                        elif all(key in loc_data for key in required_keys):
                            loc_data["refresh_pdf"] = False
                        
                        save_ingestion_data(ingestion_data)
                        logger.info(f"Updated {location} from {filename}")
                        logger.info(f"Parsed values from {filename} for {location}: {pdf_data}")
                    else:
                        logger.warning(f"PDF parsing returned no data for {location}. Keeping refresh_pdf=True.")
                        loc_data["refresh_pdf"] = True
                        save_ingestion_data(ingestion_data)
        
        logger.info(f"Final parsed PDF data for {location}: {loc_data}")

def extract_room_meters(location: str, room: str, img_path: str, client, profiles, logic="default", prev_date=None, prev_val=0, use_cache=True) -> dict:
    if not os.path.exists(img_path):
        logger.error(f"Image not found: {img_path}")
        return {"left": 0, "right": 0}

    ingestion_data = load_ingestion_data()
    loc_data = ingestion_data.get(location, {})
    room_data = loc_data.get(room, {})

    today = datetime.now().strftime("%Y%m%d")
    today_dt = datetime.now()

    # Check if we already have data for today's date
    if use_cache and room_data.get("date") == today and not room_data.get("refresh", False):
        logger.info(f"Cache hit for {location}.{room} on {today}. Skipping extraction.")
        return {"left": room_data.get("left", 0), "right": room_data.get("right", 0)}

    logger.info(f"Processing {location} {room} meters for {today}...")

    logger.info(f"Processing {location} {room} meters for {today}...")

    # Define variables for validation logic
    current_prev_val_left = 0
    current_prev_val_right = 0

    if isinstance(prev_val, (tuple, list)) and len(prev_val) >= 2:
        current_prev_val_left, current_prev_val_right = prev_val[0], prev_val[1]
    else:
        current_prev_val_left = prev_val
        current_prev_val_right = prev_val

    # Check if we need to fetch from GSheet for Rumyantsevo if prev_left/right are 0 in ingestion_data
    if location == "Rumyantsevo":
        room_data_ingestion = ingestion_data.get(location, {}).get(room, {})
        if (room_data_ingestion.get("prev_left", 0) == 0 or room_data_ingestion.get("prev_right", 0) == 0):
            logger.info(f"Attempting to fetch previous meter values for {location}.{room} from Google Sheet.")
            rumyantsevo_profile = profiles.get("Rumyantsevo", {})
            spreadsheet_id = rumyantsevo_profile.get("spreadsheet_id")
            sheet_gid = rumyantsevo_profile.get("sheet_gid")
            profile_columns = rumyantsevo_profile.get("columns", {})

            if spreadsheet_id and sheet_gid and profile_columns:
                fetched_prev_vals = gsheet_uploader.get_previous_meter_readings_for_rumyantsevo_meters(
                    spreadsheet_id, sheet_gid, profile_columns
                )
                if fetched_prev_vals:
                    if room == "kitchen":
                        current_prev_val_left = fetched_prev_vals["kitchen"]["prev_left"]
                        current_prev_val_right = fetched_prev_vals["kitchen"]["prev_right"]
                    elif room == "bathroom":
                        current_prev_val_left = fetched_prev_vals["bathroom"]["prev_left"]
                        current_prev_val_right = fetched_prev_vals["bathroom"]["prev_right"]
                    logger.info(f"Fetched previous values for {location}.{room}: prev_left={current_prev_val_left}, prev_right={current_prev_val_right}")
                    
                    # Update ingestion_data so these values are persisted and used for current validation
                    if location not in ingestion_data:
                        ingestion_data[location] = {}
                    if room not in ingestion_data[location]:
                        ingestion_data[location][room] = {}
                    ingestion_data[location][room]["prev_left"] = current_prev_val_left
                    ingestion_data[location][room]["prev_right"] = current_prev_val_right
                    save_ingestion_data(ingestion_data) # Save immediately after fetching
                else:
                    logger.warning(f"Could not fetch previous values for {location}.{room} from Google Sheet. Using existing (or default 0) values.")
            else:
                logger.error(f"Missing GSheet configuration for {location} in profiles.json. Cannot fetch previous values.")
        else:
             # If not fetching, ensure current_prev_val_left/right are updated from ingestion_data if available
             current_prev_val_left = room_data_ingestion.get("prev_left", current_prev_val_left)
             current_prev_val_right = room_data_ingestion.get("prev_right", current_prev_val_right)
    
    prev_val_left = current_prev_val_left
    prev_val_right = current_prev_val_right


    global _CACHED_MODELS_TO_TRY
    if _CACHED_MODELS_TO_TRY is None:
        _CACHED_MODELS_TO_TRY = load_cached_models()
    model_name = _CACHED_MODELS_TO_TRY[0]
    img = Image.open(img_path)
    
    # Log annotation context
    logger.info(f"Temporal Annotation Input -> Date: {prev_date}, Value: {prev_val}")

    # Temporal Annotation Assistance Prompt Logic
    days_elapsed = 0
    if prev_date:
        try:
            prev_dt = datetime.strptime(prev_date, "%d/%m/%Y")
            days_elapsed = (today_dt - prev_dt).days
        except ValueError:
            pass
            
    prompts = load_prompts()
    if location == "Tashkentskiy":
        prompt_template = prompts.get("tashkentskiy_image_prompt_template", "")
        if prompt_template:
            try:
                # Format with leading zeros to 5 digits for the prompt
                prev_val_str = f"{int(float(prev_val_left if logic == 'color_coded' and 'red' in img_path.lower() else prev_val_right)):05d}"
                # Derive leading 2 or 3 digits (take first 2 or 3)
                leading_digits = f"{prev_val_str[:2]}\" or \"{prev_val_str[:3]}"
                prompt = prompt_template.replace("01095", prev_val_str).replace("01\" or \"010", leading_digits)
            except Exception as e:
                logger.error(f"Error formatting prompt: {e}")
                prompt = prompt_template
        else:
            prompt = ""
    elif location == "Rumyantsevo":
        prompt = prompts.get("rumyantsevo_image_prompt_template", "")
    else:
        prompt_template = prompts.get("meter_extraction_temporal_prompt", "")
        if prompt_template:
            try:
                prompt = prompt_template.format(
                    prev_val_left=prev_val_left,
                    prev_date=prev_date,
                    current_date=today_dt.strftime("%d/%m/%Y"),
                    days_elapsed=days_elapsed,
                    max_allowed_reading=prev_val_left + days_elapsed
                )
            except Exception as e:
                logger.error(f"Error formatting prompt: {e}")
                prompt = prompt_template
        else:
            prompt = ""

    if not prompt:
        logger.error(f"Could not find prompt for location {location}")
        return {"left": 0, "right": 0}

    def deterministic_parse(val_str):
        if not val_str:
            return 0
        # Keep only digits
        digits = "".join(filter(str.isdigit, str(val_str)))
        if not digits:
            return 0
        # Convert to int (leading zeros are handled by int())
        return int(digits)

    try:
        response = call_gemini_with_retry(client, img, prompt)
        logger.info(f"Raw Gemini API Response: {response.text}")
        data = json.loads(response.text)
        
        is_new_format = False
        if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict) and "black_digits" in data[0]:
            is_new_format = True
        elif isinstance(data, dict) and "black_digits" in data:
            is_new_format = True

        if is_new_format:
            if logic == "color_coded":
                # Tashkentskiy
                res_dict = data[0] if isinstance(data, list) else data
                reading_str = res_dict.get("black_digits", "0")
                color = res_dict.get("color", res_dict.get("Color"))
                if not color:
                    color = "Red" if "red" in img_path.lower() else "Blue"
                val_int = deterministic_parse(reading_str)
                logger.info(f"Extracted {color} meter: black_digits={reading_str}, parsed_val={val_int}")
                
                prev_val = prev_val_left if color == "Red" else prev_val_right
                if color == "Red":
                    left, right = val_int, 0
                else:
                    left, right = 0, val_int
            else:
                # Rumyantsevo
                if isinstance(data, list):
                    left = deterministic_parse(data[0].get("black_digits", "0")) if len(data) >= 1 else 0
                    right = deterministic_parse(data[1].get("black_digits", "0")) if len(data) >= 2 else 0
                else:
                    left = deterministic_parse(data.get("black_digits", "0"))
                    right = 0
        else:
            # Old logic
            # Parse 'FinalResult' which may be an object or a list
            raw_data = data
            if isinstance(data, list):
                data = data[0]
            final_result = data.get("FinalResult", data.get("final_result", data.get("meter_reading", "0")))
            
            if logic == "color_coded":
                # Extract color from response or filename
                color = data.get("color", data.get("Color"))
                if not color:
                    color = "Red" if "red" in img_path.lower() else "Blue"

                # For color coded, FinalResult is often a string or object.
                # Handle potential object with Left/Right keys
                if isinstance(final_result, dict):
                    full_reading = final_result.get("LeftMeter", "0") if color == "Red" else final_result.get("RightMeter", "0")
                else:
                    full_reading = str(final_result)
                
                val_int = deterministic_parse(full_reading)
                logger.info(f"Extracted {color} meter: full={full_reading}, parsed_val={val_int}")
                
                # Validation logic based on color
                prev_val = prev_val_left if color == "Red" else prev_val_right
                
                # Assign correctly: Red=Left, Blue=Right
                if color == "Red":
                    left, right = val_int, 0
                elif color == "Blue":
                    left, right = 0, val_int
                else:
                    left, right = 0, 0
            else:
                # Handle Rumyantsevo (list or dict of meter results)
                if isinstance(final_result, list):
                    # Assuming first is left, second is right
                    left = deterministic_parse(final_result[0] if len(final_result) >= 1 else "0")
                    right = deterministic_parse(final_result[1] if len(final_result) >= 2 else "0")
                elif isinstance(final_result, dict):
                    left = deterministic_parse(final_result.get("LeftMeter", final_result.get("meter_1", "0")))
                    right = deterministic_parse(final_result.get("RightMeter", final_result.get("meter_2", "0")))
                else:
                    # Fallback to older format if needed
                    left = deterministic_parse(data.get("meter_1", "0"))
                    right = deterministic_parse(data.get("meter_2", "0"))
            
        # Validation
        if prev_val_left > 0 and (left - prev_val_left) > 20:
            raise ValueError(f"Validation failed for {location}.{room} (Left): New={left}, Previous={prev_val_left}. Delta > 20.")
        if prev_val_right > 0 and (right - prev_val_right) > 20:
            raise ValueError(f"Validation failed for {location}.{room} (Right): New={right}, Previous={prev_val_right}. Delta > 20.")

        # Determine refresh status
        should_refresh = not (left > 0 and right > 0)

        # Update cache (don't overwrite other fields)
        loc_data = ingestion_data.setdefault(location, {})
        room_data = loc_data.setdefault(room, {})
        room_data.update({
            "date": today,
            "refresh": should_refresh,
            "prev_left": prev_val_left,
            "prev_right": prev_val_right
        })
        # For color coded, we only update the side we found
        room_data.setdefault("left", 0)
        room_data.setdefault("right", 0)
        if logic == "color_coded":
            if color == "Red":
                room_data["left"] = left
            elif color == "Blue":
                room_data["right"] = right
        else:
            room_data["left"] = left
            room_data["right"] = right
            
        save_ingestion_data(ingestion_data)
        logger.info(f"Decoded meter values for {location}.{room}: Left={room_data['left']}, Right={room_data['right']}, Refresh={should_refresh}")
        return {"left": left, "right": right}
    except Exception as e:
        logger.error(f"Error extracting {room}: {e}")
        if isinstance(e, ValueError) and "Validation failed" in str(e):
            raise # Re-raise validation errors
        return {"left": 0, "right": 0}
