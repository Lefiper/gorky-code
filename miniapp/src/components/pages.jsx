import { addDays, MONTHS, todayKey, WEEKDAYS_SHORT } from "../lib/dates.js";
import { Empty, MeetingCard, Tabs, TaskItem } from "./ui.jsx";

const TYPE_OF_TAB = { tasks: ["task", "reminder"], meetings: ["meeting"], projects: ["project"] };
const TAB_LABELS = [["tasks", "Задачи"], ["meetings", "Встречи"], ["projects", "Проекты"]];

export function Donut({ counts }) {
  const colors = ["#5B8AF0", "#FBBF24", "#34D399", "#F87171"];
  const values = [counts.new, counts.progress, counts.done, counts.blocked];
  const total = values.reduce((a, b) => a + b, 0);
  const shown = total === 0 ? [1, 1, 1, 1] : values;
  const sum = shown.reduce((a, b) => a + b, 0);
  const cx = 45, cy = 45, r = 38, inner = 26;
  const point = (angle, radius) => [cx + radius * Math.cos(angle), cy + radius * Math.sin(angle)];
  let start = -Math.PI / 2;
  const slices = shown.map((value, i) => {
    const angle = (value / sum) * Math.PI * 2;
    const [x1, y1] = point(start, r);
    const [x2, y2] = point(start + angle, r);
    const large = angle > Math.PI ? 1 : 0;
    start += angle;
    return <path key={i} d={`M${cx},${cy} L${x1},${y1} A${r},${r} 0 ${large} 1 ${x2},${y2} Z`} fill={colors[i]} />;
  });
  return (
    <svg width="90" height="90" viewBox="0 0 90 90" aria-hidden="true">
      {slices}
      <circle cx={cx} cy={cy} r={inner} fill="#151829" />
    </svg>
  );
}

export function HomePage({ items, counts, homeTab, onHomeTab, onSeeAll, onToggle, aiText }) {
  const today = todayKey();
  const list = items.filter((item) => TYPE_OF_TAB[homeTab].includes(item.type));
  const meetingsToday = items.filter((item) => item.type === "meeting" && item.day === today);
  return (
    <>
      <div className="ai">
        <div className="aih"><span className="aib">Ассистент · последнее действие</span></div>
        <p className="ait">{aiText}</p>
      </div>
      <div className="stats">
        <div className="sc"><div className="sv bl">{counts.active}</div><div className="sl">Активных</div></div>
        <div className="sc"><div className="sv yl">{meetingsToday.length}</div><div className="sl">Встреч сегодня</div></div>
        <div className="sc"><div className="sv gr">{counts.done}</div><div className="sl">Выполнено</div></div>
      </div>
      <div className="cc">
        <div className="cw"><Donut counts={counts} /></div>
        <div className="cl">
          <Legend counts={counts} />
        </div>
      </div>
      <div>
        <div className="sh">
          <h2>Задачи</h2>
          <span className="badge">{list.length}</span>
          <button className="see-all" onClick={onSeeAll}>Все →</button>
        </div>
        <div className="card">
          <Tabs tabs={TAB_LABELS} value={homeTab} onChange={onHomeTab} />
          {list.length ? list.slice(0, 5).map((item) => (
            <TaskItem key={item.id} item={item} onToggle={onToggle} />
          )) : <Empty>Нет записей</Empty>}
        </div>
      </div>
      {homeTab !== "meetings" && (
        <div>
          <div className="sh">
            <h2>Встречи сегодня</h2>
            <span className="badge">{meetingsToday.length}</span>
          </div>
          {meetingsToday.length ? meetingsToday.map((item) => (
            <MeetingCard key={item.id} item={item} />
          )) : <Empty>Встреч на сегодня нет</Empty>}
        </div>
      )}
    </>
  );
}

function Legend({ counts }) {
  const rows = [["Новые", counts.new, "#5B8AF0"], ["В работе", counts.progress, "#FBBF24"],
    ["Готово", counts.done, "#34D399"], ["Блокировка", counts.blocked, "#F87171"]];
  return rows.map(([label, value, color]) => (
    <div key={label} className="lr">
      <div className="ld" style={{ background: color }} />
      <span className="ll">{label}</span>
      <span className="lv">{value}</span>
    </div>
  ));
}

