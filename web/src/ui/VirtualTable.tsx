import { useState, type ReactNode } from "react";

/** One column of a table. */
export interface Col<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  num?: boolean;
}

interface Props<T> {
  rows: T[];
  cols: Col<T>[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  rowClass?: (row: T) => string;
  maxHeight?: number;
  empty?: string;
}

const ROW_H = 22;
const WINDOW_AT = 500;

/** A plain table. It draws only the visible rows when the table has more than 500 rows. */
export function VirtualTable<T>({ rows, cols, rowKey, onRowClick, rowClass, maxHeight = 260, empty }: Props<T>) {
  const [scroll, setScroll] = useState(0);
  const windowed = rows.length > WINDOW_AT;
  let start = 0;
  let end = rows.length;
  if (windowed) {
    start = Math.max(0, Math.floor(scroll / ROW_H) - 10);
    end = Math.min(rows.length, start + Math.ceil(maxHeight / ROW_H) + 20);
  }
  const slice = rows.slice(start, end);
  return (
    <div className="vt" style={{ maxHeight }} onScroll={(e) => windowed && setScroll(e.currentTarget.scrollTop)}>
      <table className="grid">
        <thead>
          <tr>
            {cols.map((c) => (
              <th key={c.key} className={c.num ? "num" : undefined}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {windowed && start > 0 && (
            <tr style={{ height: start * ROW_H }}>
              <td colSpan={cols.length} />
            </tr>
          )}
          {slice.map((r) => (
            <tr
              key={rowKey(r)}
              style={windowed ? { height: ROW_H } : undefined}
              className={`${onRowClick ? "click" : ""} ${rowClass ? rowClass(r) : ""}`}
              onClick={onRowClick ? () => onRowClick(r) : undefined}
            >
              {cols.map((c) => (
                <td key={c.key} className={c.num ? "num" : undefined}>
                  {c.render(r)}
                </td>
              ))}
            </tr>
          ))}
          {windowed && end < rows.length && (
            <tr style={{ height: (rows.length - end) * ROW_H }}>
              <td colSpan={cols.length} />
            </tr>
          )}
          {rows.length === 0 && (
            <tr>
              <td colSpan={cols.length} className="muted">
                {empty ?? "—"}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
