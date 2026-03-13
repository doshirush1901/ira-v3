import useSWR from "swr";
import {
  fetchHealth,
  fetchPipeline,
  fetchDeals,
  fetchVendorsOverdue,
  fetchAgents,
} from "./api";

export function useHealth() {
  return useSWR("health", fetchHealth, {
    refreshInterval: 30_000,
    errorRetryCount: 2,
  });
}

export function usePipeline() {
  return useSWR("pipeline", fetchPipeline, {
    refreshInterval: 60_000,
  });
}

export function useDeals(sort: "heat_desc" | "heat_asc" = "heat_desc") {
  return useSWR(["deals", sort], () => fetchDeals(sort), {
    refreshInterval: 60_000,
  });
}

export function useVendorsOverdue() {
  return useSWR("vendors-overdue", fetchVendorsOverdue, {
    refreshInterval: 60_000,
  });
}

export function useAgents() {
  return useSWR("agents", fetchAgents, {
    revalidateOnFocus: false,
  });
}
