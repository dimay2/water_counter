import logging
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception, before_sleep_log
from google.genai import types
import io

# Suppress all verbose library logs
logging.getLogger("google").setLevel(logging.WARNING)
logging.getLogger("google.genai").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

def is_retryable_error(exception: Exception) -> bool:
    err_str = str(exception)
    return "503" in err_str or "UNAVAILABLE" in err_str or "429" in err_str or "RESOURCE_EXHAUSTED" in err_str

@retry(
    wait=wait_exponential(multiplier=8, min=8, max=60),
    stop=stop_after_attempt(5),
    retry=retry_if_exception(is_retryable_error),
    before_sleep=before_sleep_log(logger, logging.WARNING)
)
def call_gemini_with_retry(client, model_name, contents, prompt, context_info="", response_schema=None, response_mime_type="application/json"):
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
            model=model_name,
            contents=actual_contents,
            config=config
        )
        logger.info(f"Received response from '{model_name}'")
        logger.debug(f"Response text: {response.text}")
        return response
    except Exception as e:
        logger.error(f"Request to '{model_name}' failed: {e}")
        raise e
    finally:
        if file_upload:
            client.files.delete(name=file_upload.name)
