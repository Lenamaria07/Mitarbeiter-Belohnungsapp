from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from database import Base

class Employee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    username = Column(String, unique=True, index=True)
    password_hash = Column(String)
    positive_score = Column(Integer, default=0)
    negative_score = Column(Integer, default=0)
    role = Column(String, default="employee")  # admin oder employee

    # Verknüpfungen
    tickets = relationship("JobTicket", back_populates="employee")
    history = relationship("MonthlyHistory", back_populates="employee", order_by="MonthlyHistory.year_month")

class JobTicket(Base):
    __tablename__ = "job_tickets"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(String, unique=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"))
    is_closed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    employee = relationship("Employee", back_populates="tickets")

# --- NEU: DATENBANK-TABELLE FÜR DIE HISTORIE ---
class MonthlyHistory(Base):
    __tablename__ = "monthly_history"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"))
    year_month = Column(String, index=True)  # Format: "YYYY-MM"
    positive_score = Column(Integer, default=0)
    negative_score = Column(Integer, default=0)
    bonus_chf = Column(Integer, default=0)

    employee = relationship("Employee", back_populates="history")