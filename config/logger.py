import logging
import sys
from logging.handlers import RotatingFileHandler
from logging import StreamHandler
from os import path

# 3 MB max files, up to 2 backup files.
logging.basicConfig(format='%(asctime)s %(levelname)s - %(message)s - [%(funcName)s:%(lineno)d]',
                    level=logging.INFO,
                    handlers=[RotatingFileHandler(path.relpath('bot.log'), mode='a', maxBytes=3*1024*1024,
                                                  backupCount=5, encoding=None, delay=0),
                              StreamHandler(sys.stdout)])

logger = logging.getLogger('CatalogoFCFMBot')