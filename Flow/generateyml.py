import os  
import json  
import re  
from dotenv import load_dotenv  
#from promptflow.client import PFClient  
#from promptflow.connections import AzureOpenAIConnection  
# azure version promptflow apis
#from promptflow.azure import PFClient
#from azure.identity import DefaultAzureCredential  
#from azure.ai.ml.entities import AzureOpenAIConnection
#from azure.ai.ml import MLClient
  
# Load environment variables from .env file  
dotenv_path = os.path.join(os.getenv("PIPELINE_WORKSPACE", ""), ".env")  
load_dotenv(dotenv_path)  
  
# Load config.json  
with open("Infra/config.json") as f:  
    config = json.load(f)  
  
# Extract values from config.json and .env  
SUBSCRIPTION_ID = os.getenv("SUBSCRIPTION_ID")  
RESOURCE_GROUP = os.getenv("RESOURCE_GROUP")  
ML_WORKSPACE_NAME = os.getenv("ML_WORKSPACE_NAME")  
deployment_name = config["openai"]["models"][0]["name"]  
connection_name = config["openai"]["name"]  
api_base = os.getenv("OPENAI_ENDPOINT")  
api_version = config["openai"]["api_version"]  
api_key = os.getenv("OPENAI_KEY")  
text_embedding_model = config["openai"]["models"][1]["name"]  
text_embedding_model_name = config["openai"]["models"][1]["model"]["name"]  
api_version_search = config["search"]["api_version"]  
connection_name_search = config["search"]["name"]  
api_base_search = os.getenv("SEARCH_ENDPOINT")  
api_key_search = os.getenv("SEARCH_KEY")  
asset_name = config["chunk_embed_index_deploy"]["asset_name"] 
OPENAI_RESOURCE_ID= os.getenv("OPENAI_RESOURCE_ID")
  
values = {  
    "SUBSCRIPTION_ID": SUBSCRIPTION_ID,  
    "RESOURCE_GROUP": RESOURCE_GROUP,  
    "ML_WORKSPACE_NAME": ML_WORKSPACE_NAME,  
    "deployment_name": deployment_name,  
    "connection_name": connection_name,  
    "api_base": api_base,  
    "api_version": api_version,  
    "api_key": api_key,  
    "text_embedding_model": text_embedding_model,  
    "text_embedding_model_name": text_embedding_model_name,  
    "api_version_search": api_version_search,  
    "connection_name_search": connection_name_search,  
    "api_base_search": api_base_search,  
    "api_key_search": api_key_search,  
    "asset_name": asset_name  
}  
  
# Check if any value is None  
for key, value in values.items():  
    if value is None:  
        raise ValueError(f"Missing value for {key}")  

  
  
