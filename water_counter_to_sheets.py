import gspread
import gspread.exceptions
import google.auth
import os
import time
import random
import traceback
import json
import logging
from datetime import datetime
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel
from PIL import Image
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception, RetryError

# Load environment variables from .env
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Suppress verbose INFO logs from httpx (the REST API library)
logging.getLogger("httpx").setLevel(logging.WARNING)

# --- Constants ---
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID') or '127KX8icaYG03o5WVvnHWcXjxCxlR5s5lBMY4Gl1lSPY'
SHEET_GID = int(os.getenv('SHEET_GID') if os.getenv('SHEET_GID') else 455004741)
KITCHEN_IMG = r'Input_data\Rumyantsevo\kitchen.jpeg'
BATHROOM_IMG = r'Input_data\Rumyantsevo\bacthroom.jpeg'
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
                    logger.info(f"Loaded {len(models)} cached models from {MODELS_CACHE_FILE}")
                    return models
        except Exception as e:
            logger.warning(f"Could not read {MODELS_CACHE_FILE}: {e}")
    return []

def save_cached_models(models_list):
    try:
        with open(MODELS_CACHE_FILE, 'w') as f:
            json.dump(models_list, f, indent=4)
    except Exception as e:
        logger.warning(f"Could not write {MODELS_CACHE_FILE}: {e}")

def load_ingestion_data():
    if os.path.exists(DATA_INGESTION_FILE):
        try:
            with open(DATA_INGESTION_FILE, 'r') as f:
                data = json.load(f)
                if isinstance(data, list):
                    logger.info(f"Loaded {len(data)} cached ingestion data entries from {DATA_INGESTION_FILE}")
                    return data
        except Exception as e:
            logger.warning(f"Could not read {DATA_INGESTION_FILE}: {e}")
    return []

def save_ingestion_data(data_list):
    try:
        with open(DATA_INGESTION_FILE, 'w') as f:
            json.dump(data_list, f, indent=4)
    except Exception as e:
        logger.warning(f"Could not write {DATA_INGESTION_FILE}: {e}")

def get_api_vision_models(client):
    valid_model_names = [m.name.replace("models/", "") for m in client.models.list()]
    preferred_order = [
        'gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-2.0-flash', 
        'gemini-2.0-flash-lite', 'gemini-2.0-pro-exp'
    ]
    models_to_try = [m for m in preferred_order if m in valid_model_names]
    excluded_keywords = ['embedding', 'aqa', 'text', '1.0', '1.5', 'tts', 'audio', 'imagen', 'veo', 'lyria', 'robotics', 'computer-use']
    for m in valid_model_names:
        if m.startswith('gemini-') and not any(kw in m for kw in excluded_keywords) and m not in models_to_try:
            models_to_try.append(m)
    return models_to_try

def is_503_error(exception: Exception) -> bool:
    return "503" in str(exception) or "UNAVAILABLE" in str(exception)

def is_429_error(exception: Exception) -> bool:
    """Checks if the exception is a 429 quota error."""
    return "429" in str(exception) or "RESOURCE_EXHAUSTED" in str(exception)

def is_404_error(exception: Exception) -> bool:
    """Checks if the exception is a 404 model not found error."""
    return "404" in str(exception) or "NOT_FOUND" in str(exception)

@retry(
    wait=wait_exponential(multiplier=8, min=8, max=40),
    stop=stop_after_attempt(4),
    retry=retry_if_exception(is_503_error),
    before_sleep=lambda rs: logger.warning(
        f"Gemini API returned 503 Server Error for model '{rs.args[-1]}'. Retrying in {rs.next_action.sleep:.2f}s (Attempt {rs.attempt_number})."
    )
)
def _call_gemini_with_retry(client, img, prompt, model_name):
    return client.models.generate_content(
        model=model_name,
        contents=[img, prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=MeterReadings,
            temperature=0.1
        )
    )

