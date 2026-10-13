"use strict";

// Numero della conversazione in corso: lo assegna il backend al primo messaggio (null = conversazione nuova)
var idConversazione = null;


// Funzione che scrive un testo in un elemento mostrando in grassetto le parti tra ** (come le scrive l'assistente).
// Non uso innerHTML: il testo arriva dall'utente o dall'LLM, quindi creo io i nodi di testo e gli elementi <strong>
function scriviConGrassetto(elemento, testo)
{
    var parti = testo.split("**");

    for(var i = 0; i < parti.length; i++)
    {
        // Le parti in posizione dispari sono quelle che stavano tra due **; l'ultima, se manca la chiusura, resta testo normale
        if(i % 2 == 1 && i < parti.length - 1)
        {
            var grassetto = document.createElement("strong");
            grassetto.textContent = parti[i];
            elemento.append(grassetto);
        }
        else if(i % 2 == 1)
        {
            elemento.append("**" + parti[i]);
        }
        else
        {
            elemento.append(parti[i]);
        }
    }
}


// Funzione che aggiunge un messaggio alla chat
function aggiungiMessaggio(autore, testo, contenitore)
{
    var messaggio = document.getElementById("message-template").content.cloneNode(true);
    messaggio.querySelector(".message-author").textContent = autore;
    scriviConGrassetto(messaggio.querySelector(".message-text"), testo);

    // I messaggi dell'utente e quelli dell'assistente hanno uno stile diverso
    if(autore == "Tu")
    {
        messaggio.querySelector(".message").classList.add("message-user");
    }
    else
    {
        messaggio.querySelector(".message").classList.add("message-assistant");
    }

    // Senza contenitore il messaggio va nella chat in corso
    if(!contenitore)
    {
        contenitore = document.getElementById("messages");
    }
    contenitore.append(messaggio);
    contenitore.scrollTop = contenitore.scrollHeight;
}


// Funzione che trasforma una data e ora del backend ("2026-11-18T06:00:00") in "18/11 06:00"
function formattaDataOra(dataOra)
{
    return dataOra.slice(8, 10) + "/" + dataOra.slice(5, 7) + " " + dataOra.slice(11, 16);
}


// Funzione che trasforma una data del backend ("2026-11-18") in "18/11"
function formattaData(data)
{
    return data.slice(8, 10) + "/" + data.slice(5, 7);
}


/* Funzione che crea la scheda di un itinerario.
   - numero: posizione nella lista, parte da 1 (è il numero che l'assistente usa per salvarlo); null nel dettaglio di una prenotazione
   - conBottone: true se la scheda deve avere il pulsante "Scegli questo itinerario" (nella chat), false nel dettaglio */
function creaSchedaItinerario(itinerario, numero, conBottone)
{
    var scheda = document.getElementById("itinerary-template").content.cloneNode(true);

    if(numero != null)
    {
        scheda.querySelector(".itinerary-label").textContent = numero + ". " + itinerario.label;
    }
    else
    {
        scheda.querySelector(".itinerary-label").textContent = itinerario.label;
    }
    scheda.querySelector(".itinerary-trip").textContent = itinerario.city + ", dal " + formattaData(itinerario.departure_date) +
        " al " + formattaData(itinerario.return_date) + " (" + itinerario.nights + " notti, " + itinerario.travelers + " viaggiatori)";

    scheda.querySelector(".flight-out").textContent = "Andata: " + formattaDataOra(itinerario.flight_out.departure) + ", " +
        itinerario.flight_out.origin + " - " + itinerario.flight_out.destination + ", " + itinerario.flight_out.price_per_person + " euro a persona";
    scheda.querySelector(".flight-return").textContent = "Ritorno: " + formattaDataOra(itinerario.flight_return.departure) + ", " +
        itinerario.flight_return.origin + " - " + itinerario.flight_return.destination + ", " + itinerario.flight_return.price_per_person + " euro a persona";

    // Hotel: nome, stelle e camere scelte
    var camere = [];
    for(var i = 0; i < itinerario.hotel.rooms.length; i++)
    {
        camere.push(itinerario.hotel.rooms[i].name);
    }
    scheda.querySelector(".hotel-name").textContent = itinerario.hotel.name + " (" + itinerario.hotel.stars + " stelle)";
    scheda.querySelector(".hotel-rooms").textContent = "Camere: " + camere.join(", ");

    // Un'attività per ogni giorno (se per un giorno non ce ne sono: giorno libero)
    var elenco = scheda.querySelector(".days-list");
    for(var j = 0; j < itinerario.days.length; j++)
    {
        var giorno = document.createElement("li");
        if(itinerario.days[j].activity)
        {
            giorno.textContent = formattaData(itinerario.days[j].day) + ": " + itinerario.days[j].activity.name;
        }
        else
        {
            giorno.textContent = formattaData(itinerario.days[j].day) + ": giorno libero";
        }
        elenco.append(giorno);
    }

    scheda.querySelector(".itinerary-total").textContent = "Totale: " + itinerario.costs.total + " euro";

    // Il pulsante invia in chat la scelta dell'utente (nel dettaglio di una prenotazione non serve)
    var bottone = scheda.querySelector(".save-button");
    if(conBottone)
    {
        bottone.addEventListener("click", function()
        {
            inviaTesto("Prendo l'itinerario " + numero + ". Salvalo.");
        });
    }
    else
    {
        bottone.hidden = true;
    }

    return scheda;
}


// Funzione che mostra gli itinerari proposti dentro la chat, subito dopo l'ultimo messaggio
function mostraItinerari(itinerari)
{
    var contenitore = document.getElementById("messages");

    // L'assistente ricorda solo gli ultimi itinerari: nei gruppi precedenti il pulsante di scelta non vale più
    var vecchiBottoni = contenitore.querySelectorAll(".save-button");
    for(var k = 0; k < vecchiBottoni.length; k++)
    {
        vecchiBottoni[k].hidden = true;
    }

    var gruppo = document.createElement("div");
    gruppo.className = "itineraries-group";

    for(var i = 0; i < itinerari.length; i++)
    {
        gruppo.append(creaSchedaItinerario(itinerari[i], i + 1, true));
    }

    contenitore.append(gruppo);
    gruppo.scrollIntoView({block: "start"});
}


// Funzione che invia un testo all'assistente e mostra la risposta
async function inviaTesto(testo)
{
    aggiungiMessaggio("Tu", testo);
    document.getElementById("typing").hidden = false;

    try
    {
        var risposta = await chiamaApi("/chat", "POST", {conversation_id: idConversazione, message: testo}, null);

        idConversazione = risposta.conversation_id;
        aggiungiMessaggio("Assistente", risposta.reply);

        // Se l'assistente ha generato nuovi itinerari li mostro
        if(risposta.itineraries)
        {
            mostraItinerari(risposta.itineraries);
        }
    }
    catch(errore)
    {
        alert(errore.message);
    }

    document.getElementById("typing").hidden = true;
}


// Funzione chiamata quando l'utente invia il form della chat
function inviaMessaggio(evento)
{
    evento.preventDefault();

    var campo = document.getElementById("chat-input");
    var testo = campo.value.trim();

    if(testo == "")
    {
        return;
    }

    campo.value = "";
    inviaTesto(testo);
}


// Funzione che svuota la chat e inizia una conversazione nuova
function azzeraChat()
{
    idConversazione = null;
    document.getElementById("messages").replaceChildren();
}
