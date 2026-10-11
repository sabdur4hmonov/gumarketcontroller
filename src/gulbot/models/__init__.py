"""All models must be imported here so Alembic autogenerate sees them."""

from gulbot.models.admin import AdminAuditEntry, AdminLoginLink, AdminSession
from gulbot.models.announcement import AnnouncementDraft, AnnouncementPreference
from gulbot.models.billing import SubscriptionPayment
from gulbot.models.consent import ConsentEvent, ConsentSource, ConsentType
from gulbot.models.customer import Customer, CustomerStatus
from gulbot.models.holiday import HolidayDate, ShopHoliday
from gulbot.models.message_log import MessageLog, MessageStatus
from gulbot.models.notification import (
    NotificationChannel,
    NotificationState,
    ScheduledNotification,
)
from gulbot.models.occasion import Occasion, OccasionKind, OccasionType
from gulbot.models.ops import JobRun, ShopHealthSnapshot
from gulbot.models.order import Order, OrderReminder, OrderStatus, PingState
from gulbot.models.premium import PremiumUnlock
from gulbot.models.product import (
    HashtagAlias,
    Product,
    ProductHashtag,
    ProductSource,
)
from gulbot.models.recipient import Recipient
from gulbot.models.share_page import (
    SharePage,
    SharePageOption,
    SharePagePhoto,
    SharePageReferral,
    SharePageRsvp,
    SharePageWish,
)
from gulbot.models.shop import Shop
from gulbot.models.shop_panel import ShopAuditEntry, ShopLoginLink, ShopSession
from gulbot.models.staff import ShopStaff

__all__ = [
    "AnnouncementDraft",
    "AnnouncementPreference",
    "HolidayDate",
    "ShopHoliday",
    "ShopAuditEntry",
    "ShopLoginLink",
    "ShopSession",
    "AdminAuditEntry",
    "AdminLoginLink",
    "AdminSession",
    "ConsentEvent",
    "ConsentSource",
    "ConsentType",
    "Customer",
    "CustomerStatus",
    "MessageLog",
    "MessageStatus",
    "NotificationChannel",
    "NotificationState",
    "HashtagAlias",
    "JobRun",
    "Occasion",
    "Order",
    "OrderReminder",
    "OrderStatus",
    "OccasionKind",
    "OccasionType",
    "Product",
    "ProductHashtag",
    "PingState",
    "PremiumUnlock",
    "ProductSource",
    "Recipient",
    "ScheduledNotification",
    "SharePage",
    "SharePageOption",
    "SharePagePhoto",
    "SharePageWish",
    "SharePageReferral",
    "SharePageRsvp",
    "Shop",
    "ShopHealthSnapshot",
    "ShopStaff",
    "SubscriptionPayment",
]
