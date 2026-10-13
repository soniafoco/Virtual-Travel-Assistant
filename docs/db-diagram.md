# Schema del database

Diagramma ER dello schema implementato in `backend/app/models/models.py`.

```mermaid
erDiagram
    USERS ||--o{ CONVERSATIONS : ha
    USERS ||--o{ BOOKINGS : possiede
    CONVERSATIONS ||--o{ MESSAGES : contiene
    CONVERSATIONS |o--o{ BOOKINGS : origina
    BOOKINGS ||--|{ BOOKING_FLIGHTS : voli
    BOOKINGS ||--|{ BOOKING_ROOMS : camere_e_notti
    BOOKINGS ||--o{ BOOKING_ACTIVITIES : attivita_e_giorni
    HOTELS ||--o{ BOOKINGS : scelto_in
    FLIGHTS ||--o{ BOOKING_FLIGHTS : prenotato_in
    ROOM_AVAILABILITY ||--o{ BOOKING_ROOMS : occupata_da
    ACTIVITY_AVAILABILITY ||--o{ BOOKING_ACTIVITIES : scalata_da
    HOTELS ||--|{ ROOMS : ha
    ROOMS ||--o{ ROOM_AVAILABILITY : una_riga_per_notte
    ACTIVITIES ||--o{ ACTIVITY_AVAILABILITY : una_riga_per_giorno

    USERS {
        int id PK
        string email UK
        string password_hash
        string name
    }

    CONVERSATIONS {
        int id PK
        int user_id FK
        json requirements
        datetime created_at
        datetime updated_at
    }

    MESSAGES {
        int id PK
        int conversation_id FK
        string role
        string content
        datetime created_at
    }

    BOOKINGS {
        int id PK
        int user_id FK
        int conversation_id FK
        string status
        string label
        string country
        string city
        int hotel_id FK
        int travelers
        int nights
        date departure_date
        date return_date
        decimal total_cost
        datetime created_at
    }

    BOOKING_FLIGHTS {
        int id PK
        int booking_id FK
        int flight_id FK
        string direction
        decimal price_per_person
    }

    BOOKING_ROOMS {
        int id PK
        int booking_id FK
        int room_availability_id FK
        decimal price
    }

    BOOKING_ACTIVITIES {
        int id PK
        int booking_id FK
        int activity_availability_id FK
        decimal price_per_person
        float affinity
    }

    FLIGHTS {
        int id PK
        string origin_airport
        string destination_airport
        string destination_country
        string city
        datetime departure
        datetime arrival
        decimal price
        int seats_left
    }

    HOTELS {
        int id PK
        string name
        string country
        string city
        int stars
        string description
    }

    ROOMS {
        int id PK
        int hotel_id FK
        string name
        int capacity
    }

    ROOM_AVAILABILITY {
        int id PK
        int room_id FK
        date night
        decimal price_per_night
        bool is_free
    }

    ACTIVITIES {
        int id PK
        string name
        string country
        string city
        string category
        decimal price
        string description
        string target
    }

    ACTIVITY_AVAILABILITY {
        int id PK
        int activity_id FK
        date day
        int spots_left
    }
```

## Note sul diagramma

- **`BOOKINGS`**: una riga per prenotazione con i dati generali; il dettaglio sta nelle tabelle figlie `BOOKING_FLIGHTS` (andata e ritorno), `BOOKING_ROOMS` (una riga per camera e notte) e `BOOKING_ACTIVITIES` (una riga per attività e giorno), con chiave esterna verso le righe di disponibilità: confermare e annullare toccano quelle righe. I prezzi sono quelli del momento della proposta.
- **`ROOMS`**: una riga per camera fisica; `ROOM_AVAILABILITY.is_free` dice se è ancora libera in quella notte.
- **Unicità composte** (non disegnabili in Mermaid): `ROOM_AVAILABILITY(room_id, night)` e `ACTIVITY_AVAILABILITY(activity_id, day)`.
- **Stati di `BOOKINGS.status`**: `proposed`, `confirmed`, `cancelled`.
- **Unità dei prezzi**: voli e attività per persona; camere per camera (intera) e per notte.
- **Chroma** non è nel diagramma: un documento per attività, con lo stesso `id` di `ACTIVITIES.id`.
