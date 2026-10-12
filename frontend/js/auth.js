"use strict";

// L'utente collegato (oppure null se nessuno ha fatto il login)
var utenteCorrente = null;


// Funzione che chiede al backend chi è l'utente del token salvato nel browser (se c'è)
async function caricaUtente()
{
    utenteCorrente = null;

    if(!leggiToken())
    {
        return;
    }

    try
    {
        utenteCorrente = await chiamaApi("/auth/me", "GET", null, null);
    }
    catch(errore)
    {
        // Il token non è più valido: lo cancello
        cancellaToken();
    }
}


// Funzione che effettua il login: il backend restituisce il token, che viene salvato nel browser
async function accedi(email, password)
{
    // Il login usa un modulo (non JSON) e l'email va nel campo "username"
    var risposta = await chiamaApi("/auth/login", "POST", null, {username: email, password: password});

    salvaToken(risposta.access_token);
    await caricaUtente();
}


// Funzione chiamata quando l'utente invia il form di login
async function inviaLogin(evento)
{
    evento.preventDefault();

    var form = evento.target;
    var email = form.email.value.trim();
    var password = form.password.value;

    // Verifico se l'utente ha inserito tutti i campi del form
    if(email == "" && password == "")
    {
        alert("Non hai inserito l'email e la password!");
        return;
    }
    else if(email == "")
    {
        alert("Non hai inserito l'email!");
        return;
    }
    else if(password == "")
    {
        alert("Non hai inserito la password!");
        return;
    }

    try
    {
        await accedi(email, password);
        form.reset();
        dopoCambioUtente();
    }
    catch(errore)
    {
        alert(errore.message);
    }
}


// Funzione chiamata quando l'utente invia il form di registrazione
async function inviaRegistrazione(evento)
{
    evento.preventDefault();

    var form = evento.target;
    var nome = form.elements["name"].value.trim();  // form.name sarebbe il nome del form, non il campo
    var email = form.email.value.trim();
    var password = form.password.value;

    // Verifico se l'utente ha inserito tutti i campi del form
    if(nome == "" || email == "" || password == "")
    {
        alert("Devi inserire nome, email e password!");
        return;
    }

    try
    {
        await chiamaApi("/auth/register", "POST", {name: nome, email: email, password: password}, null);

        // Dopo la registrazione l'utente entra direttamente
        await accedi(email, password);
        form.reset();
        dopoCambioUtente();
    }
    catch(errore)
    {
        alert(errore.message);
    }
}


// Funzione chiamata quando l'utente clicca su "Esci"
function esci()
{
    if(!confirm("Sei sicuro di voler effettuare il logout?"))
    {
        return;
    }

    cancellaToken();
    utenteCorrente = null;
    dopoCambioUtente();
}
