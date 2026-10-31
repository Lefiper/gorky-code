import { STATUS_LABELS } from "../lib/api.js";
import { fmtDay, isOverdue } from "../lib/dates.js";

const PILL = { new: "pn", progress: "pp", done: "pd", blocked: "pb", pending: "pn", cancelled: "pm" };

export function StatusPill({ status }) {
  return <span className={`pill ${PILL[status] || "pn"}`}>{STATUS_LABELS[status] || "Новая"}</span>;
}

export function TaskItem({ item, onToggle, onDelete }) {
  const done = item.status === "done";
  const overdue = isOverdue(item.day, item.status);
  const when = item.type === "meeting" && item.time ? `${fmtDay(item.day)} · ${item.time}` : fmtDay(item.day);
  return (
    <div className="ti">
      <div
        className={`chk${done ? " done" : ""}`}
        role="button"
        tabIndex={0}
        aria-label="Отметить выполненной"
        onClick={() => onToggle(item)}
        onKeyDown={(e) => e.key === "Enter" && onToggle(item)}
      >
        <svg viewBox="0 0 12 12" fill="none" stroke="white" strokeWidth="2"><polyline points="1,6 4.5,9.5 11,2" /></svg>
      </div>
      <div className="tb2">
        <div className={`tn${done ? " done" : ""}`}>{item.title}</div>
        <div className="tm">
          <span className={`td${overdue ? " ov" : ""}`}>{when}</span>
          <StatusPill status={item.status} />
          {onDelete && (
            <button className="link-btn" onClick={() => onDelete(item)} aria-label="Удалить">удалить</button>
          )}
        </div>
      </div>
    </div>
  );
}

const AVATARS = ["av1", "av2", "av3", "av4"];

export function MeetingCard({ item }) {
  const [hour, minute] = (item.time || "--:--").split(":");
  return (
    <div className="mc">
      <div className="mtc">
        <span className="mth">{hour}</span>
        <span className="mtm">:{minute}</span>
        <div className="mtl" />
        <span className="mtd">{item.duration ? `${item.duration}м` : "—"}</span>
      </div>
      <div className="mdv" />
      <div className="mb">
        <div className="mbt">{item.title}</div>
        {item.desc && <div className="mbd">{item.desc}</div>}
        <div className="avs">
          {AVATARS.slice(0, 2).map((cls) => <div key={cls} className={`av ${cls}`} />)}
        </div>
      </div>
    </div>
  );
}

export function Tabs({ tabs, value, onChange }) {
  return (
    <div className="tabs">
      {tabs.map(([key, label]) => (
        <button key={key} className={`tb${value === key ? " on" : ""}`} onClick={() => onChange(key)}>
          {label}
        </button>
      ))}
    </div>
  );
}

export function Empty({ children }) {
  return <div className="empty">{children}</div>;
}
