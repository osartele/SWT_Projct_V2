import json
import os
import re


def _get_structure_json(rootdir):
    structure = {}

    for root, dirs, files in os.walk(rootdir):
        if "test" in root.replace(rootdir, "").split(os.sep):
            continue

        java_files = [file for file in files if file.endswith(".java")]
        if not java_files:
            continue

        package = root.replace(rootdir, "").replace(os.sep, ".").strip(".")
        package_structure = structure

        if package:
            for part in package.split("."):
                package_structure = package_structure.setdefault(part, {})

        for file in java_files:
            package_structure[file] = None

    return structure


def get_structure(rootdir):
    structure_file = f'{rootdir}/project_structure.json'
    with open(structure_file, 'r') as file:
        project_structure = json.load(file)
        project_structure_str = re.sub(r':\sNone', ' ', str(project_structure))
        return project_structure_str


def save_project_structure(rootdir):
    project_structure = _get_structure_json(rootdir)
    file_name = os.path.join(rootdir, 'project_structure.json')
    with open(file_name, 'w') as file:
        json.dump(project_structure, file, indent=4)


# Stampa in formato json una stringa
def format_json_string_manual(json_string):
    indent_level = 0
    formatted_string = []
    for char in json_string:
        if char == '{' or char == '[':
            formatted_string.append(char)
            indent_level += 1
            formatted_string.append('\n' + '    ' * indent_level)
        elif char == '}' or char == ']':
            indent_level -= 1
            formatted_string.append('\n' + '    ' * indent_level)
        elif char == ',':
            formatted_string.append(char)
            formatted_string.append('\n' + '    ' * indent_level)
        else:
            formatted_string.append(char)

    return ''.join(formatted_string)


# TODO FUTURE USE

"""
def get_java_structure_with_signatures(rootdir):
    structure = {}

    for root, dirs, files in os.walk(rootdir):
        java_files = [file for file in files if file.endswith(".java")]
        if not java_files:
            continue

        package = root.replace(rootdir, "").replace(os.sep, ".").strip(".")
        package_structure = structure

        if package:
            for part in package.split("."):
                package_structure = package_structure.setdefault(part, {})

        for file in java_files:
            file_path = os.path.join(root, file)

            with open(file_path, 'r', encoding='utf-8') as f:
                # Parsing il codice sorgente Java
                tree = javalang.parse.parse(f.read())

                # Estrarre classi e metodi
                for declaration in tree.types:
                    class_info = {
                        "name": declaration.name,
                        "methods": [],
                        "visibility": declaration.modifiers
                    }

                    # Estrarre metodi all'interno della classe
                    for method in declaration.methods:
                        method_info = {
                            "name": method.name,
                            "return_type": method.return_type,
                            "parameters": [
                                {"name": param.name, "type": param.type} for param in method.parameters
                            ],
                            "visibility": method.modifiers
                        }
                        class_info["methods"].append(method_info)

                    # Aggiungere la classe alla struttura
                    package_structure[file] = package_structure.get(file, {})
                    package_structure[file][class_info["name"]] = class_info

    return structure
"""

# 1
"""
# Esempio di utilizzo
root_directory = "./compiledrepos/113231746"
java_structure = get_java_structure_with_signatures(root_directory)
print(json.dumps(java_structure, indent=4))
"""
# 2
"""
root_directory = "./compiledrepos/113231746"
project_structure = get_structure(root_directory)

"""
