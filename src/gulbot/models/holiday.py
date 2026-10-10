"""Holiday campaigns (CP20): which holidays a shop runs, and the dates of the
lunar ones. Rules: gulbot.services.holiday_campaigns; the list: gulbot.holidays.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from gulbot.db.base import Base
from gulbot.holidays import HOLIDAY_KEYS_SQL, KEY_LENGTH, LUNAR_KEYS_SQL


class ShopHoliday(Base):
    """A holiday this shop runs a campaign for. Chosen by the owner in /shop;
    no row = not running it. `shops` is the tenancy root: the plain FK is the
    tenancy constraint."""

    __tablename__ = "shop_holidays"

    shop_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("shops.id", ondelete="CASCADE"), primary_key=True
    )
    holiday: Mapped[str] = mapped_column(String(KEY_LENGTH), primary_key=True)
    enabled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    #: The owner who switched it on.
    enabled_by: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (CheckConstraint(f"holiday IN ({HOLIDAY_KEYS_SQL})", name="holiday_known"),)


class HolidayDate(Base):
    """The date of a LUNAR holiday in one year, entered by the platform admin.
    Platform-wide: the calendar is the same for every shop, so no shop_id."""

    __tablename__ = "holiday_dates"

    holiday: Mapped[str] = mapped_column(String(KEY_LENGTH), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    falls_on: Mapped[date] = mapped_column(Date, nullable=False)
    set_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    #: The platform admin who entered it.
    set_by: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        CheckConstraint(f"holiday IN ({LUNAR_KEYS_SQL})", name="lunar_only"),
        CheckConstraint("EXTRACT(YEAR FROM falls_on) = year", name="date_in_its_year"),
        CheckConstraint("year BETWEEN 2020 AND 2100", name="year_range"),
    )
