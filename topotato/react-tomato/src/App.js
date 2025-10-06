import React, { useState } from "react";
import LogTable from "./component/LogTable";

const templateFiles = [
  { label: "Example 1", value: "test.json" },
];

// Mapeamento dos checkboxes para os valores de type nos logs
const LOG_TYPE_MAP = {
  err: "error",
  warn: "warn",
  notify: "notif",
  info: "info",
  debug: "debug",
};

function App() {
  const [items, setItems] = useState([]);
  const [keys, setKeys] = useState([]);
  const [error, setError] = useState("");
  const [selectedFile, setSelectedFile] = useState("");
  const [logTypeFilter, setLogTypeFilter] = useState({
    showAll: true,
    err: true,
    warn: true,
    notify: true,
    info: true,
    debug: true,
  });

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

  function processDataItems(data, dataItems, setItems, setKeys, setError, safeKeys) {
    const validItems = filterValidObjects(dataItems);
    if (validItems.length === 0) {
      setItems([]);
      setKeys([]);
      setError("The items array is empty or does not contain valid objects.");
      return;
    }

    let timedEntries = Array.isArray(data.timed) ? data.timed : [];
    const logsByItem = Array(validItems.length).fill(null).map(() => []);
    let item_idx = -1;
    let ts_end = -Infinity;
    for (let i = 0; i < timedEntries.length; i++) {
      const entry = timedEntries[i];

      while (item_idx + 1 < validItems.length && entry.ts > validItems[item_idx + 1].ts_end) {
        item_idx++;
        ts_end = validItems[item_idx]?.ts_end ?? -Infinity;
      }

      if (item_idx + 1 < validItems.length) {
        logsByItem[item_idx + 1].push(entry);
      }
    }

    const itemsWithLogs = validItems.map((item, idx) => ({ ...item, logs: logsByItem[idx] }));

    const allKeys = Array.from(
      itemsWithLogs.reduce((set, item) => {
        safeKeys(item).forEach((k) => set.add(k));
        return set;
      }, new Set())
    );

    setItems(itemsWithLogs);
    setKeys(allKeys);
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

      processDataItems(data, dataItems, setItems, setKeys, setError, safeKeys);
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

        processDataItems(dataItems, setItems, setKeys, setError, safeKeys);
      } catch (err) {
        setItems([]);
        setKeys([]);
        setError("Error reading JSON: " + err);
      }
    };
    reader.readAsText(file);
  };

  const hasValidData = items.length > 0 && keys.length > 0;

  // Handler para checkboxes
  function handleLogTypeChange(e) {
    const { name, checked } = e.target;
    if (name === 'showAll') {
      setLogTypeFilter({
        showAll: checked,
        err: checked,
        warn: checked,
        notify: checked,
        info: checked,
        debug: checked,
      });
    } else {
      setLogTypeFilter((prev) => {
        const updated = { ...prev, [name]: checked, showAll: false };
        // Se todos os checkboxes individuais ficarem marcados, ativa showAll automaticamente
        const allChecked = ['err','warn','notify','info','debug'].every(k => updated[k]);
        if (allChecked) updated.showAll = true;
        return updated;
      });
    }
  }

  // Função para filtrar logs de acordo com os checkboxes
  function filterLogs(logs) {
    if (logTypeFilter.showAll) return logs || [];
    const allowedTypes = Object.entries(logTypeFilter)
      .filter(([k, v]) => v && k !== 'showAll')
      .map(([k]) => LOG_TYPE_MAP[k]);
    return Array.isArray(logs)
      ? logs.filter((log) => allowedTypes.includes(log.data?.type))
      : [];
  }

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
      {/* Checkboxes para filtrar tipos de log */}
      <div style={{ marginBottom: 16 }}>
        <span style={{ fontWeight: 'bold', marginRight: 8 }}>Filtrar tipos:</span>
        <label style={{ marginRight: 16 }}>
          <input
            type="checkbox"
            name="showAll"
            checked={logTypeFilter.showAll}
            onChange={handleLogTypeChange}
          />
          &nbsp;Show all
        </label>
        {Object.keys(LOG_TYPE_MAP).map((key) => (
          <label key={key} style={{ marginRight: 12 }}>
            <input
              type="checkbox"
              name={key}
              checked={logTypeFilter[key]}
              onChange={handleLogTypeChange}
              disabled={logTypeFilter.showAll}
            />
            &nbsp;{key}
          </label>
        ))}
      </div>
      {error && <div style={{ color: "red", marginTop: 16 }}>{error}</div>}
      {hasValidData && (
        <div style={{ marginTop: 24 }}>
          {items.map((item, idx) => (
            <div key={idx} style={{ border: '1px solid #bdbdbd', borderRadius: 6, marginBottom: 24, background: '#f8f9fa' }}>
              <div style={{ background: '#e3e3e3', padding: '6px 12px', fontWeight: 'bold', fontSize: 18, borderTopLeftRadius: 6, borderTopRightRadius: 6 }}>
                {item.nodeid}
              </div>
              <LogTable
                  logs={filterLogs(item.logs)}
                  timed={item.logs && item.logs.length > 0 ? Math.abs(item.logs[0].ts ?? 0).toFixed(2) : '0.00'} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default App;
