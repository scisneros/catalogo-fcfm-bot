import json
import sys
from datetime import datetime, timedelta
from os import path

import requests
from bs4 import BeautifulSoup
from requests import RequestException
from telegram.ext import Updater, CommandHandler

from config.auth import token, admin_ids
from config.logger import logger
from config.persistence import persistence
from constants import *
from utils import full_strip, parse_horario, horarios_to_string, try_msg

last_check_time = datetime.now()

data = {}  # Lista de cursos de última consulta
new_data = {}  # Lista de cursos de nueva consulta


# Ejemplo de estructura de data:
# data = {"5": {"CC3001": {nombre: "Algoritmos y Estructuras de Datos",
#                          secciones: {"1": {profesor: ["Jérémy Barbay"],
#                                            cupos: "90",
#                                            horario: {catedra: ["Martes 10:15 - 11:45",
#                                                                "Jueves 10:15 - 11:45"],
#                                                      auxiliar: ["Viernes 14:30 - 16:00"]}
#                                           }
#                                     },
#                                     {"2": {profesor: ["Patricio Poblete",
#                                                       "Nelson Baloian T."],
#                                            cupos: "90",
#                                            horario: {catedra: ["Lunes 14:30 - 16:00",
#                                                                "Miércoles 14:30 - 16:00"],
#                                                      auxiliar: ["Viernes 14:30 - 16:00"],
#                                                      control: [
#                                                                ["Jueves 18:00 - 19:30"]
#                                                                ["8", "14"]  # Semanas
#                                                               ]}
#                                           }
#                                     }
#                         },
#               "CC3002": {nombre: "Metodologías de Diseño y Programación",
#                           ...
#                         }
#              }
#


def parse_catalog():
    logger.info("Scraping catalog...")
    result = {}
    cursos_cnt = 0
    secciones_cnt = 0
    i = 0
    for dept_id in DEPTS:
        i += 1
        dept_data = {}
        url = "https://ucampus.uchile.cl/m/fcfm_catalogo/?semestre={}{}&depto={}".format(YEAR, SEMESTER, dept_id)
        sys.stdout.write("\r Scraping catalog {} of {}".format(i, len(DEPTS)))
        try:
            response = requests.get(url)
        except RequestException as e:
            logger.error("Connection error: {}".format(e))
            raise RequestException("Connection error on scraping")
        soup = BeautifulSoup(response.content, 'html.parser')
        for curso_tag in soup.find_all("div", class_="ramo"):
            cursos_cnt += 1
            curso_str = full_strip(curso_tag.find("h2").contents[0]).split(" ", 1)
            curso_id = curso_str[0]
            curso_nombre = curso_str[1]
            curso_secciones = {}
            for seccion_tag in curso_tag.find("tbody").find_all("tr"):
                secciones_cnt += 1
                seccion_data = seccion_tag.find_all("td")
                seccion_id = seccion_tag["id"].split("-")[1]
                seccion_profesores = []
                for tag in seccion_data[1].find_all("h1"):
                    seccion_profesores.append(full_strip(tag.text))
                seccion_cupos = full_strip(seccion_data[2].text)
                seccion_horarios = parse_horario(seccion_data[4].contents)
                seccion_dict = {"profesores": seccion_profesores,
                                "cupos": seccion_cupos,
                                "horarios": seccion_horarios}
                curso_secciones[seccion_id] = seccion_dict

            dept_data[curso_id] = {"nombre": curso_nombre, "secciones": curso_secciones}

        result[dept_id] = dept_data

    sys.stdout.write("\nFinished scraping\n")

    with open(path.relpath('excluded/catalogdata.json'), "w") as datajsonfile:
        json.dump(result, datajsonfile, indent=4)

    logger.info("Finished scraping, found %s cursos with %s secciones", cursos_cnt, secciones_cnt)
    return result


