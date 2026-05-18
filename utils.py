import random
import string
import re
from datetime import datetime, timedelta
from typing import Optional, List
from difflib import SequenceMatcher
import logging

logger = logging.getLogger(__name__)


def generate_pickup_code(length: int = 6) -> str:
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))


def format_price(amount: float) -> str:
    return f"{amount:,.0f} so'm"


def format_datetime(dt: datetime) -> str:
    return dt.strftime("%d.%m.%Y %H:%M")


def parse_pickup_time(text: str) -> Optional[datetime]:
    text = text.strip()
    now = datetime.now()
    patterns = [
        (r'(\d{1,2}):(\d{2})', lambda m: now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)),
        (r'(\d{1,2})\.(\d{2})\.(\d{4})\s+(\d{1,2}):(\d{2})', lambda m: datetime(
            int(m.group(3)), int(m.group(2)), int(m.group(1)),
            int(m.group(4)), int(m.group(5))
        )),
    ]
    for pattern, parser in patterns:
        match = re.search(pattern, text)
        if match:
            try:
                result = parser(match)
                if result < now:
                    result += timedelta(days=1)
                return result
            except (ValueError, AttributeError):
                continue
    return None


def validate_pickup_time(dt: datetime, min_minutes: int = 30) -> tuple[bool, str]:
    now = datetime.now()
    min_time = now + timedelta(minutes=min_minutes)
    if dt <= now:
        return False, "Vaqt o'tib ketgan. Kelajakdagi vaqt kiriting."
    if dt < min_time:
        return False, f"Minimal tayyorlash vaqti {min_minutes} daqiqa. Iltimos, keyinroq vaqt tanlang."
    max_time = now + timedelta(days=7)
    if dt > max_time:
        return False, "Vaqt juda uzoq. 7 kun ichidagi vaqt kiriting."
    return True, ""


def fuzzy_match(query: str, target: str) -> float:
    query = query.lower().strip()
    target = target.lower().strip()
    if query in target:
        return 0.9
    return SequenceMatcher(None, query, target).ratio()


def extract_hashtags(text: str) -> List[str]:
    tags = re.findall(r'#(\w+)', text)
    plain = [t.strip().lower() for t in text.replace('#', ' ').split() if t.strip() and not t.startswith('#')]
    all_tags = [t.lower() for t in tags] + plain
    return list(set(all_tags))


def sanitize_text(text: str, max_length: int = 256) -> str:
    text = text.strip()
    text = re.sub(r'[<>&"\'\\]', '', text)
    return text[:max_length]


def format_order_status(status) -> str:
    status_map = {
        "pending": "⏳ Kutilmoqda",
        "verification_required": "🔍 Tekshiruv kerak",
        "confirmed": "✅ Tasdiqlangan",
        "preparing": "👨‍🍳 Tayyorlanmoqda",
        "ready": "📦 Tayyor",
        "picked_up": "✅ Olib ketildi",
        "rejected": "❌ Rad etildi",
        "expired": "⌛ Muddati o'tdi",
        "cancelled": "🚫 Bekor qilindi",
    }
    return status_map.get(str(status.value if hasattr(status, 'value') else status), str(status))


def chunks(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def is_valid_barcode(barcode: str) -> bool:
    return bool(re.match(r'^[0-9A-Za-z\-_]{4,30}$', barcode))