import React from "react";
import { List } from "react-window";

function isObject(val) {
  return val && typeof val === "object" && !Array.isArray(val);
}

export default function TableVirtualList({ items, keys }) {
  // Debug: log props recebidas
  console.log("TableVirtualList props:", { items, keys });

  if (!Array.isArray(items) || !Array.isArray(keys)) {
    console.error("Dados inválidos recebidos em TableVirtualList", { items, keys });
    return <div style={{ color: "red" }}>Dados inválidos para a tabela.</div>;
  }
  if (items.length === 0 || keys.length === 0) {
    return <div style={{ color: "#888" }}>Nenhum dado para exibir.</div>;
  }

  const Row = ({ index, style }) => {
      console.log("AQUI");
    const item = items[index];
    if (!isObject(item)) {
      console.warn("Item inválido no index", index, item);
      return (
        <div style={{ ...style, display: "flex", color: "red" }}>
          <div style={{ flex: 1, padding: "0.5em" }}>
            [Erro: item inválido]
          </div>
        </div>
      );
    }

    console.log("Renderizando linha", index, item);
    return (
      <div style={{ ...style, display: "flex" }}>
        {keys.map((key) => (
          <div
            key={key}
            style={{
              flex: 1,
              borderBottom: "1px solid #eee",
              padding: "0.5em",
              wordBreak: "break-all",
              background: index % 2 === 0 ? "#fff" : "#f9f9f9",
            }}
          >
            {item[key] !== undefined && item[key] !== null
              ? typeof item[key] === "object"
                ? JSON.stringify(item[key])
                : String(item[key])
              : ""}
          </div>
        ))}
      </div>
    );
  };

  try {
    return (
      <List
        height={500}
        itemCount={items.length}
        itemSize={40}
        width={"100%"}
        style={{ border: "1px solid #ccc" }}
      >
        {Row}
      </List>
    );
  } catch (e) {
    return (
      <div style={{ color: "red" }}>
        Erro ao renderizar lista virtual. Renderizando tabela simples para debug.<br />
        {e && e.toString()}
        <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 8 }}>
          <thead>
            <tr>
              {keys.map((key) => (
                <th key={key} style={{ border: "1px solid #ccc", padding: 4 }}>{key}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items.map((item, idx) => (
              <tr key={idx} style={{ background: idx % 2 === 0 ? "#fff" : "#f9f9f9" }}>
                {isObject(item)
                  ? keys.map((key) => (
                      <td key={key} style={{ border: "1px solid #ccc", padding: 4 }}>
                        {item[key] !== undefined && item[key] !== null
                          ? typeof item[key] === "object"
                            ? JSON.stringify(item[key])
                            : String(item[key])
                          : ""}
                      </td>
                    ))
                  : <td colSpan={keys.length} style={{ color: "red" }}>[Erro: item inválido]</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
}
