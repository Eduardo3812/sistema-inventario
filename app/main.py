# Punto de entrada de la app: acá viven todas las rutas HTTP.
#
# Para levantarla en modo desarrollo, desde la carpeta raíz del proyecto:
#   uvicorn app.main:app --reload
# Y abrís http://127.0.0.1:8000 en el navegador.

from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from . import models
from .database import Base, engine, get_db

# Crea las tablas en SQLite si todavía no existen (no pisa datos si ya están).
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Tareas y Metas")

# Le decimos a Jinja2 dónde están los .html. Ruta absoluta (basada en la
# ubicación de este archivo) para que funcione sin importar desde qué
# carpeta se ejecute `uvicorn`.
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def redirigir_con_mensaje(url: str, mensaje: str, categoria: str = "success") -> RedirectResponse:
    """
    Esta app no tiene login ni sesiones, así que en vez de guardar un
    mensaje "flash" del lado del servidor, lo mandamos como query param en
    la URL de redirect (ej: `/?msg=Meta+creada&cat=success`). La plantilla
    lo lee de `request.query_params` y lo muestra. `quote()` escapa
    espacios y caracteres especiales para que la URL sea válida.
    """
    query = f"msg={quote(mensaje)}&cat={categoria}"
    return RedirectResponse(f"{url}?{query}", status_code=status.HTTP_303_SEE_OTHER)


# ===========================================================================
# Dashboard: alta de metas, alta de tareas dentro de una meta, progreso
# ===========================================================================

@app.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    """
    Panel principal: trae SOLO las metas que todavía no están completadas
    (`fecha_completado IS NULL`, la consulta filtrada de siempre) y las
    manda a la plantilla. Cada meta ya viaja con su lista de tareas
    cargada gracias a la relación `Meta.tareas` que definimos en
    models.py, así que la plantilla puede recorrerlas sin que nosotros
    tengamos que armar ninguna consulta extra acá.
    """
    metas = (
        db.query(models.Meta)
        .filter(models.Meta.fecha_completado.is_(None))
        .order_by(models.Meta.fecha_creacion.desc())
        .all()
    )

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "metas": metas,
            "mensaje": request.query_params.get("msg"),
            "categoria_mensaje": request.query_params.get("cat", "success"),
        },
    )


@app.post("/metas/nuevo")
def crear_meta(titulo: str = Form(...), descripcion: str = Form(""), db: Session = Depends(get_db)):
    """Da de alta una meta nueva, todavía sin tareas (arranca en 0% de progreso)."""
    titulo = titulo.strip()
    if not titulo:
        return redirigir_con_mensaje("/", "El título de la meta no puede estar vacío", "error")

    meta = models.Meta(titulo=titulo, descripcion=descripcion.strip() or None)
    db.add(meta)
    db.commit()

    return redirigir_con_mensaje("/", f"Meta '{titulo}' creada. Ahora agregale tareas 👇")


@app.post("/metas/{meta_id}/tareas/nuevo")
def crear_tarea(
    meta_id: int,
    titulo: str = Form(...),
    descripcion: str = Form(""),
    db: Session = Depends(get_db),
):
    """
    Agrega una tarea nueva DENTRO de una meta puntual. Fijate que acá no
    hay un `<select>` para elegir la meta como en un formulario genérico:
    el `meta_id` viaja directo en la URL (`/metas/3/tareas/nuevo`), porque
    en el dashboard cada meta tiene su propio mini-formulario que ya sabe
    a qué meta pertenece (ver dashboard.html).
    """
    meta = db.query(models.Meta).filter(models.Meta.id == meta_id).first()
    if not meta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meta no encontrada")

    titulo = titulo.strip()
    if not titulo:
        return redirigir_con_mensaje("/", "El título de la tarea no puede estar vacío", "error")

    tarea = models.Tarea(titulo=titulo, descripcion=descripcion.strip() or None, meta_id=meta.id)
    db.add(tarea)

    # Caso borde importante: si esta meta ya estaba marcada como completada
    # (100%) y le sumamos una tarea nueva (que arranca en 'pendiente'), ya
    # no tiene sentido que siga figurando como "completada" en el
    # historial: la "reabrimos" limpiando su fecha_completado. Así el
    # porcentaje vuelve a recalcularse solo y la meta reaparece en el
    # dashboard como activa.
    if meta.fecha_completado is not None:
        meta.fecha_completado = None

    db.commit()

    return redirigir_con_mensaje("/", f"Tarea '{titulo}' agregada a '{meta.titulo}'")


@app.post("/tareas/{tarea_id}/completar")
def completar_tarea(tarea_id: int, db: Session = Depends(get_db)):
    """
    Acá pasan dos cosas encadenadas, y es el corazón de todo el sistema de
    progreso:

      1) Actualización de estado: la tarea puntual pasa a 'completado' y
         registra la fecha/hora exacta en fecha_completado.
      2) Recálculo de la meta: una vez tachada la tarea, chequeamos si con
         este cambio la meta llegó al 100% (todas sus tareas completadas).
         Si es así, marcamos la fecha_completado DE LA META también, y
         recién ahí es cuando esa meta "se gradúa" del dashboard al
         historial.

    Todo esto se guarda en un único `db.commit()` al final: para la base
    de datos es una sola transacción atómica, no dos pasos separados que
    podrían quedar a mitad de camino si algo fallara.
    """
    tarea = db.query(models.Tarea).filter(models.Tarea.id == tarea_id).first()
    if not tarea:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarea no encontrada")

    if tarea.estado == models.EstadoTarea.completado:
        return redirigir_con_mensaje("/", f"'{tarea.titulo}' ya estaba completada", "error")

    tarea.estado = models.EstadoTarea.completado
    tarea.fecha_completado = datetime.utcnow()

    # `flush()` empuja este cambio a la sesión (sin cerrar la transacción
    # todavía) para que, al leer `meta.tareas` un renglón más abajo, el
    # cálculo de progreso ya tenga en cuenta esta tarea recién completada.
    db.flush()

    meta = tarea.meta
    meta_recien_completada = (
        meta.fecha_completado is None
        and meta.total_tareas > 0
        and meta.tareas_completadas == meta.total_tareas
    )

    if meta_recien_completada:
        meta.fecha_completado = datetime.utcnow()
        mensaje = f"¡'{tarea.titulo}' completada! 🎉 Meta '{meta.titulo}' alcanzada al 100% 🏆"
    else:
        mensaje = f"'{tarea.titulo}' completada ({meta.progreso_porcentaje}% de '{meta.titulo}')"

    db.commit()

    return redirigir_con_mensaje("/", mensaje)


# ===========================================================================
# Historial: consulta filtrada de metas 100% completadas
# ===========================================================================

@app.get("/historial")
def historial(request: Request, db: Session = Depends(get_db)):
    """
    Trae EXCLUSIVAMENTE las metas con `fecha_completado` cargada (o sea,
    las que llegaron al 100%), ordenadas de la más reciente a la más
    antigua. Cada una viaja con todas sus tareas (todas completadas, ya
    que así es como llegó al 100%), para poder mostrar el detalle completo
    del logro.
    """
    metas_completadas = (
        db.query(models.Meta)
        .filter(models.Meta.fecha_completado.isnot(None))
        .order_by(models.Meta.fecha_completado.desc())
        .all()
    )

    return templates.TemplateResponse(
        request,
        "historial.html",
        {"metas_completadas": metas_completadas},
    )
