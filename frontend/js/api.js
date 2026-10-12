"use strict";

// Indirizzo del backend
var URL_API = "http://localhost:8000/api";


// Funzioni per leggere, salvare e cancellare il token di accesso nel browser
function leggiToken()
{
    return localStorage.getItem("token");
}

function salvaToken(token)
{
    localStorage.setItem("token", token);
}

function cancellaToken()
{
    localStorage.removeItem("token");
}


// Funzione che restituisce il messaggio d'errore inviato dal backend (campo "detail"), oppure un messaggio generico
async function leggiErrore(risposta)
{
    try
    {
        var dati = await risposta.json();

        // Di solito "detail" è una stringa, ma per gli errori di validazione (422) è una lista
        if(typeof dati.detail == "string")
        {
            return dati.detail;
        }
        if(Array.isArray(dati.detail))
        {
            var messaggi = [];
            for(var i = 0; i < dati.detail.length; i++)
            {
                messaggi.push(dati.detail[i].msg);
            }
            return messaggi.join("; ");
        }
    }
    catch(errore)
    {
        // La risposta non era in formato JSON: uso il messaggio generico
    }

    return "Errore " + risposta.status;
}


/* Funzione che invia una richiesta al backend. Restituisce i dati della risposta oppure lancia un errore con il messaggio del backend.
   - corpo: oggetto da inviare in formato JSON (oppure null)
   - modulo: oggetto da inviare come modulo, serve solo per il login (oppure null) */
async function chiamaApi(percorso, metodo, corpo, modulo)
{
    var intestazioni = {};
    var dati = null;
    var token = leggiToken();

    // Se l'utente ha fatto il login, il token viene inviato in ogni richiesta
    if(token)
    {
        intestazioni["Authorization"] = "Bearer " + token;
    }

    if(modulo)
    {
        intestazioni["Content-Type"] = "application/x-www-form-urlencoded";
        dati = new URLSearchParams(modulo);
    }
    else if(corpo)
    {
        intestazioni["Content-Type"] = "application/json";
        dati = JSON.stringify(corpo);
    }

    var risposta = await fetch(URL_API + percorso, {method: metodo, headers: intestazioni, body: dati});

    // Se il token è scaduto o non è valido lo cancello e torno alla pagina di accesso
    if(risposta.status == 401 && token)
    {
        cancellaToken();
        utenteCorrente = null;
        mostraVista();
    }

    if(!risposta.ok)
    {
        throw new Error(await leggiErrore(risposta));
    }

    return await risposta.json();
}
