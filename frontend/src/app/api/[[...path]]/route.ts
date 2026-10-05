import { NextRequest, NextResponse } from "next/server";

/**
 * Catch-all API proxy route.
 * Forwards all /api/* requests (except /api/chat which has its own handler)
 * to the backend FastAPI service.
 */

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

async function proxyRequest(request: NextRequest) {
  const path = request.nextUrl.pathname.replace(/^\/api/, "/api");
  const url = `${BACKEND_URL}${path}${request.nextUrl.search}`;

  const headers: Record<string, string> = {
    "Content-Type": request.headers.get("Content-Type") || "application/json",
  };
  // Locale-aware endpoints (e.g. /api/timeline) read Accept-Language
  const acceptLanguage = request.headers.get("Accept-Language");
  if (acceptLanguage) headers["Accept-Language"] = acceptLanguage;
  // Admin endpoints check X-API-Key on the backend; the proxy only relays
  // what the caller sent and never adds a key of its own
  const apiKey = request.headers.get("X-API-Key");
  if (apiKey) headers["X-API-Key"] = apiKey;
  const clientIp = request.headers.get("X-Forwarded-For");
  if (clientIp) headers["X-Forwarded-For"] = clientIp;

  const fetchOptions: RequestInit = {
    method: request.method,
    headers,
  };

  if (request.method !== "GET" && request.method !== "HEAD") {
    fetchOptions.body = await request.text();
  }

  try {
    const response = await fetch(url, fetchOptions);
    const data = await response.text();

    return new NextResponse(data, {
      status: response.status,
      headers: {
        "Content-Type": response.headers.get("Content-Type") || "application/json",
      },
    });
  } catch (error) {
    console.error(`Proxy error for ${url}:`, error);
    return NextResponse.json(
      { error: "Backend unavailable" },
      { status: 502 }
    );
  }
}

export async function GET(request: NextRequest) {
  return proxyRequest(request);
}

export async function POST(request: NextRequest) {
  return proxyRequest(request);
}

export async function DELETE(request: NextRequest) {
  return proxyRequest(request);
}

export async function PUT(request: NextRequest) {
  return proxyRequest(request);
}
