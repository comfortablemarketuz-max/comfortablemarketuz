import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from aiogram import Router, F, Bot
from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from engine import AsyncSessionLocal
from models import User, UserRole, OrderStatus
from states import CustomerStates
from keyboards import (
    main_menu_keyboard, search_mode_keyboard, product_nav_keyboard,
    cart_keyboard, pickup_time_keyboard, order_verification_keyboard,
    order_detail_keyboard, remove_keyboard, cancel_keyboard
)
from services import (
    get_or_create_user, set_user_search_mode,
    search_products, get_discounted_products, get_product_by_id,
    add_to_cart, remove_from_cart, update_cart_item_qty,
    clear_cart, get_cart_with_items,
    create_order_from_cart, get_user_orders, get_order_by_id,
    set_order_verification, cancel_order,
)
from notifications import (
    notify_new_order, notify_order_needs_verification, notify_user
)
from permissions import is_staff
from utils import (
    format_price, format_datetime, format_order_status,
    parse_pickup_time, validate_pickup_time, sanitize_text
)
from config import MIN_ORDER_VERIFY_AMOUNT, MIN_PICKUP_MINUTES

logger = logging.getLogger(__name__)
customer_router = Router()

SEARCH_RESULTS_KEY = "search_results"
SEARCH_INDEX_KEY = "search_index"
SEARCH_MSG_ID_KEY = "search_msg_id"


def build_product_card_text(product, index: int, total: int) -> str:
    price_line = ""
    if product.has_discount:
        price_line = (
            f"💰 Narx: <s>{format_price(product.price)}</s> → "
            f"<b>{format_price(product.discount_price)}</b> 🏷️ Aksiya!\n"
        )
    else:
        price_line = f"💰 Narx: <b>{format_price(product.price)}</b>\n"

    cat = product.category.name if product.category else ""
    stock = f"✅ Mavjud: {product.quantity} ta" if product.is_in_stock else "❌ Tugagan"

    text = (
        f"<b>{product.name}</b>\n\n"
        f"{price_line}"
        f"📦 {stock}\n"
    )
    if cat:
        text += f"📁 {cat}\n"
    if product.description:
        text += f"\n{product.description}\n"
    text += f"\n{index + 1}/{total}"
    return text


async def show_product_card(
    bot: Bot,
    chat_id: int,
    products: List,
    index: int,
    state: FSMContext,
    user_id: int,
    session,
    message_id: Optional[int] = None,
) -> int:
    if not products or index < 0 or index >= len(products):
        return message_id or 0
    product = products[index]
    from services import get_cart_with_items, CartItem
    cart = await get_cart_with_items(session, user_id)
    cart_item = next((i for i in cart.items if i.product_id == product.id), None)
    in_cart = cart_item is not None
    cart_qty = cart_item.quantity if cart_item else 0

    text = build_product_card_text(product, index, len(products))
    kb = product_nav_keyboard(product.id, index, len(products), in_cart, cart_qty)

    try:
        if message_id:
            if product.image_file_id:
                await bot.edit_message_media(
                    chat_id=chat_id,
                    message_id=message_id,
                    media=__import__('aiogram').types.InputMediaPhoto(
                        media=product.image_file_id,
                        caption=text,
                        parse_mode="HTML",
                    ),
                    reply_markup=kb,
                )
            else:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=kb,
                )
            return message_id
        else:
            if product.image_file_id:
                msg = await bot.send_photo(
                    chat_id=chat_id,
                    photo=product.image_file_id,
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=kb,
                )
            else:
                msg = await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=kb,
                )
            return msg.message_id
    except Exception as e:
        logger.error(f"Mahsulot kartasi ko'rsatishda xato: {e}")
        try:
            if product.image_file_id:
                msg = await bot.send_photo(
                    chat_id=chat_id,
                    photo=product.image_file_id,
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=kb,
                )
            else:
                msg = await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=kb,
                )
            return msg.message_id
        except Exception as e2:
            logger.error(f"Qayta urinishda ham xato: {e2}")
            return message_id or 0


