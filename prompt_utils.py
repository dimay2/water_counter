import os
import json
import logging

logger = logging.getLogger(__name__)

PROMPTS_FILE = 'prompts.json'

_CACHED_PROMPTS = None

def load_prompts():
    global _CACHED_PROMPTS
    if _CACHED_PROMPTS is None:
        if os.path.exists(PROMPTS_FILE):
            try:
                with open(PROMPTS_FILE, 'r', encoding='utf-8') as f:
                    raw_prompts = json.load(f)
                    if isinstance(raw_prompts, list):
                        _CACHED_PROMPTS = {p['name']: p['content'] for p in raw_prompts if 'name' in p and 'content' in p}
                    else:
                        _CACHED_PROMPTS = raw_prompts
            except Exception as e:
                logger.error(f"Could not read {PROMPTS_FILE}: {e}")
        else:
            logger.error(f"Prompts file not found: {PROMPTS_FILE}")
        if _CACHED_PROMPTS is None:
            _CACHED_PROMPTS = {}
    return _CACHED_PROMPTS
