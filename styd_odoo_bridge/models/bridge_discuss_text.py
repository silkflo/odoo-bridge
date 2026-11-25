"""Discuss assistant: what the bot says, and how STYD's answers become a message.

Pure Python (no ORM, no I/O). Everything that comes from STYD or from a user
is DATA: it is escaped, never interpreted, and the only markup in a posted
message is the markup built here (paragraphs, line breaks, a table, an
emphasis). Text that looks like a secret is hidden before anything is posted.
Contract: docs/DISCUSS_CONTRACT.md.
"""

import math
import re

from markupsafe import Markup, escape

from . import bridge_channel_protocol as proto

QUESTION_MAX = 2000
ANSWER_TEXT_MAX = 8000
UNDERSTOOD_MAX = 500
MESSAGE_MAX = 1000
TITLE_MAX = 200
TABLES_MAX = 5
COLUMNS_MAX = 20
ROWS_MAX = 200
CELL_MAX = 500
CODE_RE = re.compile(r"^[a-z_]{1,64}$")
LANG_RE = re.compile(r"^[A-Za-z]{2,3}(_[A-Za-z0-9]{2,4})?(@[A-Za-z]+)?$")

ANSWER_STATUSES = ("answered", "refused", "error")

LANGS = ("en", "fr", "es", "de", "it", "nl", "pt")