@customer_router.message(F.text == "/start")
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    async with AsyncSessionLocal() as session:
        from permissions import get_role_for_telegram_id
        role = get_role_for_telegram_id(message.from_user.id)
        user = await get_or_create_user(
            session,
            telegram_id=message.from_user.id,
            full_name=message.from_user.full_name,
            username=message.from_user.username,
            role=role,
        )
    if is_staff(user.role):
        from admin import send_admin_main
        await send_admin_main(message, state)
        return
    await message.answer(
        f"👋 Xush kelibsiz, <b>{user.full_name}</b>!\n\n"
        f"🏪 <b>QULAY MARKET</b> ga xush kelibsiz!\n"
        f"Mahsulot qidirish, savat va buyurtma berish uchun "
        f"quyidagi tugmalardan foydalaning.",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )


@customer_router.message(F.text == "🔍 Qidirish")
async def start_search(message: Message, state: FSMContext):
    await state.set_state(CustomerStates.searching)
    await state.update_data({SEARCH_RESULTS_KEY: [], SEARCH_INDEX_KEY: 0, SEARCH_MSG_ID_KEY: None})
    async with AsyncSessionLocal() as session:
        await set_user_search_mode(session, message.from_user.id, True)
    await message.answer(
        "🔍 <b>Qidiruv rejimi yoqildi</b>\n\n"
        "Mahsulot nomini yozing. Qidiruvni yakunlash uchun «❌ Qidiruvni yopish» tugmasini bosing.",
        parse_mode="HTML",
        reply_markup=search_mode_keyboard(),
    )


@customer_router.message(F.text == "❌ Qidiruvni yopish")
async def stop_search(message: Message, state: FSMContext):
    await state.set_state(None)
    async with AsyncSessionLocal() as session:
        await set_user_search_mode(session, message.from_user.id, False)
    await message.answer(
        "✅ Qidiruv yopildi.",
        reply_markup=main_menu_keyboard(),
    )


@customer_router.message(CustomerStates.searching)
async def handle_search_query(message: Message, state: FSMContext, bot: Bot):
    if message.text and message.text.startswith("/"):
        return
    query = sanitize_text(message.text or "", 100)
    if not query:
        return

    async with AsyncSessionLocal() as session:
        products = await search_products(session, query, for_customer=True)

    if not products:
        await message.answer(
            f"😕 <b>«{query}»</b> bo'yicha hech narsa topilmadi.\n"
            "Boshqa so'z yoki hashtag bilan urinib ko'ring.",
            parse_mode="HTML",
        )
        return

    data = await state.get_data()
    old_msg_id = data.get(SEARCH_MSG_ID_KEY)

    product_ids = [p.id for p in products]
    await state.update_data({
        SEARCH_RESULTS_KEY: product_ids,
        SEARCH_INDEX_KEY: 0,
        SEARCH_MSG_ID_KEY: None,
    })

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(
            session, message.from_user.id, message.from_user.full_name
        )
        fresh_products = []
        for pid in product_ids:
            p = await get_product_by_id(session, pid)
            if p:
                fresh_products.append(p)

        if old_msg_id:
            try:
                await bot.delete_message(message.chat.id, old_msg_id)
            except Exception:
                pass

        new_msg_id = await show_product_card(
            bot=bot,
            chat_id=message.chat.id,
            products=fresh_products,
            index=0,
            state=state,
            user_id=user.id,
            session=session,
        )
        await state.update_data({
            SEARCH_RESULTS_KEY: product_ids,
            SEARCH_INDEX_KEY: 0,
            SEARCH_MSG_ID_KEY: new_msg_id,
        })


