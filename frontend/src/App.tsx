import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Link, createBrowserRouter } from "react-router";
import { RouterProvider } from "react-router/dom";

import { ApiError } from "./api/client";
import { AppShell } from "./components/AppShell";
import { useTheme } from "./lib/theme";
import { SignIn } from "./pages/SignIn";

// Each screen is loaded the first time it is opened, so the first visit downloads
// only what it shows (the chart library, for example, comes with Home only).
const page = (load: () => Promise<{ Component: React.ComponentType }>) => ({ lazy: load });

export const routes = [
  { path: "/sign-in", element: <SignIn /> },
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, ...page(async () => ({ Component: (await import("./pages/Home")).Home })) },
      { path: "transactions", ...page(async () => ({ Component: (await import("./pages/Transactions")).Transactions })) },
      { path: "transactions/review", ...page(async () => ({ Component: (await import("./pages/Review")).Review })) },
      { path: "transactions/suggestions", ...page(async () => ({ Component: (await import("./pages/Suggestions")).Suggestions })) },
      { path: "money-majra", ...page(async () => ({ Component: (await import("./pages/MoneyMajra")).MoneyMajra })) },
      {
        path: "insights",
        ...page(async () => ({ Component: (await import("./pages/Insights")).Insights })),
        children: [
          { index: true, ...page(async () => ({ Component: (await import("./pages/Insights")).InsightsOverview })) },
          { path: "budgets", ...page(async () => ({ Component: (await import("./pages/Budgets")).Budgets })) },
          { path: "bills", ...page(async () => ({ Component: (await import("./pages/Bills")).Bills })) },
          { path: "what-if", ...page(async () => ({ Component: (await import("./pages/WhatIf")).WhatIf })) },
          { path: "ask", ...page(async () => ({ Component: (await import("./pages/Ask")).Ask })) },
        ],
      },
      { path: "profile", ...page(async () => ({ Component: (await import("./pages/Profile")).Profile })) },
    ],
  },
  {
    path: "*",
    element: (
      <main className="p-8">
        <h1 className="text-xl font-semibold">Page not found</h1>
        <Link className="mt-2 inline-block text-primary-ink underline" to="/">Go to Home</Link>
      </main>
    ),
  },
];

/** A sign-in that expires mid-session sends the user back to the sign-in page. */
export function makeQueryClient() {
  const client: QueryClient = new QueryClient({
    queryCache: new QueryCache({ onError: (e) => signedOutOn401(e) }),
    mutationCache: new MutationCache({ onError: (e) => signedOutOn401(e) }),
    defaultOptions: { queries: { retry: (count, e) => !(e instanceof ApiError && e.status < 500) && count < 2 } },
  });
  function signedOutOn401(error: unknown) {
    if (error instanceof ApiError && error.status === 401) client.setQueryData(["me"], null);
  }
  return client;
}

const queryClient = makeQueryClient();
const router = createBrowserRouter(routes);

export function App() {
  useTheme(); // applies the saved or system theme at start
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
