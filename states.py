from aiogram.fsm.state import State, StatesGroup


class CustomerStates(StatesGroup):
    browsing = State()
    searching = State()
    viewing_product = State()
    cart = State()
    checkout_pickup_time = State()
    order_verification_photo = State()
    order_verification_text = State()


class AdminStates(StatesGroup):
    main_menu = State()
    products_menu = State()
    add_product_name = State()
    add_product_barcode = State()
    add_product_price = State()
    add_product_discount = State()
    add_product_quantity = State()
    add_product_description = State()
    add_product_category = State()
    add_product_hashtags = State()
    add_product_image = State()
    edit_product = State()
    edit_product_field = State()
    orders_menu = State()
    order_detail = State()
    order_reject_reason = State()
    order_note = State()
    inventory_menu = State()
    add_stock = State()
    stats_menu = State()
    settings_menu = State()
    add_category = State()
    manage_users = State()
    search_order = State()
    low_stock_threshold = State()


class CashierStates(StatesGroup):
    scanning = State()
    add_missing_product = State()