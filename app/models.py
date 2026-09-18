# Modelo relacional: acá es donde cambia todo respecto a la primera
# versión de esta app. Antes teníamos una sola tabla 'elementos' con un
# campo `tipo` para distinguir tarea de meta. Ahora Meta y Tarea son dos
# ENTIDADES DISTINTAS, relacionadas entre sí:
#
#   Meta (1) ────< (N) Tarea
#
# Es decir: una meta puede tener muchas tareas, pero cada tarea pertenece
# a UNA sola meta (relación "uno a muchos", la más común en cualquier
# sistema con jerarquías: un pedido tiene muchos ítems, un post tiene
# muchos comentarios, etc.).

import enum
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .database import Base


class EstadoTarea(str, enum.Enum):
    """
    Enum de Python (que además hereda de `str`) para el campo 'estado' de
    una tarea. Con esto Python y SQLAlchemy nos obligan a que el valor sea
    SIEMPRE uno de estos dos, nunca un string libre como "hecha" o "OK".
    """

    pendiente = "pendiente"
    completado = "completado"


class Meta(Base):
    """
    Tabla 'metas': el objetivo grande (ej: "Aprender FastAPI a fondo").
    Una meta, por sí sola, no se completa "a mano": se completa SOLA
    cuando todas sus tareas quedan completadas (ver la lógica en
    main.py, ruta /tareas/{id}/completar). Por eso `fecha_completado`
    la vamos actualizando nosotros desde el backend, nunca la pisa
    directamente un formulario.
    """

    __tablename__ = "metas"

    id = Column(Integer, primary_key=True, index=True)
    titulo = Column(String, nullable=False)
    descripcion = Column(Text, nullable=True)
    fecha_creacion = Column(DateTime, default=datetime.utcnow, nullable=False)

    # nullable=True a propósito: mientras la meta tenga al menos una tarea
    # pendiente, este campo queda en None. Se llena automáticamente el
    # instante en que se completa la ÚLTIMA tarea pendiente de la meta.
    fecha_completado = Column(DateTime, nullable=True)

    # `cascade="all, delete-orphan"` significa: si algún día borráramos una
    # meta, sus tareas se borran solas con ella (no quedan tareas
    # "huérfanas" apuntando a una meta que ya no existe). `order_by` hace
    # que, cada vez que accedamos a `meta.tareas`, SQLAlchemy nos las
    # entregue ya ordenadas por fecha de creación, sin tener que acordarnos
    # de ordenarlas a mano en cada lugar del código donde las usemos.
    tareas = relationship(
        "Tarea",
        back_populates="meta",
        cascade="all, delete-orphan",
        order_by="Tarea.fecha_creacion",
    )

    # -----------------------------------------------------------------
    # Estas son "properties": atributos que en realidad son un cálculo
    # sobre `self.tareas`, no un valor guardado en su propia columna.
    # Se recalculan solas cada vez que se accede a ellas (tanto desde
    # Python como directo desde las plantillas de Jinja2), así que
    # siempre reflejan el estado más actualizado de las tareas.
    # -----------------------------------------------------------------

    @property
    def total_tareas(self) -> int:
        return len(self.tareas)

    @property
    def tareas_completadas(self) -> int:
        return sum(1 for t in self.tareas if t.estado == EstadoTarea.completado)

    @property
    def progreso_porcentaje(self) -> int:
        """
        El famoso "porcentaje de cuánto le falta a cada meta". Ojo con la
        división por cero: una meta recién creada, sin tareas todavía,
        tiene total_tareas == 0, así que devolvemos 0% directamente en vez
        de romper con un ZeroDivisionError.
        """
        if self.total_tareas == 0:
            return 0
        return round(self.tareas_completadas / self.total_tareas * 100)

    @property
    def esta_completada(self) -> bool:
        # Usamos fecha_completado (no un recálculo de porcentaje) como la
        # fuente de verdad de "¿esta meta ya está lograda?", porque es el
        # mismo campo que actualizamos a mano en el backend cada vez que
        # el progreso cambia. Mantenerlo sincronizado ahí es más simple
        # que recalcularlo en cada lugar donde preguntamos "¿está completa?".
        return self.fecha_completado is not None


class Tarea(Base):
    """Tabla 'tareas': cada paso concreto y accionable dentro de una meta."""

    __tablename__ = "tareas"

    id = Column(Integer, primary_key=True, index=True)
    titulo = Column(String, nullable=False)
    descripcion = Column(Text, nullable=True)
    estado = Column(Enum(EstadoTarea), nullable=False, default=EstadoTarea.pendiente)
    fecha_creacion = Column(DateTime, default=datetime.utcnow, nullable=False)
    fecha_completado = Column(DateTime, nullable=True)

    # Acá está la clave de la relación: cada tarea guarda el id de SU meta.
    # `nullable=False` porque, en este diseño, toda tarea pertenece
    # obligatoriamente a una meta (no existen tareas "sueltas").
    meta_id = Column(Integer, ForeignKey("metas.id"), nullable=False)

    meta = relationship("Meta", back_populates="tareas")
