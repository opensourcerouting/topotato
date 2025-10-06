import React from "react";
import { Virtuoso } from "react-virtuoso";

export default function TableVirtualList({ items, keys }) {
  if (!Array.isArray(items) || !Array.isArray(keys) || items.length === 0 || keys.length === 0) {
    return <div style={{ color: "#888" }}>Nenhum dado para exibir.</div>;
  }

  return (
    <div style={{ border: "1px solid #ccc", height: 500, width: "100%", overflow: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            {keys.map((key) => (
              <th key={key} style={{ border: "1px solid #ccc", padding: 4 }}>{key}</th>
            ))}
          </tr>
        </thead>
        <Virtuoso
          style={{ height: 460 }}
          totalCount={items.length}
          itemContent={index => (
            <tr style={{ background: index % 2 === 0 ? "#fff" : "#f9f9f9" }}>
              {keys.map(key => (
                <td key={key} style={{ border: "1px solid #ccc", padding: 4 }}>
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
      </table>
    </div>
  );
}
