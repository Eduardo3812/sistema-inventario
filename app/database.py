# Configuración de la base de datos: motor de conexión y fábrica de sesiones.
# Mismo patrón de siempre para un proyecto FastAPI + SQLAlchemy + SQLite.

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# SQLite guarda todo en un único archivo al lado del proyecto. Para una app
# chica como esta, o para un TP, es ideal: cero configuración de servidor.
SQLALCHEMY_DATABASE_URL = "sqlite:///./tareas_metas.db"

# `check_same_thread=False` es una particularidad de SQLite: por default
# solo permite usar la conexión desde el mismo thread que la abrió. FastAPI
# puede atender cada request en un thread distinto, así que sin este flag
# nos tiraría errores de threading random.
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
)

# SessionLocal es la "fábrica" que nos entrega una sesión nueva por cada
# request. Pensalo como abrir una conversación con la base: consultás,
# modificás datos, y al final la cerrás.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base es la clase madre de la que heredan todos nuestros modelos (tablas).
Base = declarative_base()


def get_db():
    """
    Dependencia de FastAPI para inyectar una sesión de base de datos en cada
    endpoint. El `yield` es la clave: todo lo de antes corre al abrir la
    request, y el `finally` garantiza que la sesión se cierre siempre al
    terminar, haya salido todo bien o haya explotado una excepción.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
