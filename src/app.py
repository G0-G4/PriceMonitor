from contextlib import asynccontextmanager
from logging import getLevelNamesMapping

from fastapi import FastAPI, Request, Form, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from datetime import date, timedelta
import os
import asyncio

from src.api.ozon_api import OzonApi
from src.config import LOG_LEVEL
from src.service.wb_wallet_discount import refresh_wallet_discounts, run_wallet_discount_loop
from src.models.database import session_maker
from src.persistence.ozon_price_db import get_previous_day
from src.persistence.wb_price_db import get_previous_wb_day
from src.persistence.parameters_db import add_scheduled_time, delete_scheduled_time, get_company_ids, add_company_ids, \
    delete_company_id, \
    get_report_path, get_scheduled_times, save_report_path, get_wb_accounts, add_wb_account, delete_wb_account, \
    mask_token
from src.persistence.task_db import count_tasks, get_tasks
from src.browser_request_sender import BrowserRequestSender, profile_exists, ReLoginRequiredError
import uvicorn
import logging.handlers
import sys

from src.service.ozon_service import OzonService
from src.service.scheduler_service import ScedulerService
from src.service.wb_service import WbService

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
    logger.info("VERSION 1.3.0")
    from src.models.database import setup_migrations
    await setup_migrations()
    try:
        await refresh_wallet_discounts()
    except Exception:
        logger.exception("initial WB wallet discount fetch failed")

    scheduler_service = await get_scheduler_service()
    await scheduler_service.restart_scheduler()
    wallet_discount_task = asyncio.create_task(run_wallet_discount_loop())
    try:
        yield
    finally:
        wallet_discount_task.cancel()
app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

sender = None
api = None
wb_service = None
scheduler_service = None
login_lock = asyncio.Lock()
login_in_progress = {"value": False}


async def get_service():
    global sender, api, service
    if sender is None:
        sender = BrowserRequestSender("https://seller.ozon.ru/app/reviews")
        api = OzonApi(sender)
        service = OzonService(api)
    return service


async def get_wb_service():
    global wb_service
    if wb_service is None:
        wb_service = WbService()
    return wb_service


async def get_scheduler_service():
    global scheduler_service
    if scheduler_service is None:
        scheduler_service = ScedulerService(await get_service(), await get_wb_service())
    return scheduler_service


async def refresh_scheduler_services():
    if scheduler_service is None:
        return
    scheduler_service.ozon_service = await get_service()
    scheduler_service.wb_service = await get_wb_service()


async def _wb_accounts_view() -> list[dict]:
    return [
        {
            "name": acc.name,
            "token_masked": mask_token(acc.token),
        }
        for acc in await get_wb_accounts()
    ]


async def _wb_auth_context(request: Request, extra: dict | None = None) -> dict:
    context = {
        "request": request,
        "wb_accounts": await _wb_accounts_view(),
        "wb_account_error": None,
    }
    if extra:
        context.update(extra)
    return context

@app.get("/", response_class=HTMLResponse)
async def get_items(request: Request):
    today = date.today().isoformat()
    return templates.TemplateResponse("price_table.html", {
        "request": request,
        "today": today,
        "marketplace": "ozon",
        "active": "prices",
    })

ITEMS_PER_PAGE = 50

