"""L'agente della chat: un modello Gemini che usa i tool di agent_tools.

Il modello conversa e raccoglie i requisiti; prezzi, date e disponibilita' li danno solo i tool.
"""

import logging

from langchain.agents import create_agent
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.config import settings
from app.core.logging import tronca
from app.services.agent_tools import AgentContext, build_tools, testo_stato

SYSTEM_PROMPT = """Sei l'assistente di viaggio di Virtual Travel Assistant. Parli in italiano, in modo cordiale e conciso.

Il tuo compito e' aiutare l'utente a organizzare un viaggio: volo di andata e ritorno, hotel per ogni notte e
un'attivita' per ogni giorno.

Per costruire gli itinerari ti servono questi dati:
- budget totale in euro;
- nazione di destinazione;
- preferenze sulle attivita': libere, qualsiasi cosa interessi all'utente (es. sport, relax, cultura, vita
  notturna, "con i bambini", kayak);
- mese di partenza;
- numero di viaggiatori;
- aeroporto di partenza (codice IATA, es. FCO): se l'utente dice un nome o una citta' (es. "Fiumicino"),
  traducilo con find_airport; se ce n'e' piu' di uno chiedi quale preferisce, e proponi solo quelli con voli;
- durata in notti: facoltativa, se l'utente non la dice usa 7;
- data di partenza esatta: facoltativa. Se l'utente dice giorni precisi (es. "dal 13 al 18 novembre") passa
  departure_date (AAAA-MM-GG) e calcola le notti come differenza tra ritorno e partenza (13-18 = 5 notti).
  Se poi li cambia, richiama generate_itineraries con la nuova departure_date e le nuove notti. Non dire mai
  di aver cambiato le date senza aver richiamato il tool. L'anno e' il prossimo in cui cade quella data.

Regole:
- Ogni volta che l'utente dice o cambia uno di questi dati, chiama subito update_requirements con quel dato
  (solo i dati nuovi). In fondo a questo messaggio trovi sempre l'elenco dei dati gia' raccolti e di quelli
  mancanti: fidati di quello, non della cronologia, e non richiedere un dato che e' gia' raccolto.
- Chiedi solo i dati che mancano, uno o due per volta. Non inventarli.
- Il mese va passato ai tool come numero da 1 a 12 (gennaio = 1, ..., dicembre = 12).
- Se search_activities non trova nulla di affine a una preferenza, dillo all'utente e chiedigli un'altra
  preferenza: non proporre attivita' che non c'entrano.
- Non conosci prezzi, date e disponibilita': usa sempre i tool. Non stimare mai una cifra o altri dettagli.
- Se l'utente e' indeciso o chiede informazioni, aiutalo con list_destinations, list_hotels, list_flight_dates e search_activities
  prima di costruire il piano.
- Quando hai tutti i dati chiama generate_itineraries. Presenta gli itinerari con il loro numero e la loro
  etichetta: citta', date, voli, hotel, attivita' giorno per giorno e costo totale. Spiega in breve le differenze
  e consiglia quello che ti sembra piu' adatto.
- Se non ci sono itinerari, spiega il motivo restituito dal tool. Se manca budget, di' quanto serve almeno e
  proponi di alzarlo, di ridurre le notti o di cambiare mese o destinazione.
- Se l'utente chiede modifiche, richiama generate_itineraries con i parametri nuovi: non ricalcolare nulla a mano.
- Dopo generate_itineraries NON salvare nulla: gli itinerari mostrati sono solo suggerimenti e non vanno in
  save_proposal. Chiama save_proposal solo quando l'utente dice in modo esplicito quale itinerario vuole
  salvare o scegliere, e salva solo quello (un solo numero, mai tutti). Dì chiaramente che e' una proposta e
  non ancora una prenotazione confermata, e chiedi se vuole confermarla.
- Prenota (confirm_booking) o annulla (cancel_booking) solo se l'utente lo chiede in modo esplicito: sono azioni
  reali. Se il tool dice che qualcosa non e' piu' disponibile, spiegalo e proponi di rigenerare gli itinerari.
  Con list_my_bookings puoi mostrare le prenotazioni dell'utente (e trovare l'id da annullare).
"""

