import logging
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, desc, update, delete
from sqlalchemy.orm import selectinload

from models import (
    User, UserRole, Category, Product, ProductTag, Cart, CartItem,
    Order, OrderItem, OrderStatus, Sale, SaleItem, InventoryLog,
    AdminAction, Notification, PickupCode, Setting, AuditLog
)
from utils import generate_pickup_code, fuzzy_match
from config import LOW_STOCK_THRESHOLD

logger = logging.getLogger(__name__)

PAGE_SIZE = 10


# ─── USER SERVICES ────────────────────────────────────────────────────────────

async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    full_name: str,
    username: Optional[str] = None,
    role: UserRole = UserRole.customer,
) -> User:
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    user = result.scalar_one_or_none()
    if user:
        user.full_name = full_name
        user.username = username
        await session.commit()
        return user
    user = User(
        telegram_id=telegram_id,
        full_name=full_name,
        username=username,
        role=role,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def get_user_by_telegram_id(session: AsyncSession, telegram_id: int) -> Optional[User]:
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    return result.scalar_one_or_none()


async def update_user_role(session: AsyncSession, user_id: int, role: UserRole) -> None:
    await session.execute(
        update(User).where(User.id == user_id).values(role=role)
    )
    await session.commit()


async def set_user_search_mode(session: AsyncSession, telegram_id: int, mode: bool) -> None:
    await session.execute(
        update(User).where(User.telegram_id == telegram_id).values(search_mode=mode)
    )
    await session.commit()


async def set_user_trusted(session: AsyncSession, user_id: int, trusted: bool) -> None:
    await session.execute(
        update(User).where(User.id == user_id).values(is_trusted=trusted)
    )
    await session.commit()


# ─── CATEGORY SERVICES ────────────────────────────────────────────────────────

async def get_all_categories(session: AsyncSession) -> List[Category]:
    result = await session.execute(
        select(Category).where(Category.is_active == True).order_by(Category.name)
    )
    return list(result.scalars().all())


async def create_category(session: AsyncSession, name: str, emoji: str = "") -> Category:
    cat = Category(name=name, emoji=emoji)
    session.add(cat)
    await session.commit()
    await session.refresh(cat)
    return cat


# ─── PRODUCT SERVICES ─────────────────────────────────────────────────────────

async def create_product(
    session: AsyncSession,
    name: str,
    price: float,
    quantity: int = 0,
    barcode: Optional[str] = None,
    description: Optional[str] = None,
    discount_price: Optional[float] = None,
    category_id: Optional[int] = None,
    image_file_id: Optional[str] = None,
    hashtags: Optional[List[str]] = None,
) -> Product:
    product = Product(
        name=name,
        price=price,
        quantity=quantity,
        barcode=barcode,
        description=description,
        discount_price=discount_price,
        category_id=category_id,
        image_file_id=image_file_id,
    )
    session.add(product)
    await session.flush()
    if hashtags:
        for tag in hashtags:
            tag = tag.strip().lower()
            if tag:
                session.add(ProductTag(product_id=product.id, tag=tag))
    await session.commit()
    await session.refresh(product)
    return product


async def update_product(session: AsyncSession, product_id: int, **kwargs) -> Optional[Product]:
    if 'hashtags' in kwargs:
        hashtags = kwargs.pop('hashtags')
        await session.execute(
            delete(ProductTag).where(ProductTag.product_id == product_id)
        )
        for tag in hashtags:
            tag = tag.strip().lower()
            if tag:
                session.add(ProductTag(product_id=product_id, tag=tag))
    if kwargs:
        await session.execute(
            update(Product).where(Product.id == product_id).values(**kwargs)
        )
    await session.commit()
    return await get_product_by_id(session, product_id)


async def get_product_by_id(session: AsyncSession, product_id: int) -> Optional[Product]:
    result = await session.execute(
        select(Product)
        .options(selectinload(Product.tags), selectinload(Product.category))
        .where(Product.id == product_id)
    )
    return result.scalar_one_or_none()


async def get_product_by_barcode(session: AsyncSession, barcode: str) -> Optional[Product]:
    result = await session.execute(
        select(Product)
        .options(selectinload(Product.tags))
        .where(Product.barcode == barcode)
    )
    return result.scalar_one_or_none()


async def search_products(
    session: AsyncSession,
    query: str,
    for_customer: bool = True,
    include_out_of_stock: bool = False,
) -> List[Product]:
    q = query.lower().strip()
    conditions = [Product.is_active == True]
    if for_customer and not include_out_of_stock:
        conditions.append(Product.quantity > 0)

    result = await session.execute(
        select(Product)
        .options(selectinload(Product.tags), selectinload(Product.category))
        .where(and_(*conditions))
    )
    products = list(result.scalars().all())

    scored = []
    for p in products:
        score = 0.0
        name_lower = p.name.lower()
        if q == name_lower:
            score = 1.0
        elif q in name_lower:
            score = 0.85
        else:
            name_score = fuzzy_match(q, p.name)
            if name_score > 0.5:
                score = name_score
        if score == 0.0:
            for tag in p.tags:
                if q in tag.tag or fuzzy_match(q, tag.tag) > 0.7:
                    score = max(score, 0.7)
                    break
        if score > 0.3:
            scored.append((score, p))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scored]


