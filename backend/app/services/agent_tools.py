"""Tool LangChain dell'agente: leggono il database e chiamano il planner.

I tool restituiscono testo JSON compatto per il modello. Prezzi, date e disponibilita' arrivano
sempre dal database o dal planner: l'LLM li legge e li racconta, non li inventa.
"""

import json
from datetime import date

from langchain_core.tools import BaseTool, tool
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.models import Activity, Flight, Hotel
from app.schemas.itinerary import Itinerary, RequirementsState
from app.services import booking
from app.services.booking import BookingError
from app.services.planner import departure_window, plan_trips
from app.services.rag import min_affinity, rank_activities

def dumps(data) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)

def unisci_stato(stato: RequirementsState, nuovi: dict) -> RequirementsState:
    """Lo stato con i dati nuovi sopra quelli vecchi. I dati None non cambiano nulla; "" azzera la data di partenza.
    Alza ValidationError se un dato non e' valido."""
    dati = stato.model_dump()
    for nome, valore in nuovi.items():
        if valore is None:
            continue
        if valore == "":
            dati[nome] = None
        elif nome == "home_airport":
            dati[nome] = valore.strip().upper()
        else:
            dati[nome] = valore
    return RequirementsState(**dati)

def testo_stato(stato: RequirementsState) -> str:
    """I dati raccolti e quelli che mancano, in italiano: va nel prompt dell'agente a ogni richiesta."""
    raccolti = {nome: valore for nome, valore in stato.model_dump(mode="json").items() if valore is not None}
    testo = "Dati gia' raccolti in questa conversazione: " + (dumps(raccolti) if raccolti else "nessuno") + "."
    mancanti = stato.missing()
    if mancanti:
        testo += " Dati ancora mancanti: " + ", ".join(mancanti) + "."
    else:
        testo += " Hai tutti i dati obbligatori."
    return testo

class AgentContext:
    """Cio' che i tool condividono durante una conversazione."""

    def __init__(self, session: Session, user_id: int | None = None, conversation_id: int | None = None, today: date | None = None):
        self.session = session
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.today = today or date.today()
        self.itineraries: list[Itinerary] = []  # gli ultimi proposti dal planner, numerati da 1
        self.itineraries_changed = False  # True se in questa richiesta generate_itineraries ha sostituito la lista
        self.state = RequirementsState()  # i requisiti raccolti finora nella conversazione
        self.state_changed = False  # True se in questa richiesta un tool ha modificato lo stato
        self.last_proposal_id: int | None = None  # l'ultima proposta salvata in questa conversazione

def summarize(number: int, it: Itinerary) -> dict:
    """La versione compatta di un itinerario che il modello deve presentare."""
    return {
        "numero": number,
        "etichetta": it.label,
        "citta": it.city,
        "date": f"{it.departure_date} - {it.return_date} ({it.nights} notti)",
        "volo_andata": f"{it.flight_out.departure:%d/%m %H:%M}, {it.flight_out.price_per_person} euro a persona",
        "volo_ritorno": f"{it.flight_return.departure:%d/%m %H:%M}, {it.flight_return.price_per_person} euro a persona",
        "hotel": f"{it.hotel.name} ({it.hotel.stars} stelle), camere: {', '.join(r.name for r in it.hotel.rooms)}",
        "giorni": [
            {"giorno": str(d.day), "attivita": d.activity.name if d.activity else None,
             "categoria": d.activity.category if d.activity else None}
            for d in it.days
        ],
        "giorni_liberi": it.free_days,
        "costi_euro": it.costs.model_dump(),
    }

