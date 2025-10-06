import React from "react";
import { Virtuoso } from "react-virtuoso";

function getStatusColor(status) {
  if (!status) return "#fff";
  if (status === "passed") return "#e6ffe6";
  if (status === "failed") return "#ffe6e6";
  if (status === "skipped") return "#fffbe6";
  return "#fff";
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
        <table style={{ width: "100%", borderCollapse: "collapse", background: "#fff" }}>
          <thead style={{ position: "sticky", top: 0, background: "#f0f0f0", zIndex: 2 }}>
            <tr>
              {keys.map((key) => (
                <th key={key} style={{ border: "1px solid #ccc", padding: 8, fontWeight: 600, fontSize: 15, background: "#f0f0f0" }}>{key}</th>
              ))}
            </tr>
          </thead>
        </table>
        <div style={{ height: 420 }}>
          <Virtuoso
            style={{ height: 420 }}
            totalCount={items.length}
            components={{
              Table: (props) => <table {...props} style={{ width: "100%", borderCollapse: "collapse" }} />,
              TableRow: (props) => <tr {...props} />,
            }}
            itemContent={index => (
              <tr style={{ background: index % 2 === 0 ? "#fff" : "#f7f7f7", backgroundColor: getStatusColor(items[index].status) }}>
                {keys.map(key => (
                  <td key={key} style={{ border: "1px solid #eee", padding: 8, fontSize: 14 }}>
                    {items[index][key] !== undefined && items[index][key] !== null
                      ? typeof items[index][key] === "object"
                        ? JSON.stringify(items[index][key])
                        : String(items[index][key])
                      : ""}
                  </td>
                ))}
              </tr>
            )}
          />
        </div>
      </div>
    </div>
  );
}
