import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Link, createBrowserRouter } from "react-router";
import { RouterProvider } from "react-router/dom";

import { ApiError } from "./api/client";
import { AppShell } from "./components/AppShell";
import { useTheme } from "./lib/theme";
import { Home } from "./pages/Home";
import { Insights } from "./pages/Insights";
import { MoneyMajra } from "./pages/MoneyMajra";
import { Profile } from "./pages/Profile";
import { SignIn } from "./pages/SignIn";
import { Transactions } from "./pages/Transactions";

export const routes = [
  { path: "/sign-in", element: <SignIn /> },
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Home /> },
      { path: "transactions", element: <Transactions /> },
      { path: "money-majra", element: <MoneyMajra /> },
      { path: "insights", element: <Insights /> },
      { path: "profile", element: <Profile /> },
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
