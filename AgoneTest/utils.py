import os
import pandas as pd
import subprocess
import shutil
import re
import xml.etree.ElementTree as ET
import ctypes
import mavenLib
from dotenv import load_dotenv

load_dotenv()

def _legacy_prompt_only_path_removed_message(test_type):
    return (
        "Legacy prompt-only generation has been retired and no longer uses direct provider SDKs. "
        f"Skipping deprecated helper invocation for `{test_type}` and leaving generation to the Gemini CLI pipeline."
    )

def set_gradle_variable(gradle_directory, gradle_version, system):
    """
    Sets the gradle variable accordingly to the given gradle version.
        Parameters:
                gradle_directory (String): the directory containing the gradle bin files.
                gradle_version (String): the version of Gradle
                system (String): the current OS (Windows, Linux, etc..)   
    """
    if gradle_version.startswith('4'):
        gradle_variable = f"{gradle_directory}/gradle-4.10.2"
    elif gradle_version.startswith('5'):
        gradle_variable = f"{gradle_directory}/gradle-5.6.4"
    elif gradle_version.startswith('6'):
        gradle_variable = f"{gradle_directory}/gradle-6.8.3"
    elif gradle_version.startswith('7'):
        gradle_variable = f"{gradle_directory}/gradle-7.6"
    elif gradle_version.startswith('8'):
        gradle_variable = f"{gradle_directory}/gradle-8.6"
    else:
        gradle_variable = f"{gradle_directory}/gradle-8.6"
    if system=="Windows":
        os.environ['PATH'] = f"{gradle_variable}/bin;{os.environ['PATH']}"
    else: # for Linux and Darwin
        os.environ['PATH'] = f"{gradle_variable}/bin:{os.environ['PATH']}"


def set_java_home(java_directory, java_version, system):
    """
    Sets the java home variable accordingly to the given java version.
        Parameters:
                java_directory (String): the directory containing the jdk files.
                java_version (String): the version of Java
                system (String): the current OS (Windows, Linux, etc..)   
    """
    if java_version == '1.5' or java_version == '5':
        java_home = os.getenv('JAVA_HOME_5')
    elif java_version == '1.6' or java_version == '6':
        java_home = os.getenv('JAVA_HOME_6')
    elif java_version == '1.7' or java_version == '7':
        java_home = os.getenv('JAVA_HOME_7')
    elif java_version == '1.8' or java_version == '8':
        java_home = os.getenv('JAVA_HOME_8')
    elif java_version == '11':
        java_home = os.getenv('JAVA_HOME_11')
    elif java_version == '17':
        java_home = os.getenv('JAVA_HOME_17')
    elif java_version == '21':
        java_home = os.getenv('JAVA_HOME_21')
    else:
        java_home = os.getenv('JAVA_HOME_DEFAULT')
    print("ecco il java home" + java_home)
    os.environ['JAVA_HOME'] = java_home
    if system=="Windows":
        os.environ['PATH'] = f"{java_home}/bin;{os.environ['PATH']}"
    else: # for Linux and Darwin
        os.environ['PATH'] = f"{java_home}/bin:{os.environ['PATH']}"


    
def read_class_content(file_path): 
    """
    Reads the content of a test class or focal class.
        Parameters:
                    file_path (string): the path of the test class/focal class
        Returns:
                    :the content of the given test class/focal class. 'None' if the given path is not a class, if the given path does not exist or if an error occurred while reading the file 
    """
    # if the given file is not a class
    if file_path.endswith(".java") == False:
        return None
    # If the file exists
    try:
        if os.path.exists(file_path):
            # Open the file
            with open(file_path, 'r') as file:
                # Return the content of the file
                return file.read()
        else:
            # If the file does not exist, return None
            return None
    except Exception as e:
        print(e)
        # If an exception occurs, return None
        return None
    


def verify_if_folder_has_already_been_processed(folder):
    """
    Verifies if the given folder has already been processed. 
        Parameters:
                    folder: the ID of the project (that is the name of the corresponding folder)
        Returns:
                    :'True' if the folder has already been processed, False otherwise
    """
    compiled_path = f'compiledrepos/{folder}'
    failed_path = f'failedrepos/{folder}'
    if os.path.exists(compiled_path):
        return True
    elif os.path.exists(failed_path):
        return True
    else:
        return False
    


def count_files_of_a_dir(dir_path):
    """
    Returns the number of files given a directory path.
        Parameters:
                    dir_path: the directory path
        Returns:
                    count: the number of files
    """
    count = 0
    # Iterate directory
    for path in os.listdir(dir_path):
        # check if current path is a file
        if os.path.isdir(os.path.join(dir_path, path)):
            count += 1
    return count





