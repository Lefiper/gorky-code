import { useState } from "react";
import { EDITABLE_STATUSES, STATUS_LABELS } from "../lib/api.js";
import { localIso, todayKey } from "../lib/dates.js";

const KINDS = [["task", "Задача"], ["reminder", "Напоминание"], ["meeting", "Встреча"], ["project", "Проект"]];

export function Sheet({ open, onClose, title, children }) {
  return (
    <div className={`ov${open ? " open" : ""}`} onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="sh2">
        <div className="handle" />
        <div style={{ textAlign: "center", marginBottom: 16 }}>
          <h3 style={{ fontSize: 15, fontWeight: 600 }}>{title}</h3>
        </div>
        {children}
      </div>
    </div>
  );
}

export function AddSheet({ open, onClose, onCreate }) {
  const [kind, setKind] = useState("task");
  const [title, setTitle] = useState("");
  const [desc, setDesc] = useState("");
  const [day, setDay] = useState(todayKey());
  const [time, setTime] = useState("10:00");
  const [duration, setDuration] = useState("");
  const [status, setStatus] = useState("new");
  const [error, setError] = useState("");

  const submit = async () => {
    if (!title.trim()) return setError("Введите название.");
    setError("");
    try {
      await onCreate({
        type: kind,
        title: title.trim(),
        description: desc.trim(),
        localDate: day,
        localTime: ["meeting", "reminder"].includes(kind) ? time : "09:00",
        duration: kind === "meeting" && duration ? Number(duration) : null,
        status: kind === "reminder" ? "pending" : kind === "meeting" ? "new" : status,
      });
      setTitle("");
      setDesc("");
      onClose();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <Sheet open={open} onClose={onClose} title="Новая запись">
      <div className="tabs" style={{ marginBottom: 16 }}>
        {KINDS.map(([key, label]) => (
          <button key={key} className={`tb${kind === key ? " on" : ""}`} onClick={() => setKind(key)}>{label}</button>
        ))}
      </div>
      <div className="af"><label>Название</label>
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Что нужно сделать?" maxLength={200} />
      </div>
      <div className="af"><label>Описание</label>
        <textarea value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="Детали..." maxLength={10000} />
      </div>
      <div className="row2">
        <div className="af"><label>{kind === "meeting" ? "Дата" : "Срок"}</label>
          <input type="date" value={day} onChange={(e) => setDay(e.target.value)} />
        </div>
        {["meeting", "reminder"].includes(kind) ? (
          <div className="af"><label>Время</label>
            <input type="time" value={time} onChange={(e) => setTime(e.target.value)} />
          </div>
        ) : (
          <div className="af"><label>Статус</label>
            <select value={status} onChange={(e) => setStatus(e.target.value)}>
              {EDITABLE_STATUSES.filter((s) => s !== "done").map((s) => (
                <option key={s} value={s}>{STATUS_LABELS[s]}</option>
              ))}
            </select>
          </div>
        )}
      </div>
      {kind === "meeting" && (
        <div className="af"><label>Длительность, минут</label>
          <input type="number" min="1" value={duration} onChange={(e) => setDuration(e.target.value)} placeholder="необязательно" />
        </div>
      )}
      {error && <p style={{ color: "var(--red)", fontSize: 12, marginBottom: 10 }}>{error}</p>}
      <button className="btn-p" onClick={submit}>Создать</button>
    </Sheet>
  );
}

export function VoiceSheet({ open, onClose, botLink }) {
  return (
    <Sheet open={open} onClose={onClose} title="Голосовой ввод">
      <div className="vs">
        <p>Голосовые сообщения распознаёт и обрабатывает бот MAX. Отправьте запись в чат с ботом.</p>
      </div>
      {botLink ? (
        <a className="btn-p" href={botLink} style={{ display: "block", textAlign: "center", textDecoration: "none" }}>
          Открыть чат с ботом
        </a>
      ) : (
        <p style={{ color: "var(--mut)", fontSize: 12 }}>Ссылка на бота не задана (VITE_BOT_LINK).</p>
      )}
      <button className="btn-s" style={{ marginTop: 12 }} onClick={onClose}>Закрыть</button>
    </Sheet>
  );
}
