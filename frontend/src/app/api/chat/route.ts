import { NextRequest } from "next/server";

/**
 * API Route per la chat RAG
 *
 * Proxy verso il backend FastAPI Python che gestisce:
 * 1. Authority calculation e chunk retrieval
 * 2. Generazione risposta con GPT-4o
 */

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";
const PROXY_SECRET = process.env.PROXY_SHARED_SECRET || "";

export async function POST(request: NextRequest) {
  const { query, task_id } = await request.json();

  if (!query || typeof query !== "string") {
    return new Response(
      JSON.stringify({ error: "Query is required" }),
      { status: 400, headers: { "Content-Type": "application/json" } }
    );
  }

  // Forward Accept-Language and the real client IP (for per-IP rate limits)
  const acceptLanguage = request.headers.get("accept-language") || "it";
  const clientIp = request.headers.get("x-forwarded-for") || "";

  try {
    // Proxy verso il backend FastAPI
    const backendResponse = await fetch(`${BACKEND_URL}/api/query`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "Accept-Language": acceptLanguage,
        ...(clientIp ? { "X-Forwarded-For": clientIp } : {}),
        // Lets the backend skip this proxy's own hop when it picks the client IP
        ...(PROXY_SECRET ? { "X-Proxy-Secret": PROXY_SECRET } : {}),
      },
      body: JSON.stringify({ query, task_id }),
    });

    if (!backendResponse.ok) {
      throw new Error(`Backend error: ${backendResponse.status}`);
    }

    // Stream diretto dal backend
    const reader = backendResponse.body?.getReader();
    if (!reader) {
      throw new Error("No response body");
    }

    const stream = new ReadableStream({
      async start(controller) {
        const decoder = new TextDecoder();
        const encoder = new TextEncoder();
        let buffer = ""; // Buffer per messaggi parziali

        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            // Decodifica e aggiungi al buffer
            buffer += decoder.decode(value, { stream: true });

            // Processa solo messaggi completi (terminano con \n\n)
            const messages = buffer.split("\n\n");

            // L'ultimo elemento potrebbe essere incompleto, mantienilo nel buffer
            buffer = messages.pop() || "";

            for (const message of messages) {
              const lines = message.split("\n");
              for (const line of lines) {
                if (line.startsWith("data:")) {
                  const data = line.substring(5).trim();
                  if (data) {
                    // Passa direttamente il JSON che già contiene il tipo
                    controller.enqueue(encoder.encode(`data: ${data}\n\n`));
                  }
                }
              }
            }
          }

          // Processa eventuali dati rimasti nel buffer
          if (buffer.trim()) {
            const lines = buffer.split("\n");
            for (const line of lines) {
              if (line.startsWith("data:")) {
                const data = line.substring(5).trim();
                if (data) {
                  controller.enqueue(encoder.encode(`data: ${data}\n\n`));
                }
              }
            }
          }
        } catch (error) {
          controller.enqueue(encoder.encode(`data: ${JSON.stringify({ type: "error", message: "Stream error" })}\n\n`));
        } finally {
          controller.close();
        }
      },
    });

    return new Response(stream, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
      },
    });

  } catch (error) {
    console.error("Backend connection error:", error);

    // Fallback: usa mock data se il backend non è disponibile
    return fallbackMockResponse(query);
  }
}

/**
 * Formatta gli eventi dal backend per il frontend
 */
function formatEventForFrontend(event: Record<string, unknown>): Record<string, unknown> | null {
  // Gestisci i diversi tipi di eventi dal backend

  // Progress event
  if (event.step !== undefined) {
    return { type: "progress", step: event.step, total: event.total, message: event.message };
  }

  // Query type
  if (event.type !== undefined) {
    return { type: "query_type", queryType: event.type };
  }

  // Chunk (streaming text)
  if (event.content !== undefined) {
    return { type: "chunk", content: event.content };
  }

  // Experts
  if (event.experts !== undefined) {
    return {
      type: "experts",
      experts: (event.experts as Array<Record<string, unknown>>).map(formatExpert)
    };
  }

  // Citations
  if (event.citations !== undefined) {
    return {
      type: "citations",
      citations: (event.citations as Array<Record<string, unknown>>).map(formatCitation)
    };
  }

  // Commissioni
  if (event.commissioni !== undefined) {
    return { type: "commissioni", commissioni: event.commissioni };
  }

  // Balance metrics
  if (event.maggioranza_percentage !== undefined) {
    return {
      type: "balance",
      metrics: {
        maggioranzaPercentage: event.maggioranza_percentage,
        opposizionePercentage: event.opposizione_percentage,
        biasScore: event.bias_score,
      }
    };
  }

  // Complete
  if (event.message_id !== undefined) {
    return { type: "complete", messageId: event.message_id, processingTime: event.processing_time_ms };
  }

  // Error
  if (event.message !== undefined && !event.step) {
    return { type: "error", message: event.message };
  }

  return null;
}

