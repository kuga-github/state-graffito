import type { RowDataPacket } from "mysql2";
import { db } from "@/lib/db";
import { calculateMetrics } from "@/lib/geometry";
import type { Stroke } from "@/lib/types";

const centeredCoordinatesMigration = "coordinates-centered-at-zero-v1";
const cubicBezierMetricsMigration = "cubic-bezier-metrics-v1";
const allPointCentroidMigration = "all-point-centroid-v1";
const bottomPointCountsMigration = "bottom-point-counts-v1";
const vectorPointBottomCountsMigration = "vector-point-bottom-counts-v1";
const uniqueBottomPointCountsMigration = "unique-bottom-point-counts-v1";
const straightLineDirectionMetricsMigration = "straight-line-direction-metrics-v1";
const pathDirectionMetricsMigration = "path-direction-metrics-v1";
const bottomPointTotalOnlyMigration = "bottom-point-total-only-v1";
const bottomPointCategoryCountsMigration = "bottom-point-category-counts-v1";

interface LegacyPathRow extends RowDataPacket {
  id: number;
  strokes: Stroke[] | string;
}

declare global {
  // eslint-disable-next-line no-var
  var coordinateMigrationPromise: Promise<void> | undefined;
  // eslint-disable-next-line no-var
  var cubicBezierMetricsMigrationPromise: Promise<void> | undefined;
  // eslint-disable-next-line no-var
  var allPointCentroidMigrationPromise: Promise<void> | undefined;
  // eslint-disable-next-line no-var
  var bottomPointCountsMigrationPromise: Promise<void> | undefined;
  // eslint-disable-next-line no-var
  var vectorPointBottomCountsMigrationPromise: Promise<void> | undefined;
  // eslint-disable-next-line no-var
  var uniqueBottomPointCountsMigrationPromise: Promise<void> | undefined;
  // eslint-disable-next-line no-var
  var straightLineDirectionMetricsMigrationPromise: Promise<void> | undefined;
  // eslint-disable-next-line no-var
  var pathDirectionMetricsMigrationPromise: Promise<void> | undefined;
  // eslint-disable-next-line no-var
  var bottomPointTotalOnlyMigrationPromise: Promise<void> | undefined;
  // eslint-disable-next-line no-var
  var bottomPointCategoryCountsMigrationPromise: Promise<void> | undefined;
}

async function migrateLegacyCoordinates(): Promise<void> {
  const connection = await db.getConnection();
  let transactionStarted = false;

  try {
    await connection.query(`
      CREATE TABLE IF NOT EXISTS application_migrations (
        name VARCHAR(120) NOT NULL PRIMARY KEY,
        applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
      )
    `);
    const [applied] = await connection.execute<RowDataPacket[]>(
      "SELECT name FROM application_migrations WHERE name = ?",
      [centeredCoordinatesMigration]
    );
    if (applied.length) return;

    await connection.beginTransaction();
    transactionStarted = true;
    const [paths] = await connection.query<LegacyPathRow[]>(
      "SELECT id, strokes FROM character_paths FOR UPDATE"
    );
    for (const path of paths) {
      const strokes = typeof path.strokes === "string" ? JSON.parse(path.strokes) as Stroke[] : path.strokes;
      const centeredStrokes = strokes.map((stroke) =>
        stroke.map((point) => ({ ...point, x: point.x - 8, y: point.y - 8 }))
      );
      await connection.execute(
        "UPDATE character_paths SET strokes = ?, metrics = ? WHERE id = ?",
        [JSON.stringify(centeredStrokes), JSON.stringify(calculateMetrics(centeredStrokes)), path.id]
      );
    }
    await connection.execute(
      "INSERT INTO application_migrations (name) VALUES (?)",
      [centeredCoordinatesMigration]
    );
    await connection.commit();
    transactionStarted = false;
  } catch (error) {
    if (transactionStarted) await connection.rollback();
    throw error;
  } finally {
    connection.release();
  }
}

async function migrateCubicBezierMetrics(): Promise<void> {
  const connection = await db.getConnection();
  let transactionStarted = false;

  try {
    const [applied] = await connection.execute<RowDataPacket[]>(
      "SELECT name FROM application_migrations WHERE name = ?",
      [cubicBezierMetricsMigration]
    );
    if (applied.length) return;

    await connection.beginTransaction();
    transactionStarted = true;
    const [paths] = await connection.query<LegacyPathRow[]>(
      "SELECT id, strokes FROM character_paths FOR UPDATE"
    );
    for (const path of paths) {
      const strokes = typeof path.strokes === "string" ? JSON.parse(path.strokes) as Stroke[] : path.strokes;
      await connection.execute(
        "UPDATE character_paths SET metrics = ? WHERE id = ?",
        [JSON.stringify(calculateMetrics(strokes)), path.id]
      );
    }
    await connection.execute(
      "INSERT INTO application_migrations (name) VALUES (?)",
      [cubicBezierMetricsMigration]
    );
    await connection.commit();
    transactionStarted = false;
  } catch (error) {
    if (transactionStarted) await connection.rollback();
    throw error;
  } finally {
    connection.release();
  }
}