def check_catalog(context):
    global data, new_data, last_check_time
    try:
        new_data = parse_catalog()
    except RequestException:
        logger.error("Aborting check.")
        return

    logger.info("Looking for changes...")

    all_changes = {}

    for d_id in DEPTS:
        old_cursos = data.get(d_id, {}).keys()
        new_cursos = new_data.get(d_id, {}).keys()
        ocs = set(old_cursos)
        ncs = set(new_cursos)
        added = [x for x in new_cursos if x not in ocs]
        deleted = [x for x in old_cursos if x not in ncs]
        inter = [x for x in old_cursos if x in ncs]
        modified = {}
        d_data = data[d_id]
        d_new_data = new_data[d_id]
        for c_id in inter:
            mods = {}
            if d_data[c_id]["nombre"] != d_new_data[c_id]["nombre"]:
                mods["nombre"] = [d_data[c_id]["nombre"], d_new_data[c_id]["nombre"]]
            old_secciones = set(d_data[c_id]["secciones"].keys())
            new_secciones = set(d_new_data[c_id]["secciones"].keys())
            changes_sec = {}
            added_sec = new_secciones - old_secciones
            deleted_sec = old_secciones - new_secciones
            inter_sec = old_secciones & new_secciones
            modified_sec = {}
            for s_id in inter_sec:
                mods_sec = {}
                s_id = str(s_id)
                if d_data[c_id]["secciones"][s_id]["profesores"] != d_new_data[c_id]["secciones"][s_id]["profesores"]:
                    mods_sec["profesores"] = [d_data[c_id]["secciones"][s_id]["profesores"],
                                              d_new_data[c_id]["secciones"][s_id]["profesores"]]
                if d_data[c_id]["secciones"][s_id]["cupos"] != d_new_data[c_id]["secciones"][s_id]["cupos"]:
                    mods_sec["cupos"] = [d_data[c_id]["secciones"][s_id]["cupos"],
                                         d_new_data[c_id]["secciones"][s_id]["cupos"]]
                if d_data[c_id]["secciones"][s_id]["horarios"] != d_new_data[c_id]["secciones"][s_id]["horarios"]:
                    mods_sec["horarios"] = [d_data[c_id]["secciones"][s_id]["horarios"],
                                            d_new_data[c_id]["secciones"][s_id]["horarios"]]
                if len(mods_sec) > 0:
                    modified_sec[s_id] = mods_sec

            if len(added_sec) > 0:
                changes_sec["added"] = added_sec
            if len(deleted_sec) > 0:
                changes_sec["deleted"] = deleted_sec
            if len(modified_sec) > 0:
                changes_sec["modified"] = modified_sec

            if len(changes_sec) > 0:
                mods["secciones"] = changes_sec

            if len(mods) > 0:
                modified[c_id] = mods

        if added or deleted or modified:
            all_changes[d_id] = {}
            if added:
                all_changes[d_id]["added"] = added
            if deleted:
                all_changes[d_id]["deleted"] = deleted
            if modified:
                all_changes[d_id]["modified"] = modified

    if len(all_changes) > 0:
        logger.info("Changes detected on %s", str([x for x in all_changes]))
        notify_changes(all_changes, context)
    else:
        logger.info("No changes detected")
    data = new_data
    last_check_time = datetime.now()


def notify_changes(all_changes, context):
    chats_data = context.job.context.chat_data
    changes_dict = {}
    for d_id in all_changes:
        changes_str = changes_to_string(all_changes[d_id], d_id)
        changes_dict[d_id] = changes_str

    # for chat_id in admin_ids:  # DEBUG, send only to admin
    for chat_id in chats_data:
        subscribed_deptos = chats_data[int(chat_id)].setdefault("subscribed_deptos", [])
        subscribed_cursos = chats_data[int(chat_id)].setdefault("subscribed_cursos", [])
        dept_matches = [x for x in subscribed_deptos if x in all_changes]
        curso_matches = [x for x in subscribed_cursos if (x[0] in all_changes and x[1] in all_changes[x[0]])]
        if dept_matches or curso_matches:
            try_msg(context.bot, attempts=2,
                    parse_mode="HTML",
                    chat_id=chat_id,
                    text="\U00002757 ¡He detectado cambios en tus suscripciones!\n"
                         "<i>Último chequeo {}</i>".format(last_check_time.strftime("%H:%M:%S")))
            for d_id in dept_matches:
                try_msg(context.bot, attempts=2,
                        chat_id=chat_id,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                        text=("<b>Cambios en {}</b>"
                              "\n{}\n"
                              "<a href='https://ucampus.uchile.cl/m/fcfm_catalogo/?semestre={}{}&depto={}'>"
                              "\U0001F50D Ver catálogo</a>"
                              ).format(DEPTS[d_id][1], changes_dict[d_id], YEAR, SEMESTER, d_id)
                        )
            for d_c_id in curso_matches:
                d_id = d_c_id[0]
                c_id = d_c_id[1]
                change_type_str = ""
                curso_changes_str = ""
                if c_id in all_changes[d_id]["added"]:
                    change_type_str = "Curso añadido:"
                    curso_changes_str = added_curso_string(c_id, d_id)
                elif c_id in all_changes[d_id]["deleted"]:
                    change_type_str = "Curso eliminado:"
                    curso_changes_str = deleted_curso_string(c_id, d_id)
                elif c_id in all_changes[d_id]["modified"]:
                    change_type_str = "Curso modificado:"
                    curso_changes_str = modified_curso_string(c_id, d_id, all_changes[d_id]["modified"][c_id])
                try_msg(context.bot, attempts=2,
                        chat_id=chat_id,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                        text=("<b>{}</b>"
                              "\n{}\n"
                              "<a href='https://ucampus.uchile.cl/m/fcfm_catalogo/?semestre={}{}&depto={}'>"
                              "\U0001F50D Ver catálogo</a>"
                              ).format(change_type_str, curso_changes_str, YEAR, SEMESTER, d_id)
                        )


