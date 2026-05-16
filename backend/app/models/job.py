from sqlalchemy import (
    Column, Integer, BigInteger, String, Text, Boolean,
    DateTime, ForeignKey, Enum
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum


class WorkModelEnum(str, enum.Enum):
    on_site = "on_site"
    hybrid = "hybrid"
    remote = "remote"
    unknown = "unknown"


class Job(Base):
    """
    Vagas do LinkedIn após ETL.
    Chave para o cruzamento Discourse vs Reality.
    """
    __tablename__ = "jobs"

    id = Column(BigInteger, primary_key=True)  # ID original do LinkedIn
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)

    # Dados originais
    titulo = Column(Text)
    localizacao = Column(Text)

    # Dados enriquecidos pelo ETL
    seniority_score = Column(Integer)         # 1=junior, 2=pleno, 3=senior, 4=lead/staff
    area = Column(String(50), index=True)     # "engenharia", "produto", "dados"...
    work_model = Column(Enum(WorkModelEnum), default=WorkModelEnum.unknown, index=True)

    # Flags técnicas (do jobs_features.csv)
    has_ml = Column(Boolean, default=False)
    has_cloud = Column(Boolean, default=False)
    has_backend = Column(Boolean, default=False)
    has_data = Column(Boolean, default=False)
    has_frontend = Column(Boolean, default=False)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    company = relationship("Company", back_populates="jobs")
    skills = relationship("JobSkill", back_populates="job", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Job id={self.id} company={self.company_id} titulo={self.titulo[:40] if self.titulo else ''}>"


class JobSkill(Base):
    """Skills das vagas em formato normalizado (1 skill por linha)."""
    __tablename__ = "job_skills"

    id = Column(Integer, primary_key=True)
    job_id = Column(BigInteger, ForeignKey("jobs.id"), nullable=False, index=True)
    skill = Column(String(100), nullable=False, index=True)

    # Relationships
    job = relationship("Job", back_populates="skills")

    def __repr__(self):
        return f"<JobSkill job={self.job_id} skill={self.skill}>"