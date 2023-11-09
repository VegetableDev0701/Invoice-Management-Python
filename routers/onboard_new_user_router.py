import asyncio
from typing import Any, Dict
from fastapi import APIRouter, Depends

from config import PROJECT_NAME
from utils import auth
from utils.data_models.onboard_new_user import UpdateUserInfo
from utils.database.firestore import push_to_firestore
from utils.onboard_utils import check_user_email, onboard_new_user


router = APIRouter()


@router.put("/onboard_new_user")
async def check_users_email_domain(
    user_email: str, current_user=Depends(auth.get_current_user)
) -> Dict[str, Any]:
    domain = user_email.split("@")[-1]

    user_data = await onboard_new_user(domain=domain, user_email=user_email)

    return user_data


@router.get("/check_user_email")
async def check_user_email_route(
    user_email: str, current_user=Depends(auth.get_current_user)
):
    is_part_of_org = await check_user_email(user_email=user_email)
    return {"message": is_part_of_org}


@router.patch("/update_new_user_info")
async def update_company_name(
    data: UpdateUserInfo, current_user=Depends(auth.get_current_user)
) -> dict:
    company_id = data.company_id
    company_name = data.company_name
    user_id = data.user_id
    user_name = data.user_name

    tasks = []

    tasks.append(
        asyncio.create_task(
            push_to_firestore(
                project_name=PROJECT_NAME,
                collection="organizations",
                document=company_id,
                data={
                    "company_name": company_name,
                    "business_address": data.business_address,
                    "business_city": data.business_city,
                    "business_state": data.business_state,
                    "business_zip": data.business_zip,
                },
            )
        )
    )
    tasks.append(
        asyncio.create_task(
            push_to_firestore(
                project_name=PROJECT_NAME,
                collection="organizations",
                document=company_id,
                doc_collection="users",
                doc_collection_document=user_id,
                data={
                    "company_id": company_id,
                    "company_name": company_name,
                    "user_name": user_name,
                    "business_address": data.business_address,
                    "business_city": data.business_city,
                    "business_state": data.business_state,
                    "business_zip": data.business_zip,

                },
            )
        )
    )
    tasks.append(
        asyncio.create_task(
            push_to_firestore(
                project_name=PROJECT_NAME,
                collection="users",
                document=user_id,
                data={
                    "company_id": company_id,
                    "company_name": company_name,
                    "user_name": user_name,
                    "business_address": data.business_address,
                    "business_city": data.business_city,
                    "business_state": data.business_state,
                    "business_zip": data.business_zip,
                },
            )
        )
    )
    _ = await asyncio.gather(*tasks)

    return {"message": "Succesfully finished onbaording new user."}