def remove_missing_files_from_dataframe(project_df):
    """
    Removes from the given dataframe all the rows that contain a missing file (in other words, a file that is not present in the corresponding repository directory)        
        Parameters:
                    project_df (Dataframe): the dataframe containing the names and paths of the focal classes and the associated test classes
        Returns:
                    proejct_df (Dataframe): the new dataframe without the rows that contain a missing file
    """
    index_to_remove = set() # contains all the indexes that are to be removed because the corresponding focal path or test path is not present in the repository
    # If a test_path or a focal_path of the project_df (that is output/classes.csv filtered with the current project) doesn't exist in the repository, it will be removed from the dataframe
    for index, row in project_df.iterrows():
        if "repos/" in row['Test_Path']:
            test_path = row['Test_Path'].replace("repos/", "compiledrepos/")
            focal_path = row['Focal_Path'].replace("repos/", "compiledrepos/")
        else:
            project = row['Project']
            test_path = f"compiledrepos/{project}/" + row['Test_Path']
            focal_path = f"compiledrepos/{project}/" + row['Focal_Path']
        if not (os.path.isfile(test_path) and os.path.isfile(focal_path)):
            index_to_remove.add(index)
    project_df = project_df.drop(index=index_to_remove)
    project_df = project_df.reset_index()
    return project_df



def configure_test_smell_detector(project_dataframe, project):
    """
    Configures tsDetect to analyze the focal classes and the test classes specified in the given dataframe. 
    It must be executed prior to running tsDetect.
        Parameters:
                    project_dataframe (Dataframe): the dataframe that contains all the focal classes and test classes that are to be executed by tsDetect
                    project: the ID of the project
        Returns:
                    csv_path: the path of the CSV file that needs to be passed as input to the test smell detector
    """
    data = []
    project_df = project_dataframe.copy()
    for index, row in project_df.iterrows():
        test_path = row['Test_Path']
        focal_path = row['Focal_Path']
        test_path_append = os.path.join("compiledrepos", str(project), test_path)
        focal_path_append = os.path.join("compiledrepos", str(project), focal_path)
        test_path_absolute = os.path.abspath(test_path_append)
        focal_path_absolute = os.path.abspath(focal_path_append)
        data.append([project, test_path_absolute, focal_path_absolute])
    df = pd.DataFrame(data)
    csv_path = f"output/{project}/pathToInputFile.csv"
    df.to_csv(csv_path, index=False, header=False, na_rep="-")
    return csv_path




           

def run_test_smell_detector(csv_path, project, test_type, technique, module=None):
    """
    Runs tsDetect and saves the result in the 'TestSmellDetection_{project}_{test_type}_{technique}.csv' file. 
    It must be executed after configure_test_smell_detector().
    This function uses the TestSmellDetector.jar file; therefore, the tsDetect JAR file must be present in the same directory as utils.py
        Parameters:
                    csv_path: the path of the CSV file returned by configure_test_smell_detector()
                    project: the ID of the project
                    test_type: the type of the test
                    technique: the prompt technique adopted if the test type is an AI model, 'None' if it is not an AI model
                    module: the name of the module of the project
        Returns:
                    result_path: the path of the CSV file containing the results provided by tsDetect. 'None' if an error occurred while trying to run tsDetect
    """
    command = ["java", "-jar", "./TestSmellDetector.jar", csv_path]
    try:
        output = subprocess.check_output(command, stderr=subprocess.STDOUT)
    except Exception as e:
        print(e.output.decode("utf-8")) 
        return None
    files = os.listdir(os.getcwd())
    result_path = None
    for file in files:
        if file.startswith('Output_TestSmellDetection'): 
            if module is None:  
                if technique is not None:
                    new_name = f'TestSmellDetection_{project}_{test_type}_{technique}.csv'
                else:
                    new_name = f'TestSmellDetection_{project}_{test_type}.csv'
            else:
                if technique is not None:
                    new_name = f'TestSmellDetection_{project}_{module}_{test_type}_{technique}.csv'
                else:
                    new_name = f'TestSmellDetection_{project}_{module}_{test_type}.csv'
            if os.path.exists(f'{new_name}'):
                os.remove(f'{new_name}')
            os.rename(file, new_name)  
            result_path = f'output/{project}/{new_name}'
            if os.path.exists(result_path):
                os.remove(result_path)
            shutil.move(new_name, f'output/{project}')
            break
    return result_path




