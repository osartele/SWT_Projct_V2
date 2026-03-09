import os
import re

import gradleLib
import mavenLib
import json

def _legacy_prompt_only_path_removed_message(test_type):
    return (
        "Legacy prompt-only correction has been retired and no longer uses direct provider SDKs. "
        f"Skipping deprecated correction helper invocation for `{test_type}`."
    )




def correct_errors(project, test_type, technique, test_path, project_path, project_df, system, messages, errori, dictionary_for_restore, chance, type_project):
    print(f"Package command failed for project: {project}, test type: {test_type}, technique: {technique}\n")

    # Impostazione cartella per salvare le classi fallite
    failed_dir = "./failed_classes"
    if not os.path.exists(failed_dir):
        os.makedirs(failed_dir)

    # Salva la classe di test fallita
    save_class(test_path, "_failed", failed_dir)
    print(f"{chance} CHANCE")

    # Corregge la classe
    corrected_class, success = conversation(test_type, errori, messages, chance)
    save_class(test_path, "_processed", failed_dir)  # Salva la classe corretta come "_processed"

    if success:
        # Sovrascrive la classe di test con quella restituita
        with open(test_path, 'w') as test_file_write:
            test_file_write.write(corrected_class)

        esito = None
        if type_project == "Maven":
            # Esegue il test Maven con la classe corretta
            esito, errori = mavenLib.run_maven_test_command(project_path, project_df, system)
        elif type_project == "Gradle":
            # Esegue il test Gradle con la classe corretta
            esito, errori = gradleLib.run_gradle_test_command(project_path, project_df, system)

        # Se il maven test passa con la classe corretta, salva la classe corretta e restituisce True
        if esito:
            print("Test passed with the corrected class.")
            save_class(test_path, "_corrected", failed_dir)  # Salva la classe corretta come "_corrected"
            print(f"Classe di test corretta salvata in: {os.path.join(failed_dir, os.path.basename(test_path).replace('.java', '_corrected.java'))}")
            print(f"Package command completed for {project}\n")
            return True, None
        # Se il maven test fallisce con la classe corretta, ripristina la classe originale e restituisce False
        else:
            print("Test failed again with the corrected class.\n")
            print(f"Ripristino della classe originale a causa del fallimento del test Maven con la classe corretta, nel seguente path di salvataggio: {test_path}\n")
            restore_original_class(test_path, dictionary_for_restore)
            return False, errori
    else:
        print("Conversation did not return a successful correction.")
        return False, None


def conversation(test_type, errors, messages, num_chance):
    """
    Retained for backwards compatibility after removing direct provider SDK usage.
    """

    messages.append(conversation_messages(errors, num_chance))

    warning_message = _legacy_prompt_only_path_removed_message(test_type)
    print(warning_message)
    messages.append({"role": "system", "content": warning_message})
    return None, False