async def get_discounted_products(session: AsyncSession) -> List[Product]:
    result = await session.execute(
        select(Product)
        .options(selectinload(Product.tags))
        .where(
            and_(
                Product.is_active == True,
                Product.quantity > 0,
                Product.discount_price > 0,
                Product.discount_price < Product.price,
            )
        )
        .order_by(Product.name)
    )
    return list(result.scalars().all())


async def get_all_products_admin(
    session: AsyncSession,
    page: int = 0,
) -> Tuple[List[Product], int]:
    count_result = await session.execute(
        select(func.count()).where(Product.is_active == True)
    )
    total = count_result.scalar() or 0
    result = await session.execute(
        select(Product)
        .options(selectinload(Product.tags), selectinload(Product.category))
        .where(Product.is_active == True)
        .order_by(Product.name)
        .offset(page * PAGE_SIZE)
        .limit(PAGE_SIZE)
    )
    return list(result.scalars().all()), total


async def delete_product(session: AsyncSession, product_id: int) -> None:
    await session.execute(
        update(Product).where(Product.id == product_id).values(is_active=False)
    )
    await session.commit()


async def adjust_product_quantity(
    session: AsyncSession,
    product_id: int,
    change: int,
    reason: str,
    actor_id: Optional[int] = None,
) -> None:
    product = await get_product_by_id(session, product_id)
    if product:
        new_qty = max(0, product.quantity + change)
        await session.execute(
            update(Product).where(Product.id == product_id).values(quantity=new_qty)
        )
        session.add(InventoryLog(
            product_id=product_id,
            change=change,
            reason=reason,
            actor_id=actor_id,
        ))
        await session.commit()


async def get_low_stock_products(session: AsyncSession, threshold: int = None) -> List[Product]:
    if threshold is None:
        threshold = LOW_STOCK_THRESHOLD
    result = await session.execute(
        select(Product)
        .where(
            and_(
                Product.is_active == True,
                Product.quantity > 0,
                Product.quantity <= threshold,
            )
        )
        .order_by(Product.quantity)
    )
    return list(result.scalars().all())


async def get_out_of_stock_products(session: AsyncSession) -> List[Product]:
    result = await session.execute(
        select(Product)
        .where(and_(Product.is_active == True, Product.quantity == 0))
        .order_by(Product.name)
    )
    return list(result.scalars().all())


# ─── CART SERVICES ────────────────────────────────────────────────────────────