@customer_router.callback_query(F.data.startswith("prod_nav:"))
async def navigate_products(callback: CallbackQuery, state: FSMContext, bot: Bot):
    index = int(callback.data.split(":")[1])
    data = await state.get_data()
    product_ids = data.get(SEARCH_RESULTS_KEY, [])
    if not product_ids or index < 0 or index >= len(product_ids):
        await callback.answer("Mahsulot topilmadi")
        return

    await state.update_data({SEARCH_INDEX_KEY: index})
    async with AsyncSessionLocal() as session:
        products = []
        for pid in product_ids:
            p = await get_product_by_id(session, pid)
            if p:
                products.append(p)
        user = await get_or_create_user(
            session, callback.from_user.id, callback.from_user.full_name
        )
        msg_id = await show_product_card(
            bot=bot,
            chat_id=callback.message.chat.id,
            products=products,
            index=index,
            state=state,
            user_id=user.id,
            session=session,
            message_id=callback.message.message_id,
        )
        await state.update_data({SEARCH_MSG_ID_KEY: msg_id})
    await callback.answer()


@customer_router.callback_query(F.data == "noop")
async def noop_callback(callback: CallbackQuery):
    await callback.answer()


@customer_router.message(F.text == "🏷️ Aksiyalar")
async def show_promotions(message: Message, state: FSMContext, bot: Bot):
    async with AsyncSessionLocal() as session:
        products = await get_discounted_products(session)

    if not products:
        await message.answer(
            "😕 Hozirda aktiv aksiyalar yo'q.",
            reply_markup=main_menu_keyboard(),
        )
        return

    product_ids = [p.id for p in products]
    await state.update_data({
        SEARCH_RESULTS_KEY: product_ids,
        SEARCH_INDEX_KEY: 0,
        SEARCH_MSG_ID_KEY: None,
    })

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(
            session, message.from_user.id, message.from_user.full_name
        )
        fresh_products = [await get_product_by_id(session, pid) for pid in product_ids]
        fresh_products = [p for p in fresh_products if p]
        new_msg_id = await show_product_card(
            bot=bot,
            chat_id=message.chat.id,
            products=fresh_products,
            index=0,
            state=state,
            user_id=user.id,
            session=session,
        )
        await state.update_data({SEARCH_MSG_ID_KEY: new_msg_id})


@customer_router.callback_query(F.data.startswith("cart_add:"))
async def cart_add(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split(":")[1])
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(
            session, callback.from_user.id, callback.from_user.full_name
        )
        ok, msg = await add_to_cart(session, user.id, product_id)
    await callback.answer(msg)
    if ok:
        await _refresh_product_card_in_place(callback, state)


@customer_router.callback_query(F.data.startswith("cart_inc:"))
async def cart_increment(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split(":")[1])
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(
            session, callback.from_user.id, callback.from_user.full_name
        )
        ok, new_qty = await update_cart_item_qty(session, user.id, product_id, +1)
    await callback.answer(f"Miqdor: {new_qty}" if ok else "Maksimal miqdor")
    if ok:
        await _refresh_product_card_in_place(callback, state)


@customer_router.callback_query(F.data.startswith("cart_dec:"))
async def cart_decrement(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split(":")[1])
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(
            session, callback.from_user.id, callback.from_user.full_name
        )
        ok, new_qty = await update_cart_item_qty(session, user.id, product_id, -1)
    if new_qty == 0:
        await callback.answer("Savatdan olib tashlandi")
    else:
        await callback.answer(f"Miqdor: {new_qty}")
    await _refresh_product_card_in_place(callback, state)


@customer_router.callback_query(F.data.startswith("cart_remove:"))
async def cart_remove(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split(":")[1])
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(
            session, callback.from_user.id, callback.from_user.full_name
        )
        await remove_from_cart(session, user.id, product_id)
    await callback.answer("Savatdan olib tashlandi")
    await _refresh_product_card_in_place(callback, state)


