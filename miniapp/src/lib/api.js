import { getInitData } from "./auth.js";
import { dayBounds, toLocal } from "./dates.js";

const BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/$/, "");
const DEV_USER = import.meta.env.VITE_DEV_USER_ID || "";

export const STATUS_LABELS = {
  new: "Новая",
  progress: "В работе",
  done: "Готово",
  blocked: "Блокировка",
  pending: "Новая",
  cancelled: "Отменена",
};
export const EDITABLE_STATUSES = ["new", "progress", "done", "blocked"];

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function authHeaders() {
  const initData = getInitData();
  if (initData) return { "X-Max-InitData": initData };
  // Только для локальной разработки вне MAX: API принимает этот заголовок лишь при AUTH_DEV_MODE=true.
  if (DEV_USER) return { "X-Debug-User-Id": DEV_USER };
  return {};
}

async function request(path, { method = "GET", body, idempotencyKey } = {}) {
  const headers = { ...authHeaders() };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;
  const response = await fetch(BASE + path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 204) return null;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new ApiError(response.status, typeof data.detail === "string" ? data.detail : "Ошибка запроса к серверу.");
  }
  return data;
}

export function toItem(event) {
  const local = toLocal(event.event_at);
  return {
    id: event.id,
    type: event.event_type,
    title: event.name,
    desc: event.description || "",
    day: local.day,
    time: local.time,
    duration: event.duration_minutes,
    status: event.status,
  };
}

// Загружает все страницы периода (API отдаёт до 100 событий за запрос).
export async function listEvents(fromIso, toIso) {
  const items = [];
  for (let offset = 0; offset < 1000; offset += 100) {
    const query = new URLSearchParams({ from: fromIso, to: toIso, limit: "100", offset: String(offset) });
    const page = await request(`/api/tasks?${query}`);
    if (!page || !Array.isArray(page.items)) {
      throw new ApiError(502, "Сервер вернул неожиданный ответ. Проверьте VITE_API_BASE.");
    }
    items.push(...page.items.map(toItem));
    if (!page.has_more) break;
  }
  return items;
}

export async function listDay(day) {
  const { from, to } = dayBounds(day);
  return listEvents(from, to);
}

export async function createEvent({ type, title, description, localDate, localTime, duration, status }) {
  const { event_at: eventAt } = await request("/api/timezone/resolve", { method: "POST", body: { date: localDate, time: localTime } });
  return request("/api/tasks", {
    method: "POST",
    idempotencyKey: crypto.randomUUID(),
    body: {
      event_type: type,
      name: title,
      description: description || "",
      event_at: eventAt,
      duration_minutes: duration || null,
      status,
    },
  }).then((data) => toItem(data.event));
}

export function setStatus(id, status) {
  return request(`/api/tasks/${id}`, { method: "PATCH", body: { status } });
}

export function removeEvent(id) {
  return request(`/api/tasks/${id}`, { method: "DELETE" });
}

export const getTimezone = () => request("/api/timezone");
export const saveTimezone = (timezone) => request("/api/timezone", { method: "PUT", body: { timezone } });
