/** Флаг первой выкатки: в тихом режиме анализ скрыт, пока работник догоняет
 *  очередь и строит первую норму. По умолчанию показан. Читается при запросе,
 *  а не при сборке: переключается правкой окружения без пересборки. */
export function anomalyReportVisible() {
  return (process.env.ANOMALY_REPORT_VISIBLE ?? "true").trim().toLowerCase() !== "false";
}
