// ── Health ────────────────────────────────────────────────────────────

export interface ServiceHealth {
  status: string;
  latency_ms?: number;
  error?: string | null;
}

export interface HealthResponse {
  status: string;
  services: Record<string, ServiceHealth>;
}

// ── Feedback ─────────────────────────────────────────────────────────

export interface FeedbackRequest {
  correction: string;
  previous_query: string;
  previous_response: string;
  user_id?: string;
  severity?: "LOW" | "MEDIUM" | "HIGH";
}

export interface FeedbackResponse {
  status: string;
  polarity: string;
  correction_id: number | null;
  micro_learning_triggered: boolean;
}

// ── Pipeline ─────────────────────────────────────────────────────────

export interface PipelineStage {
  count: number;
  total_value: number;
}

export interface PipelineResponse {
  pipeline: {
    stages: Record<string, PipelineStage>;
    total_count: number;
    total_value: number;
  };
}

// ── Deals with heat (for CRM dashboard sort) ─────────────────────────

export interface DealWithHeat {
  id: string;
  title: string;
  stage: string;
  value: number;
  currency?: string;
  machine_model?: string | null;
  created_at: string | null;
  updated_at: string | null;
  contact_id: string;
  contact_name: string | null;
  contact_email: string | null;
  company_name: string | null;
  account_summary?: string | null;
  heat_score: number;
  heat_label: "hot" | "warm" | "cold";
}

export interface DealsResponse {
  deals: DealWithHeat[];
  count: number;
}

// ── Vendors ──────────────────────────────────────────────────────────

export interface OverduePayable {
  id: string;
  vendor_name: string;
  invoice_number?: string;
  amount: number;
  currency?: string;
  due_date: string;
  days_overdue: number;
  description?: string;
}

export interface OverdueResponse {
  overdue: OverduePayable[];
  count: number;
}

// ── Email ────────────────────────────────────────────────────────────

export interface EmailSearchRequest {
  from_address?: string;
  to_address?: string;
  subject?: string;
  query?: string;
  after?: string;
  before?: string;
  max_results?: number;
}

export interface EmailResult {
  id: string;
  thread_id: string;
  from: string;
  to: string;
  subject: string;
  date: string;
  body: string;
}

export interface EmailSearchResponse {
  count: number;
  emails: EmailResult[];
}

export interface EmailThread {
  thread_id: string;
  messages: Array<{
    id: string;
    from: string;
    to: string;
    subject: string;
    date: string;
    body: string;
  }>;
}

// ── Board Meeting ────────────────────────────────────────────────────

export interface BoardMeetingRequest {
  topic: string;
  participants?: string[];
}

export interface BoardMeetingResponse {
  topic: string;
  participants: string[];
  contributions: Record<string, string>;
  synthesis: string;
  action_items: string[];
}

// ── Task Stream ──────────────────────────────────────────────────────

export interface TaskStreamCallbacks {
  onProgress: (event: TaskProgress) => void;
  onClarificationNeeded: (questions: string[], taskId: string) => void;
  onResult: (result: TaskResult) => void;
  onError: (error: string) => void;
}

export interface TaskProgress {
  type: string;
  task_id?: string;
  [key: string]: unknown;
}

export interface TaskResult {
  task_id: string;
  status: string;
  summary?: string;
  file_path?: string;
  file_format?: string;
}

export interface TaskState {
  task_id: string;
  status: string;
  goal?: string;
  output_format?: string;
  user_id?: string;
  [key: string]: unknown;
}

export interface TaskListResponse {
  count: number;
  tasks: TaskState[];
}

export interface TaskEventsResponse {
  task_id: string;
  count: number;
  events: TaskProgress[];
}
