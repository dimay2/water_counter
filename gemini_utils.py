import logging
import os
import json
import random
import io
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception, before_sleep_log
from google.genai import types

# Suppress all verbose library logs
logging.getLogger("google").setLevel(logging.WARNING)
logging.getLogger("google.genai").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

MODELS_CACHE_FILE = 'working_models.json'
_MODELS_LIST_CACHE = None

def load_models():
    if os.path.exists(MODELS_CACHE_FILE):
        try:
            with open(MODELS_CACHE_FILE, 'r') as f:
                models = json.load(f)
                if isinstance(models, list) and len(models) > 0:
                    return models
        except Exception as e:
            logger.warning(f"Could not read {MODELS_CACHE_FILE}: {e}")
    return []

def get_models():
    global _MODELS_LIST_CACHE
    if _MODELS_LIST_CACHE is None:
        _MODELS_LIST_CACHE = load_models()
    return _MODELS_LIST_CACHE

def save_models(models):
    try:
        with open(MODELS_CACHE_FILE, 'w') as f:
            json.dump(models, f, indent=4)
    except Exception as e:
        logger.error(f"Could not write {MODELS_CACHE_FILE}: {e}")

def demote_model(model_name):
    models = load_models() # Always load from file to be sure
    if not models or model_name not in models:
        return
    
    idx = models.index(model_name)
    models.pop(idx)
    
    # Put lower this model to random [2..10] places down
    shift = random.randint(2, 10)
    new_idx = idx + shift
    if new_idx > len(models):
        new_idx = len(models)
        
    models.insert(new_idx, model_name)
    save_models(models)
    
    # Update global cache
    global _MODELS_LIST_CACHE
    _MODELS_LIST_CACHE = models
    
    logger.info(f"Demoted model '{model_name}' from index {idx} to {new_idx} (shifted by {shift})")

def is_retryable_error(exception: Exception) -> bool:
    err_str = str(exception)
    return "503" in err_str or "500" in err_str or "502" in err_str or "504" in err_str or "UNAVAILABLE" in err_str or "429" in err_str or "RESOURCE_EXHAUSTED" in err_str

def before_sleep_combined(retry_state):
    """Callback for tenacity before_sleep that logs error and delay before the next retry attempt."""
    try:
        exception = retry_state.outcome.exception()
        err_msg = str(exception)
        max_attempts = getattr(getattr(retry_state.retry_object, 'stop', None), 'max_attempt_number', 5)
        sleep_time = getattr(retry_state.next_action, 'sleep', 0) if retry_state.next_action else 0
        next_model = get_models()[0] if get_models() else "unknown"

        reason = err_msg
        if hasattr(exception, 'response') and hasattr(exception.response, 'text'):
            try:
                error_data = json.loads(exception.response.text)
                if 'error' in error_data and isinstance(error_data['error'], dict):
                    error_code = error_data['error'].get('code', 'UNKNOWN')
                    error_status = error_data['error'].get('status', 'UNKNOWN_STATUS')
                    reason = f"{error_code} {error_status}"
            except Exception:
                pass

        logger.warning(
            f"Transient API error ({reason}). Retrying in {sleep_time:.1f}s (Attempt {retry_state.attempt_number}/{max_attempts}). "
            f"Next model to try: '{next_model}'."
        )
    except Exception as e:
        logger.warning(f"Retrying attempt {retry_state.attempt_number} after error: {e}")

@retry(
    wait=wait_exponential(multiplier=8, min=8, max=60),
    stop=stop_after_attempt(5),
    retry=retry_if_exception(is_retryable_error),
    before_sleep=before_sleep_combined
)
def call_gemini_with_retry(client, contents, prompt, context_info="", response_schema=None, response_mime_type="application/json"):
    # Get the current best model for this attempt
    model_name = get_models()[0] # Always try the first model in the list

    logger.info(f"Sending request to model: '{model_name}' | Context: {context_info}")
    logger.info(f"Full prompt sent to Gemini:\n{prompt}")
    
    config = types.GenerateContentConfig(
        response_mime_type=response_mime_type,
        temperature=0.0
    )
    if response_schema:
        config.response_schema = response_schema
        
    file_upload = None
    try:
        actual_contents = []

        if hasattr(contents, 'width') and hasattr(contents, 'height'):  # Duck typing for PIL Image
            # Save the PIL Image to a temporary BytesIO object
            byte_arr = io.BytesIO()
            contents.save(byte_arr, format='PNG')
            byte_arr.seek(0)
            file_upload = client.files.upload(
                file=byte_arr,
                config=types.UploadFileConfig(mime_type='image/png')
            )

            actual_contents.append(file_upload)
        else:
            actual_contents.append(contents)
        
        actual_contents.append(prompt)

        response = client.models.generate_content(
            model=model_name, # Use the dynamically chosen model_name
            contents=actual_contents,
            config=config
        )
        logger.info(f"Received response from '{model_name}'")
        logger.debug(f"Response text: {response.text}")
        return response
    except Exception as e:
        error_message = str(e)
        try:
            if hasattr(e, 'response') and hasattr(e.response, 'text'):
                error_data = json.loads(e.response.text)
            else:
                error_data = json.loads(error_message)

            if 'error' in error_data and isinstance(error_data['error'], dict):
                error_code = error_data['error'].get('code', 'UNKNOWN')
                error_status = error_data['error'].get('status', 'UNKNOWN_STATUS')
                logger.error(f"Request to '{model_name}' failed: {error_code} {error_status}")
            else:
                logger.error(f"Request to '{model_name}' failed: {error_message}")
        except json.JSONDecodeError:
            logger.error(f"Request to '{model_name}' failed: {error_message}")
        
        # Demote the model that just failed
        demote_model(model_name)
        raise e
    finally:
        if file_upload:
            client.files.delete(name=file_upload.name)
