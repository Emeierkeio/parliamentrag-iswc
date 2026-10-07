# ParliamentRAG MCP server

Porta i dati della Camera dei Deputati (XIX legislatura) dentro Claude e
qualunque client [MCP](https://modelcontextprotocol.io): ricerca ibrida su
interventi e atti, sedute con riassunti, votazioni con i voti dei singoli
deputati, testo esatto degli emendamenti votati.

Il server interroga l'API pubblica di [parliamentrag.it](https://www.parliamentrag.it)
in sola lettura: nessuna credenziale, nessun database locale.

**La via più rapida**: endpoint remoto già online, niente da installare.
Aggiungi `https://mcp.parliamentrag.it/mcp` ai connettori del tuo assistente
(claude.ai, ChatGPT in modalità sviluppatore, o qualsiasi client remote-MCP).

## Strumenti

| Tool | Cosa fa |
|---|---|
| `search_parliament` | Ricerca ibrida (full-text + semantica) su interventi in Aula e atti parlamentari |
| `list_sessions` | Sedute con riassunto AI, dibattiti e conteggi, paginate |
| `get_session_votes` | Tutte le votazioni di una seduta |
| `get_vote_details` | Dettaglio votazione: aggregati, breakdown per gruppo, atto collegato (scheda + PDF), voti individuali filtrabili per deputato/gruppo, flag scrutinio segreto |
| `get_voted_text` | Testo integrale dell'emendamento/articolo votato, dall'Allegato A del resoconto |
| `get_debate` | Dettaglio dibattito: riassunto, atti discussi, oratori |
| `get_vote_hemicycle` | L'emiciclo della votazione come immagine: un punto per deputato, colori per esito, mostrato direttamente nella chat |

## Installazione

Serve [uv](https://docs.astral.sh/uv/) (le dipendenze sono dichiarate inline
nello script, non si installa nulla).

**Claude Code:**

```bash
claude mcp add parliamentrag -- uv run /percorso/assoluto/ParliamentRAG/mcp/server.py
```

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "parliamentrag": {
      "command": "uv",
      "args": ["run", "/percorso/assoluto/ParliamentRAG/mcp/server.py"]
    }
  }
}
```

**Da GitHub, senza clonare il repo:**

```bash
claude mcp add parliamentrag -- uvx --from "git+https://github.com/Emeierkeio/parliamentrag-iswc.git#subdirectory=mcp" parliamentrag-mcp
```

**Senza uv (pip):**

```bash
pip install "parliamentrag-mcp @ git+https://github.com/Emeierkeio/parliamentrag-iswc.git#subdirectory=mcp"
claude mcp add parliamentrag -- parliamentrag-mcp
```

**Altri client MCP** (Cursor, VS Code con Copilot, Gemini CLI, Windsurf, …):
lo stesso blocco JSON funziona ovunque, cambia solo il file di
configurazione del client (`~/.cursor/mcp.json`, `.vscode/mcp.json`,
`~/.gemini/settings.json`, ecc.):

```json
{
  "mcpServers": {
    "parliamentrag": {
      "command": "uv",
      "args": ["run", "/percorso/assoluto/ParliamentRAG/mcp/server.py"]
    }
  }
}
```

## Server remoto (ChatGPT e claude.ai)

ChatGPT e claude.ai usano MCP tramite **connettori remoti**: serve il server
esposto su un URL pubblico. Il server supporta già il trasporto
streamable-http:

```bash
MCP_TRANSPORT=http PORT=8080 uv run mcp/server.py
# endpoint MCP: http://localhost:8080/mcp
```

Per il deploy c'è il `Dockerfile` in questa cartella (su Railway: nuovo
servizio dal repo con root directory `mcp/`, poi dominio ad es.
`mcp.parliamentrag.it`). Una volta online:

- **claude.ai**: Settings → Connectors → Add custom connector →
  `https://mcp.parliamentrag.it/mcp`
- **ChatGPT**: Impostazioni → Connettori (modalità sviluppatore) →
  aggiungi l'URL dell'endpoint

Il server resta in sola lettura sull'API pubblica: nessuna credenziale,
nessun dato utente.

## Note

- I contenuti (interventi, riassunti, testi) sono in italiano.
- Il backend può essere in sleep: la prima chiamata a volte impiega 30-60
  secondi; il server ritenta da solo una volta.
- Endpoint override per sviluppo locale: `PARLIAMENTRAG_API=http://localhost:8000/api`.

## Esempi di domande (in Claude)

- «Come hanno votato i deputati del PD sul voto finale del DDL 2961?»
- «Cosa si è detto in Aula sull'intelligenza artificiale a luglio 2026?»
- «Leggimi il testo dell'emendamento 6.21 della seduta 700 e dimmi chi l'ha respinto.»
