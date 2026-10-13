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


// Funzione che controlla il formato dell'email: qualcosa, una chiocciola, un dominio con almeno un punto
function emailValida(email)
{
    var modello = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

    return modello.test(email);
}


// Funzione che controlla i dati della registrazione con le stesse regole del backend. Restituisce true se sono tutti validi
function validaFormRegistrazione(nome, email, password)
{
    // Prima i campi vuoti: li elenco tutti insieme
    var mancanti = [];
    if(nome == "")
    {
        mancanti.push("Nome");
    }
    if(email == "")
    {
        mancanti.push("Email");
    }
    if(password == "")
    {
        mancanti.push("Password");
    }
    if(mancanti.length > 0)
    {
        alert("Non hai inserito i seguenti campi: " + mancanti.join(", "));
        return false;
    }

    // Poi il formato di ogni campo: mi fermo al primo errore
    if(nome.length > 100)
    {
        alert("Il nome può avere al massimo 100 caratteri!");
        return false;
    }
    if(!emailValida(email))
    {
        alert("L'email non è valida! Deve essere nel formato nome@dominio.it");
        return false;
    }
    if(password.trim() == "")
    {
        alert("La password non può contenere solo spazi!");
        return false;
    }
    if(password.length < 8)
    {
        alert("La password deve avere almeno 8 caratteri!");
        return false;
    }
    // Il backend accetta al massimo 72 byte: le lettere accentate ne occupano 2
    if(new TextEncoder().encode(password).length > 72)
    {
        alert("La password è troppo lunga! Massimo 72 byte (le lettere accentate ne occupano di più).");
        return false;
    }

    return true;
}


// Funzione chiamata quando l'utente invia il form di registrazione
async function inviaRegistrazione(evento)
{
    evento.preventDefault();

    var form = evento.target;
    var nome = form.elements["name"].value.trim();  // form.name sarebbe il nome del form, non il campo
    var email = form.email.value.trim();
    var password = form.password.value;

    // Verifico che i dati inseriti siano completi e nel formato giusto
    if(!validaFormRegistrazione(nome, email, password))
    {
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
