import os  
import argparse  
import json  
import time  
from azure.identity import DefaultAzureCredential  
from azure.ai.ml import MLClient, Input, Output  
from azure.ai.ml.dsl import pipeline  
from azure.ai.ml.entities._job.pipeline._io import PipelineInput  
import subprocess  
from dotenv import load_dotenv  
  
def parse_config_file():  
    """Parse the configuration JSON file."""  
    with open("Infra/config.json") as config_file:  
        config = json.load(config_file)  
    return {  
        "CHUNK_SIZE": config['chunk_embed_index_deploy']['chunk_size'],  
        "CHUNK_OVERLAP": config['chunk_embed_index_deploy']['chunk_overlap'],  
        "ASSET_NAME": config['chunk_embed_index_deploy']['asset_name'],  
        "DATA_SOURCE": config['chunk_embed_index_deploy']['data_source'],  
        "EMBEDDINGS_MODEL": config['chunk_embed_index_deploy']['embeddings_model'],  
        "COMPUTE_SIZE": config['ml']['compute']['size']  
    }  
  
def load_env_vars():  
    """Load environment variables from .env file."""  
    env_path = os.path.join(os.getenv("PIPELINE_WORKSPACE"), ".env") 
    load_dotenv(env_path)  
    return {  
        "SUBSCRIPTION_ID": os.getenv("SUBSCRIPTION_ID"),  
        "RESOURCE_GROUP": os.getenv("RESOURCE_GROUP"),  
        "SERVICE_PRINCIPAL_ID": os.getenv("SERVICE_PRINCIPAL_ID"),  
        "ML_WORKSPACE_NAME": os.getenv("ML_WORKSPACE_NAME"),  
        "OPENAI_CONNECTION_NAME": os.getenv("OPENAI_CONNECTION_NAME"),  
        "AISEARCH_CONNECTION_NAME": os.getenv("AISEARCH_CONNECTION_NAME"),  
        "DOCUMENT_INTELLIGENCE_CONNECTION_NAME": os.getenv("DOCUMENT_INTELLIGENCE_CONNECTION_NAME"), 
        "STORAGE_ACCOUNT_NAME":os.getenv("STORAGE_ACCOUNT_NAME"), 
    }  
  