# key -> {lang: text}. Kept short: the bot speaks in one line.
MESSAGES = {
    "welcome": {
        "en": "Hello, I'm Speak To Your Database. Ask me questions about your Odoo data here, or mention me in a channel. I answer with your own Odoo access rights.",
        "fr": "Bonjour, je suis Speak To Your Database. Posez-moi ici vos questions sur vos données Odoo, ou mentionnez-moi dans un canal. Je réponds avec vos propres droits d'accès Odoo.",
        "es": "Hola, soy Speak To Your Database. Hágame aquí preguntas sobre sus datos de Odoo, o mencióneme en un canal. Respondo con sus propios permisos de Odoo.",
        "de": "Hallo, ich bin Speak To Your Database. Stellen Sie mir hier Fragen zu Ihren Odoo-Daten oder erwähnen Sie mich in einem Kanal. Ich antworte mit Ihren eigenen Odoo-Zugriffsrechten.",
        "it": "Ciao, sono Speak To Your Database. Mi faccia qui domande sui suoi dati Odoo, o mi menzioni in un canale. Rispondo con i suoi permessi Odoo.",
        "nl": "Hallo, ik ben Speak To Your Database. Stel mij hier vragen over uw Odoo-gegevens, of noem mij in een kanaal. Ik antwoord met uw eigen Odoo-toegangsrechten.",
        "pt": "Olá, sou o Speak To Your Database. Faça-me aqui perguntas sobre os seus dados do Odoo, ou mencione-me num canal. Respondo com os seus próprios acessos do Odoo.",
    },
    "answered_in_dm": {
        "en": "I've answered you in a direct message.",
        "fr": "Je vous ai répondu en message direct.",
        "es": "Le he respondido en un mensaje directo.",
        "de": "Ich habe Ihnen in einer Direktnachricht geantwortet.",
        "it": "Le ho risposto in un messaggio diretto.",
        "nl": "Ik heb u geantwoord in een direct bericht.",
        "pt": "Respondi-lhe numa mensagem direta.",
    },
    "looking": {
        "en": "Looking it up…",
        "fr": "Je cherche…",
        "es": "Lo estoy buscando…",
        "de": "Ich schaue nach…",
        "it": "Sto cercando…",
        "nl": "Ik zoek het op…",
        "pt": "A procurar…",
    },
    "not_allowed": {
        "en": "You can't ask Speak To Your Database in Odoo yet. Please ask your Odoo administrator for access.",
        "fr": "Vous ne pouvez pas encore interroger Speak To Your Database dans Odoo. Demandez l'accès à votre administrateur Odoo.",
        "es": "Todavía no puede preguntar a Speak To Your Database en Odoo. Pida acceso a su administrador de Odoo.",
        "de": "Sie können Speak To Your Database in Odoo noch nicht fragen. Bitten Sie Ihren Odoo-Administrator um Zugang.",
        "it": "Non può ancora fare domande a Speak To Your Database in Odoo. Chieda l'accesso al suo amministratore Odoo.",
        "nl": "U kunt Speak To Your Database in Odoo nog niets vragen. Vraag uw Odoo-beheerder om toegang.",
        "pt": "Ainda não pode perguntar ao Speak To Your Database no Odoo. Peça acesso ao seu administrador do Odoo.",
    },
    "disabled": {
        "en": "The Speak To Your Database assistant is switched off in this Odoo. Please ask your Odoo administrator.",
        "fr": "L'assistant Speak To Your Database est désactivé dans cet Odoo. Demandez à votre administrateur Odoo.",
        "es": "El asistente de Speak To Your Database está desactivado en este Odoo. Consulte a su administrador de Odoo.",
        "de": "Der Speak To Your Database-Assistent ist in diesem Odoo ausgeschaltet. Fragen Sie Ihren Odoo-Administrator.",
        "it": "L'assistente Speak To Your Database è disattivato in questo Odoo. Chieda al suo amministratore Odoo.",
        "nl": "De Speak To Your Database-assistent staat uit in deze Odoo. Vraag het uw Odoo-beheerder.",
        "pt": "O assistente Speak To Your Database está desligado neste Odoo. Fale com o seu administrador do Odoo.",
    },
    "not_connected": {
        "en": "This Odoo is not connected to Speak To Your Database right now. Please ask your Odoo administrator.",
        "fr": "Cet Odoo n'est pas connecté à Speak To Your Database pour le moment. Demandez à votre administrateur Odoo.",
        "es": "Este Odoo no está conectado a Speak To Your Database en este momento. Consulte a su administrador de Odoo.",
        "de": "Dieses Odoo ist gerade nicht mit Speak To Your Database verbunden. Fragen Sie Ihren Odoo-Administrator.",
        "it": "Questo Odoo non è collegato a Speak To Your Database in questo momento. Chieda al suo amministratore Odoo.",
        "nl": "Deze Odoo is nu niet verbonden met Speak To Your Database. Vraag het uw Odoo-beheerder.",
        "pt": "Este Odoo não está ligado ao Speak To Your Database neste momento. Fale com o seu administrador do Odoo.",
    },
    "rate_user": {
        "en": "You have asked many questions in a short time. Please try again in a few minutes.",
        "fr": "Vous avez posé beaucoup de questions en peu de temps. Réessayez dans quelques minutes.",
        "es": "Ha hecho muchas preguntas en poco tiempo. Vuelva a intentarlo en unos minutos.",
        "de": "Sie haben in kurzer Zeit viele Fragen gestellt. Bitte versuchen Sie es in ein paar Minuten erneut.",
        "it": "Ha fatto molte domande in poco tempo. Riprovi tra qualche minuto.",
        "nl": "U hebt veel vragen gesteld in korte tijd. Probeer het over een paar minuten opnieuw.",
        "pt": "Fez muitas perguntas em pouco tempo. Tente novamente dentro de alguns minutos.",
    },
    "rate_db": {
        "en": "This Odoo has reached its limit of questions for now. Please try again later.",
        "fr": "Cet Odoo a atteint sa limite de questions pour le moment. Réessayez plus tard.",
        "es": "Este Odoo ha alcanzado su límite de preguntas por ahora. Vuelva a intentarlo más tarde.",
        "de": "Dieses Odoo hat sein Fragenlimit vorerst erreicht. Bitte versuchen Sie es später erneut.",
        "it": "Questo Odoo ha raggiunto per ora il limite di domande. Riprovi più tardi.",
        "nl": "Deze Odoo heeft voorlopig het maximum aantal vragen bereikt. Probeer het later opnieuw.",
        "pt": "Este Odoo atingiu o limite de perguntas por agora. Tente novamente mais tarde.",
    },
    "empty": {
        "en": "Ask me a question about your data, for example: \"What were our sales last month?\"",
        "fr": "Posez-moi une question sur vos données, par exemple : « Quelles ont été nos ventes le mois dernier ? »",
        "es": "Hágame una pregunta sobre sus datos, por ejemplo: «¿Cuánto vendimos el mes pasado?»",
        "de": "Stellen Sie mir eine Frage zu Ihren Daten, zum Beispiel: „Wie hoch war unser Umsatz letzten Monat?“",
        "it": "Mi faccia una domanda sui suoi dati, per esempio: «Quanto abbiamo venduto il mese scorso?»",
        "nl": "Stel mij een vraag over uw gegevens, bijvoorbeeld: \"Wat was onze omzet vorige maand?\"",
        "pt": "Faça-me uma pergunta sobre os seus dados, por exemplo: «Quanto vendemos no mês passado?»",
    },
    "unreachable": {
        "en": "I could not reach Speak To Your Database. Please try again in a moment.",
        "fr": "Je n'ai pas pu joindre Speak To Your Database. Réessayez dans un instant.",
        "es": "No he podido contactar con Speak To Your Database. Vuelva a intentarlo en un momento.",
        "de": "Ich konnte Speak To Your Database nicht erreichen. Bitte versuchen Sie es gleich noch einmal.",
        "it": "Non sono riuscito a raggiungere Speak To Your Database. Riprovi tra un momento.",
        "nl": "Ik kon Speak To Your Database niet bereiken. Probeer het zo meteen opnieuw.",
        "pt": "Não consegui contactar o Speak To Your Database. Tente novamente daqui a pouco.",
    },
    "timeout": {
        "en": "Speak To Your Database did not answer in time. Please try again.",
        "fr": "Speak To Your Database n'a pas répondu à temps. Réessayez.",
        "es": "Speak To Your Database no respondió a tiempo. Vuelva a intentarlo.",
        "de": "Speak To Your Database hat nicht rechtzeitig geantwortet. Bitte versuchen Sie es erneut.",
        "it": "Speak To Your Database non ha risposto in tempo. Riprovi.",
        "nl": "Speak To Your Database heeft niet op tijd geantwoord. Probeer het opnieuw.",
        "pt": "O Speak To Your Database não respondeu a tempo. Tente novamente.",
    },
    "error": {
        "en": "Something went wrong while answering. Please try again.",
        "fr": "Un problème est survenu pendant la réponse. Réessayez.",
        "es": "Algo salió mal al responder. Vuelva a intentarlo.",
        "de": "Beim Antworten ist ein Fehler aufgetreten. Bitte versuchen Sie es erneut.",
        "it": "Qualcosa è andato storto durante la risposta. Riprovi.",
        "nl": "Er ging iets mis bij het antwoorden. Probeer het opnieuw.",
        "pt": "Algo correu mal ao responder. Tente novamente.",
    },
    "refused": {
        "en": "Speak To Your Database cannot answer this question.",
        "fr": "Speak To Your Database ne peut pas répondre à cette question.",
        "es": "Speak To Your Database no puede responder a esta pregunta.",
        "de": "Speak To Your Database kann diese Frage nicht beantworten.",
        "it": "Speak To Your Database non può rispondere a questa domanda.",
        "nl": "Speak To Your Database kan deze vraag niet beantwoorden.",
        "pt": "O Speak To Your Database não pode responder a esta pergunta.",
    },
    "discuss_off": {
        "en": "The Discuss assistant is not switched on for this workspace in Speak To Your Database. Please ask your administrator.",
        "fr": "L'assistant Discuss n'est pas activé pour cet espace dans Speak To Your Database. Demandez à votre administrateur.",
        "es": "El asistente de Discuss no está activado para este espacio en Speak To Your Database. Consulte a su administrador.",
        "de": "Der Discuss-Assistent ist für diesen Arbeitsbereich in Speak To Your Database nicht eingeschaltet. Fragen Sie Ihren Administrator.",
        "it": "L'assistente Discuss non è attivo per questo spazio in Speak To Your Database. Chieda al suo amministratore.",
        "nl": "De Discuss-assistent staat niet aan voor deze werkruimte in Speak To Your Database. Vraag het uw beheerder.",
        "pt": "O assistente do Discuss não está ativo para este espaço no Speak To Your Database. Fale com o seu administrador.",
    },
    "member_unknown": {
        "en": "Your Odoo user is not linked to a Speak To Your Database member. Please ask your administrator.",
        "fr": "Votre utilisateur Odoo n'est lié à aucun membre de Speak To Your Database. Demandez à votre administrateur.",
        "es": "Su usuario de Odoo no está vinculado a ningún miembro de Speak To Your Database. Consulte a su administrador.",
        "de": "Ihr Odoo-Benutzer ist mit keinem Mitglied von Speak To Your Database verknüpft. Fragen Sie Ihren Administrator.",
        "it": "Il suo utente Odoo non è collegato a un membro di Speak To Your Database. Chieda al suo amministratore.",
        "nl": "Uw Odoo-gebruiker is niet gekoppeld aan een lid van Speak To Your Database. Vraag het uw beheerder.",
        "pt": "O seu utilizador do Odoo não está ligado a um membro do Speak To Your Database. Fale com o seu administrador.",
    },
    "prompts_exhausted": {
        "en": "The Speak To Your Database plan has no questions left for now. Please ask your administrator.",
        "fr": "Le forfait Speak To Your Database n'a plus de questions disponibles pour le moment. Demandez à votre administrateur.",
        "es": "El plan de Speak To Your Database no tiene más preguntas disponibles por ahora. Consulte a su administrador.",
        "de": "Im Speak To Your Database-Tarif sind vorerst keine Fragen mehr übrig. Fragen Sie Ihren Administrator.",
        "it": "Il piano Speak To Your Database non ha più domande disponibili per ora. Chieda al suo amministratore.",
        "nl": "Het Speak To Your Database-abonnement heeft voorlopig geen vragen meer over. Vraag het uw beheerder.",
        "pt": "O plano do Speak To Your Database não tem mais perguntas disponíveis por agora. Fale com o seu administrador.",
    },
    "understood_as": {
        "en": "Understood as", "fr": "Compris comme", "es": "Entendido como", "de": "Verstanden als",
        "it": "Inteso come", "nl": "Begrepen als", "pt": "Entendido como",
    },
    "rows_shown": {
        "en": "Showing {shown} of {total} rows.",
        "fr": "{shown} lignes affichées sur {total}.",
        "es": "Se muestran {shown} de {total} filas.",
        "de": "{shown} von {total} Zeilen angezeigt.",
        "it": "Mostrate {shown} righe su {total}.",
        "nl": "{shown} van {total} rijen getoond.",
        "pt": "A mostrar {shown} de {total} linhas.",
    },
    "pairing_waiting": {
        "en": "A Speak To Your Database workspace asks to connect to this Odoo: {name} (workspace id {ref}, email domain of the person who typed the code: {domain}). Nothing is read until you approve it in Speak To Your Database Bridge > Connect without opening a port. If you did not start this pairing, refuse it there.",
        "fr": "Un espace Speak To Your Database demande à se connecter à cet Odoo : {name} (id d'espace {ref}, domaine e-mail de la personne qui a saisi le code : {domain}). Rien n'est lu tant que vous ne l'approuvez pas dans Speak To Your Database Bridge > Connect without opening a port. Si vous n'avez pas lancé cet appairage, refusez-le là.",
        "es": "Un espacio de Speak To Your Database pide conectarse a este Odoo: {name} (id de espacio {ref}, dominio de correo de quien escribió el código: {domain}). No se lee nada hasta que lo apruebe en Speak To Your Database Bridge > Connect without opening a port. Si no inició esta vinculación, recházela allí.",
        "de": "Ein Speak To Your Database-Arbeitsbereich möchte sich mit diesem Odoo verbinden: {name} (Arbeitsbereich-ID {ref}, E-Mail-Domain der Person, die den Code eingegeben hat: {domain}). Es wird nichts gelesen, bis Sie ihn unter Speak To Your Database Bridge > Connect without opening a port genehmigen. Wenn Sie diese Kopplung nicht gestartet haben, lehnen Sie sie dort ab.",
        "it": "Uno spazio Speak To Your Database chiede di collegarsi a questo Odoo: {name} (id spazio {ref}, dominio e-mail di chi ha digitato il codice: {domain}). Non viene letto nulla finché non lo approva in Speak To Your Database Bridge > Connect without opening a port. Se non ha avviato questo abbinamento, lo rifiuti lì.",
        "nl": "Een Speak To Your Database-werkruimte vraagt verbinding met deze Odoo: {name} (werkruimte-id {ref}, e-maildomein van wie de code typte: {domain}). Er wordt niets gelezen tot u het goedkeurt in Speak To Your Database Bridge > Connect without opening a port. Hebt u deze koppeling niet gestart, weiger ze daar.",
        "pt": "Um espaço do Speak To Your Database pede para se ligar a este Odoo: {name} (id do espaço {ref}, domínio de e-mail de quem escreveu o código: {domain}). Nada é lido até o aprovar em Speak To Your Database Bridge > Connect without opening a port. Se não iniciou esta ligação, recuse-a lá.",
    },
    "yes": {"en": "Yes", "fr": "Oui", "es": "Sí", "de": "Ja", "it": "Sì", "nl": "Ja", "pt": "Sim"},
    "no": {"en": "No", "fr": "Non", "es": "No", "de": "Nein", "it": "No", "nl": "Nee", "pt": "Não"},
}

