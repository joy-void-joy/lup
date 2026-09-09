// Every view is a URL. Hash history rather than the browser's path history,
// because the same bundle serves from a loopback origin and opens from a file
// on disk, and only the fragment survives both without a server to route it.
import {
  createHashHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  type SearchSchemaInput,
} from "@tanstack/react-router";
import { Browse } from "./Browse";
import { Layout } from "./Layout";
import { NodePage } from "./NodePage";

export type View = "list" | "graph";

export type BrowseSearch = {
  kind: string;
  standing: string;
  since: string;
  q: string;
  view: View;
};

function word(value: unknown): string {
  return typeof value === "string" ? value : "";
}

const rootRoute = createRootRoute({
  component: () => (
    <Layout>
      <Outlet />
    </Layout>
  ),
});

export const browseRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  validateSearch: (search: Record<string, unknown> & SearchSchemaInput): BrowseSearch => ({
    kind: word(search["kind"]),
    standing: word(search["standing"]),
    since: word(search["since"]),
    q: word(search["q"]),
    view: search["view"] === "graph" ? "graph" : "list",
  }),
  component: Browse,
});

export const nodeRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/node/$id",
  component: NodePage,
});

const routeTree = rootRoute.addChildren([browseRoute, nodeRoute]);

export const router = createRouter({ routeTree, history: createHashHistory() });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