def retrieve_code_coverage_and_cyclomatic_complexity(project_path, project_dataframe, project_id, type_project, module=None):
    """
    Retrieves the code coverage (Branch, Method, Line and Mutation) of the single classes from the given Maven/Gradle project.
    Retriveves also the cyclomatic_complexity of the single classes from the given Maven/Gradle projects.
    Parameters:
                    project_path: the path of the project
                    project_dataframe (Dataframe): the dataframe that contains the focal classes and the test classes of the project involved in the code and mutation coverage
                    project_id: the ID of the project
                    type_project: the type of the project (if Maven or Gradle project)
                    module (optional): the module to analyze
    Returns:
                    measures_df (DataFrame): The DataFrame containing the measures of code coverage and cyclomatic complexity for individual classes from the given Maven/Gradle project.

    """
    
    project_df = project_dataframe.copy()
    if module is None:
        # find all modules and save their paths in a list for JaCoCo and PITest
        modules = search_modules(project_path, project_df, project_id, type_project)
        if not modules:
            return None
    else:
        modules = [module]
        
    jacoco_df_all = None
    pitest_df_all = None
    # For each module, retrieve the .csv files and read them to obtain the results from JaCoCo and PITest. All the results are then merged into a single DataFrame.
    for module in modules:
        jacoco_df = None
        pitest_df = None
        path = os.path.join(project_path, module)
        if type_project == 'Maven':
            if os.path.exists(os.path.join(path, f"target/site/jacoco/jacoco.csv")):
                jacoco_df = pd.read_csv(os.path.join(path, f"target/site/jacoco/jacoco.csv"))
            elif os.path.exists(os.path.join(path, f"target/site/jacoco-ut/jacoco.csv")):
                jacoco_df = pd.read_csv(os.path.join(path, f"target/site/jacoco-ut/jacoco.csv"))

            
            if os.path.exists(os.path.join(path, f"target/pit-reports/mutations.csv")):
                pitest_df = pd.read_csv(os.path.join(path, f"target/pit-reports/mutations.csv"), header=None)
        else:
            if os.path.exists(os.path.join(path, f"build/reports/jacoco/jacoco.csv")):
                jacoco_df = pd.read_csv(os.path.join(path, f"build/reports/jacoco/jacoco.csv"))
            elif os.path.exists(os.path.join(path, f"build/reports/jacoco-ut/jacoco.csv")):
                jacoco_df = pd.read_csv(os.path.join(path, f"build/reports/jacoco-ut/jacoco.csv"))

            if os.path.exists(os.path.join(path, f"build/reports/pitest/mutations.csv")):
                pitest_df = pd.read_csv(os.path.join(path, f"build/reports/pitest/mutations.csv"), header=None)
        
        if jacoco_df is None or pitest_df is None:
            return None
        
        pitest_df[0] = pitest_df[0].str.replace('.java', '')
        pitest_df.columns = ['Focal_Class', 'Package', 'Mutation_Name', 'Method_Name', 'Line_Number', 'Result', 'Killing_test']
        # Each row of the pitest_df DataFrame represents a mutation
        # Focal_Class: the name of the focal class without the .java extension
        # Package: the package of the focal class
        # Mutation_Name: the name of the engine used for the mutation
        # Method_Signature: the name of the method involved in the mutation
        # Line_Number: the number of the line of code involved in the mutation
        # Killing_Test: the test that ultimately killed the mutation
        pitest_df = pitest_df.groupby('Focal_Class').agg(
            {'Result': lambda x: round((x == 'KILLED').sum() / len(x) * 100, 2)})
        pitest_df = pitest_df.rename(columns={'Result': 'Mutation_Coverage'})
        pitest_df = pitest_df.reset_index()
        pitest_df_all = pd.concat([pitest_df_all, pitest_df], ignore_index=True)

        jacoco_df = jacoco_df.rename(columns={'CLASS': 'Focal_Class'})
        jacoco_df_all = pd.concat([jacoco_df_all, jacoco_df], ignore_index=True)

        
    project_df = pd.merge(project_df, jacoco_df_all, how="left", on=['Focal_Class'])
            

    # add branch, method and line coverage as a percentages
    # add the cyclomatic complexity
    measures_data = []
    for index, row in project_df.iterrows():
        focal_class = row['Focal_Class']
        try:
            if row['BRANCH_COVERED'] + row ['BRANCH_MISSED'] != 0:
                branch_coverage = round((row['BRANCH_COVERED']/(row['BRANCH_COVERED'] + row ['BRANCH_MISSED'])*100),2)
            else:
                branch_coverage = '-'
        except Exception as e:
            branch_coverage = '-'
            
        try:
            if row['METHOD_COVERED'] + row ['METHOD_MISSED'] != 0:
                method_coverage = round((row['METHOD_COVERED']/(row['METHOD_COVERED'] + row ['METHOD_MISSED'])*100),2)
            else:
                method_coverage = '-'
        except Exception as e:
            method_coverage = '-'
            
        try:
            if row['LINE_COVERED'] + row ['LINE_MISSED'] != 0:
                line_coverage = round((row['LINE_COVERED']/(row['LINE_COVERED'] + row ['LINE_MISSED'])*100),2)
            else:
                line_coverage = '-'
        except Exception as e:
            line_coverage = '-'
            
        try:
            cyclomatic_complexity = row['COMPLEXITY_MISSED'] + row['COMPLEXITY_COVERED']
        except Exception as e:
            cyclomatic_complexity = '-'
        try:
            loc = row['LINE_MISSED'] + row['LINE_COVERED']
        except Exception as e:
            loc = '-'


        measures_data.append([focal_class, cyclomatic_complexity, loc, branch_coverage, method_coverage, line_coverage])
    
    measures_df = pd.DataFrame(measures_data, columns=['Focal_Class', 'Cyclomatic_complexity', 'Lines_of_code', 'Branch_coverage', 'Method_coverage', 'Line_coverage'])
    measures_df = pd.merge(project_df, measures_df, how="left",
                            on=['Focal_Class'])
    measures_df = pd.merge(measures_df, pitest_df_all, how="left",
                                on=['Focal_Class'])
    measures_df.drop(columns=['GROUP', 'PACKAGE', 'INSTRUCTION_MISSED', 'INSTRUCTION_COVERED', 'BRANCH_MISSED', 'BRANCH_COVERED', 'LINE_MISSED', 'LINE_COVERED', 'COMPLEXITY_MISSED', 'COMPLEXITY_COVERED', 'METHOD_MISSED', 'METHOD_COVERED'], inplace=True)


    return measures_df





