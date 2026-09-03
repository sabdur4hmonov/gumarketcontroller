"""All models must be imported here so Alembic autogenerate sees them."""

from gulbot.models.consent import ConsentEvent, ConsentSource, ConsentType
from gulbot.models.customer import Customer, CustomerStatus
from gulbot.models.occasion import Occasion, OccasionType
from gulbot.models.recipient import Recipient
from gulbot.models.shop import Shop

__all__ = [
    "ConsentEvent",
    "ConsentSource",
    "ConsentType",
    "Customer",
    "CustomerStatus",
    "Occasion",
    "OccasionType",
    "Recipient",
    "Shop",
]