async def _refresh_product_card_in_place(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    product_ids = data.get(SEARCH_RESULTS_KEY, [])
    index = data.get(SEARCH_INDEX_KEY, 0)
    if not product_ids:
        return
    async with AsyncSessionLocal() as session:
        products = [await get_product_by_id(session, pid) for pid in product_ids]
        products = [p for p in products if p]
        user = await get_or_create_user(
            session, callback.from_user.id, callback.from_user.full_name
        )
        if products and 0 <= index < len(products):
            product = products[index]
            cart = await get_cart_with_items(session, user.id)
            cart_item = next((i for i in cart.items if i.product_id == product.id), None)
            in_cart = cart_item is not None
            cart_qty = cart_item.quantity if cart_item else 0
            text = build_product_card_text(product, index, len(products))
            kb = product_nav_keyboard(product.id, index, len(products), in_cart, cart_qty)
            try:
                if product.image_file_id:
                    from aiogram.types import InputMediaPhoto
                    await callback.message.edit_media(
                        InputMediaPhoto(
                            media=product.image_file_id,
                            caption=text,
                            parse_mode="HTML",
                        ),
                        reply_markup=kb,
                    )
                else:
                    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
            except Exception as e:
                logger.warning(f"Kartani yangilashda xato: {e}")


@customer_router.callback_query(F.data.startswith("cart_info:"))
async def cart_info_callback(callback: CallbackQuery):
    await callback.answer("Savatdagi miqdor")


@customer_router.message(F.text == "🛒 Savat")
async def show_cart(message: Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(
            session, message.from_user.id, message.from_user.full_name
        )
        cart = await get_cart_with_items(session, user.id)

    if not cart.items:
        await message.answer(
            "🛒 Savatingiz bo'sh.\n\nMahsulot qo'shish uchun «🔍 Qidirish» tugmasini bosing.",
            reply_markup=main_menu_keyboard(),
        )
        return

    text = "🛒 <b>Savatingiz:</b>\n\n"
    for item in cart.items:
        pname = item.product.name if item.product else "Noma'lum"
        text += f"• {pname} x{item.quantity} — {format_price(item.subtotal)}\n"
    text += f"\n💰 <b>Jami: {format_price(cart.total)}</b>"

    await message.answer(text, parse_mode="HTML", reply_markup=cart_keyboard(True))


@customer_router.callback_query(F.data == "cart_clear")
async def cart_clear(callback: CallbackQuery):
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(
            session, callback.from_user.id, callback.from_user.full_name
        )
        await clear_cart(session, user.id)
    await callback.message.edit_text(
        "🗑 Savat tozalandi.",
        reply_markup=None,
    )
    await callback.answer("Savat tozalandi")


@customer_router.callback_query(F.data == "continue_shopping")
async def continue_shopping(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await callback.message.answer(
        "🔍 Qidirishni davom ettirish uchun mahsulot nomini yozing.",
        reply_markup=search_mode_keyboard(),
    )
    await state.set_state(CustomerStates.searching)
    await callback.answer()


@customer_router.callback_query(F.data == "checkout")
async def start_checkout(callback: CallbackQuery, state: FSMContext):
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(
            session, callback.from_user.id, callback.from_user.full_name
        )
        cart = await get_cart_with_items(session, user.id)

    if not cart.items:
        await callback.answer("Savat bo'sh!")
        return

    await state.set_state(CustomerStates.checkout_pickup_time)
    await callback.message.edit_text(
        f"📦 Buyurtma jami: <b>{format_price(cart.total)}</b>\n\n"
        f"⏰ Olib ketish vaqtini tanlang yoki yozing (masalan: <code>14:30</code>):",
        parse_mode="HTML",
        reply_markup=pickup_time_keyboard(),
    )
    await callback.answer()


@customer_router.callback_query(F.data == "back_to_cart")
async def back_to_cart(callback: CallbackQuery, state: FSMContext):
    await state.set_state(None)
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(
            session, callback.from_user.id, callback.from_user.full_name
        )
        cart = await get_cart_with_items(session, user.id)
    if not cart.items:
        await callback.message.edit_text("🛒 Savat bo'sh.")
        return
    text = "🛒 <b>Savatingiz:</b>\n\n"
    for item in cart.items:
        pname = item.product.name if item.product else "?"
        text += f"• {pname} x{item.quantity} — {format_price(item.subtotal)}\n"
    text += f"\n💰 <b>Jami: {format_price(cart.total)}</b>"
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=cart_keyboard(True))
    await callback.answer()


@customer_router.callback_query(F.data == "cancel_checkout")
async def cancel_checkout(callback: CallbackQuery, state: FSMContext):
    await state.set_state(None)
    await callback.message.delete()
    await callback.message.answer(
        "Buyurtma bekor qilindi.",
        reply_markup=main_menu_keyboard(),
    )
    await callback.answer()


@customer_router.callback_query(F.data.startswith("pickup:"))
async def handle_pickup_choice(callback: CallbackQuery, state: FSMContext, bot: Bot):
    choice = callback.data.split(":")[1]
    if choice == "custom":
        await callback.message.edit_text(
            "📝 Olib ketish vaqtini kiriting:\n"
            "Format: <code>HH:MM</code> yoki <code>DD.MM.YYYY HH:MM</code>\n\n"
            "Masalan: <code>15:30</code> yoki <code>20.05.2025 09:00</code>",
            parse_mode="HTML",
            reply_markup=cancel_keyboard(),
        )
        await state.set_state(CustomerStates.checkout_pickup_time)
        await callback.answer()
        return

    minutes = int(choice)
    pickup_time = datetime.now() + timedelta(minutes=minutes)
    await _process_checkout(callback, state, bot, pickup_time)


@customer_router.message(CustomerStates.checkout_pickup_time)
async def handle_custom_pickup_time(message: Message, state: FSMContext, bot: Bot):
    from utils import parse_pickup_time, validate_pickup_time
    dt = parse_pickup_time(message.text or "")
    if not dt:
        await message.answer(
            "❌ Vaqt formatini tushunmadim.\n"
            "Iltimos, <code>HH:MM</code> yoki <code>DD.MM.YYYY HH:MM</code> formatida kiriting.",
            parse_mode="HTML",
        )
        return
    ok, err = validate_pickup_time(dt, MIN_PICKUP_MINUTES)
    if not ok:
        await message.answer(f"❌ {err}")
        return
    await _process_checkout_msg(message, state, bot, dt)


async def _process_checkout(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    pickup_time: datetime,
):
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(
            session, callback.from_user.id, callback.from_user.full_name
        )
        cart = await get_cart_with_items(session, user.id)
        if not cart.items:
            await callback.answer("Savat bo'sh!")
            return
        total = cart.total
        needs_verification = total >= MIN_ORDER_VERIFY_AMOUNT

        if needs_verification and not user.is_trusted:
            await state.update_data({"pending_pickup_time": pickup_time.isoformat()})
            await callback.message.edit_text(
                f"⚠️ Buyurtma summasi <b>{format_price(total)}</b>\n\n"
                f"50 000 so'mdan oshgan buyurtmalar uchun tasdiqlash kerak.\n\n"
                f"Quyidagilardan birini tanlang:",
                parse_mode="HTML",
                reply_markup=order_verification_keyboard(),
            )
            await state.set_state(CustomerStates.order_verification_photo)
            await callback.answer()
            return

        order = await create_order_from_cart(
            session, user.id, pickup_time, needs_verification=False
        )
        if not order:
            await callback.answer("Buyurtma yaratishda xato!")
            return
        await notify_new_order(bot, session, order)

    await state.set_state(None)
    await callback.message.edit_text(
        f"✅ <b>Buyurtma #{order.id} qabul qilindi!</b>\n\n"
        f"⏰ Olib ketish vaqti: <b>{format_datetime(pickup_time)}</b>\n"
        f"🔑 Pickup kodi: <code>{order.pickup_code}</code>\n\n"
        f"Buyurtma tayyor bo'lganda xabar beramiz.",
        parse_mode="HTML",
        reply_markup=None,
    )
    await callback.answer()


async def _process_checkout_msg(
    message: Message,
    state: FSMContext,
    bot: Bot,
    pickup_time: datetime,
):
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(
            session, message.from_user.id, message.from_user.full_name
        )
        cart = await get_cart_with_items(session, user.id)
        if not cart.items:
            await message.answer("Savat bo'sh!")
            return
        total = cart.total
        needs_verification = total >= MIN_ORDER_VERIFY_AMOUNT

        if needs_verification and not user.is_trusted:
            await state.update_data({"pending_pickup_time": pickup_time.isoformat()})
            await message.answer(
                f"⚠️ Buyurtma summasi <b>{format_price(total)}</b>\n\n"
                f"50 000 so'mdan oshgan buyurtmalar uchun tasdiqlash kerak.\n\n"
                f"Quyidagilardan birini tanlang:",
                parse_mode="HTML",
                reply_markup=order_verification_keyboard(),
            )
            await state.set_state(CustomerStates.order_verification_photo)
            return

        order = await create_order_from_cart(
            session, user.id, pickup_time, needs_verification=False
        )
        if not order:
            await message.answer("Buyurtma yaratishda xato. Qaytadan urinib ko'ring.")
            return
        await notify_new_order(bot, session, order)

    await state.set_state(None)
    await message.answer(
        f"✅ <b>Buyurtma #{order.id} qabul qilindi!</b>\n\n"
        f"⏰ Olib ketish vaqti: <b>{format_datetime(pickup_time)}</b>\n"
        f"🔑 Pickup kodi: <code>{order.pickup_code}</code>\n\n"
        f"Buyurtma tayyor bo'lganda xabar beramiz.",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )


@customer_router.callback_query(F.data == "verify_photo")
async def verify_photo_prompt(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CustomerStates.order_verification_photo)
    await callback.message.edit_text(
        "📸 Iltimos, bank/to'lov cheki rasmini yuboring:",
    )
    await callback.answer()


@customer_router.callback_query(F.data == "verify_text")
async def verify_text_prompt(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CustomerStates.order_verification_text)
    await callback.message.edit_text(
        "✍️ O'zingiz haqingizda yozing (ism, telefon, doimiy mijoz ekanligingiz va h.k.):",
    )
    await callback.answer()


@customer_router.message(CustomerStates.order_verification_photo, F.photo)
async def receive_verification_photo(message: Message, state: FSMContext, bot: Bot):
    photo_file_id = message.photo[-1].file_id
    data = await state.get_data()
    pickup_str = data.get("pending_pickup_time")
    pickup_time = datetime.fromisoformat(pickup_str) if pickup_str else datetime.now() + timedelta(hours=1)

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(
            session, message.from_user.id, message.from_user.full_name
        )
        order = await create_order_from_cart(
            session, user.id, pickup_time, needs_verification=True
        )
        if not order:
            await message.answer("Buyurtma yaratishda xato. Qaytadan urinib ko'ring.")
            return
        await set_order_verification(session, order.id, photo=photo_file_id)
        await notify_order_needs_verification(bot, session, order)
        admin_ids = await __import__('notifications').get_admin_telegram_ids(session)
        for admin_tid in admin_ids:
            try:
                await bot.send_photo(
                    admin_tid,
                    photo=photo_file_id,
                    caption=f"Buyurtma #{order.id} uchun to'lov cheki",
                )
            except Exception:
                pass

    await state.set_state(None)
    await message.answer(
        f"✅ <b>Buyurtma #{order.id} yuborildi!</b>\n\n"
        f"Admin tekshirib, tasdiqlaydi. Natija haqida xabar beramiz.\n"
        f"🔑 Pickup kodi: <code>{order.pickup_code}</code>",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )


@customer_router.message(CustomerStates.order_verification_text)
async def receive_verification_text(message: Message, state: FSMContext, bot: Bot):
    text_info = sanitize_text(message.text or "", 500)
    data = await state.get_data()
    pickup_str = data.get("pending_pickup_time")
    pickup_time = datetime.fromisoformat(pickup_str) if pickup_str else datetime.now() + timedelta(hours=1)

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(
            session, message.from_user.id, message.from_user.full_name
        )
        order = await create_order_from_cart(
            session, user.id, pickup_time, needs_verification=True
        )
        if not order:
            await message.answer("Buyurtma yaratishda xato.")
            return
        await set_order_verification(session, order.id, text=text_info)
        await notify_order_needs_verification(bot, session, order)

    await state.set_state(None)
    await message.answer(
        f"✅ <b>Buyurtma #{order.id} yuborildi!</b>\n\n"
        f"Admin tekshirib tasdiqlaydi. Xabar beramiz.\n"
        f"🔑 Pickup kodi: <code>{order.pickup_code}</code>",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )


@customer_router.message(F.text == "📦 Buyurtmalarim")
async def show_my_orders(message: Message):
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(
            session, message.from_user.id, message.from_user.full_name
        )
        orders = await get_user_orders(session, user.id)

    if not orders:
        await message.answer(
            "📦 Sizda hozircha buyurtma yo'q.",
            reply_markup=main_menu_keyboard(),
        )
        return

    builder = InlineKeyboardBuilder()
    for order in orders:
        status_text = format_order_status(order.status)
        builder.row(InlineKeyboardButton(
            text=f"#{order.id} | {format_price(order.total_amount)} | {status_text}",
            callback_data=f"my_order:{order.id}",
        ))

    await message.answer(
        "📦 <b>Buyurtmalarim:</b>",
        parse_mode="HTML",
        reply_markup=builder.as_markup(),
    )


@customer_router.callback_query(F.data.startswith("my_order:"))
async def show_order_detail(callback: CallbackQuery):
    order_id = int(callback.data.split(":")[1])
    async with AsyncSessionLocal() as session:
        order = await get_order_by_id(session, order_id)
    if not order:
        await callback.answer("Buyurtma topilmadi")
        return

    items_text = "\n".join(
        f"• {i.product_name_snapshot} x{i.quantity} — {format_price(i.subtotal)}"
        for i in order.items
    )
    status_text = format_order_status(order.status)
    text = (
        f"📦 <b>Buyurtma #{order.id}</b>\n\n"
        f"📊 Holat: {status_text}\n"
        f"💰 Jami: {format_price(order.total_amount)}\n"
        f"⏰ Olib ketish: {format_datetime(order.pickup_time) if order.pickup_time else 'Belgilanmagan'}\n"
        f"🔑 Kod: <code>{order.pickup_code}</code>\n\n"
        f"{items_text}"
    )
    if order.rejection_reason:
        text += f"\n\n❌ Sabab: {order.rejection_reason}"

    can_cancel = order.status.value in ("pending", "verification_required")
    kb = order_detail_keyboard(order.id) if can_cancel else None
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@customer_router.callback_query(F.data.startswith("order_cancel:"))
async def cancel_my_order(callback: CallbackQuery, bot: Bot):
    order_id = int(callback.data.split(":")[1])
    async with AsyncSessionLocal() as session:
        user = await get_or_create_user(
            session, callback.from_user.id, callback.from_user.full_name
        )
        order = await get_order_by_id(session, order_id)
        if not order or order.user_id != user.id:
            await callback.answer("Ruxsat yo'q!")
            return
        cancelled = await cancel_order(session, order_id)
    if cancelled:
        await callback.message.edit_text(
            f"✅ Buyurtma #{order_id} bekor qilindi.",
            reply_markup=None,
        )
        await callback.answer("Buyurtma bekor qilindi")
    else:
        await callback.answer("Bu buyurtmani bekor qilib bo'lmaydi!")