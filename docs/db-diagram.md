# Schema del database

Schema implementato in `backend/app/models/models.py`.

Ogni riquadro è una tabella con le sue colonne (PK chiave primaria, FK chiave esterna, UK valore unico). Ogni freccia va da una tabella a quella che richiama e porta il nome della colonna che le collega (per esempio `BOOKINGS --user_id--> USERS` significa che la prenotazione contiene l'id dell'utente).

```mermaid
flowchart TD
    USERS["<b>USERS</b><br/>id PK<br/>email UK<br/>password_hash<br/>name"]

    CONVERSATIONS["<b>CONVERSATIONS</b><br/>id PK<br/>user_id FK<br/>requirements<br/>created_at<br/>updated_at"]

    MESSAGES["<b>MESSAGES</b><br/>id PK<br/>conversation_id FK<br/>role<br/>content<br/>created_at"]

    BOOKINGS["<b>BOOKINGS</b><br/>id PK<br/>user_id FK<br/>conversation_id FK<br/>status<br/>label<br/>country<br/>city<br/>hotel_id FK<br/>travelers<br/>nights<br/>departure_date<br/>return_date<br/>total_cost<br/>created_at"]

    BOOKING_FLIGHTS["<b>BOOKING_FLIGHTS</b><br/>id PK<br/>booking_id FK<br/>flight_id FK<br/>direction<br/>price_per_person"]

    BOOKING_ROOMS["<b>BOOKING_ROOMS</b><br/>id PK<br/>booking_id FK<br/>room_availability_id FK<br/>price"]

    BOOKING_ACTIVITIES["<b>BOOKING_ACTIVITIES</b><br/>id PK<br/>booking_id FK<br/>activity_availability_id FK<br/>price_per_person<br/>affinity"]

    FLIGHTS["<b>FLIGHTS</b><br/>id PK<br/>origin_airport<br/>destination_airport<br/>destination_country<br/>city<br/>departure<br/>arrival<br/>price<br/>seats_left"]

    HOTELS["<b>HOTELS</b><br/>id PK<br/>name<br/>country<br/>city<br/>stars<br/>description"]

    ROOMS["<b>ROOMS</b><br/>id PK<br/>hotel_id FK<br/>name<br/>capacity"]

    ROOM_AVAILABILITY["<b>ROOM_AVAILABILITY</b><br/>id PK<br/>room_id FK<br/>night<br/>price_per_night<br/>is_free"]

    ACTIVITIES["<b>ACTIVITIES</b><br/>id PK<br/>name<br/>country<br/>city<br/>category<br/>price<br/>description<br/>target"]

    ACTIVITY_AVAILABILITY["<b>ACTIVITY_AVAILABILITY</b><br/>id PK<br/>activity_id FK<br/>day<br/>spots_left"]

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