async def get_or_create_cart(session: AsyncSession, user_id: int) -> Cart:
    result = await session.execute(
        select(Cart)
        .options(selectinload(Cart.items).selectinload(CartItem.product))
        .where(Cart.user_id == user_id)
    )
    cart = result.scalar_one_or_none()
    if not cart:
        cart = Cart(user_id=user_id)
        session.add(cart)
        await session.commit()
        await session.refresh(cart)
    return cart


async def add_to_cart(
    session: AsyncSession,
    user_id: int,
    product_id: int,
    quantity: int = 1,
) -> Tuple[bool, str]:
    product = await get_product_by_id(session, product_id)
    if not product:
        return False, "Mahsulot topilmadi."
    if not product.is_in_stock:
        return False, "Mahsulot omborda yo'q."

    cart = await get_or_create_cart(session, user_id)
    result = await session.execute(
        select(CartItem).where(
            and_(CartItem.cart_id == cart.id, CartItem.product_id == product_id)
        )
    )
    item = result.scalar_one_or_none()
    if item:
        new_qty = item.quantity + quantity
        if new_qty > product.quantity:
            return False, f"Omborda faqat {product.quantity} ta mavjud."
        item.quantity = new_qty
        item.price_snapshot = product.effective_price
    else:
        session.add(CartItem(
            cart_id=cart.id,
            product_id=product_id,
            quantity=quantity,
            price_snapshot=product.effective_price,
        ))
    await session.commit()
    return True, "Savatga qo'shildi ✅"


async def remove_from_cart(
    session: AsyncSession,
    user_id: int,
    product_id: int,
) -> None:
    cart = await get_or_create_cart(session, user_id)
    await session.execute(
        delete(CartItem).where(
            and_(CartItem.cart_id == cart.id, CartItem.product_id == product_id)
        )
    )
    await session.commit()


