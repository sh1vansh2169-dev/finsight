// Hooks for duplicate review, category suggestions, unusual payments, budgets,
// commitments and the what-if simulator.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, query } from "./client";
import { useInvalidateLedger } from "./hooks";
import type {
  Budget, BudgetUse, Commitment, DuplicateCandidate, Recurring, Scenario, Simulation, Suggestions, Upcoming,
} from "./types";

// ---------------------------------------------------------------- duplicate review

export function useDuplicates(status: "open" | "all" = "open") {
  return useQuery({
    queryKey: ["duplicates", status],
    queryFn: () => api<DuplicateCandidate[]>(`/review/duplicates${query({ status })}`),
  });
}

/** ``keep`` is the record to keep when it is one payment; null means "two different payments". */
export function useResolveDuplicate() {
  const invalidate = useInvalidateLedger();
  return useMutation({
    mutationFn: ({ id, keep }: { id: number; keep: number | null }) =>
      api<DuplicateCandidate>(`/review/duplicates/${id}/resolve`, {
        body: keep === null ? { decision: "distinct" } : { decision: "duplicate", keep_transaction_id: keep },
      }),
    onSuccess: invalidate,
  });
}

export function useReopenDuplicate() {
  const invalidate = useInvalidateLedger();
  return useMutation({
    mutationFn: (id: number) => api<DuplicateCandidate>(`/review/duplicates/${id}/reopen`, { method: "POST" }),
    onSuccess: invalidate,
  });
}

export function useScanDuplicates() {
  const invalidate = useInvalidateLedger();
  return useMutation({
    mutationFn: () => api<{ new_candidates: number }>("/review/duplicates/scan", { method: "POST" }),
    onSuccess: invalidate,
  });
}

// ---------------------------------------------------------------- suggestions, unusual payments

export function useSuggestions() {
  return useQuery({ queryKey: ["suggestions"], queryFn: () => api<Suggestions>("/ml/category-suggestions") });
}

export function useDismissUnusual() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, note }: { id: number; note?: string }) =>
      api<void>(`/ml/unusual/${id}/dismiss`, { body: note ? { note } : {} }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["unusual"] }),
  });
}

// ---------------------------------------------------------------- budgets and commitments

/** Budgets and commitments feed Home, recommendations and the simulator: refresh them all. */
function usePlanChange<V, R>(fn: (vars: V) => Promise<R>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () =>
      Promise.all(
        ["budgets", "budget-usage", "dashboard", "recommendations", "commitments", "recurring", "upcoming", "simulation"]
          .map((key) => client.invalidateQueries({ queryKey: [key] })),
      ),
  });
}

export function useBudgets() {
  return useQuery({ queryKey: ["budgets"], queryFn: () => api<Budget[]>("/budgets") });
}

export function useBudgetUsage() {
  return useQuery({ queryKey: ["budget-usage"], queryFn: () => api<BudgetUse[]>("/budgets/usage") });
}

export function useSetBudget() {
  return usePlanChange((body: { category: string; monthly_limit: string }) => api<Budget>("/budgets", { method: "PUT", body }));
}

export function useDeleteBudget() {
  return usePlanChange((id: number) => api<void>(`/budgets/${id}`, { method: "DELETE" }));
}

export function useRecurring() {
  return useQuery({ queryKey: ["recurring"], queryFn: () => api<Recurring[]>("/recurring") });
}

export function useCommitments() {
  return useQuery({ queryKey: ["commitments"], queryFn: () => api<Commitment[]>("/commitments") });
}

export function useUpcoming(days = 30) {
  return useQuery({ queryKey: ["upcoming", days], queryFn: () => api<Upcoming>(`/commitments/upcoming${query({ days })}`) });
}

export function useConfirmRecurring() {
  return usePlanChange((key: string) => api<Commitment>("/commitments/confirm", { body: { key } }));
}

export interface CommitmentInput {
  name: string;
  direction: "debit" | "credit";
  amount: string;
  cadence: string;
  next_due: string;
  category?: string;
}

export function useAddCommitment() {
  return usePlanChange((body: CommitmentInput) => api<Commitment>("/commitments", { body }));
}

export function useUpdateCommitment() {
  return usePlanChange(({ id, ...change }: { id: number; status: "active" | "paused" | "ended" }) =>
    api<Commitment>(`/commitments/${id}`, { method: "PATCH", body: change }));
}

// ---------------------------------------------------------------- what-if

export interface SimulationInput {
  horizon_days: number;
  starting_balance?: string;
  scenarios: Scenario[];
}

export function useSimulation(input: SimulationInput) {
  return useQuery({
    queryKey: ["simulation", input],
    queryFn: () => api<Simulation>("/simulate", { body: input }),
    placeholderData: (previous) => previous,
  });
}

// ---------------------------------------------------------------- assistant

export interface AssistantStatus {
  available: boolean;
  model: string;
  message: string;
}

export interface AssistantAnswer {
  answer: string;
  unverified_figures: string[];
  tool_calls: { name: string; arguments: unknown; result: unknown }[];
  stopped_early: boolean;
  model: string;
}

export function useAssistantStatus() {
  return useQuery({ queryKey: ["assistant-status"], queryFn: () => api<AssistantStatus>("/assistant/status"), staleTime: 30_000 });
}

export function useAsk() {
  return useMutation({
    mutationFn: (body: { question: string; history: { role: "user" | "assistant"; content: string }[] }) =>
      api<AssistantAnswer>("/assistant/ask", { body }),
  });
}
