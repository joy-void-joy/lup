import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { router } from "./router";
import "./styles.css";

const root = document.getElementById("root");
if (root === null) {
  throw new Error("the explorer's page carries no #root to mount into");
}

// A reading stays fresh for a while rather than being refetched on every
// focus: the log grows as sessions record, and a page that redrew itself
// under a reader on each glance back would move what they were pointing at.
const client = new QueryClient({ defaultOptions: { queries: { staleTime: 30_000 } } });

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
