import json
import os
import pickle
import tempfile
from datetime import timedelta, datetime

import data
from config.auth import admin_ids
from config.logger import logger
from constants import DEPTS
from data import jq, dp
from utils import try_msg


def start(update, context):
    logger.info("[Command /start]")
    if context.chat_data.get("enable", False):
        try_msg(context.bot,
                chat_id=update.message.chat_id,
                text="¡Mis avisos para este chat ya están activados! El próximo chequeo será apróximadamente a las "
                     + (data.last_check_time + timedelta(seconds=300)).strftime("%H:%M") +
                     ".\nRecuerda configurar los avisos de este chat usando /suscribir_depto o /suscribir_curso"
                )
    else:
        context.chat_data["enable"] = True
        try_msg(context.bot,
                chat_id=update.message.chat_id,
                text="A partir de ahora avisaré por este chat si detecto algún cambio en el catálogo de cursos."
                     "\nRecuerda configurar los avisos de este chat usando /suscribir_depto o /suscribir_curso"
                )


def stop(update, context):
    logger.info("[Command /stop]")
    context.chat_data["enable"] = False
    try_msg(context.bot,
            chat_id=update.message.chat_id,
            text="Ok, dejaré de avisar cambios en el catálogo por este chat. "
                 "Puedes volver a activar los avisos enviándome /start nuevamente."
            )


def subscribe_depto(update, context):
    logger.info("[Command /suscribir_depto]")
    if context.args:
        added = []
        already = []
        failed = []
        for arg in context.args:
            if arg in DEPTS:
                if "subscribed_deptos" not in context.chat_data:
                    context.chat_data["subscribed_deptos"] = []
                if arg not in context.chat_data["subscribed_deptos"]:
                    added.append(arg)
                    context.chat_data["subscribed_deptos"].append(arg)
                else:
                    already.append(arg)
            else:
                failed.append(arg)
        response = ""
        if added:
            response += "\U0001F4A1 Te avisaré sobre los cambios en:\n<i>{}</i>\n\n" \
                .format("\n".join(["- " + DEPTS[x][1] + " ({})".format(x) for x in added]))
        if already:
            response += "\U0001F44D Ya te habías suscrito a:\n<i>{}</i>\n\n" \
                .format("\n".join(["- " + DEPTS[x][1] + " ({})".format(x) for x in already]))
        if failed:
            response += "\U0001F914 No pude identificar ningún departamento asociado a:\n<i>{}</i>\n\n"\
                .format("\n".join(["- " + str(x) for x in failed]))
            response += "Puedo recordarte la lista de /deptos que reconozco.\n"

        try_msg(context.bot,
                chat_id=update.message.chat_id,
                parse_mode="HTML",
                text=response)

        if added and not context.chat_data.get("enable", False):
            try_msg(context.bot,
                    chat_id=update.message.chat_id,
                    parse_mode="HTML",
                    text="He registrado tus suscripciones ¡Pero los avisos para este chat están desactivados!.\n"
                         "Actívalos enviándome /start")
    else:
        try_msg(context.bot,
                chat_id=update.message.chat_id,
                parse_mode="HTML",
                text="Debes decirme qué departamentos deseas monitorear.\n<i>Ej. /suscribir_depto 5 21 9</i>\n\n"
                     "Para ver la lista de códigos de deptos que reconozco envía /deptos")


