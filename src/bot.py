from datetime import datetime, timedelta
import logging
import requests
import json

from telegram import TelegramError
from telegram.ext import Updater, CommandHandler
from bs4 import BeautifulSoup

from config.auth import token
from config.persistence import persistence

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger('CatalogoFCFMBot')

last_check_time = datetime.now()

data = {}  # Lista de cursos de última consulta
new_data = {}  # Lista de cursos de nueva consulta


# Ejemplo de estructura de data:
# data = {"CC3001": {nombre: "Algoritmos y Estructuras de Datos",
#                    secciones: [{profesor: ["Jérémy Barbay"],
#                                 cupos: "90",
#                                 horario: {catedra: ["Martes 10:15 - 11:45",
#                                          "Jueves 10:15 - 11:45"],
#                                           auxiliar: ["Viernes 14:30 - 16:00"]}
#                                },
#                                {profesor: ["Patricio Poblete",
#                                            "Nelson Baloian T."],
#                                 cupos: "90",
#                                 horario: {catedra: ["Lunes 14:30 - 16:00",
#                                                     "Miércoles 14:30 - 16:00"],
#                                           auxiliar: ["Viernes 14:30 - 16:00"],
#                                           control: [
#                                                     ["Jueves 18:00 - 19:30"]
#                                                     ["8", "14"]  # Semanas
#                                                    ]}
#                                }
#                               ]
#                   },
#         "CC3002": {nombre: "Metodologías de Diseño y Programación",
#                     ...
#                   }
#        }
#


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
            result["control"][1] = controlsplit[1].split(", ")
    return result


def changes_to_string(added, deleted, modified):
    changes_str = ""
    if len(added) > 0:
        changes_str += "\n<i>Cursos añadidos:</i>\n"
        for curso_id in added:
            curso = new_data[curso_id]
            changes_str += "\U0001F4D7 <b>{} {}</b>\n".format(curso_id, curso["nombre"])
            for seccion_id in curso["secciones"]:
                seccion = curso["secciones"][seccion_id]
                profs = ", ".join(seccion["profesores"])
                changes_str += "    S{} - {} - {} cupos\n".format(seccion_id, profs, seccion["cupos"])
                changes_str += horarios_to_string(seccion["horarios"], 8)
    if len(deleted) > 0:
        changes_str += "\n<i>Cursos eliminados:</i>\n"
        for curso_id in deleted:
            curso = data[curso_id]
            changes_str += "\U0001F4D9 <b>{} {}</b>\n".format(curso_id, curso["nombre"])
    if len(modified) > 0:
        changes_str += "\n<i>Cursos modificados:</i>\n"
        for curso_id in modified:
            curso_mods = modified[curso_id]
            if "nombre" in curso_mods:
                changes_str += "\U0001F4D8 <b>{}</b> _{}_\n_Renombrado:_ <b>{}</b>".format(curso_id,
                                                                                 curso_mods["nombre"][0],
                                                                                 curso_mods["nombre"][1])
            else:
                changes_str += "\U0001F4D8 <b>{} {}</b>\n".format(curso_id, new_data[curso_id]["nombre"])
            if "secciones" in curso_mods:
                if "added" in curso_mods["secciones"]:
                    changes_str += "    <i>Secciones añadidas:</i>\n"
                    for seccion_id in curso_mods["secciones"]["added"]:
                        seccion = new_data[curso_id]["secciones"][seccion_id]
                        profs = ", ".join(seccion["profesores"])
                        changes_str += "    \U00002795 Secc. {} - {} - {} cupos\n".format(seccion_id, profs,
                                                                                          seccion["cupos"])
                        changes_str += horarios_to_string(seccion["horarios"], 8)
                if "deleted" in curso_mods["secciones"]:
                    changes_str += "    <i>Secciones eliminadas:</i>\n"
                    for seccion_id in curso_mods["secciones"]["deleted"]:
                        seccion = new_data[curso_id]["secciones"][seccion_id]
                        profs = ", ".join(seccion["profesores"])
                        changes_str += "    \U00002796 Secc. {} - {}\n".format(seccion_id, profs)
                if "modified" in curso_mods["secciones"]:
                    changes_str += "    <i>Secciones modificadas:</i>\n"
                    for seccion_id in curso_mods["secciones"]["modified"]:
                        seccion_mods = curso_mods["secciones"]["modified"][seccion_id]
                        if "profesores" in seccion_mods:
                            changes_str += "    \U00003030 <b>Sección {}</b>\n".format(seccion_id)
                            changes_str += "        Cambia profesor\n".format(seccion_id)
                            changes_str += "        \U00002013 de: <i>{}</i>\n".format(", ".join(seccion_mods["profesores"][0]))
                            changes_str += "        \U00002013 a: <i>{}</i>\n".format(", ".join(seccion_mods["profesores"][1]))
                        else:
                            profs = ", ".join(new_data[curso_id]["secciones"][seccion_id]["profesores"])
                            changes_str += "    \U00003030 <b>Sección {}</b> - {}\n".format(seccion_id, profs)
                        if "cupos" in seccion_mods:
                            changes_str += "        Cambia cupos\n".format(seccion_id)
                            changes_str += "        \U00002013 de: <i>{}</i>\n".format(seccion_mods["cupos"][0])
                            changes_str += "        \U00002013 a: <b>{}</b>\n".format(seccion_mods["cupos"][1])
                        if "horarios" in seccion_mods:
                            changes_str += "        Cambia horario\n".format(seccion_id)
                            changes_str += "        \U00002013 de:\n{}".format(
                                horarios_to_string(seccion_mods["horarios"][0], 8))
                            changes_str += "        \U00002013 a:\n{}".format(
                                horarios_to_string(seccion_mods["horarios"][1], 8))
    return changes_str


