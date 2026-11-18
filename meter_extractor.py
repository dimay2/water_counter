import os
import json
import logging
from datetime import datetime
from PIL import Image, ImageOps
from pydantic import BaseModel
from pdf_extractor import parse_rumyantsevo_pdf, parse_tashkentskiy_pdf
from gemini_utils import call_gemini_with_retry, get_last_used_model, load_models
from prompt_utils import load_prompts, build_rumyantsevo_context, build_tashkentskiy_context
import gsheet_uploader

# Configure logging
logger = logging.getLogger(__name__)

MODELS_CACHE_FILE = 'working_models.json'
DATA_INGESTION_FILE = 'data_for_ingestion.json'
MAX_MONTHLY_DELTA = 30
MAX_VALIDATION_ATTEMPTS = 3

class MeterReadings(BaseModel):
    meter_1: str
    meter_2: str

_CACHED_MODELS_TO_TRY = None

def load_cached_models():
    return load_models()

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
    model_name = load_models("pdf")[0]

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

        # Check if today's date exists in GSheet. If not, force PDF refresh.
        today_date = datetime.now().strftime("%d/%m/%Y")
        profile = profiles.get(location, {})
        spreadsheet_id = profile.get("spreadsheet_id")
        sheet_gid = profile.get("sheet_gid")
        
        if spreadsheet_id and sheet_gid:
            last_record = gsheet_uploader.get_last_readings(spreadsheet_id, sheet_gid)
            if last_record:
                last_date = last_record[0]
                if last_date != today_date:
                    logger.info(f"[{location}] Today's date {today_date} not found in GSheet (last date: {last_date}). Forcing PDF refresh.")
                    loc_data["refresh_pdf"] = True
            else:
                logger.info(f"[{location}] GSheet is empty. Forcing PDF refresh.")
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
    img = ImageOps.exif_transpose(Image.open(img_path))
    
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
            target_prev = prev_val_left if logic == 'color_coded' and 'red' in img_path.lower() else prev_val_right
            context_block = build_tashkentskiy_context(target_prev, max_delta=MAX_MONTHLY_DELTA)
            prompt = (
                prompt_template.replace("{context_block}", context_block)
                if "{context_block}" in prompt_template
                else f"{prompt_template}\n\nContext:\n{context_block}"
            )
        else:
            prompt = ""
    elif location == "Rumyantsevo":
        prompt_template = prompts.get("rumyantsevo_image_prompt_template", "")
        if prompt_template:
            context_block = build_rumyantsevo_context(prev_val_left, prev_val_right, max_delta=MAX_MONTHLY_DELTA)
            prompt = (
                prompt_template.replace("{context_block}", context_block)
                if "{context_block}" in prompt_template
                else f"{prompt_template}\n\nContext:\n{context_block}"
            )
        else:
            prompt = ""
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

    try:
        excluded_models = set()
        left, right, color = 0, 0, None

        for attempt in range(1, MAX_VALIDATION_ATTEMPTS + 1):
            response = call_gemini_with_retry(
                client,
                img,
                prompt,
                context_info=f"{location}.{room} (attempt {attempt}/{MAX_VALIDATION_ATTEMPTS})",
                excluded_models=excluded_models,
                task_type="ocr",
            )
            logger.info(f"Raw Gemini API Response: {response.text}")
            data = json.loads(response.text)
            left, right, color = _parse_meter_payload(data, logic, img_path)

            try:
                _validate_meter_readings(
                    location, room, logic, color, left, right, prev_val_left, prev_val_right
                )
                break
            except ValueError as ve:
                used_model = get_last_used_model()
                if used_model:
                    excluded_models.add(used_model)
                if attempt < MAX_VALIDATION_ATTEMPTS:
                    logger.warning(f"{ve} Escalating to next model after '{used_model}'.")
                else:
                    raise

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


def _deterministic_parse(val_str) -> int:
    """Keep only digits from raw meter text and parse as integer (stripping leading zeros)."""
    if not val_str:
        return 0
    digits = "".join(filter(str.isdigit, str(val_str)))
    return int(digits) if digits else 0