def subscribe_curso(update, context):
    logger.info("[Command /suscribir_curso]")
    if context.args:
        added = []
        already = []
        unknown = []
        failed = []
        failed_depto = []
        for arg in context.args:
            try:
                (d_arg, c_arg) = arg.split("-")
                c_arg = c_arg.upper()
            except ValueError:
                failed.append(arg)
                continue

            if d_arg in DEPTS:
                if "subscribed_cursos" not in context.chat_data:
                    context.chat_data["subscribed_cursos"] = []
                if (d_arg, c_arg) not in context.chat_data["subscribed_cursos"]:
                    context.chat_data["subscribed_cursos"].append((d_arg, c_arg))
                    is_curso_known = c_arg in data.current_data[d_arg]
                    if is_curso_known:
                        added.append((d_arg, c_arg))
                    else:
                        unknown.append((d_arg, c_arg))
                else:
                    already.append((d_arg, c_arg))
            else:
                failed_depto.append((d_arg, c_arg))
        response = ""
        if added:
            response += "\U0001F4A1 Te avisaré sobre cambios en:\n<i>{}</i>\n\n" \
                .format("\n".join(["- " + (x[1] + " de " + DEPTS[x[0]][1] + " ({})".format(x[0])) for x in added]))
        if unknown:
            response += "\U0001F4A1 Actualmente no tengo registros de:\n<i>{}</i>\n" \
                .format("\n".join(["- " + (x[1] + " en " + DEPTS[x[0]][1] + " ({})".format(x[0])) for x in unknown]))
            response += "Te avisaré si aparece algún curso con ese código en ese depto.\n\n"
        if already:
            response += "\U0001F44D Ya estabas suscrito a:\n<i>{}</i>.\n\n" \
                .format("\n".join(["- " + (x[1] + " de " + DEPTS[x[0]][1] + " ({})".format(x[0])) for x in already]))
        if failed_depto:
            response += "\U0001F914 No pude identificar ningún departamento asociado a:\n<i>{}</i>\n\n" \
                .format("\n".join(["- " + x[0] for x in failed_depto]))
            response += "Puedo recordarte la lista de /deptos que reconozco.\n"
        if failed:
            response += "\U0001F914 No pude identificar el par <i>'depto-curso'</i> en:\n<i>{}</i>\n\n"\
                .format("\n".join(["- " + str(x) for x in failed]))
            response += "Guíate por el formato del ejemplo:\n" \
                        "<i>Ej. /suscribir_curso 5-CC3001 21-MA1002</i>\n"

        try_msg(context.bot,
                chat_id=update.message.chat_id,
                parse_mode="HTML",
                text=response)

        if (added or unknown) and not context.chat_data.get("enable", False):
            try_msg(context.bot,
                    chat_id=update.message.chat_id,
                    parse_mode="HTML",
                    text="He registrado tus suscripciones ¡Pero los avisos para este chat están desactivados!\n"
                         "Actívalos enviándome /start")
    else:
        try_msg(context.bot,
                chat_id=update.message.chat_id,
                parse_mode="HTML",
                text="Debes decirme qué cursos deseas monitorear en la forma <i>'depto-curso'</i> para registrarlo.\n"
                     "<i>Ej. /suscribir_curso 5-CC3001 21-MA1002</i>\n\n"
                     "Para ver la lista de códigos de deptos que reconozco envía /deptos")


def unsubscribe_depto(update, context):
    logger.info("[Command /desuscribir_depto]")
    if context.args:
        deleted = []
        notsuscribed = []
        failed = []
        for arg in context.args:
            if arg in DEPTS:
                if arg in context.chat_data["subscribed_deptos"]:
                    deleted.append(arg)
                    context.chat_data["subscribed_deptos"].remove(arg)
                else:
                    notsuscribed.append(arg)
            else:
                failed.append(arg)
        response = ""

        if deleted:
            response += "\U0001F6D1 Dejaré de avisarte sobre cambios en:\n<i>{}</i>\n\n" \
                .format("\n".join(["- " + DEPTS[x][1] + " ({})".format(x) for x in deleted]))
        if notsuscribed:
            response += "\U0001F44D No estás suscrito a <i>{}</i>.\n" \
                .format("\n".join(["- " + DEPTS[x][1] + " ({})".format(x) for x in notsuscribed]))
        if failed:
            response += "\U0001F914 No pude identificar ningún departamento asociado a\n:<i>{}</i>\n\n"\
                .format("\n".join(["- " + str(x) for x in failed]))
            response += "Puedo recordarte la lista de /deptos que reconozco.\n"

        response += "\nRecuerda que puedes apagar temporalmente todos los avisos usando /stop, " \
                    "sin perder tus suscripciones"

        try_msg(context.bot,
                chat_id=update.message.chat_id,
                parse_mode="HTML",
                text=response)
    else:
        try_msg(context.bot,
                chat_id=update.message.chat_id,
                parse_mode="HTML",
                text="Indícame qué departamentos quieres dejar de monitorear.\n"
                     "<i>Ej. /desuscribir_depto 5 21</i>\n\n"
                     "Para ver las suscripciones de este chat envía /suscripciones\n"
                     "Para ver la lista de códigos de deptos que reconozco envía /deptos\n")


