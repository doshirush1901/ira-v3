import useSWR from "swr";
import {
  fetchHealth,
  fetchPipeline,
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
