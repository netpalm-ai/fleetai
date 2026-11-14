export type Ticket = {
  id: string;
  status: string;
  title?: string;
  severity?: string;
  context?: string;
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
