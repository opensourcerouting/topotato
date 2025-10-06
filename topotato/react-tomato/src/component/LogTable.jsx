import React from 'react';
import { Virtuoso } from 'react-virtuoso';
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

const LogTable = ({ logs, timed }) => (
  <div className="log-table-container">
    <div className="log-status-row log-status-success">
      <span>&#9654; passed after {timed || '0.00s'}</span>
    </div>
    <div style={{ height: 400, width: '100%' }}>
      <Virtuoso
        data={logs}
        style={{ height: 360, width: '100%' }}
        components={{
          List: React.forwardRef((props, ref) => (
            <table className="log-table"><tbody ref={ref} {...props} /></table>
          )),
        }}
        itemContent={(idx, log) => (
          <tr className={getRowClass(log.data.type)}>
            <td className="log-time">{log.ts}</td>
            <td className="log-router">{log.data.router}</td>
            <td className="log-daemon">{log.data.daemon}</td>
            <td className="log-text">{log.data.text}</td>
            <td className="log-level">{log.data.type}</td>
          </tr>
        )}
      />
    </div>
  </div>
);

export default LogTable;
