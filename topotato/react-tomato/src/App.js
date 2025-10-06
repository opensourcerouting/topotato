import React, { useState } from "react";
import TableVirtualList from "./TableVirtualList";

function App() {
  const [items, setItems] = useState([]);
  const [keys, setKeys] = useState([]);
  const [error, setError] = useState("");

  function safeKeys(obj) {
    if (obj && typeof obj === "object" && !Array.isArray(obj)) {
      return Object.keys(obj);
    }
    return [];
  }

  function filterValidObjects(arr) {
    if (!Array.isArray(arr)) return [];
    return arr.filter((item) => item && typeof item === "object" && !Array.isArray(item));
  }

  const handleFile = (e) => {
    setError("");
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const data = JSON.parse(event.target.result);
        let dataItems = [];
        if (Array.isArray(data)) {
          dataItems = data;
        } else if (data && Array.isArray(data.items)) {
          dataItems = data.items;
        } else {
          setItems([]);
          setKeys([]);
          setError("O JSON deve ser um array de objetos ou conter um campo 'items' com um array.");
          return;
        }
        dataItems = filterValidObjects(dataItems);
        if (dataItems.length === 0) {
          setItems([]);
          setKeys([]);
          setError("O array de itens está vazio ou não contém objetos válidos.");
          return;
        }
        const allKeys = Array.from(
          dataItems.reduce((set, item) => {
            safeKeys(item).forEach((k) => set.add(k));
            return set;
          }, new Set())
        );
        setItems(dataItems);
        setKeys(allKeys);
      } catch (err) {
        setItems([]);
        setKeys([]);
        setError("Erro ao ler JSON: " + err);
      }
    };
    reader.readAsText(file);
  };

  const hasValidData = items.length > 0 && keys.length > 0;

  return (
    <div style={{ padding: 24, fontFamily: "Arial, sans-serif" }}>
      <h1>Resultados dos Testes (JSON)</h1>
      <input type="file" accept="application/json" onChange={handleFile} />
      {error && <div style={{ color: "red", marginTop: 16 }}>{error}</div>}
      {hasValidData && (
        <div style={{ marginTop: 24 }}>
          <div style={{ display: "flex", fontWeight: "bold", background: "#f0f0f0" }}>
            {keys.map((key) => (
              <div key={key} style={{ flex: 1, padding: "0.5em" }}>
                {key}
              </div>
            ))}
          </div>
          <TableVirtualList items={items} keys={keys} />
        </div>
      )}
    </div>
  );
}

export default App;
