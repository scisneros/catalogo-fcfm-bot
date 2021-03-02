from datetime import datetime

from telegram.ext import Updater

from config.auth import token
from config.persistence import persistence

last_check_time = datetime.now()

current_data = {}  # Lista de cursos de última consulta
new_data = {}  # Lista de cursos de nueva consulta


updater = Updater(token=token, use_context=True, persistence=persistence)
dp = updater.dispatcher
jq = updater.job_queue
job_check_results = None
job_check_changes = None

config = {}
