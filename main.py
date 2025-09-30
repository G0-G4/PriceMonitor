from fastapi import FastAPI, Request, Form, Query, Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime
import uuid
import secrets
import uvicorn
app = FastAPI()
templates = Jinja2Templates(directory="templates")
security = HTTPBasic()

# Basic Auth credentials (in production, use proper user management)
USERNAME = "admin"
PASSWORD = "secret"

async def get_current_username(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, USERNAME)
    correct_password = secrets.compare_digest(credentials.password, PASSWORD)
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# Dummy datastore
class Price:
    def __init__(self):
        self.date = datetime.now()
        self.article = uuid.uuid4()
        self.marketing_seller_price = 0
        self.old_price = 10
        self.marketing_price = 0
        self.marketing_oa_price = 0
        self.marketing_price_change_ = 10
        self.marketing_oa_price_change = -10
prices = [
    Price(), Price(),
    Price(), Price(),
    Price(), Price(),
    Price(), Price(),
    Price(), Price(),
    Price(), Price(),
    Price(), Price(),
    Price(), Price(),
    Price(), Price(),
    Price(), Price(),
    Price(), Price(),
    Price(), Price(),
    Price(), Price(),

          ]

@app.get("/", response_class=HTMLResponse)
async def get_items(request: Request, username: str = Depends(get_current_username)):
    return templates.TemplateResponse("price_table.html", {"request": request})

ITEMS_PER_PAGE = 10

@app.get("/prices", response_class=HTMLResponse)
async def get_prices(
    request: Request,
    page: int = Query(1, ge=1),
    article_filter: str = Query(None),
    start_date: str = Query(None),
    end_date: str = Query(None),
    username: str = Depends(get_current_username)
):
    filtered_prices = prices

    # Apply filters
    if article_filter:
        filtered_prices = [p for p in filtered_prices if article_filter.strip().lower() in str(p.article).lower()]

    if start_date:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        filtered_prices = [p for p in filtered_prices if p.date >= start]

    if end_date:
        end = datetime.strptime(end_date, "%Y-%m-%d")
        filtered_prices = [p for p in filtered_prices if p.date <= end]

    # Pagination
    start_idx = (page - 1) * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    paginated_prices = filtered_prices[start_idx:end_idx]
    total_pages = (len(filtered_prices) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE

    return templates.TemplateResponse(
        "partials/price.html",
        {
            "request": request,
            "prices": paginated_prices,
            "current_page": page,
            "total_pages": total_pages
        }
    )

if __name__ == '__main__':
    uvicorn.run(app, host="127.0.0.1", port=8000)