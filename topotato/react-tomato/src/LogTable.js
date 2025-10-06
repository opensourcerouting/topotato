import React from "react";
import { TableVirtuoso } from "react-virtuoso";

const levelColors = {
  error: "#f8d7da",
  warn: "#ffe5b4",
  info: "#e3f2fd",
  notif: "#e2e3e5",
  command: "#f8f9fa",
  pylog: "#f5f5f5",
};

const levelTextColors = {
  error: "#721c24",
  warn: "#8a6d3b",
  info: "#0c5460",
  notif: "#383d41",
  command: "#495057",
  pylog: "#495057",
};

function getRowStyle(level) {
  return {
    background: levelColors[level] || "#fff",
    color: levelTextColors[level] || "#222",
    borderBottom: "1px solid #e0e0e0",
    fontFamily: "monospace",
    fontSize: 14,
    verticalAlign: 'top',
  };
}

function getLevel(entry) {
  if (entry.data?.type === "pylog") return "pylog";
  if (entry.data?.type === "log") return entry.data.level || "info";
  if (entry.data?.type === "vtysh") return "command";
  if (entry.data?.type === "packet") return "notif";
  return "info";
}

function renderMessage(entry) {
  if (entry.data?.type === "vtysh")
    return <span style={{color: '#495057'}}>&#x2610; <b>{entry.data.command}</b></span>;

  if (entry.data?.type === "pylog")
    return <i>unknown event: pylog</i>;

  // Novo: packet
  if (entry.data?.type === "packet") {
    // Mostra só o início do dump para não poluir a tabela
    const dump = entry.data.dump || "";
    return <span style={{fontFamily: 'monospace', color: '#333'}}>{dump.split("\n")[0]} ...</span>;
  }

  // Novo: log
  if (entry.data?.type === "log") {
    const text = entry.data.text || "";
    // Destaca arquivos entre colchetes
    const parts = text.split(/(\[.*?\])/g);
    return parts.map((part, i) =>
      part.startsWith("[") && part.endsWith("]") ? (
        <span key={i} style={{color: '#007bff', textDecoration: 'underline'}}>{part}</span>
      ) : (
        <span key={i}>{part}</span>
      )
    );
  }

  if (entry.data?.msg) {
    const msg = entry.data.msg;
    const match = msg.match(/^(\w+): (.*)$/);
    if (match) {
      const [, func, rest] = match;
      const parts = rest.split(/(\[.*?\])/g);
      return <>
        <b>{func}:</b> {parts.map((part, i) =>
          part.startsWith("[") && part.endsWith("]") ? (
            <span key={i} style={{color: '#007bff', textDecoration: 'underline'}}>{part}</span>
          ) : (
            <span key={i}>{part}</span>
          )
        )}
      </>;
    }
    const parts = msg.split(/(\[.*?\])/g);
    return parts.map((part, i) =>
      part.startsWith("[") && part.endsWith("]") ? (
        <span key={i} style={{color: '#007bff', textDecoration: 'underline'}}>{part}</span>
      ) : (
        <span key={i}>{part}</span>
      )
    );
  }
  return entry.data?.msg || "";
}

export default function LogTable({ logs }) {
  if (!logs || logs.length === 0) return null;

  return (
    <div style={{ border: '1px solid #bdbdbd', borderRadius: 4, margin: 0, background: '#fff' }}>
      <TableVirtuoso
        style={{ width: "100%", maxHeight: 320 }}
        data={logs}
        components={{
          Table: (props) => <table {...props} style={{ width: "100%", borderCollapse: "collapse", marginTop: 0 }} />,
          TableHead: (props) => (
            <thead {...props}>
              <tr style={{ background: "#f0f0f0", fontWeight: "bold" }}>
                <th style={{ width: 60, textAlign: 'right', padding: '2px 8px' }}>Time</th>
                <th style={{ width: 40, textAlign: 'left', padding: '2px 8px' }}>Host</th>
                <th style={{ width: 60, textAlign: 'left', padding: '2px 8px' }}>Service</th>
                <th style={{ width: 60, textAlign: 'left', padding: '2px 8px' }}>ID</th>
                <th style={{ width: 60, textAlign: 'left', padding: '2px 8px' }}>Level</th>
                <th style={{ textAlign: 'left', padding: '2px 8px' }}>Message</th>
              </tr>
            </thead>
          ),
        }}
        itemContent={(i, entry) => {
          const level = getLevel(entry);
          return [
            <td key="time" style={{...getRowStyle(level), textAlign: 'right', padding: '2px 8px'}}>{entry.ts?.toFixed(3) ?? ""}</td>,
            <td key="host" style={{...getRowStyle(level), textAlign: 'left', padding: '2px 8px'}}>{entry.data?.host || ""}</td>,
            <td key="service" style={{...getRowStyle(level), textAlign: 'left', padding: '2px 8px'}}>{entry.data?.service || ""}</td>,
            <td key="id" style={{...getRowStyle(level), textAlign: 'left', padding: '2px 8px'}}>{entry.data?.id || ""}</td>,
            <td key="level" style={{ ...getRowStyle(level), fontWeight: "bold", textAlign: 'left', padding: '2px 8px' }}>{level}</td>,
            <td key="msg" style={{...getRowStyle(level), textAlign: 'left', padding: '2px 8px'}}>{renderMessage(entry)}</td>,
          ];
        }}
      />
    </div>
  );
}
