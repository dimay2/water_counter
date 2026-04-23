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
             required_keys = ["ХВС КПУ", "ГВС КПУ", "Водоотв. КПУ", "Отоп.эн.пл.", "Сод.жил.пом. и обращение с ТКО*", "Запирающее устройство", "Газ"]
        
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

def extract_room_meters(location: str, room: str, img_path: str, client, logic="default", prev_val_left=0, prev_val_right=0, use_cache=True) -> dict:
    if not os.path.exists(img_path):
        logger.error(f"Image not found: {img_path}")
        return {"left": 0, "right": 0}

    ingestion_data = load_ingestion_data()
    loc_data = ingestion_data.get(location, {})
    room_data = loc_data.get(room, {})

    today = datetime.now().strftime("%Y%m%d")

    # Check if we already have data for today's date
    if use_cache and room_data.get("date") == today and not room_data.get("refresh", False):
        logger.info(f"Cache hit for {location}.{room} on {today}. Skipping extraction.")
        logger.info(f"Decoded meter values for {location}.{room}: Left={room_data.get('left', 0)}, Right={room_data.get('right', 0)}")
        return {"left": room_data.get("left", 0), "right": room_data.get("right", 0)}

    logger.info(f"Processing {location} {room} meters for {today}...")
    logger.info(f"Extracting meters from image: {os.path.basename(img_path)}")
    logger.info(f"Previous readings for {location}.{room}: Left={prev_val_left}, Right={prev_val_right}")

    global _CACHED_MODELS_TO_TRY
    if _CACHED_MODELS_TO_TRY is None:
        _CACHED_MODELS_TO_TRY = load_cached_models()

    model_name = _CACHED_MODELS_TO_TRY[0]
    img = Image.open(img_path)
    
    if logic == "color_coded":
        prompt = f"""Analyze the provided water meter image and extract the EXACT 8-digit reading. The reading consists of 5 black digits (cubic meters) and 3 red digits (liters).

Follow these high-precision rules:
1. **Full Reading:** Extract ALL 8 digits together as one string.
2. **Padding:** You MUST include ALL leading zeros. For example, if the counter shows 01099 and 451, the reading is 01099451. If it shows 00979 and 904, the reading is 00979904.
3. **Red Meter Check:** Specifically for the Red meter, ensure you read the 5 cubic meter digits correctly. For example, '01099' is 1099 cubic meters, not 99. Do not truncate leading zeros in the cubic meter part.
4. **Distinctions:** Identify the color (Red or Blue) based on the dial color.

Output ONLY a JSON object in this format:
{{
  "serial_number": "string",
  "full_reading": "8-digit string",
  "cubic_meters": "5-digit string",
  "liters": "3-digit string",
  "color": "Red/Blue",
  "confidence_score": 0.0-1.0
}}

Context:
- Annotated target Red meter: 01099451 (Expect 1099 cubic meters)
- Annotated target Blue meter: 00979904 (Expect 979 cubic meters)
- Your output MUST match the 8-digit full reading logic."""
    else:
        prompt = f"""Extract both water meters from the image.
        Return as JSON: {{"meter_1": "left_full_reading", "meter_2": "right_full_reading"}}
        
        Rules:
        - Extract full counter readings including leading zeros and fractional digits (e.g., "00456.789").
        - meter_1 is the Left meter, meter_2 is the Right meter.
        
        Context:
        - Previous readings: Left={prev_val_left}, Right={prev_val_right}
        
        Do not include serial numbers."""

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

    try:
        response = call_gemini_with_retry(client, model_name, img, prompt)
        logger.info(f"API Response: {response.text}")
        data = json.loads(response.text)

        if logic == "color_coded":
            # Extract from new format: full_reading is 8 digits
            full_reading = data.get("full_reading", "0")
            # Deterministic parse takes string, keeps digits, trims last 3 (fractional), returns int
            val_int = deterministic_parse(full_reading)
            color = data.get("color")
            
            logger.info(f"Extracted {color} meter: full_reading={full_reading}, parsed_val={val_int}")
            
            # Use prev_val based on color for validation
            prev_val = prev_val_left if color == "Red" else prev_val_right
            
            # Validation
            if prev_val > 0 and (val_int - prev_val) > 20:
                raise ValueError(f"Validation failed for {location}.{room} ({color}): New={val_int}, Previous={prev_val}. Delta > 20.")
            if prev_val > 0 and val_int < prev_val:
                logger.warning(f"New reading {val_int} is less than previous {prev_val} for {location}.{room} ({color}). Check if meter rolled over or extraction is wrong.")

            # Left = red, Right = blue
            if color == "Red":
                left, right = val_int, 0
            elif color == "Blue":
                left, right = 0, val_int
            else:
                left, right = 0, 0
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
