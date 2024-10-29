import os  
import time  
import json  
import random  
import string  
import subprocess  
  
def load_env_vars():  
    """  
    Load environment variables.  
      
    Returns:  
        dict: A dictionary containing the environment variables.  
    """  
    return {  
        "SERVICE_CONNECTION": os.getenv("SERVICE_CONNECTION"),  
        "SUBSCRIPTION_ID": os.getenv("SUBSCRIPTION_ID"),  
        "RESOURCE_GROUP": os.getenv("RESOURCE_GROUP"),  
        "LOCATION": os.getenv("LOCATION"),  
        "SERVICE_PRINCIPAL_ID": os.getenv("SERVICE_PRINCIPAL_ID"),  
        "PROVISION_RESOURCE": os.getenv("PROVISION_RESOURCE") == "true",  
    }  
  
def print_debug_info(env_vars):  
    """  
    Print environment variables for debugging.  
      
    Args:  
        env_vars (dict): A dictionary containing the environment variables.  
    """  
    for key, value in env_vars.items():  
        print(f"{key}: {value}")  
  
def validate_config_file():  
    """  
    Validate the presence of the configuration file.  
      
    Raises:  
        FileNotFoundError: If config.json is not found in Infra directory.  
    """  
    if not os.path.isfile("Infra/config.json"):  
        raise FileNotFoundError("Error: config.json not found in Infra directory.")  
  
def parse_config_file():  
    """  
    Parse the configuration file.  
      
    Returns:  
        dict: The parsed configuration file.  
    """  
    with open("Infra/config.json") as config_file:  
        config = json.load(config_file)  
    return config  
  
def generate_unique_prefix(length=3):  
    """  
    Generate a unique prefix with lowercase characters and numbers.  
      
    Args:  
        length (int): Length of the prefix.  
          
    Returns:  
        str: The generated prefix.  
    """  
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))  
  
def parse_and_generate_names():  
    """  
    Parse the configuration file and generate unique names.  
      
    Returns:  
        dict: A dictionary containing the generated names.  
    """  
    config = parse_config_file()  
    unique_prefix = generate_unique_prefix()  
  
    return {  
        "OPENAI_NAME": f"{config['openai']['name']}-{unique_prefix}",  
        "SEARCH_NAME": f"{config['search']['name']}-{unique_prefix}",  
        "FORMRECOGNIZER_NAME": f"{config['formrecognizer']['name']}-{unique_prefix}",  
        "ML_WORKSPACE_NAME": f"{config['ml']['workspace_name']}-{unique_prefix}",  
        "COMPUTE_NAME": f"{config['ml']['compute']['name']}-{unique_prefix}",  
        "COMPUTE_SIZE": config['ml']['compute']['size'],  
        "IDLE_TIME": config['ml']['compute']['idle_time_before_shutdown_minutes'],  
        "OPENAI_CONNECTION_NAME": config['aml_ws_connections']['openai_connection'],  
        "AISEARCH_CONNECTION_NAME": config['aml_ws_connections']['aisearch_connection'],  
        "DOCUMENT_INTELLIGENCE_CONNECTION_NAME": config['aml_ws_connections']['document_intelligence_connection'],  
    }  
  
def print_parsed_values(parsed_values):  
    """  
    Print parsed values for debugging.  
      
    Args:  
        parsed_values (dict): A dictionary containing the parsed values.  
    """  
    for key, value in parsed_values.items():  
        print(f"{key}: {value}")  
  
def run_azure_cli_command(command):  
    """  
    Run an Azure CLI command.  
      
    Args:  
        command (str): The Azure CLI command to run.  
          
    Returns:  
        str: The output of the command.  
          
    Raises:  
        RuntimeError: If the command fails.  
    """  
    result = subprocess.run(command, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)  
    if result.returncode != 0:  
        raise RuntimeError(f"Command failed with error: {result.stderr}")  
    return result.stdout.strip()  
  
def manage_resource_group(resource_group_name, location):  
    """  
    Manage resource group using Azure CLI.  
      
    Args:  
        resource_group_name (str): The name of the resource group.  
        location (str): The location of the resource group.  
    """  
    rg_exists = run_azure_cli_command(f"az group exists --name {resource_group_name}") == "true"  
  
    if rg_exists:  
        print(f"Resource group {resource_group_name} exists. Deleting it...")  
        run_azure_cli_command(f"az group delete --name {resource_group_name} --yes --no-wait")  
        run_azure_cli_command(f"az group wait --name {resource_group_name} --deleted")  
        print(f"Resource group {resource_group_name} has been deleted.")  
  
    print(f"Creating resource group {resource_group_name}...")  
    run_azure_cli_command(f"az group create --name {resource_group_name} --location {location}")  
    print(f"Provisioned resource group {resource_group_name}")  
  
