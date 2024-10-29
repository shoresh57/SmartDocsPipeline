import os  
import json  
import datetime  
import time
from azure.ai.ml import MLClient  
from azure.identity import DefaultAzureCredential  
from promptflow.azure import PFClient  
from dotenv import load_dotenv  
from azure.ai.ml.entities import AzureOpenAIConnection, Data  
from azure.ai.ml.constants import AssetTypes  
  
def load_environment():  
    """Load environment variables from .env file."""  
    dotenv_path = os.path.join(os.getenv("PIPELINE_WORKSPACE", ""), ".env")  
    load_dotenv(dotenv_path)  
  
def load_config():  
    """Load configuration from config.json."""  
    with open("Infra/config.json") as f:  
        return json.load(f)  
  
def get_credentials():  
    """Get Azure credentials."""  
    try:  
        credential = DefaultAzureCredential()  
        credential.get_token("https://management.azure.com/.default")  
        return credential  
    except Exception as ex:  
        raise RuntimeError("Failed to obtain credential: " + str(ex))  
  
def check_data_path(data_path):  
    """Verify if the given data path exists."""  
    data_path = os.path.normpath(data_path)  
    if os.path.exists(data_path):  
        print(f"Data path exists: {data_path}")  
    else:  
        print(f"Data path does not exist: {data_path}")  
    return data_path  
  
def create_connection(ml_client, connection_name, api_base, credential, api_key, api_version, open_ai_resource_id):  
    """Create or update the AzureOpenAI connection."""  
    wps_connection = AzureOpenAIConnection(  
        name=connection_name,  
        azure_endpoint=api_base,  
        credentials=credential,  
        api_key=api_key,  
        api_version=api_version,  
        open_ai_resource_id=open_ai_resource_id,  
        api_type="azure"  
    )  
    ml_client.connections.create_or_update(wps_connection)  
  
def main():  
    # Load environment and config  
    load_environment()  
    config = load_config()  
  
    connection_name = config["openai"]["name"]  
    api_base = os.getenv("OPENAI_ENDPOINT")  
    api_key = os.getenv("OPENAI_KEY")  
    api_version = config["openai"]["api_version"]  
    openai_resource_id = os.getenv("OPENAI_RESOURCE_ID")  
    subscription_id = os.getenv("SUBSCRIPTION_ID")  
    resource_group = os.getenv("RESOURCE_GROUP")  
    ml_workspace_name = os.getenv("ML_WORKSPACE_NAME")  
  
    # Get credentials  
    credential = get_credentials()  
  
    # Initialize clients  
    pf = PFClient(  
        credential=credential,  
        subscription_id=subscription_id,  
        resource_group_name=resource_group,  
        workspace_name=ml_workspace_name  
    )  
    ml_client = MLClient(  
        credential=credential,  
        subscription_id=subscription_id,  
        resource_group_name=resource_group,  
        workspace_name=ml_workspace_name  
    )  
  
    # Create connection  
    create_connection(ml_client, connection_name, api_base, credential, api_key, api_version, openai_resource_id)  
  
    # Determine the full path to the data file  
    current_dir = os.path.dirname(os.path.abspath(__file__))  
    data_path = os.path.join(current_dir, '..', 'Data', 'data.jsonl')  
    data_path = check_data_path(data_path)  
  
    # Define and create Data asset  
    my_data = Data(  
        path=data_path,  
        type=AssetTypes.URI_FILE,  
        description="Data for evaluation and chatflow in ml studio gui",  
        name="evaluation"  
    )  
    ml_client.data.create_or_update(my_data)  
  
    # Run the flow  
    flow = "Flow/ChatFlow"  
    now = datetime.datetime.now()  
    pf_name = f"chat-flow"  
    
    # Retry logic for creating the flow
    retries = 1
    for attempt in range(retries + 1):  # Try once, then retry if failed
        try:
            pf.flows.create_or_update(flow=flow, display_name=pf_name, type="chat")
            print(f"Flow {pf_name} created successfully.")
            break  # Exit the loop if successful
        except Exception as e:
            if attempt < retries:
                print(f"Failed to create flow {pf_name}. Retrying in 60 seconds...")
                time.sleep(60)  # Wait 60 seconds before retrying
            else:
                print(f"Failed to create flow {pf_name} after {retries + 1} attempts. Error: {e}")
                raise  # Re-raise the exception after retries are exhausted
     
  
    # Create a run with a different variant node  
    variant_run = pf.run(  
        flow=flow,  
        data=data_path,  
        column_mapping={  
            "query": "${data.question}",  
            "chat_history": []  
        },  
        variant="${generateReply.variant_0}"  
    )  
    pf.stream(variant_run)  
    details = pf.get_details(variant_run)  
    print(details.head(10))  
  
    # Evaluate flow similarity  
    eval_flow_similarity = "Flow/Evaluation/Similarity"  
    eval_run_variant_similarity = pf.run(  
        flow=eval_flow_similarity,  
        data=data_path,  
        run=variant_run,  
        column_mapping={  
            "question": "${data.question}",  
            "ground_truth": "${data.ground_truth}",  
            "answer": "${run.outputs.reply}",  
        }  
    )  
    pf.stream(eval_run_variant_similarity)  
    similarity_metrics = pf.get_metrics(eval_run_variant_similarity)  
    print("Similarity:")  
    print(json.dumps(similarity_metrics, indent=4))  
  
    # Evaluate flow groundedness  
    eval_flow_ground = "Flow/Evaluation/Groundedness"  
    eval_run_variant_ground = pf.run(  
        flow=eval_flow_ground,  
        data=data_path,  
        run=variant_run,  
        column_mapping={  
            "question": "${data.question}",  
            "context": "${data.context}",  
            "answer": "${run.outputs.reply}",  
        }  
    )  
    pf.stream(eval_run_variant_ground)  
    ground_metrics = pf.get_metrics(eval_run_variant_ground)  
    print("Groundedness:")  
    print(json.dumps(ground_metrics, indent=4))  
  
    # Combine metrics and decide deployment  
    combined_metrics = {  
        "gpt_similarity": similarity_metrics.get("gpt_similarity", 0),  
        "gpt_similarity_pass_rate(%)": similarity_metrics.get("gpt_similarity_pass_rate(%)", 0),  
        "gpt_groundedness": ground_metrics.get("gpt_groundedness", 0),  
        "gpt_groundedness_pass_rate(%)": ground_metrics.get("gpt_groundedness_pass_rate(%)", 0)  
    }  
    score = 0.5 * combined_metrics["gpt_similarity"] + 0.5 * combined_metrics["gpt_groundedness"]  
    threshold = 3.5  
    decision = "yes" if score > threshold else "no"  
  
    # Combine metrics and decision into a dictionary  
    output_data = {  
        "decision": decision,  
        "combined_metrics": combined_metrics  
    }  
  
    # Save the dictionary to a JSON file  
    with open("deploy.json", "w") as f:  
        json.dump(output_data, f, indent=4)  
  
    # Print results  
    print(json.dumps(combined_metrics, indent=4))  
    print(f"Decision: {decision}")  
  
if __name__ == "__main__":  
    main()  
