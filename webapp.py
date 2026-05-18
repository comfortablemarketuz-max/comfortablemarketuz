import logging
import json
from typing import Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List

from engine import AsyncSessionLocal
from services import (
    get_product_by_barcode, get_or_create_user, create_sale
)
from utils import format_price

logger = logging.getLogger(__name__)

app = FastAPI(title="QULAY MARKET WebApp", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class SaleItem(BaseModel):
    barcode: str
    quantity: int = 1


class SaleRequest(BaseModel):
    cashier_telegram_id: int
    items: List[SaleItem]


@app.get("/", response_class=HTMLResponse)
async def scanner_page():
    try:
        with open("scanner.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse("<h1>scanner.html topilmadi</h1>", status_code=404)


@app.get("/api/product/{barcode}")
async def get_product(barcode: str):
    async with AsyncSessionLocal() as session:
        product = await get_product_by_barcode(session, barcode)
    if not product:
        raise HTTPException(status_code=404, detail="Mahsulot topilmadi")
    return {
        "id": product.id,
        "name": product.name,
        "price": product.effective_price,
        "original_price": product.price,
        "has_discount": product.has_discount,
        "discount_price": product.discount_price,
        "quantity": product.quantity,
        "barcode": product.barcode,
        "in_stock": product.is_in_stock,
        "image_file_id": product.image_file_id,
    }


@app.post("/api/sale")
async def complete_sale(sale_req: SaleRequest):
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(
            session, sale_req.cashier_telegram_id, "Kassir"
        )
        items = []
        errors = []
        for si in sale_req.items:
            product = await get_product_by_barcode(session, si.barcode)
            if not product:
                errors.append(f"Barcode topilmadi: {si.barcode}")
                continue
            if product.quantity < si.quantity:
                errors.append(f"{product.name}: omborda {product.quantity} ta bor, {si.quantity} so'raldi")
                continue
            items.append({
                "product_id": product.id,
                "quantity": si.quantity,
                "price": product.effective_price,
                "name": product.name,
            })
        if not items:
            return JSONResponse(
                status_code=400,
                content={"error": "Mahsulotlar topilmadi", "details": errors}
            )
        sale = await create_sale(session, user.id, items)
        return {
            "success": True,
            "sale_id": sale.id,
            "total": sale.total_amount,
            "total_formatted": format_price(sale.total_amount),
            "items_count": len(items),
            "errors": errors,
        }


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "QULAY MARKET WebApp"}