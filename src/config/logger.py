import logging
from logging.handlers import RotatingFileHandler

log_formatter = logging.Formatter('%(asctime)s %(levelname)s - %(message)s - [%(funcName)s:%(lineno)d]')

logFile = '../bot.log'

# 3 MB max files, up to 2 backup files.
my_handler = RotatingFileHandler(logFile, mode='a', maxBytes=3*1024*1024, backupCount=2, encoding=None, delay=0)
my_handler.setFormatter(log_formatter)
my_handler.setLevel(logging.INFO)

logger = logging.getLogger('CatalogoFCFMBot')
logger.setLevel(logging.INFO)
logger.addHandler(my_handler)
