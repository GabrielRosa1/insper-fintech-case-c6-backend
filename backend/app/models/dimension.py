from sqlalchemy import Column, Integer, String, Text, Boolean
from sqlalchemy.orm import relationship
from app.database import Base


class Dimension(Base):
    """
    Dimensões de análise como entidade — adicionar nova dimensão = INSERT, não ALTER TABLE.
    Exemplos: lideranca, presencial, salario_beneficios, cultura, crescimento,
              saude_mental, diversidade, proposito, tech_stack
    """
    __tablename__ = "dimensions"

    id = Column(Integer, primary_key=True)
    slug = Column(String(50), unique=True, nullable=False)       # "lideranca"
    name = Column(String(100), nullable=False)                   # "Liderança"
    description = Column(Text)                                   # Para o prompt da IA
    icon = Column(String(50))                                    # Para o frontend
    display_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    is_core = Column(Boolean, default=True)  # False = dimensão experimental

    # Relationships
    review_dimensions = relationship("ReviewDimension", back_populates="dimension")
    stats = relationship("CompanyDimensionStats", back_populates="dimension")

    def __repr__(self):
        return f"<Dimension {self.slug}>"