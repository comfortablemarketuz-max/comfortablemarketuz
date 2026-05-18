from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
    ReplyKeyboardRemove, WebAppInfo
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from typing import List, Optional
from models import Product, Order, OrderStatus, Category
from config import WEBAPP_URL


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text="🔍 Qidirish"),
        KeyboardButton(text="🛒 Savat"),
    )
    builder.row(
        KeyboardButton(text="📦 Buyurtmalarim"),
        KeyboardButton(text="🏷️ Aksiyalar"),
    )
    return builder.as_markup(resize_keyboard=True)


def search_mode_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="❌ Qidiruvni yopish"))
    return builder.as_markup(resize_keyboard=True)


def product_nav_keyboard(
    product_id: int,
    current_index: int,
    total: int,
    in_cart: bool = False,
    cart_qty: int = 0
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    nav_row = []
    if current_index > 0:
        nav_row.append(InlineKeyboardButton(
            text="◀️", callback_data=f"prod_nav:{current_index - 1}"
        ))
    nav_row.append(InlineKeyboardButton(
        text=f"{current_index + 1}/{total}", callback_data="noop"
    ))
    if current_index < total - 1:
        nav_row.append(InlineKeyboardButton(
            text="▶️", callback_data=f"prod_nav:{current_index + 1}"
        ))
    builder.row(*nav_row)

    if in_cart and cart_qty > 0:
        builder.row(
            InlineKeyboardButton(text="➖", callback_data=f"cart_dec:{product_id}"),
            InlineKeyboardButton(text=f"🛒 {cart_qty} ta", callback_data=f"cart_info:{product_id}"),
            InlineKeyboardButton(text="➕", callback_data=f"cart_inc:{product_id}"),
        )
        builder.row(InlineKeyboardButton(
            text="🗑 Savatdan olib tashlash", callback_data=f"cart_remove:{product_id}"
        ))
    else:
        builder.row(InlineKeyboardButton(
            text="🛒 Savatga qo'shish", callback_data=f"cart_add:{product_id}"
        ))
    return builder.as_markup()


def cart_keyboard(has_items: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if has_items:
        builder.row(InlineKeyboardButton(
            text="✅ Buyurtma berish", callback_data="checkout"
        ))
        builder.row(InlineKeyboardButton(
            text="🗑 Savatni tozalash", callback_data="cart_clear"
        ))
    builder.row(InlineKeyboardButton(
        text="🔍 Xarid qilishni davom ettirish", callback_data="continue_shopping"
    ))
    return builder.as_markup()


def pickup_time_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="30 daqiqa", callback_data="pickup:30"),
        InlineKeyboardButton(text="1 soat", callback_data="pickup:60"),
    )
    builder.row(
        InlineKeyboardButton(text="2 soat", callback_data="pickup:120"),
        InlineKeyboardButton(text="3 soat", callback_data="pickup:180"),
    )
    builder.row(InlineKeyboardButton(
        text="📝 Vaqtni o'zim kiritaman", callback_data="pickup:custom"
    ))
    builder.row(InlineKeyboardButton(
        text="⬅️ Orqaga", callback_data="back_to_cart"
    ))
    return builder.as_markup()


def order_verification_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="📸 Chek rasmini yuborish", callback_data="verify_photo"
    ))
    builder.row(InlineKeyboardButton(
        text="✍️ O'zim haqimda yozaman", callback_data="verify_text"
    ))
    builder.row(InlineKeyboardButton(
        text="⬅️ Bekor qilish", callback_data="cancel_checkout"
    ))
    return builder.as_markup()


def order_detail_keyboard(order_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="❌ Bekor qilish", callback_data=f"order_cancel:{order_id}"
    ))
    return builder.as_markup()


def admin_main_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text="📊 Dashboard"),
        KeyboardButton(text="📦 Mahsulotlar"),
    )
    builder.row(
        KeyboardButton(text="🛒 Zakazlar"),
        KeyboardButton(text="🏭 Ombor"),
    )
    builder.row(
        KeyboardButton(text="📈 Statistika"),
        KeyboardButton(text="⚙️ Sozlamalar"),
    )
    builder.row(
        KeyboardButton(
            text="🔬 Kassa Scanner",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )
    )
    builder.row(KeyboardButton(text="🏠 Bosh menyu"))
    return builder.as_markup(resize_keyboard=True)


