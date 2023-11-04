import json

from fastapi import APIRouter, Depends

from config import PROJECT_NAME
from utils.database.firestore import stream_entire_collection
from utils import auth


router = APIRouter()


@router.get("/{company_id}/all-forms")
async def get_forms(
    company_id: str,
    #current_user=Depends(auth.get_current_user)
) -> str:
    #auth.check_user_data(company_id=company_id, current_user=current_user)

    form_docs = await stream_entire_collection(
        project_name=PROJECT_NAME,
        collection_name=company_id,
        document_name="base-forms",
        doc_collection_name="forms",
    )

    return json.dumps(form_docs)