# Codes the hub may refuse a question with (ack accepted:false), and what the bot says.
REFUSAL_MESSAGE_KEYS = {
    "discuss_off": "discuss_off",
    "member_unknown": "member_unknown",
    "member_not_allowed": "not_allowed",
    "prompts_exhausted": "prompts_exhausted",
    "rate_limited": "rate_user",
    "not_paired": "not_connected",
    "channel_offline": "not_connected",
}


def lang_key(lang):
    code = str(lang or "en").split("_")[0].split("-")[0].lower()
    return code if code in LANGS else "en"


def say(key, lang, **values):
    texts = MESSAGES[key]
    text = texts.get(lang_key(lang)) or texts["en"]
    return text.format(**values) if values else text


# ---------------------------------------------------------------------------
# secrets never reach Discuss
# ---------------------------------------------------------------------------
HIDDEN = "[hidden]"
_SECRET_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),       # JWT
    re.compile(r"\b(?:sk|rk)[-_](?:live|test|proj|ant)?[-_]?[A-Za-z0-9_-]{16,}"),      # API keys
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),                                      # GitHub
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),                                    # Slack
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                                              # AWS
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)"),
    re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])"),              # channel secret shape
)
_KEY_VALUE = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|token)\b(\s*[:=]\s*)(\S+)")


