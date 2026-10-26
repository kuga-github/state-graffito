export type PointRole = "start" | "middle" | "end";

export interface VectorPoint {
  x: number;
  y: number;
  role: PointRole;
}

export type Stroke = VectorPoint[];

export interface BoundingBox {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
  width: number;
  height: number;
}

export interface PathMetrics {
  lineCount: number;
  curveCount: number;
  horizontalLineCount: number;
  verticalLineCount: number;
  diagonalLineCount: number;
  horizontalLineRatio: number;
  verticalLineRatio: number;
  diagonalLineRatio: number;
  curveRatio: number;
  totalLength: number;
  boundingBox: BoundingBox;
  bottomPointCount: number;
  bottomMiddlePointCount: number;
  bottomNonMiddlePointCount: number;
  fillRatio: number;
  centroid: { x: number; y: number };
}

export interface CharacterPath {
  id: number;
  category: string;
  name: string;
  strokes: Stroke[];
  metrics: PathMetrics;
  updatedAt: string;
}
