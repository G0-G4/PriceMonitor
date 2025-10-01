from fastapi import FastAPI, Request, Form, Query, Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime, date
from service.ozon_service import OzonService
from api.ozon_api import OzonApi
from browser_request_sender import BrowserRequestSender
import uvicorn
import asyncio

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Initialize service
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

ITEMS_PER_PAGE = 10

@app.get("/prices", response_class=HTMLResponse)
async def get_prices(
    request: Request,
    page: int = Query(1, ge=1),
    company_id: str = Query(None),
    target_date: str = Query(None)
):
    service = await get_service()
    
    # Parse date or use today if not provided
    try:
        target_date_obj = date.fromisoformat(target_date) if target_date else date.today()
    except ValueError:
        target_date_obj = date.today()

    # Get price changes from database
    price_changes = await service.get_price_change(
        target_date=target_date_obj,
        limit=ITEMS_PER_PAGE,
        offset=(page - 1) * ITEMS_PER_PAGE,
        company_id=company_id
    )

    # Get total count for pagination
    total_count = len(await service.get_price_change(
        target_date=target_date_obj,
        company_id=company_id
    ))
    total_pages = (total_count + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE

    return templates.TemplateResponse(
        "partials/price.html",
        {
            "request": request,
            "prices": price_response.price_changes,
            "current_page": page,
            "total_pages": total_pages,
            "company_id": company_id,
            "target_date": target_date.isoformat()
        }
    )

if __name__ == '__main__':
    uvicorn.run(app, host="127.0.0.1", port=8000)