export function TasksPage({ items, selDay, onSelDay, allTab, onAllTab, onToggle, onDelete }) {
  const today = todayKey();
  const days = Array.from({ length: 7 }, (_, i) => addDays(today, i - 6));
  const dayItems = items.filter((item) => item.day === selDay);
  const allList = items.filter((item) => TYPE_OF_TAB[allTab].includes(item.type));
  return (
    <>
      <div>
        <div className="sh"><h2>Последние 7 дней</h2></div>
        <div className="ws">
          {days.map((day) => {
            const [, , d] = day.split("-").map(Number);
            const weekday = WEEKDAYS_SHORT[(new Date(`${day}T00:00:00`).getDay() + 6) % 7];
            const hasItems = items.some((item) => item.day === day);
            return (
              <div key={day} className={`wc${day === selDay ? " sel" : ""}`} onClick={() => onSelDay(day)}>
                <span className="wd">{weekday}</span>
                <span className="wn">{d}</span>
                {hasItems ? <span className="wdot" /> : <span style={{ height: 5 }} />}
              </div>
            );
          })}
        </div>
        <div className="card" style={{ marginTop: 10 }}>
          {dayItems.length ? dayItems.map((item) => (
            <TaskItem key={item.id} item={item} onToggle={onToggle} onDelete={onDelete} />
          )) : <Empty>Нет задач в этот день</Empty>}
        </div>
      </div>
      <div>
        <div className="sh" style={{ marginTop: 4 }}>
          <h2>Все задачи</h2>
          <span className="badge">{items.length}</span>
        </div>
        <div className="card">
          <Tabs tabs={TAB_LABELS} value={allTab} onChange={onAllTab} />
          {allList.length ? allList.map((item) => (
            <TaskItem key={item.id} item={item} onToggle={onToggle} onDelete={onDelete} />
          )) : <Empty>Нет записей</Empty>}
        </div>
      </div>
    </>
  );
}

export function NotifsPage() {
  return (
    <div className="card">
      <Empty>
        Уведомления и напоминания приходят в чат с ботом MAX. Мини-приложение пока не получает их из API.
      </Empty>
    </div>
  );
}

export function CalendarPage({ items, month, onMonth, selDay, onSelDay }) {
  const [year, monthIndex] = [month.getFullYear(), month.getMonth()];
  const first = new Date(year, monthIndex, 1);
  const offset = (first.getDay() + 6) % 7;
  const daysInMonth = new Date(year, monthIndex + 1, 0).getDate();
  const cells = [];
  for (let i = offset; i > 0; i--) cells.push({ day: new Date(year, monthIndex, 1 - i) });
  for (let d = 1; d <= daysInMonth; d++) cells.push({ day: new Date(year, monthIndex, d), current: true });
  while (cells.length % 7 !== 0) cells.push({ day: new Date(year, monthIndex + 1, cells.length - offset - daysInMonth + 1) });
  const keyOf = (date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  const today = todayKey();
  const withItems = new Set(items.map((item) => item.day));
  const dayItems = items.filter((item) => item.day === selDay).sort((a, b) => a.time.localeCompare(b.time));
  return (
    <div className="card">
      <div className="calh">
        <span className="calm">{MONTHS[monthIndex]} {year}</span>
        <button className="caln" onClick={() => onMonth(-1)} aria-label="Предыдущий месяц">‹</button>
        <button className="caln" onClick={() => onMonth(1)} aria-label="Следующий месяц">›</button>
      </div>
      <div className="calg">
        {WEEKDAYS_SHORT.map((w) => <div key={w} className="calw">{w}</div>)}
        {cells.map(({ day, current }, index) => {
          const key = keyOf(day);
          const cls = ["cald", !current && "om", key === today && "tod", key === selDay && current && "sel",
            withItems.has(key) && "hev"].filter(Boolean).join(" ");
          return (
            <div key={index} className={cls} onClick={() => current && onSelDay(key)}>{day.getDate()}</div>
          );
        })}
      </div>
      <div className="cale">
        {dayItems.length ? dayItems.map((item) => (
          <div key={item.id} className="cer">
            <span className="cet">{item.time}</span>
            <span className="cen">{item.title}</span>
          </div>
        )) : <Empty>Нет событий в этот день</Empty>}
      </div>
    </div>
  );
}
