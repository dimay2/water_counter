import gspread
import gspread.exceptions
import google.auth
import os
import time
import random
import traceback
import json
import logging
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

def extract_numbers_from_meter(img_path: str) -> tuple[list[int], str]:
    """
    Extracts all digits from water meters using Gemini and processes them
    (drops 3 rightmost digits and removes leading zeros).
    Returns a tuple containing a list of values found, and the model name used.
    """
    if not os.path.exists(img_path):
        logger.error(f"Image not found: {img_path}")
        return [], ""

    global _CACHED_MODELS_TO_TRY

    try:
        client = genai.Client()
        img = Image.open(img_path)
        prompt = "Extract all digits from the two water meters in this image, including both the black and red background digits. Return them as meter_1 (top or left) and meter_2 (bottom or right) as strings, preserving all leading zeros."
        
        if _CACHED_MODELS_TO_TRY is None:
            _CACHED_MODELS_TO_TRY = load_cached_models()

        api_models_fetched = False

        if not _CACHED_MODELS_TO_TRY:
            _CACHED_MODELS_TO_TRY = get_api_vision_models(client)
            api_models_fetched = True
            if not _CACHED_MODELS_TO_TRY:
                logger.error("No valid vision-capable models found available for this API key.")
                return [], ""
            
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
                    
                    # Promote successful model to the top of the cached list and save
                    if model_name in _CACHED_MODELS_TO_TRY:
                        _CACHED_MODELS_TO_TRY.remove(model_name)
                    _CACHED_MODELS_TO_TRY.insert(0, model_name)
                    save_cached_models(_CACHED_MODELS_TO_TRY)
                    
                    return [process_meter_string(data.get("meter_1", "")), process_meter_string(data.get("meter_2", ""))], model_name
                except RetryError as e:
                    final_exception = e.last_attempt.exception()
                    logger.error(f"Model '{model_name}' failed after all retries for a persistent 503 error. Final exception: {final_exception}")
                except Exception as e:
                    if is_429_error(e) or is_404_error(e):
                        if is_429_error(e):
                            reason = "quota exhausted"
                        else:  # is_404_error
                            reason = "model not found"
                            # Permanently remove 404 models from cache
                            if model_name in _CACHED_MODELS_TO_TRY:
                                _CACHED_MODELS_TO_TRY.remove(model_name)
                                save_cached_models(_CACHED_MODELS_TO_TRY)
                        
                        logger.error(f"Model '{model_name}' failed ({reason}). Falling back to next...")
                    else:
                        logger.error(f"A non-retryable error occurred extracting from {img_path} with {model_name}: {e}")
                        # Permanently remove models that throw bad requests (e.g. 400 Modality not supported)
                        if model_name in _CACHED_MODELS_TO_TRY:
                            _CACHED_MODELS_TO_TRY.remove(model_name)
                            save_cached_models(_CACHED_MODELS_TO_TRY)
            
            # If we exhausted the list
            if not api_models_fetched:
                logger.warning("All cached models failed. Fetching a fresh list of models from API...")
                fresh_models = get_api_vision_models(client)
                new_models = [m for m in fresh_models if m not in _CACHED_MODELS_TO_TRY]
                if new_models:
                    logger.info("Discovered new vision-capable models from API:")
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

        return [], ""

    except Exception as e:
        logger.error(f"An unexpected error occurred in extract_numbers_from_meter for {img_path}: {e}")
        return [], ""

def main():
    logger.info("--- Water Counter Processor (Vision-Based) ---")
    
    logger.info("Processing Bathroom image...")
    b_values, b_model = extract_numbers_from_meter(BATHROOM_IMG)
    b_left = b_values[0] if len(b_values) > 0 else 0
    b_right = b_values[1] if len(b_values) > 1 else 0

    logger.info("Processing Kitchen image...")
    k_values, k_model = extract_numbers_from_meter(KITCHEN_IMG)
    k_left = k_values[0] if len(k_values) > 0 else 0
    k_right = k_values[1] if len(k_values) > 1 else 0

    logger.info("Final Results:")
    k_mod_str = f" (via {k_model})" if k_model else ""
    b_mod_str = f" (via {b_model})" if b_model else ""
    logger.info(f"  Kitchen: B={k_left}, C={k_right}{k_mod_str}")
    logger.info(f"  Bathroom: D={b_left}, E={b_right}{b_mod_str}")

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

        new_row = ["", k_left, k_right, b_left, b_right]
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
