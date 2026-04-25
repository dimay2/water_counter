import os
import json
import logging
from datetime import datetime
from PIL import Image
from pydantic import BaseModel
from pdf_extractor import parse_rumyantsevo_pdf, parse_tashkentskiy_pdf
from gemini_utils import call_gemini_with_retry

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
        required_keys = ["ХВС КПУ", "ГВС КПУ", "Водоотв. КПУ"]
        if location == "Tashkentskiy":
             required_keys = ["ХВС КПУ", "ГВС КПУ", "Водоотв. КПУ", "Отоп.эн.пл.", "Содержание ТКО", "Запирающее устройство", "Газ"]
        
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
                        
                        # Only set refresh_pdf to False if all keys are present
                        if all(key in loc_data for key in required_keys):
                            loc_data["refresh_pdf"] = False
                        
                        save_ingestion_data(ingestion_data)
                        logger.info(f"Updated {location} from {filename}")
                        logger.info(f"Parsed values from {filename} for {location}: {pdf_data}")
                    else:
                        logger.warning(f"PDF parsing returned no data for {location}. Keeping refresh_pdf=True.")
                        loc_data["refresh_pdf"] = True
                        save_ingestion_data(ingestion_data)
        
        logger.info(f"Final parsed PDF data for {location}: {loc_data}")

def extract_room_meters(location: str, room: str, img_path: str, client, logic="default", prev_date=None, prev_val=0, use_cache=True) -> dict:
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

    # Define variables for validation logic
    prev_val_left = prev_val if logic != "color_coded" else (prev_val if logic == "color_coded" else 0)
    prev_val_right = prev_val if logic != "color_coded" else (prev_val if logic == "color_coded" else 0)

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
            
    prompt = f"""Task: Extract digits from an ITELMA mechanical water meter image using Temporal Annotation Assistance.
1. Input Parameters:
Previous Reading: {prev_val}
Previous Reading Date: {prev_date}
Current Date: {today_dt.strftime("%d/%m/%Y")}
Consumption Constraint: Total consumption cannot exceed 1.0 m^3 per day since the last reading.
Max Allowed Reading = {prev_val} + ({days_elapsed} days × 1.0) = {prev_val + days_elapsed}.

2. Mechanical Gear-Train Logic:
Driving Right Rule: Decode Right-to-Left. Use the fractional red digits to determine the "Lift" of the black digits.
Rollover Threshold: * If Red Digits are 900–999: The black unit digit is entering transition.
If Red Digits are 000–100: The black unit digit has just completed a rollover.
Staggered Alignment: If the visual reading is lower than the Previous Reading, look for "hidden" digits entering at the bottom of the drum (e.g., a '0' looking like a '1' due to gear slop).

3. Annotation Assistance & Validation:
Step A: Calculate the Max Allowed Reading.
Step B: Extract the visual digits (Center, Top, Bottom of each drum).
Step C: If the extracted visual reading is outside the range [{prev_val}] to [{prev_val + days_elapsed}], re-evaluate the leading black digits. Prioritize the value that fits the logical range over the "most centered" visual digit if a rollover is mechanically plausible.

4. Visual Artifact Filtering:
Ignore vertical black shadows on the edges; identify the specific ink printed on the drum.
Distinguish between the red background (fractional) and white/black background (cubic meters).

5. Output Format:
Calculation: Days Elapsed and Max Allowed Threshold.
Visual Breakdown: Analysis per drum.
Final Result: XXXXX (Whole Cubic Meters only).

- Inputs:
1. last reading date - {prev_date} and shall not be null or blank
2. last reading value  - {prev_val} and shall not be null or blank"""

    def deterministic_parse(val_str):
        if not val_str:
            return 0
        # Keep only digits
        digits = "".join(filter(str.isdigit, str(val_str)))
        # Trim last 3 fractional digits as requested
        if len(digits) > 3:
            trimmed = digits[:-3]
        else:
            trimmed = "0"
        # Remove leading zeros and convert to int
        return int(trimmed.lstrip("0") or "0")

    # Log the prompt sent to Gemini
    logger.debug(f"Prompt sent to Gemini:\n{prompt}")

    try:
        response = call_gemini_with_retry(client, model_name, img, prompt)
        # Log the raw response for debugging
        logger.info(f"Raw Gemini API Response: {response.text}")
        data = json.loads(response.text)
        
        # If data is a list (as seen in logs), assume the first element is the meter reading
        if isinstance(data, list):
            data = data[0]

        if logic == "color_coded":
            # Extract from new format: whole_numbers_m3 (5 digits) + decimal_liters (3 digits)
            # The model now returns "whole_numbers_m3" and "decimal_liters" directly in the JSON response
            m3 = data.get("whole_numbers_m3", "0")
            liters = data.get("decimal_liters", "0")
            
            # Combine to get full reading
            full_reading = f"{m3}{liters}"
            # Deterministic parse takes string, keeps digits, trims last 3 (fractional), returns int
            val_int = deterministic_parse(full_reading)
            color = data.get("color")
            if not color:
                color = "Red" if "red" in img_path.lower() else "Blue"
            
            logger.info(f"Extracted {color} meter: m3={m3}, liters={liters}, full={full_reading}, parsed_val={val_int}")
            
            # Use prev_val based on color for validation
            # IMPORTANT: For color coded, we need to be careful with prev_val mapping
            # prev_val is already passed as the specific left/right reading
            
            # Validation
            if prev_val > 0 and (val_int - prev_val) > 20:
                raise ValueError(f"Validation failed for {location}.{room} ({color}): New={val_int}, Previous={prev_val}. Delta > 20.")
            if prev_val > 0 and val_int < prev_val:
                logger.warning(f"New reading {val_int} is less than previous {prev_val} for {location}.{room} ({color}).")

            # Left = red, Right = blue
            if color == "Red":
                left, right = val_int, 0
            elif color == "Blue":
                left, right = 0, val_int
            else:
                left, right = 0, 0
        else:
            # Handle Rumyantsevo which might return a list of meters
            left = 0
            right = 0
            if isinstance(data, list):
                # Assuming first is left, second is right
                if len(data) >= 1:
                    left = deterministic_parse(f"{data[0].get('whole_numbers_m3', '0')}{data[0].get('decimal_liters', '0')}")
                if len(data) >= 2:
                    right = deterministic_parse(f"{data[1].get('whole_numbers_m3', '0')}{data[1].get('decimal_liters', '0')}")
            else:
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
