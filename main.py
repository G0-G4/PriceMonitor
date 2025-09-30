from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime
app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Dummy datastore
class Price:
    def __init__(self):
        self.date = datetime.now()
        self.article = "kasfjkaswjf"
        self.marketing_seller_price = 0
        self.old_price = 0
        self.marketing_price = 0
        self.marketing_oa_price = 0
prices = [Price(), Price()]

@app.get("/", response_class=HTMLResponse)
def get_items(request: Request):
    return templates.TemplateResponse("price_table.html", {"request": request, "prices": prices})

@app.post("/add-item")
def add_item(request: Request, item: str = Form(...)):
    return templates.TemplateResponse("partials/price.html", {"request": request, "item": item})