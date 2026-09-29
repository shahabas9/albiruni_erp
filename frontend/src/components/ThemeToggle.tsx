import { useTheme } from "../theme/ThemeProvider";
import "./ThemeToggle.css";

/** Day/night switch. Click the track to toggle; the small label resets to the OS preference. */
export function ThemeToggle() {
  const { resolved, choice, toggle, setChoice } = useTheme();
  const isDark = resolved === "dark";

  return (
    <div className="theme-toggle-group">
      <button
        type="button"
        role="switch"
        aria-checked={isDark}
        aria-label={isDark ? "Switch to day mode" : "Switch to night mode"}
        className="theme-toggle"
        onClick={toggle}
      >
        <span className="tt-icon tt-sun" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
            <circle cx="12" cy="12" r="4.2" />
            <path d="M12 2.5v2.2M12 19.3v2.2M4.2 4.2l1.6 1.6M18.2 18.2l1.6 1.6M2.5 12h2.2M19.3 12h2.2M4.2 19.8l1.6-1.6M18.2 5.8l1.6-1.6" />
          </svg>
        </span>
        <span className="tt-icon tt-moon" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="11" height="11" fill="currentColor">
            <path d="M20.5 14.6A8.5 8.5 0 1 1 9.4 3.5a7 7 0 0 0 11.1 11.1Z" />
          </svg>
        </span>
        <span className="tt-knob" />
      </button>
      {choice !== "system" && (
        <button type="button" className="theme-system-reset" onClick={() => setChoice("system")}>
          match system
        </button>
      )}
    </div>
  );
}