def create_ai_services(search_name, formrecognizer_name, resource_group, location, subscription_id):  
    """  
    Create AI Search and Document Intelligence services using Azure CLI.  
      
    Args:  
        search_name (str): The name of the search service.  
        formrecognizer_name (str): The name of the form recognizer service.  
        resource_group (str): The resource group name.  
        location (str): The location.  
        subscription_id (str): The subscription ID.  
    """  
    print("Creating AI search and Azure Document Intelligence service")  
    run_azure_cli_command(f"az search service create --name {search_name} --resource-group {resource_group} --sku standard --location {location} --semantic-search standard --no-wait")  
    run_azure_cli_command(f"az search service wait --name {search_name} --resource-group {resource_group} --created")  
    run_azure_cli_command(f"az cognitiveservices account create --name {formrecognizer_name} --resource-group {resource_group} --location {location} --kind FormRecognizer --sku s0 --subscription {subscription_id} --yes")  
    print("AI search and Azure Document Intelligence services created successfully.")  

def create_openai_service(openai_name, resource_group, location, subscription_id):  
    """  
    Create Azure OpenAI service and wait until it's ready using Azure CLI.  
      
    Args:  
        openai_name (str): The name of the OpenAI service.  
        resource_group (str): The resource group name.  
        location (str): The location.  
        subscription_id (str): The subscription ID.  
    """  
    print("Creating Azure OpenAI service")  
    run_azure_cli_command(f"az cognitiveservices account create --name {openai_name} --resource-group {resource_group} --location {location} --kind OpenAI --sku s0 --subscription {subscription_id} --yes")  
  
    print("Waiting for Azure OpenAI service to be ready...")  
    while True:  
        openai_state = run_azure_cli_command(f"az cognitiveservices account show --name {openai_name} --resource-group {resource_group} --query 'properties.provisioningState' -o tsv")  
        if openai_state == "Succeeded":  
            print("Azure OpenAI service is ready.")  
            break  
        elif openai_state == "Failed":  
            print("Azure OpenAI service provisioning failed.")  
            exit(1)  
        else:  
            print(f"Waiting for OpenAI service provisioning... Current state: {openai_state}")  
            time.sleep(30)  
  
def create_ml_workspace(ml_workspace_name, resource_group, location, subscription_id):  
    """  
    Create Azure Machine Learning workspace and wait until it's ready using Azure CLI.  
      
    Args:  
        ml_workspace_name (str): The name of the ML workspace.  
        resource_group (str): The resource group name.  
        location (str): The location.  
        subscription_id (str): The subscription ID.  
    """  
    print("Creating Azure Machine Learning workspace...")  
    run_azure_cli_command(f"az ml workspace create --name {ml_workspace_name} --resource-group {resource_group} --location {location} --subscription {subscription_id}")  
  
    print("Waiting for Azure Machine Learning workspace to be ready...")  
    while True:  
        workspace_state = run_azure_cli_command(f"az resource show --resource-type Microsoft.MachineLearningServices/workspaces --name {ml_workspace_name} --resource-group {resource_group} --subscription {subscription_id} --query 'properties.provisioningState' -o tsv")  
        if workspace_state == "Succeeded":  
            print("ML workspace is ready.")  
            break  
        elif workspace_state == "Failed":  
            print("Workspace creation failed.")  
            exit(1)  
        else:  
            print(f"Waiting for workspace provisioning... Current state: {workspace_state}")  
            time.sleep(30)  
  
def deploy_openai_models(openai_name, resource_group):  
    """  
    Deploy OpenAI models.  
      
    Args:  
        openai_name (str): The name of the OpenAI service.  
        resource_group (str): The resource group name.  
    """  
    print("Deploying OpenAI models...")  
    config = parse_config_file()  
    models = config['openai']['models']  
  
    for model in models:  
        deployment_name = model['name']  
        model_name = model['model']['name']  
        model_version = model['model']['version']  
        model_format = model['model']['format']  
        sku_name = model['sku']['name']  
        sku_capacity = model['sku']['capacity']  
  
        run_azure_cli_command(  
            f"az cognitiveservices account deployment create --resource-group {resource_group} --name {openai_name} --deployment-name {deployment_name} --model-name {model_name} --model-version {model_version} --model-format {model_format} --sku-name {sku_name} --sku-capacity {sku_capacity}"  
        )  
    print("OpenAI models deployed successfully.")  
  
