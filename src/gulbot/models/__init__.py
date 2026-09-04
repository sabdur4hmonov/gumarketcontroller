"""All models must be imported here so Alembic autogenerate sees them."""

from gulbot.models.consent import ConsentEvent, ConsentSource, ConsentType
from gulbot.models.customer import Customer, CustomerStatus
from gulbot.models.message_log import MessageLog, MessageStatus
from gulbot.models.notification import (
    NotificationChannel,
    NotificationState,
    ScheduledNotification,
)
from gulbot.models.occasion import Occasion, OccasionKind, OccasionType
from gulbot.models.product import (
    HashtagAlias,
    Product,
    ProductHashtag,
    ProductSource,
)
from gulbot.models.recipient import Recipient
from gulbot.models.shop import Shop

__all__ = [
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
    "Occasion",
    "OccasionKind",
    "OccasionType",
    "Product",
    "ProductHashtag",
    "ProductSource",
    "Recipient",
    "ScheduledNotification",
    "Shop",
]