def conversation_messages(errors, num_chance):
    """
    Returns a predefined message to guide the correction of a test class based on the number of attempts.

    The function generates a detailed initial message when called for the first time, outlining general instructions
    for correcting errors. If the initial correction attempt fails, it provides a follow-up message,
    more targeted and specific, to address recurring errors.

    Parameters:
        errors (str): Description of the errors encountered during the class compilation.
        n (int): Number of correction attempts made; used to determine which message to return.

    Returns:
        dict: A dictionary containing the correction message, structured based on the number of attempts.
               - If n == 1, returns the initial message with general instructions.
               - If n > 1, returns a message with specific guidance for targeted corrections.
    """
    # Aggiungi il messaggio di errore per continuare la conversazione su questa classe specifica
    first_message = {"role": "user", "content": (
                "This test class you just generated contains some compilation errors. Please carefully review the errors and "
                "modify the class so that it compiles without any errors in Maven.\n\n"
                "Ensure that the class retains all original structure and code, including imports, declarations, and methods, "
                "while only correcting the portions of the code related to the errors.\n\n"
                "### Instructions:\n"
                "1. Correct all compilation errors, preserving all working sections.\n"
                "2. Verify that each method declaration is complete, with correct syntax, parameters, and return types.\n"
                "3. Ensure that all necessary imports are included, adding any missing ones to resolve 'cannot find symbol' errors.\n"
                "4. If certain methods or classes are not recognized, investigate whether they need to be imported or redefined, "
                "and make the appropriate adjustments. If a specific external class or method is essential, ensure it is correctly referenced.\n"
                "5. You must only correct the specific compilation errors and avoid altering any other code sections that are already functional.\n"
                "6. Ensure that all required exceptions are properly handled in method declarations or with try-catch blocks where necessary.\n"
                "7. Respond with the entire corrected class, including imports, without additional explanations or comments outside of the code.\n\n"

                "### General Error Handling Guidelines:\n"

                "- **Syntax errors (e.g., `<identifier> expected` or `invalid method declaration`)**:\n"
                "  - Ensure that each method has a valid name, parameter list, and return type. Check for missing semicolons or braces.\n"

                "- **Cannot find symbol errors (e.g., `cannot find symbol` or `symbol: method <methodName>()`)**:\n"
                "  - This often indicates a missing import or that the class/method does not exist. Verify if the method or class is part of an external library or "
                "    if it needs to be declared in this file. Add the required import if it's from an external library.\n"

                "- **Missing import errors (e.g., `cannot find symbol: class SomeClass`)**:\n"
                "  - Add an import statement for any missing class if it's from an external package. Ensure that all classes and interfaces used in the test are imported correctly.\n"

                "- **Unhandled exceptions (e.g., `unreported exception <ExceptionType>`)**:\n"
                "  - Surround the relevant code with a try-catch block, or add the exception type to the method's `throws` clause.\n"

                "- **Missing or undefined enums or constants**:\n"
                "  - If the code references an enum or constant that is not defined, consider creating a placeholder enum or constant with the appropriate values.\n"

                "- **Dependencies issues (e.g., missing libraries)**:\n"
                "  - Ensure that all external libraries required by the class are included in the project dependencies. If an external class or method is referenced, "
                "    check that the corresponding library is listed in the project’s configuration file (such as `pom.xml` for Maven).\n\n"

                "### Compilation Errors:\n" + errors)}

    second_message= {"role": "user",
                    "content": (
                        "The initial corrections did not resolve all compilation errors in the test class. Please make the necessary adjustments to ensure the class compiles successfully in Maven.\n\n"
                        "Focus specifically on resolving the following types of issues:\n"
                        "1. **Syntax errors**: Carefully review each method to ensure it has the correct syntax, parameter list, and return type.\n"
                        "2. **Unresolved symbols and missing imports**: Add any missing imports for external classes or methods that are undefined. Make sure every referenced class or method is accessible.\n"
                        "3. **Annotations**: If specific annotations (like @Test or others) are causing errors, check that they are applied in the correct context and are supported by the project's dependencies.\n"
                        "4. **Exception handling**: Address any unhandled exceptions by wrapping the code in try-catch blocks or declaring the exceptions in the method signature.\n\n"
        
                        "### Key Points:\n"
                        "- Reason step-by-step.\n"
                        "- Review the error messages carefully to identify the root cause of each issue.\n"
                        "- Make only the changes necessary to resolve the errors without altering working parts of the code.\n"
                        "- Confirm that all required classes and methods are imported or defined correctly.\n"
                        "- Ensure that every method, annotation, and dependency aligns with Maven's requirements for successful compilation.\n\n"
        
                        "Once these specific issues are addressed, respond with the entire corrected test class, including necessary imports and modifications.\n"
                        "\n### Compilation Errors:\n" + errors)}
    return first_message if num_chance == 1 else second_message


def save_class(test_path, suffix, save_dir):
    """Salva la classe di test con un suffisso specifico in una directory specificata."""
    filename = os.path.basename(test_path).replace(".java", f"{suffix}.java")
    save_path = os.path.join(save_dir, filename)

    with open(test_path, 'r') as test_file:
        content = test_file.read()
    with open(save_path, 'w') as file:
        file.write(content)

    return save_path


def restore_original_class(test_path, dictionary_for_restore):
    """Ripristina la classe originale dal dizionario."""
    with open(test_path, 'w') as test_file_write:
        test_file_write.write(dictionary_for_restore[test_path])


