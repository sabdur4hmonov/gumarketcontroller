"""All models must be imported here so Alembic autogenerate sees them."""

from gulbot.models.customer import Customer, CustomerStatus
from gulbot.models.shop import Shop

__all__ = ["Customer", "CustomerStatus", "Shop"]
