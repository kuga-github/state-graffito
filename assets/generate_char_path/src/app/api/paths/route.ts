import { NextResponse } from "next/server";
import type { ResultSetHeader, RowDataPacket } from "mysql2";
import { db } from "@/lib/db";
import { calculateMetrics } from "@/lib/geometry";
import { ensureCenteredCoordinates } from "@/lib/migrations";
import { InputError, parseLabel, parseStrokes } from "@/lib/validation";
import type { CharacterPath, PathMetrics, Stroke } from "@/lib/types";

export const runtime = "nodejs";

interface PathRow extends RowDataPacket {
  id: number;
  category: string;
  name: string;
  strokes: Stroke[] | string;
  metrics: PathMetrics | string;
  updated_at: Date;
}

function decodeJson<T>(value: T | string): T {
  return typeof value === "string" ? (JSON.parse(value) as T) : value;
}

function toPath(row: PathRow): CharacterPath {
  return {
    id: row.id,
    category: row.category,
    name: row.name,
    strokes: decodeJson(row.strokes),
    metrics: decodeJson(row.metrics),
    updatedAt: row.updated_at.toISOString()
  };
}

function getSaveFailureReason(error: unknown): string {
  const code =
    error && typeof error === "object" && "code" in error && typeof error.code === "string"
      ? error.code
      : undefined;

  switch (code) {
    case "ER_ACCESS_DENIED_ERROR":
      return "MySQL authentication failed. Check DB_USER, DB_PASSWORD, and the credentials used to initialize MySQL.";
    case "ECONNREFUSED":
    case "ETIMEDOUT":
    case "ENOTFOUND":
      return "Could not connect to MySQL. Check DB_HOST, DB_PORT, and whether the MySQL container is running.";
    case "ER_NO_SUCH_TABLE":
      return "A required table is missing. Check whether MySQL initialization completed.";
    default:
      return error instanceof Error ? error.message : String(error);
  }
}

export async function GET() {
  try {
    await ensureCenteredCoordinates();
    const [rows] = await db.query<PathRow[]>(
      "SELECT id, category, name, strokes, metrics, updated_at FROM character_paths ORDER BY category, name"
    );
    return NextResponse.json(rows.map(toPath));
  } catch (error) {
    console.error("Failed to list character paths", error);
    return NextResponse.json({ error: "Could not load the character list." }, { status: 500 });
  }
}

export async function POST(request: Request) {
  let connection: Awaited<ReturnType<typeof db.getConnection>> | undefined;
  try {
    let body: Record<string, unknown>;
    try {
      body = (await request.json()) as Record<string, unknown>;
    } catch {
      return NextResponse.json({ error: "Request body must be valid JSON." }, { status: 400 });
    }
    if (!body || typeof body !== "object" || Array.isArray(body)) {
      return NextResponse.json({ error: "Request body must be a JSON object." }, { status: 400 });
    }
    const category = parseLabel(body.category, "Category");
    const name = parseLabel(body.name, "Name");
    const strokes = parseStrokes(body.strokes);
    const metrics = calculateMetrics(strokes);
    await ensureCenteredCoordinates();
    connection = await db.getConnection();
    await connection.beginTransaction();
    await connection.execute<ResultSetHeader>(
      `INSERT INTO character_paths (category, name, strokes, metrics)
       VALUES (?, ?, ?, ?)
       ON DUPLICATE KEY UPDATE strokes = VALUES(strokes), metrics = VALUES(metrics)`,
      [category, name, JSON.stringify(strokes), JSON.stringify(metrics)]
    );
    const [rows] = await connection.query<PathRow[]>(
      "SELECT id, category, name, strokes, metrics, updated_at FROM character_paths WHERE category = ? AND name = ?",
      [category, name]
    );
    await connection.commit();
    return NextResponse.json(toPath(rows[0]));
  } catch (error) {
    if (connection) await connection.rollback();
    if (error instanceof InputError) {
      return NextResponse.json({ error: error.message }, { status: 400 });
    }
    console.error("Failed to save character path", error);
    return NextResponse.json({
      error: "Could not save the character path.",
      reason: getSaveFailureReason(error)
    }, { status: 500 });
  } finally {
    connection?.release();
  }
}
