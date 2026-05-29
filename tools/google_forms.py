import json
import os
from pathlib import Path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


def apply_global_form_format(form_service, form_id, questions_data):
    """
    edit global form settings such as title, description, quiz mode, and email collection based on the first item in the JSON (id: 0).
    """
    global_format_payload = {
        "requests": [
            {
                # set the form title, document title, and description
                "updateFormInfo": {
                    "info": {
                        "title": questions_data.get("survey_title", "Untitled Survey"),
                        "description": questions_data.get("survey_description", "Please complete this survey. Thank you for your participation!"),
                    },
                    "updateMask": "title,description" # <-- UPDATE THE MASK
                }
            },
            {
                # set the form settings, e.g., quiz mode, email collection, etc.
                "updateSettings": {
                    "settings": {
                        # set as quiz
                        "quizSettings": {
                            "isQuiz": False 
                        },
                        # email required for response
                        "emailCollectionType": "RESPONDER_INPUT" 
                    },
                    # set the fields we want to update
                    "updateMask": "quizSettings.isQuiz,emailCollectionType" 
                }
            }
        ]
    }
    # update
    form_service.forms().batchUpdate(
        formId=form_id, 
        body=global_format_payload
    ).execute()

def convert_to_forms_api_requests(data):
    """Parses the JSON list and converts it into Google Forms API createItem requests."""
    requests = []
    index_counter = 0
    current_section = None
    survey_info = {}

    for item in data:
        # Skip the title configuration (handled in the main function)
        if item.get("id") == 0:
            survey_info = item
            continue

        # Setup the basic item structure
        question_type = item.get("type")
        item_title = item.get("question")
        options = item.get("options", [])
        
        item_config = {"title": item_title}
        question_config = {"required": True}
        
        # Map your custom JSON types to Google Forms API types
        if question_type == "single_choice":
            question_config["choiceQuestion"] = {
                "type": "RADIO",
                "options": [{"value": opt} for opt in options]
            }
        elif question_type == "multiple_choice":
            question_config["choiceQuestion"] = {
                "type": "CHECKBOX",
                "options": [{"value": opt} for opt in options]
            }
        elif question_type == "text":
            question_config["textQuestion"] = {
                "paragraph": True
            }
            
        item_config["questionItem"] = {"question": question_config}
        
        # Add the constructed question to the batch requests
        requests.append({
            "createItem": {
                "item": item_config,
                "location": {"index": index_counter}
            }
        })
        index_counter += 1

    return {"requests": requests}, survey_info

def mcp_survey_executor(configs,questions_data: list) -> str:
    creds = None
    
    # AUTHENTICATION
    if os.path.exists(configs["Token_json"]):
        creds = Credentials.from_authorized_user_file(configs["Token_json"], configs['SCOPES'])
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                configs["GOOGLE_APPLICATION_CREDENTIALS"], configs['SCOPES']
            )
            creds = flow.run_local_server(port=0) 
        with open(configs["Token_json"], "w") as token:
            token.write(creds.to_json())
    
    # BUILD SERVICES (Add the Drive Service)
    form_service = build("forms", "v1", credentials=creds)
    drive_service = build("drive", "v3", credentials=creds)
    
    result = form_service.forms().create(body={
        "info": {
            "title": "Quickstart Form",
        }
    }).execute()
    form_id = result["formId"]
    
    api_payload, survey_info = convert_to_forms_api_requests(questions_data)
    
    #RENAME FILE IN GOOGLE DRIVE
    survey_title = survey_info.get("survey_title", "Untitled Survey")
    try:
        drive_service.files().update(
            fileId=form_id,
            body={"name": survey_title}
        ).execute()
    except Exception as e:
        print(f"Warning: Could not update Drive filename. Error: {e}")

    # CONTINUE WITH FORMS API UPDATES
    apply_global_form_format(form_service, form_id, survey_info)

    form_service.forms().batchUpdate(formId=form_id, body=api_payload).execute()
    
    final_form = form_service.forms().get(formId=form_id).execute()
    print(f"\nSurvey successfully published: https://docs.google.com/forms/d/{form_id}/edit")
    return f"https://docs.google.com/forms/d/{form_id}/edit"

def survey_executor_google(
    questions_data: str,
) -> str:
    """Executes the survey creation process using Google Forms API. Expects a JSON string as input, which will be parsed into a list of question configurations."""

    configs  = json.load(open('./configs.json'))
    try:
        parsed_questions = json.loads(questions_data)
    except json.JSONDecodeError as e:
        return json.dumps(
            {
                "status": "error",
                "message": f"questions_data is not valid JSON: {e}",
            },
            ensure_ascii=False,
        )

    if not isinstance(parsed_questions, list):
        return json.dumps(
            {
                "status": "error",
                "message": "questions_data must be a JSON list.",
            },
            ensure_ascii=False,
        )
    if configs["save_survey"]["save_to_local"]:
        output_path = Path(configs["save_survey"]["output_path"])
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(parsed_questions, f, ensure_ascii=False, indent=2)
    if configs["save_survey"]["save_to_google_forms"]:
        return mcp_survey_executor(configs['GOOGLE_KEYS'],parsed_questions)