# YAML template  
flow_template = """
id: template_chat_flow
name: Template Chat Flow
inputs:
  chat_history:
    type: list
    default: []
    is_chat_input: false
  query:
    type: string
    default: "What does Windows 10 Provides?"
    is_chat_input: false
outputs:
  reply:
    type: string
    reference: ${generateReply.output}
    is_chat_output: true
  documents:
    type: string
    reference: ${selectChunks.output}
nodes:
- name: formatRewriteIntentInputs
  type: python
  source:
    type: code
    path: formatConversationForIntentRewriting.py
  inputs:
    history: ${inputs.chat_history}
    max_tokens: 2000
    query: ${inputs.query}
  use_variants: false
- name: rewriteIntent
  type: llm
  source:
    type: code
    path: ragcore/prompt_templates/rewriteIntent.jinja2
  inputs:
    deployment_name: {{deployment_name}}
    temperature: 0.7
    top_p: 0.95
    max_tokens: 120
    presence_penalty: 0
    frequency_penalty: 0
    conversation: ${formatRewriteIntentInputs.output}
  provider: AzureOpenAI
  connection: {{connection_name}}
  api: chat
  module: promptflow.tools.aoai
  use_variants: false
- name: extractSearchIntent
  type: python
  source:
    type: code
    path: extractSearchIntent.py
  inputs:
    intent: ${rewriteIntent.output}
  use_variants: false
- name: querySearchResource
  type: python
  source:
    type: package
    tool: promptflow_vectordb.tool.common_index_lookup.search
  inputs:
    mlindex_content: >
      embeddings:
        api_base: {{api_base}}
        api_type: azure
        api_version: {{api_version}}
        batch_size: '1'
        connection:
          id: /subscriptions/{{SUBSCRIPTION_ID}}/resourceGroups/{{RESOURCE_GROUP}}/providers/Microsoft.MachineLearningServices/workspaces/{{ML_WORKSPACE_NAME}}/connections/{{connection_name}}
        connection_type: workspace_connection
        deployment: {{text_embedding_model_name}}
        dimension: 1536
        kind: open_ai
        model: {{text_embedding_model}}
        schema_version: '2'
      index:
        api_version: 2024-05-01-preview
        connection:
          id: /subscriptions/{{SUBSCRIPTION_ID}}/resourceGroups/{{RESOURCE_GROUP}}/providers/Microsoft.MachineLearningServices/workspaces/{{ML_WORKSPACE_NAME}}/connections/{{connection_name_search}}
        connection_type: workspace_connection
        endpoint: {{api_base_search}}
        engine: azure-sdk
        field_mapping:
          content: content
          embedding: contentVector
          metadata: meta_json_string
        index: {{asset_name}}
        kind: acs
        semantic_configuration_name: azureml-default
    queries: ${extractSearchIntent.output}
    query_type: Hybrid + semantic
    top_k: 5
  use_variants: false
- name: chunkDocuments
  type: python
  source:
    type: code
    path: chunkDocuments.py
  inputs:
    data_source: Azure AI Search
    max_tokens: 1050
    queries: ${extractSearchIntent.output}
    query_type: Hybrid (vector + keyword)
    results: ${querySearchResource.output}
    top_k: 5
  use_variants: false
- name: selectChunks
  type: python
  source:
    type: code
    path: filterChunks.py
  inputs:
    min_score: 0.3
    results: ${chunkDocuments.output}
    top_k: 5
  use_variants: false
- name: shouldGenerateReply
  type: python
  source:
    type: code
    path: shouldGenerateReply.py
  inputs:
    chunks: ${selectChunks.output}
    queries: ${extractSearchIntent.output}
  use_variants: false
- name: formatGenerateReplyInputs
  type: python
  source:
    type: code
    path: formatReplyInputs.py
  inputs:
    chunks: ${selectChunks.output}
    history: ${inputs.chat_history}
    max_conversation_tokens: 2000
    max_tokens: 5000
    query: ${inputs.query}
  use_variants: false
- name: generateReply
  use_variants: true
node_variants:
  generateReply:
    default_variant_id: variant_0
    variants:
      variant_0:
        node:
          name: generateReply
          type: llm
          source:
            type: code
            path: ragcore/prompt_templates/generateReply.jinja2
          inputs:
            inputs: ${formatGenerateReplyInputs.output}
            deployment_name: {{deployment_name}}
            temperature: 0.7
            top_p: 0.95
            max_tokens: 800
            presence_penalty: 0
            frequency_penalty: 0
            indomain: "True"
            role_info: You are an AI assistant that helps people find information.
          provider: AzureOpenAI
          connection: {{connection_name}}
          api: chat
          module: promptflow.tools.aoai
          activate:
            when: ${shouldGenerateReply.output}
            is: true
      variant_1:
        node:
          name: generateReply
          type: llm
          source:
            type: code
            path: generateReply__variant_1.jinja2
          inputs:
            inputs: ${formatGenerateReplyInputs.output}
            deployment_name: {{deployment_name}}
            temperature: 0.2
            top_p: 0.95
            max_tokens: 1000
            presence_penalty: 0
            frequency_penalty: 0
            indomain: "True"
            role_info: You are an AI assistant that helps people find information.
          provider: AzureOpenAI
          connection: {{connection_name}}
          api: chat
          module: promptflow.tools.aoai
          activate:
            when: ${shouldGenerateReply.output}
            is: true
environment:
  python_requirements_txt: requirements.txt
"""  
# YAML template  
similarity_template = """
inputs:
  question:
    type: string
    default: What feeds all the fixtures in low voltage tracks instead of each light having a line-to-low voltage transformer?
    is_chat_input: false
  ground_truth:
    type: string
    default: The main transformer is the object that feeds all the fixtures in low voltage tracks.
    is_chat_input: false
  answer:
    type: string
    default: Master transformer.
    is_chat_input: false
outputs:
  gpt_similarity:
    type: object
    reference: ${concat_scores.output.gpt_similarity}
    evaluation_only: false
    is_chat_output: false
nodes:
- name: similarity_score
  type: llm
  source:
    type: code
    path: similarity_score.jinja2
  inputs:
    question: "${inputs.question}"
    ground_truth: "${inputs.ground_truth}"
    answer: "${inputs.answer}"
    max_tokens: "256"
    deployment_name: {{deployment_name}}
    temperature: "0.0"
  api: chat
  provider: AzureOpenAI
  connection: {{connection_name}}
  module: promptflow.tools.aoai
  aggregation: false
- name: concat_scores
  type: python
  source:
    type: code
    path: concat_scores.py
  inputs:
    similarity_score: "${similarity_score.output}"
  aggregation: false
- name: aggregate_variants_results
  type: python
  source:
    type: code
    path: aggregate_variants_results.py
  inputs:
    results: "${concat_scores.output}"
  aggregation: true
environment:
  python_requirements_txt: requirements.txt

""" 
groundedness_template = """
inputs:
  question:
    type: string
    default: What feeds all the fixtures in low voltage tracks instead of each light having a line-to-low voltage transformer?
    is_chat_input: false
  context:
    type: string
    default: Track lighting, invented by Lightolier, was popular at one period of time because it was much easier to install than recessed lighting, and individual fixtures are decorative and can be easily aimed at a wall. It has regained some popularity recently in low-voltage tracks, which often look nothing like their predecessors because they do not have the safety issues that line-voltage systems have, and are therefore less bulky and more ornamental in themselves. A master transformer feeds all of the fixtures on the track or rod with 12 or 24 volts, instead of each light fixture having its own line-to-low voltage transformer. There are traditional spots and floods, as well as other small hanging fixtures. A modified version of this is cable lighting, where lights are hung from or clipped to bare metal cables under tension
    is_chat_input: false
  answer:
    type: string
    default: The main transformer is the object that feeds all the fixtures in low voltage tracks.
    is_chat_input: false
outputs:
  gpt_groundedness:
    type: object
    reference: ${concat_scores.output.gpt_groundedness}
    evaluation_only: false
    is_chat_output: false
nodes:
- name: groundedness_score
  type: llm
  source:
    type: code
    path: groundedness_score.jinja2
  inputs:
    question: "${inputs.question}"
    context: "${inputs.context}"
    answer: "${inputs.answer}"
    max_tokens: "256"
    deployment_name: {{deployment_name}}
    temperature: "0.0"
  api: chat
  provider: AzureOpenAI
  connection: {{connection_name}}
  module: promptflow.tools.aoai
  aggregation: false
- name: concat_scores
  type: python
  source:
    type: code
    path: concat_scores.py
  inputs:
    groundesness_score: "${groundedness_score.output}"
  aggregation: false
- name: aggregate_variants_results
  type: python
  source:
    type: code
    path: aggregate_variants_results.py
  inputs:
    results: "${concat_scores.output}"
  aggregation: true
environment:
  python_requirements_txt: requirements.txt

"""

