from contextlib import asynccontextmanager
from logging import getLevelNamesMapping

from fastapi import FastAPI, Request, Form, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from datetime import date
import os
import json

from src.api.ozon_api import OzonApi
from src.config import LOG_LEVEL
from src.models.database import session_maker
from src.persistence.parameters_db import add_scheduled_time, delete_scheduled_time, get_company_ids, add_company_ids, \
    delete_company_id, \
    get_cookies, \
    get_report_path, get_scheduled_times, save_report_path, upsert_cookies
from src.persistence.task_db import count_tasks, get_tasks
from src.browser_request_sender import BrowserRequestSender
import uvicorn
import logging.handlers
import sys

from src.service.ozon_service import OzonService
from src.service.scheduler_service import ScedulerService

log_level = getLevelNamesMapping()[LOG_LEVEL]

os.makedirs('logs', exist_ok=True)
log_filename = f"logs/priceMonitor.log"

root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)

formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(filename)s - %(lineno)d - %(message)s')

# File handler
file_handler = logging.handlers.RotatingFileHandler(
    log_filename,
    backupCount=3,
    maxBytes=5_000_000
)
file_handler.setFormatter(formatter)

# Console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)

root_logger.handlers = []
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)

logger = logging.getLogger(__name__)
# Silence noisy libraries
logging.getLogger('sqlalchemy.engine').setLevel(logging.ERROR)  # Only show SQL errors
logging.getLogger('sqlalchemy.pool').setLevel(logging.ERROR)
logging.getLogger('httpx').setLevel(logging.ERROR)
logging.getLogger('httpcore').setLevel(logging.ERROR)
logging.getLogger('asyncio').setLevel(logging.WARNING)
logging.getLogger('aiosqlite').setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("VERSION 1.1.0")
    from src.models.database import setup_migrations
    await setup_migrations()
    
    scheduler_service = await get_scheduler_service()
    await scheduler_service.restart_scheduler()
    yield
app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="templates")

sender = None
api = None
scheduler_service = None

async def get_service():
    global sender, api, service
    if sender is None:
        sender = BrowserRequestSender("https://seller.ozon.ru/app/reviews")
        api = OzonApi(sender)
        service = OzonService(api)
    return service

async def get_scheduler_service():
    global scheduler_service
    if scheduler_service is None:
        scheduler_service = ScedulerService(await get_service())
    return scheduler_service

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
    scheduled_times = await get_scheduled_times()
    report_path = await get_report_path()
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "company_ids": company_ids,
        "cookies": cookies.value if cookies else "",
        "scheduled_times": scheduled_times,
        "report_path": report_path.value if report_path else ""
    })

@app.post("/company_ids", response_class=HTMLResponse)
async def add_company_id(request: Request, company_id: str = Form(...)):
    try:
        if company_id.strip():
            await add_company_ids([company_id])
        company_ids = await get_company_ids()
        return templates.TemplateResponse("partials/company_ids.html", {
            "request": request,
            "company_ids": company_ids
        })
    except Exception as e:
        company_ids = await get_company_ids()
        return templates.TemplateResponse("partials/company_ids.html", {
            "request": request,
            "company_ids": company_ids,
            "error": f"Error adding company ID: {str(e)}"
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
    try:
        json.loads(cookies)
        await upsert_cookies(cookies)
        current_cookies = await get_cookies()
        return templates.TemplateResponse("partials/cookies.html", {
            "request": request,
            "cookies": current_cookies.value if current_cookies else "",
            "saved": True
        })
    except Exception as e:
        current_cookies = await get_cookies()
        return templates.TemplateResponse("partials/cookies.html", {
            "request": request,
            "cookies": current_cookies.value if current_cookies else "",
            "saved": False,
            "error": f"Error saving cookies: {str(e)}"
        })

@app.post("/scheduled_times", response_class=HTMLResponse)
async def add_scheduled_time_endpoint(request: Request, scheduled_time: str = Form(...)):
    try:
        if scheduled_time.strip():
            await add_scheduled_time([scheduled_time])
        scheduled_times = await get_scheduled_times()
        scheduler_service = await get_scheduler_service()
        await scheduler_service.restart_scheduler()
        return templates.TemplateResponse("partials/scheduled_times.html", {
            "request": request,
            "scheduled_times": scheduled_times
        })
    except Exception as e:
        scheduled_times = await get_scheduled_times()
        return templates.TemplateResponse("partials/scheduled_times.html", {
            "request": request,
            "scheduled_times": scheduled_times,
            "error": f"Error adding scheduled time: {str(e)}"
        })

@app.delete("/scheduled_times/{scheduled_time}", response_class=HTMLResponse)
async def remove_scheduled_time(request: Request, scheduled_time: str):
    await delete_scheduled_time(scheduled_time)
    scheduled_times = await get_scheduled_times()
    scheduler_service = await get_scheduler_service()
    await scheduler_service.restart_scheduler()
    return templates.TemplateResponse("partials/scheduled_times.html", {
        "request": request,
        "scheduled_times": scheduled_times
    })

@app.get("/report_path", response_class=HTMLResponse)
async def show_report_path(request: Request):
    report_path = await get_report_path()
    return templates.TemplateResponse("partials/report_path.html", {
        "request": request,
        "report_path": report_path.value if report_path else "",
        "saved": False,
        "error": None
    })

@app.post("/report_path", response_class=HTMLResponse)
async def update_report_path(request: Request, report_path: str = Form(...)):
    if not os.path.isdir(report_path):
        return templates.TemplateResponse("partials/report_path.html", {
            "request": request,
            "report_path": report_path,
            "saved": False,
            "error": "Path does not exist or is not a directory"
        })
    
    try:
        await save_report_path(report_path)
        return templates.TemplateResponse("partials/report_path.html", {
            "request": request,
            "report_path": report_path,
            "saved": True
        })
    except Exception as e:
        return templates.TemplateResponse("partials/report_path.html", {
            "request": request,
            "report_path": report_path,
            "saved": False,
            "error": f"Error saving path: {str(e)}"
        })

@app.get("/scheduled_times", response_class=HTMLResponse)
async def show_scheduled_times(request: Request):
    scheduled_times = await get_scheduled_times()
    return templates.TemplateResponse("partials/scheduled_times.html", {
        "request": request,
        "scheduled_times": scheduled_times
    })

@app.get("/tasks", response_class=HTMLResponse)
async def get_tasks_page(request: Request):
    return templates.TemplateResponse("task_table.html", {"request": request})

@app.get("/tasks/list", response_class=HTMLResponse)
async def get_tasks_endpoint(
    request: Request,
    page: int = Query(1, ge=1),
):
    async with session_maker() as session:
        # Get total count
        total_count = await count_tasks(session)
        total_pages = (total_count + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE

        # Get paginated tasks
        tasks = await get_tasks(session, limit=ITEMS_PER_PAGE, offset=(page - 1) * ITEMS_PER_PAGE)

    return templates.TemplateResponse(
        "partials/task.html",
        {
            "request": request,
            "tasks": tasks,
            "current_page": page,
            "total_pages": total_pages,
        }
    )