def extract_numbers_from_meter(location: str, position: str, img_path: str) -> tuple[int, str]:
    """
    Extracts digits from a specific water meter image, checks cache for recent data,
    and returns the processed integer value along with the model name used.
    """
    if not os.path.exists(img_path):
        logger.error(f"Image not found: {img_path}")
        return 0, ""

    today_ymd = datetime.now().strftime("%Y%m%d")
    ingestion_data = load_ingestion_data()
    
    # Check cache for existing data for this meter and today's date
    for entry in ingestion_data:
        if (entry.get("water_meter_location") == location and
            entry.get("water_meter_position") == position and
            entry.get("last_update") == today_ymd):
            logger.info(f"Cache hit for {location} {position} meter. Using cached value: {entry.get("water_meter_value")}")
            return entry.get("water_meter_value", 0), "Cached"

    global _CACHED_MODELS_TO_TRY

    try:
        client = genai.Client()
        img = Image.open(img_path)
        prompt = f"Extract all digits from the {position} water meter in this image, including both the black and red background digits. Return it as meter_1 as string, preserving all leading zeros. If there are two meters, extract the one that corresponds to the {position} position."
        
        if _CACHED_MODELS_TO_TRY is None:
            _CACHED_MODELS_TO_TRY = load_cached_models()

        api_models_fetched = False

        if not _CACHED_MODELS_TO_TRY:
            _CACHED_MODELS_TO_TRY = get_api_vision_models(client)
            api_models_fetched = True
            if not _CACHED_MODELS_TO_TRY:
                logger.error("No valid vision-capable models found available for this API key.")
                return 0, ""
            
            logger.info("Fetched vision-capable models from API:")
            for m in _CACHED_MODELS_TO_TRY:
                logger.info(f"  - {m}")

        def process_meter_string(m_str):
            if not m_str: return 0
            digits = "".join(filter(str.isdigit, str(m_str)))
            if len(digits) <= 3: return 0
            digits = digits[:-3]
            digits = digits.lstrip('0')
            return int(digits) if digits else 0

        while True:
            models_to_iterate = list(_CACHED_MODELS_TO_TRY)
            for i, model_name in enumerate(models_to_iterate):
                delay = random.uniform(4.0, 8.0)
                logger.info(f"Sleeping for {delay:.2f}s to respect API rate limits...")
                time.sleep(delay)
                
                logger.info(f"Attempting to process image with model: {model_name}")
                try:
                    response = _call_gemini_with_retry(client, img, prompt, model_name)
                    data = json.loads(response.text)
                    logger.info(f"Successfully processed image using model: {model_name}")
                    
                    meter_value = process_meter_string(data.get("meter_1", ""))

                    # Save to ingestion data cache
                    new_entry = {
                        "water_meter_location": location,
                        "water_meter_position": position,
                        "water_meter_value": meter_value,
                        "last_update": today_ymd
                    }
                    # Update existing entry or add new one
                    found = False
                    for idx, entry in enumerate(ingestion_data):
                        if entry.get("water_meter_location") == location and entry.get("water_meter_position") == position:
                            ingestion_data[idx] = new_entry
                            found = True
                            break
                    if not found:
                        ingestion_data.append(new_entry)
                    save_ingestion_data(ingestion_data)

                    # Promote successful model to the top of the cached list and save
                    if model_name in _CACHED_MODELS_TO_TRY:
                        _CACHED_MODELS_TO_TRY.remove(model_name)
                    _CACHED_MODELS_TO_TRY.insert(0, model_name)
                    save_cached_models(_CACHED_MODELS_TO_TRY)
                    
                    return meter_value, model_name
                except RetryError as e:
                    final_exception = e.last_attempt.exception()
                    logger.error(f"Model \'{model_name}\' failed after all retries for a persistent 503 error. Final exception: {final_exception}")
                except Exception as e:
                    if is_429_error(e) or is_404_error(e):
                        if is_429_error(e):\
                            reason = "quota exhausted"\n                        else:  # is_404_error\n                            reason = "model not found"\n                            # Permanently remove 404 models from cache\n                            if model_name in _CACHED_MODELS_TO_TRY:\n                                _CACHED_MODELS_TO_TRY.remove(model_name)\n                                save_cached_models(_CACHED_MODELS_TO_TRY)\n                        \n                        logger.error(f"Model \'{model_name}\' failed ({reason}). Falling back to next...")\n                    else:\n                        logger.error(f"A non-retryable error occurred extracting from {img_path} with {model_name}: {e}")\n                        # Permanently remove models that throw bad requests (e.g. 400 Modality not supported)\n                        if model_name in _CACHED_MODELS_TO_TRY:\n                            _CACHED_MODELS_TO_TRY.remove(model_name)\n                            save_cached_models(_CACHED_MODELS_TO_TRY)\n            \n            # If we exhausted the list\n            if not api_models_fetched:\n                logger.warning("All cached models failed. Fetching a fresh list of models from API...")\n                fresh_models = get_api_vision_models(client)\n                new_models = [m for m in fresh_models if m not in _CACHED_MODELS_TO_TRY]\n                if new_models:\n                    logger.info("Discovered new vision-capable models from API:")
                    for m in new_models:
                        logger.info(f"  - {m}")
                    _CACHED_MODELS_TO_TRY.extend(new_models)
                    save_cached_models(_CACHED_MODELS_TO_TRY)
                    api_models_fetched = True
                    continue  # Loop again to try the newly discovered models
                else:
                    logger.error("No additional models found to try from the API.")
                    break
            else:
                logger.error("All fallback models exhausted.")
                break

        return 0, ""

    except Exception as e:
        logger.error(f"An unexpected error occurred in extract_numbers_from_meter for {img_path}: {e}")
        return 0, ""

