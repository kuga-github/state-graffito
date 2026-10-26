"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toSvgPath } from "@/lib/geometry";
import type { CharacterPath, PointRole, Stroke, VectorPoint } from "@/lib/types";

const gridLines = Array.from({ length: 17 }, (_, index) => index);
const labels: Record<PointRole, string> = { start: "Start", middle: "Midpoint", end: "End" };
const colors: Record<PointRole, string> = { start: "#2e8b57", middle: "#e99a1a", end: "#c74440" };

type PointDrag = { strokeIndex: number; pointIndex: number; pointerId: number; moved: boolean };

const hasCoincidentEndpoints = (stroke: Stroke) => {
  const start = stroke[0];
  const end = stroke[stroke.length - 1];
  return stroke.length >= 2 && start.x === end.x && start.y === end.y;
};

const gridCoordinates = (svg: SVGSVGElement, clientX: number, clientY: number) => {
  const rect = svg.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;
  const x = Math.round(((clientX - rect.left) / rect.width) * 17 - 8.5);
  const y = Math.round(((clientY - rect.top) / rect.height) * 17 - 8.5);
  return x >= -8 && x <= 8 && y >= -8 && y <= 8 ? { x, y } : null;
};

export default function Editor() {
  const [paths, setPaths] = useState<CharacterPath[]>([]);
  const [category, setCategory] = useState("");
  const [name, setName] = useState("");
  const [strokes, setStrokes] = useState<Stroke[][]>([]);
  const [activeStroke, setActiveStroke] = useState(0);
  const [nextRole, setNextRole] = useState<PointRole>("middle");
  const [previewMode, setPreviewMode] = useState(false);
  const [saved, setSaved] = useState<CharacterPath | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const activePoints = strokes[activeStroke]?.[0] ?? [];
  const categories = useMemo(
    () => [...new Set(paths.map((path) => path.category))].sort((left, right) => left.localeCompare(right)),
    [paths]
  );
  const pointDrag = useRef<PointDrag | null>(null);
  const suppressClick = useRef(false);

  const loadPaths = useCallback(async () => {
    const response = await fetch("/api/paths");
    if (!response.ok) throw new Error("Could not load saved paths.");
    setPaths((await response.json()) as CharacterPath[]);
  }, []);

  useEffect(() => {
    loadPaths().catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Could not load the path list."));
  }, [loadPaths]);

  const addPoint = (x: number, y: number) => {
    setError("");
    setSaved(null);
    if (nextRole === "start") {
      if (!activePoints.length) {
        if (strokes.length) {
          setStrokes((current) => current.map((strokeSet, index) =>
            index === activeStroke ? [[{ x, y, role: "start" }]] : strokeSet
          ));
        } else {
          setStrokes([[[{ x, y, role: "start" }]]]);
          setActiveStroke(0);
        }
      } else if (activePoints[activePoints.length - 1].role === "end") {
        const newStrokeIndex = strokes.length;
        setStrokes((current) => [...current, [[{ x, y, role: "start" }]]]);
        setActiveStroke(newStrokeIndex);
      } else {
        setError("Set the current stroke's end point before adding a new start point.");
        return;
      }
      setNextRole("end");
      return;
    }
    if (!strokes.length) {
      setStrokes([[[{ x, y, role: "start" }]]]);
      setActiveStroke(0);
      setNextRole("end");
      return;
    }
    if (activePoints.length && activePoints[activePoints.length - 1].role === "end") {
      setError("Cannot add points after an end point. Add a stroke or delete the last point.");
      return;
    }
    setStrokes((current) => current.map((strokeSet, index) => {
      if (index !== activeStroke) return strokeSet;
      const currentPoints = strokeSet[0];
      const role = currentPoints.length === 0 ? "start" : nextRole;
      return [[...currentPoints, { x, y, role }]];
    }));
    if (!activePoints.length) {
      setNextRole("end");
    } else if (nextRole === "end") {
      setNextRole("start");
    }
  };

  const updatePoint = (index: number, point: VectorPoint) => {
    setStrokes((current) => current.map((strokeSet, strokeIndex) =>
      strokeIndex === activeStroke
        ? [strokeSet[0].map((existing, pointIndex) => pointIndex === index ? point : existing)]
        : strokeSet
    ));
    setSaved(null);
  };

  const addStroke = () => {
    setStrokes((current) => [...current, [[]]]);
    setActiveStroke(strokes.length);
    setSaved(null);
  };

  const loadPath = (path: CharacterPath) => {
    setCategory(path.category);
    setName(path.name);
    setStrokes(path.strokes.map((stroke) => [stroke]));
    setActiveStroke(0);
    setSaved(path);
    setMessage(`Editing "${path.category} / ${path.name}".`);
    setError("");
  };

  const removePoint = (pointIndex: number) => {
    const remainingPoints = activePoints.filter((_, index) => index !== pointIndex);
    if (!remainingPoints.length) {
      setStrokes((current) => current.filter((_, strokeIndex) => strokeIndex !== activeStroke));
      setActiveStroke(Math.max(0, activeStroke - 1));
    } else if (activePoints[pointIndex].role === "end") {
      setStrokes((current) => current.map((strokeSet, strokeIndex) =>
        strokeIndex === activeStroke ? [remainingPoints] : strokeSet
      ));
      setNextRole("end");
    } else {
      setStrokes((current) => current.map((strokeSet, strokeIndex) => {
        if (strokeIndex !== activeStroke) return strokeSet;
        const points = remainingPoints;
        points[0] = { ...points[0], role: "start" };
        if (points.length > 1) points[points.length - 1] = { ...points[points.length - 1], role: "end" };
        for (let index = 1; index < points.length - 1; index += 1) {
          points[index] = { ...points[index], role: "middle" };
        }
        return [points];
      }));
    }
    setSaved(null);
  };

  const save = async () => {
    setError("");
    setMessage("");
    const normalized = strokes.map((strokeSet) => strokeSet[0]).filter((stroke) => stroke.length > 0);
    try {
      const response = await fetch("/api/paths", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ category, name, strokes: normalized })
      });
      const body = (await response.json()) as CharacterPath | { error: string; reason?: string };
      if (!response.ok) {
        const failure = body as { error: string; reason?: string };
        throw new Error([failure.error, failure.reason ? `Reason: ${failure.reason}` : ""].filter(Boolean).join("\n"));
      }
      const path = body as CharacterPath;
      setSaved(path);
      setMessage("Character path and metrics saved.");
      await loadPaths();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save the character path.");
    }
  };

  const deletePath = async (path: CharacterPath) => {
    if (!window.confirm(`Delete "${path.category} / ${path.name}"?`)) return;
    setError("");
    setMessage("");
    try {
      const response = await fetch(`/api/paths/${path.id}`, { method: "DELETE" });
      const body = (await response.json()) as { error?: string; reason?: string };
      if (!response.ok) {
        throw new Error([body.error ?? "Could not delete the character path.", body.reason ? `Reason: ${body.reason}` : ""]
          .filter(Boolean)
          .join("\n"));
      }
      setPaths((current) => current.filter((item) => item.id !== path.id));
      if (saved?.id === path.id || (category === path.category && name === path.name)) {
        setCategory("");
        setName("");
        setStrokes([]);
        setActiveStroke(0);
        setSaved(null);
      }
      setMessage(`Deleted "${path.category} / ${path.name}".`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not delete the character path.");
    }
  };

  const svgStrokes = useMemo(() => strokes.map((set) => set[0]), [strokes]);
  const gridLinePath = (lineIndex: number, vertical: boolean) => gridLines.map((pointIndex, index) => {
    const x = vertical ? lineIndex - 8 : pointIndex - 8;
    const y = vertical ? pointIndex - 8 : lineIndex - 8;
    return `${index === 0 ? "M" : "L"}${x},${y}`;
  }).join(" ");
  const inactiveStrokeIndexes = useMemo(
    () => strokes.map((_, index) => index).filter((index) => index !== activeStroke),
    [strokes.length, activeStroke]
  );
  const hasActiveStroke = activeStroke >= 0 && activeStroke < strokes.length;
  const renderPoint = (strokeIndex: number, point: VectorPoint, pointIndex: number, isActive: boolean) => (
    <g
      key={`${strokeIndex}-${pointIndex}`}
      onPointerDown={(event) => {
        if (!isActive) return;
        event.stopPropagation();
        event.preventDefault();
        const svg = event.currentTarget.ownerSVGElement;
        if (!svg) return;
        pointDrag.current = { strokeIndex, pointIndex, pointerId: event.pointerId, moved: false };
        svg.setPointerCapture(event.pointerId);
      }}
      onClick={(event) => {
        event.stopPropagation();
        if (suppressClick.current) {
          suppressClick.current = false;
          return;
        }
        if (nextRole === "start" || nextRole === "end") {
          addPoint(point.x, point.y);
        } else {
          setActiveStroke(strokeIndex);
        }
      }}
      style={{ cursor: isActive ? "grab" : "pointer", touchAction: isActive ? "none" : "manipulation" }}
    >
      <circle
        cx={point.x}
        cy={point.y}
        r=".27"
        fill={isActive ? colors[point.role] : "#b8beb8"}
        opacity={isActive ? 1 : 0.65}
        stroke={isActive ? "white" : "#f4f3ef"}
        strokeWidth=".06"
      />
    </g>
  );

  return (
    <main className="shell">
      <header className="header">
        <h1>Generate Character Path</h1>
      </header>
      <div className="layout">
        <section className="card">
          <h2>17×17 Vector Editor</h2>
          <div className="field-grid">
            <label className="field">Category
              <input list="existing-categories" value={category} onChange={(event) => setCategory(event.target.value)} maxLength={120} />
              <datalist id="existing-categories">
                {categories.map((existingCategory) => <option key={existingCategory} value={existingCategory} />)}
              </datalist>
            </label>
            <label className="field">Name<input value={name} onChange={(event) => setName(event.target.value)} maxLength={120} /></label>
          </div>
          <div className="toolbar">
            <label>Next point <select value={nextRole} onChange={(event) => setNextRole(event.target.value as PointRole)}>
              <option value="middle">Midpoint</option><option value="end">End</option><option value="start">Start</option>
            </select></label>
            {strokes.length > 0
              ? <label>Active stroke <select value={activeStroke} onChange={(event) => setActiveStroke(Number(event.target.value))}>
                {strokes.map((_, index) => <option key={index} value={index}>{index + 1}</option>)}
              </select></label>
              : <span className="muted">No strokes</span>}
            <button type="button" onClick={addStroke}>Add stroke</button>
            <button type="button" aria-pressed={previewMode} onClick={() => setPreviewMode((current) => !current)}>
              Preview {previewMode ? "ON" : "OFF"}
            </button>
          </div>
          <svg
            className={previewMode ? "grid grid-preview" : "grid"}
            viewBox="-8.5 -8.5 17 17"
            role="img"
            aria-label="17×17 editing grid"
            onPointerDownCapture={() => { suppressClick.current = false; }}
            onPointerMove={(event) => {
              const drag = pointDrag.current;
              if (!drag || drag.pointerId !== event.pointerId || drag.strokeIndex !== activeStroke) return;
              const coordinates = gridCoordinates(event.currentTarget, event.clientX, event.clientY);
              const currentPoint = strokes[drag.strokeIndex]?.[0]?.[drag.pointIndex];
              if (!coordinates || !currentPoint || (coordinates.x === currentPoint.x && coordinates.y === currentPoint.y)) return;
              drag.moved = true;
              updatePoint(drag.pointIndex, { ...currentPoint, ...coordinates });
            }}
            onPointerUp={(event) => {
              const drag = pointDrag.current;
              if (!drag || drag.pointerId !== event.pointerId) return;
              suppressClick.current = drag.moved;
              pointDrag.current = null;
            }}
            onPointerCancel={(event) => {
              if (pointDrag.current?.pointerId !== event.pointerId) return;
              pointDrag.current = null;
              suppressClick.current = false;
            }}
          >
            {!previewMode && gridLines.map((index) => {
              return <g
                key={index}
                stroke={index % 4 === 0 ? "#56634f" : index % 2 === 0 ? "#aeb7a8" : "#e0e4dc"}
                strokeWidth={index % 4 === 0 ? ".11" : index % 2 === 0 ? ".065" : ".035"}
              >
                <path d={gridLinePath(index, true)} fill="none" />
                <path d={gridLinePath(index, false)} fill="none" />
              </g>;
            })}
            {!previewMode && <rect x="-8.5" y="-8.5" width="17" height="17" fill="transparent" pointerEvents="all" onClick={(event) => {
              const svg = event.currentTarget.ownerSVGElement;
              if (!svg) return;
              const coordinates = gridCoordinates(svg, event.clientX, event.clientY);
              if (coordinates) addPoint(coordinates.x, coordinates.y);
            }} />}
            {previewMode
              ? svgStrokes.map((stroke, index) => <g key={`preview-line-${index}`}>
                <path d={toSvgPath(stroke)} fill="none" stroke="#354c3c" strokeWidth=".16" />
                {hasCoincidentEndpoints(stroke) && <circle
                  cx={stroke[0].x}
                  cy={stroke[0].y}
                  r=".16"
                  fill="#354c3c"
                />}
              </g>)
              : <>
            {inactiveStrokeIndexes.map((index) => <g key={`line-${index}`}>
              <path d={toSvgPath(svgStrokes[index])} fill="none" stroke="#aeb4ae" opacity=".7" strokeWidth=".12" />
              {hasCoincidentEndpoints(svgStrokes[index]) && <circle
                cx={svgStrokes[index][0].x}
                cy={svgStrokes[index][0].y}
                r=".35"
                fill="none"
                stroke="#aeb4ae"
                strokeWidth=".08"
                opacity=".8"
                pointerEvents="none"
              />}
            </g>)}
            {inactiveStrokeIndexes.flatMap((strokeIndex) =>
              svgStrokes[strokeIndex].map((point, pointIndex) => renderPoint(strokeIndex, point, pointIndex, false))
            )}
            {hasActiveStroke && <g>
              <path d={toSvgPath(svgStrokes[activeStroke])} fill="none" stroke="#354c3c" strokeWidth=".12" />
              {hasCoincidentEndpoints(svgStrokes[activeStroke]) && <circle
                cx={svgStrokes[activeStroke][0].x}
                cy={svgStrokes[activeStroke][0].y}
                r=".35"
                fill="none"
                stroke="#354c3c"
                strokeWidth=".08"
                pointerEvents="none"
              />}
            </g>}
            {hasActiveStroke && svgStrokes[activeStroke].map((point, pointIndex) =>
              renderPoint(activeStroke, point, pointIndex, true)
            )}
              </>}
          </svg>
          <div className="toolbar">
            {!previewMode && <span className="muted">● Start　● Midpoint　● End</span>}
            <button type="button" onClick={save}>Save to database</button>
          </div>
          {!previewMode && <div className="point-list">
            {activePoints.map((point, index) => <div className="point-item" key={`${index}-${point.x}-${point.y}`}>
              <span>{index + 1}. {labels[point.role]} ({point.x}, {point.y})</span>
              <button type="button" onClick={() => removePoint(index)}>Delete</button>
            </div>)}
          </div>}
          {message && <p className="success">{message}</p>}
          {error && <p className="error">{error}</p>}
        </section>
        <section>
          {saved && <div className="card">
            <h2>Calculated Metrics</h2>
            <dl className="metrics">
              <div><dt>Total strokes</dt><dd>{saved.metrics.lineCount}</dd></div>
              <div><dt>Stroke counts (horizontal / vertical / diagonal / curved)</dt><dd>
                {saved.metrics.horizontalLineCount} / {saved.metrics.verticalLineCount} / {saved.metrics.diagonalLineCount} / {saved.metrics.curveCount}
              </dd></div>
              <div><dt>Stroke ratios (horizontal / vertical / diagonal / curved)</dt><dd>
                {(saved.metrics.horizontalLineRatio * 100).toFixed(1)}% / {(saved.metrics.verticalLineRatio * 100).toFixed(1)}% / {(saved.metrics.diagonalLineRatio * 100).toFixed(1)}% / {(saved.metrics.curveRatio * 100).toFixed(1)}%
              </dd></div>
              <div><dt>Total length</dt><dd>{saved.metrics.totalLength.toFixed(2)}</dd></div>
              <div><dt>Bounding box</dt><dd>
                Left {saved.metrics.boundingBox.minX} / Top {saved.metrics.boundingBox.minY.toFixed(2)} / Right {saved.metrics.boundingBox.maxX} / Bottom {saved.metrics.boundingBox.maxY.toFixed(2)}
                <br />Width {saved.metrics.boundingBox.width.toFixed(2)} / Height {saved.metrics.boundingBox.height.toFixed(2)}
              </dd></div>
              <div><dt>Points on vector bottom edge</dt><dd>{saved.metrics.bottomPointCount}</dd></div>
              <div><dt>Midpoints on vector bottom edge</dt><dd>{saved.metrics.bottomMiddlePointCount}</dd></div>
              <div><dt>Other points on vector bottom edge</dt><dd>{saved.metrics.bottomNonMiddlePointCount}</dd></div>
              <div><dt>Fill ratio</dt><dd>{saved.metrics.fillRatio.toFixed(3)}</dd></div>
              <div><dt>Centroid</dt><dd>({saved.metrics.centroid.x}, {saved.metrics.centroid.y})</dd></div>
            </dl>
          </div>}
          <div className="card">
            <div className="row"><h2>Saved characters ({paths.length})</h2><button type="button" onClick={() => {
              setCategory("");
              setName("");
              setStrokes([]);
              setActiveStroke(0);
              setSaved(null);
              setMessage("");
              setError("");
            }}>New</button></div>
            <div className="path-scroll path-list">
              {paths.map((path) => <div className="path-item" key={path.id}>
                <button type="button" className="path-item-open" onClick={() => loadPath(path)}>
                  <span>{path.category} / {path.name}</span><span className="muted">{path.metrics.lineCount} strokes</span>
                </button>
                <button
                  type="button"
                  className="path-item-delete"
                  aria-label={`Delete ${path.category} ${path.name}`}
                  onClick={() => deletePath(path)}
                >Delete</button>
              </div>)}
              {!paths.length && <p className="muted">No saved characters.</p>}
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
