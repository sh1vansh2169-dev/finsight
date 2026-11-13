import { useEffect, useState } from "react";

export type ThemeChoice = "system" | "light" | "dark";
const KEY = "moneyos-theme";

function stored(): ThemeChoice {
  try {
    const value = localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system"; // storage can be unavailable (private windows); the app still works
  }
}

function apply(choice: ThemeChoice) {
  const dark = choice === "dark" || (choice === "system" && window.matchMedia?.("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}

/** The theme follows the system unless the user picks one; the choice is remembered on this device. */
export function useTheme(): [ThemeChoice, (choice: ThemeChoice) => void] {
  const [choice, setChoice] = useState<ThemeChoice>(stored);
  useEffect(() => {
    apply(choice);
    if (choice !== "system") return;
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    const listener = () => apply("system");
    media?.addEventListener("change", listener);
    return () => media?.removeEventListener("change", listener);
  }, [choice]);
  const update = (next: ThemeChoice) => {
    try {
      if (next === "system") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, next);
    } catch {
      /* not remembered, but still applied */
    }
    setChoice(next);
  };
  return [choice, update];
}