def redact(text, known_secrets=()):
    """Hide the module's own secrets and anything shaped like a credential."""
    if not text:
        return text
    out = str(text)
    for secret in known_secrets or ():
        if secret and len(secret) >= 8:
            out = out.replace(secret, HIDDEN)
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub(HIDDEN, out)
    out = _KEY_VALUE.sub(lambda m: m.group(1) + m.group(2) + HIDDEN, out)
    return out


# ---------------------------------------------------------------------------
# no clickable link in what the bot posts
# ---------------------------------------------------------------------------
# An address in an answer is shown, never linked: the scheme is dropped and the
# dots of the host are bracketed (example[.]com), so neither Odoo nor a mail
# client turns it into a link.
_URL_RE = re.compile(r"(?i)\b(?:[a-z][a-z0-9+.-]{1,15}://|www\.)[^\s<>\"']+")


def _delink_match(match):
    text = match.group(0)
    if "://" in text:
        text = text.split("://", 1)[1]
    host, sep, rest = text.partition("/")
    return host.replace(".", "[.]") + sep + rest


def delink(text):
    """The text with every web address made plain (not clickable)."""
    if not text:
        return text
    return _URL_RE.sub(_delink_match, str(text))


def _plain(text, secrets):
    """Text from STYD as the bot shows it: secrets hidden, addresses not links."""
    return delink(redact(text, secrets))


