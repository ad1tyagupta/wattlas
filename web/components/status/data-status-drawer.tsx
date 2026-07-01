import { connectorLabel, formatSnapshotTime } from "@/lib/format";
import type { SnapshotManifest } from "@/lib/snapshot/types";

type Props = { manifest: SnapshotManifest; open: boolean; onClose: () => void };

export function DataStatusDrawer({ manifest, open, onClose }: Props) {
  if (!open) return null;
  return (
    <div className="drawer-backdrop" onMouseDown={onClose}>
      <aside className="drawer status-drawer" onMouseDown={(event) => event.stopPropagation()} aria-label="Data source status">
        <div className="drawer-header"><div><small>Snapshot integrity</small><h2>Data source status</h2></div><button type="button" onClick={onClose} aria-label="Close data source status">×</button></div>
        <p className="drawer-intro">The map serves the last successful validated snapshot. One failed source cannot erase usable data.</p>
        <div className="status-summary"><span>Snapshot</span><strong>{formatSnapshotTime(manifest.generatedAt)}</strong><span>Model</span><strong>{manifest.modelVersion}</strong></div>
        <div className="connector-list">
          {manifest.connectors.map((connector) => (
            <article key={connector.id} className="connector-row">
              <span className={`connector-state ${connector.state}`} aria-label={connector.state} />
              <div>
                <strong>{connectorLabel(connector.id)}</strong>
                <small>{connector.lastSuccessAt ? `Observed ${formatSnapshotTime(connector.lastSuccessAt)}` : "Observation unavailable"}</small>
                <small>Checked {formatSnapshotTime(connector.checkedAt)}</small>
                {connector.message ? <small className="connector-message">{connector.message}</small> : null}
              </div>
              <em>{connector.state.replace("_", " ")}</em>
            </article>
          ))}
        </div>
      </aside>
    </div>
  );
}
