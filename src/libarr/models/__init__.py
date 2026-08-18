"""ORM models. Importing this package registers all tables on Base.metadata."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from libarr.db import Base


class Setting(Base):
    """Key/value application settings (see plan §4.2)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[str] = mapped_column(String(4096), nullable=False)


__all__ = ["Setting"]