def retrieve_workspace_properties(ml_workspace_name, resource_group):  
    """  
    Retrieve workspace properties.  
      
    Args:  
        ml_workspace_name (str): The name of the ML workspace.  
        resource_group (str): The resource group name.  
          
    Returns:  
        tuple: Key Vault name, Storage Account name, and Application Insights name.  
    """  
    print("Retrieving workspace properties...")  
    workspace_properties = run_azure_cli_command(f"az ml workspace show --name {ml_workspace_name} --resource-group {resource_group}")  
    workspace_properties_json = json.loads(workspace_properties)  
  
    key_vault_name = os.path.basename(workspace_properties_json.get('key_vault', ''))  
    storage_account_name = os.path.basename(workspace_properties_json.get('storage_account', ''))  
    application_insights_name = os.path.basename(workspace_properties_json.get('application_insights', ''))  
  
    print(f"Key Vault Name: {key_vault_name}")  
    print(f"Storage Account Name: {storage_account_name}")  
    print(f"Application Insights Name: {application_insights_name}")  
  
    return key_vault_name, storage_account_name, application_insights_name  
  
def retrieve_endpoints_and_keys(openai_name, search_name, formrecognizer_name, resource_group, subscription_id):  
    """  
    Retrieve endpoints and API keys.  
      
    Args:  
        openai_name (str): The name of the OpenAI service.  
        search_name (str): The name of the search service.  
        formrecognizer_name (str): The name of the form recognizer service.  
        resource_group (str): The resource group name.  
        subscription_id (str): The subscription ID.  
          
    Returns:  
        dict: A dictionary containing endpoints and API keys.  
    """  
    print("Retrieving endpoints and API keys...")  
    openai_endpoint = run_azure_cli_command(f"az cognitiveservices account show --name {openai_name} --resource-group {resource_group} --query properties.endpoint -o tsv")  
    search_endpoint = f"https://{search_name}.search.windows.net/"  
    formrecognizer_endpoint = run_azure_cli_command(f"az cognitiveservices account show --name {formrecognizer_name} --resource-group {resource_group} --query properties.endpoint -o tsv")  
  
    openai_key = run_azure_cli_command(f"az cognitiveservices account keys list --name {openai_name} --resource-group {resource_group} --subscription {subscription_id} --query key1 -o tsv")  
    search_key = run_azure_cli_command(f"az search admin-key show --resource-group {resource_group} --service-name {search_name} --query primaryKey -o tsv")  
    formrecognizer_key = run_azure_cli_command(f"az cognitiveservices account keys list --name {formrecognizer_name} --resource-group {resource_group} --subscription {subscription_id} --query key1 -o tsv")  
  
    #print(f"OpenAI Endpoint: {openai_endpoint}")  
    #print(f"Search Endpoint: {search_endpoint}")  
    #print(f"Form Recognizer Endpoint: {formrecognizer_endpoint}")  
    #print(f"OpenAI Key: {openai_key}")  
    #print(f"Search Key: {search_key}")  
    #print(f"Form Recognizer Key: {formrecognizer_key}")  
  
    return {  
        "OPENAI_ENDPOINT": openai_endpoint,  
        "SEARCH_ENDPOINT": search_endpoint,  
        "FORMRECOGNIZER_ENDPOINT": formrecognizer_endpoint,  
        "OPENAI_KEY": openai_key,  
        "SEARCH_KEY": search_key,  
        "FORMRECOGNIZER_KEY": formrecognizer_key,  
    }  
  
def generate_yaml_file(file_name, content):  
    """  
    Generate a YAML file.  
      
    Args:  
        file_name (str): The name of the file.  
        content (str): The content to write to the file.  
    """  
    with open(file_name, 'w') as f:  
        f.write(content)  
  