/**
 * Formatta un expert dal backend per il frontend
 * Backend now uses English field names, pass through directly
 */
function formatExpert(expert: Record<string, unknown>) {
  return {
    id: expert.id,
    first_name: expert.first_name || expert.nome,
    last_name: expert.last_name || expert.cognome,
    group: expert.group || expert.gruppo,
    coalition: expert.coalition || expert.coalizione,
    authority_score: expert.authority_score,
    camera_profile_url: expert.camera_profile_url || expert.scheda_camera,
    profession: expert.profession || expert.professione,
    education: expert.education || expert.istruzione,
    committee: expert.committee || expert.commissione,
    institutional_role: expert.institutional_role || expert.ruolo_istituzionale,
    score_breakdown: expert.score_breakdown,
    relevant_speeches_count: expert.relevant_speeches_count || expert.n_interventi_rilevanti,
    acts_detail: expert.acts_detail || expert.atti_dettaglio,
  };
}

/**
 * Formatta una citation dal backend per il frontend
 * Backend now uses English field names, pass through directly
 */
function formatCitation(citation: Record<string, unknown>) {
  return {
    chunk_id: citation.chunk_id,
    deputy_first_name: citation.deputy_first_name || citation.deputato_nome,
    deputy_last_name: citation.deputy_last_name || citation.deputato_cognome,
    group: citation.group || citation.gruppo,
    coalition: citation.coalition || citation.coalizione,
    date: citation.date || citation.data,
    debate: citation.debate || citation.dibattito,
    debate_id: citation.debate_id || citation.dibattito_id,
    intervention_id: citation.intervention_id || citation.intervento_id,
    text: citation.text || citation.testo,
    quote_text: citation.quote_text,
    full_text: citation.full_text,
    similarity: citation.similarity,
    camera_profile_url: citation.camera_profile_url || citation.scheda_camera,
    institutional_role: citation.institutional_role,
  };
}

/**
 * Fallback con mock data quando il backend non è disponibile
 */
function fallbackMockResponse(query: string) {
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    async start(controller) {
      const sendEvent = (type: string, data: Record<string, unknown>) => {
        const event = `data: ${JSON.stringify({ type, ...data })}\n\n`;
        controller.enqueue(encoder.encode(event));
      };

      try {
        // Avvisa che stiamo usando il fallback
        sendEvent("warning", { message: "Backend non disponibile. Usando dati di esempio." });

        // Simula i 6 step del pipeline RAG
        const steps = [
          { delay: 300, step: 1 },
          { delay: 400, step: 2 },
          { delay: 500, step: 3 },
          { delay: 400, step: 4 },
          { delay: 300, step: 5 },
          { delay: 200, step: 6 },
        ];

        for (const { delay, step } of steps) {
          await new Promise((resolve) => setTimeout(resolve, delay));
          sendEvent("progress", { step });
        }

        // Simula streaming della risposta
        const mockContent = `## Risposta di esempio

Il backend ParliamentRAG non è attualmente disponibile.

Per avviare il backend:
\`\`\`bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
\`\`\`

Una volta avviato, potrai:
- Fare domande puntuali (es. "Qual è l'ultima interrogazione sul superbonus?")
- Fare domande generiche (es. "Qual è il posizionamento dei gruppi parlamentari sull'immigrazione?")

Il sistema analizzerà i dibattiti parlamentari della XIX legislatura.`;

        const chunks = mockContent.split(" ");
        for (const chunk of chunks) {
          await new Promise((resolve) => setTimeout(resolve, 30));
          sendEvent("chunk", { content: chunk + " " });
        }

        // Completa
        sendEvent("complete", { messageId: `mock_${Date.now()}` });

      } catch (error) {
        sendEvent("error", { message: "Errore durante l'elaborazione" });
      } finally {
        controller.close();
      }
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}
