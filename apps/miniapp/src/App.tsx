import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueueScreen } from "./screens/QueueScreen";
import { ReviewScreen } from "./screens/ReviewScreen";
import { SettingsScreen } from "./screens/SettingsScreen";
import { ProjectsScreen } from "./screens/ProjectsScreen";

export function App() {
  return (
    <BrowserRouter basename="/app">
      <Routes>
        <Route path="/" element={<QueueScreen />} />
        <Route path="/review/:stableId" element={<ReviewScreen />} />
        <Route path="/settings" element={<SettingsScreen />} />
        <Route path="/projects" element={<ProjectsScreen />} />
      </Routes>
    </BrowserRouter>
  );
}
