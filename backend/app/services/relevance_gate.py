"""User-facing messages for the out-of-domain handling (issue #22).

Two levels, matching the two signals:
- ``gate_message``: the evidence gate found too little on-topic material, the
  pipeline stops and this markdown replaces the answer.
- ``domain_notice``: the LLM domain check flags the query as out of scope but
  the evidence gate passed; this blockquote goes above the normal answer.

Messages are pre-localized: they reach the client as-is, without passing
through the translation step.
"""

_GATE = {
    "it": ("Tema non trovato",
           "Nel corpus della Camera dei Deputati (XIX legislatura) non ci "
           "sono dibattiti pertinenti a questo tema, quindi il sistema non "
           "ha generato una risposta.",
           "Temi vicini che l'Aula ha discusso"),
    "en": ("Topic not found",
           "The Chamber of Deputies corpus (19th legislature) has no debates "
           "relevant to this topic, so the system generated no answer.",
           "Nearby topics the Chamber did debate"),
    "fr": ("Sujet introuvable",
           "Le corpus de la Chambre des députés (XIXe législature) ne "
           "contient aucun débat pertinent sur ce sujet ; le système n'a "
           "donc généré aucune réponse.",
           "Sujets proches réellement débattus"),
    "de": ("Thema nicht gefunden",
           "Das Korpus der Abgeordnetenkammer (19. Legislaturperiode) "
           "enthält keine Debatten zu diesem Thema; das System hat deshalb "
           "keine Antwort erzeugt.",
           "Verwandte Themen, die die Kammer debattiert hat"),
    "es": ("Tema no encontrado",
           "El corpus de la Cámara de Diputados (XIX legislatura) no "
           "contiene debates pertinentes sobre este tema, así que el "
           "sistema no generó una respuesta.",
           "Temas cercanos que la Cámara sí debatió"),
    "pt": ("Tema não encontrado",
           "O corpus da Câmara dos Deputados (XIX legislatura) não contém "
           "debates pertinentes sobre este tema, então o sistema não gerou "
           "uma resposta.",
           "Temas próximos que a Câmara debateu"),
}

_NOTICE = {
    "it": ("> **Nota**: la domanda sembra fuori dal perimetro della Camera "
           "dei Deputati. La risposta qui sotto usa i dibattiti italiani più "
           "vicini al tema{sugg}.\n\n",
           "; forse cercavi: {topics}"),
    "en": ("> **Note**: the question looks outside the Chamber of Deputies' "
           "scope. The answer below uses the closest Italian debates{sugg}."
           "\n\n",
           "; you may have meant: {topics}"),
    "fr": ("> **Note** : la question semble hors du périmètre de la Chambre "
           "des députés. La réponse ci-dessous s'appuie sur les débats "
           "italiens les plus proches{sugg}.\n\n",
           " ; vous cherchiez peut-être : {topics}"),
    "de": ("> **Hinweis**: Die Frage liegt offenbar außerhalb des Bereichs "
           "der Abgeordnetenkammer. Die Antwort unten stützt sich auf die "
           "nächstliegenden italienischen Debatten{sugg}.\n\n",
           "; vielleicht meinten Sie: {topics}"),
    "es": ("> **Nota**: la pregunta parece fuera del ámbito de la Cámara de "
           "Diputados. La respuesta usa los debates italianos más "
           "cercanos{sugg}.\n\n",
           "; quizá buscabas: {topics}"),
    "pt": ("> **Nota**: a pergunta parece fora do âmbito da Câmara dos "
           "Deputados. A resposta usa os debates italianos mais "
           "próximos{sugg}.\n\n",
           "; talvez procurasse: {topics}"),
}