def generate_yaml_files(parsed_values, endpoints_and_keys, env_vars):  
    """  
    Generate YAML files for connections.  
      
    Args:  
        parsed_values (dict): The parsed values.  
        endpoints_and_keys (dict): The endpoints and API keys.  
        env_vars (dict): The environment variables.  
    """  
    generate_yaml_file("openai_connection.yml", f"""  
name: {parsed_values["OPENAI_CONNECTION_NAME"]}  
type: azure_open_ai  
azure_endpoint: {endpoints_and_keys["OPENAI_ENDPOINT"]}  
api_key: {endpoints_and_keys["OPENAI_KEY"]}  
open_ai_resource_id: /subscriptions/{env_vars["SUBSCRIPTION_ID"]}/resourceGroups/{env_vars["RESOURCE_GROUP"]}/providers/Microsoft.CognitiveServices/accounts/{parsed_values["OPENAI_NAME"]}  
""")  
    generate_yaml_file("create-instance.yml", f"""  
name: {parsed_values["COMPUTE_NAME"]}  
type: computeinstance  
size: {parsed_values["COMPUTE_SIZE"]}  
idle_time_before_shutdown_minutes: {parsed_values["IDLE_TIME"]}  
""")  
    generate_yaml_file("search_connection.yml", f"""  
name: {parsed_values["AISEARCH_CONNECTION_NAME"]}  
type: azure_ai_search  
endpoint: {endpoints_and_keys["SEARCH_ENDPOINT"]}  
api_key: {endpoints_and_keys["SEARCH_KEY"]}  
""")  
    generate_yaml_file("formrecognizer_connection.yml", f"""  
name: {parsed_values["DOCUMENT_INTELLIGENCE_CONNECTION_NAME"]}  
type: api_key  
api_base: {endpoints_and_keys["FORMRECOGNIZER_ENDPOINT"]}  
api_key: {endpoints_and_keys["FORMRECOGNIZER_KEY"]}  
""")  
  
def generate_env_file(parsed_values, endpoints_and_keys, env_vars, key_vault_name, storage_account_name, application_insights_name):  
    """  
    Generate .env file.  
      
    Args:  
        parsed_values (dict): The parsed values.  
        endpoints_and_keys (dict): The endpoints and API keys.  
        env_vars (dict): The environment variables.  
        key_vault_name (str): The Key Vault name.  
        storage_account_name (str): The Storage Account name.  
        application_insights_name (str): The Application Insights name.  
    """  
    generate_yaml_file(".env", f"""  
SERVICE_CONNECTION={env_vars["SERVICE_CONNECTION"]}  
SUBSCRIPTION_ID={env_vars["SUBSCRIPTION_ID"]}  
RESOURCE_GROUP={env_vars["RESOURCE_GROUP"]}  
LOCATION={env_vars["LOCATION"]}  
OPENAI_NAME={parsed_values["OPENAI_NAME"]}  
SEARCH_NAME={parsed_values["SEARCH_NAME"]}  
FORMRECOGNIZER_NAME={parsed_values["FORMRECOGNIZER_NAME"]}  
ML_WORKSPACE_NAME={parsed_values["ML_WORKSPACE_NAME"]}  
KEY_VAULT_NAME={key_vault_name}  
STORAGE_ACCOUNT_NAME={storage_account_name}  
APPLICATION_INSIGHTS_NAME={application_insights_name}  
OPENAI_ENDPOINT={endpoints_and_keys["OPENAI_ENDPOINT"]}  
SEARCH_ENDPOINT={endpoints_and_keys["SEARCH_ENDPOINT"]}  
FORMRECOGNIZER_ENDPOINT={endpoints_and_keys["FORMRECOGNIZER_ENDPOINT"]}  
OPENAI_KEY={endpoints_and_keys["OPENAI_KEY"]}  
SEARCH_KEY={endpoints_and_keys["SEARCH_KEY"]}  
FORMRECOGNIZER_KEY={endpoints_and_keys["FORMRECOGNIZER_KEY"]}  
AISEARCH_CONNECTION_NAME={parsed_values["AISEARCH_CONNECTION_NAME"]}  
OPENAI_CONNECTION_NAME={parsed_values["OPENAI_CONNECTION_NAME"]}  
DOCUMENT_INTELLIGENCE_CONNECTION_NAME={parsed_values["DOCUMENT_INTELLIGENCE_CONNECTION_NAME"]}  
OPENAI_RESOURCE_ID=/subscriptions/{env_vars["SUBSCRIPTION_ID"]}/resourceGroups/{env_vars["RESOURCE_GROUP"]}/providers/Microsoft.CognitiveServices/accounts/{parsed_values["OPENAI_NAME"]}  
COMPUTE_SIZE={parsed_values["COMPUTE_SIZE"]}  
""")  
  
