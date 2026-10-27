import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router";
import "./index.css";
import { Layout } from "./components/Layout";
import { MetaProvider } from "./meta";
import { NewJobPage } from "./pages/NewJob";
import { JobsPage } from "./pages/Jobs";
import { JobDetailPage } from "./pages/JobDetail";
import { FilmsPage } from "./pages/Films";
import { FilmDetailPage } from "./pages/FilmDetail";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MetaProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<NewJobPage />} />
            <Route path="jobs" element={<JobsPage />} />
            <Route path="jobs/:id" element={<JobDetailPage />} />
            <Route path="films" element={<FilmsPage />} />
            <Route path="films/:id" element={<FilmDetailPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </MetaProvider>
  </StrictMode>,
);
