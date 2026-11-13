import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, api, query } from "./client";
import type {
  Account, Dashboard, Health, ImportBatch, ImportDetail, MajraGroup, MajraGroupDetail, MajraPerson, MajraSummary,
  Recommendation, SplitMethod,
  Transaction, TransactionPage, UnusualList, User,
} from "./types";

/** The signed-in user, or null when signed out (a 401 is an answer, not an error). */
export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return await api<User>("/auth/me");
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null;
        throw error;
      }
    },
    staleTime: 60_000,
  });
}

export function useSignupOpen() {
  return useQuery({ queryKey: ["signup-status"], queryFn: () => api<{ signup_open: boolean }>("/auth/status") });
}

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: async () => (await fetch("/health")).json() as Promise<Health>,
    staleTime: Infinity,
  });
}

export function useSignIn(mode: "login" | "register") {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string; password: string }) =>
      api<{ user: User }>(`/auth/${mode}`, { body: { ...body, use_cookie: true } }),
    onSuccess: (result) => {
      client.clear(); // never show one person's cached data to another
      client.setQueryData(["me"], result.user);
    },
  });
}

export function useSignOut() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api<void>("/auth/logout", { method: "POST" }),
    onSettled: () => {
      client.clear();
      client.setQueryData(["me"], null);
    },
  });
}

export function useDashboard(month?: string) {
  return useQuery({ queryKey: ["dashboard", month ?? "latest"], queryFn: () => api<Dashboard>(`/dashboard${query({ month })}`) });
}

export interface TransactionFilters {
  q?: string;
  category?: string;
  account?: string;
  txn_type?: string;
}

export function useTransactions(filters: TransactionFilters, limit: number) {
  return useQuery({
    queryKey: ["transactions", filters, limit],
    queryFn: () => api<TransactionPage>(`/transactions${query({ ...filters, limit })}`),
    placeholderData: (previous) => previous,
  });
}

export function useCategories() {
  return useQuery({ queryKey: ["categories"], queryFn: () => api<string[]>("/categories") });
}

export function useAccounts() {
  return useQuery({ queryKey: ["accounts"], queryFn: () => api<Account[]>("/accounts") });
}

/** After any change to the ledger, everything derived from it is refetched. */
function useInvalidateLedger() {
  const client = useQueryClient();
  return () =>
    Promise.all(
      ["transactions", "dashboard", "categories", "accounts", "recommendations", "majra-summary"].map((key) =>
        client.invalidateQueries({ queryKey: [key] }),
      ),
    );
}

export function useCorrectTransaction() {
  const invalidate = useInvalidateLedger();
  return useMutation({
    mutationFn: ({ id, ...change }: { id: number; category?: string; txn_type?: string }) =>
      api<Transaction>(`/transactions/${id}`, { method: "PATCH", body: change }),
    onSuccess: invalidate,
  });
}

export function usePreviewImport() {
  return useMutation({
    mutationFn: ({ file, account, dayFirst }: { file: File; account?: string; dayFirst: boolean }) => {
      const form = new FormData();
      form.set("file", file);
      if (account) form.set("account", account);
      form.set("day_first", String(dayFirst));
      return api<ImportDetail>("/imports/preview", { form });
    },
  });
}

export function useFinishImport() {
  const invalidate = useInvalidateLedger();
  return useMutation({
    mutationFn: ({ id, action }: { id: number; action: "commit" | "discard" }) =>
      api<ImportBatch>(`/imports/${id}/${action}`, { method: "POST" }),
    onSuccess: invalidate,
  });
}

export function useRecommendations() {
  return useQuery({ queryKey: ["recommendations"], queryFn: () => api<Recommendation[]>("/recommendations") });
}

export function useMajraSummary() {
  return useQuery({ queryKey: ["majra-summary"], queryFn: () => api<MajraSummary[]>("/majra/summary") });
}

export function useMajraGroups() {
  return useQuery({ queryKey: ["majra-groups"], queryFn: () => api<MajraGroup[]>("/majra/groups") });
}

export function useMajraGroup(id: number) {
  return useQuery({ queryKey: ["majra-group", id], queryFn: () => api<MajraGroupDetail>(`/majra/groups/${id}`) });
}

export function useMajraPeople() {
  return useQuery({ queryKey: ["majra-people"], queryFn: () => api<MajraPerson[]>("/majra/people") });
}

/** Every Money Majra change returns the group's new state; keep it and refresh what depends on it. */
function useMajraChange<V>(fn: (vars: V) => Promise<MajraGroupDetail>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (detail) => {
      client.setQueryData(["majra-group", detail.group.id], detail);
      return Promise.all(
        ["majra-groups", "majra-summary", "dashboard", "recommendations"].map((key) =>
          client.invalidateQueries({ queryKey: [key] })),
      );
    },
  });
}

export function useAddPerson() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api<MajraPerson>("/majra/people", { body: { name } }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["majra-people"] }),
  });
}

export function useCreateGroup() {
  return useMajraChange((body: { name: string; member_ids: number[]; currency?: string }) =>
    api<MajraGroupDetail>("/majra/groups", { body }));
}

export interface ExpenseInput {
  groupId: number;
  description: string;
  date: string;
  amount: string;
  paid_by_id: number;
  split: { method: SplitMethod; participants: { person_id: number; value?: string }[] };
}

export function useAddExpense() {
  return useMajraChange(({ groupId, ...body }: ExpenseInput) =>
    api<MajraGroupDetail>(`/majra/groups/${groupId}/expenses`, { body }));
}

export interface PaymentInput {
  groupId: number;
  payer_id: number;
  receiver_id: number;
  amount: string;
  date: string;
  description: string;
  confirm_duplicate?: boolean;
}

export function useAddPayment() {
  return useMajraChange(({ groupId, ...body }: PaymentInput) =>
    api<MajraGroupDetail>(`/majra/groups/${groupId}/payments`, { body }));
}

export function useAddLoan() {
  return useMajraChange((body: { person_id: number; direction: "lent" | "borrowed"; amount: string; date: string; description: string }) =>
    api<MajraGroupDetail>("/majra/loans", { body }));
}

export function useVoidEntry() {
  return useMajraChange(({ id, reason }: { id: number; reason: string }) =>
    api<MajraGroupDetail>(`/majra/entries/${id}/void`, { body: { reason } }));
}

export function useUnusual() {
  return useQuery({ queryKey: ["unusual"], queryFn: () => api<UnusualList>("/ml/unusual") });
}

export function useDeleteAccount() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (password: string) => api<{ deleted: boolean }>("/auth/delete-account", { body: { password, confirm: true } }),
    onSuccess: () => {
      client.clear();
      client.setQueryData(["me"], null);
    },
  });
}
