from models import UserRole
from config import OWNER_IDS, ADMIN_IDS

ROLE_PERMISSIONS = {
    UserRole.owner: {
        "manage_admins", "manage_products", "manage_orders",
        "manage_inventory", "view_stats", "manage_settings",
        "manage_cashiers", "manage_categories", "view_all_orders",
        "approve_orders", "reject_orders", "access_admin_panel",
        "access_cashier", "delete_products", "manage_roles",
        "export_data",
    },
    UserRole.admin: {
        "manage_products", "manage_orders", "manage_inventory",
        "view_stats", "manage_categories", "view_all_orders",
        "approve_orders", "reject_orders", "access_admin_panel",
        "delete_products",
    },
    UserRole.cashier: {
        "access_cashier", "view_own_sales",
    },
    UserRole.warehouse: {
        "manage_inventory", "view_products",
    },
    UserRole.customer: {
        "view_products", "manage_own_cart", "manage_own_orders",
    },
}


def has_permission(role: UserRole, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, set())


def is_admin_or_higher(role: UserRole) -> bool:
    return role in (UserRole.owner, UserRole.admin)


def is_staff(role: UserRole) -> bool:
    return role in (UserRole.owner, UserRole.admin, UserRole.cashier, UserRole.warehouse)


def get_role_for_telegram_id(telegram_id: int) -> UserRole:
    if telegram_id in OWNER_IDS:
        return UserRole.owner
    if telegram_id in ADMIN_IDS:
        return UserRole.admin
    return UserRole.customer