def added_curso_string(curso_id, depto_id):
    result = ""
    curso = new_data[depto_id][curso_id]
    result += "\U0001F4D7 <b>{} {}</b>\n".format(curso_id, curso["nombre"])
    for seccion_id in curso["secciones"]:
        seccion = curso["secciones"][seccion_id]
        profs = ", ".join(seccion["profesores"])
        result += "    S{} - {} - {} cupos\n".format(seccion_id, profs, seccion["cupos"])
        result += horarios_to_string(seccion["horarios"], 8)
    return result


def deleted_curso_string(curso_id, depto_id):
    result = ""
    curso = data[depto_id][curso_id]
    result += "\U0001F4D9 <b>{} {}</b>\n".format(curso_id, curso["nombre"])
    return result


def modified_curso_string(curso_id, depto_id, curso_mods):
    result = ""
    if "nombre" in curso_mods:
        result += "\U0001F4D8 <b>{}</b> _{}_\n_Renombrado:_ <b>{}</b>".format(curso_id,
                                                                              curso_mods["nombre"][0],
                                                                              curso_mods["nombre"][1])
    else:
        result += "\U0001F4D8 <b>{} {}</b>\n".format(curso_id, new_data[depto_id][curso_id]["nombre"])
    if "secciones" in curso_mods:
        if "added" in curso_mods["secciones"]:
            result += "    <i>Secciones añadidas:</i>\n"
            for seccion_id in curso_mods["secciones"]["added"]:
                seccion = new_data[depto_id][curso_id]["secciones"][seccion_id]
                profs = ", ".join(seccion["profesores"])
                result += "    \U00002795 Secc. {} - {} - {} cupos\n".format(seccion_id, profs,
                                                                             seccion["cupos"])
                result += horarios_to_string(seccion["horarios"], 8)
        if "deleted" in curso_mods["secciones"]:
            result += "    <i>Secciones eliminadas:</i>\n"
            for seccion_id in curso_mods["secciones"]["deleted"]:
                seccion = new_data[depto_id][curso_id]["secciones"][seccion_id]
                profs = ", ".join(seccion["profesores"])
                result += "    \U00002796 Secc. {} - {}\n".format(seccion_id, profs)
        if "modified" in curso_mods["secciones"]:
            result += "    <i>Secciones modificadas:</i>\n"
            for seccion_id in curso_mods["secciones"]["modified"]:
                seccion_mods = curso_mods["secciones"]["modified"][seccion_id]
                if "profesores" in seccion_mods:
                    result += "    \U00003030 <b>Sección {}</b>\n".format(seccion_id)
                    result += "        Cambia profesor\n".format(seccion_id)
                    result += "        \U00002013 de: <i>{}</i>\n".format(
                        ", ".join(seccion_mods["profesores"][0]))
                    result += "        \U00002013 a: <b>{}</b>\n".format(
                        ", ".join(seccion_mods["profesores"][1]))
                else:
                    profs = ", ".join(new_data[depto_id][curso_id]["secciones"][seccion_id]["profesores"])
                    result += "    \U00003030 <b>Sección {}</b> - {}\n".format(seccion_id, profs)
                if "cupos" in seccion_mods:
                    result += "        Cambia cupos\n".format(seccion_id)
                    result += "        \U00002013 de: <i>{}</i>\n".format(seccion_mods["cupos"][0])
                    result += "        \U00002013 a: <b>{}</b>\n".format(seccion_mods["cupos"][1])
                if "horarios" in seccion_mods:
                    result += "        Cambia horario\n".format(seccion_id)
                    result += "        \U00002013 de:\n{}".format(
                        horarios_to_string(seccion_mods["horarios"][0], 12))
                    result += "        \U00002013 a:\n{}".format(
                        horarios_to_string(seccion_mods["horarios"][1], 12))
    return result


