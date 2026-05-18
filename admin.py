import logging
from datetime import datetime
from typing import Optional

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

from engine import AsyncSessionLocal
from models import UserRole, OrderStatus, Product
from states import AdminStates
from permissions import is_admin_or_higher, has_permission
from keyboards import (
    admin_main_keyboard, admin_products_keyboard, admin_orders_filter_keyboard,
    admin_order_keyboard, product_edit_keyboard, products_list_keyboard,
    confirm_keyboard, cancel_keyboard,
)
from services import (
    get_or_create_user, get_all_categories, create_category,
    create_product, update_product, delete_product, get_product_by_id,
    get_all_products_admin, get_orders_by_status, get_order_by_id,
    update_order_status, adjust_product_quantity,
    get_today_stats, get_top_products, get_hourly_sales,
    get_weekly_stats, get_cashier_stats,
    get_low_stock_products, get_out_of_stock_products,
    get_setting, set_setting, set_user_trusted, update_user_role,
)
from notifications import (
    notify_admins, notify_order_status_change, notify_low_stock,
    notify_out_of_stock,
)
from utils import (
    format_price, format_datetime, format_order_status,
    sanitize_text, extract_hashtags, is_valid_barcode
)
from config import LOW_STOCK_THRESHOLD

logger = logging.getLogger(__name__)
admin_router = Router()

PAGE_SIZE = 10


def _require_admin(func):
    import functools
    @functools.wraps(func)
    async def wrapper(message_or_cb, state: FSMContext = None, *args, **kwargs):
        if isinstance(message_or_cb, Message):
            tid = message_or_cb.from_user.id
        else:
            tid = message_or_cb.from_user.id
        async with AsyncSessionLocal() as session:
            user = await get_or_create_user(session, tid, "")
        if not is_admin_or_higher(user.role):
            if isinstance(message_or_cb, Message):
                await message_or_cb.answer("⛔ Ruxsat yo'q.")
            else:
                await message_or_cb.answer("⛔ Ruxsat yo'q.", show_alert=True)
            return
        if state:
            return await func(message_or_cb, state, *args, **kwargs)
        return await func(message_or_cb, *args, **kwargs)
    return wrapper


async def send_admin_main(message: Message, state: FSMContext):
    await state.set_state(AdminStates.main_menu)
    await message.answer(
        "👑 <b>Admin Panel — QULAY MARKET</b>\n\nBo'limni tanlang:",
        parse_mode="HTML",
        reply_markup=admin_main_keyboard(),
    )


