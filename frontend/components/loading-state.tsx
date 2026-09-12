export function LoadingState() {
  return (
    <div className="loading-state" role="status" aria-live="polite">
      <span className="sr-only">Загрузка данных</span>
      <div className="skeleton skeleton-title" />
      <div className="skeleton skeleton-lead" />
      <div className="skeleton skeleton-panel" />
      <div className="skeleton-grid">
        <div className="skeleton skeleton-card" />
        <div className="skeleton skeleton-card" />
        <div className="skeleton skeleton-card" />
      </div>
    </div>
  );
}
