import type { Stroke, VectorPoint } from "./types";

const roles = new Set(["start", "middle", "end"]);

export class InputError extends Error {}

export function parseStrokes(value: unknown): Stroke[] {
  if (!Array.isArray(value) || value.length === 0) {
    throw new InputError("Add at least one stroke.");
  }

  return value.map((stroke, strokeIndex) => {
    if (!Array.isArray(stroke) || stroke.length < 2) {
      throw new InputError(`Stroke ${strokeIndex + 1} must have a start and end point.`);
    }
    const points = stroke.map((candidate): VectorPoint => {
      if (!candidate || typeof candidate !== "object") throw new InputError("Invalid point format.");
      const point = candidate as Record<string, unknown>;
      if (
        !Number.isInteger(point.x) || !Number.isInteger(point.y) ||
        (point.x as number) < -8 || (point.x as number) > 8 ||
        (point.y as number) < -8 || (point.y as number) > 8 ||
        typeof point.role !== "string" || !roles.has(point.role)
      ) {
        throw new InputError("Coordinates must be integers from -8 to 8, and point roles must be start, midpoint, or end.");
      }
      return { x: point.x as number, y: point.y as number, role: point.role as VectorPoint["role"] };
    });

    if (points[0].role !== "start" || points[points.length - 1].role !== "end" ||
      points.slice(1, -1).some((point) => point.role !== "middle")) {
      throw new InputError(`Stroke ${strokeIndex + 1} must contain a start point, optional midpoints, and an end point in that order.`);
    }
    return points;
  });
}

export function parseLabel(value: unknown, label: string): string {
  if (typeof value !== "string" || !value.trim() || value.trim().length > 120) {
    throw new InputError(`${label} must be between 1 and 120 characters.`);
  }
  return value.trim();
}