async function migrateAllPointCentroids(): Promise<void> {
  const connection = await db.getConnection();
  let transactionStarted = false;

  try {
    const [applied] = await connection.execute<RowDataPacket[]>(
      "SELECT name FROM application_migrations WHERE name = ?",
      [allPointCentroidMigration]
    );
    if (applied.length) return;

    await connection.beginTransaction();
    transactionStarted = true;
    const [paths] = await connection.query<LegacyPathRow[]>(
      "SELECT id, strokes FROM character_paths FOR UPDATE"
    );
    for (const path of paths) {
      const strokes = typeof path.strokes === "string" ? JSON.parse(path.strokes) as Stroke[] : path.strokes;
      await connection.execute(
        "UPDATE character_paths SET metrics = ? WHERE id = ?",
        [JSON.stringify(calculateMetrics(strokes)), path.id]
      );
    }
    await connection.execute(
      "INSERT INTO application_migrations (name) VALUES (?)",
      [allPointCentroidMigration]
    );
    await connection.commit();
    transactionStarted = false;
  } catch (error) {
    if (transactionStarted) await connection.rollback();
    throw error;
  } finally {
    connection.release();
  }
}

async function migrateBottomPointCounts(): Promise<void> {
  const connection = await db.getConnection();
  let transactionStarted = false;

  try {
    const [applied] = await connection.execute<RowDataPacket[]>(
      "SELECT name FROM application_migrations WHERE name = ?",
      [bottomPointCountsMigration]
    );
    if (applied.length) return;

    await connection.beginTransaction();
    transactionStarted = true;
    const [paths] = await connection.query<LegacyPathRow[]>(
      "SELECT id, strokes FROM character_paths FOR UPDATE"
    );
    for (const path of paths) {
      const strokes = typeof path.strokes === "string" ? JSON.parse(path.strokes) as Stroke[] : path.strokes;
      await connection.execute(
        "UPDATE character_paths SET metrics = ? WHERE id = ?",
        [JSON.stringify(calculateMetrics(strokes)), path.id]
      );
    }
    await connection.execute(
      "INSERT INTO application_migrations (name) VALUES (?)",
      [bottomPointCountsMigration]
    );
    await connection.commit();
    transactionStarted = false;
  } catch (error) {
    if (transactionStarted) await connection.rollback();
    throw error;
  } finally {
    connection.release();
  }
}

async function migrateVectorPointBottomCounts(): Promise<void> {
  const connection = await db.getConnection();
  let transactionStarted = false;

  try {
    const [applied] = await connection.execute<RowDataPacket[]>(
      "SELECT name FROM application_migrations WHERE name = ?",
      [vectorPointBottomCountsMigration]
    );
    if (applied.length) return;

    await connection.beginTransaction();
    transactionStarted = true;
    const [paths] = await connection.query<LegacyPathRow[]>(
      "SELECT id, strokes FROM character_paths FOR UPDATE"
    );
    for (const path of paths) {
      const strokes = typeof path.strokes === "string" ? JSON.parse(path.strokes) as Stroke[] : path.strokes;
      await connection.execute(
        "UPDATE character_paths SET metrics = ? WHERE id = ?",
        [JSON.stringify(calculateMetrics(strokes)), path.id]
      );
    }
    await connection.execute(
      "INSERT INTO application_migrations (name) VALUES (?)",
      [vectorPointBottomCountsMigration]
    );
    await connection.commit();
    transactionStarted = false;
  } catch (error) {
    if (transactionStarted) await connection.rollback();
    throw error;
  } finally {
    connection.release();
  }
}

