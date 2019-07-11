

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
