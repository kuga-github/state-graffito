import { NextResponse } from "next/server";
import type { ResultSetHeader } from "mysql2";
import { db } from "@/lib/db";

export const runtime = "nodejs";

export async function DELETE(_request: Request, context: { params: Promise<{ id: string }> }) {
  try {
    const { id: idString } = await context.params;
    const id = Number(idString);
    if (!Number.isSafeInteger(id) || id < 1) {
      return NextResponse.json({ error: "Provide a valid character ID." }, { status: 400 });
    }

    const [result] = await db.execute<ResultSetHeader>(
      "DELETE FROM character_paths WHERE id = ?",
      [id]
    );
    if (result.affectedRows === 0) {
      return NextResponse.json({ error: "The requested character was not found." }, { status: 404 });
    }
    return NextResponse.json({ deleted: true });
  } catch (error) {
    console.error("Failed to delete character path", error);
    return NextResponse.json({
      error: "Could not delete the saved character.",
      reason: error instanceof Error ? error.message : String(error)
    }, { status: 500 });
  }
}
