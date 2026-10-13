# Schema del database

Schema implementato in `backend/app/models/models.py`.

Ogni riquadro è una tabella con le sue colonne (PK chiave primaria, FK chiave esterna, UK valore unico). Ogni freccia va da una tabella a quella che richiama e porta il nome della colonna che le collega (per esempio `BOOKINGS --user_id--> USERS` significa che la prenotazione contiene l'id dell'utente).

```mermaid
flowchart TD
    USERS["<table><tr><th colspan='2'>USERS</th></tr><tr><td align='left'>id</td><td>PK</td></tr><tr><td align='left'>email</td><td>UK</td></tr><tr><td align='left'>password_hash</td><td></td></tr><tr><td align='left'>name</td><td></td></tr></table>"]

    CONVERSATIONS["<table><tr><th colspan='2'>CONVERSATIONS</th></tr><tr><td align='left'>id</td><td>PK</td></tr><tr><td align='left'>user_id</td><td>FK</td></tr><tr><td align='left'>requirements</td><td></td></tr><tr><td align='left'>created_at</td><td></td></tr><tr><td align='left'>updated_at</td><td></td></tr></table>"]

    MESSAGES["<table><tr><th colspan='2'>MESSAGES</th></tr><tr><td align='left'>id</td><td>PK</td></tr><tr><td align='left'>conversation_id</td><td>FK</td></tr><tr><td align='left'>role</td><td></td></tr><tr><td align='left'>content</td><td></td></tr><tr><td align='left'>created_at</td><td></td></tr></table>"]

    BOOKINGS["<table><tr><th colspan='2'>BOOKINGS</th></tr><tr><td align='left'>id</td><td>PK</td></tr><tr><td align='left'>user_id</td><td>FK</td></tr><tr><td align='left'>conversation_id</td><td>FK</td></tr><tr><td align='left'>status</td><td></td></tr><tr><td align='left'>label</td><td></td></tr><tr><td align='left'>country</td><td></td></tr><tr><td align='left'>city</td><td></td></tr><tr><td align='left'>hotel_id</td><td>FK</td></tr><tr><td align='left'>travelers</td><td></td></tr><tr><td align='left'>nights</td><td></td></tr><tr><td align='left'>departure_date</td><td></td></tr><tr><td align='left'>return_date</td><td></td></tr><tr><td align='left'>total_cost</td><td></td></tr><tr><td align='left'>created_at</td><td></td></tr></table>"]

    BOOKING_FLIGHTS["<table><tr><th colspan='2'>BOOKING_FLIGHTS</th></tr><tr><td align='left'>id</td><td>PK</td></tr><tr><td align='left'>booking_id</td><td>FK</td></tr><tr><td align='left'>flight_id</td><td>FK</td></tr><tr><td align='left'>direction</td><td></td></tr><tr><td align='left'>price_per_person</td><td></td></tr></table>"]

    BOOKING_ROOMS["<table><tr><th colspan='2'>BOOKING_ROOMS</th></tr><tr><td align='left'>id</td><td>PK</td></tr><tr><td align='left'>booking_id</td><td>FK</td></tr><tr><td align='left'>room_availability_id</td><td>FK</td></tr><tr><td align='left'>price</td><td></td></tr></table>"]

    BOOKING_ACTIVITIES["<table><tr><th colspan='2'>BOOKING_ACTIVITIES</th></tr><tr><td align='left'>id</td><td>PK</td></tr><tr><td align='left'>booking_id</td><td>FK</td></tr><tr><td align='left'>activity_availability_id</td><td>FK</td></tr><tr><td align='left'>price_per_person</td><td></td></tr><tr><td align='left'>affinity</td><td></td></tr></table>"]

    FLIGHTS["<table><tr><th colspan='2'>FLIGHTS</th></tr><tr><td align='left'>id</td><td>PK</td></tr><tr><td align='left'>origin_airport</td><td></td></tr><tr><td align='left'>destination_airport</td><td></td></tr><tr><td align='left'>destination_country</td><td></td></tr><tr><td align='left'>city</td><td></td></tr><tr><td align='left'>departure</td><td></td></tr><tr><td align='left'>arrival</td><td></td></tr><tr><td align='left'>price</td><td></td></tr><tr><td align='left'>seats_left</td><td></td></tr></table>"]

    HOTELS["<table><tr><th colspan='2'>HOTELS</th></tr><tr><td align='left'>id</td><td>PK</td></tr><tr><td align='left'>name</td><td></td></tr><tr><td align='left'>country</td><td></td></tr><tr><td align='left'>city</td><td></td></tr><tr><td align='left'>stars</td><td></td></tr><tr><td align='left'>description</td><td></td></tr></table>"]

    ROOMS["<table><tr><th colspan='2'>ROOMS</th></tr><tr><td align='left'>id</td><td>PK</td></tr><tr><td align='left'>hotel_id</td><td>FK</td></tr><tr><td align='left'>name</td><td></td></tr><tr><td align='left'>capacity</td><td></td></tr></table>"]

    ROOM_AVAILABILITY["<table><tr><th colspan='2'>ROOM_AVAILABILITY</th></tr><tr><td align='left'>id</td><td>PK</td></tr><tr><td align='left'>room_id</td><td>FK</td></tr><tr><td align='left'>night</td><td></td></tr><tr><td align='left'>price_per_night</td><td></td></tr><tr><td align='left'>is_free</td><td></td></tr></table>"]

    ACTIVITIES["<table><tr><th colspan='2'>ACTIVITIES</th></tr><tr><td align='left'>id</td><td>PK</td></tr><tr><td align='left'>name</td><td></td></tr><tr><td align='left'>country</td><td></td></tr><tr><td align='left'>city</td><td></td></tr><tr><td align='left'>category</td><td></td></tr><tr><td align='left'>price</td><td></td></tr><tr><td align='left'>description</td><td></td></tr><tr><td align='left'>target</td><td></td></tr></table>"]

    ACTIVITY_AVAILABILITY["<table><tr><th colspan='2'>ACTIVITY_AVAILABILITY</th></tr><tr><td align='left'>id</td><td>PK</td></tr><tr><td align='left'>activity_id</td><td>FK</td></tr><tr><td align='left'>day</td><td></td></tr><tr><td align='left'>spots_left</td><td></td></tr></table>"]

    CONVERSATIONS -- user_id --> USERS
    MESSAGES -- conversation_id --> CONVERSATIONS
    BOOKINGS -- user_id --> USERS
    BOOKINGS -- conversation_id --> CONVERSATIONS
    BOOKINGS -- hotel_id --> HOTELS
    BOOKING_FLIGHTS -- booking_id --> BOOKINGS
    BOOKING_FLIGHTS -- flight_id --> FLIGHTS
    BOOKING_ROOMS -- booking_id --> BOOKINGS
    BOOKING_ROOMS -- room_availability_id --> ROOM_AVAILABILITY
    BOOKING_ACTIVITIES -- booking_id --> BOOKINGS
    BOOKING_ACTIVITIES -- activity_availability_id --> ACTIVITY_AVAILABILITY
    ROOMS -- hotel_id --> HOTELS
    ROOM_AVAILABILITY -- room_id --> ROOMS
    ACTIVITY_AVAILABILITY -- activity_id --> ACTIVITIES
```

## Note sul diagramma

- **`BOOKINGS`**: una riga per prenotazione con i dati generali; il dettaglio sta nelle tabelle figlie `BOOKING_FLIGHTS` (andata e ritorno), `BOOKING_ROOMS` (una riga per camera e notte) e `BOOKING_ACTIVITIES` (una riga per attività e giorno), con chiave esterna verso le righe di disponibilità: confermare e annullare toccano quelle righe. I prezzi sono quelli del momento della proposta.
- **`ROOMS`**: una riga per camera fisica; `ROOM_AVAILABILITY.is_free` dice se è ancora libera in quella notte.
- **Unicità composte**: `ROOM_AVAILABILITY(room_id, night)` e `ACTIVITY_AVAILABILITY(activity_id, day)`.
- **Stati di `BOOKINGS.status`**: `proposed`, `confirmed`, `cancelled`.
- **Unità dei prezzi**: voli e attività per persona; camere per camera (intera) e per notte.
- **Chroma** non è nel diagramma: un documento per attività, con lo stesso `id` di `ACTIVITIES.id`.