logger = logging.getLogger("app.agent")


class LogAgente(BaseCallbackHandler):
    """Scrive nel log ogni passaggio dell'agente: messaggi al modello, risposte, tool chiamati e risultati."""

    def __init__(self):
        self.nomi_tool = {}  # id della chiamata -> nome del tool (serve a scrivere il nome anche alla fine)

    # Input del modello: l'ultimo messaggio ricevuto (messaggio dell'utente oppure risultato di un tool)
    def on_chat_model_start(self, serialized, messages, **kwargs):
        ultimo = messages[0][-1]
        logger.info("LLM INPUT  (%d messaggi) [%s] %s", len(messages[0]), ultimo.type, tronca(ultimo.text))

    # Output del modello: il testo della risposta e gli eventuali tool che vuole chiamare
    def on_llm_end(self, response, **kwargs):
        messaggio = response.generations[0][0].message
        richieste = [chiamata["name"] for chiamata in messaggio.tool_calls]
        logger.info("LLM OUTPUT %s | tool richiesti: %s", tronca(messaggio.text) or "-", richieste or "-")

    def on_llm_error(self, error, **kwargs):
        logger.error("LLM ERRORE %s: %s", type(error).__name__, tronca(error))

    def on_tool_start(self, serialized, input_str, run_id=None, **kwargs):
        nome = kwargs.get("name") or serialized.get("name")
        self.nomi_tool[run_id] = nome
        logger.info("TOOL INPUT  %s %s", nome, tronca(input_str))

    def on_tool_end(self, output, run_id=None, **kwargs):
        nome = self.nomi_tool.pop(run_id, "?")
        logger.info("TOOL OUTPUT %s %s", nome, tronca(getattr(output, "content", output)))

    def on_tool_error(self, error, run_id=None, **kwargs):
        nome = self.nomi_tool.pop(run_id, "?")
        logger.error("TOOL ERRORE %s: %s", nome, tronca(error))


def build_model(provider: str | None = None) -> BaseChatModel:
    """Gemini (default), Groq o un modello Hugging Face: `provider` o, se omesso, llm_provider di config.yaml."""
    options = {} if settings.llm_temperature is None else {"temperature": settings.llm_temperature}
    provider = provider or settings.llm_provider
    if provider == "groq":
        from langchain_groq import ChatGroq

        return ChatGroq(model=settings.groq_model, api_key=settings.groq_api_key, **options)
    if provider == "huggingface":
        from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint

        endpoint = HuggingFaceEndpoint(
            repo_id=settings.hf_model, task="text-generation", huggingfacehub_api_token=settings.hf_token,
            max_new_tokens=settings.hf_max_new_tokens, **options,
        )
        return ChatHuggingFace(llm=endpoint)
    return ChatGoogleGenerativeAI(model=settings.gemini_model, google_api_key=settings.gemini_api_key, **options)

def build_agent(ctx: AgentContext, model: BaseChatModel | None = None):
    """Un agente legato al contesto di una conversazione. `model` e' iniettabile per i test."""
    # lo stato della conversazione (dati raccolti e mancanti) e' in fondo al prompt: il modello lo vede anche se la cronologia e' stata tagliata
    prompt = SYSTEM_PROMPT + "\n" + testo_stato(ctx.state)
    agent = create_agent(model or build_model(), build_tools(ctx), system_prompt=prompt)
    return agent.with_config(callbacks=[LogAgente()], run_name="agente-viaggi")  # ogni chiamata dell'agente finisce nel log

def reply(agent, history: list[dict], session_id: str | None = None) -> str:
    """Risposta dell'agente alla conversazione (lista di {"role": "user"|"assistant", "content": ...}).

    `session_id` e' l'id della chat: Phoenix raggruppa nella scheda Sessions tutte le trace con lo stesso valore."""
    config = {}
    if session_id is not None:
        config = {"metadata": {"session_id": session_id}}  # l'instrumentor lo salva come attributo session.id
    result = agent.invoke({"messages": history}, config=config)
    return result["messages"][-1].text