def create_aml_connections(resource_group, ml_workspace_name):  
    """  
    Create connections in Azure ML.  
      
    Args:  
        resource_group (str): The resource group name.  
        ml_workspace_name (str): The name of the ML workspace.  
    """  
    print("Creating OpenAI connection...")  
    run_azure_cli_command(f"az ml connection create --file openai_connection.yml --resource-group {resource_group} --workspace-name {ml_workspace_name}")  
    print("Creating Search connection...")  
    run_azure_cli_command(f"az ml connection create --file search_connection.yml --resource-group {resource_group} --workspace-name {ml_workspace_name}")  
    print("Creating Form Recognizer connection...")  
    run_azure_cli_command(f"az ml connection create --file formrecognizer_connection.yml --resource-group {resource_group} --workspace-name {ml_workspace_name}")  
  
def create_compute_instance(resource_group, ml_workspace_name):  
    """  
    Create compute instance using YAML definition.  
      
    Args:  
        resource_group (str): The resource group name.  
        ml_workspace_name (str): The name of the ML workspace.  
    """  
    print("Creating compute instance from YAML definition...")  
    run_azure_cli_command(f"az ml compute create -f create-instance.yml --resource-group {resource_group} --workspace-name {ml_workspace_name}")  
  
def save_env_and_samplepdf_blobstore(resource_group, ml_workspace_name, storage_account_name):  
    """  
    Save .env file and sample PDF to Azure ML default datastore.  
      
    Args:  
        resource_group (str): The resource group name.  
        ml_workspace_name (str): The name of the ML workspace.  
        storage_account_name (str): The storage account name.  
    """  
    mycontainer = run_azure_cli_command(f"az ml datastore show --name workspaceblobstore --resource-group {resource_group} --workspace-name {ml_workspace_name} --query container_name --output tsv")  
    print("Uploading .env to AML workspace blob storage")  
    run_azure_cli_command(f"az storage blob upload --account-name {storage_account_name} --container-name {mycontainer} --name Environement/.env --file .env")  
    print("Uploading sample.pdf file from Data Folder to AML workspace blob storage")  
    run_azure_cli_command(f"az storage blob upload --account-name {storage_account_name} --container-name {mycontainer} --name Data/sample.pdf --file Data/sample.pdf")  
  
# Main function to orchestrate the steps  
def main():
    print("Load environment variables")  
    env_vars = load_env_vars()  
    print_debug_info(env_vars)  
    validate_config_file()  
    print("Parse the configuration file and generate unique names")
    parsed_values = parse_and_generate_names()  
    print_parsed_values(parsed_values)  
  
    if env_vars["PROVISION_RESOURCE"]:  
       
        manage_resource_group(env_vars["RESOURCE_GROUP"], env_vars["LOCATION"]) 
        create_ai_services(parsed_values["SEARCH_NAME"], parsed_values["FORMRECOGNIZER_NAME"], env_vars["RESOURCE_GROUP"], env_vars["LOCATION"], env_vars["SUBSCRIPTION_ID"])  
        create_openai_service(parsed_values["OPENAI_NAME"], env_vars["RESOURCE_GROUP"], env_vars["LOCATION"], env_vars["SUBSCRIPTION_ID"]) 
        create_ml_workspace(parsed_values["ML_WORKSPACE_NAME"], env_vars["RESOURCE_GROUP"], env_vars["LOCATION"], env_vars["SUBSCRIPTION_ID"])  
        deploy_openai_models(parsed_values["OPENAI_NAME"], env_vars["RESOURCE_GROUP"])  
        key_vault_name, storage_account_name, application_insights_name = retrieve_workspace_properties(parsed_values["ML_WORKSPACE_NAME"], env_vars["RESOURCE_GROUP"])  
        endpoints_and_keys = retrieve_endpoints_and_keys(parsed_values["OPENAI_NAME"], parsed_values["SEARCH_NAME"], parsed_values["FORMRECOGNIZER_NAME"], env_vars["RESOURCE_GROUP"], env_vars["SUBSCRIPTION_ID"])  
        generate_yaml_files(parsed_values, endpoints_and_keys, env_vars)  
        generate_env_file(parsed_values, endpoints_and_keys, env_vars, key_vault_name, storage_account_name, application_insights_name)  
        create_aml_connections(env_vars["RESOURCE_GROUP"], parsed_values["ML_WORKSPACE_NAME"])  
        #create_compute_instance(env_vars["RESOURCE_GROUP"], parsed_values["ML_WORKSPACE_NAME"])  
        save_env_and_samplepdf_blobstore(env_vars["RESOURCE_GROUP"], parsed_values["ML_WORKSPACE_NAME"], storage_account_name)  
  
if __name__ == "__main__":  
    main()  