def main():
    logger.info("--- Water Counter Processor (Vision-Based) ---")
    
    location = "Rumyantsevo" # As per user request, this is a fixed location

    logger.info("Processing Kitchen left image...")
    k_left, k_left_model = extract_numbers_from_meter(location, "kitchen_left", KITCHEN_IMG)

    logger.info("Processing Kitchen right image...")
    k_right, k_right_model = extract_numbers_from_meter(location, "kitchen_right", KITCHEN_IMG)

    logger.info("Processing Bathroom left image...")
    b_left, b_left_model = extract_numbers_from_meter(location, "bathroom_left", BATHROOM_IMG)

    logger.info("Processing Bathroom right image...")
    b_right, b_right_model = extract_numbers_from_meter(location, "bathroom_right", BATHROOM_IMG)

    logger.info("Final Results:")
    k_left_mod_str = f" (via {k_left_model})" if k_left_model else ""
    k_right_mod_str = f" (via {k_right_model})" if k_right_model else ""
    b_left_mod_str = f" (via {b_left_model})" if b_left_model else ""
    b_right_mod_str = f" (via {b_right_model})" if b_right_model else ""

    logger.info(f"  Kitchen Left: {k_left}{k_left_mod_str}")
    logger.info(f"  Kitchen Right: {k_right}{k_right_mod_str}")
    logger.info(f"  Bathroom Left: {b_left}{b_left_mod_str}")
    logger.info(f"  Bathroom Right: {b_right}{b_right_mod_str}")

    if k_left == 0 or k_right == 0 or b_left == 0 or b_right == 0:
        logger.warning("Extraction failed (one or more values are 0). Exiting without uploading to Google Sheets.")
        return

    try:
        logger.info("Connecting to Google Sheets...")
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds, _ = google.auth.default(scopes=scopes)
        client = gspread.authorize(creds)
        
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        sheet = spreadsheet.get_worksheet_by_id(SHEET_GID)

        today_date = datetime.now().strftime("%Y-%m-%d")
        new_row = [today_date, k_left, k_right, b_left, b_right]
        sheet.append_row(new_row, value_input_option='RAW')
        logger.info("Successfully appended row to Google Sheets!")
        
    except gspread.exceptions.SpreadsheetNotFound:
        logger.error(f"Google Sheet not found (404 Error).")
        logger.error(f"Please verify SPREADSHEET_ID '{SPREADSHEET_ID}' in your .env file.")
        logger.error("Crucial: Ensure the sheet is shared with your Google Cloud Service Account email!")
    except Exception:
        logger.error("Error occurred during Google Sheets upload", exc_info=True)

if __name__ == "__main__":
    main()