# Function to replace {{...}} placeholders with values from the dictionary  
def replace_curly_braces(template, values):  
    # This regex matches patterns inside double curly braces {{...}}  
    pattern = re.compile(r'{{\s*([^}]+)\s*}}')  
  
    # Replace matched patterns using the values dictionary  
    def replacer(match):  
        key = match.group(1)  
        # Return the corresponding value from the dictionary if the key exists  
        if key in values:  
            return str(values[key])  
        else:  
            raise KeyError(f"Missing key {key} in values dictionary")  
  
    # Substitute the values in the template  
    return pattern.sub(replacer, template)  
  
# Now call the function to replace only the {{...}} placeholders  
formatted_flow_yaml = replace_curly_braces(flow_template, values) 
formatted_similarity_yaml = replace_curly_braces(similarity_template , values) 
formatted_ground_yaml = replace_curly_braces(groundedness_template , values) 
# Write the YAML content to a file  
with open("Flow/ChatFlow/flow.dag.yaml", "w") as f:  
    f.write(formatted_flow_yaml)  

with open("Flow/Evaluation/Groundedness/flow.dag.yaml", "w") as f:  
    f.write(formatted_ground_yaml) 

with open("Flow/Evaluation/Similarity/flow.dag.yaml", "w") as f:  
    f.write(formatted_similarity_yaml) 