# Same messages when the graph also holds the Senate.
_GATE_PARLIAMENT = {
    "it": ("Tema non trovato",
           "Nel corpus del Parlamento (Camera e Senato, XIX legislatura) non "
           "ci sono dibattiti pertinenti a questo tema, quindi il sistema non "
           "ha generato una risposta.",
           "Temi vicini che il Parlamento ha discusso"),
    "en": ("Topic not found",
           "The Italian Parliament corpus (Chamber and Senate, 19th "
           "legislature) has no debates relevant to this topic, so the system "
           "generated no answer.",
           "Nearby topics Parliament did debate"),
    "fr": ("Sujet introuvable",
           "Le corpus du Parlement italien (Chambre et Sénat, XIXe "
           "législature) ne contient aucun débat pertinent sur ce sujet ; le "
           "système n'a donc généré aucune réponse.",
           "Sujets proches réellement débattus"),
    "de": ("Thema nicht gefunden",
           "Das Korpus des italienischen Parlaments (Abgeordnetenkammer und "
           "Senat, 19. Legislaturperiode) enthält keine Debatten zu diesem "
           "Thema; das System hat deshalb keine Antwort erzeugt.",
           "Verwandte Themen, die das Parlament debattiert hat"),
    "es": ("Tema no encontrado",
           "El corpus del Parlamento italiano (Cámara y Senado, XIX "
           "legislatura) no contiene debates pertinentes sobre este tema, así "
           "que el sistema no generó una respuesta.",
           "Temas cercanos que el Parlamento sí debatió"),
    "pt": ("Tema não encontrado",
           "O corpus do Parlamento italiano (Câmara e Senado, XIX "
           "legislatura) não contém debates pertinentes sobre este tema, "
           "então o sistema não gerou uma resposta.",
           "Temas próximos que o Parlamento debateu"),
}

_NOTICE_PARLIAMENT = {
    "it": ("> **Nota**: la domanda sembra fuori dal perimetro del Parlamento. "
           "La risposta qui sotto usa i dibattiti italiani più vicini al "
           "tema{sugg}.\n\n",
           "; forse cercavi: {topics}"),
    "en": ("> **Note**: the question looks outside the Italian Parliament's "
           "scope. The answer below uses the closest Italian debates{sugg}."
           "\n\n",
           "; you may have meant: {topics}"),
    "fr": ("> **Note** : la question semble hors du périmètre du Parlement "
           "italien. La réponse ci-dessous s'appuie sur les débats italiens "
           "les plus proches{sugg}.\n\n",
           " ; vous cherchiez peut-être : {topics}"),
    "de": ("> **Hinweis**: Die Frage liegt offenbar außerhalb des Bereichs "
           "des italienischen Parlaments. Die Antwort unten stützt sich auf "
           "die nächstliegenden italienischen Debatten{sugg}.\n\n",
           "; vielleicht meinten Sie: {topics}"),
    "es": ("> **Nota**: la pregunta parece fuera del ámbito del Parlamento "
           "italiano. La respuesta usa los debates italianos más "
           "cercanos{sugg}.\n\n",
           "; quizá buscabas: {topics}"),
    "pt": ("> **Nota**: a pergunta parece fora do âmbito do Parlamento "
           "italiano. A resposta usa os debates italianos mais "
           "próximos{sugg}.\n\n",
           "; talvez procurasse: {topics}"),
}


def _messages():
    from .retrieval.scope import loaded_chambers

    if "senato" in loaded_chambers():
        return _GATE_PARLIAMENT, _NOTICE_PARLIAMENT
    return _GATE, _NOTICE


def gate_payload(query: str, suggestions: list, locale: str = "it") -> dict:
    """Structured payload for the ``gate`` SSE event.

    The frontend renders it as a dedicated empty-state block (serif title,
    explanation, clickable topic chips) instead of markdown content.
    """
    gate, _ = _messages()
    title, body, sugg_label = gate.get(locale, gate["en"])
    return {
        "title": title,
        "body": body.format(query=query),
        "suggestions_label": sugg_label,
        "suggestions": list(suggestions),
    }


def gate_message(query: str, suggestions: list, locale: str = "it") -> str:
    """Markdown fallback with the same content as :func:`gate_payload`."""
    p = gate_payload(query, suggestions, locale)
    text = f"## {p['title']}\n\n{p['body']}"
    if p["suggestions"]:
        text += f"\n\n{p['suggestions_label']}:\n" + "\n".join(
            f"- {s}" for s in p["suggestions"])
    return text


def domain_notice(suggestions: list, locale: str = "it") -> str:
    """Blockquote prepended to the answer when only the LLM check fires."""
    from urllib.parse import quote

    _, notice = _messages()
    template, sugg_template = notice.get(locale, notice["en"])
    sugg = ""
    if suggestions:
        links = ", ".join(f"[{s}](suggest:{quote(s)})" for s in suggestions)
        sugg = sugg_template.format(topics=links)
    return template.format(sugg=sugg)