def changes_to_string(changes, depto_id):
    added = changes.get("added", [])
    deleted = changes.get("deleted", [])
    modified = changes.get("modified", [])
    changes_str = ""
    if len(added) > 0:
        changes_str += "\n<i>Cursos añadidos:</i>\n"
        for curso_id in added:
            changes_str += added_curso_string(curso_id, depto_id)
    if len(deleted) > 0:
        changes_str += "\n<i>Cursos eliminados:</i>\n"
        for curso_id in deleted:
            deleted_curso_string(curso_id, depto_id)
    if len(modified) > 0:
        changes_str += "\n<i>Cursos modificados:</i>\n"
        for curso_id in modified:
            changes_str += modified_curso_string(curso_id, depto_id, modified[curso_id])

    return changes_str


def start(update, context):
    logger.info("[Command /start]")
    if context.chat_data.get("enable", False):
        try_msg(context.bot,
                chat_id=update.message.chat_id,
                text="¡Mis avisos para este chat ya están activados! El próximo chequeo será apróximadamente a las "
                     + (last_check_time + timedelta(seconds=900)).strftime("%H:%M") +
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
            except ValueError:
                failed.append(arg)
                continue

            if d_arg in DEPTS:
                if "subscribed_cursos" not in context.chat_data:
                    context.chat_data["subscribed_cursos"] = []
                if (d_arg, c_arg) not in context.chat_data["subscribed_cursos"]:
                    context.chat_data["subscribed_cursos"].append((d_arg, c_arg))
                    is_curso_known = c_arg in data[d_arg]
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
            response += "Te avisaré si aparece algún curso con ese nombre en ese depto.\n\n"
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
                    text="He registrado tus suscripciones ¡Pero los avisos para este chat están desactivados!.\n"
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
        notsuscribed = []
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
                    notsuscribed.append((d_arg, c_arg))
            else:
                failed_depto.append((d_arg, c_arg))
        response = ""
        if deleted:
            response += "\U0001F6D1 Dejaré de avisarte sobre cambios en:\n<i>{}</i>\n\n" \
                .format("\n".join([("- " + x[1] + " de " + DEPTS[x[0]][1] + " ({})".format(x[0])) for x in deleted]))
        if notsuscribed:
            response += "\U0001F44D No estás suscrito a\n<i>{}</i>\n\n" \
                .format("\n".join([("- " + x[1] + " de " + DEPTS[x[0]][1] + " ({})".format(x[0])) for x in notsuscribed]))
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

    result = "Actualmente doy los siguientes avisos para este chat:\n\n"
    result += "<b>Avisos activados:</b> <i>{}</i>\n\n"\
        .format("Sí \U00002714" if context.chat_data.get("enable", False) else "No \U0000274C")
    if sub_deptos_list:
        result += "<b>Avisos por departamento:</b>\n"
        result += "\n".join(sub_deptos_list)
        result += "\n\n"
    if sub_cursos_list:
        result += "<b>Avisos por curso:</b>\n"
        result += "\n".join(sub_cursos_list)
        result += "\n\n"
    try_msg(context.bot,
            chat_id=update.message.chat_id,
            parse_mode="HTML",
            text=result)


def force_check(update, context):
    if int(update.message.from_user.id) in admin_ids:
        logger.info("[Command /force_check from admin %s]", update.message.from_user.id)
        job_check = context.job_queue.get_jobs_by_name("job_check")[0]
        job_check.run(job_check.context)


def get_log(update, context):
    if int(update.message.from_user.id) in admin_ids:
        logger.info("[Command /get_log from admin %s]", update.message.from_user.id)
        send_document(chat_id=update.message.from_user.id, document=open(path.relpath('bot.log'), 'rb'), filename=CataLog)


def main():
    updater = Updater(token=token, use_context=True, persistence=persistence)
    dp = updater.dispatcher
    jq = updater.job_queue

    jq.run_repeating(check_catalog, interval=900, context=dp, name="job_check")

    dp.add_handler(CommandHandler('start', start))
    dp.add_handler(CommandHandler('stop', stop))
    dp.add_handler(CommandHandler('suscribir_depto', subscribe_depto))
    dp.add_handler(CommandHandler('suscribir_curso', subscribe_curso))
    dp.add_handler(CommandHandler('desuscribir_depto', unsubscribe_depto))
    dp.add_handler(CommandHandler('desuscribir_curso', unsubscribe_curso))
    dp.add_handler(CommandHandler('deptos', deptos))
    dp.add_handler(CommandHandler('suscripciones', subscriptions))
    # Admin commands
    dp.add_handler(CommandHandler('force_check', force_check))
    dp.add_handler(CommandHandler('get_log', get_log))

    global data
    data = parse_catalog()

    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()
