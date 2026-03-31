import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { init, backButton, mainButton } from "@telegram-apps/sdk-react";
import { App } from "./App";
import "./styles/globals.css";

try {
  init();
  backButton.mount();
  mainButton.mount();
} catch (e) {
  console.error("Failed to initialize Telegram SDK", e);
}

const webapp = window.Telegram?.WebApp;
if (webapp) {
  webapp.ready();
  webapp.expand();
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