def unsubscribe_curso(update, context):
    logger.info("[Command /desuscribir_curso]")
    if context.args:
        deleted = []
        notsub = []
        failed = []
        failed_depto = []
        for arg in context.args:
            try:
                (d_arg, c_arg) = arg.split("-")
            except ValueError:
                failed.append(arg)
                continue

            if d_arg in DEPTS:
                if "subscribed_cursos" not in context.chat_data:
                    context.chat_data["subscribed_cursos"] = []
                if (d_arg, c_arg) in context.chat_data["subscribed_cursos"]:
                    deleted.append((d_arg, c_arg))
                    context.chat_data["subscribed_cursos"].remove((d_arg, c_arg))
                else:
                    notsub.append((d_arg, c_arg))
            else:
                failed_depto.append((d_arg, c_arg))
        response = ""
        if deleted:
            response += "\U0001F6D1 Dejaré de avisarte sobre cambios en:\n<i>{}</i>\n\n" \
                .format("\n".join([("- " + x[1] + " de " + DEPTS[x[0]][1] + " ({})".format(x[0])) for x in deleted]))
        if notsub:
            response += "\U0001F44D No estás suscrito a\n<i>{}</i>\n\n" \
                .format("\n".join([("- " + x[1] + " de " + DEPTS[x[0]][1] + " ({})".format(x[0])) for x in notsub]))
        if failed_depto:
            response += "\U0001F914 No pude identificar ningún departamento asociado a:\n<i>{}</i>\n\n" \
                .format("\n".join(["- " + x[0] for x in failed_depto]))
            response += "Puedo recordarte la lista de /deptos que reconozco.\n"
        if failed:
            response += "\U0001F914 No pude identificar el par <i>'depto-curso'</i> en:\n<i>{}</i>\n\n"\
                .format("\n".join(["- " + str(x) for x in failed]))
            response += "Guíate por el formato del ejemplo:\n" \
                        "<i>Ej. /desuscribir_curso 5-CC3001 21-MA1002</i>\n"

        response += "\nRecuerda que puedes apagar temporalmente todos los avisos usando /stop, " \
                    "sin perder tus suscripciones"
        try_msg(context.bot,
                chat_id=update.message.chat_id,
                parse_mode="HTML",
                text=response)
    else:
        try_msg(context.bot,
                chat_id=update.message.chat_id,
                parse_mode="HTML",
                text="Indícame qué cursos quieres dejar de monitorear.\n"
                     "<i>Ej. /desuscribir_curso 5-CC3001 21-MA1002</i>\n\n"
                     "Para ver las suscripciones de este chat envía /suscripciones\n"
                     "Para ver la lista de códigos de deptos que reconozco envía /deptos\n")


def deptos(update, context):
    logger.info("[Command /deptos]")
    deptos_list = ["<b>{}</b> - <i>{} {}</i>".format(x, DEPTS[x][0], DEPTS[x][1]) for x in DEPTS]

    try_msg(context.bot,
            chat_id=update.message.chat_id,
            parse_mode="HTML",
            text="Estos son los códigos que representan a cada departamento o área. "
                 "Utilizaré los mismos códigos que usa U-Campus para facilitar la consistencia\n"
                 "\n{}".format("\n".join(deptos_list)))


