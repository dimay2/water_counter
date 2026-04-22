import os
import json
import logging
from gemini_utils import call_gemini_with_retry

logger = logging.getLogger(__name__)

def parse_rumyantsevo_pdf(pdf_path: str, client, model_name) -> dict:
    logger.info(f"Initiating Rumyantsevo PDF parsing: {pdf_path}")
    file_upload = client.files.upload(file=pdf_path)
    prompt = """
    Extract utility charges from the table column 2 ("Виды услуг") and column 9 ("Всего начисл.").
    - Fields: "Содержание и техническое обслуживание помещений", "Обращение с ТКО", "Холодное водоснабжение", "Холодная вода для ГВС", "Теплоэнергия для ГВС", "Водоотведение", "Отопление", "Охрана и мониторинг ЖК", "Электроснабжение для СОИ:"
    - Clean currency: remove all digits after comma.
    - JSON: {"Service Name": "Value"}
    """
    try:
        response = call_gemini_with_retry(client, model_name, file_upload, prompt, context_info=f"Rumyantsevo PDF: {os.path.basename(pdf_path)}")
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
    prompt = """
    Extract utility charges from table column "Вид платежа".
    Fields to extract:
    - Left part: "ХВС КПУ", "ГВС КПУ", "Водоотв. КПУ", "Отоп.эн.пл."
    - Right part: "Сод.жил.пом. и обращение с ТКО*", "Запирающее устройство", "Газ"
    - Ignore "Взнос на кап. ремонт".
    - Rule: Clean currency (remove digits after comma).
    - Note: Ensure "Сод.жил.пом. и обращение с ТКО*" is captured exactly even if it spans multiple lines or has spaces.
    - JSON: {"Service Name": "Value"}
    """
    try:
        response = call_gemini_with_retry(client, model_name, file_upload, prompt, context_info=f"Tashkentskiy PDF: {os.path.basename(pdf_path)}")
        data = json.loads(response.text)
        logger.info(f"Parsed PDF: {data}")
        return data
    except Exception as e:
        logger.error(f"Failed Tashkentskiy PDF: {e}")
        return {}
    finally:
        client.files.delete(name=file_upload.name)
