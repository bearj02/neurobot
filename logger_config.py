import logging

def setup_logger():
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger = logging.getLogger('global_logger')
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    return logger

global_logger = setup_logger()
