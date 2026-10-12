"use strict";

// Funzione che restituisce il testo da mostrare per lo stato di una prenotazione
function testoStato(stato)
{
    if(stato == "proposed")
    {
        return "In sospeso";
    }
    else if(stato == "confirmed")
    {
        return "Confermata";
    }
    else if(stato == "cancelled")
    {
        return "Annullata";
    }

    return stato;
}


// Funzione che trasforma una data del backend ("2026-11-18") in "18/11/2026"
function formattaDataEstesa(data)
{
    return data.slice(8, 10) + "/" + data.slice(5, 7) + "/" + data.slice(0, 4);
}


// Funzione che crea la scheda di una prenotazione. Ogni prenotazione ha i campi: id, status, city, country, departure_date, return_date,
// nights, travelers, total_cost, hotel_name, hotel_stars, hotel_image_url
function creaScheda(prenotazione)
{
    var scheda = document.getElementById("booking-template").content.cloneNode(true);

    scheda.querySelector(".booking").dataset.status = prenotazione.status;
    scheda.querySelector(".booking-city").textContent = prenotazione.city + ", " + prenotazione.country;
    scheda.querySelector(".booking-hotel").textContent = "🏨 " + prenotazione.hotel_name + " (" + prenotazione.hotel_stars + " stelle)";
    scheda.querySelector(".booking-dates").textContent = "📅 " + formattaDataEstesa(prenotazione.departure_date) + " - " +
        formattaDataEstesa(prenotazione.return_date) + " (" + prenotazione.nights + " notti)";
    scheda.querySelector(".booking-travelers").textContent = "👥 " + prenotazione.travelers + " viaggiatori";
    scheda.querySelector(".booking-total").textContent = prenotazione.total_cost + " euro";

    // Stato (con il colore giusto) e foto dell'hotel
    var stato = scheda.querySelector(".booking-status");
    stato.textContent = testoStato(prenotazione.status);
    stato.classList.add("status-" + prenotazione.status);
    mostraFoto(scheda.querySelector(".booking-photo"), prenotazione.hotel_image_url, prenotazione.hotel_name);

    var bottoneDettaglio = scheda.querySelector(".detail-button");
    var bottoneConferma = scheda.querySelector(".confirm-button");
    var bottoneAnnulla = scheda.querySelector(".cancel-button");

    // Si può confermare solo una proposta e annullare solo una prenotazione non ancora annullata
    bottoneConferma.hidden = (prenotazione.status != "proposed");
    bottoneAnnulla.hidden = (prenotazione.status == "cancelled");

    bottoneDettaglio.addEventListener("click", function() { apriDettaglio(prenotazione.id); });
    bottoneConferma.addEventListener("click", function() { cambiaStato(prenotazione.id, "confirm"); });
    bottoneAnnulla.addEventListener("click", function() { cambiaStato(prenotazione.id, "cancel"); });

    return scheda;
}


// Funzione che apre la finestra con il dettaglio di una prenotazione (voli, hotel e attività giorno per giorno)
async function apriDettaglio(id)
{
    try
    {
        var dettaglio = await chiamaApi("/bookings/" + id, "GET", null, null);

        // Riuso la scheda dell'itinerario della chat, senza numero e senza il pulsante "Scegli"
        var contenuto = document.getElementById("dialog-content");
        contenuto.replaceChildren(creaSchedaItinerario(dettaglio.itinerary, null, false));

        document.getElementById("booking-dialog").showModal();
    }
    catch(errore)
    {
        alert(errore.message);
    }
}


// Funzione che conferma o annulla una prenotazione (azione: "confirm" oppure "cancel") e poi ricarica la lista
async function cambiaStato(id, azione)
{
    if(azione == "confirm" && !confirm("Vuoi confermare la prenotazione? Voli, camere e attività verranno bloccati."))
    {
        return;
    }
    if(azione == "cancel" && !confirm("Sei sicuro di voler annullare la prenotazione?"))
    {
        return;
    }

    try
    {
        await chiamaApi("/bookings/" + id + "/" + azione, "POST", null, null);
    }
    catch(errore)
    {
        // Per esempio una camera non più libera: il backend spiega il motivo e la prenotazione resta com'era
        alert(errore.message);
    }

    await caricaPrenotazioni();
}


// Funzione che chiede al backend le prenotazioni dell'utente e le mostra, divise per stato (in sospeso, confermate, annullate)
async function caricaPrenotazioni()
{
    var stati = ["proposed", "confirmed", "cancelled"];

    try
    {
        var prenotazioni = await chiamaApi("/bookings", "GET", null, null);

        // Svuoto le tre sezioni e azzero i contatori
        var conteggi = {proposed: 0, confirmed: 0, cancelled: 0};
        for(var i = 0; i < stati.length; i++)
        {
            document.getElementById("list-" + stati[i]).replaceChildren();
        }

        // Ogni prenotazione va nella sezione del suo stato
        for(var j = 0; j < prenotazioni.length; j++)
        {
            var stato = prenotazioni[j].status;
            document.getElementById("list-" + stato).append(creaScheda(prenotazioni[j]));
            conteggi[stato]++;
        }

        // Numero di prenotazioni nel titolo di ogni sezione e messaggio per le sezioni vuote
        for(var k = 0; k < stati.length; k++)
        {
            document.getElementById("count-" + stati[k]).textContent = conteggi[stati[k]];
            document.getElementById("empty-" + stati[k]).hidden = (conteggi[stati[k]] > 0);
        }

        document.getElementById("bookings-empty").hidden = (prenotazioni.length > 0);
    }
    catch(errore)
    {
        alert(errore.message);
    }
}