# ---------------------------------------------------------------------------
# the question
# ---------------------------------------------------------------------------
def extract_question(body_html, bot_partner_id, bot_name):
    """Plain text of a Discuss message, without the bot's mention. Returns
    ``(text, truncated)``. The text is data: it is only ever sent to STYD as a
    JSON string."""
    text = ""
    body = str(body_html or "")
    if body.strip():
        try:
            from lxml import html as lhtml
            root = lhtml.fragment_fromstring(body, create_parent="div")
            for anchor in root.xpath("//a[@data-oe-model='res.partner']"):
                if anchor.get("data-oe-id") == str(bot_partner_id):
                    anchor.drop_tree()
            for br in root.xpath("//br"):
                br.tail = "\n" + (br.tail or "")
            text = root.text_content()
        except Exception:  # not HTML: keep the raw text
            text = re.sub(r"<[^>]*>", " ", body)
    if bot_name:
        text = text.replace("@" + bot_name, " ")
    text = re.sub(r"[ \t\r\f\v ]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text).strip()
    truncated = len(text) > QUESTION_MAX
    return text[:QUESTION_MAX], truncated


# ---------------------------------------------------------------------------
# the answer (hub -> module, discuss_answer args)
# ---------------------------------------------------------------------------
class AnswerError(ValueError):
    pass


def _cap_str(value, limit):
    if value is None:
        return None
    if not isinstance(value, str):
        raise AnswerError("bad_answer")
    return value[:limit]


def _cell(value):
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return value[:CELL_MAX]
    return str(value)[:CELL_MAX]


def _problem(value, limit):
    """{code, message} of a refusal or an error, capped; None when absent."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise AnswerError("bad_answer")
    code = value.get("code")
    code = code if isinstance(code, str) and CODE_RE.match(code) else None
    message = value.get("message")
    message = message[:limit] if isinstance(message, str) else None
    return {"code": code, "message": message}


def validate_answer(args):
    """Check and normalise the args of a ``discuss_answer``. Raises AnswerError."""
    if not isinstance(args, dict):
        raise AnswerError("bad_answer")
    qid = args.get("question_id")
    if not isinstance(qid, str) or not proto.QUESTION_ID_RE.match(qid):
        raise AnswerError("bad_answer")
    status = args.get("status")
    if status not in ANSWER_STATUSES:
        raise AnswerError("bad_answer")
    lang = args.get("lang")
    lang = lang if isinstance(lang, str) and LANG_RE.match(lang) else None
    tables = []
    raw_tables = args.get("tables") or []
    if not isinstance(raw_tables, list):
        raise AnswerError("bad_answer")
    for raw in raw_tables[:TABLES_MAX]:
        if not isinstance(raw, dict) or not isinstance(raw.get("columns"), list) \
                or not isinstance(raw.get("rows") or [], list):
            raise AnswerError("bad_answer")
        columns = [str(c)[:TITLE_MAX] for c in raw["columns"][:COLUMNS_MAX]]
        if not columns:
            continue
        rows = []
        for row in (raw.get("rows") or [])[:ROWS_MAX]:
            if not isinstance(row, list):
                raise AnswerError("bad_answer")
            cells = [_cell(v) for v in row[:len(columns)]]
            cells += [None] * (len(columns) - len(cells))
            rows.append(cells)
        total = raw.get("total_rows")
        total = total if isinstance(total, int) and not isinstance(total, bool) and total >= len(rows) else None
        title = raw.get("title")
        tables.append({
            "title": title[:TITLE_MAX] if isinstance(title, str) else None,
            "columns": columns,
            "rows": rows,
            "total_rows": total,
        })
    answer = {
        "question_id": qid,
        "status": status,
        "lang": lang,
        "text": _cap_str(args.get("text"), ANSWER_TEXT_MAX),
        "understood_as": _cap_str(args.get("understood_as"), UNDERSTOOD_MAX),
        "tables": tables,
        "refusal": _problem(args.get("refusal"), MESSAGE_MAX),
        "error": _problem(args.get("error"), MESSAGE_MAX),
    }
    if status == "answered" and not (answer["text"] or answer["tables"]):
        raise AnswerError("bad_answer")
    return answer


def _paragraphs(text, secrets):
    parts = []
    for block in re.split(r"\n\s*\n", _plain(text, secrets).strip()):
        if block.strip():
            lines = [escape(line) for line in block.strip().split("\n")]
            parts.append(Markup("<p>%s</p>") % Markup("<br/>").join(lines))
    return Markup("").join(parts)


def _cell_text(value, lang):
    if value is None:
        return ""
    if value is True:
        return say("yes", lang)
    if value is False:
        return say("no", lang)
    return str(value)


def _table(table, lang, secrets):
    head = Markup("").join(
        Markup("<th>%s</th>") % _plain(col, secrets) for col in table["columns"])
    body = []
    for row in table["rows"]:
        cells = []
        for value in row:
            numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
            cell = _plain(_cell_text(value, lang), secrets)
            cells.append((Markup('<td class="text-end">%s</td>') if numeric else Markup("<td>%s</td>")) % cell)
        body.append(Markup("<tr>%s</tr>") % Markup("").join(cells))
    html = Markup("")
    if table.get("title"):
        html += Markup("<p><strong>%s</strong></p>") % _plain(table["title"], secrets)
    html += Markup('<table class="table table-sm table-bordered"><thead><tr>%s</tr></thead><tbody>%s</tbody></table>') % (
        head, Markup("").join(body))
    total = table.get("total_rows")
    if total and total > len(table["rows"]):
        html += Markup("<p><em>%s</em></p>") % say("rows_shown", lang, shown=len(table["rows"]), total=total)
    return html


def render_answer(answer, user_lang, secrets=()):
    """The bot's message for a validated answer (Markup; everything escaped)."""
    lang = answer.get("lang") or user_lang
    status = answer["status"]
    if status == "refused":
        problem = answer.get("refusal") or {}
        text = problem.get("message") or say("refused", lang)
        return _paragraphs(text, secrets)
    if status == "error":
        problem = answer.get("error") or {}
        text = problem.get("message") or say("error", lang)
        return _paragraphs(text, secrets)
    html = Markup("")
    if answer.get("understood_as"):
        html += Markup("<p><em>%s: %s</em></p>") % (
            say("understood_as", lang), _plain(answer["understood_as"], secrets))
    if answer.get("text"):
        html += _paragraphs(answer["text"], secrets)
    for table in answer.get("tables") or []:
        html += _table(table, lang, secrets)
    return html


def bot_line(key, lang):
    """One of the bot's own lines, as a message body."""
    return Markup("<p>%s</p>") % say(key, lang)


def pairing_waiting_line(lang, name, ref, domain):
    """The line every Odoo admin gets when a pairing waits for approval. The
    values come from STYD: escaped, addresses not links."""
    text = say("pairing_waiting", lang, name=delink(name or "-"), ref=ref or "-", domain=delink(domain or "-"))
    return Markup("<p>%s</p>") % text
