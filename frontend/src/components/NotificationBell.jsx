import { useEffect, useRef, useState } from "react";
import {
  getNotifications,
  getUnreadCount,
  markAllNotificationsRead,
  markNotificationRead,
} from "../api.js";

const POLL_MS = 60_000;

// Header bell: unread badge (polled), dropdown with recent notifications.
export default function NotificationBell() {
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState(null);
  const wrapRef = useRef(null);

  async function refreshCount() {
    try {
      const { unread: n } = await getUnreadCount();
      setUnread(n);
    } catch {
      /* signed out or transient error — badge just stays put */
    }
  }

  useEffect(() => {
    refreshCount();
    const id = setInterval(refreshCount, POLL_MS);
    return () => clearInterval(id);
  }, []);

  // Close on outside click.
  useEffect(() => {
    if (!open) return;
    function onClick(e) {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next) {
      try {
        setItems(await getNotifications());
      } catch (err) {
        setItems([]);
      }
    }
  }

  async function onRead(note) {
    if (note.read) return;
    try {
      await markNotificationRead(note.id);
      setItems((xs) =>
        xs.map((x) => (x.id === note.id ? { ...x, read: true } : x)),
      );
      setUnread((n) => Math.max(0, n - 1));
    } catch {
      /* best-effort */
    }
  }

  async function onReadAll() {
    try {
      await markAllNotificationsRead();
      setItems((xs) => (xs || []).map((x) => ({ ...x, read: true })));
      setUnread(0);
    } catch {
      /* best-effort */
    }
  }

  return (
    <div className="bell-wrap" ref={wrapRef}>
      <button
        type="button"
        className="bell"
        onClick={toggle}
        aria-label={`Notifications${unread ? ` (${unread} unread)` : ""}`}
        aria-expanded={open}
      >
        🔔
        {unread > 0 && <span className="bell-badge">{unread}</span>}
      </button>
      {open && (
        <div className="bell-dropdown" role="menu">
          <div className="bell-dropdown-head">
            <strong>Notifications</strong>
            {unread > 0 && (
              <button type="button" className="linklike" onClick={onReadAll}>
                Mark all read
              </button>
            )}
          </div>
          {items === null ? (
            <p className="empty">Loading…</p>
          ) : items.length === 0 ? (
            <p className="empty">Nothing yet — alerts you configure will show
              up here when they fire.</p>
          ) : (
            <ul className="bell-list">
              {items.map((n) => (
                <li
                  key={n.id}
                  className={`bell-item ${n.read ? "read" : "unread"}`}
                  onClick={() => onRead(n)}
                >
                  <span className="bell-item-title">{n.title}</span>
                  {n.body && <span className="bell-item-body">{n.body}</span>}
                  <span className="bell-item-meta">
                    {n.ticker} ·{" "}
                    {n.created_at
                      ? new Date(n.created_at).toLocaleString()
                      : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
