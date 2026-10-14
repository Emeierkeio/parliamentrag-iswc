# Server MCP remoto (streamable-http) per i connettori di ChatGPT e claude.ai.
# Railway: crea un servizio con root directory `mcp/` e questo Dockerfile
# viene usato automaticamente; la porta arriva dalla variabile PORT.
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml server.py ui_views.py icon.png favicon.ico senato_aula.json ./
RUN pip install --no-cache-dir .

ENV MCP_TRANSPORT=streamable-http
EXPOSE 8080

CMD ["parliamentrag-mcp"]