def horarios_to_string(horarios, indent):
    result = ""
    if len(horarios["catedra"]) > 0:
        result += (" "*indent) + "<i>Cátedra: {}</i>\n".format(", ".join(horarios["catedra"]))
    if len(horarios["auxiliar"]) > 0:
        result += (" "*indent) + "<i>Auxiliar: {}</i>\n".format(", ".join(horarios["auxiliar"]))
    if len(horarios["control"][0]) > 0:
        result += (" "*indent) + "<i>Control: {}</i>\n".format(", ".join(horarios["control"][0]))
    if len(horarios["control"][1]) > 0:
        result += (" "*indent) + "<i>Semanas {}</i>\n".format(", ".join(horarios["control"][1]))
    return result


def parse_catalog():
    result = {}
    response = requests.get('https://ucampus.uchile.cl/m/fcfm_catalogo/?semestre=20191&depto=5')
    soup = BeautifulSoup(response.content, 'html.parser')
    for curso_tag in soup.find_all("div", class_="ramo"):
        curso_str = full_strip(curso_tag.find("h2").contents[0]).split(" ", 1)
        curso_id = curso_str[0]
        curso_nombre = curso_str[1]
        curso_secciones = {}
        for seccion_tag in curso_tag.find("tbody").find_all("tr"):
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

        result[curso_id] = {"nombre": curso_nombre, "secciones": curso_secciones}

    with open("../excluded/catalogdata.json", "w") as datajsonfile:
        json.dump(result, datajsonfile, indent=4)

    return result