def generate_output_csv_test_type(project_id, test_type, technique, measures_df, csv_path_test_smell, module=None):
    """
    Generates and saves the output CSV file that contains all the measures about the single test type applied in the project (code coverage, mutation coverage and number of test smells)
        Parameters:
                    project_id: the ID of the project
                    test_type: the type of the test (e.g 'human', 'evosuite',...)
                    technique: the prompt technique adopted if the test type is an AI model, 'None' if it is not an AI model
                    measures_df (Dataframe): the dataframe containing measures about code coverage and cyclomatic complexity
                    csv_path_test_smell: the path of the CSV file returned by tsDetect
                    module: the name of the project module (optional)
        Returns:
                    csv_path: the path of the output CSV file that includes all the measures about the single test type applied in the project (code coverage, mutation coverage and number of test smells)
                    : 'None' if an error occurred
    """

    if csv_path_test_smell is not None:
        if os.path.exists(csv_path_test_smell):
            test_smell_df = pd.read_csv(csv_path_test_smell)
            # remove .java from the TestClass column
            test_smell_df['TestClass']=test_smell_df['TestClass'].str.replace('.java','')
            test_smell_df['TestClass'] = test_smell_df['TestClass'].str.split('/').str[-1]
            test_smell_df = test_smell_df.drop(columns=['App', 'TestFilePath', 'ProductionFilePath', 'RelativeTestFilePath', 'RelativeProductionFilePath'])
            # rename the column TestClass to Test_Class
            test_smell_df = test_smell_df.rename(columns={'TestClass':'Test_Class'})
            measures_df = pd.merge(measures_df, test_smell_df, how="left", on=['Test_Class'])

    # replace /repos with /compiledrepos in Focal_path e Test_Path
    for index, row in measures_df.iterrows():
        measures_df.at[index, 'Focal_Path'] = row['Focal_Path'].replace('repos/', 'compiledrepos/')
        measures_df.at[index, 'Test_Path'] = row['Test_Path'].replace('repos/', 'compiledrepos/')

    csv_path = None
    if module is None:
        if technique is not None:
            csv_path = f'./output/{project_id}/TestClasses_{project_id}_{test_type}_{technique}.csv'
        else:
            csv_path = f'./output/{project_id}/TestClasses_{project_id}_{test_type}.csv'
    else:
        if technique is not None:
            csv_path = f'./output/{project_id}/TestClasses_{project_id}_{module}_{test_type}_{technique}.csv'
        else:
            csv_path = f'./output/{project_id}/TestClasses_{project_id}_{module}_{test_type}.csv'
    try:
        measures_df.to_csv(csv_path, index=False, na_rep="-")
    except Exception as e:
        return None
    return csv_path

    


