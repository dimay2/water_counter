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
DEFAULT_OCR_MODELS = [
    "gemini-4-hydrogen",
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3-flash-preview",
    "gemini-4-argon",
    "gemini-3.1-pro-preview",
    "gemini-3.1-pro-preview-customtools",
    "gemini-4-carbon",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.1-flash-lite-preview",
]
DEFAULT_PDF_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.8-flash",
    "gemini-3.5-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.1-flash-lite-preview",
    "gemini-3-flash-preview",
    "gemini-4-hydrogen",
    "gemini-4-argon",
    "gemini-3.1-pro-preview",
    "gemini-3.1-pro-preview-customtools",
    "gemini-4-carbon",
]
DEFAULT_MODELS = {
    "ocr": DEFAULT_OCR_MODELS,
    "pdf": DEFAULT_PDF_MODELS,
}
_MODELS_LIST_CACHE = None
_LAST_USED_MODEL = None

def _load_models_store() -> dict[str, list[str]]:
    """Load the per-task model priority map from disk, normalizing legacy list files."""
    store = {
        "ocr": list(DEFAULT_OCR_MODELS),
        "pdf": list(DEFAULT_PDF_MODELS),
    }
    if os.path.exists(MODELS_CACHE_FILE):
        try:
            with open(MODELS_CACHE_FILE, 'r', encoding='utf-8') as f:
                raw = json.load(f)
                if isinstance(raw, dict):
                    for key in ("ocr", "pdf"):
                        if isinstance(raw.get(key), list) and len(raw[key]) > 0:
                            store[key] = list(raw[key])
                elif isinstance(raw, list) and len(raw) > 0:
                    store["ocr"] = list(raw)
        except Exception as e:
            logger.warning(f"Could not read {MODELS_CACHE_FILE}: {e}")
    return store

def load_models(task_type: str = "ocr") -> list[str]:
    """Return the ordered model list for the given task_type ('ocr' or 'pdf')."""
    store = _load_models_store()
    return list(store.get(task_type, store["ocr"]))

def select_model(excluded_models=None, task_type: str = "ocr") -> str:
    """Return the highest-priority available model for task_type not in excluded_models."""
    models = get_models(task_type=task_type)
    if not models:
        models = list(DEFAULT_MODELS.get(task_type, DEFAULT_OCR_MODELS))
    if excluded_models:
        for m in models:
            if m not in excluded_models:
                return m
    return models[0]

def get_last_used_model():
    """Return the model name used in the most recent call_gemini_with_retry invocation."""
    return _LAST_USED_MODEL

def get_models(task_type: str = "ocr") -> list[str]:
    global _MODELS_LIST_CACHE
    if _MODELS_LIST_CACHE is None:
        _MODELS_LIST_CACHE = _load_models_store()
    return _MODELS_LIST_CACHE.get(task_type, _MODELS_LIST_CACHE["ocr"])

def save_models(models, task_type: str | None = None):
    try:
        if isinstance(models, dict):
            payload = models
        elif task_type is not None:
            payload = _load_models_store()
            payload[task_type] = list(models)
        else:
            payload = models
        with open(MODELS_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=4)
    except Exception as e:
        logger.error(f"Could not write {MODELS_CACHE_FILE}: {e}")

def demote_model(model_name: str, task_type: str = "ocr"):
    store = _load_models_store()
    models = store.get(task_type, store["ocr"])
    if not models or model_name not in models:
        return

    idx = models.index(model_name)
    models.pop(idx)

    # Put lower this model to random [2..10] places down
    shift = random.randint(2, 10)
    new_idx = min(idx + shift, len(models))

    models.insert(new_idx, model_name)
    store[task_type] = models
    save_models(store)

    # Update global cache
    global _MODELS_LIST_CACHE
    _MODELS_LIST_CACHE = store

    logger.info(f"Demoted [{task_type}] model '{model_name}' from index {idx} to {new_idx} (shifted by {shift})")

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
        task_type = retry_state.kwargs.get("task_type", "ocr")
        excluded = retry_state.kwargs.get("excluded_models")
        next_model = select_model(excluded_models=excluded, task_type=task_type)

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
def call_gemini_with_retry(
    client,
    contents,
    prompt,
    context_info="",
    response_schema=None,
    response_mime_type="application/json",
    excluded_models=None,
    media_resolution=None,
    task_type="ocr",
):
    # Get the current best non-excluded model for this attempt
    global _LAST_USED_MODEL
    model_name = select_model(excluded_models, task_type=task_type)
    _LAST_USED_MODEL = model_name

    logger.info(f"Sending request to model: '{model_name}' [{task_type}] | Context: {context_info}")
    logger.info(f"Full prompt sent to Gemini:\n{prompt}")

    is_image = hasattr(contents, 'width') and hasattr(contents, 'height')
    if media_resolution is None and is_image:
        media_resolution = types.MediaResolution.MEDIA_RESOLUTION_HIGH

    config_kwargs = {
        "response_mime_type": response_mime_type,
        "temperature": 0.0,
    }
    if response_schema:
        config_kwargs["response_schema"] = response_schema
    if media_resolution is not None:
        config_kwargs["media_resolution"] = media_resolution

    config = types.GenerateContentConfig(**config_kwargs)

    file_upload = None
    try:
        actual_contents = []

        if is_image:  # Duck typing for PIL Image
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
        demote_model(model_name, task_type=task_type)
        raise e
    finally:
        if file_upload:
            client.files.delete(name=file_upload.name)
