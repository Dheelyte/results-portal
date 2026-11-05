/**
 * The parent's PDF download (ARCHITECTURE.md §8.5, §9).
 *
 * A plain `<a href>` on the card page points here, because §8.5 wants the
 * download to be a link a parent taps — not JavaScript that fetches a blob.
 * The browser sends no Authorization header, so this handler supplies one:
 * it reads the web session's cookie, asks the API for the card, and streams
 * the PDF back.
 *
 * The API's own route answers with a 302 to a five-minute signed URL
 * (`app/pdf/links.py`). `fetch` follows that hop server-side, so the signed
 * URL never reaches the browser at all — one fewer thing that can be copied
 * out of an address bar and pasted into a group chat.
 */

import { NextResponse } from "next/server";

import { halfFrom } from "@/lib/half";
import { currentSession, refreshSession } from "@/lib/server/session";

const INTERNAL_API = process.env.INTERNAL_API_URL ?? "http://api:8000";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ pupilId: string; termId: string }> },
) {
  const { pupilId, termId } = await params;
  // A route handler may write cookies, so it can renew directly rather than
  // bouncing the parent through `/api/session` (D89).
  const session = (await currentSession()) ?? (await refreshSession());
  if (!session) {
    return new Response(null, { status: 303, headers: { Location: "/" } });
  }

  // Narrowed to the enum before it is interpolated into the API's URL.
  const half = halfFrom(new URL(request.url).searchParams.get("half"));

  const response = await fetch(
    `${INTERNAL_API}/api/v1/my/children/${pupilId}/reports/${termId}/pdf?half=${half}`,
    { headers: { Authorization: `Bearer ${session.accessToken}` }, cache: "no-store" },
  );

  if (!response.ok) {
    // R12 again: a withheld or unpublished card is not found, and nothing
    // here says which.
    return new NextResponse("Result not yet available. Please contact the school.", {
      status: 404,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  }

  return new NextResponse(await response.arrayBuffer(), {
    headers: {
      "Content-Type": "application/pdf",
      "Content-Disposition": 'inline; filename="report-card.pdf"',
      // The same reason the API sets it: a cached copy of a signed response
      // would outlive the signature.
      "Cache-Control": "private, no-store",
    },
  });
}