async function migrateUniqueBottomPointCounts(): Promise<void> {
  const connection = await db.getConnection();
  let transactionStarted = false;

  try {
    const [applied] = await connection.execute<RowDataPacket[]>(
      "SELECT name FROM application_migrations WHERE name = ?",
      [uniqueBottomPointCountsMigration]
    );
    if (applied.length) return;

    await connection.beginTransaction();
    transactionStarted = true;
    const [paths] = await connection.query<LegacyPathRow[]>(
      "SELECT id, strokes FROM character_paths FOR UPDATE"
    );
    for (const path of paths) {
      const strokes = typeof path.strokes === "string" ? JSON.parse(path.strokes) as Stroke[] : path.strokes;
      await connection.execute(
        "UPDATE character_paths SET metrics = ? WHERE id = ?",
        [JSON.stringify(calculateMetrics(strokes)), path.id]
      );
    }
    await connection.execute(
      "INSERT INTO application_migrations (name) VALUES (?)",
      [uniqueBottomPointCountsMigration]
    );
    await connection.commit();
    transactionStarted = false;
  } catch (error) {
    if (transactionStarted) await connection.rollback();
    throw error;
  } finally {
    connection.release();
  }
}

async function migrateStraightLineDirectionMetrics(): Promise<void> {
  const connection = await db.getConnection();
  let transactionStarted = false;

  try {
    const [applied] = await connection.execute<RowDataPacket[]>(
      "SELECT name FROM application_migrations WHERE name = ?",
      [straightLineDirectionMetricsMigration]
    );
    if (applied.length) return;

    await connection.beginTransaction();
    transactionStarted = true;
    const [paths] = await connection.query<LegacyPathRow[]>(
      "SELECT id, strokes FROM character_paths FOR UPDATE"
    );
    for (const path of paths) {
      const strokes = typeof path.strokes === "string" ? JSON.parse(path.strokes) as Stroke[] : path.strokes;
      await connection.execute(
        "UPDATE character_paths SET metrics = ? WHERE id = ?",
        [JSON.stringify(calculateMetrics(strokes)), path.id]
      );
    }
    await connection.execute(
      "INSERT INTO application_migrations (name) VALUES (?)",
      [straightLineDirectionMetricsMigration]
    );
    await connection.commit();
    transactionStarted = false;
  } catch (error) {
    if (transactionStarted) await connection.rollback();
    throw error;
  } finally {
    connection.release();
  }
}

async function migratePathDirectionMetrics(): Promise<void> {
  const connection = await db.getConnection();
  let transactionStarted = false;

  try {
    const [applied] = await connection.execute<RowDataPacket[]>(
      "SELECT name FROM application_migrations WHERE name = ?",
      [pathDirectionMetricsMigration]
    );
    if (applied.length) return;

    await connection.beginTransaction();
    transactionStarted = true;
    const [paths] = await connection.query<LegacyPathRow[]>(
      "SELECT id, strokes FROM character_paths FOR UPDATE"
    );
    for (const path of paths) {
      const strokes = typeof path.strokes === "string" ? JSON.parse(path.strokes) as Stroke[] : path.strokes;
      await connection.execute(
        "UPDATE character_paths SET metrics = ? WHERE id = ?",
        [JSON.stringify(calculateMetrics(strokes)), path.id]
      );
    }
    await connection.execute(
      "INSERT INTO application_migrations (name) VALUES (?)",
      [pathDirectionMetricsMigration]
    );
    await connection.commit();
    transactionStarted = false;
  } catch (error) {
    if (transactionStarted) await connection.rollback();
    throw error;
  } finally {
    connection.release();
  }
}

async function migrateBottomPointTotalOnly(): Promise<void> {
  const connection = await db.getConnection();
  let transactionStarted = false;

  try {
    const [applied] = await connection.execute<RowDataPacket[]>(
      "SELECT name FROM application_migrations WHERE name = ?",
      [bottomPointTotalOnlyMigration]
    );
    if (applied.length) return;

    await connection.beginTransaction();
    transactionStarted = true;
    const [paths] = await connection.query<LegacyPathRow[]>(
      "SELECT id, strokes FROM character_paths FOR UPDATE"
    );
    for (const path of paths) {
      const strokes = typeof path.strokes === "string" ? JSON.parse(path.strokes) as Stroke[] : path.strokes;
      await connection.execute(
        "UPDATE character_paths SET metrics = ? WHERE id = ?",
        [JSON.stringify(calculateMetrics(strokes)), path.id]
      );
    }
    await connection.execute(
      "INSERT INTO application_migrations (name) VALUES (?)",
      [bottomPointTotalOnlyMigration]
    );
    await connection.commit();
    transactionStarted = false;
  } catch (error) {
    if (transactionStarted) await connection.rollback();
    throw error;
  } finally {
    connection.release();
  }
}

