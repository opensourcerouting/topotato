import React, { useState } from "react";
import TableVirtualList from "./TableVirtualList";

const templateFiles = [
  { label: "Example 1", value: "test.json" },
];

function App() {
  const [items, setItems] = useState([]);
  const [keys, setKeys] = useState([]);
  const [error, setError] = useState("");
  const [selectedFile, setSelectedFile] = useState("");

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

  // New: Load JSON file from templates folder
  async function handleTemplateSelect(e) {
    setError("");
    const file = e.target.value;
    setSelectedFile(file);
    if (!file) {
      setItems([]);
      setKeys([]);
      return;
    }
    try {
      // Dynamic import of JSON
      const data = await import(`./templates/${file}`);
      let dataItems = [];
      if (Array.isArray(data.default)) {
        dataItems = data.default;
      } else if (data.default && Array.isArray(data.default.items)) {
        dataItems = data.default.items;
      } else {
        setItems([]);
        setKeys([]);
        setError("JSON must be an array of objects or contain an 'items' field with an array.");
        return;
      }
      dataItems = filterValidObjects(dataItems);
      if (dataItems.length === 0) {
        setItems([]);
        setKeys([]);
        setError("The items array is empty or does not contain valid objects.");
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
      setError("Error importing JSON: " + err);
    }
  }

  // Keep manual upload as well
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
          setError("JSON must be an array of objects or contain an 'items' field with an array.");
          return;
        }
        dataItems = filterValidObjects(dataItems);
        if (dataItems.length === 0) {
          setItems([]);
          setKeys([]);
          setError("The items array is empty or does not contain valid objects.");
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
        setError("Error reading JSON: " + err);
      }
    };
    reader.readAsText(file);
  };

  // Debug log
  React.useEffect(() => {
    console.log("[DEBUG] items:", items);
    console.log("[DEBUG] keys:", keys);
  }, [items, keys]);

  const hasValidData = items.length > 0 && keys.length > 0;

  return (
    <div style={{ padding: 24, fontFamily: "Arial, sans-serif" }}>
      <h1>Test Results (JSON)</h1>
      <div style={{ marginBottom: 16 }}>
        <label>Choose a template:&nbsp;</label>
        <select value={selectedFile} onChange={handleTemplateSelect}>
          <option value="">Select...</option>
          {templateFiles.map((f) => (
            <option key={f.value} value={f.value}>{f.label}</option>
          ))}
        </select>
      </div>
      <div style={{ marginBottom: 16 }}>
        <label>Or upload a JSON file:&nbsp;</label>
        <input type="file" accept="application/json" onChange={handleFile} />
      </div>
      {error && <div style={{ color: "red", marginTop: 16 }}>{error}</div>}
      {hasValidData && (
        <div style={{ marginTop: 24 }}>
          <TableVirtualList items={items} keys={keys} />
        </div>
      )}
    </div>
  );
}

export default App;
