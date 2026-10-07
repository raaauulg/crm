"""Datos de demostración inventados (`crm demo`). Nombres claramente ficticios.

Las fechas son relativas a hoy para que el dashboard siempre tenga seguimientos vencidos,
próximos y facturas en todos los estados.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from crm.models import (
    Company,
    Contact,
    Contract,
    Interaction,
    Invoice,
    Phase,
    Service,
)
from crm.services.catalog import ensure_default_catalog
from crm.services.clock import today
from crm.services.errors import ServiceError
from crm.services.money import total_with_vat

DEMO_ACTOR = "demo"


@dataclass(frozen=True)
class DemoCompany:
    name: str
    sector: str
    municipality: str
    phase: Phase
    source: str
    service: str | None
    value_eur: int | None
    pain: int | None
    next_step: str = ""
    next_in_days: int | None = None
    notes: str = ""


COMPANIES: list[DemoCompany] = [
    DemoCompany(
        "Carpintería Pino Ficticio",
        "Carpintería",
        "Covaleda",
        Phase.WON,
        "Visita",
        "Albaranes y facturas sin teclear",
        1700,
        80,
        "Revisar uso del primer mes",
        5,
        "Pierden 6 h/semana tecleando albaranes de proveedores.",
    ),
    DemoCompany(
        "Transportes Ejemplo Duero",
        "Transporte",
        "Almazán",
        Phase.WON,
        "Recomendación",
        "Pedidos sin teclear",
        2000,
        75,
        "Llamada de seguimiento trimestral",
        20,
    ),
    DemoCompany(
        "Asesoría Inventada Numancia",
        "Asesoría",
        "Soria",
        Phase.WON,
        "FOES",
        "Recepcionista virtual",
        2500,
        70,
        "Reclamar factura vencida",
        -3,
    ),
    DemoCompany(
        "Muebles Demo Pinares",
        "Mueble",
        "Duruelo de la Sierra",
        Phase.WON,
        "Visita",
        "Presupuestos en 5 minutos",
        2200,
        65,
    ),
    DemoCompany(
        "Embutidos La Imaginaria",
        "Alimentación",
        "Ólvega",
        Phase.PROPOSAL_SENT,
        "Evento",
        "Parte del lunes",
        2400,
        70,
        "Llamar para resolver dudas de la propuesta",
        -2,
        "Interesados en el parte semanal de producción.",
    ),
    DemoCompany(
        "Talleres Ficción Moncayo",
        "Taller mecánico",
        "Ágreda",
        Phase.PROPOSAL_SENT,
        "Buscador",
        "Presupuestos en 5 minutos",
        2200,
        60,
        "Esperar respuesta",
        4,
    ),
    DemoCompany(
        "Clínica Dental Sonrisa Inventada",
        "Salud",
        "Soria",
        Phase.DIAGNOSIS,
        "Recomendación",
        "Recepcionista virtual",
        2500,
        85,
        "Entregar diagnóstico",
        2,
        "Pierden llamadas en horas punta; quieren citas fuera de horario.",
    ),
    DemoCompany(
        "Gestoría Ejemplar del Burgo",
        "Gestoría",
        "El Burgo de Osma",
        Phase.DIAGNOSIS,
        "FOES",
        "Albaranes y facturas sin teclear",
        1700,
        60,
        "Recoger muestras de facturas",
        6,
    ),
    DemoCompany(
        "Hotel Rural Demo Sierra",
        "Hostelería",
        "Covaleda",
        Phase.MEETING,
        "Visita",
        "Web sencilla",
        690,
        40,
        "Reunión con la propietaria",
        1,
    ),
    DemoCompany(
        "Fontanería Ficticia Hermanos",
        "Instalaciones",
        "San Leonardo de Yagüe",
        Phase.MEETING,
        "Recomendación",
        "Presupuestos en 5 minutos",
        2200,
        55,
        "Preparar demo de presupuestos",
        3,
    ),
    DemoCompany(
        "Distribuciones Prueba Soria",
        "Distribución",
        "Soria",
        Phase.MEETING,
        "Buscador",
        "Pedidos sin teclear",
        2000,
        70,
        "Confirmar fecha de reunión",
        -5,
    ),
    DemoCompany(
        "Panadería El Horno Inventado",
        "Alimentación",
        "Almazán",
        Phase.CONTACTED,
        "Visita",
        "Taller IA útil para tu oficina",
        1200,
        30,
        "Volver a llamar",
        7,
    ),
    DemoCompany(
        "Construcciones Demo Tierras Altas",
        "Construcción",
        "Ágreda",
        Phase.CONTACTED,
        "Buscador",
        "Presupuestos en 5 minutos",
        2200,
        50,
        "Enviar caso de éxito",
        -1,
    ),
    DemoCompany(
        "Óptica Visión Ficticia",
        "Comercio",
        "Soria",
        Phase.CONTACTED,
        "Evento",
        "Recepcionista virtual",
        2500,
        45,
    ),
    DemoCompany(
        "Agroservicios Ejemplo Campo",
        "Agricultura",
        "El Burgo de Osma",
        Phase.IDENTIFIED,
        "Buscador",
        "Albaranes y facturas sin teclear",
        1700,
        55,
        "Buscar contacto del gerente",
        10,
    ),
    DemoCompany(
        "Serrería Pinar Imaginario",
        "Madera",
        "Duruelo de la Sierra",
        Phase.IDENTIFIED,
        "Visita",
        "Pedidos sin teclear",
        2000,
        60,
    ),
    DemoCompany(
        "Academia Demo Saber",
        "Formación",
        "Soria",
        Phase.IDENTIFIED,
        "Recomendación",
        "Taller IA útil para tu oficina",
        1200,
        35,
        "Llamar en septiembre",
        12,
    ),
    DemoCompany(
        "Ferretería Tornillo Ficticio",
        "Comercio",
        "Ólvega",
        Phase.IDENTIFIED,
        "Buscador",
        "Paso a programa con Verifactu",
        600,
        50,
    ),
    DemoCompany(
        "Bodega Ejemplo Ribera",
        "Vino",
        "San Esteban de Gormaz",
        Phase.IDENTIFIED,
        "Evento",
        "Web sencilla",
        690,
        25,
    ),
    DemoCompany(
        "Lavandería Inventada Express",
        "Servicios",
        "Soria",
        Phase.LEAD,
        "Importación",
        None,
        None,
        None,
    ),
    DemoCompany(
        "Cárnicas Prueba Moncayo",
        "Alimentación",
        "Ólvega",
        Phase.LEAD,
        "Importación",
        None,
        None,
        None,
    ),
    DemoCompany(
        "Autoescuela Ficción Vía",
        "Formación",
        "Almazán",
        Phase.LEAD,
        "Importación",
        None,
        None,
        None,
    ),
    DemoCompany(
        "Inmobiliaria Demo Hogar",
        "Inmobiliaria",
        "Soria",
        Phase.LOST,
        "Buscador",
        "Recepcionista virtual",
        2500,
        30,
        "",
        None,
        "No ven el retorno ahora; volver a intentar en un año.",
    ),
    DemoCompany(
        "Peluquería Estilo Inventado",
        "Servicios",
        "El Burgo de Osma",
        Phase.LOST,
        "Visita",
        "Web sencilla",
        690,
        20,
    ),
    DemoCompany(
        "Imprenta Ejemplo Tinta",
        "Artes gráficas",
        "Soria",
        Phase.PROPOSAL_SENT,
        "Recomendación",
        "Albaranes y facturas sin teclear",
        1700,
        65,
        "Llamar para cerrar",
        0,
    ),
]

CONTACT_NAMES = [
    ("Lucía Ejemplo", "Gerente"),
    ("Mario Prueba", "Administración"),
    ("Ana Ficticia", "Propietaria"),
    ("Jorge Demo", "Jefe de taller"),
    ("Elena Inventada", "Oficina"),
]

INTERACTION_NOTES = [
    ("visita", "Primera visita: explican cómo trabajan hoy.", "Interesados"),
    ("llamada", "Llamada para concretar reunión.", "Reunión fijada"),
    ("email", "Envío de resumen y siguiente paso.", ""),
    ("whatsapp", "Mandan fotos de albaranes de ejemplo.", "Material recibido"),
    ("evento", "Coincidimos en jornada de FOES.", "Contacto en frío"),
]


def _is_empty(session: Session) -> bool:
    return not session.scalar(select(func.count(Company.id)))


def _wipe_business_data(session: Session) -> None:
    """Borra empresas y todo lo que cuelga de ellas. No toca usuarios ni el catálogo."""
    for model in (Invoice, Contract, Interaction, Contact, Company):
        session.execute(delete(model))


def load_demo(session: Session, force: bool = False, on: date | None = None) -> int:
    """Carga las empresas de demostración. Devuelve cuántas ha creado.

    Solo sobre una base de datos sin empresas, salvo `force=True` (borra las existentes).
    """
    on = on or today()
    if not _is_empty(session):
        if not force:
            raise ServiceError(
                "La base de datos ya tiene empresas. Usa --forzar para borrarlas y cargar la demo."
            )
        _wipe_business_data(session)
    ensure_default_catalog(session)
    services = {s.name: s for s in session.scalars(select(Service))}

    contact_counter = 0
    for index, demo in enumerate(COMPANIES):
        service = services.get(demo.service) if demo.service else None
        company = Company(
            name=demo.name,
            sector=demo.sector,
            municipality=demo.municipality,
            source=demo.source,
            phase=demo.phase.value,
            service=service,
            estimated_value_cents=demo.value_eur * 100 if demo.value_eur is not None else None,
            estimated_fee_cents=service.monthly_fee_cents if service else None,
            pain_score=demo.pain,
            notes=demo.notes,
            next_step=demo.next_step,
            next_step_date=(
                on + timedelta(days=demo.next_in_days) if demo.next_in_days is not None else None
            ),
            phone=f"600 000 1{index:02d}",
            created_by=DEMO_ACTOR,
            updated_by=DEMO_ACTOR,
        )
        session.add(company)

        if demo.phase is not Phase.LEAD:
            for n in range(1 + index % 2):
                name, role = CONTACT_NAMES[(index + n) % len(CONTACT_NAMES)]
                contact_counter += 1
                company.contacts.append(
                    Contact(
                        name=name,
                        role=role,
                        phone=f"600 000 0{contact_counter % 100:02d}",
                        email=f"{name.split()[0].lower()}{contact_counter}@ejemplo.com",
                        is_primary=n == 0,
                        data_source="Demo",
                        data_date=on - timedelta(days=30),
                        created_by=DEMO_ACTOR,
                        updated_by=DEMO_ACTOR,
                    )
                )
            for n in range(index % 4):
                channel, summary, result = INTERACTION_NOTES[(index + n) % len(INTERACTION_NOTES)]
                company.interactions.append(
                    Interaction(
                        occurred_on=on - timedelta(days=2 + n * 9 + index % 5),
                        channel=channel,
                        summary=summary,
                        result=result,
                        created_by=DEMO_ACTOR,
                    )
                )

        if demo.phase is Phase.WON and service is not None:
            _add_client_history(session, company, service, index, on)

    session.commit()
    return len(COMPANIES)


def _add_client_history(
    session: Session, company: Company, service: Service, index: int, on: date
) -> None:
    """Contrato desde hace unos meses y una factura por mes; la más antigua de algunos, vencida."""
    months_ago = 3 + index
    start = _months_before(on, months_ago)
    contract = Contract(
        company=company,
        service=service,
        setup_price_cents=service.setup_price_cents,
        monthly_fee_cents=service.monthly_fee_cents,
        start_date=start,
        commitment_months=12,
        created_by=DEMO_ACTOR,
        updated_by=DEMO_ACTOR,
    )
    session.add(contract)

    year = on.year % 100
    issued = [(start, service.setup_price_cents)] + [
        (_months_before(on, m), service.monthly_fee_cents) for m in range(months_ago - 1, -1, -1)
    ]
    for n, (issue, base) in enumerate(issued):
        if base == 0:
            continue
        due = issue + timedelta(days=30)
        is_latest = n == len(issued) - 1
        # La asesoría (index 2) tiene una factura impagada y vencida para la demo.
        unpaid = is_latest or (index == 2 and n == len(issued) - 3)
        session.add(
            Invoice(
                number=f"DEMO-{year}-{index:02d}{n:02d}",
                company=company,
                contract=contract,
                issue_date=issue,
                base_cents=base,
                vat_percent=21,
                total_cents=total_with_vat(base, 21),
                due_date=due,
                paid_date=None if unpaid or due > on else min(due, issue + timedelta(days=15)),
                created_by=DEMO_ACTOR,
                updated_by=DEMO_ACTOR,
            )
        )


def _months_before(on: date, months: int) -> date:
    """Mismo día (o el 28 como máximo) `months` meses antes."""
    total = on.year * 12 + (on.month - 1) - months
    return date(total // 12, total % 12 + 1, min(on.day, 28))
