import logging

logging.basicConfig(filename='../bot.log',
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger('CatalogoFCFMBot')
