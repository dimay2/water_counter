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


def compute_expected_prefixes(prev_val: int, max_delta: int = 30, prefix_len: int = 3, width: int = 5) -> list[str]:
    """Return ordered unique zero-padded leading prefixes covering [prev_val, prev_val + max_delta]."""
    seen = []
    modulus = 10 ** width
    for val in range(prev_val, prev_val + max_delta + 1):
        prefix = f"{val % modulus:0{width}d}"[:prefix_len]
        if prefix not in seen:
            seen.append(prefix)
    return seen


def format_meter_context(label: str, prev_val, max_delta: int = 30) -> str:
    """Build rollover-aware historical reading guidance for a single 5-digit mechanical meter."""
    try:
        prev_int = int(float(prev_val)) if prev_val is not None else 0
    except (ValueError, TypeError):
        prev_int = 0

    if prev_int <= 0:
        return f"- {label}: No previous reading available; read the digits strictly from left to right."

    min_str = f"{prev_int % 100000:05d}"
    max_str = f"{(prev_int + max_delta) % 100000:05d}"
    prefixes_3 = compute_expected_prefixes(prev_int, max_delta=max_delta, prefix_len=3, width=5)
    prefixes_2 = compute_expected_prefixes(prev_int, max_delta=max_delta, prefix_len=2, width=5)

    prefix_3_str = " or ".join(f'"{p}"' for p in prefixes_3)
    rollover_note = ""
    if len(prefixes_3) > 1:
        rollover_note = f" (accounts for digit rollover across {min_str}..{max_str})"
    if len(prefixes_2) > 1:
        prefix_2_str = " or ".join(f'"{p}"' for p in prefixes_2)
        rollover_note += f"; valid first 2 digits: {prefix_2_str}"

    return (
        f"- {label}: Previous reading was {min_str}. Current reading should be >= {min_str} and within normal "
        f"monthly consumption (plausible range: {min_str} to {max_str}; expected first 3 digits: {prefix_3_str}{rollover_note})."
    )


def build_rumyantsevo_context(prev_val_left, prev_val_right, max_delta: int = 30) -> str:
    """Format historical context block for the two Rumyantsevo meters (left/upper, right/lower)."""
    left_line = format_meter_context("Left/upper meter (1st item in array)", prev_val_left, max_delta=max_delta)
    right_line = format_meter_context("Right/lower meter (2nd item in array)", prev_val_right, max_delta=max_delta)
    return (
        f"{left_line}\n"
        f"{right_line}\n"
        "Use this historical context ONLY to resolve glare, shadows, or ambiguous digits—always read the actual physical dials carefully."
    )


def build_tashkentskiy_context(prev_val, max_delta: int = 30) -> str:
    """Format historical context block for a single Tashkentskiy meter."""
    line = format_meter_context("Target meter", prev_val, max_delta=max_delta)
    return (
        f"{line}\n"
        "Use this historical context ONLY to resolve dark shadows, glare, or ambiguities—always read the actual physical dials carefully."
    )