@app.get("/prices", response_class=HTMLResponse)
async def get_prices(
    request: Request,
    page: int = Query(1, ge=1),
    company_id: str = Query(None),
    offer_id: str = Query(None),
    target_date: str = Query(None),
    marketplace: str = Query("ozon"),
):
    company_id = company_id.strip() if company_id else None
    offer_id = offer_id.strip() if offer_id else None
    marketplace = (marketplace or "ozon").strip().lower()
    if marketplace not in ("ozon", "wb"):
        marketplace = "ozon"
    try:
        target_date_obj = date.fromisoformat(target_date) if target_date else date.today()
    except ValueError:
        target_date_obj = date.today()

    if marketplace == "wb":
        service = await get_wb_service()
        previous_date = (await get_previous_wb_day(target_date_obj, company_id)) or (target_date_obj - timedelta(days=1))
        price_change_response = await service.get_price_change(
            target_date=target_date_obj,
            previous_date=previous_date,
            limit=ITEMS_PER_PAGE,
            offset=(page - 1) * ITEMS_PER_PAGE,
            vendor_code=offer_id,
            account=company_id,
        )
        template_name = "partials/wb_price.html"
    else:
        service = await get_service()
        previous_date = (await get_previous_day(target_date_obj)) or (target_date_obj - timedelta(days=1))
        price_change_response = await service.get_price_change(
            target_date=target_date_obj,
            previous_date=previous_date,
            limit=ITEMS_PER_PAGE,
            offset=(page - 1) * ITEMS_PER_PAGE,
            company_id=company_id,
            offer_id=offer_id
        )
        template_name = "partials/price.html"

    total_count = price_change_response.total
    total_pages = (total_count + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE

    return templates.TemplateResponse(
        template_name,
        {
            "request": request,
            "prices": price_change_response.price_changes,
            "current_page": page,
            "total_pages": total_pages,
            "company_id": company_id,
            "offer_id": offer_id,
            "marketplace": marketplace,
            "target_date": target_date_obj.isoformat(),
            "previous_date": previous_date.strftime("%Y-%m-%d"),
            "format_percentage": lambda value: f"{value:.4f}"
        }
    )

@app.get("/settings", response_class=HTMLResponse)
async def settings(request: Request):
    company_ids = await get_company_ids()
    scheduled_times = await get_scheduled_times()
    report_path = await get_report_path()
    wb_context = await _wb_auth_context(request)
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "company_ids": company_ids,
        "scheduled_times": scheduled_times,
        "report_path": report_path.value if report_path else "",
        "authenticated": profile_exists(),
        "login_in_progress": login_in_progress["value"],
        "active": "settings",
        **wb_context,
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

@app.get("/login/status", response_class=HTMLResponse)
async def login_status(request: Request):
    just_done = None
    if login_in_progress.get("result") is not None and not login_in_progress.get("value"):
        just_done = login_in_progress["result"]
        login_in_progress["result"] = None
    return templates.TemplateResponse("partials/auth.html", {
        "request": request,
        "authenticated": profile_exists(),
        "login_in_progress": login_in_progress["value"],
        "just_logged_in": just_done is True,
        "error": None if just_done is None else (None if just_done else "Login failed or window closed before reaching seller.ozon.ru/app/"),
    })


@app.post("/login", response_class=HTMLResponse)
async def login(request: Request):
    if login_in_progress.get("value"):
        return templates.TemplateResponse("partials/auth.html", {
            "request": request,
            "authenticated": profile_exists(),
            "login_in_progress": True,
        })

    async with login_lock:
        login_in_progress["value"] = True
        login_in_progress["result"] = None
        global sender
        if sender is not None:
            try:
                await sender.close()
            except Exception:
                logger.exception("failed to close existing browser sender before login")
            sender = None

        async def _run_login():
            login_sender = BrowserRequestSender("https://seller.ozon.ru/app/reviews")
            try:
                success = await asyncio.wait_for(login_sender.login(), timeout=650)
                login_in_progress["result"] = bool(success)
            except asyncio.TimeoutError:
                login_in_progress["result"] = False
            except Exception:
                logger.exception("login failed")
                login_in_progress["result"] = False
            finally:
                login_in_progress["value"] = False
                try:
                    await refresh_scheduler_services()
                except Exception:
                    logger.exception("failed to refresh scheduler services after Ozon login")

        asyncio.create_task(_run_login())

    return templates.TemplateResponse("partials/auth.html", {
        "request": request,
        "authenticated": profile_exists(),
        "login_in_progress": True,
    })


@app.post("/wb_accounts", response_class=HTMLResponse)
async def add_wb_account_endpoint(request: Request, account: str = Form(...), wb_api_token: str = Form(...)):
    try:
        await add_wb_account(account, wb_api_token)
        return templates.TemplateResponse("partials/wb_accounts.html", await _wb_auth_context(request))
    except Exception as e:
        return templates.TemplateResponse("partials/wb_accounts.html", await _wb_auth_context(request, {
            "wb_account_error": str(e),
        }))


@app.delete("/wb_accounts/{account}", response_class=HTMLResponse)
async def remove_wb_account(request: Request, account: str):
    try:
        await delete_wb_account(account)
        return templates.TemplateResponse("partials/wb_accounts.html", await _wb_auth_context(request))
    except Exception as e:
        return templates.TemplateResponse("partials/wb_accounts.html", await _wb_auth_context(request, {
            "wb_account_error": str(e),
        }))


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
    return templates.TemplateResponse("task_table.html", {"request": request, "active": "tasks"})

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