def admin_products_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="➕ Manual qo'shish", callback_data="admin_add_product_manual"
    ))
    builder.row(InlineKeyboardButton(
        text="📋 Mahsulotlar ro'yxati", callback_data="admin_list_products:0"
    ))
    builder.row(InlineKeyboardButton(
        text="🏷️ Kategoriyalar", callback_data="admin_categories"
    ))
    builder.row(InlineKeyboardButton(
        text="⬅️ Orqaga", callback_data="admin_back_main"
    ))
    return builder.as_markup()


def admin_order_keyboard(order_id: int, status: OrderStatus) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if status == OrderStatus.pending:
        builder.row(
            InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"admin_order_confirm:{order_id}"),
            InlineKeyboardButton(text="❌ Rad etish", callback_data=f"admin_order_reject:{order_id}"),
        )
    elif status == OrderStatus.verification_required:
        builder.row(
            InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"admin_order_confirm:{order_id}"),
            InlineKeyboardButton(text="❌ Rad etish", callback_data=f"admin_order_reject:{order_id}"),
        )
    elif status == OrderStatus.confirmed:
        builder.row(InlineKeyboardButton(
            text="👨‍🍳 Tayyorlanmoqda", callback_data=f"admin_order_preparing:{order_id}"
        ))
    elif status == OrderStatus.preparing:
        builder.row(InlineKeyboardButton(
            text="✅ Tayyor", callback_data=f"admin_order_ready:{order_id}"
        ))
    builder.row(InlineKeyboardButton(
        text="📝 Nota qo'shish", callback_data=f"admin_order_note:{order_id}"
    ))
    builder.row(InlineKeyboardButton(
        text="⬅️ Orqaga", callback_data="admin_orders_back"
    ))
    return builder.as_markup()


def admin_orders_filter_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⏳ Kutayotgan", callback_data="admin_orders_filter:pending"),
        InlineKeyboardButton(text="🔍 Tekshiruv", callback_data="admin_orders_filter:verification_required"),
    )
    builder.row(
        InlineKeyboardButton(text="✅ Tasdiqlangan", callback_data="admin_orders_filter:confirmed"),
        InlineKeyboardButton(text="👨‍🍳 Tayyorlanmoqda", callback_data="admin_orders_filter:preparing"),
    )
    builder.row(
        InlineKeyboardButton(text="📦 Tayyor", callback_data="admin_orders_filter:ready"),
        InlineKeyboardButton(text="✅ Olib ketilgan", callback_data="admin_orders_filter:picked_up"),
    )
    builder.row(
        InlineKeyboardButton(text="❌ Rad etilgan", callback_data="admin_orders_filter:rejected"),
        InlineKeyboardButton(text="📋 Hammasi", callback_data="admin_orders_filter:all"),
    )
    return builder.as_markup()


def product_edit_keyboard(product_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    fields = [
        ("📝 Nom", "name"), ("💰 Narx", "price"),
        ("🏷️ Aksiya narxi", "discount"), ("📦 Miqdor", "quantity"),
        ("📄 Tavsif", "description"), ("🖼 Rasm", "image"),
        ("🔖 Hashtaglar", "hashtags"), ("📁 Kategoriya", "category"),
    ]
    for label, field in fields:
        builder.row(InlineKeyboardButton(
            text=label, callback_data=f"admin_edit_field:{product_id}:{field}"
        ))
    builder.row(InlineKeyboardButton(
        text="🗑 O'chirish", callback_data=f"admin_delete_product:{product_id}"
    ))
    builder.row(InlineKeyboardButton(
        text="⬅️ Orqaga", callback_data="admin_list_products:0"
    ))
    return builder.as_markup()


def products_list_keyboard(
    products: list,
    page: int,
    total_pages: int
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for p in products:
        stock_icon = "✅" if p.is_in_stock else "❌"
        sale_icon = "🏷️" if p.has_discount else ""
        builder.row(InlineKeyboardButton(
            text=f"{stock_icon} {sale_icon} {p.name[:30]} | {p.effective_price:,.0f} so'm",
            callback_data=f"admin_view_product:{p.id}"
        ))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"admin_list_products:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"admin_list_products:{page + 1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="⬅️ Orqaga", callback_data="admin_products_back"))
    return builder.as_markup()


def cashier_scanner_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(
            text="📷 Scanner ochish",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )
    )
    builder.row(KeyboardButton(text="📊 Bugungi savdo"))
    builder.row(KeyboardButton(text="🏠 Bosh menyu"))
    return builder.as_markup(resize_keyboard=True)


def remove_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


def cancel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel"))
    return builder.as_markup()


def confirm_keyboard(action: str, item_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Ha", callback_data=f"{action}:yes:{item_id}"),
        InlineKeyboardButton(text="❌ Yo'q", callback_data=f"{action}:no:{item_id}"),
    )
    return builder.as_markup()