async function migrateBottomPointCategoryCounts(): Promise<void> {
  const connection = await db.getConnection();
  let transactionStarted = false;

  try {
    const [applied] = await connection.execute<RowDataPacket[]>(
      "SELECT name FROM application_migrations WHERE name = ?",
      [bottomPointCategoryCountsMigration]
    );
    if (applied.length) return;

    await connection.beginTransaction();
    transactionStarted = true;
    const [paths] = await connection.query<LegacyPathRow[]>(
      "SELECT id, strokes FROM character_paths FOR UPDATE"
    );
    for (const path of paths) {
      const strokes = typeof path.strokes === "string" ? JSON.parse(path.strokes) as Stroke[] : path.strokes;
      await connection.execute(
        "UPDATE character_paths SET metrics = ? WHERE id = ?",
        [JSON.stringify(calculateMetrics(strokes)), path.id]
      );
    }
    await connection.execute(
      "INSERT INTO application_migrations (name) VALUES (?)",
      [bottomPointCategoryCountsMigration]
    );
    await connection.commit();
    transactionStarted = false;
  } catch (error) {
    if (transactionStarted) await connection.rollback();
    throw error;
  } finally {
    connection.release();
  }
}

export function ensureCenteredCoordinates(): Promise<void> {
  if (!global.coordinateMigrationPromise) {
    global.coordinateMigrationPromise = migrateLegacyCoordinates().then(async () => {
      if (!global.cubicBezierMetricsMigrationPromise) {
        global.cubicBezierMetricsMigrationPromise = migrateCubicBezierMetrics().catch((error: unknown) => {
          global.cubicBezierMetricsMigrationPromise = undefined;
          throw error;
        });
      }
      await global.cubicBezierMetricsMigrationPromise;
      if (!global.allPointCentroidMigrationPromise) {
        global.allPointCentroidMigrationPromise = migrateAllPointCentroids().catch((error: unknown) => {
          global.allPointCentroidMigrationPromise = undefined;
          throw error;
        });
      }
      await global.allPointCentroidMigrationPromise;
      if (!global.bottomPointCountsMigrationPromise) {
        global.bottomPointCountsMigrationPromise = migrateBottomPointCounts().catch((error: unknown) => {
          global.bottomPointCountsMigrationPromise = undefined;
          throw error;
        });
      }
      await global.bottomPointCountsMigrationPromise;
      if (!global.vectorPointBottomCountsMigrationPromise) {
        global.vectorPointBottomCountsMigrationPromise = migrateVectorPointBottomCounts().catch((error: unknown) => {
          global.vectorPointBottomCountsMigrationPromise = undefined;
          throw error;
        });
      }
      await global.vectorPointBottomCountsMigrationPromise;
      if (!global.uniqueBottomPointCountsMigrationPromise) {
        global.uniqueBottomPointCountsMigrationPromise = migrateUniqueBottomPointCounts().catch((error: unknown) => {
          global.uniqueBottomPointCountsMigrationPromise = undefined;
          throw error;
        });
      }
      await global.uniqueBottomPointCountsMigrationPromise;
      if (!global.straightLineDirectionMetricsMigrationPromise) {
        global.straightLineDirectionMetricsMigrationPromise = migrateStraightLineDirectionMetrics().catch((error: unknown) => {
          global.straightLineDirectionMetricsMigrationPromise = undefined;
          throw error;
        });
      }
      await global.straightLineDirectionMetricsMigrationPromise;
      if (!global.pathDirectionMetricsMigrationPromise) {
        global.pathDirectionMetricsMigrationPromise = migratePathDirectionMetrics().catch((error: unknown) => {
          global.pathDirectionMetricsMigrationPromise = undefined;
          throw error;
        });
      }
      await global.pathDirectionMetricsMigrationPromise;
      if (!global.bottomPointTotalOnlyMigrationPromise) {
        global.bottomPointTotalOnlyMigrationPromise = migrateBottomPointTotalOnly().catch((error: unknown) => {
          global.bottomPointTotalOnlyMigrationPromise = undefined;
          throw error;
        });
      }
      await global.bottomPointTotalOnlyMigrationPromise;
      if (!global.bottomPointCategoryCountsMigrationPromise) {
        global.bottomPointCategoryCountsMigrationPromise = migrateBottomPointCategoryCounts().catch((error: unknown) => {
          global.bottomPointCategoryCountsMigrationPromise = undefined;
          throw error;
        });
      }
      await global.bottomPointCategoryCountsMigrationPromise;
    }).catch((error: unknown) => {
      global.coordinateMigrationPromise = undefined;
      throw error;
    });
  }
  return global.coordinateMigrationPromise;
}
