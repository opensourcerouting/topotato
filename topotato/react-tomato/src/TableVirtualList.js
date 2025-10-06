import React from "react";
import { TableVirtuoso } from "react-virtuoso";

function getStatusColor(status) {
  if (!status) return "#fff";
  if (status === "passed") return "#e6ffe6";
  if (status === "failed") return "#ffe6e6";
  if (status === "skipped") return "#fffbe6";
  return "#fff";
}

function formatTimestamp(ts) {
  if (!ts) return "";
  const date = new Date(ts * 1000);
  if (isNaN(date.getTime())) return "";
  return date.toLocaleString();
}

export default function TableVirtualList({ items, keys }) {
  if (!Array.isArray(items) || !Array.isArray(keys) || items.length === 0 || keys.length === 0) {
    return <div style={{ color: "#888" }}>No data to display.</div>;
  }

  // Status summary (if 'status' field exists)
  const statusSummary = items.reduce(
    (acc, item) => {
      if (item.status) acc[item.status] = (acc[item.status] || 0) + 1;
      return acc;
    },
    {}
  );

  // Add 'Timestamp' as a virtual column if 'ts_end' exists in the data
  const hasTsEnd = keys.includes('ts_end');
  const displayKeys = hasTsEnd ? [...keys, 'Timestamp'] : keys;

  return (
    <div style={{ border: "1px solid #ccc", borderRadius: 8, background: "#fafbfc", padding: 24, maxWidth: 1200, margin: "0 auto" }}>
      <h2 style={{ marginTop: 0, marginBottom: 16, fontSize: 28, color: "#222" }}>Test Report</h2>
      <div style={{ marginBottom: 16, fontSize: 16 }}>
        <b>Total tests:</b> {items.length}
        {Object.keys(statusSummary).length > 0 && (
          <>
            {Object.entries(statusSummary).map(([status, count]) => (
              <span key={status} style={{ marginLeft: 16 }}>
                <b>{status}:</b> {count}
              </span>
            ))}
          </>
        )}
      </div>
      <div style={{ border: "1px solid #bbb", borderRadius: 4, overflow: "hidden" }}>
        <TableVirtuoso
          style={{ height: 420 }}
          data={items}
          columns={displayKeys}
          fixedHeaderContent={() => (
            <tr>
              {displayKeys.map((key) => (
                <th key={key} style={{ border: "1px solid #ccc", padding: 8, fontWeight: 600, fontSize: 15, background: "#f0f0f0", position: 'sticky', top: 0, zIndex: 2 }}>{key}</th>
              ))}
            </tr>
          )}
          itemContent={(index, item) => (
            displayKeys.map((key) => (
              key === 'Timestamp' ? (
                <td key={key} style={{ border: "1px solid #eee", padding: 8, fontSize: 14, background: getStatusColor(item.status) }}>
                  {formatTimestamp(item['ts_end'])}
                </td>
              ) : (
                <td key={key} style={{ border: "1px solid #eee", padding: 8, fontSize: 14, background: getStatusColor(item.status) }}>
                  {item[key] !== undefined && item[key] !== null
                    ? typeof item[key] === "object"
                      ? JSON.stringify(item[key])
                      : String(item[key])
                    : ""}
                </td>
              )
            ))
          )}
        />
      </div>
    </div>
  );
}