def search_modules(project_path, project_dataframe, project_id, type_project):
    """
    Searches all the modules where are stored pitest and jacoco measures. 
    It works with either Maven and Gradle projects.
        Parameters:
                    project_path: the path of the proejct
                    project_dataframe (Dataframe): the dataframe containing the focal classes and the test classes for which to search the modules
                    project_id: the ID of the project
                    type_project: the type of the project (if Maven or Gradle project)
        Returns:
                    modules (List): the list of modules found
                    
    """
    project_df = project_dataframe.copy()
    modules = set()
    if type_project == 'Maven':
        for index, row in project_df.iterrows():
            location = row['Test_Path'].replace(f'repos/{project_id}/', '').replace(f"{row['Test_Class']}.java", '')
            while not os.path.isfile(f"{project_path}/{location}/target/site/jacoco/jacoco.csv") and not os.path.isfile(f"{project_path}/{location}/target/site/jacoco-ut/jacoco.csv"):
                location = os.path.dirname(location)
                if location == '':
                    break
            if location != '':
                modules.add(location)
    elif type_project == 'Gradle':
        for index, row in project_df.iterrows():
            location = row['Test_Path'].replace(f'repos/{project_id}/', '').replace(f"{row['Test_Class']}.java", '')
            while not os.path.isfile(f"{project_path}/{location}/build/reports/jacoco/jacoco.csv") and not os.path.isfile(f"{project_path}/{location}/build/reports/jacoco-ut/jacoco.csv"):
                location = os.path.dirname(location)
                if location == '':
                    break
            if location != '':
                modules.add(location)
    return list(modules)





def verify_mockito(type_project, path):
    """
    Verifies if the given project implements the Mockito framework or not.
        Parameters:
                    type_project: the type of the project (if Maven or Gradle project)
                    path: the path of the project or of the module
        Returns:
                   :'True' if the given project implements the Mockito framework, 'False' if the given project does not implement the Mockito framework or if an error occurred
                   
    """
    if type_project == 'Maven':
        ns = {'mvn': 'http://maven.apache.org/POM/4.0.0'}
        try:
            tree = ET.parse(os.path.join(path, 'pom.xml'))
            root = tree.getroot()
            dependencies_root=root.findall('mvn:dependencies/mvn:dependency', ns)
            dependencies_management=root.findall('mvn:dependencyManagement/mvn:dependencies/mvn:dependency', ns)
            all_dependencies=dependencies_root+dependencies_management
            for dependency in all_dependencies:
                group_id = dependency.find('mvn:groupId', ns)
                artifact_id = dependency.find('mvn:artifactId', ns)
                if group_id is not None and group_id.text.__contains__('org.mockito'):
                    return True
                elif artifact_id is not None and artifact_id.text.__contains__('mockito'):
                    return True
            return False
        except Exception as e:
            print(e)
            return False

    elif type_project == 'Gradle':
        path_build_gradle=os.path.join(path, 'build.gradle')
        path_build_gradle_kts=os.path.join(path, 'build.gradle.kts')
        path_file = None # path of the file to be opened
        try:
            if os.path.exists(path_build_gradle):
                path_file = path_build_gradle
            else:
                path_file = path_build_gradle_kts
            with open(path_file, 'r') as file:
                content=file.read()
                if content.__contains__('mockito'):
                    return True
                else:
                    return False
        except Exception as e:
            print(e)
            return False
    return False




def make_api_call(test_type, technique, focal_class, focal_path, testing_framework, java_version, has_mockito, test_path, name_test_class, project_structure, project_dependencies, package_test_class=None):
    """
    Legacy prompt-only generation entrypoint retained for backwards compatibility.
    Direct provider SDK usage has been removed from this helper.

    Returns:
            response: always returns None because the deprecated path no longer performs model calls.
    """
    print(_legacy_prompt_only_path_removed_message(test_type))
    return None, []


