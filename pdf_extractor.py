import os
import json
import logging
from gemini_utils import call_gemini_with_retry
from prompt_utils import load_prompts

logger = logging.getLogger(__name__)

def parse_rumyantsevo_pdf(pdf_path: str, client, model_name) -> dict:
    logger.info(f"Initiating Rumyantsevo PDF parsing: {pdf_path}")
    file_upload = client.files.upload(file=pdf_path)

    prompts = load_prompts()
    prompt = prompts.get("rumyantsevo_pdf_prompt", "")

    try:
        response = call_gemini_with_retry(client, file_upload, prompt, context_info=f"Rumyantsevo PDF: {os.path.basename(pdf_path)}")
        data = json.loads(response.text)
        logger.info(f"Parsed PDF: {data}")
        return data
    except Exception as e:
        logger.error(f"Failed Rumyantsevo PDF: {e}")
        return {}
    finally:
        client.files.delete(name=file_upload.name)

def parse_tashkentskiy_pdf(pdf_path: str, client, model_name) -> dict:
    logger.info(f"Initiating Tashkentskiy PDF parsing: {pdf_path}")
    file_upload = client.files.upload(file=pdf_path)
    # Note: Using a standard key name to avoid encoding issues with PDF extraction
    # Key: "Сод.жил.пом. и обращение с ТКО*"

    prompts = load_prompts()
    prompt = prompts.get("tashkentskiy_pdf_prompt", "")

    try:
        response = call_gemini_with_retry(client, file_upload, prompt, context_info=f"Tashkentskiy PDF: {os.path.basename(pdf_path)}")
        data = json.loads(response.text)
        logger.info(f"Parsed PDF: {data}")
        return data
    except Exception as e:
        logger.error(f"Failed Tashkentskiy PDF: {e}")
        return {}
    finally:
        client.files.delete(name=file_upload.name)

