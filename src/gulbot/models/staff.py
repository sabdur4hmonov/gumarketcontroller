"""Who may decide a shop's orders (CP19). Rules: gulbot.services.shop_staff."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from gulbot.db.base import Base

#: How long a member's label may be (Telegram's first name is at most 64).
STAFF_LABEL_MAX = 64


class ShopStaff(Base):
    """One person allowed to confirm and reject this shop's orders.

    An EMPTY list for a shop means what it meant before CP19: anyone in the
    shop's group may decide. The first row switches the shop to "the list and
    the owners only". `shops` is the tenancy root, so the plain FK is the
    tenancy constraint: a row names exactly one shop.
    """

    __tablename__ = "shop_staff"

    shop_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("shops.id", ondelete="CASCADE"), primary_key=True
    )
    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    #: The name Telegram shared when the owner picked them, for the owner's
    #: own list. Never shown anywhere else.
    label: Mapped[str | None] = mapped_column(String(STAFF_LABEL_MAX), nullable=True)
    #: The owner who added them.
    added_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("telegram_id > 0", name="telegram_id_is_a_person"),
        CheckConstraint("added_by > 0", name="added_by_is_a_person"),
    )