async def update_cart_item_qty(
    session: AsyncSession,
    user_id: int,
    product_id: int,
    delta: int,
) -> Tuple[bool, int]:
    product = await get_product_by_id(session, product_id)
    if not product:
        return False, 0
    cart = await get_or_create_cart(session, user_id)
    result = await session.execute(
        select(CartItem).where(
            and_(CartItem.cart_id == cart.id, CartItem.product_id == product_id)
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        return False, 0
    new_qty = item.quantity + delta
    if new_qty <= 0:
        await session.delete(item)
        await session.commit()
        return True, 0
    if new_qty > product.quantity:
        return False, item.quantity
    item.quantity = new_qty
    await session.commit()
    return True, new_qty


async def clear_cart(session: AsyncSession, user_id: int) -> None:
    cart = await get_or_create_cart(session, user_id)
    await session.execute(
        delete(CartItem).where(CartItem.cart_id == cart.id)
    )
    await session.commit()


async def get_cart_with_items(session: AsyncSession, user_id: int) -> Cart:
    result = await session.execute(
        select(Cart)
        .options(selectinload(Cart.items).selectinload(CartItem.product))
        .where(Cart.user_id == user_id)
    )
    cart = result.scalar_one_or_none()
    if not cart:
        cart = Cart(user_id=user_id)
        session.add(cart)
        await session.commit()
        await session.refresh(cart)
        cart.items = []
    return cart


# ─── ORDER SERVICES ───────────────────────────────────────────────────────────

async def create_order_from_cart(
    session: AsyncSession,
    user_id: int,
    pickup_time: datetime,
    needs_verification: bool = False,
) -> Optional[Order]:
    cart = await get_cart_with_items(session, user_id)
    if not cart.items:
        return None

    total = sum(i.price_snapshot * i.quantity for i in cart.items)
    status = OrderStatus.verification_required if needs_verification else OrderStatus.pending
    code = generate_pickup_code()

    order = Order(
        user_id=user_id,
        status=status,
        total_amount=total,
        pickup_time=pickup_time,
        pickup_code=code,
    )
    session.add(order)
    await session.flush()

    for item in cart.items:
        product = item.product
        session.add(OrderItem(
            order_id=order.id,
            product_id=item.product_id,
            quantity=item.quantity,
            price_snapshot=item.price_snapshot,
            product_name_snapshot=product.name if product else "Noma'lum",
        ))
        if product:
            await adjust_product_quantity(
                session, item.product_id, -item.quantity, "order_reserved", user_id
            )

    session.add(PickupCode(order_id=order.id, code=code))
    await session.execute(
        delete(CartItem).where(CartItem.cart_id == cart.id)
    )
    await session.commit()
    await session.refresh(order)
    return order


async def get_order_by_id(session: AsyncSession, order_id: int) -> Optional[Order]:
    result = await session.execute(
        select(Order)
        .options(
            selectinload(Order.items),
            selectinload(Order.user),
        )
        .where(Order.id == order_id)
    )
    return result.scalar_one_or_none()


async def get_user_orders(
    session: AsyncSession,
    user_id: int,
    limit: int = 10,
) -> List[Order]:
    result = await session.execute(
        select(Order)
        .options(selectinload(Order.items))
        .where(Order.user_id == user_id)
        .order_by(desc(Order.created_at))
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_orders_by_status(
    session: AsyncSession,
    status: Optional[OrderStatus] = None,
    limit: int = 50,
) -> List[Order]:
    query = select(Order).options(
        selectinload(Order.items),
        selectinload(Order.user),
    )
    if status:
        query = query.where(Order.status == status)
    query = query.order_by(desc(Order.created_at)).limit(limit)
    result = await session.execute(query)
    return list(result.scalars().all())


async def update_order_status(
    session: AsyncSession,
    order_id: int,
    status: OrderStatus,
    rejection_reason: Optional[str] = None,
    admin_note: Optional[str] = None,
    verified_by: Optional[int] = None,
) -> Optional[Order]:
    values: dict = {"status": status}
    if rejection_reason:
        values["rejection_reason"] = rejection_reason
    if admin_note:
        values["admin_note"] = admin_note
    if verified_by:
        values["verified_by"] = verified_by
    await session.execute(
        update(Order).where(Order.id == order_id).values(**values)
    )
    await session.commit()
    return await get_order_by_id(session, order_id)


async def set_order_verification(
    session: AsyncSession,
    order_id: int,
    photo: Optional[str] = None,
    text: Optional[str] = None,
) -> None:
    values = {}
    if photo:
        values["verification_photo"] = photo
    if text:
        values["verification_text"] = text
    if values:
        await session.execute(
            update(Order).where(Order.id == order_id).values(**values)
        )
        await session.commit()


async def cancel_order(
    session: AsyncSession,
    order_id: int,
    reason: str = "Mijoz tomonidan bekor qilindi",
) -> Optional[Order]:
    order = await get_order_by_id(session, order_id)
    if not order:
        return None
    if order.status not in (OrderStatus.pending, OrderStatus.verification_required):
        return None
    for item in order.items:
        await adjust_product_quantity(
            session, item.product_id, item.quantity, "order_cancelled"
        )
    await session.execute(
        update(Order).where(Order.id == order_id).values(
            status=OrderStatus.cancelled,
            rejection_reason=reason,
        )
    )
    await session.commit()
    return await get_order_by_id(session, order_id)


# ─── SALE SERVICES ────────────────────────────────────────────────────────────

async def create_sale(
    session: AsyncSession,
    cashier_id: int,
    items: List[dict],
) -> Sale:
    total = sum(i["price"] * i["quantity"] for i in items)
    sale = Sale(cashier_id=cashier_id, total_amount=total)
    session.add(sale)
    await session.flush()
    for i in items:
        session.add(SaleItem(
            sale_id=sale.id,
            product_id=i["product_id"],
            quantity=i["quantity"],
            price_snapshot=i["price"],
            product_name_snapshot=i["name"],
        ))
        await adjust_product_quantity(
            session, i["product_id"], -i["quantity"], "sale", cashier_id
        )
    await session.commit()
    await session.refresh(sale)
    return sale


# ─── STATISTICS SERVICES ──────────────────────────────────────────────────────

async def get_today_stats(session: AsyncSession) -> dict:
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = today + timedelta(days=1)

    sales_result = await session.execute(
        select(func.count(), func.sum(Sale.total_amount))
        .where(Sale.created_at >= today, Sale.created_at < tomorrow)
    )
    sales_count, sales_total = sales_result.one()

    orders_result = await session.execute(
        select(func.count(), func.sum(Order.total_amount))
        .where(
            Order.created_at >= today,
            Order.created_at < tomorrow,
            Order.status == OrderStatus.picked_up,
        )
    )
    orders_count, orders_total = orders_result.one()

    pending_result = await session.execute(
        select(func.count()).where(
            Order.status.in_([OrderStatus.pending, OrderStatus.verification_required])
        )
    )
    pending_count = pending_result.scalar() or 0

    return {
        "sales_count": sales_count or 0,
        "sales_total": sales_total or 0,
        "orders_count": orders_count or 0,
        "orders_total": orders_total or 0,
        "pending_orders": pending_count,
        "date": today.strftime("%d.%m.%Y"),
    }


async def get_top_products(session: AsyncSession, limit: int = 5) -> List[dict]:
    result = await session.execute(
        select(
            SaleItem.product_name_snapshot,
            func.sum(SaleItem.quantity).label("total_qty"),
            func.sum(SaleItem.price_snapshot * SaleItem.quantity).label("total_sum"),
        )
        .group_by(SaleItem.product_name_snapshot)
        .order_by(desc("total_qty"))
        .limit(limit)
    )
    return [{"name": r[0], "qty": r[1], "total": r[2]} for r in result.all()]


async def get_hourly_sales(session: AsyncSession) -> List[dict]:
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = today + timedelta(days=1)
    result = await session.execute(
        select(Sale.total_amount, Sale.created_at)
        .where(Sale.created_at >= today, Sale.created_at < tomorrow)
        .order_by(Sale.created_at)
    )
    rows = result.all()
    hourly: dict = {}
    for amount, created in rows:
        hour = created.hour
        hourly[hour] = hourly.get(hour, 0) + (amount or 0)
    return [{"hour": h, "total": t} for h, t in sorted(hourly.items())]


async def get_weekly_stats(session: AsyncSession) -> List[dict]:
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    weekly = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        next_day = day + timedelta(days=1)
        result = await session.execute(
            select(func.sum(Sale.total_amount))
            .where(Sale.created_at >= day, Sale.created_at < next_day)
        )
        total = result.scalar() or 0
        weekly.append({"date": day.strftime("%d.%m"), "total": total})
    return weekly


async def get_cashier_stats(session: AsyncSession) -> List[dict]:
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = today + timedelta(days=1)
    result = await session.execute(
        select(
            User.full_name,
            func.count(Sale.id).label("sales"),
            func.sum(Sale.total_amount).label("total"),
        )
        .join(User, Sale.cashier_id == User.id)
        .where(Sale.created_at >= today, Sale.created_at < tomorrow)
        .group_by(User.full_name)
        .order_by(desc("total"))
    )
    return [{"name": r[0], "sales": r[1], "total": r[2]} for r in result.all()]


# ─── NOTIFICATION SERVICES ────────────────────────────────────────────────────

async def save_notification(
    session: AsyncSession,
    recipient_id: int,
    message: str,
) -> None:
    session.add(Notification(recipient_id=recipient_id, message=message))
    await session.commit()


# ─── SETTINGS ─────────────────────────────────────────────────────────────────

async def get_setting(session: AsyncSession, key: str, default: str = "") -> str:
    result = await session.execute(
        select(Setting).where(Setting.key == key)
    )
    s = result.scalar_one_or_none()
    return s.value if s else default


async def set_setting(session: AsyncSession, key: str, value: str) -> None:
    result = await session.execute(
        select(Setting).where(Setting.key == key)
    )
    s = result.scalar_one_or_none()
    if s:
        s.value = value
    else:
        session.add(Setting(key=key, value=value))
    await session.commit()