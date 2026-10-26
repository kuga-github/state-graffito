import mysql, { type Pool } from "mysql2/promise";

declare global {
  // eslint-disable-next-line no-var
  var characterPathPool: Pool | undefined;
}

export const db =
  global.characterPathPool ??
  mysql.createPool({
    host: process.env.DB_HOST ?? "127.0.0.1",
    port: Number(process.env.DB_PORT ?? 3306),
    database: process.env.DB_NAME ?? "state_graffito",
    user: process.env.DB_USER ?? "state_graffito",
    password: process.env.DB_PASSWORD ?? "state-graffito",
    waitForConnections: true,
    connectionLimit: 10,
    charset: "utf8mb4"
  });

if (process.env.NODE_ENV !== "production") global.characterPathPool = db;
