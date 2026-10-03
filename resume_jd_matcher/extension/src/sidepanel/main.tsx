import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

const container = document.getElementById("root");
// The mount node is declared in panel.html; it must exist or the panel is blank.
if (!container) {
  throw new Error("Root container #root was not found in panel.html");
}

createRoot(container).render(<App />);