def check_catalog(context):
    logger.info("Looking for changes...")
    global data, new_data, last_check_time
    new_data = parse_catalog()
    last_check_time = datetime.now()

    old_cursos = set(data.keys())
    new_cursos = set(new_data.keys())
    added = new_cursos - old_cursos
    deleted = old_cursos - new_cursos
    inter = old_cursos & new_cursos
    modified = {}
    for curso in inter:
        mods = {}
        if data[curso]["nombre"] != new_data[curso]["nombre"]:
            mods["nombre"] = [data[curso]["nombre"], new_data[curso]["nombre"]]
        old_secciones = set(data[curso]["secciones"].keys())
        new_secciones = set(new_data[curso]["secciones"].keys())
        changes_sec = {}
        added_sec = new_secciones - old_secciones
        deleted_sec = old_secciones - new_secciones
        inter_sec = old_secciones & new_secciones
        modified_sec = {}
        for seccion in inter_sec:
            mods_sec = {}
            seccion = str(seccion)
            if data[curso]["secciones"][seccion]["profesores"] != new_data[curso]["secciones"][seccion]["profesores"]:
                mods_sec["profesores"] = [data[curso]["secciones"][seccion]["profesores"],
                                          new_data[curso]["secciones"][seccion]["profesores"]]
            if data[curso]["secciones"][seccion]["cupos"] != new_data[curso]["secciones"][seccion]["cupos"]:
                mods_sec["cupos"] = [data[curso]["secciones"][seccion]["cupos"],
                                     new_data[curso]["secciones"][seccion]["cupos"]]
            if data[curso]["secciones"][seccion]["horarios"] != new_data[curso]["secciones"][seccion]["horarios"]:
                mods_sec["horarios"] = [data[curso]["secciones"][seccion]["horarios"],
                                        new_data[curso]["secciones"][seccion]["horarios"]]
            if len(mods_sec) > 0:
                modified_sec[seccion] = mods_sec

        if len(added_sec) > 0:
            changes_sec["added"] = added_sec
        if len(deleted_sec) > 0:
            changes_sec["deleted"] = deleted_sec
        if len(modified_sec) > 0:
            changes_sec["modified"] = modified_sec

        if len(changes_sec) > 0:
            mods["secciones"] = changes_sec

        if len(mods) > 0:
            modified[curso] = mods
    if len(added) > 0:
        logger.info("Added: " + str(added))
    if len(deleted) > 0:
        logger.info("Deleted: " + str(deleted))
    if len(modified) > 0:
        logger.info("Modified: " + str(modified))
    if not (len(added) > 0 or len(deleted) > 0 or len(modified) > 0):
        logger.info("No changes detected")
    else:
        notify_changes(added, deleted, modified, context)

    data = new_data


def notify_changes(added, deleted, modified, context):
    chats_data = context.job.context

    changes_str = changes_to_string(added, deleted, modified)

    for chat_id in chats_data:
        if chats_data[chat_id].get("enable", False):
            try:
                context.bot.send_message(
                    chat_id=chat_id,
                    text=("\U00002757 ¡He detectado cambios en el catálogo!"
                          "\n{}\n"
                          "<a href='https://ucampus.uchile.cl/m/fcfm_catalogo/?semestre=20191&depto=5'>"
                          "\U0001F50D Ver catálogo</a>"
                          ).format(changes_str),
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
            except TelegramError as e:
                logger.error("Messaging chat %s raised a TelegramError: %s", chat_id, str(e))


def start(update, context):
    logger.info('Start from chat ' + str(update.message.chat_id))
    if context.chat_data.get("enable", False):
        context.bot.send_message(
            chat_id=update.message.chat_id,
            text="¡Mis avisos para este chat ya están activados! El próximo chequeo será apróximadamente a las " +
                 (last_check_time + timedelta(seconds=900)).strftime("%H:%M")
        )
    else:
        context.chat_data["enable"] = True
        context.bot.send_message(
            chat_id=update.message.chat_id,
            text="A partir de ahora avisaré por este chat si detecto algún cambio en el catálogo de cursos."
        )
        context.bot.send_message(
            chat_id=update.message.chat_id,
            text="Por ahora solo funciono con cursos de Computación, pero estoy aprendiendo a revisar "
                 "cursos de otros departamentos \U0001F913\U0001F4DA"
        )


def stop(update, context):
    logger.info('Stop from chat ' + str(update.message.chat_id))
    context.chat_data["enable"] = False
    context.bot.send_message(
        chat_id=update.message.chat_id,
        text="Ok, dejaré de avisar cambios en el catálogo por este chat."
             "Puedes volver a activar los avisos enviándome /start nuevamente."
    )


def main():
    updater = Updater(token=token, use_context=True, persistence=persistence)
    dp = updater.dispatcher
    jq = updater.job_queue
    dp.add_handler(CommandHandler('start', start))
    dp.add_handler(CommandHandler('stop', stop))

    global data
    data = parse_catalog()

    jq.run_repeating(check_catalog, interval=900, context=dp.chat_data)

    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()
