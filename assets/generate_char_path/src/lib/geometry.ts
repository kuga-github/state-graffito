import type { BoundingBox, PathMetrics, Stroke } from "./types";

const sampleCount = 80;

function uniqueCoordinateCount(points: Stroke[number][]): number {
  return new Set(points.map(({ x, y }) => `${x},${y}`)).size;
}

function tangent(stroke: Stroke, index: number): { x: number; y: number } {
  const previous = stroke[Math.max(0, index - 1)];
  const next = stroke[Math.min(stroke.length - 1, index + 1)];
  const divisor = index === 0 || index === stroke.length - 1 ? 1 : 2;
  return { x: (next.x - previous.x) / divisor, y: (next.y - previous.y) / divisor };
}

function controlPoints(stroke: Stroke, segment: number): [{ x: number; y: number }, { x: number; y: number }] {
  const start = stroke[segment];
  const end = stroke[segment + 1];
  const startTangent = tangent(stroke, segment);
  const endTangent = tangent(stroke, segment + 1);
  return [
    { x: start.x + startTangent.x / 3, y: start.y + startTangent.y / 3 },
    { x: end.x - endTangent.x / 3, y: end.y - endTangent.y / 3 }
  ];
}

function curveSamples(stroke: Stroke): Array<{ x: number; y: number }> {
  if (stroke.length === 2) return stroke.map(({ x, y }) => ({ x, y }));

  const samples: Array<{ x: number; y: number }> = [];
  for (let index = 0; index < stroke.length - 1; index += 1) {
    const from = stroke[index];
    const to = stroke[index + 1];
    const [control1, control2] = controlPoints(stroke, index);
    for (let step = index === 0 ? 0 : 1; step <= sampleCount; step += 1) {
      const t = step / sampleCount;
      const inverse = 1 - t;
      samples.push({
        x: inverse ** 3 * from.x + 3 * inverse ** 2 * t * control1.x +
          3 * inverse * t ** 2 * control2.x + t ** 3 * to.x,
        y: inverse ** 3 * from.y + 3 * inverse ** 2 * t * control1.y +
          3 * inverse * t ** 2 * control2.y + t ** 3 * to.y
      });
    }
  }
  return samples;
}

export function calculateMetrics(strokes: Stroke[]): PathMetrics {
  const lineCount = strokes.length;
  const curveCount = strokes.filter((stroke) => stroke.length > 2).length;
  const directionCounts = { vertical: 0, horizontal: 0, diagonal: 0, curve: curveCount };
  for (const stroke of strokes) {
    if (stroke.length !== 2) continue;
    const [start, end] = stroke;
    if (start.x === end.x && start.y === end.y) continue;
    if (start.x === end.x) directionCounts.vertical += 1;
    else if (start.y === end.y) directionCounts.horizontal += 1;
    else directionCounts.diagonal += 1;
  }
  const directionTotal =
    directionCounts.vertical + directionCounts.horizontal + directionCounts.diagonal + directionCounts.curve;
  const samples = strokes.flatMap(curveSamples);
  const fallback = { minX: 0, minY: 0, maxX: 0, maxY: 0 };
  const bounds = samples.length
    ? {
        minX: Math.min(...samples.map((point) => point.x)),
        minY: Math.min(...samples.map((point) => point.y)),
        maxX: Math.max(...samples.map((point) => point.x)),
        maxY: Math.max(...samples.map((point) => point.y))
      }
    : fallback;
  const boundingBox: BoundingBox = {
    ...bounds,
    width: bounds.maxX - bounds.minX,
    height: bounds.maxY - bounds.minY
  };
  const allPoints = strokes.flatMap((stroke) => stroke);
  const pointBottomY = allPoints.length ? Math.max(...allPoints.map((point) => point.y)) : null;
  const bottomPoints = allPoints.filter((point) => point.y === pointBottomY);
  const bottomMiddlePoints = bottomPoints.filter((point) => point.role === "middle");
  const bottomNonMiddlePoints = bottomPoints.filter((point) => point.role !== "middle");
  const totalLength = strokes.reduce((total, stroke) => {
    const points = curveSamples(stroke);
    return total + points.slice(1).reduce((length, point, index) => {
      const previous = points[index];
      return length + Math.hypot(point.x - previous.x, point.y - previous.y);
    }, 0);
  }, 0);
  const centroid = allPoints.length > 0
    ? {
        x: Math.round(allPoints.reduce((sum, { x }) => sum + x, 0) / allPoints.length),
        y: Math.round(allPoints.reduce((sum, { y }) => sum + y, 0) / allPoints.length)
      }
    : { x: 0, y: 0 };
  const bboxArea = boundingBox.width * boundingBox.height;

  return {
    lineCount,
    curveCount,
    horizontalLineCount: directionCounts.horizontal,
    verticalLineCount: directionCounts.vertical,
    diagonalLineCount: directionCounts.diagonal,
    horizontalLineRatio: directionTotal ? directionCounts.horizontal / directionTotal : 0,
    verticalLineRatio: directionTotal ? directionCounts.vertical / directionTotal : 0,
    diagonalLineRatio: directionTotal ? directionCounts.diagonal / directionTotal : 0,
    curveRatio: directionTotal ? directionCounts.curve / directionTotal : 0,
    totalLength,
    boundingBox,
    bottomPointCount: uniqueCoordinateCount(bottomPoints),
    bottomMiddlePointCount: uniqueCoordinateCount(bottomMiddlePoints),
    bottomNonMiddlePointCount: uniqueCoordinateCount(bottomNonMiddlePoints),
    fillRatio: bboxArea ? totalLength / bboxArea : 0,
    centroid
  };
}

export function toSvgPath(stroke: Stroke): string {
  if (stroke.length < 2) return "";
  if (stroke.length === 2) return `M ${stroke[0].x} ${stroke[0].y} L ${stroke[1].x} ${stroke[1].y}`;

  const commands = [`M ${stroke[0].x} ${stroke[0].y}`];
  for (let index = 0; index < stroke.length - 1; index += 1) {
    const [control1, control2] = controlPoints(stroke, index);
    const end = stroke[index + 1];
    commands.push(`C ${control1.x} ${control1.y} ${control2.x} ${control2.y} ${end.x} ${end.y}`);
  }
  return commands.join(" ");
}
