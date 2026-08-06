import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "./theme/tokens.css";
import "./styles/app.css";
import "./styles/paper.css";
import {
  applyBackgroundEffect,
  applyTheme,
} from "./theme/theme";

applyTheme("astra-minimal");
applyBackgroundEffect("nebula");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
