from telegram import TelegramError, constants as tg_constants
from telegram.error import BadRequest, Unauthorized, ChatMigrated

from config.logger import logger
from data import dp


def full_strip(st):
    return st.replace("\n", "").replace("\t", "").strip(" ")


def parse_horario(horarios_str):
    result = {"catedra": [],
              "auxiliar": [],
              "control": [[], []]}
    for el in horarios_str:
        if not isinstance(el, str):
            continue
        el = full_strip(el)
        if el.startswith("Cátedra"):
            result["catedra"] = el.lstrip("Cátedra: ").split(", ")
        elif el.startswith("Auxiliar"):
            result["auxiliar"] = el.lstrip("Auxiliar: ").split(", ")
        elif el.startswith("Control"):
            controlsplit = el.split(", Semana: ")
            result["control"][0] = controlsplit[0].lstrip("Control: ").split(", ")
            result["control"][1] = controlsplit[1].split(", ") if len(controlsplit) > 1 else []
    return result


def horarios_to_string(horarios, indent):
    result = ""
    if len(horarios["catedra"]) > 0:
        result += (" " * indent) + "<i>Cátedra: {}</i>\n".format(", ".join(horarios["catedra"]))
    if len(horarios["auxiliar"]) > 0:
        result += (" " * indent) + "<i>Auxiliar: {}</i>\n".format(", ".join(horarios["auxiliar"]))
    if len(horarios["control"][0]) > 0:
        result += (" " * indent) + "<i>Control: {}</i>\n".format(", ".join(horarios["control"][0]))
    if len(horarios["control"][1]) > 0:
        result += (" " * indent) + "<i>Semanas {}</i>\n".format(", ".join(horarios["control"][1]))
    return result


def try_msg(bot, attempts=2, **params):
    chat_id = params["chat_id"]
    attempt = 1
    while attempt <= attempts:
        try:
            bot.send_message(**params)
        except Unauthorized:
            logger.error("Chat %s blocked the bot. Aborting message and disabling for this chat.", chat_id)
            dp.chat_data[chat_id]["enable"] = False
            break
        except ChatMigrated as e:
            logger.info("Chat %s migrated to supergroup %s. Updating in database.", chat_id, e.new_chat_id)
            dp.chat_data[e.new_chat_id] = dp.chat_data[chat_id]
            params["chat_id"] = e.new_chat_id
            attempt -= 1
        except BadRequest as e:
            logger.error("Messaging chat %s raised BadRequest: %s. Aborting message.", chat_id, e)
            raise
        except TelegramError as e:
            logger.error("[Attempt %s/%s] Messaging chat %s raised following error: %s: %s",
                         attempt, attempts, chat_id, type(e).__name__, e)
        else:
            break
        attempt += 1

    if attempt > attempts:
        logger.error("Max attempts reached for chat %s. Aborting message.", str(chat_id))


def send_long_message(bot, **params):
    text = params.pop("text", "")
    maxl = tg_constants.MAX_MESSAGE_LENGTH
    if len(text) > maxl:
        slice_index = maxl
        for i in range(maxl, -1, -1):
            if text[i] == "\n":
                slice_index = i
                break
        sliced_text = text[:slice_index]
        rest_text = text[slice_index + 1:]
        try_msg(bot, text=sliced_text, **params)
        send_long_message(bot, text=rest_text, **params)
    else:
        try_msg(bot, text=text, **params)


def notify_thread(context, chat_id, announce_message, deptos_messages, cursos_messages):
    try_msg(context.bot,
            parse_mode="HTML",
            chat_id=chat_id,
            text=announce_message)
    if dp.chat_data[chat_id].get("enable", False):
        for deptos_message in deptos_messages:
            send_long_message(context.bot,
                              chat_id=chat_id,
                              parse_mode="HTML",
                              disable_web_page_preview=True,
                              text=deptos_message)
        for curso_message in cursos_messages:
            send_long_message(context.bot,
                              chat_id=chat_id,
                              parse_mode="HTML",
                              disable_web_page_preview=True,
                              text=curso_message)