def extract_errors(stdout: str, stderr: str):
    """
    Extracts and formats error messages from Maven stdout and stderr logs. Captures both compilation errors and
    other errors/warnings. If no specific errors are found, retrieves everything following '[ERROR]' markers.

    Parameters:
    stdout (str): The standard output log from Maven.
    stderr (str): The standard error log from Maven.

    Returns:
    str: A formatted string containing the error messages.
    """
    # Regular expression to capture compilation error block
    error_pattern = re.compile(r'\[ERROR\] COMPILATION ERROR :(.*?)(?=\[INFO\] \d+ error)', re.DOTALL)
    errors = error_pattern.findall(stdout)

    if errors:
        # Clean and format compilation error block
        cleaned_errors = errors[0].strip()
        cleaned_lines = [line.replace('[INFO] -------------------------------------------------------------', '').replace('[ERROR]','').strip()
                        for line in cleaned_errors.splitlines() if line.strip()]
        formatted_errors = "The following compilation errors were encountered during the Maven build:\n"
        formatted_errors += "\n- " + "\n- ".join(cleaned_lines)
    else:
        # Check for general errors or warnings in stderr if no compilation errors are found
        cleaned_stderr = [line.strip() for line in stderr.splitlines() if line.strip() and '[ERROR]' in line]

        if cleaned_stderr:
            formatted_errors = "The following errors were encountered during the Maven build (from stderr):\n"
            formatted_errors += "\n- " + "\n- ".join(cleaned_stderr)
        else:
            # Fallback: capture all content after '[ERROR]' in stdout if no specific errors are found
            error_lines = []
            capturing = False
            for line in stdout.splitlines():
                if '[ERROR]' in line:
                    capturing = True
                    # Capture the line without the '[ERROR]' prefix
                    error_lines.append(line.replace('[ERROR]', '').strip())
                elif capturing:
                    # Continue capturing all lines after '[ERROR]' until the next '[INFO]' or end of error section
                    if '[INFO]' in line:
                        capturing = False
                    else:
                        error_lines.append(line.strip())

            if error_lines:
                formatted_errors = "The following general errors were encountered during the Maven build:\n"
                formatted_errors += "\n- " + "\n- ".join(error_lines)
            else:
                formatted_errors = "No compilation errors or general issues found in the Maven output."

    return formatted_errors


def extract_gradle_errors(stdout: str, stderr: str):
    """
    Extracts and formats error messages from Gradle stdout and stderr logs. Captures both compilation errors and
    other errors/warnings. If no specific errors are found, retrieves everything following '[ERROR]' or 'FAILED' markers.

    Parameters:
    stdout (str): The standard output log from Gradle.
    stderr (str): The standard error log from Gradle.

    Returns:
    str: A formatted string containing the error messages.
    """
    # Regular expression to capture compilation error or task failure
    error_pattern = re.compile(r'> Task :(.*?):.*?FAILED', re.DOTALL)
    errors = error_pattern.findall(stdout)

    if errors:
        # Clean and format compilation or task error block
        formatted_errors = "The following task errors were encountered during the Gradle build:\n"
        formatted_errors += "\n- " + "\n- ".join(errors)
    else:
        # Check for general errors or warnings in stderr if no specific task errors are found
        cleaned_stderr = [line.strip() for line in stderr.splitlines() if line.strip() and ('[ERROR]' in line or 'FAILED' in line)]

        if cleaned_stderr:
            formatted_errors = "The following errors were encountered during the Gradle build (from stderr):\n"
            formatted_errors += "\n- " + "\n- ".join(cleaned_stderr)
        else:
            # Fallback: capture all content after '[ERROR]' in stdout if no specific errors are found
            error_lines = []
            capturing = False
            for line in stdout.splitlines():
                if '[ERROR]' in line or 'FAILED' in line:
                    capturing = True
                    # Capture the line without the '[ERROR]' prefix
                    error_lines.append(line.replace('[ERROR]', '').strip())
                elif capturing:
                    # Continue capturing all lines after '[ERROR]' or 'FAILED' until the next '[INFO]' or end of error section
                    if '[INFO]' in line:
                        capturing = False
                    else:
                        error_lines.append(line.strip())

            if error_lines:
                formatted_errors = "The following general errors were encountered during the Gradle build:\n"
                formatted_errors += "\n- " + "\n- ".join(error_lines)
            else:
                formatted_errors = "No compilation errors or general issues found in the Gradle output."

    return formatted_errors


def save_conversation_to_json(messages, class_name, save_path="."):
    """
    Salva l'intera conversazione in un file JSON, con ciascun messaggio in formato JSON
    per includere ruolo e contenuto.

    Parameters:
        messages: lista dei messaggi della conversazione.
        class_name: il nome della classe, utilizzato per il nome del file.
        save_path: il percorso della directory in cui salvare il file (default è la directory corrente).

    Returns:
        str: Il percorso completo del file JSON creato.
    """
    # Formatta il nome del file
    file_name = f"conversation_{class_name}.json"
    full_path = os.path.join(save_path, file_name)

    # Crea la struttura della conversazione
    conversation_data = []
    for i, message in enumerate(messages):
        role = message.get("role", "unknown").capitalize()
        content = message.get("content", "")

        conversation_data.append({
            "messaggio_numero": i + 1,
            "ruolo": role,
            "contenuto": content
        })

    # Crea la directory se non esiste
    os.makedirs(save_path, exist_ok=True)

    # Scrive la conversazione nel file JSON
    with open(full_path, 'w') as file:
        json.dump(conversation_data, file, indent=4, ensure_ascii=False)

    return full_path


