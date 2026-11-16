export type Ticket = {
  id: string;
  status: string;
  title?: string;
  severity?: string;
  context?: string;
  expected?: string;
  created_at?: string | null;
  updated_at?: string | null;
  handled_at?: string | null;
  latest_run_id?: string | null;
  latest_kind?: string | null;
  latest_verdict?: string | null;
};

export type Settings = {
  subscription_status: string;
  ticket_retention_days: number | null;
  editable: boolean;
};

export type Job = {
  id: string;
  kind: string;
  status: string;
  ticket_id?: string | null;
  error?: string | null;
};
