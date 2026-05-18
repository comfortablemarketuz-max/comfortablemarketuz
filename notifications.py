import logging
from typing import List, Optional
from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models import User, UserRole, Order, Product
from config import LOW_STOCK_THRESHOLD
from utils import format_price, format_order_status, format_datetime

logger = logging.getLogger(__name__)


async def get_admin_telegram_ids(session: AsyncSession) -> List[int]:
    result = await session.execute(
        select(User.telegram_id).where(
            User.role.in_([UserRole.owner, UserRole.admin]),
            User.is_active == True,
        )
    )
    return [row[0] for row in result.all()]


async def notify_admins(bot: Bot, session: AsyncSession, message: str) -> None:
    admin_ids = await get_admin_telegram_ids(session)
    for tid in admin_ids:
        try:
            await bot.send_message(tid, message, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Admin {tid} ga xabar yuborib bo'lmadi: {e}")


async def notify_user(bot: Bot, telegram_id: int, message: str) -> None:
    try:
        await bot.send_message(telegram_id, message, parse_mode="HTML")
    except Exception as e:
        logger.warning(f"User {telegram_id} ga xabar yuborib bo'lmadi: {e}")


async def notify_new_order(bot: Bot, session: AsyncSession, order: Order) -> None:
    items_text = "\n".join(
        f"  • {i.product_name_snapshot} x{i.quantity} — {format_price(i.subtotal)}"
        for i in order.items
    )
    user = order.user
    username = f"@{user.username}" if user and user.username else (user.full_name if user else "Noma'lum")

    text = (
        f"🛒 <b>Yangi buyurtma #{order.id}</b>\n\n"
        f"👤 Mijoz: {username}\n"
        f"💰 Jami: <b>{format_price(order.total_amount)}</b>\n"
        f"⏰ Olib ketish: {format_datetime(order.pickup_time) if order.pickup_time else 'Belgilanmagan'}\n"
        f"🔑 Kod: <code>{order.pickup_code}</code>\n\n"
        f"📦 Mahsulotlar:\n{items_text}"
    )
    await notify_admins(bot, session, text)


async def notify_order_needs_verification(bot: Bot, session: AsyncSession, order: Order) -> None:
    user = order.user
    username = f"@{user.username}" if user and user.username else (user.full_name if user else "Noma'lum")
    text = (
        f"⚠️ <b>Tekshiruv kerak — #{order.id}</b>\n\n"
        f"👤 Mijoz: {username}\n"
        f"💰 Jami: <b>{format_price(order.total_amount)}</b>\n"
        f"📊 50 000 so'mdan oshgan buyurtma. Tekshirish zarur!"
    )
    await notify_admins(bot, session, text)


async def notify_order_status_change(
    bot: Bot,
    telegram_id: int,
    order: Order,
) -> None:
    status_text = format_order_status(order.status)
    text = f"📦 <b>Buyurtma #{order.id} holati o'zgardi</b>\n\n{status_text}"
    if order.status.value == "ready":
        text += f"\n\n✅ Buyurtmangiz tayyor! Kodni ko'rsating: <code>{order.pickup_code}</code>"
    elif order.status.value == "rejected":
        text += f"\n\n❌ Sabab: {order.rejection_reason or 'Ko\'rsatilmagan'}"
    await notify_user(bot, telegram_id, text)


async def notify_low_stock(bot: Bot, session: AsyncSession, product: Product) -> None:
    text = (
        f"⚠️ <b>Kam qolgan mahsulot</b>\n\n"
        f"📦 {product.name}\n"
        f"🔢 Qolgan: <b>{product.quantity} ta</b>\n"
        f"Ombor to'ldiring!"
    )
    await notify_admins(bot, session, text)


async def notify_out_of_stock(bot: Bot, session: AsyncSession, product: Product) -> None:
    text = (
        f"❌ <b>Mahsulot tugadi!</b>\n\n"
        f"📦 {product.name}\n"
        f"Tezda ombor to'ldiring!"
    )
    await notify_admins(bot, session, text)


async def send_daily_report(bot: Bot, session: AsyncSession, stats: dict) -> None:
    text = (
        f"📊 <b>Kun yakuni hisobot — {stats['date']}</b>\n\n"
        f"🏪 Kassa savdolari: {stats['sales_count']} ta — <b>{format_price(stats['sales_total'])}</b>\n"
        f"📦 Buyurtmalar: {stats['orders_count']} ta — <b>{format_price(stats['orders_total'])}</b>\n"
        f"⏳ Kutayotgan: {stats['pending_orders']} ta\n"
    )
    await notify_admins(bot, session, text)