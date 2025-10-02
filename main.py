from fastapi import FastAPI, Request, Form, Query, Depends, HTTPException, status, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime, date

from persistence.parameters_db import get_company_ids, add_company_ids, delete_company_id
from service.ozon_service import OzonService
from api.ozon_api import OzonApi
from browser_request_sender import BrowserRequestSender
import uvicorn

app = FastAPI()
templates = Jinja2Templates(directory="templates")

sender = None
api = None
service = None

async def get_service():
    global sender, api, service
    if sender is None:
        sender = await BrowserRequestSender("https://seller.ozon.ru/app/reviews").init()
        api = OzonApi(sender)
        service = OzonService(api)
    return service

@app.get("/", response_class=HTMLResponse)
async def get_items(request: Request):
    today = date.today().isoformat()
    return templates.TemplateResponse("price_table.html", {
        "request": request,
        "today": today
    })

ITEMS_PER_PAGE = 50

@app.get("/prices", response_class=HTMLResponse)
async def get_prices(
    request: Request,
    page: int = Query(1, ge=1),
    company_id: str = Query(None),
    offer_id: str = Query(None),
    target_date: str = Query(None)
):
    service = await get_service()
    
    try:
        target_date_obj = date.fromisoformat(target_date) if target_date else date.today()
    except ValueError:
        target_date_obj = date.today()

    price_change_response = await service.get_price_change(
        target_date=target_date_obj,
        limit=ITEMS_PER_PAGE,
        offset=(page - 1) * ITEMS_PER_PAGE,
        company_id=company_id,
        offer_id=offer_id
    )

    total_count = price_change_response.total
    total_pages = (total_count + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE

    return templates.TemplateResponse(
        "partials/price.html",
        {
            "request": request,
            "prices": price_change_response.price_changes,
            "current_page": page,
            "total_pages": total_pages,
            "company_id": company_id,
            "offer_id": offer_id,
            "target_date": target_date_obj.isoformat(),
            "format_percentage": lambda value: f"{value:.1f}"
        }
    )

@app.get("/settings", response_class=HTMLResponse)
async def settings(request: Request):
    company_ids = await get_company_ids()
    cookies = await get_cookies()
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "company_ids": company_ids,
        "cookies": cookies.value if cookies else ""
    })

@app.post("/company_ids", response_class=HTMLResponse)
async def add_company_id(request: Request, company_id: str = Form(...)):
    if company_id.strip():
        await add_company_ids([company_id])
    company_ids = await get_company_ids()
    return templates.TemplateResponse("partials/company_ids.html", {
        "request": request,
        "company_ids": company_ids
    })

@app.delete("/company_ids/{company_id}", response_class=HTMLResponse)
async def remove_company_id(request: Request, company_id: str):
    await delete_company_id(company_id)
    company_ids = await get_company_ids()
    return templates.TemplateResponse("partials/company_ids.html", {
        "request": request,
        "company_ids": company_ids
    })

@app.get("/company_ids", response_class=HTMLResponse)
async def show_company_ids(request: Request):
    company_ids = await get_company_ids()
    return templates.TemplateResponse("partials/company_ids.html", {
        "request": request,
        "company_ids": company_ids
    })

@app.post("/cookies", response_class=HTMLResponse)
async def update_cookies(request: Request, cookies: str = Form(...)):
    await upsert_cookies(cookies)
    current_cookies = await get_cookies()
    return templates.TemplateResponse("partials/cookies.html", {
        "request": request,
        "cookies": current_cookies.value if current_cookies else ""
    })

if __name__ == '__main__':
    uvicorn.run(app, host="127.0.0.1", port=8000)