@admin_router.message(F.text == "/admin")
async def admin_command(message: Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(
            session, message.from_user.id, message.from_user.full_name
        )
    if not is_admin_or_higher(user.role):
        await message.answer("⛔ Ruxsat yo'q.")
        return
    await send_admin_main(message, state)


@admin_router.message(F.text == "📊 Dashboard")
async def admin_dashboard(message: Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.full_name)
        if not is_admin_or_higher(user.role):
            return
        stats = await get_today_stats(session)
        low_stock = await get_low_stock_products(session)
        out_of_stock = await get_out_of_stock_products(session)
        top = await get_top_products(session, 3)

    top_text = "\n".join(f"  {i+1}. {p['name']} — {p['qty']} ta" for i, p in enumerate(top))
    text = (
        f"📊 <b>Dashboard — {stats['date']}</b>\n\n"
        f"🏪 Kassa savdolari: <b>{stats['sales_count']} ta</b> / {format_price(stats['sales_total'])}\n"
        f"📦 Buyurtmalar (olib ketilgan): <b>{stats['orders_count']} ta</b> / {format_price(stats['orders_total'])}\n"
        f"⏳ Kutayotgan: <b>{stats['pending_orders']} ta</b>\n\n"
        f"⚠️ Kam qolgan: <b>{len(low_stock)} ta</b>\n"
        f"❌ Tugagan: <b>{len(out_of_stock)} ta</b>\n"
    )
    if top:
        text += f"\n🏆 Top mahsulotlar:\n{top_text}"
    await message.answer(text, parse_mode="HTML", reply_markup=admin_main_keyboard())


@admin_router.message(F.text == "📦 Mahsulotlar")
async def admin_products(message: Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.full_name)
        if not is_admin_or_higher(user.role):
            return
    await state.set_state(AdminStates.products_menu)
    await message.answer(
        "📦 <b>Mahsulotlar boshqaruvi</b>",
        parse_mode="HTML",
        reply_markup=admin_products_keyboard(),
    )


@admin_router.callback_query(F.data == "admin_products_back")
async def admin_products_back(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.products_menu)
    await callback.message.edit_text(
        "📦 <b>Mahsulotlar boshqaruvi</b>",
        parse_mode="HTML",
        reply_markup=admin_products_keyboard(),
    )
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin_list_products:"))
async def admin_list_products(callback: CallbackQuery, state: FSMContext):
    page = int(callback.data.split(":")[1])
    async with AsyncSessionLocal() as session:
        products, total = await get_all_products_admin(session, page)
    if not products:
        await callback.answer("Mahsulotlar yo'q!")
        return
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    await callback.message.edit_text(
        f"📋 Mahsulotlar ({page * PAGE_SIZE + 1}–{min((page + 1) * PAGE_SIZE, total)}/{total}):",
        reply_markup=products_list_keyboard(products, page, total_pages),
    )
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin_view_product:"))
async def admin_view_product(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split(":")[1])
    async with AsyncSessionLocal() as session:
        product = await get_product_by_id(session, product_id)
    if not product:
        await callback.answer("Topilmadi")
        return
    tags = ", ".join(f"#{t.tag}" for t in product.tags) if product.tags else "Yo'q"
    discount_text = format_price(product.discount_price) if product.has_discount else "Yo'q"
    cat = product.category.name if product.category else "Yo'q"
    text = (
        f"📦 <b>{product.name}</b>\n\n"
        f"💰 Narx: {format_price(product.price)}\n"
        f"🏷️ Aksiya: {discount_text}\n"
        f"📦 Miqdor: {product.quantity}\n"
        f"📁 Kategoriya: {cat}\n"
        f"🔖 Hashtaglar: {tags}\n"
        f"🔢 Barcode: {product.barcode or 'Yo\'q'}\n"
        f"📄 Tavsif: {product.description or 'Yo\'q'}\n"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=product_edit_keyboard(product_id))
    await callback.answer()


@admin_router.callback_query(F.data == "admin_add_product_manual")
async def start_add_product(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.add_product_name)
    await state.update_data({"new_product": {}})
    await callback.message.edit_text(
        "➕ <b>Yangi mahsulot qo'shish</b>\n\n1/8: Mahsulot nomini kiriting:",
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@admin_router.message(AdminStates.add_product_name)
async def add_product_name(message: Message, state: FSMContext):
    name = sanitize_text(message.text or "", 256)
    if not name:
        await message.answer("Iltimos, to'g'ri nom kiriting.")
        return
    await state.update_data({"new_product": {"name": name}})
    await state.set_state(AdminStates.add_product_barcode)
    await message.answer(
        f"✅ Nom: <b>{name}</b>\n\n2/8: Barcode kiriting (yoki /skip):",
        parse_mode="HTML",
    )


@admin_router.message(AdminStates.add_product_barcode)
async def add_product_barcode(message: Message, state: FSMContext):
    text = message.text or ""
    data = await state.get_data()
    product_data = data.get("new_product", {})
    if text != "/skip":
        barcode = sanitize_text(text, 64)
        if not is_valid_barcode(barcode):
            await message.answer("❌ Barcode noto'g'ri. Faqat raqam/harf ishlatilsin (4-30 belgi).")
            return
        product_data["barcode"] = barcode
    await state.update_data({"new_product": product_data})
    await state.set_state(AdminStates.add_product_price)
    await message.answer("3/8: Narxni kiriting (masalan: 12500):")


@admin_router.message(AdminStates.add_product_price)
async def add_product_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.replace(",", ".").replace(" ", ""))
        if price <= 0:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("❌ Noto'g'ri narx. Masalan: 12500")
        return
    data = await state.get_data()
    product_data = data.get("new_product", {})
    product_data["price"] = price
    await state.update_data({"new_product": product_data})
    await state.set_state(AdminStates.add_product_discount)
    await message.answer(f"✅ Narx: {format_price(price)}\n\n4/8: Aksiya narxi kiriting (yoki /skip):")


@admin_router.message(AdminStates.add_product_discount)
async def add_product_discount(message: Message, state: FSMContext):
    text = message.text or ""
    data = await state.get_data()
    product_data = data.get("new_product", {})
    if text != "/skip":
        try:
            disc = float(text.replace(",", ".").replace(" ", ""))
            if disc > 0 and disc < product_data.get("price", 0):
                product_data["discount_price"] = disc
            else:
                await message.answer("❌ Aksiya narxi 0 dan katta va asosiy narxdan kichik bo'lishi kerak.")
                return
        except (ValueError, AttributeError):
            await message.answer("❌ Noto'g'ri narx.")
            return
    await state.update_data({"new_product": product_data})
    await state.set_state(AdminStates.add_product_quantity)
    await message.answer("5/8: Miqdorni kiriting (masalan: 50):")


@admin_router.message(AdminStates.add_product_quantity)
async def add_product_quantity(message: Message, state: FSMContext):
    try:
        qty = int(message.text or "0")
        if qty < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Noto'g'ri miqdor.")
        return
    data = await state.get_data()
    product_data = data.get("new_product", {})
    product_data["quantity"] = qty
    await state.update_data({"new_product": product_data})
    await state.set_state(AdminStates.add_product_description)
    await message.answer("6/8: Tavsif kiriting (yoki /skip):")


@admin_router.message(AdminStates.add_product_description)
async def add_product_description(message: Message, state: FSMContext):
    text = message.text or ""
    data = await state.get_data()
    product_data = data.get("new_product", {})
    if text != "/skip":
        product_data["description"] = sanitize_text(text, 1000)
    await state.update_data({"new_product": product_data})
    await state.set_state(AdminStates.add_product_hashtags)
    await message.answer("7/8: Hashtaglarni kiriting (masalan: sut qatiq don yoki /skip):")


@admin_router.message(AdminStates.add_product_hashtags)
async def add_product_hashtags(message: Message, state: FSMContext):
    text = message.text or ""
    data = await state.get_data()
    product_data = data.get("new_product", {})
    if text != "/skip":
        tags = [t.strip().lower() for t in text.replace("#", "").split() if t.strip()]
        product_data["hashtags"] = tags[:20]
    await state.update_data({"new_product": product_data})
    await state.set_state(AdminStates.add_product_image)
    await message.answer("8/8: Mahsulot rasmini yuboring (yoki /skip):")


@admin_router.message(AdminStates.add_product_image)
async def add_product_image(message: Message, state: FSMContext):
    data = await state.get_data()
    product_data = data.get("new_product", {})
    if message.photo:
        product_data["image_file_id"] = message.photo[-1].file_id
    elif message.text and message.text == "/skip":
        pass
    else:
        await message.answer("Rasm yuboring yoki /skip yozing.")
        return

    async with AsyncSessionLocal() as session:
        cats = await get_all_categories(session)
        product = await create_product(
            session,
            name=product_data["name"],
            price=product_data["price"],
            quantity=product_data.get("quantity", 0),
            barcode=product_data.get("barcode"),
            description=product_data.get("description"),
            discount_price=product_data.get("discount_price"),
            image_file_id=product_data.get("image_file_id"),
            hashtags=product_data.get("hashtags", []),
        )

    await state.set_state(AdminStates.products_menu)
    await state.update_data({"new_product": {}})
    tags_text = ", ".join(f"#{t}" for t in product_data.get("hashtags", []))
    await message.answer(
        f"✅ <b>Mahsulot qo'shildi!</b>\n\n"
        f"📦 {product.name}\n"
        f"💰 {format_price(product.price)}\n"
        f"📦 Miqdor: {product.quantity}\n"
        f"🔖 Teglar: {tags_text or 'Yo\'q'}\n"
        f"🆔 ID: {product.id}",
        parse_mode="HTML",
        reply_markup=admin_main_keyboard(),
    )


@admin_router.callback_query(F.data.startswith("admin_edit_field:"))
async def admin_edit_field(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    product_id = int(parts[1])
    field = parts[2]
    await state.set_state(AdminStates.edit_product_field)
    await state.update_data({"edit_product_id": product_id, "edit_field": field})
    field_prompts = {
        "name": "Yangi nom kiriting:",
        "price": "Yangi narx kiriting (so'm):",
        "discount": "Yangi aksiya narxi kiriting (yoki 0 — o'chirish):",
        "quantity": "Yangi miqdor kiriting:",
        "description": "Yangi tavsif kiriting (yoki /skip — o'chirish):",
        "image": "Yangi rasm yuboring:",
        "hashtags": "Yangi hashtaglar kiriting (bo'sh joy bilan ajrating):",
        "category": "Kategoriya ID kiriting:",
    }
    await callback.message.edit_text(
        f"✏️ {field_prompts.get(field, 'Yangi qiymat kiriting:')}",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@admin_router.message(AdminStates.edit_product_field)
async def apply_edit_field(message: Message, state: FSMContext):
    data = await state.get_data()
    product_id = data.get("edit_product_id")
    field = data.get("edit_field")
    text = message.text or ""
    update_kwargs = {}

    if field == "name":
        update_kwargs["name"] = sanitize_text(text, 256)
    elif field == "price":
        try:
            update_kwargs["price"] = float(text.replace(",", ".").replace(" ", ""))
        except ValueError:
            await message.answer("❌ Noto'g'ri narx.")
            return
    elif field == "discount":
        try:
            val = float(text.replace(",", ".").replace(" ", ""))
            update_kwargs["discount_price"] = val if val > 0 else None
        except ValueError:
            await message.answer("❌ Noto'g'ri narx.")
            return
    elif field == "quantity":
        try:
            update_kwargs["quantity"] = int(text)
        except ValueError:
            await message.answer("❌ Noto'g'ri miqdor.")
            return
    elif field == "description":
        update_kwargs["description"] = None if text == "/skip" else sanitize_text(text, 1000)
    elif field == "image":
        if message.photo:
            update_kwargs["image_file_id"] = message.photo[-1].file_id
        else:
            await message.answer("Rasm yuboring.")
            return
    elif field == "hashtags":
        tags = [t.strip().lower() for t in text.replace("#", "").split() if t.strip()]
        update_kwargs["hashtags"] = tags
    elif field == "category":
        try:
            update_kwargs["category_id"] = int(text)
        except ValueError:
            await message.answer("❌ Noto'g'ri ID.")
            return

    async with AsyncSessionLocal() as session:
        product = await update_product(session, product_id, **update_kwargs)
        if product and product.quantity <= LOW_STOCK_THRESHOLD and product.quantity > 0:
            from main import get_bot
            bot = get_bot()
            if bot:
                await notify_low_stock(bot, session, product)
        elif product and product.quantity == 0:
            from main import get_bot
            bot = get_bot()
            if bot:
                await notify_out_of_stock(bot, session, product)

    await state.set_state(AdminStates.products_menu)
    await message.answer(
        "✅ Mahsulot yangilandi!",
        reply_markup=admin_main_keyboard(),
    )


@admin_router.callback_query(F.data.startswith("admin_delete_product:"))
async def admin_delete_product(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split(":")[1])
    await callback.message.edit_text(
        "⚠️ Mahsulotni o'chirishni tasdiqlaysizmi?",
        reply_markup=confirm_keyboard("del_product", product_id),
    )
    await callback.answer()


@admin_router.callback_query(F.data.startswith("del_product:yes:"))
async def confirm_delete_product(callback: CallbackQuery):
    product_id = int(callback.data.split(":")[2])
    async with AsyncSessionLocal() as session:
        await delete_product(session, product_id)
    await callback.message.edit_text("✅ Mahsulot o'chirildi.")
    await callback.answer()


@admin_router.callback_query(F.data.startswith("del_product:no:"))
async def cancel_delete_product(callback: CallbackQuery):
    await callback.message.edit_text("Bekor qilindi.")
    await callback.answer()


@admin_router.message(F.text == "🛒 Zakazlar")
async def admin_orders(message: Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.full_name)
        if not is_admin_or_higher(user.role):
            return
    await state.set_state(AdminStates.orders_menu)
    await message.answer(
        "🛒 <b>Zakazlar boshqaruvi</b>\n\nFilterni tanlang:",
        parse_mode="HTML",
        reply_markup=admin_orders_filter_keyboard(),
    )


@admin_router.callback_query(F.data.startswith("admin_orders_filter:"))
async def admin_orders_filter(callback: CallbackQuery, state: FSMContext):
    filter_val = callback.data.split(":")[1]
    async with AsyncSessionLocal() as session:
        if filter_val == "all":
            orders = await get_orders_by_status(session, None, 30)
        else:
            try:
                status = OrderStatus(filter_val)
            except ValueError:
                await callback.answer("Noto'g'ri filter")
                return
            orders = await get_orders_by_status(session, status, 30)

    if not orders:
        await callback.answer("Bu statusda zakaz yo'q!")
        return

    builder = InlineKeyboardBuilder()
    for order in orders:
        user_name = order.user.full_name if order.user else "Noma'lum"
        status_text = format_order_status(order.status)
        builder.row(InlineKeyboardButton(
            text=f"#{order.id} | {user_name[:12]} | {format_price(order.total_amount)} | {status_text}",
            callback_data=f"admin_order_detail:{order.id}",
        ))
    builder.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data="admin_orders_back"))

    await callback.message.edit_text(
        f"📋 <b>Zakazlar ({len(orders)} ta):</b>",
        parse_mode="HTML",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@admin_router.callback_query(F.data == "admin_orders_back")
async def admin_orders_back(callback: CallbackQuery):
    await callback.message.edit_text(
        "🛒 <b>Zakazlar boshqaruvi</b>\n\nFilterni tanlang:",
        parse_mode="HTML",
        reply_markup=admin_orders_filter_keyboard(),
    )
    await callback.answer()


@admin_router.callback_query(F.data.startswith("admin_order_detail:"))
async def admin_order_detail(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split(":")[1])
    async with AsyncSessionLocal() as session:
        order = await get_order_by_id(session, order_id)
    if not order:
        await callback.answer("Topilmadi")
        return
    await _show_order_detail(callback, order)
    await callback.answer()


async def _show_order_detail(callback: CallbackQuery, order):
    items_text = "\n".join(
        f"  • {i.product_name_snapshot} x{i.quantity} — {format_price(i.subtotal)}"
        for i in order.items
    )
    user = order.user
    username = f"@{user.username}" if user and user.username else (user.full_name if user else "Noma'lum")
    trusted = "✅ Ishonchli" if user and user.is_trusted else "❌ Oddiy"
    status_text = format_order_status(order.status)

    text = (
        f"📦 <b>Zakaz #{order.id}</b>\n\n"
        f"👤 Mijoz: {username} ({trusted})\n"
        f"📊 Holat: {status_text}\n"
        f"💰 Jami: <b>{format_price(order.total_amount)}</b>\n"
        f"⏰ Olib ketish: {format_datetime(order.pickup_time) if order.pickup_time else 'Belgilanmagan'}\n"
        f"🔑 Kod: <code>{order.pickup_code}</code>\n\n"
        f"📋 Mahsulotlar:\n{items_text}\n"
    )
    if order.verification_text:
        text += f"\n✍️ Mijoz taqdimoti: {order.verification_text}"
    if order.admin_note:
        text += f"\n📝 Nota: {order.admin_note}"
    if order.rejection_reason:
        text += f"\n❌ Rad etish sababi: {order.rejection_reason}"

    await callback.message.edit_text(
        text, parse_mode="HTML",
        reply_markup=admin_order_keyboard(order.id, order.status)
    )


@admin_router.callback_query(F.data.startswith("admin_order_confirm:"))
async def admin_order_confirm(callback: CallbackQuery, bot: Bot):
    order_id = int(callback.data.split(":")[1])
    async with AsyncSessionLocal() as session:
        admin_user = await get_or_create_user(session, callback.from_user.id, callback.from_user.full_name)
        order = await update_order_status(
            session, order_id, OrderStatus.confirmed,
            verified_by=admin_user.id,
        )
        if order and order.user and order.user.telegram_id:
            await notify_order_status_change(bot, order.user.telegram_id, order)
    await callback.answer("✅ Zakaz tasdiqlandi!")
    if order:
        await _show_order_detail(callback, order)


@admin_router.callback_query(F.data.startswith("admin_order_reject:"))
async def admin_order_reject_prompt(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split(":")[1])
    await state.set_state(AdminStates.order_reject_reason)
    await state.update_data({"reject_order_id": order_id})
    await callback.message.edit_text(
        "❌ Rad etish sababini kiriting:",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@admin_router.message(AdminStates.order_reject_reason)
async def admin_order_reject_apply(message: Message, state: FSMContext, bot: Bot):
    reason = sanitize_text(message.text or "", 256)
    data = await state.get_data()
    order_id = data.get("reject_order_id")
    async with AsyncSessionLocal() as session:
        admin_user = await get_or_create_user(session, message.from_user.id, message.from_user.full_name)
        order = await get_order_by_id(session, order_id)
        if order:
            for item in order.items:
                await adjust_product_quantity(
                    session, item.product_id, item.quantity, "order_rejected"
                )
            order = await update_order_status(
                session, order_id, OrderStatus.rejected,
                rejection_reason=reason,
                verified_by=admin_user.id,
            )
            if order and order.user and order.user.telegram_id:
                await notify_order_status_change(bot, order.user.telegram_id, order)
    await state.set_state(AdminStates.orders_menu)
    await message.answer(f"✅ Zakaz #{order_id} rad etildi.", reply_markup=admin_main_keyboard())


@admin_router.callback_query(F.data.startswith("admin_order_preparing:"))
async def admin_order_preparing(callback: CallbackQuery, bot: Bot):
    order_id = int(callback.data.split(":")[1])
    async with AsyncSessionLocal() as session:
        order = await update_order_status(session, order_id, OrderStatus.preparing)
        if order and order.user and order.user.telegram_id:
            await notify_order_status_change(bot, order.user.telegram_id, order)
    await callback.answer("👨‍🍳 Tayyorlanmoqda!")
    if order:
        await _show_order_detail(callback, order)


@admin_router.callback_query(F.data.startswith("admin_order_ready:"))
async def admin_order_ready(callback: CallbackQuery, bot: Bot):
    order_id = int(callback.data.split(":")[1])
    async with AsyncSessionLocal() as session:
        order = await update_order_status(session, order_id, OrderStatus.ready)
        if order and order.user and order.user.telegram_id:
            await notify_order_status_change(bot, order.user.telegram_id, order)
    await callback.answer("✅ Zakaz tayyor!")
    if order:
        await _show_order_detail(callback, order)


@admin_router.callback_query(F.data.startswith("admin_order_note:"))
async def admin_order_note_prompt(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split(":")[1])
    await state.set_state(AdminStates.order_note)
    await state.update_data({"note_order_id": order_id})
    await callback.message.edit_text(
        "📝 Nota kiriting:",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@admin_router.message(AdminStates.order_note)
async def admin_order_note_apply(message: Message, state: FSMContext):
    note = sanitize_text(message.text or "", 500)
    data = await state.get_data()
    order_id = data.get("note_order_id")
    async with AsyncSessionLocal() as session:
        await update_order_status(session, order_id, admin_note=note, status=None)
        from sqlalchemy import update as sa_update
        from models import Order as OrderModel
        await session.execute(
            sa_update(OrderModel).where(OrderModel.id == order_id).values(admin_note=note)
        )
        await session.commit()
    await state.set_state(AdminStates.orders_menu)
    await message.answer(f"✅ Nota qo'shildi.", reply_markup=admin_main_keyboard())


@admin_router.message(F.text == "🏭 Ombor")
async def admin_warehouse(message: Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.full_name)
        if not is_admin_or_higher(user.role):
            return
        low = await get_low_stock_products(session)
        out = await get_out_of_stock_products(session)

    text = "🏭 <b>Ombor holati</b>\n\n"
    if out:
        text += f"❌ <b>Tugagan ({len(out)} ta):</b>\n"
        for p in out[:10]:
            text += f"  • {p.name}\n"
    if low:
        text += f"\n⚠️ <b>Kam qolgan ({len(low)} ta):</b>\n"
        for p in low[:10]:
            text += f"  • {p.name} — {p.quantity} ta\n"
    if not out and not low:
        text += "✅ Ombor holati yaxshi!"

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="📦 Mahsulotga qo'shish", callback_data="warehouse_add_stock"
    ))
    await message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())


@admin_router.callback_query(F.data == "warehouse_add_stock")
async def warehouse_add_stock_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.add_stock)
    await callback.message.edit_text(
        "📦 Mahsulot ID va qo'shiladigan miqdorni kiriting:\nFormat: <code>ID miqdor</code>\nMasalan: <code>5 100</code>",
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@admin_router.message(AdminStates.add_stock)
async def warehouse_add_stock_apply(message: Message, state: FSMContext):
    try:
        parts = message.text.strip().split()
        product_id = int(parts[0])
        qty = int(parts[1])
        if qty <= 0:
            raise ValueError
    except (ValueError, IndexError):
        await message.answer("❌ Format noto'g'ri. Masalan: 5 100")
        return
    async with AsyncSessionLocal() as session:
        product = await get_product_by_id(session, product_id)
        if not product:
            await message.answer("❌ Mahsulot topilmadi.")
            return
        user = await get_or_create_user(session, message.from_user.id, message.from_user.full_name)
        await adjust_product_quantity(session, product_id, qty, "warehouse_restock", user.id)
        updated = await get_product_by_id(session, product_id)
    await state.set_state(None)
    await message.answer(
        f"✅ <b>{updated.name}</b> ombori yangilandi.\n"
        f"Yangi miqdor: <b>{updated.quantity} ta</b>",
        parse_mode="HTML",
        reply_markup=admin_main_keyboard(),
    )


@admin_router.message(F.text == "📈 Statistika")
async def admin_stats(message: Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.full_name)
        if not is_admin_or_higher(user.role):
            return
        stats = await get_today_stats(session)
        top5 = await get_top_products(session, 5)
        weekly = await get_weekly_stats(session)
        cashiers = await get_cashier_stats(session)
        low = await get_low_stock_products(session)
        hourly = await get_hourly_sales(session)

    top_text = "\n".join(
        f"  {i+1}. {p['name']} — {p['qty']} ta ({format_price(p['total'])})"
        for i, p in enumerate(top5)
    ) or "  Ma'lumot yo'q"

    weekly_text = "\n".join(
        f"  {w['date']}: {format_price(w['total'])}" for w in weekly
    )

    cashier_text = "\n".join(
        f"  {c['name']}: {c['sales']} ta — {format_price(c['total'])}"
        for c in cashiers
    ) or "  Ma'lumot yo'q"

    peak_hour = max(hourly, key=lambda x: x['total'], default=None)
    peak_text = f"{peak_hour['hour']}:00 — {format_price(peak_hour['total'])}" if peak_hour else "Yo'q"

    text = (
        f"📈 <b>Statistika</b>\n\n"
        f"━━━━━ Bugun ({stats['date']}) ━━━━━\n"
        f"🏪 Savdolar: {stats['sales_count']} ta / {format_price(stats['sales_total'])}\n"
        f"📦 Buyurtmalar: {stats['orders_count']} ta / {format_price(stats['orders_total'])}\n"
        f"⏳ Kutayotgan: {stats['pending_orders']} ta\n"
        f"⚡ Eng ko'p soat: {peak_text}\n\n"
        f"━━━━━ Top 5 mahsulot ━━━━━\n{top_text}\n\n"
        f"━━━━━ Haftalik ━━━━━\n{weekly_text}\n\n"
        f"━━━━━ Kassirlar ━━━━━\n{cashier_text}\n\n"
        f"⚠️ Kam qolgan: {len(low)} ta mahsulot"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=admin_main_keyboard())


@admin_router.message(F.text == "⚙️ Sozlamalar")
async def admin_settings(message: Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(session, message.from_user.id, message.from_user.full_name)
        if user.role != UserRole.owner:
            await message.answer("⛔ Faqat owner uchun.")
            return
        threshold = await get_setting(session, "low_stock_threshold", str(LOW_STOCK_THRESHOLD))

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔢 Low stock chegarasi", callback_data="setting_low_stock"))
    builder.row(InlineKeyboardButton(text="📋 Kategoriya qo'shish", callback_data="setting_add_category"))
    builder.row(InlineKeyboardBuilder().button(
        text="👤 Foydalanuvchini ishonchli qilish", callback_data="setting_trust_user"
    ).as_markup().inline_keyboard[0][0])

    await message.answer(
        f"⚙️ <b>Sozlamalar</b>\n\n"
        f"🔢 Low stock chegarasi: <b>{threshold}</b>",
        parse_mode="HTML",
        reply_markup=builder.as_markup(),
    )


@admin_router.callback_query(F.data == "setting_low_stock")
async def setting_low_stock(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.low_stock_threshold)
    await callback.message.edit_text(
        "🔢 Yangi low stock chegarasini kiriting (masalan: 5):",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@admin_router.message(AdminStates.low_stock_threshold)
async def apply_low_stock_threshold(message: Message, state: FSMContext):
    try:
        val = int(message.text or "")
        if val < 1:
            raise ValueError
    except ValueError:
        await message.answer("❌ Noto'g'ri qiymat.")
        return
    async with AsyncSessionLocal() as session:
        await set_setting(session, "low_stock_threshold", str(val))
    await state.set_state(None)
    await message.answer(f"✅ Low stock chegarasi {val} ga o'rnatildi.", reply_markup=admin_main_keyboard())


@admin_router.callback_query(F.data == "setting_add_category")
async def setting_add_category(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.add_category)
    await callback.message.edit_text(
        "📁 Yangi kategoriya nomini kiriting:",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@admin_router.message(AdminStates.add_category)
async def apply_add_category(message: Message, state: FSMContext):
    name = sanitize_text(message.text or "", 128)
    if not name:
        await message.answer("❌ Nom bo'sh bo'lishi mumkin emas.")
        return
    async with AsyncSessionLocal() as session:
        cat = await create_category(session, name)
    await state.set_state(None)
    await message.answer(
        f"✅ Kategoriya qo'shildi: <b>{cat.name}</b> (ID: {cat.id})",
        parse_mode="HTML",
        reply_markup=admin_main_keyboard(),
    )


@admin_router.callback_query(F.data == "setting_trust_user")
async def setting_trust_user(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.manage_users)
    await callback.message.edit_text(
        "👤 Foydalanuvchi Telegram ID ni kiriting (ishonchli qilish uchun):",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@admin_router.message(AdminStates.manage_users)
async def apply_trust_user(message: Message, state: FSMContext):
    try:
        tid = int(message.text or "")
    except ValueError:
        await message.answer("❌ Noto'g'ri ID.")
        return
    async with AsyncSessionLocal() as session:
        from sqlalchemy import select
        from models import User as UserModel
        result = await session.execute(
            select(UserModel).where(UserModel.telegram_id == tid)
        )
        target = result.scalar_one_or_none()
        if not target:
            await message.answer("❌ Foydalanuvchi topilmadi.")
            return
        await set_user_trusted(session, target.id, True)
    await state.set_state(None)
    await message.answer(
        f"✅ {tid} ID li foydalanuvchi ishonchli deb belgilandi.",
        reply_markup=admin_main_keyboard(),
    )


@admin_router.callback_query(F.data == "admin_categories")
async def admin_categories(callback: CallbackQuery):
    async with AsyncSessionLocal() as session:
        cats = await get_all_categories(session)
    if not cats:
        await callback.answer("Kategoriyalar yo'q!")
        return
    text = "📁 <b>Kategoriyalar:</b>\n\n"
    for c in cats:
        text += f"  {c.emoji or '📁'} {c.name} (ID: {c.id})\n"
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_products_keyboard())
    await callback.answer()


@admin_router.callback_query(F.data == "admin_back_main")
async def admin_back_main(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.main_menu)
    await callback.message.edit_text(
        "👑 <b>Admin Panel — QULAY MARKET</b>",
        parse_mode="HTML",
    )
    await callback.answer()


@admin_router.callback_query(F.data == "cancel")
async def cancel_action(callback: CallbackQuery, state: FSMContext):
    await state.set_state(None)
    await callback.message.edit_text("❌ Bekor qilindi.")
    await callback.answer()


@admin_router.message(F.text == "🏠 Bosh menyu")
async def admin_back_home(message: Message, state: FSMContext):
    await state.set_state(None)
    from keyboards import main_menu_keyboard
    await message.answer(
        "🏠 Bosh menyu",
        reply_markup=main_menu_keyboard(),
    )