def run_pipeline(params):  
    """Run the Azure DevOps pipeline with the given parameters."""  
    try:  
        credential = DefaultAzureCredential()  
        credential.get_token("https://management.azure.com/.default")  
    except Exception as ex:  
        raise RuntimeError("Failed to obtain credential: " + str(ex))  
  
    ml_client = MLClient(  
        credential=credential,  
        subscription_id=params["SUBSCRIPTION_ID"],  
        resource_group_name=params["RESOURCE_GROUP"],  
        workspace_name=params["ML_WORKSPACE_NAME"]  
    )  
    ml_registry = MLClient(credential=ml_client._credential, registry_name="azureml")  
  
    generate_chunkembed_component = ml_registry.components.get("llm_rag_crack_and_chunk_and_embed", label="latest")  
    update_acs_index_component = ml_registry.components.get("llm_rag_update_acs_index", label="latest")  
    register_mlindex_asset_component = ml_registry.components.get("llm_rag_register_mlindex_asset", label="latest")  
  
    def use_automatic_compute(component, instance_count=1):  
        """Set automatic compute resources for the component."""  
        component.set_resources(instance_count=instance_count, instance_type=params["COMPUTE_SIZE"], properties={"compute_specification": {"automatic": True}})  
        return component  
  
    def optional_pipeline_input_provided(input: PipelineInput):  
        """Check if the optional pipeline input is provided."""  
        return input._data is not None  
  
    @pipeline(default_compute="serverless")  
    def uri_to_acs(input_data: Input, embeddings_model: str, acs_config: str, acs_connection_id: str, doc_intel_connection_id: str, asset_name: str, chunk_size: int, chunk_overlap: int, data_source_glob: str = None, aoai_connection_id: str = None, embeddings_container: Input = None):  
        """Pipeline definition for URI to ACS."""  
        generate_embeddings = generate_chunkembed_component(  
            input_data=input_data,  
            input_glob=data_source_glob,  
            chunk_size=chunk_size,  
            use_rcts=True,  
            chunk_overlap=chunk_overlap,  
            embeddings_connection_id=aoai_connection_id,  
            embeddings_container=embeddings_container,  
            embeddings_model=embeddings_model  
        )  
        use_automatic_compute(generate_embeddings)  
        if optional_pipeline_input_provided(aoai_connection_id):  
            generate_embeddings.environment_variables["AZUREML_WORKSPACE_CONNECTION_ID_AOAI"] = aoai_connection_id  
        if optional_pipeline_input_provided(embeddings_container):  
            generate_embeddings.outputs.embeddings = Output(type="uri_folder", path=f"{embeddings_container.path}/{{name}}")  
  
        update_acs_index = update_acs_index_component(  
            embeddings=generate_embeddings.outputs.embeddings,  
            acs_config=acs_config  
        )  
        use_automatic_compute(update_acs_index)  
        if optional_pipeline_input_provided(acs_connection_id):  
            update_acs_index.environment_variables["AZUREML_WORKSPACE_CONNECTION_ID_ACS"] = acs_connection_id  
  
        register_mlindex = register_mlindex_asset_component(  
            storage_uri=update_acs_index.outputs.index,  
            asset_name=asset_name  
        )  
        use_automatic_compute(register_mlindex)  
  
        return {"mlindex_asset_uri": update_acs_index.outputs.index, "mlindex_asset_id": register_mlindex.outputs.asset_id}  
  
    aoai_connection = ml_client.connections.get(params["OPENAI_CONNECTION_NAME"])  
    acs_connection = ml_client.connections.get(params["AISEARCH_CONNECTION_NAME"])  
    document_intelligence_connection_id = aoai_connection.id.replace(params["OPENAI_CONNECTION_NAME"], params["DOCUMENT_INTELLIGENCE_CONNECTION_NAME"])  
  
    pipeline_job = uri_to_acs(  
        input_data=Input(type="uri_folder", path=params["DATA_SOURCE"]),  
        data_source_glob="**/*",  
        chunk_overlap=params["CHUNK_OVERLAP"],  
        chunk_size=params["CHUNK_SIZE"],  
        embeddings_model=params["EMBEDDINGS_MODEL"],  
        aoai_connection_id=aoai_connection.id,  
        doc_intel_connection_id=document_intelligence_connection_id,  
        embeddings_container=Input(type="uri_folder", path=f"azureml://datastores/workspaceblobstore/paths/embeddings/{params['ASSET_NAME']}"),  
        acs_config=json.dumps({"index_name": params["ASSET_NAME"]}),  
        acs_connection_id=acs_connection.id,  
        asset_name=params['ASSET_NAME']  
    )  
  
    pipeline_job.display_name = params["ASSET_NAME"]  
    pipeline_job.settings.force_rerun = True  
    pipeline_job.properties["azureml.mlIndexAssetName"] = params["ASSET_NAME"]  
    pipeline_job.properties["azureml.mlIndexAssetKind"] = "acs"  
    pipeline_job.properties["azureml.mlIndexAssetSource"] = "AzureML Data"  
  
    print(f"Submitting pipeline job to experiment: {params['ASSET_NAME']}")  
    running_pipeline_job = ml_client.jobs.create_or_update(pipeline_job, experiment_name=params["ASSET_NAME"])  
    print(f"Submitted run, url: {running_pipeline_job.studio_url}")  
    print(f"Submitted id, id: {running_pipeline_job.id}")  
  
    with open("pipeline_job_id.txt", "w") as f:  
        f.write(running_pipeline_job.id)  
  
    job_id = running_pipeline_job.id  
    job_name = os.path.basename(job_id)  
  
    while True:  
        status = subprocess.run(  
            f"az ml job show --name {job_name} --resource-group {params['RESOURCE_GROUP']} --workspace-name {params['ML_WORKSPACE_NAME']} --query 'status' -o tsv",  
            shell=True, check=True, stdout=subprocess.PIPE, text=True  
        ).stdout.strip()  
  
        if "ERROR" in status:  
            print(f"An error occurred while checking job status: {status}")  
            print("Retrying in 60 seconds...")  
            time.sleep(60)  
            continue  
  
        print(f"Current job status: {status}")  
  
        if status == "Completed":  
            print("Job completed successfully.")  
            break  
        elif status == "Failed":  
            print("Job failed.")  
            exit(1)  
        else:  
            print("Job is still running. Waiting for 60 seconds...")  
            time.sleep(60)  
  
def main():  
    """Main function to load environment variables, parse configuration, and run the pipeline."""  
    env_vars = load_env_vars()  
    parsed_config = parse_config_file()  
    params = {**env_vars, **parsed_config}  
    subprocess.run(f"az storage account update \
        --name {params['STORAGE_ACCOUNT_NAME']} \
        --resource-group {params['RESOURCE_GROUP']} \
        --allow-shared-key-access true", shell=True)
    run_pipeline(params)  
  
if __name__ == "__main__":  
    main()  
