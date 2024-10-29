import os  
import uuid  
import json  
import time  
import subprocess  
from azure.identity import DefaultAzureCredential  
from azure.ai.ml import MLClient  
from azure.ai.ml.entities import ManagedOnlineEndpoint, ManagedOnlineDeployment, Model, Environment , BuildContext 
from dotenv import load_dotenv  
from azure.mgmt.authorization import AuthorizationManagementClient  
from azure.mgmt.authorization.models import RoleAssignmentCreateParameters  
  
def load_config():  
    """Load configuration from JSON and .env files."""  
    with open("Infra/config.json") as config_file:  
        config = json.load(config_file)  
  
    env_path = os.path.join(os.getenv("PIPELINE_WORKSPACE"), ".env")  
    load_dotenv(env_path)  
  
    return {  
        "FLOW_ENDPOINT_NAME": config['flow']['flow_endpoint_name'],  
        "FLOW_DEPLOYMENT_NAME": config['flow']['flow_deployment_name'],  
        "COMPUTE_SIZE": config['ml']['compute']['size'],  
        "FLOW_PATH": config['flow']['flow_path'],  
        "SUBSCRIPTION_ID": os.getenv("SUBSCRIPTION_ID"),  
        "RESOURCE_GROUP": os.getenv("RESOURCE_GROUP"),  
        "ML_WORKSPACE_NAME": os.getenv("ML_WORKSPACE_NAME"),  
        "OPENAI_CONNECTION_NAME": os.getenv("OPENAI_CONNECTION_NAME"),  
        "AISEARCH_CONNECTION_NAME": os.getenv("AISEARCH_CONNECTION_NAME"), 
        "OPENAI_NAME": os.getenv("OPENAI_NAME"), 
        "SEARCH_NAME": os.getenv("SEARCH_NAME"), 
    }  
  
def get_ml_client(config):  
    """Get an MLClient with the default Azure credential."""  
    try:  
        credential = DefaultAzureCredential()  
        credential.get_token("https://management.azure.com/.default")  
    except Exception as ex:  
        raise RuntimeError(f"Failed to obtain credential: {ex}")  
  
    return MLClient(  
        credential=credential,  
        subscription_id=config["SUBSCRIPTION_ID"],  
        resource_group_name=config["RESOURCE_GROUP"],  
        workspace_name=config["ML_WORKSPACE_NAME"]  
    )  
  
def create_role_assignment(scope, role_name, principal_id):  
    """Create a role assignment."""  
    credential = DefaultAzureCredential()  
    auth_client = AuthorizationManagementClient(  
        credential=credential,  
        subscription_id=os.getenv("SUBSCRIPTION_ID")  
    )  
  
    roles = list(auth_client.role_definitions.list(  
        scope, filter=f"roleName eq '{role_name}'"  
    ))  
      
    if len(roles) != 1:  
        raise ValueError("Role not found or not unique.")  
      
    role = roles[0]  
    parameters = RoleAssignmentCreateParameters(  
        role_definition_id=role.id,  
        principal_id=principal_id,  
        principal_type="ServicePrincipal"  
    )  
  
    return auth_client.role_assignments.create(  
        scope=scope,  
        role_assignment_name=uuid.uuid4(),  
        parameters=parameters  
    )  
  
def create_endpoint(config):  
    """Create or update the online endpoint."""  
    ml_client = get_ml_client(config)  
  
    endpoint = ManagedOnlineEndpoint(  
        name=config["FLOW_ENDPOINT_NAME"],  
        properties={"enforce_access_to_default_secret_stores": "enabled"},  
        description="Deploy online endpoint for chat flow",  
        auth_mode="key"
    
    )  
  
    operation = ml_client.online_endpoints.begin_create_or_update(endpoint)  
    #operation.wait()  # Wait for the operation to complete  
    time.sleep(120)
    # Refresh endpoint details to get the latest status  
    endpoint = ml_client.online_endpoints.get(config["FLOW_ENDPOINT_NAME"])  
    print(endpoint)
    # Check if identity is assigned  
    if not endpoint.identity:  
        raise RuntimeError("Failed to assign identity to the endpoint.")  
  
    system_principal_id = endpoint.identity.principal_id  
    command = (  
        f"az role assignment create --assignee {system_principal_id} "  
        f"--role \"Azure Machine Learning Workspace Connection Secrets Reader\" "  
        f"--scope /subscriptions/{config['SUBSCRIPTION_ID']}/resourcegroups/{config['RESOURCE_GROUP']}/"  
        f"providers/Microsoft.MachineLearningServices/workspaces/{config['ML_WORKSPACE_NAME']}"  
    )  
    subprocess.run(command, shell=True, check=True) 
  