def subscriptions(update, context):
    logger.info("[Command /suscripciones]")
    subscribed_deptos = context.chat_data.get("subscribed_deptos", [])
    subscribed_cursos = context.chat_data.get("subscribed_cursos", [])

    sub_deptos_list = ["- <b>({})</b>    <i>{} {}</i>".format(x, DEPTS[x][0], DEPTS[x][1]) for x in subscribed_deptos]
    sub_cursos_list = ["- <b>({}-{})</b>    <i>{} en {} {}</i>"
                           .format(x[0], x[1], x[1], DEPTS[x[0]][0], DEPTS[x[0]][1]) for x in subscribed_cursos]

    result = "<b>Avisos activados:</b> <i>{}</i>\n\n" \
        .format("Sí \U00002714 (Detener: /stop)" if context.chat_data.get("enable", False)
                             else "No \U0000274C (Activar: /start)")

    if sub_deptos_list or sub_cursos_list:
        result += "Actualmente doy los siguientes avisos para este chat:\n\n"
    else:
        result += "Actualmente no tienes suscripciones a ningún departamento o curso.\n" \
                  "Suscribe avisos con /suscribir_depto o /suscribir_curso."

    if sub_deptos_list:
        result += "<b>Avisos por departamento:</b>\n"
        result += "\n".join(sub_deptos_list)
        result += "\n\n"
    if sub_cursos_list:
        result += "<b>Avisos por curso:</b>\n"
        result += "\n".join(sub_cursos_list)
        result += "\n\n"

    if sub_deptos_list or sub_cursos_list:
        result += "<i>Puedes desuscribirte con /desuscribir_depto y /desuscribir_curso.</i>"
    try_msg(context.bot,
            chat_id=update.message.chat_id,
            parse_mode="HTML",
            text=result)


def force_check(update, context):
    if int(update.message.from_user.id) in admin_ids:
        logger.info("[Command /force_check from admin %s]", update.message.from_user.id)
        job_check = jq.get_jobs_by_name("job_check")[0]
        job_check.run(dp)


def get_log(update, context):
    if int(update.message.from_user.id) in admin_ids:
        logger.info("[Command /get_log from admin %s]", update.message.from_user.id)
        context.bot.send_document(chat_id=update.message.from_user.id,
                                  document=open(os.path.relpath('bot.log'), 'rb'),
                                  filename="catalogobot_log_{}.txt"
                                  .format(datetime.now().strftime("%d%b%Y-%H%M%S")))


def get_chats_data(update, context):
    if int(update.message.from_user.id) in admin_ids:
        logger.info("[Command /get_chats_data from admin %s]", update.message.from_user.id)
        try:
            db_path = os.path.relpath('db')
            with open(db_path, 'rb') as logfile:
                json_result = json.dumps(pickle.load(logfile), sort_keys=True, indent=4)
            with tempfile.NamedTemporaryFile(delete=False, mode="w+t") as temp_file:
                temp_filename = temp_file.name
                temp_file.write(json_result)
            with open(temp_filename, 'rb') as temp_doc:
                context.bot.send_document(chat_id=update.message.from_user.id,
                                          document=temp_doc,
                                          filename="catalogobot_chat_data_{}.txt"
                                          .format(datetime.now().strftime("%d%b%Y-%H%M%S")))
            os.remove(temp_filename)
        except Exception as e:
            logger.exception(e)


def force_notification(update, context):
    if int(update.message.from_user.id) in admin_ids:
        logger.info("[Command /force_notification from admin %s]", update.message.from_user.id)
        chats_data = dp.chat_data
        if context.args:
            message = update.message.text
            message = message[message.index(" ")+1:].replace("\\", "")
            for chat_id in chats_data:
                try_msg(context.bot,
                        chat_id=chat_id,
                        force=True,
                        text=message,
                        parse_mode="Markdown",
                        )
