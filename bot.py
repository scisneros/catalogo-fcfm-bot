import json
import sys
from datetime import datetime
from os import path

import requests
from bs4 import BeautifulSoup
from requests import RequestException
from telegram.ext import Updater, CommandHandler, Filters

import data
from commands import start, stop, subscribe_depto, subscribe_curso, unsubscribe_depto, unsubscribe_curso, deptos, \
    subscriptions, force_check, get_log, get_chats_data
from config.auth import token, admin_ids
from config.logger import logger
from config.persistence import persistence
from constants import DEPTS, YEAR, SEMESTER
from utils import full_strip, try_msg, horarios_to_string, parse_horario, send_long_message

updater = Updater(token=token, use_context=True, persistence=persistence)
dp = updater.dispatcher
jq = updater.job_queue


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


def scrape_catalog():
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
    try:
        try:
            data.new_data = scrape_catalog()
        except RequestException:
            logger.exception("Connection Error. Aborting check.")
            return

        all_changes = {}

        for d_id in DEPTS:
            old_cursos = data.current_data.get(d_id, {}).keys()
            new_cursos = data.new_data.get(d_id, {}).keys()
            ocs = set(old_cursos)
            ncs = set(new_cursos)
            added = [x for x in new_cursos if x not in ocs]
            deleted = [x for x in old_cursos if x not in ncs]
            inter = [x for x in old_cursos if x in ncs]
            modified = {}
            d_data = data.current_data[d_id]
            d_new_data = data.new_data[d_id]
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
                    if d_data[c_id]["secciones"][s_id]["profesores"]\
                            != d_new_data[c_id]["secciones"][s_id]["profesores"]:
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
        data.current_data = data.new_data
        data.last_check_time = datetime.now()
    except Exception as e:
        logger.exception("Uncaught exception occurred:")
        try_msg(context.bot,
                chat_id=admin_ids[0],
                text="Ayuda, ocurrió un error y no supe qué hacer uwu.\n{}: {}".format(str(type(e).__name__), str(e)))


