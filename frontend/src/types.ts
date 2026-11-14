export type Ticket = {
  id: string;
  status: string;
  title?: string;
  severity?: string;
};

export type Job = {
  id: string;
  kind: string;
  status: string;
  ticket_id?: string | null;
  error?: string | null;
};
