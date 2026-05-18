import logging
from datetime import datetime, timedelta

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, WebAppData
from aiogram.fsm.context import FSMContext

from engine import AsyncSessionLocal
from models import UserRole
from states import CashierStates
from keyboards import cashier_scanner_keyboard, admin_main_keyboard
from services import (
    get_or_create_user, get_product_by_barcode,
    create_sale, get_cashier_stats,
)
from permissions import is_staff
from utils import format_price, format_datetime
import json

logger = logging.getLogger(__name__)
cashier_router = Router()


@cashier_router.message(F.web_app_data)
async def handle_webapp_data(message: Message, bot: Bot):
    try:
        data = json.loads(message.web_app_data.data)
        action = data.get("action")

        async with AsyncSessionLocal() as session:
            user = await get_or_create_user(
                session, message.from_user.id, message.from_user.full_name
            )
            if user.role not in (UserRole.owner, UserRole.admin, UserRole.cashier):
                await message.answer("⛔ Ruxsat yo'q.")
                return

            if action == "sale_complete":
                items_raw = data.get("items", [])
                if not items_raw:
                    await message.answer("❌ Savat bo'sh!")
                    return

                sale_items = []
                errors = []
                for raw in items_raw:
                    product = await get_product_by_barcode(session, raw.get("barcode", ""))
                    if not product:
                        errors.append(f"Barcode topilmadi: {raw.get('barcode')}")
                        continue
                    sale_items.append({
                        "product_id": product.id,
                        "quantity": int(raw.get("quantity", 1)),
                        "price": product.effective_price,
                        "name": product.name,
                    })

                if not sale_items:
                    await message.answer(f"❌ Mahsulotlar topilmadi.\n" + "\n".join(errors))
                    return

                sale = await create_sale(session, user.id, sale_items)
                total_text = format_price(sale.total_amount)
                items_text = "\n".join(
                    f"• {i['name']} x{i['quantity']} — {format_price(i['price'] * i['quantity'])}"
                    for i in sale_items
                )
                await message.answer(
                    f"✅ <b>Savdo yakunlandi!</b>\n\n"
                    f"{items_text}\n\n"
                    f"💰 Jami: <b>{total_text}</b>\n"
                    f"🆔 Savdo ID: #{sale.id}",
                    parse_mode="HTML",
                    reply_markup=cashier_scanner_keyboard(),
                )
                if errors:
                    await message.answer("⚠️ Ba'zi mahsulotlar topilmadi:\n" + "\n".join(errors))

            elif action == "barcode_check":
                barcode = data.get("barcode", "")
                product = await get_product_by_barcode(session, barcode)
                if product:
                    await message.answer(
                        f"✅ <b>{product.name}</b>\n"
                        f"💰 Narx: {format_price(product.effective_price)}\n"
                        f"📦 Qoldi: {product.quantity} ta",
                        parse_mode="HTML",
                    )
                else:
                    await message.answer(f"❌ Barcode topilmadi: <code>{barcode}</code>", parse_mode="HTML")

    except json.JSONDecodeError:
        logger.error("WebApp JSON parse xatosi")
        await message.answer("❌ Ma'lumot xatosi.")
    except Exception as e:
        logger.error(f"WebApp data handler xatosi: {e}")
        await message.answer("❌ Xato yuz berdi.")


@cashier_router.message(F.text == "📊 Bugungi savdo")
async def cashier_today_stats(message: Message):
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.full_name)
        if not is_staff(user.role):
            return
        stats = await get_cashier_stats(session)

    if not stats:
        await message.answer("📊 Bugun hali savdo yo'q.", reply_markup=cashier_scanner_keyboard())
        return

    text = "📊 <b>Bugungi kassir savdolari:</b>\n\n"
    for s in stats:
        text += f"👤 {s['name']}: {s['sales']} ta — {format_price(s['total'])}\n"
    await message.answer(text, parse_mode="HTML", reply_markup=cashier_scanner_keyboard())