def deploy_managed_online(config):  
    """Deploy the online pipeline."""  
    ml_client = get_ml_client(config)  
  
    model = Model(  
        path=config["FLOW_PATH"],  
        properties={  
            "azureml.promptflow.source_flow_id": "ragflow",  
            "azureml.promptflow.mode": "chat",  
            "azureml.promptflow.chat_input": "query",  
            "azureml.promptflow.chat_output": "reply",  
        },  
    )  
  
    env = Environment( 
    build=BuildContext(
            path=config["FLOW_PATH"],
        ),  
    inference_config={  
        "liveness_route": {"path": "/health", "port": 8080},  
        "readiness_route": {"path": "/health", "port": 8080},  
        "scoring_route": {"path": "/score", "port": 8080},  
      },  
    )
  
    deployment = ManagedOnlineDeployment(  
        name=config["FLOW_DEPLOYMENT_NAME"],  
        description="Deploy flow as managed online",  
        endpoint_name=config["FLOW_ENDPOINT_NAME"],  
        model=model,
        environment=env,  
        instance_type=config["COMPUTE_SIZE"],  
        instance_count=1,  
        environment_variables={  
            "PF_DISABLE_TRACING": "true",
            "PRT_CONFIG_OVERRIDE":   
                f"deployment.subscription_id={config['SUBSCRIPTION_ID']},deployment.resource_group={config['RESOURCE_GROUP']},deployment.workspace_name={config['ML_WORKSPACE_NAME']},deployment.endpoint_name={config['FLOW_ENDPOINT_NAME']},deployment.deployment_name={config['FLOW_DEPLOYMENT_NAME']}" , 
            
        },  
    )  
  
    ml_client.online_deployments.begin_create_or_update(deployment).result()  
  
    endpoint = ml_client.online_endpoints.get(config["FLOW_ENDPOINT_NAME"])  
    endpoint.traffic = {config["FLOW_DEPLOYMENT_NAME"]: 100}  
    ml_client.online_endpoints.begin_create_or_update(endpoint).result()  
    # Provide endpoint access  
    for service, role_name in [  
        (config["OPENAI_NAME"], "Cognitive Services OpenAI User"),  
        (config["SEARCH_NAME"], "Search Index Data Contributor")  
    ]:  
        if role_name == "Cognitive Services OpenAI User":  
            scope = f"/subscriptions/{config['SUBSCRIPTION_ID']}/resourceGroups/{config['RESOURCE_GROUP']}/providers/Microsoft.CognitiveServices/accounts/{service}"  
        elif role_name == "Search Index Data Contributor":  
            scope = f"/subscriptions/{config['SUBSCRIPTION_ID']}/resourceGroups/{config['RESOURCE_GROUP']}/providers/Microsoft.Search/searchServices/{service}"  
        
        create_role_assignment(  
            scope=scope,  
            role_name=role_name,  
            principal_id=endpoint.identity.principal_id  
        )  
  
