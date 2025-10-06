import React from 'react';
import './LogTable.css';

function getRowClass(level) {
  switch (level) {
    case 'error':
      return 'log-row log-error';
    case 'warn':
      return 'log-row log-warn';
    case 'info':
      return 'log-row log-info';
    case 'notif':
      return 'log-row log-notif';
    default:
      return 'log-row';
  }
}

function formatMessage(message) {
  if (!message) return null;

  let formatted = message.replace(/(https?:\/\/\S+)/g, '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>');

  formatted = formatted.replace(/\*\*(.*?)\*\*/g, '<b>$1</b>');

  formatted = formatted.replace(/_(.*?)_/g, '<i>$1</i>');

  formatted = formatted.replace(/\[(.*?)\]/g, '<span class="log-file">[$1]</span>');
  return <span dangerouslySetInnerHTML={{ __html: formatted }} />;
}

const LogTable = ({ logs, timed }) => (
  <div className="log-table-container">
    <div className="log-status-row log-status-success">
      <span>&#9654; passed after {timed || '0.00s'}</span>
    </div>
    <table className="log-table">
      <tbody>
        {logs.map((log, idx) => (
          <tr key={idx} className={getRowClass(log.data.type)}>
            <td className="log-time">{log.ts}</td>
            <td className="log-router">{log.data.router}</td>
            <td className="log-daemon">{log.data.daemon}</td>
            <td className="log-text">{log.data.text}</td>
            <td className="log-level">{log.data.type}</td>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

export default LogTable;

