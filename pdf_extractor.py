import os
import json
import logging
from gemini_utils import call_gemini_with_retry
from prompt_utils import load_prompts

logger = logging.getLogger(__name__)

def _parse_pdf(pdf_path: str, client, prompt_key: str, label: str) -> dict:
    """Upload PDF and extract structured utility charges using the PDF model list."""
    logger.info(f"Initiating {label} PDF parsing: {pdf_path}")
    file_upload = client.files.upload(file=pdf_path)

    prompts = load_prompts()
    prompt = prompts.get(prompt_key, "")

    try:
        response = call_gemini_with_retry(
            client,
            file_upload,
            prompt,
            context_info=f"{label} PDF: {os.path.basename(pdf_path)}",
            task_type="pdf",
        )
        data = json.loads(response.text)
        logger.info(f"Parsed PDF: {data}")
        return data
    except Exception as e:
        logger.error(f"Failed {label} PDF: {e}")
        return {}
    finally:
        client.files.delete(name=file_upload.name)


def parse_rumyantsevo_pdf(pdf_path: str, client, model_name=None) -> dict:
    return _parse_pdf(pdf_path, client, "rumyantsevo_pdf_prompt", "Rumyantsevo")


def parse_tashkentskiy_pdf(pdf_path: str, client, model_name=None) -> dict:
    # Note: Using a standard key name to avoid encoding issues with PDF extraction
    # Key: "Сод.жил.пом. и обращение с ТКО*"
    return _parse_pdf(pdf_path, client, "tashkentskiy_pdf_prompt", "Tashkentskiy")

