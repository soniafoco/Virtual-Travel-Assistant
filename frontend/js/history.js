"use strict";

// Funzione che trasforma una data e ora del backend ("2026-11-18T10:30:00") in "18/11/2026 10:30"
function formattaDataCompleta(dataOra)
{
    return dataOra.slice(8, 10) + "/" + dataOra.slice(5, 7) + "/" + dataOra.slice(0, 4) + " " + dataOra.slice(11, 16);
}


// Funzione che crea la scheda di una chat precedente. Ogni chat ha i campi: id, title, last_message_at, messages_count
function creaSchedaChat(chat)
{
    var scheda = document.getElementById("history-template").content.cloneNode(true);

    scheda.querySelector(".history-title").textContent = chat.title;
    scheda.querySelector(".history-info").textContent = formattaDataCompleta(chat.last_message_at) + " - " + chat.messages_count + " messaggi";

    scheda.querySelector(".open-chat-button").addEventListener("click", function() { apriChat(chat.id, chat.title); });

    return scheda;
}


// Funzione che chiede al backend le chat dell'utente e le mostra
async function caricaStorico()
{
    var lista = document.getElementById("history-list");

    try
    {
        var chat = await chiamaApi("/conversations", "GET", null, null);

        mostraElencoChat();
        lista.replaceChildren();
        for(var i = 0; i < chat.length; i++)
        {
            lista.append(creaSchedaChat(chat[i]));
        }

        document.getElementById("history-empty").hidden = (chat.length > 0);
    }
    catch(errore)
    {
        lista.replaceChildren();
        alert(errore.message);
    }
}


// Funzione che mostra l'elenco delle chat e nasconde il dettaglio
function mostraElencoChat()
{
    document.getElementById("history-detail").hidden = true;
    document.getElementById("history-list").hidden = false;
    document.getElementById("history-empty").hidden = (document.getElementById("history-list").children.length > 0);
}


// Funzione che apre una chat precedente in sola lettura, in questa pagina: la chat in corso resta com'è
async function apriChat(id, titolo)
{
    try
    {
        var chat = await chiamaApi("/conversations/" + id, "GET", null, null);

        var contenitore = document.getElementById("history-messages");
        contenitore.replaceChildren();

        for(var i = 0; i < chat.messages.length; i++)
        {
            if(chat.messages[i].role == "user")
            {
                aggiungiMessaggio("Tu", chat.messages[i].content, contenitore);
            }
            else
            {
                aggiungiMessaggio("Assistente", chat.messages[i].content, contenitore);
            }
        }

        // Anche gli ultimi itinerari proposti, senza il pulsante di scelta
        if(chat.itineraries.length > 0)
        {
            var gruppo = document.createElement("div");
            gruppo.className = "itineraries-group";
            for(var j = 0; j < chat.itineraries.length; j++)
            {
                gruppo.append(creaSchedaItinerario(chat.itineraries[j], j + 1, false));
            }
            contenitore.append(gruppo);
        }

        document.getElementById("history-detail-title").textContent = titolo;
        document.getElementById("history-list").hidden = true;
        document.getElementById("history-empty").hidden = true;
        document.getElementById("history-detail").hidden = false;
        contenitore.scrollTop = 0;
    }
    catch(errore)
    {
        alert(errore.message);
    }
}