def build_tools(ctx: AgentContext) -> list[BaseTool]:
    """I tool legati al contesto di una conversazione (sessione DB, utente, ultimi itinerari)."""

    @tool
    def list_destinations() -> str:
        """Elenca le nazioni con le citta' che si possono prenotare. Usalo se l'utente non sa dove andare."""
        rows = ctx.session.execute(select(Hotel.country, Hotel.city).distinct().order_by(Hotel.country, Hotel.city))
        countries: dict[str, list[str]] = {}
        for country, city in rows:
            countries.setdefault(country, []).append(city)
        return dumps(countries)

    @tool
    def list_hotels(country: str, city: str | None = None) -> str:
        """Elenca gli hotel di una nazione (e facoltativamente di una citta') con stelle e descrizione.
        Non dice se sono liberi in una data: la disponibilita' la verifica generate_itineraries."""
        query = select(Hotel).where(func.lower(Hotel.country) == country.lower()).order_by(Hotel.city, Hotel.id)
        if city:
            query = query.where(func.lower(Hotel.city) == city.lower())
        hotels = ctx.session.scalars(query).all()
        return dumps([
            {"nome": h.name, "citta": h.city, "stelle": h.stars, "descrizione": h.description} for h in hotels
        ]) if hotels else "Nessun hotel trovato."

    @tool
    def find_airport(query: str) -> str:
        """Trova il codice IATA di un aeroporto di partenza a partire da un nome o da una citta' (es. "Fiumicino",
        "Milano"). Se la citta' ha piu' aeroporti restituisce tutti: chiedi all'utente quale preferisce.
        Per ognuno dice se nel sistema ci sono voli in partenza. Usalo prima di list_flight_dates e
        generate_itineraries quando l'utente non da' un codice IATA."""
        # gli aeroporti di partenza sono quelli dove atterrano i voli di rientro (verso l'Italia)
        served = set(ctx.session.scalars(
            select(Flight.destination_airport).where(Flight.destination_country == settings.home_country).distinct()
        ))
        text = query.strip().lower()
        found = [
            a for a in settings.airports
            if text and (text == a.code.lower() or text in a.name.lower() or text in a.city.lower())
        ]
        if not found:
            return dumps({"messaggio": "Aeroporto non riconosciuto.", "aeroporti_con_voli": sorted(served)})
        return dumps([
            {"codice": a.code, "nome": a.name, "citta": a.city, "voli_disponibili": a.code in served}
            for a in found
        ])

    @tool
    def list_flight_dates(home_airport: str, country: str, month: int) -> str:
        """Elenca, per ogni citta' della nazione, i giorni del mese in cui c'e' un volo di andata dall'aeroporto
        di partenza (codice IATA, es. FCO) e il prezzo piu' basso a persona. Serve a suggerire le date possibili."""
        try:
            first, last = departure_window(month, ctx.today)
        except ValueError:
            return "Il mese deve essere un numero da 1 a 12."
        rows = ctx.session.execute(
            select(Flight.city, func.date(Flight.departure), func.min(Flight.price))
            .where(
                Flight.origin_airport == home_airport.upper(),
                func.lower(Flight.destination_country) == country.lower(),
                func.date(Flight.departure) >= first.isoformat(), func.date(Flight.departure) <= last.isoformat(),
            )
            .group_by(Flight.city, func.date(Flight.departure))
            .order_by(Flight.city, func.date(Flight.departure))
        ).all()
        if not rows:
            return f"Nessun volo da {home_airport.upper()} verso {country} tra {first} e {last}."
        cities: dict[str, list[dict]] = {}
        for city, day, price in rows:
            cities.setdefault(city, []).append({"giorno": day, "prezzo_minimo_a_persona": float(price)})
        return dumps({"periodo": f"{first} - {last}", "citta": cities})

    @tool
    def search_activities(country: str, preferences: list[str]) -> str:
        """Cerca le attivita' piu' affini alle preferenze dell'utente in una nazione. Le preferenze sono libere
        (es. ["sport", "relax"], ["con i bambini"], ["kayak"]); restituisce solo quelle davvero affini."""
        threshold = min_affinity()
        ranked = [(i, score) for i, score in rank_activities(preferences, country) if score >= threshold][:settings.max_activities]
        if not ranked:
            return (f"Nessuna attivita' in {country} abbastanza affine a: {', '.join(preferences)}. "
                    "Dillo all'utente e chiedigli un'altra preferenza.")
        by_id = {a.id: a for a in ctx.session.scalars(select(Activity).where(Activity.id.in_([i for i, _ in ranked])))}
        return dumps([
            {"nome": by_id[i].name, "citta": by_id[i].city, "categoria": by_id[i].category,
             "prezzo_a_persona": float(by_id[i].price), "affinita": round(score, 2)}
            for i, score in ranked if i in by_id
        ])

    @tool
    def update_requirements(
        budget: float | None = None, country: str | None = None, activities: list[str] | None = None,
        month: int | None = None, travelers: int | None = None, nights: int | None = None,
        departure_date: str | None = None, home_airport: str | None = None,
    ) -> str:
        """Registra i dati del viaggio appena detti dall'utente. Chiamalo OGNI VOLTA che l'utente dice o cambia
        un dato (anche uno solo), passando solo i dati nuovi: gli altri restano quelli gia' salvati.
        budget = totale in euro per tutti; month = 1-12; home_airport = codice IATA; departure_date = AAAA-MM-GG
        (stringa vuota per toglierla). Restituisce i dati raccolti e quelli che mancano ancora."""
        nuovi = dict(
            budget=budget, country=country, activities=activities, month=month, travelers=travelers, nights=nights,
            departure_date=departure_date, home_airport=home_airport,
        )
        try:
            ctx.state = unisci_stato(ctx.state, nuovi)
        except ValidationError as error:
            return "Dati non validi: " + "; ".join(f"{e['loc'][0]}: {e['msg']}" for e in error.errors())
        ctx.state_changed = True
        return dumps({"raccolti": ctx.state.model_dump(mode="json"), "mancanti": ctx.state.missing()})

    @tool
    def generate_itineraries(
        budget: float | None = None, country: str | None = None, activities: list[str] | None = None,
        month: int | None = None, home_airport: str | None = None,
        travelers: int | None = None, nights: int | None = None, departure_date: str | None = None,
    ) -> str:
        """Costruisce gli itinerari (volo andata e ritorno, hotel, un'attivita' al giorno) entro il budget.
        Chiamalo solo quando hai tutti i dati. I dati che non passi vengono presi da quelli gia' registrati
        (vedi update_requirements); se ne manca qualcuno il tool dice quali. budget = totale in euro per tutti;
        month = 1-12; home_airport = codice IATA di partenza. departure_date = giorno di partenza esatto in formato
        AAAA-MM-GG: passalo SEMPRE se l'utente indica o cambia la data (es. "dal 13 al 18 novembre" = departure_date
        del 13 e nights = 5); il mese deve coincidere. Senza departure_date il planner sceglie lui i giorni nel mese.
        Restituisce gli itinerari numerati, oppure il motivo per cui non esistono (se il budget e' troppo basso
        indica la cifra minima)."""
        nuovi = dict(
            budget=budget, country=country, activities=activities, month=month, travelers=travelers, nights=nights,
            departure_date=departure_date, home_airport=home_airport,
        )
        try:
            stato = unisci_stato(ctx.state, nuovi)
            if stato.missing():
                ctx.state = stato  # i dati validi gia' passati si salvano comunque
                ctx.state_changed = True
                return dumps({"errore": "dati_mancanti", "mancanti": stato.missing()})
            req = stato.to_requirements()
        except ValidationError as error:
            return "Dati non validi: " + "; ".join(f"{e['loc'][0]}: {e['msg']}" for e in error.errors())

        ctx.state = stato  # i requisiti usati restano salvati, anche se poi il planner non trova nulla
        ctx.state_changed = True
        result = plan_trips(ctx.session, req, stato.home_airport, today=ctx.today)
        ctx.itineraries_changed = True
        if result.failure:
            ctx.itineraries = []
            return dumps({"errore": result.failure.code, "messaggio": result.failure.message,
                          "costo_minimo": result.failure.min_cost})
        ctx.itineraries = result.itineraries
        return dumps([summarize(n, it) for n, it in enumerate(ctx.itineraries, start=1)])

    @tool
    def save_proposal(itinerary_number: int) -> str:
        """Salva come proposta UN SOLO itinerario, solo se l'utente ha detto esplicitamente di volerlo salvare o
        scegliere (numero mostrato da generate_itineraries). Non chiamarlo mai di tua iniziativa e mai per
        tutti gli itinerari. Non conferma la prenotazione e non scala le disponibilita'."""
        if ctx.user_id is None:
            return "Per salvare una proposta serve un utente autenticato."
        if not 1 <= itinerary_number <= len(ctx.itineraries):
            return "Numero non valido: prima genera gli itinerari e scegli uno dei numeri proposti."
        saved = booking.create_proposal(ctx.session, ctx.user_id, ctx.conversation_id, ctx.itineraries[itinerary_number - 1])
        ctx.last_proposal_id = saved.id
        return dumps({"proposta_salvata": saved.id, "stato": saved.status, "totale_euro": float(saved.total_cost)})

    def describe(b) -> dict:
        return {
            "id": b.id, "stato": b.status, "citta": b.city,
            "date": f"{b.departure_date} - {b.return_date}",
            "viaggiatori": b.travelers, "totale_euro": float(b.total_cost),
        }

    @tool
    def confirm_booking(booking_id: int | None = None) -> str:
        """CONFERMA DAVVERO la prenotazione di una proposta salvata: scala voli, camere e posti delle attivita'.
        Chiamalo solo dopo che l'utente ha chiesto in modo esplicito di prenotare o confermare, mai di tua
        iniziativa. Senza booking_id conferma l'ultima proposta salvata in questa conversazione.
        Se qualcosa non e' piu' disponibile non cambia nulla e il tool spiega cosa."""
        if ctx.user_id is None:
            return "Per prenotare serve un utente autenticato."
        booking_id = booking_id or ctx.last_proposal_id
        if booking_id is None:
            return "Non c'e' nessuna proposta da confermare: prima scegli un itinerario e salvalo."
        try:
            confirmed = booking.confirm_booking(ctx.session, booking_id, ctx.user_id)
        except BookingError as error:
            return str(error)
        return dumps({"prenotazione_confermata": describe(confirmed)})

    @tool
    def cancel_booking(booking_id: int) -> str:
        """Annulla una prenotazione o una proposta dell'utente (se era confermata libera di nuovo posti e camere).
        Chiamalo solo se l'utente lo chiede in modo esplicito; se non conosci l'id usa prima list_my_bookings."""
        if ctx.user_id is None:
            return "Per annullare serve un utente autenticato."
        try:
            cancelled = booking.cancel_booking(ctx.session, booking_id, ctx.user_id)
        except BookingError as error:
            return str(error)
        return dumps({"prenotazione_annullata": describe(cancelled)})

    @tool
    def list_my_bookings() -> str:
        """Elenca le prenotazioni e le proposte dell'utente con id, stato, citta', date e totale."""
        if ctx.user_id is None:
            return "Per vedere le prenotazioni serve un utente autenticato."
        bookings = booking.user_bookings(ctx.session, ctx.user_id)
        return dumps([describe(b) for b in bookings]) if bookings else "Nessuna prenotazione."

    return [list_destinations, list_hotels, find_airport, list_flight_dates, search_activities, update_requirements,
            generate_itineraries, save_proposal, confirm_booking, cancel_booking, list_my_bookings]
