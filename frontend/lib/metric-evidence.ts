import type { components } from "../../contracts/openapi/m-ranked-v1-client";
import { formatCoverage, formatDate, qualityLabel } from "./format";

export type AggregateMetric = components["schemas"]["AggregateMetric"];

export function metricEvidence(metric: AggregateMetric | undefined): string | undefined {
  if (!metric) return undefined;
  return `Выборка: ${metric.sampleSize}; покрытие: ${formatCoverage(metric.coverage)}; качество: ${qualityLabel(metric.quality)}; актуальность: ${formatDate(metric.asOf)}; ревизия: ${metric.datasetRevision}`;
}