def _parse_meter_payload(data, logic: str, img_path: str) -> tuple[int, int, str | None]:
    """Parse Gemini JSON response payload into (left, right, color)."""
    is_new_format = (
        (isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict) and "black_digits" in data[0])
        or (isinstance(data, dict) and "black_digits" in data)
    )

    color = None
    if is_new_format:
        if logic == "color_coded":
            res_dict = data[0] if isinstance(data, list) else data
            reading_str = res_dict.get("black_digits", "0")
            color = res_dict.get("color", res_dict.get("Color")) or ("Red" if "red" in img_path.lower() else "Blue")
            val_int = _deterministic_parse(reading_str)
            logger.info(f"Extracted {color} meter: black_digits={reading_str}, parsed_val={val_int}")
            return (val_int, 0, color) if color == "Red" else (0, val_int, color)

        if isinstance(data, list):
            left = _deterministic_parse(data[0].get("black_digits", "0")) if len(data) >= 1 else 0
            right = _deterministic_parse(data[1].get("black_digits", "0")) if len(data) >= 2 else 0
            return left, right, None
        return _deterministic_parse(data.get("black_digits", "0")), 0, None

    # Legacy payload format fallback
    entry = data[0] if isinstance(data, list) else data
    final_result = entry.get("FinalResult", entry.get("final_result", entry.get("meter_reading", "0")))

    if logic == "color_coded":
        color = entry.get("color", entry.get("Color")) or ("Red" if "red" in img_path.lower() else "Blue")
        if isinstance(final_result, dict):
            full_reading = final_result.get("LeftMeter", "0") if color == "Red" else final_result.get("RightMeter", "0")
        else:
            full_reading = str(final_result)
        val_int = _deterministic_parse(full_reading)
        logger.info(f"Extracted {color} meter: full={full_reading}, parsed_val={val_int}")
        if color == "Red":
            return val_int, 0, color
        if color == "Blue":
            return 0, val_int, color
        return 0, 0, color

    if isinstance(final_result, list):
        left = _deterministic_parse(final_result[0] if len(final_result) >= 1 else "0")
        right = _deterministic_parse(final_result[1] if len(final_result) >= 2 else "0")
        return left, right, None
    if isinstance(final_result, dict):
        left = _deterministic_parse(final_result.get("LeftMeter", final_result.get("meter_1", "0")))
        right = _deterministic_parse(final_result.get("RightMeter", final_result.get("meter_2", "0")))
        return left, right, None
    return _deterministic_parse(entry.get("meter_1", "0")), _deterministic_parse(entry.get("meter_2", "0")), None


def _validate_meter_readings(
    location: str,
    room: str,
    logic: str,
    color: str | None,
    left: int,
    right: int,
    prev_val_left: int,
    prev_val_right: int,
    max_delta: int = MAX_MONTHLY_DELTA,
) -> None:
    """Raise ValueError if extracted readings violate monotonicity or monthly consumption bounds."""
    checks = []
    if logic == "color_coded":
        if color == "Red":
            checks.append(("Left", left, prev_val_left))
        elif color == "Blue":
            checks.append(("Right", right, prev_val_right))
    else:
        checks.extend([("Left", left, prev_val_left), ("Right", right, prev_val_right)])

    for side, new_val, prev_val in checks:
        if prev_val <= 0:
            continue
        if new_val == 0:
            raise ValueError(f"Validation failed for {location}.{room} ({side}): New=0, Previous={prev_val}.")
        if (new_val - prev_val) > max_delta:
            raise ValueError(
                f"Validation failed for {location}.{room} ({side}): New={new_val}, Previous={prev_val}. Delta > {max_delta}."
            )
        if new_val < prev_val and prev_val < 99970:
            raise ValueError(
                f"Validation failed for {location}.{room} ({side}): New={new_val} < Previous={prev_val}."
            )
