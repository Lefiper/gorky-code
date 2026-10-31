import { useCallback, useEffect, useMemo, useState } from "react";
import { createEvent, listEvents, removeEvent, setStatus, getTimezone, saveTimezone } from "./lib/api.js";
import { addDays, dayBounds, todayKey, setProfileZone } from "./lib/dates.js";
import { signalReady } from "./lib/auth.js";
import { AddSheet, VoiceSheet } from "./components/sheets.jsx";
import { CalendarPage, HomePage, NotifsPage, TasksPage } from "./components/pages.jsx";

const WINDOW_DAYS = 60;
const BOT_LINK = import.meta.env.VITE_BOT_LINK || "";

const TABS = [
  ["home", "Главная", "M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"],
  ["tasks", "Задачи", "M9 11l3 3 10-10M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"],
  ["notifs", "Уведомления", "M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9M13.73 21a2 2 0 0 1-3.46 0"],
  ["calendar", "Календарь", "M3 4h18v18H3zM16 2v4M8 2v4M3 10h18"],
];

function countStatuses(items) {
  const counts = { new: 0, progress: 0, done: 0, blocked: 0 };
  items.forEach((item) => {
    if (item.status === "pending") counts.new += 1;
    else if (counts[item.status] !== undefined) counts[item.status] += 1;
  });
  return { ...counts, active: counts.new + counts.progress + counts.blocked };
}

export default function App() {
  const [zone, setZone] = useState("Europe/Moscow");
  const [zoneDraft, setZoneDraft] = useState("Europe/Moscow");
  const [items, setItems] = useState([]);
  const [loadError, setLoadError] = useState("");
  const [page, setPage] = useState("home");
  const [homeTab, setHomeTab] = useState("tasks");
  const [allTab, setAllTab] = useState("tasks");
  const [selDay, setSelDay] = useState(todayKey());
  const [calMonth, setCalMonth] = useState(() => new Date(new Date().getFullYear(), new Date().getMonth(), 1));
  const [addOpen, setAddOpen] = useState(false);
  const [voiceOpen, setVoiceOpen] = useState(false);
  const [notice, setNotice] = useState("Нажмите «+», чтобы создать запись, или отправьте голосовое боту.");

  const reload = useCallback(async () => {
    const today = todayKey();
    const from = dayBounds(addDays(today, -WINDOW_DAYS)).from;
    const to = dayBounds(addDays(today, WINDOW_DAYS)).to;
    try {
      const profile = await getTimezone();
      setProfileZone(profile.timezone);
      setZone(profile.timezone || "Europe/Moscow");
      setZoneDraft(profile.timezone || "Europe/Moscow");
      setItems(await listEvents(from, to));
      setLoadError("");
    } catch (err) {
      setLoadError(err.message || "Не удалось загрузить события.");
    }
  }, []);

  useEffect(() => {
    signalReady();
    reload();
  }, [reload]);

  const counts = useMemo(() => countStatuses(items), [items]);

  const create = async (payload) => {
    const item = await createEvent(payload);
    setNotice(`Создано: «${item.title}».`);
    await reload();
  };

  const toggle = async (item) => {
    const next = item.status === "done" ? (item.type === "reminder" ? "pending" : "new") : "done";
    try {
      await setStatus(item.id, next);
      setNotice(next === "done" ? `«${item.title}» выполнено.` : `«${item.title}» снова открыто.`);
      await reload();
    } catch (err) {
      setNotice(`Не удалось изменить статус: ${err.message}`);
    }
  };

  const remove = async (item) => {
    if (!window.confirm(`Удалить «${item.title}»?`)) return;
    try {
      await removeEvent(item.id);
      setNotice(`«${item.title}» удалено.`);
      await reload();
    } catch (err) {
      setNotice(`Не удалось удалить: ${err.message}`);
    }
  };

  const shift = (step) => setCalMonth((m) => new Date(m.getFullYear(), m.getMonth() + step, 1));

  return (
    <>
      <header className="topbar">
        <div className="logo">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="white"><path d="M12 2a10 10 0 1 0 0 20A10 10 0 0 0 12 2zm-1 14H9V8h2v8zm4 0h-2V8h2v8z" /></svg>
        </div>
        <span className="ttl">MAX <span>Ассистент</span></span>
        <button className="ibtn ibtn-add" onClick={() => setAddOpen(true)} aria-label="Добавить">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--txt)" strokeWidth="2.5" strokeLinecap="round"><path d="M12 5v14M5 12h14" /></svg>
        </button>
        <button className="ibtn ibtn-mic" onClick={() => setVoiceOpen(true)} aria-label="Голосовой ввод">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3zM19 10v2a7 7 0 0 1-14 0v-2M12 19v4" /></svg>
        </button>
      </header>

      <main className="scroll">
        <form className="card timezone-form" onSubmit={async (e) => { e.preventDefault(); try { await saveTimezone(zoneDraft); await reload(); setSelDay(todayKey()); } catch (err) { setLoadError(err.message); } }}>
          <label>Часовой пояс <input aria-label="Часовой пояс" value={zoneDraft} onChange={e => setZoneDraft(e.target.value)} placeholder="Europe/Moscow" /></label>
          <button type="submit">Сохранить пояс</button><small> Текущий: {zone}</small>
        </form>
        {loadError && <div className="card"><p style={{ color: "var(--red)" }}>Нет связи с сервером: {loadError}</p></div>}
        {page === "home" && (
          <HomePage items={items} counts={counts} homeTab={homeTab} onHomeTab={setHomeTab}
            onSeeAll={() => setPage("tasks")} onToggle={toggle} aiText={notice} />
        )}
        {page === "tasks" && (
          <TasksPage items={items} selDay={selDay} onSelDay={setSelDay} allTab={allTab}
            onAllTab={setAllTab} onToggle={toggle} onDelete={remove} />
        )}
        {page === "notifs" && <NotifsPage />}
        {page === "calendar" && (
          <CalendarPage items={items} month={calMonth} onMonth={shift} selDay={selDay} onSelDay={setSelDay} />
        )}
      </main>

      <nav className="tbar">
        {TABS.map(([key, label, path]) => (
          <button key={key} className={`tbb${page === key ? " on" : ""}`} onClick={() => setPage(key)}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d={path} /></svg>
            {label}
          </button>
        ))}
      </nav>

      <AddSheet open={addOpen} onClose={() => setAddOpen(false)} onCreate={create} />
      <VoiceSheet open={voiceOpen} onClose={() => setVoiceOpen(false)} botLink={BOT_LINK} />
    </>
  );
}