def generate_output_csv_project(project, project_dataframe, test_types, techniques, module=None):
    """
    Generates and saves the output CSV file that includes all the measures about all the test types applied in the project (code coverage, mutation coverage and number of test smells).
    Parameters:
                project: the ID of the project
                project_dataframe (Dataframe): the dataframe that contains all the focal classes and test classes involved in the test types 
                test_types: all the test types
                techniques: all the prompt techniques associated with the AI test types
                module: the name of the module (optional)
    Returns:
                df_output (Dataframe): the dataframe that includes all the measures about all the test types applied in the project (code coverage, mutation coverage and number of test smells).
                output_csv_path: the path of the CSV file that includes all the measures about all the test types applied in the project (code coverage, mutation coverage and number of test smells)    
    """
    # richiama il dataframe df_chance che si trova in mavenLib.py
    df_chance = mavenLib.df_chance
    project_df = project_dataframe.copy()
    files = os.listdir(f'output/{project}')
    # dictionary where the keys are the dataframes label and the values are the dataframes. There is a dataframe for each TestClasses file
    dataframes = dict()
    for test_type in test_types:
        if test_type == 'human' or  test_type == 'evosuite':
            dataframes[test_type] = pd.DataFrame()
        else:
            for technique in techniques:
                dataframes[f'{test_type}_{technique}'] = pd.DataFrame()

    # if the TestClasses file is maven failed or gradle failed (all the test classes failed during the maven execution), then leave the corresponding dataframe empty
    # if the TestClasses file is failed (generic error in AgoneTest.py) or not found, then set the corresponding dataframe to None
    # if the TestClasses file is a csv, then set the dataframe to the content of the csv
    if module is None:
        for key in dataframes.keys():
            find = False
            for file in files:
                if file.__contains__(f"TestClasses_{project}_{key}"):
                    find = True
                    if file.endswith(".csv"):
                        dataframes[key] = pd.read_csv(f'output/{project}/{file}')
                    elif file.endswith('.failed'):
                        dataframes[key] = None     
                    break
            if find == False:
                dataframes[key] = None
    else:
         for key in dataframes.keys():
            find = False
            for file in files:
                if file.__contains__(f"TestClasses_{project}_{module}_{key}"):
                    find = True
                    if file.endswith(".csv"):
                        dataframes[key] = pd.read_csv(f'output/{project}/{file}')
                    elif file.endswith('.failed'):
                        dataframes[key] = None
                    break
            if find == False:
                dataframes[key] = None
        

    # Remove from the dictionary the keys associated to a dataframe setted to None
    key_to_remove = set()
    for key in dataframes.keys():
        if dataframes[key] is None:
            key_to_remove.add(key)
    for key in key_to_remove:
        del dataframes[key]

    
    focal_classes = project_df['Focal_Class'].tolist() 
    data_df_output = []
    df_output = pd.DataFrame(data_df_output, columns=['ID_Focal_Class', 'Cyclomatic_Complexity_Focal_Class', 'Lines_Of_Code_Focal_Class', 'Generator(LLM/EVOSUITE)', 'Prompt_Technique', 'Branch_Coverage', 'Line_Coverage', 'Method_Coverage', 'Compilation', 'Mutation_Coverage','NumberOfMethods', 'Assertion Roulette', 'Conditional Test Logic',
        'Constructor Initialization', 'Default Test', 'EmptyTest',
        'Exception Catching Throwing', 'General Fixture', 'Mystery Guest',
        'Print Statement', 'Redundant Assertion', 'Sensitive Equality',
        'Verbose Test', 'Sleepy Test', 'Eager Test', 'Lazy Test',
        'Duplicate Assert', 'Unknown Test', 'IgnoredTest', 'Resource Optimism',
        'Magic Number Test', 'Dependent Test', 'Chance'])

    for focal_class in focal_classes:
        for test_type in test_types: 
            if test_type != "human" and test_type != "evosuite": # in other words, if test_type is an AI model
                for technique in techniques:
                    if (f"{test_type}_{technique}" in dataframes.keys()) == False:
                        continue
                    dataframe = dataframes.get(f'{test_type}_{technique}')
                    if dataframe is not None:
                        find_focal_class = False
                        for index, row in dataframe.iterrows():
                            if row['Focal_Class'] == focal_class:
                                if 'NumberOfMethods' in row.index:
                                    data_df_output = [f'{project}_{focal_class}', row['Cyclomatic_complexity'], row['Lines_of_code'], test_type, technique, row['Branch_coverage'], row['Line_coverage'], row['Method_coverage'], "1", row['Mutation_Coverage'], row['NumberOfMethods'], row['Assertion Roulette'], row['Conditional Test Logic'], row['Constructor Initialization'], row['Default Test'], row['EmptyTest'], row['Exception Catching Throwing'], row['General Fixture'], row['Mystery Guest'], row['Print Statement'], row['Redundant Assertion'], row['Sensitive Equality'], row['Verbose Test'], row['Sleepy Test'], row['Eager Test'], row['Lazy Test'], row['Duplicate Assert'], row['Unknown Test'], row['IgnoredTest'], row['Resource Optimism'], row['Magic Number Test'], row['Dependent Test']]
                                else:
                                    data_df_output = [f'{project}_{focal_class}', row['Cyclomatic_complexity'], row['Lines_of_code'], test_type, technique, row['Branch_coverage'], row['Line_coverage'], row['Method_coverage'], "1", row['Mutation_Coverage']]
                                find_focal_class = True
                                break
                        if find_focal_class == False:
                            data_df_output = [f'{project}_{focal_class}', row['Cyclomatic_complexity'], row['Lines_of_code'], test_type, technique, "-", "-", "-", "0", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-"]

                        if len(data_df_output) != len(df_output.columns):
                            missing_length = len(df_output.columns) - len(data_df_output)
                            print(f"Adjusting data_df_output length. Expected {len(df_output.columns)}, got {len(data_df_output)}")
                            data_df_output += ['-'] * missing_length  # Completa con '-' per le colonne mancanti

                        if len(data_df_output) == len(df_output.columns):
                            df_output.loc[len(df_output)] = data_df_output
                            nom = focal_class + 'Test'
                            for index, row in df_chance.iterrows():
                                if row['Test_Class'] == nom:
                                    df_output.at[len(df_output)-1, 'Chance'] = row['Chance']
                            if df_output.at[len(df_output) - 1, 'Chance'] == 6:
                                df_output.at[len(df_output) - 1, 'Compilation'] = "0"

                        else:
                            print(f"[Error]Error: Mismatched columns for focal class {focal_class}. Expected {len(df_output.columns)}, got {len(data_df_output)}")
                         
            else: # if the test_type is 'human' or 'evosuite'
                if (f"{test_type}" in dataframes.keys()) == False:
                        continue
                dataframe = dataframes[f'{test_type}']
                if dataframe is not None:
                    find_focal_class = False
                    for index, row in dataframe.iterrows():
                        if row['Focal_Class'] == focal_class:
                            if 'NumberOfMethods' in row.index:
                                data_df_output = [f'{project}_{focal_class}', row['Cyclomatic_complexity'], row['Lines_of_code'], test_type, "-", row['Branch_coverage'], row['Line_coverage'], row['Method_coverage'], "1", row['Mutation_Coverage'], row['NumberOfMethods'], row['Assertion Roulette'], row['Conditional Test Logic'], row['Constructor Initialization'], row['Default Test'], row['EmptyTest'], row['Exception Catching Throwing'], row['General Fixture'], row['Mystery Guest'], row['Print Statement'], row['Redundant Assertion'], row['Sensitive Equality'], row['Verbose Test'], row['Sleepy Test'], row['Eager Test'], row['Lazy Test'], row['Duplicate Assert'], row['Unknown Test'], row['IgnoredTest'], row['Resource Optimism'], row['Magic Number Test'], row['Dependent Test']]
                            else:
                                data_df_output = [f'{project}_{focal_class}', row['Cyclomatic_complexity'], row['Lines_of_code'], test_type, "-", row['Branch_coverage'], row['Line_coverage'], row['Method_coverage'], "1", row['Mutation_Coverage']]
                            find_focal_class = True
                            break
                    if find_focal_class == False:
                        data_df_output = [f'{project}_{focal_class}', row['Cyclomatic_complexity'], row['Lines_of_code'], test_type, "-", "-", "-", "0", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-"]

                    if len(data_df_output) != len(df_output.columns):
                        missing_length = len(df_output.columns) - len(data_df_output)
                        print(
                            f"Adjusting data_df_output length. Expected {len(df_output.columns)}, got {len(data_df_output)}")
                        data_df_output += ['-'] * missing_length  # Completa con '-' per le colonne mancanti

                    if len(data_df_output) == len(df_output.columns):
                            df_output.loc[len(df_output)] = data_df_output
                    else:
                        print(f"[Error]Error: Mismatched columns for focal class {focal_class}. Expected {len(df_output.columns)}, got {len(data_df_output)}")
                         
    if module is None:
        df_output_path = f"output/{project}/{project}_Output.csv"
    else:
        df_output_path = f"output/{project}/{project}_{module}_Output.csv"

    df_new_execution = pd.DataFrame()
    if os.path.exists(df_output_path):
        try:
            df_previous_execution = pd.read_csv(df_output_path)
            if not df_previous_execution.empty and not df_output.empty:
                df_new_execution = pd.concat([df_previous_execution, df_output], ignore_index=True)
            elif df_previous_execution.empty and not df_output.empty:
                df_new_execution = df_output
            else:
                df_new_execution = df_previous_execution
        except Exception as e:
            try:
                df_new_execution = df_output
            except Exception as e:
                print(e)
                return None
    else:
        try:
            df_new_execution = df_output
        except Exception as e:
            print(e)
            return None
    df_new_execution.drop_duplicates(subset={'ID_Focal_Class', 'Generator(LLM/EVOSUITE)', 'Prompt_Technique'}, keep='last', inplace=True)
    df_new_execution.to_csv(df_output_path, index=False, na_rep="-") 
        
    output_csv_path = f"/{project}_Output.csv"

    return df_new_execution, output_csv_path




def write_file(file_path, content):
    """
    Writes the given content in the given file. 
        Parameters:
                    file_path: the path of the file
                    content: the content that needs to be written                
    """
    try:
        with open(file_path, 'w') as file:
            file.write(content) 
    except Exception as e:
        print(e)



def write_files(dictionary_for_write):
   """
    Writes the given contents in the given files.
        Parameters:
                    dictionary_for_write: it has file paths as keys and file contents as values
    """
   for file_path, content in dictionary_for_write.items():
    try:
        with open(file_path, 'w') as file:
            file.write(content) 
    except Exception as e:
       print(e)



def remove_evosuite_scaffolding_files(test_paths):
    """
    Removes the scaffolding files added by evosuite.       
        Parameters:
                    test_paths (List): list containing all the paths that refere to test classes presumably associated to a scaffolding file
    """
    for test_path in test_paths:
        name_focal_class = ''
        regex_name_focal_class = r'/([^\/]+)\.java'
        match = re.search(regex_name_focal_class, test_path)
        if match:
            name_focal_class = match.group(0)
            name_focal_class = name_focal_class.replace('.java', '').replace('/', '').replace('Test', '').replace('test', '')

        regex_pattern = r'.*/'
        match = re.search(regex_pattern, test_path)
        if match:
            scaffolding_path = f"{match.group(0)}{name_focal_class}_ESTest_scaffolding.java"
            try:
                if os.path.exists(scaffolding_path):
                    os.remove(scaffolding_path)
            except Exception as e:
                print(e)



def remove_dot_evosuite_dir(project, module):
    """
    Removes the .evosuite directory    
        Parameters:
                    project: the ID of the project containing the .evosuite directory
                    module: the project module containing the .evosuite directory
    """
    if module is not None:
        dot_evosuite_to_remove = f'compiledrepos/{project}/{module}/.evosuite'
        try:
            if os.path.exists(dot_evosuite_to_remove):
                shutil.rmtree(dot_evosuite_to_remove)
        except Exception as e:
            print(e)


def find_module_class(project, class_path):
    """
    Searches the module of the given focal or test class. 
        Parameters:
                    project: the ID of the project
                    class_path: the path of the focal or test class
        Returns:
                    module: the module of the given focal of test class, 'None' if an error occurred

    """
    # Search the current module
    module = None
    regex = rf"{project}/(.*?)/"
    match = re.search(regex, class_path)
    if match:
        module = match.group(0)
        module = module.replace('/', '').replace(f'{project}', '')
        return  module
    else:
        return None
    

def remove_directory_evosuite_command_line():
    """
    Removes the directory generated by evosuite jar file  
    """
    evosuite_tests_path = 'evosuite-tests'
    evosuite_report_path = 'evosuite-report'
    if os.path.exists(evosuite_tests_path):
        shutil.rmtree(evosuite_tests_path)
    if os.path.exists(evosuite_report_path):
        shutil.rmtree(evosuite_report_path)


def check_version(version):
    """
    Check if the given version matches the correct pattern for versions (e.g., 1.2.3, 1.2, or 12.3.1).
        Parameters:
                version: the version to check
        Returns:
                :True if the given version matches the correct pattern for versions, False otherwise."""
    pattern = r'^(\d{1,3})(\.(\d{1,3}))*$'
    if version is None:
        return False
    if re.match(pattern, version):
        return True
    else:
        return False
    

def find_package(class_path):
    """
    Search the package of the given class.
        Parameters:
                class_path: the path of the focal or test class.
        Returns:
                :the package as a string, 'None' if the package was not found
    """
    with open(class_path, 'r') as class_file_read:
        class_content = class_file_read.read()
    cleaned_content = re.sub(r'//.*', '', class_content) # Remove the single-line comments
    cleaned_content = re.sub(r'/\*.*?\*/', '', cleaned_content, flags=re.DOTALL)  # Remove the multi-lines comments
    match = re.search(r'package\s+([\w.]+);', cleaned_content)
    if match:
        return match.group(1)
    else:
        return None
    


def find_max_value(values):
    """
    Search for the maximum value in the given list or set.
    
    Parameters:
            values (list or set): the list or set of values in which to search for the maximum.
        
    Returns:
            :the maximum value found, or 'None' if the given list/set is empty.
    """
    if len(values) == 0:
        return None
    if isinstance(values, set):
        values = list(values)
    max_value = values[0]
    for value in values:
        if value>max_value:
            max_value = value
    return max_value
            
    

def find_min_value(values):
    """
    Search for the minimum value in the given list or set.
    
    Parameters:
            values (list or set): the list or set of values in which to search for the minimum.
        
    Returns:
            :the minimum value found, or 'None' if the given list/set is empty.
    """
    if len(values) == 0:
        return None  
    if isinstance(values, set):
        values = list(values)
    min_value = values[0]
    for value in values:
        if value < min_value:
            min_value = value
    return min_value



def is_admin(system):
    """
    Check if the script is running with or without the administrator privileges.
    Parameters:
            system (String): the current OS (Windows, Linux, etc..)   
    Returns:
            :True if the script is running with the administrator privileges, False otherwise.
    """
    if system == 'Windows':
        try:
            return ctypes.windll.shell32.IsUserAnAdmin()
        except:
            return False
    else:
        try:
            if os.geteuid() == 0:
                return True
            else:
                return False
        except:
            return False



