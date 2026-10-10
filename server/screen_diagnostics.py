"""Shared metadata-only logging. Never pass credentials or image content."""
import logging

logger = logging.getLogger('screenvision')
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('SCREEN_VISION %(message)s'))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False


def log(event, **fields):
    output = logger.debug if event in ('request','capture_start','capture_success') else logger.info
    output('%s %s', event, ' '.join(f'{key}={value}' for key, value in fields.items()))
