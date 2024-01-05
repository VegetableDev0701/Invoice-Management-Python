#!/usr/bin/env python

import json
import os

from fastapi import FastAPI, Depends, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from utils.database.firestore import get_all_company_data
from utils import auth
from global_vars.globals_io import (
    DOC_TYPE_INVOICE,
)
from routers import (
    vendors,
    forms,
    cost_codes,
    invoices,
    websocket,
    agave,
    onboard_new_user_router,
    employees_customers

)
from routers.projects import (
    projects,
    labor,
    change_order,
    contracts,
    budget,
    client_bill,
)
from config import PROJECT_NAME

DOC_TYPE = DOC_TYPE_INVOICE
TESTING = False

app = FastAPI()

dir_path = os.path.join('static')

# Check if the directory exists
if not os.path.exists(dir_path):
    # Create the directory
    os.makedirs(dir_path)

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    try:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY
            or status.HTTP_401_UNAUTHORIZED,
            content={"detail": exc.errors(), "body": exc.body},
        )
    except Exception as e:
        print(e)
        return exc.body


app.include_router(projects.router)
app.include_router(labor.router)
app.include_router(change_order.router)
app.include_router(vendors.router)
app.include_router(forms.router)
app.include_router(cost_codes.router)
app.include_router(invoices.router)
app.include_router(contracts.router)
app.include_router(websocket.router)
app.include_router(budget.router)
app.include_router(client_bill.router)
app.include_router(agave.router)
app.include_router(onboard_new_user_router.router)
app.include_router(employees_customers.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://api.stak.cc",
        "https://staging-api.stak.cc",
        "https://app.stak.cc",
        "https://staging-app.stak.cc",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/{company_id}/company-data")
async def get_form_data(
    company_id: str,
    current_user=Depends(auth.get_current_user),
):
    auth.check_user_data(company_id=company_id, current_user=current_user)

    doc = await get_all_company_data(
        project_name=PROJECT_NAME, collection_name=company_id
    )

    return json.dumps(doc)


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        log_level="info",
        reload=True,
        access_log=False,
    )
