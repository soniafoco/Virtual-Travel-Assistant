"use strict";

// Funzione che sceglie la vista da mostrare in base all'indirizzo della pagina (#auth, #chat, #history oppure #bookings)
function mostraVista()
{
    var vista = location.hash.slice(1);

    if(vista != "auth" && vista != "chat" && vista != "history" && vista != "bookings")
    {
        vista = "chat";
    }

    // Senza utente collegato si può vedere solo la pagina di accesso, che invece non serve più dopo il login
    if(utenteCorrente == null)
    {
        vista = "auth";
    }
    else if(vista == "auth")
    {
        vista = "chat";
    }

    // Se l'indirizzo non corrisponde alla vista, lo aggiorno: l'evento hashchange richiamerà questa funzione
    if(location.hash != "#" + vista)
    {
        location.hash = "#" + vista;
        return;
    }

    // Mostro la sezione scelta e nascondo le altre
    var sezioni = document.querySelectorAll("[data-view]");
    for(var i = 0; i < sezioni.length; i++)
    {
        sezioni[i].hidden = (sezioni[i].dataset.view != vista);
    }

    // Il menu si vede solo se l'utente è collegato
    document.getElementById("main-nav").hidden = (utenteCorrente == null);
    if(utenteCorrente != null)
    {
        document.getElementById("user-name").textContent = utenteCorrente.name;
    }

    // Evidenzio nel menu la voce della pagina in cui ci si trova
    var voci = document.querySelectorAll("#main-nav a");
    for(var j = 0; j < voci.length; j++)
    {
        voci[j].classList.toggle("active", voci[j].dataset.link == vista);
    }

    if(vista == "history")
    {
        caricaStorico();
    }
    else if(vista == "bookings")
    {
        caricaPrenotazioni();
    }
}


// Funzione chiamata dopo un login o un logout: riparto da una chat vuota
function dopoCambioUtente()
{
    azzeraChat();
    mostraVista();
}


// Funzione chiamata quando l'utente clicca su un suggerimento: la frase va nel campo di testo, pronta da inviare o modificare
function usaSuggerimento(evento)
{
    var campo = document.getElementById("chat-input");
    campo.value = evento.currentTarget.dataset.text;
    campo.focus();
}


// Funzione chiamata all'apertura della pagina: collega i form e le funzioni, poi mostra la vista giusta
async function avvia()
{
    document.getElementById("login-form").addEventListener("submit", inviaLogin);
    document.getElementById("register-form").addEventListener("submit", inviaRegistrazione);
    document.getElementById("chat-form").addEventListener("submit", inviaMessaggio);
    document.getElementById("new-chat-button").addEventListener("click", azzeraChat);
    document.getElementById("history-back-button").addEventListener("click", mostraElencoChat);
    document.getElementById("logout-button").addEventListener("click", esci);
    window.addEventListener("hashchange", mostraVista);

    // I pulsanti dei suggerimenti nella colonna laterale della chat scrivono la frase nel campo di testo
    var suggerimenti = document.querySelectorAll(".suggestion");
    for(var i = 0; i < suggerimenti.length; i++)
    {
        suggerimenti[i].addEventListener("click", usaSuggerimento);
    }

    // La finestra del dettaglio si chiude con la X oppure cliccando fuori dalla finestra
    var finestra = document.getElementById("booking-dialog");
    document.getElementById("close-dialog").addEventListener("click", function() { finestra.close(); });
    finestra.addEventListener("click", function(evento)
    {
        if(evento.target == finestra)
        {
            finestra.close();
        }
    });

    await caricaUtente();
    mostraVista();
}

avvia();
