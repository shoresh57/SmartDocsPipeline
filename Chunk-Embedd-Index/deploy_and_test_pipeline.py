import os  
import json  
import time  
import subprocess  
from azure.identity import DefaultAzureCredential  
from azure.ai.ml import MLClient, Input  
from azure.ai.ml.entities import BatchEndpoint, PipelineComponentBatchDeployment  
from dotenv import load_dotenv  
  
  
def parse_config_file():  
    """Parse the configuration JSON file."""  
    with open("Infra/config.json") as config_file:  
        config = json.load(config_file)  
    return {  
        "ENDPOINT_NAME": config['chunk_embed_index_deploy']['endpoint_name'],  
        "DEPLOYMENT_NAME": config['chunk_embed_index_deploy']['deployment_name'],  
        "ASSET_NAME": config['chunk_embed_index_deploy']['asset_name'],  
        "DATA_SOURCE": config['chunk_embed_index_deploy']['data_source']  
    }  
  
  
def load_env_vars():  
    """Load environment variables from .env file."""  
    env_path = os.path.join(os.getenv("PIPELINE_WORKSPACE"), ".env")  
    load_dotenv(env_path)  
    return {  
        "SUBSCRIPTION_ID": os.getenv("SUBSCRIPTION_ID"),  
        "RESOURCE_GROUP": os.getenv("RESOURCE_GROUP"),  
        "ML_WORKSPACE_NAME": os.getenv("ML_WORKSPACE_NAME"),  
    }  
  
  
def get_ml_client(params):  
    """Get an MLClient with the default Azure credential."""  
    try:  
        credential = DefaultAzureCredential()  
        credential.get_token("https://management.azure.com/.default")  
    except Exception as ex:  
        raise RuntimeError("Failed to obtain credential: " + str(ex))  
  
    return MLClient(  
        credential=credential,  
        subscription_id=params["SUBSCRIPTION_ID"],  
        resource_group_name=params["RESOURCE_GROUP"],  
        workspace_name=params["ML_WORKSPACE_NAME"]  
    )  
  
  
def create_endpoint(params):  
    """Create or update the batch endpoint."""  
    ml_client = get_ml_client(params)  
  
    endpoint = BatchEndpoint(  
        name=params["ENDPOINT_NAME"],  
        description="deploy pipeline for cracking and embedding",  
    )  
    ml_client.batch_endpoints.begin_create_or_update(endpoint).result()  
  
  
def deploy_batch_pipeline(params, job_id):  
    """Deploy the batch pipeline."""  
    ml_client = get_ml_client(params)  
  
    deployment = PipelineComponentBatchDeployment(  
        name=params["DEPLOYMENT_NAME"],  
        description="deploy pipeline for cracking and embedding",  
        endpoint_name=params["ENDPOINT_NAME"],  
        job_definition=job_id,  
        settings={"default_compute": "serverless", "force_rerun": True},  
    )  
  
    ml_client.batch_deployments.begin_create_or_update(deployment).result()  
    endpoint = ml_client.batch_endpoints.get(params["ENDPOINT_NAME"])  
    endpoint.defaults.deployment_name = params["DEPLOYMENT_NAME"]  
    ml_client.batch_endpoints.begin_create_or_update(endpoint).result()  
  
  
def wait_for_deployment(params):  
    """Wait for deployment to complete."""  
    while True:  
        status = subprocess.run(  
            f"az ml batch-deployment show --name {params['DEPLOYMENT_NAME']} --endpoint-name {params['ENDPOINT_NAME']} --resource-group {params['RESOURCE_GROUP']} --workspace-name {params['ML_WORKSPACE_NAME']} --query 'provisioning_state' -o tsv",  
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
  
  
def test_endpoint(params):  
    """Test the endpoint."""  
    ml_client = get_ml_client(params)  
  
    input_data = Input(type="uri_folder", path=params["DATA_SOURCE"])  
    embeddings_container = Input(type="uri_folder", path=f"azureml://datastores/workspaceblobstore/paths/embeddings/{params['ASSET_NAME']}")  
  
    job = ml_client.batch_endpoints.invoke(  
        endpoint_name=params["ENDPOINT_NAME"],  
        inputs={"input_data": input_data, "embeddings_container": embeddings_container}  
    )  
  
    ml_client.jobs.stream(name=job.name)  
  
  
def main():  
    """Main function to load environment variables, parse configuration, and run deployment and testing."""  
    env_vars = load_env_vars()  
    parsed_config = parse_config_file()  
    params = {**env_vars, **parsed_config}  
  
    job_id_path = os.path.join(os.getenv("PIPELINE_WORKSPACE"), "pipeline_job_id.txt")  
    with open(job_id_path, "r") as f:  
        job_id = f.read().strip()  
  
    create_endpoint(params)  
    deploy_batch_pipeline(params, job_id)  
    wait_for_deployment(params)  
    test_endpoint(params)  
  
  
if __name__ == "__main__":  
    main()  