def wait_for_deployment(config):  
    """Wait for deployment to complete."""  
    while True:  
        status = subprocess.run(  
            (  
                f"az ml online-deployment show --name {config['FLOW_DEPLOYMENT_NAME']} "  
                f"--endpoint-name {config['FLOW_ENDPOINT_NAME']} "  
                f"--resource-group {config['RESOURCE_GROUP']} "  
                f"--workspace-name {config['ML_WORKSPACE_NAME']} "  
                "--query 'provisioning_state' -o tsv"  
            ),  
            shell=True, check=True, stdout=subprocess.PIPE, text=True  
        ).stdout.strip()  
  
        if status == "Succeeded":  
            print("Deployment completed successfully.")  
            break  
        elif status in ["Failed", "Canceled"]:  
            print(f"Deployment {status.lower()}.")  
            exit(1)  
        else:  
            print(f"Deployment is {status.lower()}. Waiting for 60 seconds...")  
            time.sleep(60)  
  
def test_endpoint(config):  
    """Test the endpoint."""  
    ml_client = get_ml_client(config)  
    current_dir = os.path.dirname(os.path.abspath(__file__))  
    data_path = os.path.join(current_dir, '..', 'Data', 'sample-request.json')  
    scoring_uri = ml_client.online_endpoints.get(name=config["FLOW_ENDPOINT_NAME"]).scoring_uri
    print(scoring_uri)
    DATA_PLANE_TOKEN = ml_client.online_endpoints.get_keys(name=config["FLOW_ENDPOINT_NAME"]).primary_key
    print(DATA_PLANE_TOKEN)
    
    import urllib.request
    import ssl

    def allowSelfSignedHttps(allowed):
        # bypass the server certificate verification on client side
        if allowed and not os.environ.get('PYTHONHTTPSVERIFY', '') and getattr(ssl, '_create_unverified_context', None):
            ssl._create_default_https_context = ssl._create_unverified_context

    allowSelfSignedHttps(True) # this line is needed if you use self-signed certificate in your scoring service.

    # Request data goes here
    # The example below assumes JSON formatting which may be updated
    # depending on the format your endpoint expects.
    # More information can be found here:
    # https://docs.microsoft.com/azure/machine-learning/how-to-deploy-advanced-entry-script
    with open(data_path, 'r') as file:  
        data = json.load(file) 

    body = str.encode(json.dumps(data))

    url = scoring_uri
    # Replace this with the primary/secondary key, AMLToken, or Microsoft Entra ID token for the endpoint
    api_key =DATA_PLANE_TOKEN  
    if not api_key:
        raise Exception("A key should be provided to invoke the endpoint")


    headers = {'Content-Type':'application/json', 'Authorization':('Bearer '+ api_key)}
    for attempt in range(3):  
        try:  
            req = urllib.request.Request(url, body, headers)  
            response = urllib.request.urlopen(req)  
            result = response.read()  
  
            # Parse the JSON response  
            result_json = json.loads(result)  
            # Extract and print the reply part  
            reply = result_json.get("reply", "No reply found")  
            print(reply)  
            break  # Exit loop if successful  
  
        except Exception as e:  
            print(f"Attempt {attempt + 1}: Failed to reach endpoint. Error: {e}")  
            if attempt < 2:  # Don't wait after the last attempt  
                time.sleep(120)  
            else:  
                print("Failed to reach the endpoint after 3 attempts.") 

def get_decision_from_json(path_file):  
    """Open deploy.json and retrieve the decision value."""  
    try:  
        with open(path_file, "r") as f:  
            data = json.load(f)  
            return data.get("decision")  
    except (FileNotFoundError, json.JSONDecodeError) as e:  
        print(f"Error reading deploy.json: {e}")  
        return None  
  
def main():  
    """Main function to load environment variables, parse configuration, and run deployment and testing."""  
    config = load_config()  
    create_endpoint(config)  
    deploy_managed_online(config)  
    wait_for_deployment(config)  
    time.sleep(120)
    test_endpoint(config)  
  
if __name__ == "__main__":  
    path_file = os.path.join(os.getenv("PIPELINE_WORKSPACE"), "deploy.json")  
    decision = get_decision_from_json(path_file)  
    if decision == "yes":  
        main()  
    else:  
        print("Decision was not 'yes'. Main will not run. It means evaluation flow didn't pass criteria to be deployed.")  
