from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Company(Base):
    """
    Entidade central do sistema. Adicionar nova empresa = INSERT, não código.
    target_company = True marca qual é a empresa "dona" da análise (C6 Bank).
    """
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True)
    slug = Column(String(50), unique=True, nullable=False)      # "c6_bank", "nubank"
    name = Column(String(100), nullable=False)                   # "C6 Bank", "Nubank"
    display_name = Column(String(100))                           # Para o frontend
    segment = Column(String(50))                                 # "fintech", "big_bank"
    country = Column(String(10), default="BR")
    is_target = Column(Boolean, default=False)                   # True = C6 Bank (empresa-cliente)
    is_active = Column(Boolean, default=True)
    logo_url = Column(Text)
    glassdoor_url = Column(Text)
    linkedin_url = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    reviews = relationship("Review", back_populates="company")
    jobs = relationship("Job", back_populates="company")
    events = relationship("CompanyEvent", back_populates="company")
    dimension_stats = relationship("CompanyDimensionStats", back_populates="company")
    insights_as_target = relationship(
        "Insight", foreign_keys="Insight.target_company_id", back_populates="target_company"
    )
    insights_as_compared = relationship(
        "Insight", foreign_keys="Insight.compared_company_id", back_populates="compared_company"
    )

    def __repr__(self):
        return f"<Company {self.slug}>"