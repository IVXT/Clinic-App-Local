from __future__ import annotations

import datetime as dt
from typing import List, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from clinic_app.extensions import db


class Base(DeclarativeBase):
    """Declarative base for clinic domain models."""


class QueryMixin:
    """Provide a Flask-SQLAlchemy-style query attribute."""

    @classmethod
    def query(cls):  # type: ignore[override]
        return db.session().query(cls)


class Patient(QueryMixin, Base):
    __tablename__ = "patients"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    short_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)

    appointments: Mapped[List["Appointment"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan"
    )


class Doctor(QueryMixin, Base):
    __tablename__ = "doctors"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    doctor_label: Mapped[str] = mapped_column(Text, nullable=False)
    color: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    appointments: Mapped[List["Appointment"]] = relationship(back_populates="doctor")


class Appointment(QueryMixin, Base):
    __tablename__ = "appointments"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    patient_id: Mapped[Optional[str]] = mapped_column(
        Text, ForeignKey("patients.id", ondelete="SET NULL"), nullable=True
    )
    patient_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    patient_phone: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    doctor_id: Mapped[str] = mapped_column(Text, ForeignKey("doctors.id"), nullable=False)
    doctor_label: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    start_time: Mapped[dt.datetime] = mapped_column("starts_at", DateTime, nullable=False)
    end_time: Mapped[dt.datetime] = mapped_column("ends_at", DateTime, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="scheduled")
    color: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    room: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reminder_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)

    patient: Mapped[Optional[Patient]] = relationship(Patient, back_populates="appointments")
    doctor: Mapped[Optional[Doctor]] = relationship(Doctor, back_populates="appointments")
