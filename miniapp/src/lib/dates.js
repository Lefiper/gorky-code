let profileZone = "Europe/Moscow";
export function setProfileZone(value) { profileZone = value || "Europe/Moscow"; }
function zonedParts(date) { return Object.fromEntries(new Intl.DateTimeFormat("en-CA", { timeZone: profileZone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(date).map(p => [p.type,p.value])); }
// Календарные даты в локальном часовом поясе устройства; API получает ISO 8601 с offset.
const MONTHS_SHORT = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
export const MONTHS = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"];
export const WEEKDAYS_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

const pad = (n) => String(n).padStart(2, "0");

export function dayKey(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function todayKey() {
  const p = zonedParts(new Date());
  return `${p.year}-${p.month}-${p.day}`;
}

export function addDays(day, count) {
  const [y, m, d] = day.split("-").map(Number);
  return dayKey(new Date(y, m - 1, d + count));
}

export function offsetOf(date) {
  const minutes = -date.getTimezoneOffset();
  const sign = minutes >= 0 ? "+" : "-";
  const abs = Math.abs(minutes);
  return `${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
}

// day: YYYY-MM-DD, time: HH:MM → ISO 8601 с локальным смещением.
export function localIso(day, time) {
  const date = new Date(`${day}T${time}:00`);
  return `${day}T${time}:00${offsetOf(date)}`;
}

export function dayBounds(day) {
  return { from: localIso(day, "00:00"), to: localIso(addDays(day, 1), "00:00") };
}

export function toLocal(isoUtc) {
  const date = new Date(isoUtc);
  const p = zonedParts(date);
  return { day: `${p.year}-${p.month}-${p.day}`, time: `${p.hour}:${p.minute}` };
}

export function fmtDay(day) {
  const today = todayKey();
  if (day === today) return "сегодня";
  if (day === addDays(today, 1)) return "завтра";
  if (day === addDays(today, -1)) return "вчера";
  const [, m, d] = day.split("-").map(Number);
  return `${d} ${MONTHS_SHORT[m - 1]}`;
}

export function isOverdue(day, status) {
  return status !== "done" && day < todayKey();
}