def notify_changes(all_changes, context):
    chats_data = dp.chat_data
    changes_dict = {}
    for d_id in all_changes:
        changes_str = changes_to_string(all_changes[d_id], d_id)
        changes_dict[d_id] = changes_str

    # for chat_id in admin_ids:  # DEBUG, send only to admin
    for chat_id in chats_data:
        subscribed_deptos = chats_data[int(chat_id)].setdefault("subscribed_deptos", [])
        subscribed_cursos = chats_data[int(chat_id)].setdefault("subscribed_cursos", [])
        dept_matches = [x for x in subscribed_deptos if x in all_changes]
        curso_matches = [x for x in subscribed_cursos if (x[0] in all_changes
                                                          and (x[1] in all_changes[x[0]].get("added", []) or
                                                               x[1] in all_changes[x[0]].get("deleted", []) or
                                                               x[1] in all_changes[x[0]].get("modified", {})))]
        if dept_matches or curso_matches:
            try_msg(context.bot,
                    parse_mode="HTML",
                    chat_id=chat_id,
                    text="\U00002757 ¡He detectado cambios en tus suscripciones!\n"
                         "<i>Desde el último chequeo a las {}</i>".format(data.last_check_time.strftime("%H:%M:%S")))
            for d_id in dept_matches:
                send_long_message(context.bot,
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
                if c_id in all_changes[d_id].get("added", []):
                    change_type_str = "Curso añadido:"
                    curso_changes_str = added_curso_string(c_id, d_id)
                elif c_id in all_changes[d_id].get("deleted", []):
                    change_type_str = "Curso eliminado:"
                    curso_changes_str = deleted_curso_string(c_id, d_id)
                elif c_id in all_changes[d_id].get("modified", {}):
                    change_type_str = "Curso modificado:"
                    curso_changes_str = modified_curso_string(c_id, d_id, all_changes[d_id]["modified"][c_id])
                send_long_message(context.bot,
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
    curso = data.new_data[depto_id][curso_id]
    result += "\U0001F4D7 <b>{} {}</b>\n".format(curso_id, curso["nombre"])
    for seccion_id in curso["secciones"]:
        seccion = curso["secciones"][seccion_id]
        profs = ", ".join(seccion["profesores"])
        result += "    S{} - {} - {} cupos\n".format(seccion_id, profs, seccion["cupos"])
        result += horarios_to_string(seccion["horarios"], 8)
    return result


def deleted_curso_string(curso_id, depto_id):
    result = ""
    curso = data.current_data[depto_id][curso_id]
    result += "\U0001F4D9 <b>{} {}</b>\n".format(curso_id, curso["nombre"])
    return result


def modified_curso_string(curso_id, depto_id, curso_mods):
    result = ""
    if "nombre" in curso_mods:
        result += "\U0001F4D8 <b>{}</b> <i>{}</i>\n<i>Renombrado:</i> <b>{}</b>\n"\
            .format(curso_id, curso_mods["nombre"][0], curso_mods["nombre"][1])
    else:
        result += "\U0001F4D8 <b>{} {}</b>\n".format(curso_id, data.new_data[depto_id][curso_id]["nombre"])
    if "secciones" in curso_mods:
        if "added" in curso_mods["secciones"]:
            result += "    <i>Secciones añadidas:</i>\n"
            for seccion_id in curso_mods["secciones"]["added"]:
                seccion = data.new_data[depto_id][curso_id]["secciones"][seccion_id]
                profs = ", ".join(seccion["profesores"])
                result += "    \U00002795 Secc. {} - {} - {} cupos\n".format(seccion_id, profs,
                                                                             seccion["cupos"])
                result += horarios_to_string(seccion["horarios"], 8)
        if "deleted" in curso_mods["secciones"]:
            result += "    <i>Secciones eliminadas:</i>\n"
            for seccion_id in curso_mods["secciones"]["deleted"]:
                print(" ".join([depto_id, curso_id, seccion_id]))
                seccion = data.current_data[depto_id][curso_id]["secciones"][seccion_id]
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
                    profs = ", ".join(data.new_data[depto_id][curso_id]["secciones"][seccion_id]["profesores"])
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
            changes_str += deleted_curso_string(curso_id, depto_id)
    if len(modified) > 0:
        changes_str += "\n<i>Cursos modificados:</i>\n"
        for curso_id in modified:
            changes_str += modified_curso_string(curso_id, depto_id, modified[curso_id])

    return changes_str


def main():
    try:
        with open(path.relpath('excluded/catalogdata.json'), "r") as datajsonfile:
            data.current_data = json.load(datajsonfile)
        logger.info("Data loaded from local, initial check for changes will be made")
        check_first = True
    except OSError:
        logger.info("No local data was found, initial scraping will be made without checking for changes.")
        check_first = False
        data.current_data = scrape_catalog()

    jq.run_repeating(check_catalog, interval=900, first=(0 if check_first else None), name="job_check")

    dp.add_handler(CommandHandler('start', start))
    dp.add_handler(CommandHandler('stop', stop))
    dp.add_handler(CommandHandler('suscribir_depto', subscribe_depto))
    dp.add_handler(CommandHandler('suscribir_curso', subscribe_curso))
    dp.add_handler(CommandHandler('desuscribir_depto', unsubscribe_depto))
    dp.add_handler(CommandHandler('desuscribir_curso', unsubscribe_curso))
    dp.add_handler(CommandHandler('deptos', deptos))
    dp.add_handler(CommandHandler('suscripciones', subscriptions))
    # Admin commands
    dp.add_handler(CommandHandler('force_check', force_check, filters=Filters.user(admin_ids)))
    dp.add_handler(CommandHandler('get_log', get_log, filters=Filters.user(admin_ids)))
    dp.add_handler(CommandHandler('get_chats_data', get_chats_data, filters=Filters.user(admin_ids)))

    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()
